# 資料源偵察與取得手冊（data-sources）

> 復刻手冊的「資料層」：如何從**官方開放試題資料**偵察、取得、落地成題庫。
> 給 agent／維護者執行。對應的下載與解析腳本在升學專案 `scripts/`。
> 授權：本手冊與 scripts 採 MIT；試題資料依著作權法 §9 屬公共所有。

本手冊涵蓋兩個官方資料源（學測走大考中心、會考走心測中心）、著作權依據與
clean-room 紀律、範圍決策，以及題庫 `bank.json` 每題的欄位 schema。**忠於專案
實際做法**：以下函式名、欄位、流程都對應真實腳本，未臆造。

---

## 0. 核心原則（先讀）

- **官方優先、權威答案鍵**：試題與**標準答案**都取官方 PDF。標準答案是唯一權威
  答案鍵；出版商的答案寫法**不餵進**任何生成 prompt。
- **clean-room**：只重製試題本身（§9 允許），**不抄**出版商的編排、分類、詳解。
  詳解由我們自行生成並標註「AI 整理，需查證」。
- **curl + python 優於 WebFetch**：抓官方列表 HTML 與 PDF，用 `curl -A Mozilla`
  搭配 python 正則直取連結，比 WebFetch 快且準（少一層摘要失真）。
- **逐字忠實**：解析時絕不改寫、摘要、翻譯原文；題組共用素材原文保留。
- **base64 安全鐵則**：圖一律存獨立 PNG，`bank.json` 只存**檔名**（純文字、可 lint）；
  base64 只在 build 階段於腳本內部與輸出 HTML 流動，**絕不進入對話／終端／stdout**。

---

## 1. 大考中心（學測）：ceec.edu.tw

學測（GSAT）／分科等大學入學考試的歷年試題與標準答案，由**大學入學考試中心**
（ceec.edu.tw）公布。網站是傳統伺服器渲染，`curl` 直接抓得到列表 HTML。

### 1.1 偵察列表頁

各科歷年試題在「歷屆試題」分類頁，網址帶 `xsmsid`（分類節點 id）參數。流程：

1. 用瀏覽器（或 `curl`）打開該科歷屆試題分類頁，記下該科對應的 `xsmsid`。
2. `curl -A Mozilla` 抓該分類頁 HTML（含各年度試題與答案的連結清單）。
3. 用 python 正則從 HTML 直接抓出 `file_pool` 連結（PDF 實體所在）。

```bash
# 範例：抓某科歷屆試題分類頁，找出 file_pool PDF 連結
curl -s -A "Mozilla/5.0" "https://www.ceec.edu.tw/xmfile?xsmsid=<科目分類節點>" \
  | python3 -c "import sys,re; \
    [print(m) for m in re.findall(r'/file_pool/[^\"'\'' ]+\.pdf', sys.stdin.read())]"
```

### 1.2 取試題 PDF + 官方標準答案 PDF

- 試題 PDF 與**標準答案** PDF 都在 `file_pool/` 下，沿 1.1 取到的連結直接 `curl -O`
  下載到 `data/raw/`。
- 命名建議與後續 parser 對齊（多年度），例如國文走 `parse_gsat.py`、英文走
  `parse_eng.py`、社會走 `parse_soc.py`。**每個科目可能需要各自的 parser**
  （題型結構不同），不要假設一支 parser 通吃。
- 標準答案 PDF 多為表格，用 `pymupdf` 的 `find_tables()` 解析出「題號 → 正解」。

### 1.3 為什麼不用 WebFetch

實測 `curl + python` 取 ceec 列表 HTML 與 PDF 連結，比 WebFetch 快且準：WebFetch
會摘要頁面、可能漏掉或改寫連結；直取 HTML 正則命中 `file_pool` PDF 最可靠。

---

## 2. 心測中心（會考）：cap.rcpet.edu.tw

國中教育會考（CAP）由**國家教育研究院測驗及評量研究中心**（cap.rcpet.edu.tw）
辦理。和 ceec 不同，這個網站**前端 JS 渲染**：直接 `curl` 抓主頁拿不到試題連結。

### 2.1 突破 JS 渲染：走 iframe 頁

關鍵發現：`examination.html` 用 **iframe** 載入靜態頁
`exam/{年}/{年}exam.html`，**該頁才列出各科試題連結**，且連結指向 **Google Drive**
的 file id。流程：

1. `curl -A Mozilla` 抓 iframe 頁 `exam/{年}/{年}exam.html`（這頁是靜態 HTML，
   curl 抓得到）。
2. 用正則抓 `file/d/{id}` 取出各科的 **Google Drive file id**。
3. 把每年各科的 file id 整理成 `data/raw/cap_drive_ids.json`。

### 2.2 cap_drive_ids.json 結構

外層鍵是學年度（字串），內層鍵是科目／用途，值是 Drive file id：

```json
{
  "111": {
    "參考答案": "<file_id>",
    "寫作":     "<file_id>",
    "國文":     "<file_id>",
    "英語閱讀": "<file_id>",
    "社會":     "<file_id>"
  },
  "112": { "...": "..." }
}
```

- 已蒐集 **111–115** 五個學年度的「國文／英語閱讀／社會／參考答案／寫作」file id。
- ⚠️ 目前**缺數學／自然**的 Drive id —— 擴圖式科時需回 cap iframe 頁補抓。

### 2.3 fetch_cap.py：從 Drive 下載（含病毒掃描確認頁）

`scripts/fetch_cap.py` 讀 `cap_drive_ids.json`，逐年逐科從 Drive 下載 PDF 到
`data/raw/{年}_{stem}.pdf`。重點機制：

- **科目對應輸出檔名**：以 `SUBJ_OUT` 字典映射，例如 `國文 → 會考國文_試題`、
  `英語閱讀 → 會考英語_試題`、`社會 → 會考社會_試題`、`參考答案 → 會考_參考答案`。
  只下載文字科 + 參考答案；**寫作（非選）暫不**下載（延後）。
- **Drive 大檔病毒掃描確認頁**：Drive 對大檔回傳的是一頁 HTML（`content-type` 含
  `text/html`）而非 PDF，腳本同時處理兩種版本：
  - **新版確認頁**：HTML 內含 `<form action=...>` 與隱藏的 confirm／uuid 參數
    → 解析 form 的 action 與所有 `name/value`，跟著再送一次 GET。
  - **舊版確認頁**：`download_warning` cookie 帶 confirm token → 補 `confirm=<token>`
    重新請求。
- **合法 PDF 檢查**：`_is_pdf()` 確認檔案 > 1 KB 且前 4 bytes 為 `%PDF`。
- **冪等**：已存在且為合法 PDF 則跳過；下載失敗逐檔回報、不中斷整批。
- **只印安全資訊**：檔名、KB 大小、是否合法 PDF；**不印** bytes／base64。

```bash
uv run --with requests python scripts/fetch_cap.py
```

### 2.4 會考卷的結構特性（解析時要知道）

- 全卷**四選一單選**（無多選、無五選項、無選擇式非選），比學測單純。
- 國文固定 **42 題**、社會 **54 題**；含單題與題組（題組 = 一段選文／圖文 + 數小題）。
- 國文寫作 = 非選（延後）、英聽 = 音檔（延後）。
- markitdown 線性化後，題組標頭以行內樣式辨識（如「請閱讀以下…，並回答 A ～ B 題：」），
  `passage` = 標頭後到第一個子題題號前的原文。各科有專屬 parser
  （`parse_cap_國文.py`／`parse_cap_社會.py`／`parse_cap_英語.py`）。
- 解析時以官方答案表的題號為權威、要求題號嚴格遞增（濾掉注釋的「1.」之類假題號）；
  跳過卷首約 1.5 頁的測驗說明；偵測圖表指涉詞或選項殘缺以標 `needs_figure`。

---

## 3. 著作權與 clean-room

### 3.1 法律依據：著作權法 §9

> **§9.1.5**：依法令舉行之各類考試**試題及其備用試題**，不得為著作權之標的。

因此**官方試題可自由重製**，不需授權、不付費。標準答案同屬考試試題的一部分，作為
**權威答案鍵**使用。

### 3.2 clean-room 紀律（受保護的不能碰）

§9 解放的是「試題」本身，**不解放**出版商加值的部分：

- ❌ 不抄出版商的**編排**（分類、難度標註、章節對應、選文導讀）。
- ❌ 不抄出版商的**詳解**；**出版商答案／詳解的寫法不餵進生成 prompt**。
- ✅ 詳解由我們**自行生成**，clean-room（只看官方試題與官方答案），全標
  「AI 整理，需查證」並附把握度；經程式 lint + 紅隊抽驗。
- ✅ 作文採**官方分級樣卷**（最高分→低分），不 AI 代寫完整作文；英文短答／中譯英
  近乎有標準答案，可由 AI 整理參考答案並標明須查證。

---

## 4. 範圍決策（由維護者拍板）

範圍是**對象決策**，不是技術決策 —— 由維護者依服務對象拍板。本專案目前：

- **只收新課綱 111 學年度起**（收 111–115），舊課綱不收。
  - 理由：聚焦範圍、避免課綱落差造成誤導（本專案對象是新課綱第一屆）。
- 學測與會考放在同一平台、用考試選擇器切換，**預設不跨考混題**。
- 國考（專技、不同對象）各自獨立，不併入升學平台。

新維護者要服務不同對象（例如要收舊課綱、或另一個國家的考試）時，自行調整收錄範圍，
其餘流程（偵察→下載→解析→題庫→裁圖→詳解）不變。

---

## 5. 題庫 schema：bank.json（每題）

`bank.json` 是純文字題庫，每題一個物件。**圖只存檔名**，build 時才內嵌（見 §6）。
每題欄位：

| 欄位           | 型別        | 說明 |
|----------------|-------------|------|
| `qid`          | string      | 全域唯一題 id；merge 以此為鍵（冪等）。 |
| `exam`         | string      | 考試別：`學測` / `會考`。 |
| `year`         | string／int | 學年度，例如 `111`–`115`。 |
| `subject`      | string      | 科目，例如 國文／英語／社會。 |
| `no`           | int／string | 該卷題號。 |
| `group_id`     | string／null| 題組 id；同一題組的小題共用。非題組為 null。 |
| `passage`      | string／null| 題組**共用素材**（選文／圖文敘述）原文；非題組為 null。 |
| `stem`         | string      | 題幹（逐字忠實，不改寫）。 |
| `options`      | object／array| 選項，如 `{"A": "...", "B": "..."}`；文意選填等以 A–J 詞庫存。 |
| `answer`       | string／array| 正解；**可多選**（多選逐選項，如 `["A","C"]`）。 |
| `type`         | string      | 題型：`單選` / `多選` / `題組` / `非選`。 |
| `needs_figure` | bool        | 是否需要圖（圖表指涉詞或選項殘缺時為 true）。 |
| `figure`       | string／null| 圖檔名（**只存檔名**，如 `C111_社會_g44_45.png`），無圖為 null。 |

補充：實作中部分題另帶 `section`（卷內區段，如 詞彙／綜合測驗／閱讀）等輔助欄位，
但上表為核心契約。

### 圖檔命名（由 extract_figures 寫回 figure 欄）

- 學測：獨立題 `S{年}_{科}_q{no}.png`、題組 `G{年}_{科}_g{首}_{末}.png`
  （由 `extract_figures.py` 產生）。
- 會考：獨立題 `C{年}_{科}_q{no}.png`、題組 `C{年}_{科}_g{首}_{末}.png`
  （由 `extract_figures_cap.py` 產生）。題組區間取該 group 全部成員題號的 min~max；
  group 內所有 `needs_figure` 子題的 `figure` 欄都指向同一張圖。

---

## 6. 圖的 base64 安全架構（只描述、不貼任何 base64）

為了讓題庫**可 lint、可 diff**，又能做出離線單檔，圖走三段式：

```
原卷 PDF ──extract_figures──► data/figures/{檔名}.png   （獨立二進位 PNG）
                                      │
bank.json 只寫 figure="{檔名}.png"     │  （純文字、可 lint、可 git delta）
                                      ▼
build_app.py 建置時：PNG ──► base64 ──► 內嵌進 window.__FIGS__（輸出 HTML 內）
```

- `data/figures/` 存獨立 PNG（pymupdf 整塊 render，raster+vector 一起點陣化，
  zoom 2.2；**保真不失真壓縮**）。
- `bank.json` 只存**檔名字串**，永不寫 base64 —— 保持題庫純文字、可 lint、git 可 delta。
- `build_app.py` 建置時才把 PNG 讀進來 base64 內嵌成 `window.__FIGS__`；前端
  單檔走 `__FIGS__`、dev 走 `../data/figures/`。
- **鐵則**：base64 全程只在 build 腳本內部與最終 HTML 流動，**絕不進入對話、stdout、
  Read 或任何工具輸出**。萃圖腳本只印張數／位元組大小／檔名／座標／計數，
  驗圖一律用 Read 直接開 PNG，不 cat、不印 bytes。

---

## 7. 端到端流程速查

```
偵察 ──► 下載 ──► 轉檔 ──► 解析 ──► 答案鍵 ──► 題庫 ──► 裁圖 ──► 詳解 ──► 打包
```

| 階段   | 學測（ceec）                          | 會考（cap）                                |
|--------|---------------------------------------|--------------------------------------------|
| 偵察   | curl 列表 HTML，正則取 `file_pool` PDF | curl iframe `exam/{年}/{年}exam.html`，取 Drive file id |
| 下載   | `curl -O` 試題＋標準答案 PDF           | `fetch_cap.py`（讀 cap_drive_ids.json，處理確認頁） |
| 轉檔   | markitdown PDF → md（解決閱讀序／題組） | 同左 |
| 解析   | `parse_gsat.py` / `parse_eng.py` / `parse_soc.py` | `parse_cap_{國文,社會,英語}.py` |
| 答案鍵 | 標準答案 PDF `find_tables()` → 題號→正解 | 參考答案 PDF（多科一覽表）定位各科欄 |
| 題庫   | merge 進 `bank.json`（qid-keyed 冪等） | 同左 |
| 裁圖   | `extract_figures.py`（S/G 命名）       | `extract_figures_cap.py`（C 命名） |
| 詳解   | Sonnet 生成 → Opus 抽驗（k≥4/40 升級） | 同左 |
| 打包   | `build_app.py` → 單檔 HTML（圖 base64 內嵌） | 同左 |

模型路由：抓資料／轉檔等機械工作用較小模型；文字科解析與詳解用中階模型；題組長文、
難題、圖式、紅隊查核用最強模型。詳解抽驗採統計規則：抽樣錯誤達 k≥4/40
（錯誤率下界 ≥4%）才升級到更強模型重做。

---

## 8. 國考（考選部）：MCP 拿題 + 官方 PDF 拿答案（雙來源）

國考（高普考／律師／司法官／會計師／醫師／教師等）有別於學測會考——題量極大（考選部
dataset 170565：64,815 卷、320,663 題、2000 至今），且**有現成的開放資料 MCP 鏡像**
（Twinkle Hub 的 exam corpus）。但**答案不在 MCP 裡**，仍要回官方 PDF。雙來源分工：

| 要拿什麼 | 來源 | 工具／做法 |
|---|---|---|
| 整卷題目 | Twinkle Hub MCP | `get_exam_paper(paper_id)` 回整卷題幹＋選項 |
| **跨年挑特定主題題目** | Twinkle Hub MCP | `search_exam_questions(query, stem_contains=, exam_type=, subject=, year_from=)` — 題目層級語意檢索，建新題庫挑題很方便 |
| **選擇題標準答案** | **官方 PDF（非 MCP）** | curl 考選部「測驗式試題標準答案」PDF → `pdftotext` / `pymupdf find_tables()` 解出題號→正解 |
| 申論參考解 | 無官方解 | 自行 AI 生成＋紅隊（見 explanations-redteam.md） |

**關鍵坑（實測）**：MCP 的語意向量**只 embed 題幹，選項與答案不入索引**，所以
①「找答案提到 XX 的題」搜不到 ②MCP **完全沒有答案欄位**——別期待 MCP 給標準答案。
答案唯一權威仍是官方 PDF（同 §0 原則）。所以國考管線＝**MCP 拿題（語意搜尋挑題更靈活）
＋ 官方 PDF 拿答案（逐題全驗）**，兩來源獨立、可交叉對照，不單押一個來源。

> 載入對應的 `tw-opendata-exam` skill 可取得這三個 MCP tool 的完整簽名與 query 範例。
