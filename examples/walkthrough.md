# 端到端實作範例：學測社會 111

> 用一個真實年份、一個科目，把「官方 PDF →雙擊即用的單檔 HTML」整條管線跑一遍。
> 這份範例所有指令逐步可照做；換年份／科目只要改檔名。授權 MIT。

## 為什麼挑社會 111

社會卷是這套管線裡**最難啃**的一科，正好拿來示範完整流程：

- **幾乎全為題組**：一段共用材料（◎ 引文／統計表）底下掛數小題，passage 要綁對。
- **大量圖表題**：學測社會 111–115 共 326 題，其中 175 題（約 54%）標了 `needs_figure`，得對照圖才能作答。光 111 這一年就有 67 題、其中 41 題需要圖。
- **跨領域**：歷史／地理／公民交錯，沒有固定分區，領域得用關鍵詞推。
- **markitdown 會把複雜統計表打散**：111 卷尤其明顯，選項被吃掉、非選題幹被切成數字碎片，需要 pymupdf 座標 fallback 補抓。

把社會 111 跑通，其他文字科（國綜、英文）跟其他年份都是同一條路的子集。

---

## 全景

```
ceec 試題 PDF ─┐
               ├─markitdown─▶ 111_社會_試題.md ─parse_soc.py─▶ bank.json
ceec 答案 PDF ─┘                                （題幹／選項／題組／型別／needs_figure）
                  └─pymupdf find_tables─▶ 答案鍵（對應各題，含非選的「／」）

bank.json（needs_figure 題）─extract_figures.py─▶ data/figures/*.png（bank 只存檔名）

詳解：Sonnet 生成 + Opus 抽驗 ─▶ explanations.json

      build_app.py ─內嵌 bank／詳解／圖(base64)─▶ 開卷有益_學測.html
                                          └─preview smoke（瀏覽器驗 0 console error）
```

七步：① 偵察下載 → ② markitdown 轉檔 → ③ `parse_soc.py` 解析 → ④ `extract_figures.py` 裁圖 → ⑤ Sonnet 詳解 + Opus 抽驗 → ⑥ `build_app.py` 出單檔 → ⑦ preview smoke。

> **著作權**：大考中心歷年試題依著作權法 §9「依法令舉行之各類考試試題」不受著作權保護，可自由重製。官方標準答案 PDF 為權威答案鍵；出版商編排／詳解不抄、不餵進生成 prompt（clean-room）。

---

## 步驟 1：偵察 ceec，取試題 + 答案 PDF

大考中心 `ceec.edu.tw` 的歷年試題頁是靜態 HTML，PDF 連結藏在 file_pool 清單裡。用 `curl` + `python` 抓連結比 WebFetch 快又準。

```bash
cd "開卷有益/升學"
mkdir -p data/raw

# 偵察：抓該科歷年試題列表頁的 HTML，從中撈出 file_pool 的 PDF 連結
# （xsmsid 是 ceec 該科目列表的頁面參數；社會科與國綜／英文各自不同）
curl -sL -A "Mozilla/5.0" "https://www.ceec.edu.tw/xmfile?xsmsid=<社會列表頁id>" \
  | python3 -c "import sys,re; \
print('\n'.join(re.findall(r'/file_pool/[^\"\x27]+\.pdf', sys.stdin.read())))"
```

從清單裡認出 111 社會的兩個檔（試題卷、標準答案卷），下載並用統一命名：

```bash
curl -sL -A "Mozilla/5.0" "https://www.ceec.edu.tw/file_pool/<111社會試題>.pdf" \
  -o data/raw/111_社會_試題.pdf
curl -sL -A "Mozilla/5.0" "https://www.ceec.edu.tw/file_pool/<111社會答案>.pdf" \
  -o data/raw/111_社會_答案.pdf
```

**命名契約（後續腳本全靠它）**：

| 檔案 | 格式 | 例 |
|------|------|-----|
| 試題 PDF | `data/raw/{年}_社會_試題.pdf` | `111_社會_試題.pdf` |
| 答案 PDF | `data/raw/{年}_社會_答案.pdf` | `111_社會_答案.pdf` |

`data/raw/` 被 git 忽略（可隨時重抓，不進版控）。確認兩個檔都是合法 PDF：

```bash
ls -la data/raw/111_社會_*.pdf
# 檔案大小不應為 0；用看圖／PDF 工具開第一頁確認不是錯誤頁
```

---

## 步驟 2：markitdown 轉檔

把**試題** PDF 轉成 markdown。markitdown 的好處是閱讀順序乾淨、題組選文不錯位（比 pymupdf 直接抽文字可靠得多）。

```bash
~/.claude/skills/markitdown/.venv/bin/markitdown \
  data/raw/111_社會_試題.pdf -o data/raw/111_社會_試題.md
```

**注意**：markitdown 不裁圖、OCR 走雲端，**不用於圖**；圖留到步驟 4 由 `extract_figures.py` 處理。

轉出來的 markdown 有兩個已知毛病，`parse_soc.py` 的 `flatten_md` 會吸收掉：

1. markitdown 把題幹／選項／材料嵌進 markdown 表格（`| ... | ... |`），得攤平還原成純文字。
2. 題組標頭「a-b 為題組」常被切成兩行，且順序可能顛倒（「為題組」在前、「a-b」在後）。

**答案 PDF 不轉 markdown** —— 它走 pymupdf `find_tables` 直接解析表格（步驟 3 內）。

---

## 步驟 3：`parse_soc.py` 解析（題組／圖／答案鍵）

一支腳本同時吃 `111_社會_試題.md` 與 `111_社會_答案.pdf`，輸出結構化題目並冪等合併進 `data/bank.json`。

```bash
uv run --with pymupdf python3 scripts/parse_soc.py
```

### 它做了什麼

- **攤平**（`flatten_md`）：丟掉 markdown 表格分隔線、把表格 cell 按序拼回、過濾頁眉頁腳與作答注意事項，得到乾淨多行純文字。`join_clean` 再把 markitdown 逐字拆字造成的「中 文 字 間 空 格」黏回（只動兩側皆為 CJK 的空格，不黏壞英數）。
- **章節邊界**（`section_bounds`）：認出「第壹部分」單選題號上限與「第貳部分」起點。
- **題組綁定**（`parse_groups`）：題組標頭以三形態容錯比對（同行 `a-b為題組`、顛倒兩行、正常兩行），把標頭後到第一個子題前的材料抓成 `passage`，組內各題共用同一 `group_id`（如 `111_社會_g28_29`）。
- **切題與選項**（`parse_questions` → `split_stem_options`）：以行首題號切題，抓 `(A)`–`(E)`；`_trim_option` 清掉末選項被黏進的下一題殘留。
- **答案鍵**（`parse_answers`）：用 pymupdf `find_tables` 解析答案 PDF 的橫排 4 對「題號／答案」；單選單字母 A–E、多選多字母、非選標「／」。**答案表是官方完整題號清單**，拿來當權威過濾，剔除卷末附錄被誤判為題號的孤立數字。
- **領域推斷**（`infer_domain`）：歷史／地理／公民各有關鍵詞表，命中最多者勝；平手或皆 0 留空，不武斷判定。
- **needs_figure**（`needs_figure`）：社會圖多，**寧可多標** —— 題幹或 passage 出現「圖／表／地圖／附圖／照片／示意／統計圖／曲線／分布」、或選項數 < 4（圖被吃掉）、或選項全空，就標 `True`。

### 破碎統計表的 fallback（111 卷的重點）

markitdown 把 111 的複雜統計表線性化失敗時，會出現兩種髒資料，`parse_year` 用 PDF 座標重抓救回：

- **選擇題選項不足**：答案是字母（A–E）但解析到的選項 < 4 → 用 `pdf_text_rows` 建立 PDF 座標行（頁→上→左排序），再 `qfix_from_pdf` 依閱讀順序重抓題幹 + 選項。
- **非選題幹變數字碎片**：答案是「／」但題幹中文字 < 8 → `nonmc_stem_from_pdf` 從題號列拼到下一題號／頁眉前，重建題幹。

座標行是 lazy 建立的（只有真的需要 fallback 才開 PDF）。

### 寫進 bank.json 的每題欄位

```jsonc
{
  "qid": "111_社會_1",     // {年}_社會_{題號}
  "exam": "學測",
  "subject": "社會",
  "year": 111,
  "no": 1,
  "domain": "公民",         // 歷史／地理／公民／""（推不出留空）
  "type": "單選",           // 單選／多選／非選
  "stem": "……",            // 逐字忠實擷取，不改寫不摘要
  "options": {"A": "…", "B": "…", "C": "…", "D": "…"},
  "answer": "B",            // 多選多字母；非選為 ""
  "group_id": null,         // 題組則為 "111_社會_g28_29"
  "passage": "",            // 題組共用材料
  "needs_figure": true      // 圖表題標記
}
```

`merge_bank` 是冪等的：讀現有 bank → 移除舊社會題 → 加新社會題 → 寫回，不動國綜／英文。

### 跑完會看到（與真實一致）

```
111 社會:67 題 | 型別 單選57 非選10 | 有答案 57 | needs_figure 41 (61%) | 題組 ...
...
合計 326 題 | 文字可答 151 (46%) vs 須對照圖表 175 (54%)

抽樣(qid / domain / type / stem前40 / 選項數 / answer / needs_figure):
  111_社會_1 | 公民 | 單選 | ……  | opts=4 | ans='B' | fig=True
  ...
```

**先抽 5–8 題人工核對**（題幹完整、選項齊、題組沒拆散、答案對得上官方），再往下走。

---

## 步驟 4：`extract_figures.py` 裁圖

把 bank 中 `exam=='學測'` 且 `needs_figure==True` 的題目，所在原卷 PDF 的版面區塊 render 成乾淨 PNG，存到 `data/figures/`，供單檔離線顯示。忠實重現原卷，不簡化不重排。

先 dry-run 看 band 計算與報告，不寫檔：

```bash
uv run --with pymupdf python scripts/extract_figures.py --dry-run
```

確認 band 高度合理（沒有偏矮切圖、沒有偏高吃到別題）後正式產圖：

```bash
uv run --with pymupdf python scripts/extract_figures.py
```

### 定位策略（穩健性關鍵）

逐頁建「正規化字元索引」（`build_char_index`）：每個非空白字元對應其 span bbox。

- **獨立圖題**：用題目 stem 的長前綴（30→10 字且**頁內唯一**）定位 y 座標（`locate_text`）；對不上才放寬到 6 字、再不行用 12 字片段掃描（`locate_text_fragments`）並吸附到題號行。長前綴是為了避免題號數字或短字串撞題。
- **題組共用圖／材料**：用「N-M為題組」這個標記當主錨點（`find_group_mark`），比 passage 全文比對可靠得多 —— passage 經 markitdown 重排後字序與 PDF span 不一致，常含 ◎／圖說／數字而比對失敗。

### band（render 區塊）

- 獨立題：上界 = stem 起點（往上含題號、留 padding），下界 = 同頁下一題起點（無則到頁尾扣頁碼）；再對 band 內圖片／向量圖底部取 max（`band_image_bottom`），確保圖不被切半張、又不吃進下一題的圖。
- 題組：上界 = 題組標記 y，下界 = 同頁標記後第一個子題 y（子題落到下頁則到頁尾）。**一個 group 只 render 一張**，組內目標子題的 `figure` 欄全指向它（忠實：共用同一張圖）。

寬度一律取整頁寬單欄（`detect_columns`）：社會題組常「文字左、圖右」並排，依文字 x0 切欄會把右側圖切掉，故不切欄。render 用 zoom 2.2 把 raster + vector 一起點陣化。

### 檔名規則

| 類型 | 格式 | 例 |
|------|------|-----|
| 獨立題 | `S{年}_q{題號}.png` | `S111_q1.png` |
| 題組 | `S{年}_g{首題}_{末題}.png` | `S111_g28_29.png` |

簡碼：社會 `S`、國綜 `G`、英文 `E`。

### 安全鐵則（最高優先）

- 圖一律存成獨立二進位 PNG。本腳本**只**印張數、位元組大小、檔名、qid 清單、座標數字 —— **絕不 print 圖片 bytes／base64／data URL**。
- `bank.json` 只寫入 `figure` 檔名字串，**永不寫 base64**，保持純文字可 lint。
- 驗圖時用看圖工具開 PNG，**不要對含 base64 的檔做 cat／head**。

冪等：每次重建 `data/figures/`（清空再產），`figure` 欄以重算後的對應覆蓋。

---

## 步驟 5：Sonnet 詳解 + Opus 抽驗

clean-room 生成詳解：官方標準答案是權威答案鍵，出版商寫法不進 prompt。

### 生成（Sonnet）

文字題（非 `needs_figure`）逐題請 Sonnet 寫繁中詳解，全形標點，全標「AI 整理需查證」並附把握度。輸出彙整成 `data/explanations.json`：

```jsonc
{
  "explanations": {
    "111_社會_1": { "t": "正解 (B)。……", "c": 0.9 }   // t=詳解文字、c=把握度
  }
}
```

題組長文閱讀理解、難題改用 **Opus** 生成。

### 抽驗（Opus 反駁式紅隊）

用 Opus 對生成的詳解做反駁式抽驗，動態停（Wilson CI）：

- **統計規則**：抽樣中真錯數 **k ≥ 4 / 40** 才把該科升級為 Opus 全量重做；低於此續用 Sonnet。
- 社會科實測抽 11 題 **11 OK / 0 錯**（見 LOOP 進度），低於地板 → 續 Sonnet。
- 只修「確認錯」（如判定寫反），措辭瑕疵酌修；修完重 lint 重驗。

> 圖表題（`needs_figure`）的詳解依賴步驟 4 裁出的圖；文字題可先行。模型路由依成本守則：解析／一般詳解 Sonnet、難題／長文／紅隊 Opus、下載轉檔等機械 Haiku。

---

## 步驟 6：`build_app.py` 出單檔

把開發版（`web/`）打包成「雙擊就能用」的單檔 HTML。瀏覽器在 `file://` 下會擋 `fetch()` 本機檔，所以單檔版把題庫／關聯／樣式／程式／圖全部內嵌，不需伺服器。

```bash
python3 scripts/build_app.py
```

### 它做了什麼

1. 讀 `data/bank.json`（原樣內嵌）、`data/relations.json`（精簡成純 qid 清單，丟分數縮體積）、`data/explanations.json`、作文範本。
2. 讀 `data/figures/` 下每張 PNG，base64 編碼後組成 `window.__FIGS__ = {檔名: dataURI}`（`figures_block`）。
3. 讀 `web/index.html`，把 `<link app.css>` 換成內嵌 `<style>`、每個 `<script src>` 換成內嵌 `<script>`，並注入 `window.__BANK__` / `__FIGS__` / `__REL__` / `__EXPL__`。
4. **一場考試一份獨立單檔**：輸出 `開卷有益_學測.html`、`開卷有益_會考.html`，外加 repo 根 `index.html`（GitHub Pages 首頁＋離線下載目錄）與 `.nojekyll`。

`web/loader.js` 優先採用內嵌的 `window.__BANK__` / `__FIGS__`，所以同一套程式碼：單檔版走內嵌、開發版（`python3 -m http.server`）走 fetch，互不衝突。

### 圖的安全架構（重申）

圖的流向是：**PNG（步驟 4）→ bank.json 只存檔名 → build 時才 base64 內嵌進 `window.__FIGS__`**。base64 字串只在 `figures_block` 內部與輸出 HTML 字串裡流動，**絕不 print**（避免塞進 stdout／對話觸發內容過濾器，這是過去崩潰的主因）。`build_app.py` 只印張數／大小／缺檔。另外 `js_safe_json` 會把資料裡的 `</` 轉成 `<\/`，避免內容裡萬一出現 `</script>` 提早關閉標籤。

### 跑完會看到

```
圖片內嵌:175/175 張,原始合計 ... MB
學測: 開卷有益_學測.html  ... MB
會考: 開卷有益_會考.html  ... MB
首頁/目錄:index.html(GitHub Pages 首頁 + 離線下載目錄)
```

---

## 步驟 7：preview smoke

開單檔做冒煙測試，確認題卡渲染、答案揭露、詳解、題組 passage、圖片載入都正常，且 0 console error。

開發版（可即時改）用 http.server，圖走 `../data/figures/`：

```bash
cd "開卷有益/升學"
python3 -m http.server 8000 --directory web
# 瀏覽器開 http://localhost:8000/
```

單檔版直接雙擊 `開卷有益_學測.html`（`file://` 可開，圖走內嵌 `__FIGS__`）。

### 冒煙檢查清單

- [ ] 題卡渲染：111 社會 67 題都出得來，正解選項標綠。
- [ ] **圖片載入**：`S111_q1.png` 等獨立題圖在題幹後、題組圖（如 `S111_g28_29.png`）在文章區，白底不反白。
- [ ] 題組：共用 passage 顯示在文章區，組內各題共用同一張圖。
- [ ] 型別排序：多題模式 單選→多選→題組→非選，型別內科目交錯。
- [ ] 詳解：揭露後顯示繁中全形詳解＋把握度＋「AI 整理需查證」。
- [ ] **0 console error**（這是過關門檻）。

通過後 commit 當下乾淨成果。換下一年（112…115）或下一科（國綜／英文）時，從步驟 1 重跑，命名契約不變即可。

---

## 一頁速查

```bash
cd "開卷有益/升學"

# 1. 偵察 + 下載（curl 抓 ceec file_pool 連結後下載試題 + 答案）
#    → data/raw/111_社會_{試題,答案}.pdf

# 2. 轉檔
~/.claude/skills/markitdown/.venv/bin/markitdown \
  data/raw/111_社會_試題.pdf -o data/raw/111_社會_試題.md

# 3. 解析（題組/圖/答案鍵 → bank.json，冪等）
uv run --with pymupdf python3 scripts/parse_soc.py

# 4. 裁圖（先 dry-run 驗 band，再正式產 PNG）
uv run --with pymupdf python scripts/extract_figures.py --dry-run
uv run --with pymupdf python scripts/extract_figures.py

# 5. 詳解：Sonnet 生成 → Opus 抽驗（k≥4/40 才升級）→ explanations.json

# 6. 打包單檔
python3 scripts/build_app.py

# 7. preview smoke（0 console error 才算過）
python3 -m http.server 8000 --directory web
```
