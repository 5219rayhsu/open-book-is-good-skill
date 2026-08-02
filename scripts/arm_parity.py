#!/usr/bin/env python3
"""實驗臂等價性登記簿：判分器沒有等價證明就**拒絕輸出數字**。

## 為什麼要這支（同一個病踩第五次之後）

「評測環境必須與生產一致」這條規則寫在 skill `batching-and-measurement.md` §13，
寫得很清楚，也被引用過三次——然後又犯了兩次。第五次是拿 Sonnet 5 跟 terra max
比 A′：GPT 臂走 `codex exec "$PROMPT"`（操作卡＝指令本文），Claude 臂是手打的
Agent 包裝（操作卡＝「去讀這個檔案」）。同一個模型、同一批題，**只改包裝**：

    lint 0/20  →  lint 20/20

差 20 個百分點是模型差異，差 100 個百分點是我的差異。而它**長得像結果**。

### 為什麼散文規則救不了

規則要生效，得在對的時刻被想起、且情況要被認出來符合它。這種控制的可靠度
等於注意力，而注意力在「順手加一個實驗臂」這種動作上最薄。三次失敗的共同結構
都是**新臂沒有跟舊臂共用程式碼路徑**，於是差異不可見。

### 所以閘門放在判分器，不放在啟動處

啟動處需要紀律（會忘）；判分器是**你一定會跑的那一步**（不跑就沒有數字）。
把「拿不出等價證明就拋錯」放在那裡，等於把這條規則接進執行路徑。

🔴 **沒有登記＝失敗，不是通過。** 這是本檔最重要的一行設計。若「查無紀錄」
當成放行，這道閘就退化成 opt-in，跟散文規則一樣會被忘掉。

## 用法

啟動端（每發一塊就記一次，記的是**真正送出去的那串字**）：

    from arm_parity import record
    record("ab9", "S", 1, prompt_text, model="sonnet", effort="-")

判分端（比較任何兩臂之前）：

    from arm_parity import assert_parity
    assert_parity("ab9", ["P", "Q", "S"], blocks=range(1, 11))
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

LEDGER = pathlib.Path(__file__).parent / "_arm_parity.json"


def _load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {}


def digest(prompt: str, outfile: str = "") -> str:
    """送出去的指令本文的雜湊。

    🔴 **不做語意正規化**——這支的存在意義就是抓「看起來一樣其實不一樣」，
    把差異洗掉等於把自己關掉。只允許兩種遮罩，各有具名理由：

      ① 行尾／首尾空白：shell 與檔案讀寫會動它，不遮會製造假警報，
         而假警報會逼人關掉這道閘（那比沒有閘更糟）。
      ② `outfile`：每一臂**必然**要寫到不同的輸出檔，那是實驗基礎設施的差異，
         不是任務差異。**必須由呼叫端明講是哪個字串**——不接受「自動偵測看起來
         像檔名的東西」，那會變成靜默的萬用洗白。
    """
    t = str(prompt)
    if outfile:
        t = t.replace(outfile, "<OUT>")
    return hashlib.sha256(
        "\n".join(ln.rstrip() for ln in t.strip().splitlines()).encode()
    ).hexdigest()[:16]


def record(exp: str, arm: str, block: int, prompt: str, model: str,
           effort: str = "-", outfile: str = "") -> str:
    d = _load()
    h = digest(prompt, outfile)
    d.setdefault(exp, {}).setdefault(arm, {})[str(block)] = {
        "prompt_sha": h, "model": model, "effort": effort,
        "chars": len(prompt), "ts": time.time()}
    LEDGER.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return h


def assert_parity(exp: str, arms: list, blocks, newer_than: float = 0.0) -> None:
    """同一 exp 的同一塊，所有臂收到的指令本文必須逐位元組相同。

    可以不同的只有 model 與 effort——那正是實驗變因。其餘任何差異都表示
    你在比的不是模型，是兩個不同的任務。

    🔴 `newer_than`：帳本跨執行持久化，所以**上一輪的舊紀錄會替這一輪背書**——
    重跑時忘了重新 record()，這道閘會拿舊雜湊放行。那是「查無紀錄＝失敗」原則的
    時間軸破口（fable 2026-08-02 指出）。判分器應傳入最舊輸出檔的 mtime：
    比輸出還舊的登記＝那次登記不是在描述這批輸出，按查無紀錄處理。
    """
    d = _load().get(exp, {})
    stale = [(a, b) for a in arms for b in blocks
             if str(b) in d.get(a, {}) and d[a][str(b)].get("ts", 0) < newer_than]
    if stale:
        raise AssertionError(
            f"❌ 臂等價性登記**比輸出還舊**：{exp} 有 {len(stale)} 筆過期（如 {stale[:3]}）。\n"
            f"   舊帳不得為新跑背書——重跑了就要重新 record()，"
            f"否則這道閘拿的是上一輪的雜湊。")
    missing = [(a, b) for a in arms for b in blocks if str(b) not in d.get(a, {})]
    if missing:
        raise AssertionError(
            f"❌ 臂等價性**查無紀錄**：{exp} 缺 {missing[:6]}"
            f"{'…' if len(missing) > 6 else ''}（共 {len(missing)} 筆）\n"
            f"   沒有登記＝不算通過。啟動端要呼叫 arm_parity.record()，"
            f"記下**真正送出去的那串字**。\n"
            f"   拿不出等價證明就不該輸出比較數字——那個數字可能全部是包裝差異。")

    bad = []
    for b in blocks:
        shas = {a: d[a][str(b)]["prompt_sha"] for a in arms}
        if len(set(shas.values())) > 1:
            bad.append((b, shas))
    if bad:
        lines = "\n".join(f"   塊 {b}：" + "、".join(f"{a}={s}" for a, s in sh.items())
                          for b, sh in bad[:5])
        raise AssertionError(
            f"❌ 臂之間的指令本文不同（{len(bad)} 塊）——你比的不是模型，是兩個任務：\n"
            f"{lines}\n"
            f"   實驗變因只能是 model／effort。先讓所有臂共用同一份 prompt 再重跑。")

    models = {a: {d[a][str(b)]["model"] for b in blocks} for a in arms}
    print(f"✓ 臂等價性：{exp} 共 {len(list(blocks))} 塊 × {len(arms)} 臂，"
          f"指令本文逐塊一致；變因＝" + "、".join(f"{a}:{'/'.join(sorted(m))}"
                                            for a, m in models.items()))


def selftest() -> None:
    """🔴 兩個方向都要驗——這道閘壞掉時會**放行**，而放行看起來像成功。"""
    import tempfile
    global LEDGER
    keep = LEDGER
    try:
        LEDGER = pathlib.Path(tempfile.mkdtemp()) / "t.json"
        record("t", "A", 1, "同一份指令", model="terra", effort="max")
        record("t", "B", 1, "同一份指令", model="sonnet")
        assert_parity("t", ["A", "B"], [1])          # 內容相同、只有模型不同 → 過

        # ① 內容不同必須擋（這就是踩了五次的那個情況）
        record("t", "C", 1, "去讀這個檔案照做", model="sonnet")
        try:
            assert_parity("t", ["A", "C"], [1])
        except AssertionError as e:
            assert "不是模型" in str(e)
        else:
            raise SystemExit("❌ 包裝不同卻放行——這道閘等於不存在")

        # ② 查無紀錄必須擋，不可以當成通過
        try:
            assert_parity("t", ["A", "ZZ"], [1])
        except AssertionError as e:
            assert "查無紀錄" in str(e)
        else:
            raise SystemExit("❌ 沒登記卻放行——閘門退化成 opt-in，跟散文規則一樣會被忘掉")

        # ③ 只差空白／行尾不算差異（否則假警報會逼人關掉這道閘）
        record("t", "D", 1, "同一份指令   \n", model="opus")
        assert_parity("t", ["A", "D"], [1])

        # ④ outfile 遮罩：各臂寫到不同輸出檔是基礎設施差異，不該算成任務差異
        record("t", "E", 2, "把結果寫進 armE_out.json", model="terra", outfile="armE_out.json")
        record("t", "F", 2, "把結果寫進 armF_out.json", model="sonnet", outfile="armF_out.json")
        assert_parity("t", ["E", "F"], [2])

        # 🔴 但遮罩只准遮**呼叫端指名的那一個**——遮罩不可以順手洗掉真正的任務差異
        record("t", "G", 3, "寫進 armG_out.json，並且只寫 10 題", model="terra",
               outfile="armG_out.json")
        record("t", "H", 3, "寫進 armH_out.json，並且只寫 20 題", model="sonnet",
               outfile="armH_out.json")
        try:
            assert_parity("t", ["G", "H"], [3])
        except AssertionError as e:
            assert "不是模型" in str(e)
        else:
            raise SystemExit("❌ outfile 遮罩把真正的任務差異也洗掉了——遮罩開太寬")
        # ⑤ 舊帳不得為新跑背書（fable 指出的時間軸破口）
        import time as _t
        assert_parity("t", ["A", "B"], [1], newer_than=0)        # 不設門檻 → 照舊放行
        try:
            assert_parity("t", ["A", "B"], [1], newer_than=_t.time() + 60)
        except AssertionError as e:
            assert "比輸出還舊" in str(e)
        else:
            raise SystemExit("❌ 上一輪的舊登記替這一輪背書了——重跑忘了 record 就抓不到")
        print("arm_parity selftest ok（同文放行／異文擋下／未登記擋下／空白不誤報／"
              "outfile 遮得掉但遮不寬／舊帳不背書）")
    finally:
        LEDGER = keep


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        d = _load()
        for exp, arms in d.items():
            print(f"{exp}：" + "、".join(f"{a}({len(b)} 塊)" for a, b in arms.items()))
