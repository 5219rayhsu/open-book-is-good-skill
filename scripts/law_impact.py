#!/usr/bin/env python3
"""比對新舊 anchor pack，列出修法後受影響的已上線詳解（零 token）。

用途：月維護。`anchor_pack.py --check` 報某法過期 → `--build` 重建 →
本腳本比對「重建前備份的 pack」與「新 pack」，找出條文有異動的條號，
再掃已發佈的 explanations.json，列出引用到這些條號的 qid。

只讀不寫任何題庫檔；輸出一份 law_impact_<date>.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anchor_pack import extractCitations, loadExplanationItems  # noqa: E402


def diffPack(oldPack: dict[str, Any], newPack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """回傳 {法名: {amended: [條號], added: [...], removed: [...], old_date, new_date}}，只收有變動的法。"""
    changes: dict[str, dict[str, Any]] = {}
    for law, newLaw in newPack.items():
        oldLaw = oldPack.get(law)
        if oldLaw is None:
            changes[law] = {
                "old_date": None,
                "new_date": newLaw.get("amend_date"),
                "amended": [],
                "added": sorted(newLaw.get("articles", {})),
                "removed": [],
            }
            continue
        oldArts = oldLaw.get("articles", {})
        newArts = newLaw.get("articles", {})
        amended = sorted(a for a in newArts if a in oldArts and newArts[a] != oldArts[a])
        added = sorted(a for a in newArts if a not in oldArts)
        removed = sorted(a for a in oldArts if a not in newArts)
        if amended or added or removed or oldLaw.get("amend_date") != newLaw.get("amend_date"):
            changes[law] = {
                "old_date": oldLaw.get("amend_date"),
                "new_date": newLaw.get("amend_date"),
                "amended": amended,
                "added": added,
                "removed": removed,
            }
    return changes


def impactedItems(
    explPath: Path, changes: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """掃已上線詳解，列出引用到異動／新增／刪除條號的 qid。"""
    touched = {
        law: set(info["amended"]) | set(info["added"]) | set(info["removed"])
        for law, info in changes.items()
    }
    lawNames = [law for law, arts in touched.items() if arts]
    if not lawNames:
        return []
    hits: list[dict[str, Any]] = []
    for qid, text in loadExplanationItems(explPath):
        refs = sorted(
            {
                (c.law, c.art)
                for c in extractCitations(text, lawNames)
                if c.art in touched.get(c.law, ())
            }
        )
        if refs:
            hits.append(
                {
                    "qid": qid,
                    "refs": [
                        {
                            "law": law,
                            "art": art,
                            "kind": (
                                "amended"
                                if art in changes[law]["amended"]
                                else "added"
                                if art in changes[law]["added"]
                                else "removed"
                            ),
                        }
                        for law, art in refs
                    ],
                }
            )
    return hits


def selftest() -> int:
    oldPack = {"測試法": {"amend_date": "2026-01-01", "articles": {"10": "三十日", "11": "不變", "12": "將被刪"}}}
    newPack = {"測試法": {"amend_date": "2026-07-22", "articles": {"10": "六十日", "11": "不變", "13": "新增"}}}
    changes = diffPack(oldPack, newPack)
    tests = [
        ("改動條被抓到", changes["測試法"]["amended"] == ["10"]),
        ("未改動條不入列", "11" not in changes["測試法"]["amended"]),
        ("新增條被抓到", changes["測試法"]["added"] == ["13"]),
        ("刪除條被抓到", changes["測試法"]["removed"] == ["12"]),
        ("無變動的法不入列", diffPack(oldPack, oldPack) == {}),
    ]
    for name, passed in tests:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return 0 if all(p for _, p in tests) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, help="重建前的 pack 備份")
    parser.add_argument("--new", type=Path, help="重建後的 pack")
    parser.add_argument("--expl", type=Path, help="已發佈的 explanations.json")
    parser.add_argument("--out", type=Path, help="輸出 law_impact_<date>.json")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    missing = [n for n in ("old", "new", "expl", "out") if getattr(args, n) is None]
    if missing:
        parser.error("--selftest 以外的模式需要 --old/--new/--expl/--out")

    oldPack = json.loads(args.old.read_text(encoding="utf-8"))
    newPack = json.loads(args.new.read_text(encoding="utf-8"))
    changes = diffPack(oldPack, newPack)
    items = impactedItems(args.expl, changes)
    result = {
        "old_pack": str(args.old),
        "new_pack": str(args.new),
        "explanations": str(args.expl),
        "changes": changes,
        "impacted": items,
        "summary": {
            "laws_changed": len(changes),
            "articles_touched": sum(
                len(c["amended"]) + len(c["added"]) + len(c["removed"]) for c in changes.values()
            ),
            "impacted_items": len(items),
        },
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
