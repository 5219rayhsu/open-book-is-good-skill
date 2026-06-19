#!/usr/bin/env python3
"""把 staging 題庫(data/_stage/cap_{科}.json)idempotent 併入正本 data/bank.json。

- qid-keyed upsert:已存在的 qid 就地取代,新 qid 附加在尾端(既有題目順序不動 →
  純文字 diff 最小、可 delta)。
- 併前自動備份 bank.json → bank.json.bak;併後重新 json.load 驗合法 + 檢查無重複 qid。
- 只動 questions;meta 加一筆 cap 科目紀錄(資訊性,app 由 questions 自行 derive)。

用法:uv run python3 scripts/merge_cap_to_bank.py data/_stage/cap_自然.json
"""
from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "data" / "bank.json"


def main(stage_path: str) -> None:
    stage = json.loads(Path(stage_path).read_text(encoding="utf-8"))
    if not isinstance(stage, list) or not stage:
        raise SystemExit("staging 不是非空陣列:%s" % stage_path)

    bank = json.loads(BANK.read_text(encoding="utf-8"))
    qs = bank["questions"]
    idx = {q["qid"]: i for i, q in enumerate(qs)}

    added = replaced = 0
    for q in stage:
        qid = q["qid"]
        if qid in idx:
            qs[idx[qid]] = q
            replaced += 1
        else:
            idx[qid] = len(qs)
            qs.append(q)
            added += 1

    # 備份 → 寫回
    shutil.copy2(BANK, BANK.with_suffix(".json.bak"))
    BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=1), encoding="utf-8")

    # 併後驗證:重讀合法、無重複 qid
    re = json.loads(BANK.read_text(encoding="utf-8"))
    ids = [q["qid"] for q in re["questions"]]
    assert len(ids) == len(set(ids)), "出現重複 qid!"

    subj = stage[0].get("subject", "?")
    exam = stage[0].get("exam", "?")
    nfig = sum(1 for q in stage if q.get("figure"))
    print("併入 %s/%s:新增 %d、取代 %d(staging %d 題,其中 %d 題有圖)" % (
        exam, subj, added, replaced, len(stage), nfig))
    print("bank.json 現有 %d 題;備份 → bank.json.bak;JSON 合法、無重複 qid ✓" % len(ids))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法:python3 scripts/merge_cap_to_bank.py <staging.json>")
    main(sys.argv[1])
