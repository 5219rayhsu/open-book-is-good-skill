#!/usr/bin/env python3
"""掃大考中心(ceec)一般試題列表(分頁 1~19),蒐集學測數學A/數學B/自然的「試卷＋答案」
PDF 連結(111~115),建對照表 data/raw/ceec_dl_urls.json。預設只掃描列印,加 --download 才下載。

檔名線索:「03-114學測數學a試題.pdf」「03-115學測數學a試卷.pdf」「03-115學測數學a答案.pdf」。
要的:試卷/試題(題目卷,非答題卷、非評分原則);答案(標準答案,非答題卷)。
排除:答題卷(空白作答卷)、非選擇題參考答案、評分原則、答案卡。
著作權:§9 不受保護。用法:uv run --with requests python3 scripts/scrape_ceec_math.py [--download]
"""
from __future__ import annotations
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LIST = "https://www.ceec.edu.tw/xmfile?xsmsid=0J052424829869345634&page=%d"
PAGES = range(1, 20)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
YEARS = {"111", "112", "113", "114", "115"}
# 檔名子字串 → 標準科目鍵。NFKC 已折全形字母,故只需列半形;含「數a/數b」省「學」變體
# (ceec 113 數A 真實檔名「03-113學測數a試題定稿.pdf」就是這樣漏抓的)。見
# open-book-is-good-skill/references/dirty-data-robustness.md。
SUBJ = [("數學a", "數學A"), ("數a", "數學A"), ("數學b", "數學B"), ("數b", "數學B"), ("自然", "自然")]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def classify(fn: str):
    """回 (year, subject, kind) 或 None。kind ∈ {試卷, 答案}。"""
    # NFKC 先折全形英數/空白(數學ａ→數學a、Ａ→A),再轉小寫,避免變體漏抓。
    low = unicodedata.normalize("NFKC", fn).lower()
    ym = re.search(r"(1[0-9]{2})\s*學測", low)
    if not ym or ym.group(1) not in YEARS:
        return None
    year = ym.group(1)
    subj = next((s for key, s in SUBJ if key in low), None)
    if not subj:
        return None
    # 排除非目標
    if "答題卷" in fn or "非選" in fn or "評分" in fn or "答案卡" in fn or "特色" in fn:
        # 「答案」要保留,但「非選擇題參考答案」排除(上面 非選 already 擋)
        if "答案" in fn and "答題卷" not in fn and "非選" not in fn and "卡" not in fn:
            pass
        else:
            return None
    if "答案" in fn:
        return (year, subj, "答案")
    if "試卷" in fn or "試題" in fn:
        return (year, subj, "試卷")
    return None


def main(download: bool) -> None:
    found = {}  # (year,subj,kind) -> url
    for p in PAGES:
        try:
            html = fetch(LIST % p)
        except Exception as e:  # noqa: BLE001
            print("page %d 失敗:%s" % (p, e), file=sys.stderr)
            continue
        for u in re.findall(r'''href=["']([^"']*file_pool[^"']*\.pdf)["']''', html, re.I):
            u = u.replace("&amp;", "&")
            if u.startswith("http"):
                url = u
            elif u.startswith("/"):
                url = "https://www.ceec.edu.tw" + u
            else:
                url = "https://www.ceec.edu.tw/" + u
            fn = urllib.parse.unquote(u.split("/")[-1])
            c = classify(fn)
            if c and c not in found:
                found[c] = url
    # 零筆守門:命名/版面漂移或 SSL 全失敗時,絕不寫出空 JSON 覆蓋上次成功的對照表。
    if not found:
        print("0 筆 PDF 符合條件,終止寫入以免覆蓋 ceec_dl_urls.json", file=sys.stderr)
        sys.exit(1)
    # 對照表
    table = {}
    for (year, subj, kind), url in found.items():
        table.setdefault(year, {}).setdefault(subj, {})[kind] = url
    (RAW / "ceec_dl_urls.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print("覆蓋(試卷/答案):")
    for y in sorted(YEARS):
        row = table.get(y, {})
        cells = []
        for s in ("數學A", "數學B", "自然"):
            d = row.get(s, {})
            cells.append("%s[%s%s]" % (s, "卷" if d.get("試卷") else "-", "案" if d.get("答案") else "-"))
        print("  %s: %s" % (y, " ".join(cells)))

    if not download:
        print("\n(只掃描;加 --download 下載)")
        return

    import requests
    RAW.mkdir(parents=True, exist_ok=True)
    SUBJ_STEM = {"數學A": "數學A", "數學B": "數學B", "自然": "自然"}
    ok = skip = fail = 0
    for (year, subj, kind), url in sorted(found.items()):
        stem = "試題" if kind == "試卷" else "答案"
        out = RAW / ("%s_%s_%s.pdf" % (year, SUBJ_STEM[subj], stem))
        if out.exists() and out.stat().st_size > 1024 and out.read_bytes()[:4] == b"%PDF":
            skip += 1
            continue
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            out.write_bytes(r.content)
            if out.read_bytes()[:4] == b"%PDF":
                print("%s: %dKB ✓" % (out.name, len(r.content) // 1024)); ok += 1
            else:
                print("%s: 非PDF✗" % out.name); fail += 1
        except Exception as e:  # noqa: BLE001
            print("%s: 失敗 %s" % (out.name, e)); fail += 1
    print("\n下載小結:成功 %d、略過 %d、失敗 %d" % (ok, skip, fail))


if __name__ == "__main__":
    main("--download" in sys.argv)
