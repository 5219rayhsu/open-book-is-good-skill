#!/usr/bin/env python3
"""驗「這個 skill 的 description 上有沒有任務的字」（零 token）。

2026-08-06 事故：整輪 8 小時全在做紅隊／修復站／上線，本 skill **一次都沒觸發**。
根因之一是 description 寫成「它是什麼」的流程自述，而不是「何時用它」的觸發器——
「修復」「上線」「發佈」「跑批」「建置」這些**使用者真的會講的字，一個都不在裡面**。
選 skill 的模型是拿使用者的話對 description 的字做匹配；沒有可匹配的表面就選不到。

🔴 **這支的價值全在它會對舊版 FAIL。** 一把量什麼都說 PASS 的尺不是門。
所以 `--selftest` 兩側都測：舊 description（known-bad，必須 FAIL）與
現行 description（known-good，必須 PASS）。任一側結果不符即中止——那代表尺壞了，
不是 skill 好了。

用法：skill_trigger_lint.py [SKILL.md 路徑]    # 預設查同 repo 的 SKILL.md
    skill_trigger_lint.py --selftest
"""
import pathlib
import re
import sys

# 使用者會講的任務動詞。少一個，那類任務就選不到這個 skill。
NEED = ["建置", "解析", "入庫", "裁圖", "詳解", "跑批", "紅隊", "修復", "上線", "發佈"]

# 🔴 known-bad 固定樣本：2026-08-06 之前的 description，逐字保留。
#    它是這把尺的否證側，**不要因為「舊的已經不用了」就刪掉**——刪了就沒人知道
#    尺還會不會 FAIL。
OLD_DESC = (
    "從官方開放試題資料復刻一套考古題自學系統的方法手冊：偵察資料源→下載轉檔→"
    "判斷式解析→題庫→答案配對全驗（必跑）→裁圖→詳解（含查證紀律）→"
    "詳解紅隊（必跑，問使用者全跑或抽查）→build 單檔／網站；已跑通國考，"
    "正延伸嘗試臺灣升學（學測／會考）等公開試題。")


def read_desc(p: pathlib.Path) -> str:
    """取 frontmatter 的 description（到下一個頂層鍵或 `---` 為止）。"""
    t = p.read_text(encoding="utf-8")
    m = re.search(r"^---\n(.*?)\n---", t, re.S)
    if not m:
        sys.exit(f"🔴 {p} 沒有 YAML frontmatter，skill 不會被掛載。")
    fm = m.group(1)
    d = re.search(r"^description:\s*(.+?)(?=\n[a-zA-Z_-]+:|\Z)", fm, re.S | re.M)
    if not d:
        sys.exit(f"🔴 {p} 的 frontmatter 沒有 description。")
    return " ".join(d.group(1).split())


def missing(desc: str) -> list:
    return [w for w in NEED if w not in desc]


def selftest() -> None:
    bad = missing(OLD_DESC)
    assert bad, "🔴 尺壞了：舊 description 應該 FAIL，卻通過了"
    # 舊版該缺的就是那五個；順便釘住「缺的是哪些」，避免 NEED 被改成恆真的清單。
    assert set(bad) >= {"修復", "上線", "發佈", "跑批", "建置"}, bad
    here = pathlib.Path(__file__).resolve().parent.parent / "SKILL.md"
    now = missing(read_desc(here))
    assert not now, f"🔴 現行 description 仍缺觸發詞：{now}"
    print(f"✅ selftest 通過：known-bad 缺 {bad}、known-good 全中")


def main(path: str | None) -> None:
    p = pathlib.Path(path) if path else \
        pathlib.Path(__file__).resolve().parent.parent / "SKILL.md"
    miss = missing(read_desc(p))
    if miss:
        sys.exit(f"🔴 FAIL 缺觸發詞：{miss}\n"
                 f"   → 這些任務的使用者用語在 description 上沒有匹配面，選不到本 skill。")
    print(f"✅ PASS {p.name}：{len(NEED)} 個觸發詞全在 description 裡")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    selftest() if "--selftest" in sys.argv else main(args[0] if args else None)
