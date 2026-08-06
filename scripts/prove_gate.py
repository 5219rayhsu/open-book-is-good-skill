#!/usr/bin/env python3
"""證明一條 selftest 斷言**真的會擋**——把手動的反向驗證變成一行指令。

## 為什麼需要它

閘門寫錯最常見的形態不是「擋錯東西」，是**什麼都不擋**：

  · `len(parts) < 5` 擋掉每一道四選一 → 偵測器五科回報「0 筆可修」，看起來像沒缺陷。
  · `set(card) <= BLIND_KEYS` 是**子集**斷言 → `passage` 缺席照樣通過。
  · `：` 的替換只驗了右側是漢字那一半 → 右側是拉丁文時打破三段式結構。
  · `exam_of` 用黑名單排除前綴 → 換一批檔名就靜靜地回傳錯的科目。

四次都是同一個形狀：**檢查只覆蓋了作者想得到的那一邊**。而恆真／恆假的檢查
在日誌上與「全部通過」長得一模一樣。

唯一可靠的判準是**突變測試**：把被測的那一行改回錯的寫法，selftest **必須失敗**。
這件事我手動做過三次，每次十幾行——**貴的儀式會被跳過**，所以把它變成一行。

## 用法

    prove_gate.py <腳本> <把這段> <改成這段> [--cmd "--selftest"]

它會：複製腳本到同目錄的暫存檔（保住相對 import）→ 套用取代 → 跑 `--selftest`
→ **要求非零退出**。零退出＝那條斷言其實不會擋，等於沒寫。

    prove_gate.py fix_expl_lint_two.py 'if ch == "：":' 'if False:'

`<把這段>` 找不到或找到多處都直接失敗——證明用的突變必須精準，
模糊的突變證明不了任何事。
"""
import pathlib
import subprocess
import sys

MARK = "_provegate_tmp_"


def prove(script: str, old: str, new: str, cmd: str = "--selftest") -> int:
    p = pathlib.Path(script).resolve()
    src = p.read_text()
    n = src.count(old)
    if n != 1:
        print(f"❌ 突變字串在 {p.name} 出現 {n} 次（要恰好 1 次）——精準才證明得了東西")
        return 2
    tmp = p.with_name(MARK + p.name)
    tmp.write_text(src.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(tmp), *cmd.split()],
                           capture_output=True, text=True, cwd=p.parent)
    finally:
        tmp.unlink(missing_ok=True)
    tail = (r.stdout + r.stderr).strip().splitlines()
    tail = tail[-1][:100] if tail else "(無輸出)"
    if r.returncode == 0:
        print(f"❌ 突變後 selftest 仍然通過 → 這條斷言不會擋，等於沒寫\n   {tail}")
        return 1
    print(f"✅ 突變後 selftest 失敗（exit {r.returncode}）→ 這條斷言真的會擋\n   {tail}")
    return 0


def selftest() -> int:
    """用自己當受測對象：把下面那條「恆真」斷言換成恆假，必須被抓到。"""
    assert 1 + 1 == 2, "TARGET_REAL"      # ← --selfprove 的突變靶（訊息字串唯一）
    print("✅ selftest 通過（本檔的 selftest 只是給 --selfprove 當靶）")  # TARGET_HARMLESS
    return 0


def selfprove() -> int:
    """證明本檔自己有效：對自己做一次突變測試。

    🔴 靶字串用**執行期拼接**組出來（`"TAR" + "GET_REAL"`），不要寫成字面值——
    否則它在本檔內會出現兩次（一次是靶、一次是這裡的參數），`count != 1` 會直接
    拒收。自我指涉的測試必然踩到這個，拼接是最省事的解法。
    """
    me = pathlib.Path(__file__).name
    real = "TAR" + "GET_REAL"
    harmless = "TAR" + "GET_HARMLESS"
    ok = prove(me, f'1 + 1 == 2, "{real}"', f'1 + 1 == 3, "{real}"')
    # 🔴 反過來也要驗：**無害的突變不該被判成有效**，否則這支工具會恆真地說「有效」。
    bad = prove(me, harmless, harmless + "_CHANGED")
    if ok == 0 and bad == 1:
        print("\n✅ prove_gate 自證通過：真突變會失敗、無害突變不會")
        return 0
    print(f"\n❌ prove_gate 自證失敗（真突變 {ok}、無害突變 {bad}）")
    return 1


if __name__ == "__main__":
    # 🔴 **先把帶值的旗標連值一起拿掉，再判其他旗標。**
    #    `--cmd "--selftest"` 的**值**本身就叫 `--selftest`，若先寫
    #    `if "--selftest" in sys.argv` 就會跑自己的 selftest 而不是受測腳本的——
    #    症狀是「看起來通過了」。與 mk_rt_chunks 的 `--size 15` 被當成檔名同源：
    #    **旗標的值也在 argv 裡**，掃描整個 argv 找旗標名一定會誤中。
    argv = sys.argv[1:]
    cmd = "--selftest"
    if "--cmd" in argv:
        i = argv.index("--cmd")
        cmd = argv[i + 1]
        del argv[i:i + 2]
    if "--selftest" in argv:
        sys.exit(selftest())
    if "--selfprove" in argv:
        sys.exit(selfprove())
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 3:
        sys.exit(__doc__.rsplit("## 用法", 1)[-1])
    sys.exit(prove(args[0], args[1], args[2], cmd))
