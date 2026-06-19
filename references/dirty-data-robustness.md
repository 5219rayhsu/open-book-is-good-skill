## 髒資料韌性（Dirty-Data Robustness）

> 政府／考試開放資料（大考中心 ceec、心測中心、data.gov.tw 等）的命名、編碼、版面年年漂移。任何照本手冊復刻到別科、別國考、別國資料源的人，最常見的死法不是程式邏輯錯，而是「程式跑完 exit code 0、輸出看起來正常、但整科整年靜默漏抓」。本章把這類陷阱與防禦集中講清楚。核心心法一句話：**寧可大聲崩潰，也不要安靜地產出空資料覆蓋掉上次的好資料。**

### 一、五條通則原則

1. **寬鬆 token 匹配 ＋ 先正規化，再比對。**
   永遠不要用 exact-match 比對檔名或科目名（`*_數學A_試題.pdf`、`s + '科' in t`、`'數學a' in fn`）。政府檔名同一份東西會出現「試題／試卷／試題定稿」「數學A／數a／數學ａ」「會考英語／英文」「自然／自然科」等變體。做法：
   - 進入任何字串比對前，先 `unicodedata.normalize('NFKC', s)`。NFKC 一次把全形英數（`Ａ`→`A`、`１`→`1`）、全形括號（`（）`→`()`）、全形空白（`U+3000`）折回半形，中文與標點不受損（`試題`、`自然科` 等 CJK 字元不變）。注意 NFKC 不會自動轉小寫，仍需另接 `.lower()`。本專案 23 個腳本只有 2 個有做正規化，這是最大的系統性破口。
   - 檔名用寬鬆 glob（`*數學*試題*.pdf`）撈出候選，再用 NFKC + 正則抽年份與科目關鍵字確認，別用 `%d_%s_試題.pdf` 直接拼路徑。
   - 科目／選項字母用「別名集合」而非單一字串：`{'數學A','數a','數學ａ'}`、選項正則同時吃 `[（(]\s*([A-DＡ-Ｄ])\s*[）)]`。
   - **連『年份／類型』判斷也別退回 exact-match。** 年份常只出現在 URL path 而檔名沒有「學測」二字；類型可能是「試題／試卷／定稿」。年份從「檔名 ＋ 連結文字 ＋ URL path」三處任一抽到即可，不要強求單一來源都帶「學測」。

2. **缺檔／0 筆結果，先懷疑「命名變體」，且必須報錯。**
   `glob` 回空、`find_tables()` 回空、`classify()` 全 miss——這些幾乎都是命名或版面漂移，不是「今年真的沒資料」。鐵律：
   - `if not years: raise` 或 `sys.exit(1)`，絕不靜默寫出 `[]` / `{}`。
   - 缺檔不要 `return []` 後繼續，要 log 出「哪年哪科哪個路徑沒找到」並計入失敗清單，最後非零 exit code。
   - **多重命中也要當異常處理。** 別名比對若同一字串同時命中多科（如檔名含「數a」又含「數b」），代表合卷或檔名拼接，不能只取第一個命中——應蒐集全部命中，>1 時 raise 或至少 `logging.warning` 留下完整檔名，否則會「錯分一筆」這種比零筆更難察覺的髒資料。
   - 跨年批次用 `try/except ... continue` 包住單年，讓一年壞掉不會炸掉整批、其他年仍能寫出。

3. **驗證內容，不要只驗 URL / 副檔名。**
   `r.content[:4] == b'%PDF'` 過不了截斷下載；`status_code` 4xx/5xx 也可能被當成功；Google Drive 確認頁／CAPTCHA 頁會被當 PDF 寫進磁碟。做法：下載後 `r.raise_for_status()`、用 `pypdf.PdfReader` 確認 `len(pages) > 0` 或至少驗尾端有 `%%EOF`；解析後驗題數（如會考社會應 54 題、學測自然應 ≥50），不足就 raise 而非只 print 警告。**驗證失敗一定要擋在寫檔之前**，否則髒資料已落盤。

4. **別吞錯，別讓 except 變成資料黑洞。**
   `except Exception: continue` 會把 SSL 憑證錯、DNS 失敗、逾時、PDF 損毀全部變成「安靜跳過」。做法：分類捕捉（可重試的 timeout vs 不可重試的 `SSLCertVerificationError`）；累計失敗頁／年，超過閾值就 `sys.exit(1)`；用 `logging.exception()` 留完整 traceback，連年份／科目／file_id／HTTP status 一起記。

5. **憑證問題用系統 curl 思維，別關掉驗證——但要分清楚兩個信任庫。**
   macOS 常因系統 CA 缺失或程式端 CA bundle 過舊，導致 `urllib`／`requests` SSL 失敗。正解是明確指定 CA bundle（`ssl.create_default_context()`、或統一改用 `requests`／`certifi`），而不是 `check_hostname=False` 把驗證關掉。
   診斷時要先認清：macOS `/usr/bin/curl` 走 **SecureTransport（系統 Keychain）**，而 Python `requests` 走 **certifi 自帶的 `cacert.pem`**——這是兩個獨立的信任庫。所以：
   - `curl -I <url>` 通、程式不通：**多半**是程式端 CA 設定／certifi 過舊，但也可能是該站的 root 只在 Keychain 受信任、certifi 沒收錄（常見於企業或本機自簽 CA）。先 `pip install -U certifi` 或把該 root 餵給 `verify=` 再判斷。
   - `curl` 也不通：問題在站台憑證本身，不是你的程式。

6. **寫檔要原子化，並先備份。**
   `open(path, 'w')` / `write_text()` 是「先清空再寫」，寫到一半被 kill（磁碟滿、Ctrl-C、重啟）就留下半截或 0-byte 的損毀檔。做法：
   - 先寫同目錄下的暫存檔（`path.with_suffix('.tmp')`），驗證通過後 `os.replace(tmp, path)`。`os.replace` 只在**同一檔案系統內**才原子；tmp 與目標跨掛載點（如 tmp 在 `/tmp`、目標在 `/Users`）會丟 `OSError: EXDEV`，所以暫存檔務必放在目標的同一目錄。
   - 覆蓋前 `shutil.copy2` 留帶時間戳的 `.bak`。
   - 唯一性／schema 等 `assert` 要排在 `write_text` **之前**：先在記憶體或暫存檔上驗，通過才落盤。本專案 `merge_cap_to_bank.py` 的唯一性 `assert` 排在 `write_text` 之後六行——等於損毀資料已落盤才檢查。正確順序是「組好 dict → 驗唯一性／qid → 寫 tmp → os.replace」。

### 二、教學案例：ceec 113 數A「數a 少一個『學』字」

這是真實踩過的雷，把上面原則具象化。

`scrape_ceec_math.py` 的科目對照表是：

```python
SUBJ = [("數學a", "數學A"), ("數學ａ", "數學A"), ("數學b", "數學B"), ("數學ｂ", "數學B"), ("自然", "自然")]
```

每個 key 都帶「學」字。年份正則是 `r"(11[1-5])學測"`，要求「學測」緊跟年份。問題：大考中心 113 年那批 PDF 的檔名／連結文字，數A 出現了**省略「學」字的「數a」**寫法。於是：

- `classify()` 跑 `next((s for key, s in SUBJ if key in low), None)`——`數學a`、`數學ａ` 都比不到只有「數a」的字串，回 `None`。
- 該年數A 的「試卷」連結整筆被丟掉，但程式照常 exit 0。
- 產出的 `ceec_dl_urls.json` 裡，**113 數學A 只剩「答案」、沒有「試卷」**（可實際打開該檔驗證）。下游解析拿不到題目卷，整科整年靜默缺題，CI 完全無感。

連鎖放大：下游 parse 腳本用 `*_數學A_試題.pdf` exact-match，就算手動補了檔名只要差一個字也照樣 miss；`scrape` 的零筆結果還會寫出空 JSON 覆蓋掉上次成功的表。一個少打的「學」字，串起「exact-match + 不正規化 + 吞錯 + 零筆覆蓋」四個破口。

**正確修法**（多個原則一次到位）。注意修法本身也容易在三個地方重蹈覆轍：**年份不要強求「學測」字面**、**年份正則要有邊界**、**多重命中要當異常**：

```python
import re
import sys
import logging
import unicodedata

YEARS = {"111", "112", "113", "114", "115"}   # 別忘了定義，否則 NameError

def norm(s: str) -> str:
    # NFKC 折全形英數/括號/空白；NFKC 不轉小寫，需另接 .lower()
    return unicodedata.normalize("NFKC", s).lower()

# 別名集合涵蓋省字與全形變體
SUBJ_ALIASES = {
    "數學A": ("數學a", "數學ａ", "數a", "數ａ"),
    "數學B": ("數學b", "數學ｂ", "數b", "數ｂ"),
    "自然":  ("自然", "自然科"),
}

def extract_year(*sources: str):
    # 年份從檔名/連結文字/URL path 任一抽到即可，不強求都帶「學測」。
    # \b 邊界避免 2113→113、1130→130 這類過度匹配。
    for src in sources:
        m = re.search(r"\b(1[0-9]{2})\b", norm(src))
        if m and m.group(1) in YEARS:
            return m.group(1)
    return None

def classify(fn: str, url: str = ""):
    year = extract_year(fn, url)
    if not year:
        return None
    t = norm(fn)
    hits = [std for std, al in SUBJ_ALIASES.items() if any(a in t for a in al)]
    if not hits:
        logging.warning("科目比對失敗，可能是新命名變體: %s", fn)   # 留下可追的訊號
        return None
    if len(hits) > 1:
        # 同時命中多科 = 合卷或檔名拼接，別偷偷取第一個
        logging.error("單一檔名命中多科 %s，疑似合卷/拼接，需人工確認: %s", hits, fn)
        raise ValueError(f"ambiguous subject for {fn!r}: {hits}")
    return (year, hits[0])

# 寫檔前的 guard：零筆一定要擋
if not found:
    logging.error("0 筆符合條件，終止寫入以免覆蓋上次成功結果")
    sys.exit(1)
```

### 三、攝取前自檢清單（Ingestion Pre-flight Checklist）

復刻到任何新資料源前，逐項打勾：

- [ ] **正規化**：所有字串比對前都先 `unicodedata.normalize('NFKC', ...)` 再 `.lower()`？選項字母、答案字母、科目名、檔名、答案表 cell 都涵蓋？
- [ ] **檔名寬鬆比對**：用寬鬆 glob ＋ 正則抽取，而非 exact-match 拼路徑？已列出「試題／試卷／試題定稿」「省字／全形」等已知變體別名？
- [ ] **年份／類型也不退回 exact-match**：年份從「檔名 ＋ 連結文字 ＋ URL path」任一抽到即可，不強求字面含「學測」？年份正則有 `\b` 邊界且對照合理範圍集合（避免 `2113`→`113`）？
- [ ] **多重命中即異常**：別名比對同時命中多科時 raise／warning，而非靜默取第一個（合卷／拼接會被錯分成單科）？
- [ ] **缺檔即報**：缺試題或答案檔時 `raise`／`sys.exit(1)` 並指名路徑，而非 `return []` 靜默跳過？
- [ ] **零筆即報**：`glob`／`find_tables`／`classify` 回空時報錯，不寫出空 `[]`／`{}` 覆蓋舊資料？
- [ ] **不吞錯**：沒有裸 `except Exception: continue`？SSL／逾時／損毀分類處理並累計失敗、最後非零 exit？
- [ ] **內容驗證**：下載驗 `raise_for_status()` ＋ PDF 結構（`%%EOF`／可開頁），不只驗 magic bytes？解析驗題數達預期門檻？
- [ ] **驗證擋在寫檔前**：所有驗證失敗都在 `json.dump` 之前中止，髒資料不落盤？
- [ ] **憑證**：用系統 CA／`certifi` 明確指定，沒有偷關 SSL 驗證？診斷時記得 `/usr/bin/curl`（Keychain）與 Python（certifi）是兩個信任庫——curl 通而程式不通也可能是 certifi 缺該 root，先 `pip install -U certifi` 再下判斷？
- [ ] **原子寫入 ＋ 備份**：寫**同目錄**的 `*.tmp` 後 `os.replace`（跨檔系統會 `EXDEV`，故 tmp 要放目標同一目錄）？覆蓋前留帶時間戳 `.bak`？所有 `open` 用 `with`？
- [ ] **驗證／assert 在落盤前**：唯一性、qid、schema 等檢查排在 `write_text`／`os.replace` **之前**（先在記憶體或 tmp 上驗，通過才覆蓋正式檔）？
- [ ] **重跑冪等／去重**：合併進主庫的腳本重跑不會重複併入同一批題目（用 `qid` 去重，已存在則 skip 或更新，而非無條件 append）？
- [ ] **跨年隔離**：單年解析用 `try/except continue` 包住，一年壞不影響其他年也不中斷整批寫出？
- [ ] **路徑不依賴 cwd**：用 `Path(__file__).resolve().parent.parent` 算絕對路徑，從任何目錄執行都能定位 `data/raw`？
- [ ] **schema 驗證**：合併進主庫前，逐筆驗 `qid` 等必要欄位存在且非空（`qid` 為 `None` 會讓多題靜默併成一筆）？
- [ ] **可追訊號**：所有靜默降級（跨頁截斷、欄位 fallback、比對 miss）都至少 `logging.warning` 留下年份／科目／題號，CI 可 grep？