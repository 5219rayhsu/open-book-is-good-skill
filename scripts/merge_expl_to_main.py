#!/usr/bin/env python3
"""把 staging 詳解目錄(每檔 {qid:{t,c}})idempotent 併入 explanations.json。

- 逐檔 json.load 驗合法(壞檔報錯跳過,不污染正本);entry 須有非空 t 與 c∈{high,med,low}。
- qid upsert;併前備份 explanations.json → .bak;併後重讀驗合法、更新 meta.count。
- 可選 --cover bank 子集檢查(該 exam/subject 是否 100% 有詳解)。

用法:uv run python3 scripts/merge_expl_to_main.py data/_stage/自然_expl [會考 自然]
"""
from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPL = ROOT / "data" / "explanations.json"
BANK = ROOT / "data" / "bank.json"
VALID_C = {"high", "med", "low"}


def main(stage_dir: str, exam: str | None = None, subject: str | None = None) -> None:
    sd = Path(stage_dir)
    files = sorted(sd.glob("*.json"))
    if not files:
        raise SystemExit("staging 目錄無 .json:%s" % stage_dir)

    doc = json.loads(EXPL.read_text(encoding="utf-8"))
    inner = doc["explanations"]

    added = replaced = bad = 0
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print("壞檔跳過:%s (%s)" % (f.name, e)); bad += 1; continue
        for qid, ent in data.items():
            t = (ent or {}).get("t", "")
            c = (ent or {}).get("c", "")
            if not isinstance(t, str) or not t.strip() or c not in VALID_C:
                print("略過格式異常:%s %r" % (qid, ent)); bad += 1; continue
            if qid in inner:
                replaced += 1
            else:
                added += 1
            inner[qid] = {"t": t.strip(), "c": c}

    shutil.copy2(EXPL, EXPL.with_suffix(".json.bak"))
    doc["meta"]["count"] = len(inner)
    EXPL.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    re = json.loads(EXPL.read_text(encoding="utf-8"))   # 重讀驗合法
    print("併入詳解:新增 %d、取代 %d、壞/異常 %d;explanations.json 現 %d 筆(JSON 合法✓)" % (
        added, replaced, bad, len(re["explanations"])))

    if exam and subject:
        bank = json.loads(BANK.read_text(encoding="utf-8"))["questions"]
        sub = [q["qid"] for q in bank if q["exam"] == exam and q["subject"] == subject]
        have = sum(1 for qid in sub if qid in re["explanations"])
        print("覆蓋 %s/%s:%d/%d %s" % (exam, subject, have, len(sub),
                                       "✓" if have == len(sub) else "⚠ 仍有缺"))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        raise SystemExit("用法:python3 scripts/merge_expl_to_main.py <staging_dir> [exam subject]")
    main(a[0], a[1] if len(a) > 1 else None, a[2] if len(a) > 2 else None)
