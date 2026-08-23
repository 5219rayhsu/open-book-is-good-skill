#!/usr/bin/env python3
"""找出解不到目標節的「見 §X」引用。零依賴、零 token。

為什麼需要一支程式：`check_section_ids.py` 只驗證節號本身不撞號，不驗證
**引用**指向的節是否真的存在。改編號、砍節、搬檔名，都會讓舊引用變成
一句語法正確、語意錯誤的死鏈——讀者跟著「見 §24」翻過去，那裡什麼都沒有，
但沒有任何工具會報錯。

引用型式分兩種（正規化空白／全形都要能認）：
  (a) 帶檔名（qualified）：`<name>.md §<id>`，或 `<name>.md` 後 12 字內出現
      `§<id>`／`<id>`；範圍 `§2–§12` 只查頭尾兩個節。
  (b) 不帶檔名（bare）：`§<id>`，且該行 `§` 前 40 字內沒有 `.md`
      →對象是**同一份檔案**。

目標節：`^##+ §?<id>[、.]?\\s`（`## 24.`／`## §24`／`### 21.7`／`## 四、`／
`## §F′` 都算）。忽略 code fence 內與 `rg `／`grep ` 開頭的行。

🔴 id 判準不能只認純數字：`2.1a`（reviewer-input-parity.md §2.1a）這種「子節
+ 字母」是真實存在的節號，第一版 regex 收尾只認 `[、.]` 或空白，`a` 卡在中間
直接連整條 HEADING 都配不到——那一節從此在查核範圍裡憑空消失。
同理 `### 1)` 這種右括號收尾（figures.md）也要能配到。

🔴 帶點號的 id 不能無腦全收：`著作權法 §9.1.5` 長得像節號但其實是法條，
真的把它當節號查會產生假警報。但也不能無腦全砍：`explanations-redteam.md
§3.0.1` 是真實存在的節。折衷是分層處理——**建目標表時完全不過濾**（`### §3.0.1`
照樣正常登記，因為它真的是一節）；**只在判斷「這是不是一條合法引用」時**才用
兩條互相獨立的規則跳過：id 帶 3 段以上數字（2 個點），或整行含『著作權法』——
兩條是 OR 不是 AND，因為「著作權法 §9」（0 個點）跟「§9.1.5」（不提著作權法三字，
只是另一句法條引文）各自只踩中一條，第一版寫成 AND 兩條都漏抓，兩種假警報都放出來了。

🔴 目標節的判準不能只認「##+ §id」緊接著：本庫真實存在 `### 🔴 §11.1 …` 這種
「## + emoji 標記 + §id」的寫法（🔴＝血淚教訓、🛠＝配套工具），第一版沒放行 emoji，
`parsing.md` 裡一整串 §11.1／§11.2／§11.4～§11.6／§14／§16／§18／§19～§21 的真實子節
全部從查核範圍消失，害得所有指向它們的引用（跨檔＋站內）被錯判成斷鏈。

用法：check_section_refs.py [根目錄，預設本檔上一層]  → 有斷鏈就 exit 1
"""
import pathlib
import re
import sys

NUM = r"\d+(?:\.\d+)*[a-z]?[′″]?"          # 24 / 21.7 / 12′ / 2.1a / 3.0.1
ALPHA = r"[A-Z]{1,2}\d*[′″]?"               # H / A3 / F′ / AA
# 🔴 原本寫 `[A-Z]`（單字母）。字母用到 Y 之後就會有人鑄 §AA——而**雙字母 id 的
# 標題整個匹配不到**，於是指向它的引用一律回報「查無此節」，指向 §A 這種不存在的 id。
# 這正是 gates-lessons §Y 自己寫的那條：id 空間的形狀要從真實檔案枚舉，不要假設。
# 枚舉指令：rg -oh '^#{2,3} §?[0-9A-Z.′″]*' references/ | sort -u
CJK = r"[一二三四五六七八九十百千萬]+"        # 四
ID = rf"(?:{NUM}|{ALPHA}|{CJK})"

# 目標節：行首 `##+`，可選「🔴／🛠 標記」，可選 `§`，id，收尾是全／半形頓號句點
# 右括號，或空白／行尾。
HEADING_RE = re.compile(rf"^##+\s+(?:[🔴🛠]\s+)?§?({ID})(?:[、.)）]|(?=\s|$))", re.M)
FILE_RE = r"[\w\-一-龥]+\.md"
# 間隔不跨句界（。！？）也不跨表格欄界（|）——否則會把下一句開頭的年份數字
# 或表格下一欄的字母，誤認成同一個引用的 id。
QUALIFIED_RE = re.compile(rf"({FILE_RE})[^。！？|]{{0,12}}?§?({ID})")
BARE_RE = re.compile(rf"§({ID})")
RANGE_TAIL_RE = re.compile(rf"^[–-]§?({ID})")

TARGET_GLOBS = [("references", "*.md"), (".", "SKILL.md"),
                 ("examples", "*.md"), ("docs/adr", "*.md")]


CJK_ONLY_RE = re.compile(rf"^{CJK}$")


def is_multi_dot(id_: str) -> bool:
    return id_.count(".") >= 2


def is_unmarked_cjk(id_: str, line: str, id_start: int) -> bool:
    # 🔴 CJK 數字（一二三…）在中文散文裡到處都是（「同一條」「二話不說」），
    # 沒有 § 開頭時不能當節號——這條只擋 qualified 分支：bare 分支的 regex
    # 本來就強制吃一個 `§`，天生免疫；qualified 分支的 `§?` 是可選的，才會中招
    # （實測案例：batching-and-measurement.md「是同一條律」被誤配成 §一）。
    return bool(CJK_ONLY_RE.match(id_)) and line[id_start - 1] != "§"


def target_files(root: pathlib.Path) -> list[pathlib.Path]:
    files = []
    for sub, pattern in TARGET_GLOBS:
        files.extend(sorted((root / sub).glob(pattern)))
    return files


def heading_ids(text: str) -> set[str]:
    return set(HEADING_RE.findall(text))


def check_ref(fname: str, id_: str, headings: dict[str, set], src: pathlib.Path,
               lineno: int, out: list[str]) -> None:
    ids = headings.get(fname)
    if ids is None or id_ in ids:
        return
    out.append(f"🔴 {src.name}:{lineno} → {fname} §{id_}（查無此節）")


def scan_file(src: pathlib.Path, headings: dict[str, set]) -> list[str]:
    out: list[str] = []
    in_code = False
    for lineno, line in enumerate(src.read_text().splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(("rg ", "grep ")):
            continue
        if "著作權法" in line:
            continue
        consumed = []
        for m in QUALIFIED_RE.finditer(line):
            fname, id_ = m.group(1), m.group(2)
            if is_multi_dot(id_) or is_unmarked_cjk(id_, line, m.start(2)):
                continue
            consumed.append((m.start(2), m.end(2)))
            check_ref(fname, id_, headings, src, lineno, out)
            tail = RANGE_TAIL_RE.match(line[m.end():])
            if tail and not is_multi_dot(tail.group(1)) and \
                    not is_unmarked_cjk(tail.group(1), line, m.end() + tail.start(1)):
                check_ref(fname, tail.group(1), headings, src, lineno, out)
        for m in BARE_RE.finditer(line):
            id_, start = m.group(1), m.start(1)
            if is_multi_dot(id_):
                continue
            if any(a <= start < b for a, b in consumed):
                continue
            if ".md" in line[max(0, m.start() - 40):m.start()]:
                continue
            check_ref(src.name, id_, headings, src, lineno, out)
    return out


def selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "references").mkdir()
        a = root / "references" / "a.md"
        b = root / "references" / "b.md"
        a.write_text("## 1. A\n## §H B\n### 2.1a C\n")

        # qualified ok
        b.write_text("見 `a.md` §1 那節\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # qualified broken
        b.write_text("見 `a.md` §99 那節\n")
        assert len(scan_file(b, {"a.md": heading_ids(a.read_text())})) == 1
        # bare ok（同檔）
        a2 = root / "references" / "a2.md"
        a2.write_text("## 5. X\n見上面 §5 那節\n")
        assert scan_file(a2, {"a2.md": heading_ids(a2.read_text())}) == []
        # bare broken
        a3 = root / "references" / "a3.md"
        a3.write_text("## 5. X\n見上面 §9 那節\n")
        assert len(scan_file(a3, {"a3.md": heading_ids(a3.read_text())})) == 1
        # code fence 內忽略
        b.write_text("```\n見 `a.md` §99\n```\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # 質數 id ok
        b.write_text("見 `a.md` §H 那節\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # 子節 + 字母 id ok
        b.write_text("見 `a.md` §2.1a 那節\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # 著作權法 §9.1.5 跳過（不當節號查；兩條規則各自單獨成立）
        b.write_text("依著作權法 §9.1.5 不受保護\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # 只有點數夠多（無著作權法字樣）也要跳過
        b.write_text("見 `a.md` §9.1.5 那節\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # 只有著作權法字樣（id 本身沒有點）也要跳過，不可誤判成 bare §9 斷鏈
        b.write_text("依著作權法 §9 不受保護\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # emoji 標記＋§id 的子節要能被登記成目標（不是查核範圍外的裝飾字）
        c = root / "references" / "c.md"
        c.write_text("### 🔴 §11.1 偵測器回報 0 筆\n")
        b.write_text("見 `c.md` §11.1 那節\n")
        assert scan_file(b, {"c.md": heading_ids(c.read_text())}) == []
        # 裸 CJK 數字（無 §）只是散文用字，不可誤配成節號引用
        b.write_text("見 `a.md` 是同一條律\n")
        assert scan_file(b, {"a.md": heading_ids(a.read_text())}) == []
        # 🔴 雙字母 id（§AA）：字母用到 Y 之後就會出現。單字母正則會讓
        # **標題本身匹配不到**，於是指向它的引用全部回報「查無此節」。
        aa = root / "references" / "aa.md"
        aa.write_text("## §AA 兩個字母的節\n\n## §AB 另一節\n")
        b.write_text("見 `aa.md` §AA 與 `aa.md` §AB。\n")
        assert scan_file(b, {"aa.md": heading_ids(aa.read_text())}) == [], "雙字母 id 誤報"
        b.write_text("見 `aa.md` §AZ。\n")
        assert len(scan_file(b, {"aa.md": heading_ids(aa.read_text())})) == 1, "雙字母真斷鏈沒抓到"

    print("=== check_section_refs selftest PASS（12 案例）===")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else \
        pathlib.Path(__file__).resolve().parent.parent
    files = target_files(root)
    headings = {f.name: heading_ids(f.read_text()) for f in files}
    broken = 0
    for f in files:
        for line in scan_file(f, headings):
            print(line)
            broken += 1
    print(f"掃了 {len(files)} 份，斷鏈 {broken} 條")
    sys.exit(1 if broken else 0)
