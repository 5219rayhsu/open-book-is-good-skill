# 打包、網站化、部署與體積永續

> 本檔講「程式碼／資料 → 給人用的成品」最後一哩：把開發版打包成自足單檔、做成可離線的網站（PWA）、部署，以及如何讓 git 倉庫不隨產物無限長大。授權 MIT。
>
> 對應實作：`scripts/build_app.py`、`web/index.html`（開發版模板）、`sw.js`、`web/manifest.webmanifest`、`index.html`（repo 根索引）。決策脈絡見 `docs/DECISIONS.md`。

---

## 0. 兩種交付，一份原始碼

同一套 `web/` 程式碼同時餵兩種交付，靠「資料來源優先序」分流，互不衝突：

| 交付 | 開啟方式 | 資料怎麼進來 | 給誰 |
| --- | --- | --- | --- |
| **整合網站（PWA）** | 瀏覽器開 `web/index.html`（http/https） | `loader.js` 走 `fetch('../data/*.json')` | 一般使用者（主交付） |
| **離線單檔 HTML** | 雙擊（`file://`） | `build_app.py` 把資料內嵌成 `window.__BANK__` 等全域變數 | 沒網路／要備份的人（備案） |

關鍵在 `loader.js`：**優先採用 `window.__*` 內嵌資料，沒有才 fetch**。所以單檔版走內嵌、開發版走 `python3 -m http.server` 的 fetch，同一份 JS 兩邊都跑得起來，不必維護兩套。

為什麼需要單檔版？瀏覽器在 `file://`（直接雙擊 HTML）下會擋 `fetch()` 本機檔，開發版那種 `fetch('../data/bank.json')` 會失敗、卡在「題庫尚未載入」。單檔版把題庫／關聯／樣式／程式全部內嵌進一個 HTML，零伺服器、零前置步驟，雙擊就能練。

---

## 1. `build_app.py`：內嵌成單檔

純標準庫、確定性。流程（對應 `build()`）：

1. 讀 `data/bank.json`（原樣內嵌）、`data/relations.json`（精簡成純 qid 清單）、`data/essays.json`、`data/explanations.json`、`data/essay_samples.json`（後三者可能尚未生成，缺檔時內嵌空物件，不報錯）。
2. 讀 `web/index.html`：剝除 `<!--PWA-->…<!--/PWA-->` 區塊（那是網站版專用，`file://` 不適用）→ 把 `<link app.css>` 換成內嵌 `<style>` → 在第一個 `<script src="srs.js">` 之前注入資料區塊 → 把每個 `<script src>` 換成內嵌 `<script>`。
3. 一場考試輸出一份獨立單檔；同時產生 repo 根 `index.html`（索引／Pages 首頁）與 `.nojekyll`。

### 注入的全域變數

資料區塊把以下變數塞進 `window`，給 `loader.js` 取用：

| 變數 | 內容 | 來源 |
| --- | --- | --- |
| `window.__BANK__` | 題庫（原樣） | `data/bank.json` |
| `window.__FIGS__` | `{檔名: dataURI}` 的圖庫 | `data/figures/*.png`，build 時才 base64 |
| `window.__REL__` | `{qid: {similar:[qid…], opposite:[…], related:[…]}}` | `data/relations.json`（精簡） |
| `window.__ESSAYS__` | 申論題 | `data/essays.json` |
| `window.__EXPL__` | `{qid: {t, c}}` 本題詳解 | `data/explanations.json` |
| `window.__ESAMPLES__` | `{qid: [範本…]}` 申論範本 | `data/essay_samples.json` |

> 注意：JS 端對 `window.__BANK__/__REL__` 的命名沿用「BANK／REL」；`figures_block()` 注入的鍵名是 `window.__FIGS__`。建置腳本內 `relations` 變數名為 `rel_slim`，請以實際程式為準，勿臆造欄位。

### 一場考試一份自足單檔（不出合併版）

`EXAM_BUILDS` 列出要產出的考試：傳 `exam` 給 `build()` 時，只留該考試的題／詳解／關聯／圖，輸出較小單檔。目前產出：

- `開卷有益_學測.html`（約 19 MB）
- `開卷有益_會考.html`（約 31 MB）

**刻意不再輸出「學測＋會考合併版」**（曾約 50 MB）。理由（見 `docs/DECISIONS.md` 2026-06-19）：

- 合併檔是會慢慢長大的中心化巨物，逼每個人扛下用不到的東西，與「一場考試＝一份自足單檔」的 plurality／subsidiarity 相反。要全包的人下載多份即可。
- 50 MB 會踩 GitHub 對單一檔案 50 MB 的警示線；砍掉後最大檔是會考 31 MB，乾淨過關。

### repo 根 `index.html`：很薄的索引

`build_index()` 產生 repo 根 `index.html`，純靜態、零相依。它同時是 **GitHub Pages 首頁**與**本機 clone 的下載目錄**：

- 一顆「線上練習」鈕 → `web/index.html`（網站版 PWA，隨開隨用、可加到主畫面、可離線）。
- 各考試卡片 → 下載對應的離線單檔（挑要考的那一份就好，不必扛全部）。

它是索引、不是容器：列出各獨立單檔供挑選，本身不打包任何題庫。

### base64 安全架構（鐵則）

圖檔走「PNG 獨立存 → bank 只存檔名 → build 時才 base64 內嵌」：

```
data/figures/*.png   （二進位 PNG，加一張多一張）
      │
      ▼  bank.json 的題目只記 figure 檔名（純文字、可 lint、可 diff）
      │
      ▼  build_app.py 的 figures_block() 讀 PNG → base64 → 組成 window.__FIGS__
      │
      ▼  base64 字串只在「本函式內部」與「輸出 HTML 字串」流動
```

**base64 字串絕不進入 stdout／終端輸出／對話**——會觸發 Anthropic AUP 內容過濾器、違反專案鐵則。`figures_block()` 只 print 張數／原始大小（MB）／缺檔清單，從不 print 編碼字串。`js_safe_json()` 另把任何 `</` 轉成 `<\/`，避免資料裡萬一出現 `</script>` 提早關閉標籤。

---

## 2. 前端鐵則

打包腳本只是「把檔案串起來」，真正的可維護性靠前端自律：

- **ES5 語法**：不用 `import`／模組、不用樣板字串（backtick）、不用 `innerHTML`。SW 與註冊碼也維持 ES5（`var`、`function`），舊環境與 `file://` 都安全。
- **DOM 用 `el()`／`textContent`**：節點以建構函式組裝、文字一律 `textContent`，杜絕 XSS 注入面；不靠字串拼 HTML。
- **檔 < 800 行**：`web/` 各模組維持小而專一（多數 < 400 行）。`app.js` 目前約 780 行、最接近上限，再長就要拆模組；新增功能優先開新檔，並同步加進 `build_app.py` 的 `JS_ORDER` 與 `sw.js` 的 `SHELL`。
- **載入順序有意義**：`JS_ORDER`（build）、`<script src>`（`web/index.html`）、`SHELL`（`sw.js`）三處的 JS 清單必須一致，否則單檔版／網站版行為會漂移。

---

## 3. PWA：manifest + Service Worker

### manifest

`web/manifest.webmanifest`：`scope: "../"`、`start_url: "./index.html"`、`display: standalone`、`theme_color: #3a6ea5`，icon 走 `icon-192.png`／`icon-512.png`。`web/index.html` 的 `<!--PWA-->` 區塊掛 `<link rel="manifest">` 與 `<meta name="theme-color">`。

### Service Worker（`sw.js`）

放在 `升學/` 根、`scope=升學/`，由 `web/index.html` 以 `register('../sw.js', {scope:'../'})` 註冊；**只在 http/https 下註冊**（`file://` 單檔版不跑 SW）。路徑全用相對 → 在 GitHub Pages 子路徑下也安全。

快取策略 = **cache-first，shell precache + 隨選快取 `/data/`**：

- **install**：把 `SHELL` 清單（`web/` 的 HTML/CSS/JS + `manifest` + 兩顆 icon + `data/bank.json` + `data/explanations.json`）逐一 `cache.add`，個別 `catch`——缺一檔不讓整個 install 失敗。然後 `skipWaiting()`。
- **activate**：刪掉所有非當前版本的舊 cache，再 `clients.claim()`。
- **fetch**：先 `caches.match`，命中即回；未命中才 `fetch`。**`/data/` 底下的回應（題庫／詳解／圖檔）首次抓到就 clone 進 cache**，之後離線可用——這就是「圖隨選載入、不內嵌 base64」的網站版做法。離線且未快取的導覽請求退回 `web/index.html`。

> **改版鐵則：改 shell 內任何檔就把 `CACHE` 版號 +1**（目前 `var CACHE = 'obig-sheng-v4'`）。版號一變，`activate` 會清掉舊 cache，回訪者下次 reload 拿到新版。cache-first 的代價是更新延後一個 reload，可接受。忘記 +1 = 使用者卡在舊版。

---

## 4. 產物層收斂決策

`docs/DECISIONS.md`（2026-06-19）把產物結構收斂成：

- **主交付 = 整合網站（GitHub Pages／PWA）**：各考試／科目進同一個站，依選單切換、**資料按需 fetch、圖隨選載入**。網站不內嵌 base64，**根本不產生那種肥大**。「全世界的考試都能在這裡找到」——「這裡」就是一個站。
- **離線單檔 = 按需匯出、走 GitHub Release**（不 commit 進 git）：單檔是 build 產物，build 後上傳為 **Release 附件**；網站放「下載離線版」鈕，直連 `releases/latest/download/檔名`，不跳轉第三方雲端。
  - 不放第三方雲端硬碟：大檔公開下載有掃毒中介頁與下載額度限制、UX 差。Release 內建、免費、與專案同處、不影響 clone 大小，單檔上限 2 GB（我們才 19–31 MB）。
- **離線單檔用途仍保住**：服務沒網路的學子——「一次有網路抓下 → 永久離線 ＋ 可拷貝」。

> **為什麼改**：base64 倍數成長其實是「離線單檔這個格式」逼出來的。網站為主、單檔下放 Release，兇手就不進 git。一個整合站＝一份引擎、一次部署，比「N repo × N 站 × 各自 rebuild」維護成本低得多。
>
> **遷移狀態**：里程碑，不急著現在動。現況 `升學/` 仍 commit 著兩科單檔、git 歷史已肥；遷移＝① 開乾淨新 repo 或清理歷史 ② 單檔改丟 Release、repo 不再 commit ③ 各科資料整合進同一站。等「要擴科」時一起做。

---

## 5. 體積永續：三配套

病灶：build 出的單檔是大 base64，改一字整串全變、git 無法 delta，每次 rebuild ＋ commit 就疊一份約數十 MB 副本，撐大 `.git`。

1. **里程碑才提交大單檔**：rebuild 出的大單檔只在里程碑才 commit（例如一輪隔夜生成完），不是每次微調都 push。原始碼／資料是純文字、可 delta，照常隨時提交。（收斂後更徹底：單檔根本不進 git、改丟 Release，見 §4。）
2. **淺層 clone 預設**：`git clone --depth 1` 當預設取得方式（寫進 README）；完整歷史留給要稽核的人。
3. **一科一檔天生有上限**：一科一檔 → 體積有上限（你不會把所有考科疊進同一檔）。某科自己也太大時，下一步是**再往下切**（依年份或科目），或讓圖走網站版隨選載入。原則是「**讓沒有任何單一檔案需要變那麼大**」，而非「把一個巨檔壓小」。

> **圖檔保真是地板**：原卷圖表優先保真，**不做失真壓縮**（pngquant／降 DPI 等會讓地圖／圖表失真、影響判讀）。圖檔（一科約 13–22 MB）是體積地板、降不掉；結構解決不了體積，體積仍靠上述三配套。「保真 vs 體積」列為公開待解問題，見 `docs/OPEN-QUESTIONS.md`。
>
> GitHub 硬限制供參：單一檔案 100 MB（超過直接擋 push）、50 MB 會警示、倉庫建議 1 GB 內。

---

## 6. 重建與 smoke 驗收

### 重建

```bash
cd 升學/
python3 scripts/build_app.py
```

產出：`開卷有益_學測.html`、`開卷有益_會考.html`、repo 根 `index.html`、`.nojekyll`。腳本會 print 每科 MB 與圖片內嵌張數／缺檔。

### preview smoke（每次改 build／前端後必跑）

用 preview 開**離線單檔**（最嚴格：沒伺服器、沒 SW，全靠內嵌資料），逐項驗：

- [ ] 考試選擇器：切換考試後，科目／出題／雷達／診斷／藍圖都 scope 到該考試。
- [ ] 型別排序：多題出卷（整卷／模擬／混合）維持「單選 → 多選 → 題組 → 非選」，型別內各科交錯。
- [ ] 題組：題幹 + 子題完整呈現、作答正常。
- [ ] 多選題：可複選、計分正確。
- [ ] 詳解：作答後本題詳解（`window.__EXPL__`）正常顯示；缺詳解的題不報錯。
- [ ] **0 console error**：開 devtools console，全程無紅字。

網站版另驗：http server 下 SW 註冊成功、離線後仍可開、圖隨選快取生效（首次線上看過的圖，離線再看仍在）。
