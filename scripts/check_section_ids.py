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
SEC = re.compile(r"^## §?(\d+|[A-Z])(?:\.(?=\s)|(?=\s))", re.M)


def dupes(text: str) -> list[str]:
    return sorted(f"{k} ×{n}" for k, n in collections.Counter(SEC.findall(text)).items() if n > 1)


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
    print("=== check_section_ids selftest PASS（9 案例）===")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest(); sys.exit(0)
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                        pathlib.Path(__file__).resolve().parent.parent / "references")
    bad = 0
    for f in sorted(root.glob("*.md")):
        d = dupes(f.read_text())
        if d:
            bad += 1
            print(f"🔴 {f.name}: 節號重複 {', '.join(d)}")
    print(f"掃了 {len(list(root.glob('*.md')))} 份，撞號 {bad} 份")
    sys.exit(1 if bad else 0)
