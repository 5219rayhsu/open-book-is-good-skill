# 圖式科：裁圖內嵌 + base64 安全架構

> **裁圖/圖表抽取的「主」參考＝ `exam-pdf-asset-extractor` skill**（圖表是它的專責：像素 autocrop＋裁切偵測、image/text 雙錨點開關、image-table text-pair 錨點、跨頁、Completeness Re-check 掃全題型）。新裁圖工作先讀那支。本檔只留 **open-book 專屬建置面**：離線單檔（學測／會考）的 base64 內嵌架構；**國考是線上站 → 圖存 PNG 不做 base64**（見主 skill）。
>
> 適用範圍：社會圖表題、英文圖選項題、國文／社會題組共用材料圖，以及未來的數學／自然圖式科。
> 對應腳本：`scripts/extract_figures.py`（學測）、`scripts/extract_figures_cap.py`（會考）、`scripts/build_app.py`（建置內嵌）。
> 授權：MIT。

圖式題若缺圖等於廢題 —— 練習要面對真實，所以本專案的取向是**裁切原卷版面區塊 render 成 PNG 內嵌**，忠實重現原卷，不簡化、不重排。本文件說明兩件事：

1. **怎麼把圖從 PDF 裁出來**（為何不靠 `get_images()`、怎麼定位題目、怎麼決定 band 邊界）。
2. **★ base64 安全架構**（最重要）：圖檔、題庫、建置三者如何分工，讓 base64 全程不進對話／終端。

---

## 一、為何不靠 `page.get_images()`

直覺做法是用 PyMuPDF 的 `page.get_images()` 把頁面內嵌的點陣圖一張張抽出來。但考卷的圖**多半抓不到**：

- 地圖、統計圖表、示意圖、路線圖，原卷裡常是**矢量繪製**（向量路徑 + 文字輪廓），根本沒有一張可被 `get_images()` 列舉的內嵌點陣圖。
- 就算抽得到內嵌點陣，也會漏掉疊在上面的座標軸文字、圖例、比例尺這些**向量層**，拼不回完整的圖。

**改用整塊 render**：用 PyMuPDF 把「題目所在的版面區塊（band）」**整塊點陣化** —— raster 與 vector 一起進同一張 PNG，所見即所得。render 參數：

```python
ZOOM = 2.2
MATRIX = fitz.Matrix(ZOOM, ZOOM)
# render：page.get_pixmap(matrix=MATRIX, clip=fitz.Rect(xL, y0, xR, y1))
```

`zoom 2.2` 是清晰度與體積的折衷：夠看清地圖細節，又不至於讓單張 PNG 過肥。clip 框出 band 的矩形範圍，`get_pixmap` 把那塊版面（含所有圖層）一次點陣化成乾淨 PNG。

---

## 二、怎麼定位題目在頁面的位置

要裁對 band，先得知道「這一題從頁面哪個 y 座標開始」。兩支腳本用了不同但同源的策略。

### 學測：用 stem／題組標記的文字前綴定位（`extract_figures.py`）

逐頁建一個「**正規化字元索引**」：`build_char_index(page)` 走訪 `page.get_text("dict")` 的每個 text span，把每個非空白字元對應到它所屬 span 的 bbox，得到 `(normtext, metas)`。接著：

- **獨立題**：用題目 `stem` 的正規化前綴在 `normtext` 內 `find` 出 y 座標（`locate_text`）。關鍵是**長前綴優先 + 要求唯一**：先試 30→10 字且該前綴在頁內唯一（避免短字串或題號數字撞到別題）；對不上才放寬到 6 字、不要求唯一。
- **題組共用圖／材料**：改用「**N-M為題組**」這個題組標記當主錨點（`find_group_mark`）。它文字短、固定、落在 passage 區上緣，比拿 passage 全文比對可靠得多 —— passage 經 markitdown 重排後，字序與 PDF span 已不一致，且常夾雜圖說／數字而比對失敗。
- **fallback**：bank 裡若某題 stem 開頭被解析器截斷，`locate_text_fragments` 把 stem 切成多個 12 字片段，任一命中即可，並用 `snap_to_question_number` 把上界吸附回該題的「`{no}.`」題號行，讓 band 含到題號。

### 會考：用題號行定位（`extract_figures_cap.py`）

會考版面與學測不同：題號行「`{no}.`」於左邊界（`x0 < QNUM_X_MAX = 92`）非常穩定，所以**改用題號行當主錨點**。

- `collect_question_anchors(page)` 掃每行，行首符合 `QNUM_RE = ^\s*(\d{1,3})[.．]` 且左邊界夠左者，收成 `(no, y0)` 錨點清單。
- 為什麼不用 stem：會考「這張圖最可能…」型題，**圖夾在題號行與 stem 之間**，若用 stem 當上界會把圖切掉。用題號行當上界才能含進圖。
- 題組材料用「**…回答第 {首} 至 {末} 題：**」這類子標題定位（`find_group_head`，容忍 `~ ～ - － 至 到` 各種分隔符），找不到子標題時退而用第一子題題號行往上抓一段保守 padding。

> **題組圖 vs 獨立題圖的擺位原則**：題組共用圖屬於整組的材料，放在**文章（passage）區**；獨立題的圖屬於該題，放在**題幹之後**。腳本據此選擇上界錨點（題組→題組標記／子標題；獨立→stem 或題號行），確保裁出的 band 對應到正確的視覺脈絡。

---

## 三、band 邊界怎麼決定（不切半張圖）

定位到上界後，下界與圖底保護是裁圖品質的關鍵。

**上界**：題目／題組標記起點往上留少量 padding（`TOP_PAD`），但不高於頁眉下緣（`HEADER_Y`）。會考另有 `band_image_top`：右側並排圖的頂端常凸出於題號行上方，往上延伸把圖含進來，但絕不越過前一題。

**下界**：取「**同頁下一個題目／題號行的起點**」當硬上限（確保不吃進下一題的圖）；若是該頁最後一題，則到頁尾內文底部（`page_text_bottom`，已排除頁碼）。

**圖底保護（最關鍵）**：`band_image_bottom` 掃 band 內的圖片（`get_images`）與向量圖（`get_drawings`），對「圖頂落在 band 內」的圖取其底部 y 的 max，把下界往下延伸，**確保圖不被切半張**；但延伸絕不超過硬上限（下一題起點），避免吃進下一題。整頁框線（高度超過頁面 85% 的大矩形）排除，不誤判外框為圖。

會考題組另有更細的判斷：用 `figure_segment_count`（向量線段 + raster 圖加權計數）判斷「圖在 passage 還是在某子題」，再決定要不要把下界延伸到含圖子題之後 —— 純文字 passage 的題組，真正的圖常落在某個 `needs_figure` 子題的題幹旁或選項區。

### 寬度：一律整頁寬單欄

社會／英文／國綜／會考的題幹經探勘皆為單欄佈局。**刻意不依文字 x0 切欄** —— 題組材料常是「文字左、圖右」的圖文並排，依文字切欄會把右側的圖切掉（實測 `111_社會_g59_60` 的圖 11 在右半被誤切）。故 band 一律取整頁寬（扣左右白邊 `SIDE_MARGIN_L/R`）。`detect_columns` 保留為單一寬度決策點，日後真遇雙欄題卷可在此擴充。

### 檔名規則（跨科一致、含年份與科目）

| 類型 | 學測 | 會考 |
| --- | --- | --- |
| 獨立題 | `{簡碼}{year}_q{no}.png`（例 `S114_q24.png`） | `C{年}_{科}_q{no}.png`（例 `C111_國文_q1.png`） |
| 題組 | `{簡碼}{year}_g{首}_{末}.png`（例 `S114_g31_32.png`） | `C{年}_{科}_g{首}_{末}.png`（例 `C111_社會_g44_45.png`） |

學測簡碼：社會 `S`、國綜 `G`、英文 `E`。題組區間取該 group 全部成員的 min~max 題號（忠實：共用同一張圖），group 內所有 `needs_figure` 子題的 `figure` 欄都指向這張。

---

## 四、★ base64 安全架構（最重要）

base64 字串塞進對話／終端／工具輸出會觸發 Anthropic AUP 內容過濾器、kill 掉 session —— 這是專案鐵則。整套設計就是要讓 **base64 全程不進那些通道**。資料流分三段、職責清楚：

```
┌──────────────┐   裁圖     ┌──────────────────┐  只寫檔名  ┌──────────────┐
│  原卷 PDF     │ ────────▶ │ data/figures/*.png │ ────────▶ │  bank.json    │
│ data/raw/    │  (render)  │  獨立二進位 PNG     │  (純文字)  │ figure 欄存檔名 │
└──────────────┘            └──────────────────┘            └──────┬───────┘
                                      │                            │ build 時
                                      │  build 讀檔                 │ 讀檔名
                                      ▼                            ▼
                            ┌─────────────────────────────────────────────┐
                            │  build_app.py：figures_block()                │
                            │  PNG bytes → base64 data URI                  │
                            │  → window.__FIGS__ = {檔名: dataURI}          │
                            │  ★ base64 只在此函式內部 + 輸出 HTML 流動       │
                            └─────────────────────────────────────────────┘
```

### 1) 圖存獨立 PNG（`data/figures/檔名.png`）

裁圖腳本一律把圖存成**獨立的二進位 PNG 檔**，絕不把圖內容（bytes／base64／data URI）印出。腳本的 stdout **只**有：張數、位元組大小、檔名、座標數字、qid 清單、計數。驗圖要靠**開啟 PNG 檔**看，不是把內容印到終端。

### 2) bank.json 只存 figure 檔名（純文字、可 lint）

裁完後，`figure` 欄寫回的是**檔名字串**（例 `"figure": "S114_q24.png"`），永不寫 base64。好處：

- bank.json 維持**純文字**，可被全形／半形標點 lint、可 diff、git 能 delta。
- 題庫與圖的繫結是「檔名指向」，一張圖被多個題組子題共用時，多筆 `figure` 欄指同一檔名即可。

學測腳本把 `figure` 欄寫回 `data/bank.json` 正本；會考腳本只動 `data/_stage/cap_{科}.json` staging，不碰正本。

### 3) build 時才 base64 內嵌進 `window.__FIGS__`

只有建置這一步才碰 base64。`build_app.py` 的 `figures_block(bank)`：

- 收集 bank 中所有題目引用到的 `figure` 檔名（去重）。
- 逐一讀 `data/figures/{檔名}` 的 bytes，編成 `"data:image/png;base64," + base64.b64encode(raw)` 的 data URI。
- 組成 `window.__FIGS__ = {檔名: dataURI}` 一段 `<script>`，注入輸出 HTML。前端用檔名查這個物件拿到 data URI 顯示圖。

函式的**安全紀律寫在 docstring 與行內**：base64 字串**只在本函式內部與輸出 HTML 字串裡流動，絕不 print**。`figures_block` 只 `print` 三件事：內嵌張數／總張數、原始合計大小（MB）、缺檔清單（`figure` 欄指到但 `data/figures/` 沒有的檔名）。

> 同樣的 `</` → `<\/` 轉義由 `js_safe_json` 處理，避免資料裡萬一出現 `</script>` 提早關閉標籤。data URI 經此函式序列化後一起注入。

### 安全紀律小結（agent／貢獻者務必遵守）

- **絕不**把任何 base64 字串放進對話、終端輸出、工具參數、Read 結果。
- 腳本只印**計數與大小**；要看圖就**開 PNG 檔**。
- bank.json／staging JSON 只存**檔名**；base64 只活在 `build_app.py` 內部與最終 HTML。
- 不 `cat` 圖檔、不把圖 bytes 餵進 prompt。

---

## 五、保真，不做失真壓縮

原卷圖表**優先保真**：地圖／圖表一旦失真就影響判讀，所以**不用 pngquant、不降 DPI**等失真壓縮。可做的只有**無損**最佳化（例如 oxipng 重新編碼，像素不變、省約 27%），不算失真。

代價是單檔體積變大（含圖約 19–31 MB／場），且圖式重的科目（數學／自然）還沒加。**「保真 vs 體積」目前無理想解，列為公開待解問題**，向社群徵求做法（向量化、一科一檔再往下切、PWA 隨選載圖等），詳見 `docs/OPEN-QUESTIONS.md`。已知失敗實驗：整頁向量化 SVG 對密集圖表反而**比 PNG 大很多**（密向量臃腫），僅單純幾何線稿可能划算。

---

## 六、冪等與重用

- **學測**（`extract_figures.py`）：每次重建整個 `data/figures/`（清空 `.png` 再產），`figure` 欄以重算後的對應覆蓋寫入。
- **會考**（`extract_figures_cap.py`）：只刪除／重建本腳本負責科目的 `C{年}_{科}_*` PNG，**不動學測的 `S/G/E` 圖**。
- 兩支共用同一套 band／圖底保護機制；`extract_figures.py` 的定位與 render 邏輯**可重用於會考**，會考版即是沿用並按版面差異改寫而成。

### 用法

```bash
# 學測
uv run --with pymupdf python scripts/extract_figures.py
uv run --with pymupdf python scripts/extract_figures.py --dry-run   # 只報告不寫檔

# 會考
uv run --with pymupdf python scripts/extract_figures_cap.py
uv run --with pymupdf python scripts/extract_figures_cap.py --dry-run

# 建置內嵌（base64 只在此步流動，不進終端）
uv run python scripts/build_app.py
```

`--dry-run` 只計算 band 與印報告，不存圖、不寫 JSON，適合先檢查定位與邊界。報告會標出「band 偏矮（疑切圖）」與「band 偏高（疑含到別題）」供人工複核。
