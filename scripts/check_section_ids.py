#!/usr/bin/env python3
"""references/*.md 的節號不得重複。零依賴、零 token。

為什麼需要一支程式：2026-08-23 一天內撞號兩次——`batching-and-measurement.md`
同時有兩個 §24 與兩個 §25，`gates.md` 的 §H 被兩節共用。兩次都是**碰巧**發現的
（一次是重複插入的副作用，一次是臨時寫的斷言剛好擋下）。

撞號的危害不是難看，是**引用失效而且不會報錯**：「見 §24」在有兩個 §24 的檔案裡
仍然是一句合法的句子，讀者會讀到先出現的那一節，然後得到一個看起來合理的結論。

判準刻意分兩種，因為兩種節號的合法子節形式不同：
  數字節：`## 24.`；`## 24.1` 這種子節不算重複（另計）。
  字母節：`## §H `；`## §A1` 這種子節不算重複（另計）。

用法：check_section_ids.py [references 目錄]   → 有撞號就 exit 1 並逐條列出
"""
import collections
import pathlib
import re
import sys

# 🔴 判準要正規化**識別字**，不是比對語法。第一版分開寫 `## 24.` 與 `## §H `
# 兩條 regex，結果漏掉當天真實發生過的那次撞號——因為同一份檔裡還有第三種寫法
# `## §24`（帶 § 卻是數字、且沒有句點），它兩條都不中。
# 「§」與句點都只是裝飾，`24` 才是識別字；`24.1` 與 `§A1` 是子節，不是重複。
#
# 🔴 質數記號（′ U+2032／″ U+2033）也是識別字的一部分，不是裝飾：`12′` 與 `12″`
# 是兩個不同的節（見 batching-and-measurement.md §12′、gates.md §F′）。第一版的
# `\b` 收尾在質數記號後面就斷了——`′`／`″` 不是 word char，「質數記號→空白」不算
# word boundary，導致 `## 12′ …` 整行連 SEC 都配不到，直接從查核範圍消失（既不算
# 重複，也不算不重複，是真正的假陰性）。改成跟 SUBSEC 一致的 `(?=\s)` 前瞻收尾。
SEC = re.compile(r"^## §?(\d+[′″]?|[A-Z][′″]?)(?:\.(?=\s)|(?=\s))", re.M)

# `### ` id 只在同一個 `## ` 父節底下才算重複——`## 1.` 底下的 `### 1.1` 跟
# `## 2.` 底下的 `### 1.1` 是不同東西，key 要帶父節號。子節只認 `數字.數字` 形式
# （21.5 這種），不含字母子節（那種目前沒有真實案例，YAGNI）。
#
# 🔴 2026-08-23 首次實跑就撞了假陽性：explanations-redteam.md 同一個 §5 底下有
# `### 5.2`／`### 5.2′`／`### 5.2″` 三個不同子節（依序防「中文混半形」「拉丁字
# 混全形」「規則互撞」），舊版 `\b` 收尾不吃質數記號，三個都被正規化成同一個
# `5.2`，報成撞號 ×3。跟 SEC 同一個病灶：`\b` 在質數記號後面不成立，改成
# `(?=\s)` 前瞻，並把質數記號收進捕獲群組讓它真正參與識別字比對。
SUBSEC = re.compile(r"^### (\d+\.\d+[′″]?)(?=\s)", re.M)


def dupes(text: str) -> list[str]:
    return sorted(f"{k} ×{n}" for k, n in collections.Counter(SEC.findall(text)).items() if n > 1)


def sub_dupes(text: str) -> list[str]:
    parent = None
    counts: collections.Counter = collections.Counter()
    for line in text.splitlines():
        m = SEC.match(line)
        if m:
            parent = m.group(1)
            continue
        m2 = SUBSEC.match(line)
        if m2:
            counts[(parent, m2.group(1))] += 1
    return sorted(f"{sub} ×{n} (under ## {parent}.)"
                  for (parent, sub), n in counts.items() if n > 1)


def selftest() -> None:
    assert dupes("## 24. a\n## 25. b\n") == []
    assert dupes("## 24. a\n## 24. b\n") == ["24 ×2"]
    assert dupes("## §H a\n## §I b\n") == []
    assert dupes("## §H a\n## §H b\n") == ["H ×2"]
    # 🔴 混用寫法仍算同一節：`## 24.` 與 `## §24` 是同一個識別字。
    #    這一條是拿當天真實漏掉的那次撞號回填的——第一版在它身上是綠的。
    assert dupes("## 24. a\n## §24 b\n") == ["24 ×2"]
    assert dupes("## §24 a\n## §25 b\n") == []
    # 子節不算重複：§A 與 §A1、24 與 24.1 是不同的東西
    assert dupes("## §A a\n## §A1 b\n## §A2 c\n") == []
    assert dupes("## 24. a\n## 24.1 b\n") == []
    # 內文提到 §H 不算節（必須行首 `## `）
    assert dupes("## §H a\n見 §H 那節\n") == []
    # ### 子節撞號：同一父節下重複才算
    assert sub_dupes("## 21. a\n### 21.5 x\n### 21.5 y\n") == ["21.5 ×2 (under ## 21.)"]
    # 不同父節底下的同號子節不算重複
    assert sub_dupes("## 1. a\n### 1.1 x\n## 2. b\n### 1.1 y\n") == []
    # 🔴 回填 2026-08-23 首跑撞的假陽性：質數記號讓 5.2／5.2′／5.2″ 是三個不同子節
    assert sub_dupes("## 5. a\n### 5.2 x\n### 5.2′ y\n### 5.2″ z\n") == []
    # 但質數記號本身重複仍要被抓到——不是「有質數記號就一律放行」
    assert sub_dupes("## 5. a\n### 5.2′ x\n### 5.2′ y\n") == ["5.2′ ×2 (under ## 5.)"]
    # SEC 層也要吃質數記號：`## 12′` 與 `## 12″` 是兩個不同節，不是同一個 12
    assert dupes("## 12′ a\n## 12″ b\n") == []
    assert dupes("## 12′ a\n## 12′ b\n") == ["12′ ×2"]
    print("=== check_section_ids selftest PASS（15 案例）===")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest(); sys.exit(0)
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                        pathlib.Path(__file__).resolve().parent.parent / "references")
    bad = 0
    for f in sorted(root.glob("*.md")):
        text = f.read_text()
        d = dupes(text) + sub_dupes(text)
        if d:
            bad += 1
            print(f"🔴 {f.name}: 節號重複 {', '.join(d)}")
    print(f"掃了 {len(list(root.glob('*.md')))} 份，撞號 {bad} 份")
    sys.exit(1 if bad else 0)
