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

- 合併檔是會慢慢長大的中心化巨物，逼每個人扛下用不到的東西，與「一場考試＝一份自足單檔、各自自足」的原則相反。要全包的人下載多份即可。
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

## 發佈時清單裡有別人改的檔：推之前要自己驗（2026-08-02）

多 session 並行時，發佈腳本送出的是**整個 repo 的 HEAD**，不是「我這輪改的東西」。
實測一次發佈 5 個檔，其中 2 個是另一 session 的批次（7,954 則詳解拿掉開頭套語）。
**按下 `--push` 的人為全部內容負責**，不能只驗自己那份。

### 零 token 五道驗收（單行 JSON 的 `git diff` 永遠是「1 行改 1 行」，看不出內容）

| 驗什麼 | 為什麼 |
| --- | --- |
| **筆數對帳**（發佈前 vs 發佈後，逐檔） | 掉筆是最貴且最無聲的損失 |
| **長度只准往一個方向變** | 拿掉套語就只該變短。實測 min=3 max=5、0 則變長＝改動確實只做了宣稱的事 |
| **開頭殘留標點／連接詞／雙冒號** | 砍字串最常見的傷害是把句子開頭砍成「正解：，……」 |
| **空詳解數** | 砍過頭會整則變空 |
| **原字串殘留數** | 量「這次沒清乾淨多少」——它不是回歸，但要記進工單 |

實測結果：0 殘留標點、0 空詳解、0 變長，13 則開頭變成「與…」但那是
「正解：〈名詞片語〉」的合法寫法（拿掉「題眼是」之後），不是砍壞。
另有 232 則沒清到——**那與線上現況相同，不是本次造成的回歸**，
確認它已在工單裡列管後才推。

> **判準：發佈只要求「不比現況壞」，不要求「全部完美」。**
> 把「沒改到的」與「改壞的」分開算，否則永遠不敢按下發佈。

## `.gitignore` 的 `*.bak*` 擋不到**目錄名**（2026-08-02）

`figures_pre_recrop_bak/` 底下 670 個衍生 PNG 被 track 了一個月。
`*.bak*` 是**檔名**樣式，對目錄無效：

```gitignore
*_bak/
*_bak_*/
data/*/raw/
```

止血：`git rm -r --cached <目錄>`（**工作樹檔案保留**，跑完務必數一次實體檔還在）。
根治是「衍生圖不進 repo，部署時重生」——source 是 PDF ＋ 偵測程式 ＋ 少量手修的
`overrides/`。**別用 Git LFS**（把問題換個地方付錢）。

### 🔴 但別把這件事當成 `.git` 變肥的原因——我就這樣誤判了一次

同一輪我看到 `du -sh .git` = 487M（一個月前 93MB），又看到 670 個 PNG 被 track，
就把兩者接成因果寫進 commit message 與工單。**兩個事實都對，因果是我補的，沒量佔比。**

量完之後：

```
.git 487M 的組成         歷史 blob 佔比（全部 1,111 MB）
  177M  packed            data/social-worker/   185.8 MB / 30 blob
  310M  鬆散物件 3,696 個   data/doctor/figures/  123.2 MB / 419 blob
                          *_bak/ ＋ raw/         10.4 MB ← 只有 1%
```

**真正的大宗是資料檔反覆 commit**：`bank.json`／`explanations.json` 每改一次就是
一份幾 MB 的新快照，30 次就是 180MB。那是大型題庫專案的正常成本，不是缺陷。

### 先跑 `git gc`，再談要不要改寫歷史

`git gc` 把鬆散物件收進 packfile 並做差分壓縮，**不動任何 commit、SHA 全不變、
不需要 force push**。實測三個 repo：

| repo | gc 前 | gc 後 |
| --- | ---: | ---: |
| 開發用（含全部歷史） | 487M | **287M** |
| 發佈用（rsync 產生，**從未 pack 過**） | 351M | **241M** |
| skill | 3.0M | **788K** |

> **判準：`du -sh .git` 這個數字本身會誤導**——它把「還沒整理的暫存」與「永久歷史」
> 加在一起。要判斷 repo 是不是真的臃腫，看 `git count-objects -vH` 的 **`size-pack`**，
> 不是資料夾大小。用 `du` 的數字去下「需要改寫歷史」的結論，等於拿沒對焦的尺量東西。

特別注意 **rsync 產生的發佈用 repo 幾乎一定沒 pack 過**（沒人在那裡跑過會觸發
auto-gc 的日常操作），往往是三個 repo 裡最肥的那個。

**歷史改寫（`filter-repo`／BFG）是最後手段**：所有 commit SHA 全變、必須 force push、
別人手上的 clone 全部作廢。先量 `size-pack`、先 `gc`，剩下的量級若仍不可接受再談。

### 把 `gc` 掛進發佈腳本的收尾（含一個自檢被騙過兩次的實錄）

```bash
GC_LOOSE_MIN=${GC_LOOSE_MIN:-500}          # 低於此數整理的效益不值那幾秒
loose_count() { git -C "$1" count-objects -v | awk '/^count:/{print $2}'; }
maybe_gc() {
  local repo="$1" n; n="$(loose_count "$repo")"
  [ "${n:-0}" -lt "$GC_LOOSE_MIN" ] && { echo "· 鬆散物件 ${n:-0} 個，跳過整理"; return 0; }
  git -C "$repo" gc --quiet 2>/dev/null || { echo "⚠ gc 沒跑成功（不影響已發佈內容）"; return 0; }
}
```

掛在 **push 成功之後**，失敗只警告不擋——已經發佈出去的內容不該因為整理沒做而被判失敗。

**自檢寫了三版才擋得住**，每一版都是在 known-bad 上跑才發現破的：

| known-bad 變體 | 第一版自檢 | 修法 |
| --- | --- | --- |
| `loose_count` 讀錯欄位 | ✅ 抓到 | — |
| **把 `git gc` 換成 `true`** | ❌ **沒抓到** | 別驗「有沒有印出『已整理』」，**驗後置條件**：造出鬆散物件 → 跑 → 數量必須歸零 |
| **預設門檻打成 `999999`**（等於永久關閉） | ❌ **沒抓到** | 自檢裡用 `GC_LOOSE_MIN=0` 覆寫門檻去測執行路徑，就**驗不到預設值本身**——要多一條 range 斷言 |
| 門檻分支恆假 | ✅ 抓到 | — |

兩個可推廣的教訓：

1. **驗訊息不等於驗行為。** 「印出成功」是最容易造假的東西，把被測函式換成 `true` 就過。
   要驗的是**它宣稱造成的狀態改變**。
2. 🔴 **自檢裡為了走到某條路徑而覆寫的參數，就是這個自檢驗不到的盲區。**
   用 `GC_LOOSE_MIN=0` 逼 gc 執行的那一刻，「預設值合不合理」就掉出射程了——
   而預設值多打一個零不會有任何錯誤訊息，只會安靜地永遠不整理。
   **每覆寫一個參數，就要補一條專門驗那個參數的斷言。**

## 發佈閘門本身要有版本控管（2026-08-02）

實測踩到：`publish_platform.sh` 是**唯一擋得住敏感字外洩的閘門**，卻放在兩個
git repo 的**外面**——改壞了沒有回溯點。同一層還有 245 支建置腳本，全部一樣。

這種格局很容易長出來：資料 repo 與發佈 repo 各自納管得好好的，而**驅動它們的工具**
落在中間那層沒人管。判準很簡單：**「改壞了會怎樣」最嚴重的那個檔，往往就是沒被納管的那個。**

### 收進來時用白名單，不要用黑名單

第一版寫黑名單（列出跑批產物的樣式），結果漏掉 `*_ALL.json`／`*_lint.json`／`*_gen.js`，
一次要收 **3,556 檔／55MB**。改成白名單後是 **301 檔／2.6MB**：

```gitignore
*            # 預設全擋
!*/          # 但要能走進子目錄
!*.py
!*.sh
!*.md
_dev/        # 白名單之後再把整個目錄擋掉（順序：後面的贏）
_raw/
.venv*/
```

**失敗方向不對稱**：黑名單漏一種＝**靜默進庫**（產物混進歷史、體積長大、diff 全是噪音）；
白名單漏一種＝少收一個看得見的檔。選會吵的那一邊。

### 三個提交前必驗

1. **假的 `.env` 造出來測 `git check-ignore -v`** ——別靠「目前沒有 .env」。
2. **`git ls-files -s | grep ^160000`** ——巢狀 repo 被當成 gitlink 收進來是常見誤收。
3. **密鑰掃描要能分辨自檢 canary**：發佈腳本自己就含 `AKIAIOSFODNN7EXAMPLE`
   這類假密鑰（那是它 selftest 的 known-bad），掃描器會命中它——**看清楚再放行**。

### 🔴 新增 `.git` 會改變裸 `git` 指令的解析結果

原本那層不是 repo，腳本裡的裸 `git xxx` 會報 "not a git repository"；
現在會**安靜地找到新 repo**。收進來之後要 grep 一次所有裸 git 呼叫逐支確認。
（本輪實測：一支用 `git -C <repo>` 明確指定＝安全；一支用 `git hash-object`＝
只看內容、無 `.gitattributes` 過濾器，新舊結果實測完全相同。**但這是驗出來的，不是推的。**）

### 這個 repo 該不該有 remote

**預設不要。** 建置工具會引用內部方法論名稱、私有 repo 名與絕對路徑——
發佈腳本的敏感字掃描樣式**本身就是那份清單**。本機 repo 已經給了回溯點與 diff，
那是當初要納管的全部理由；推到雲端是另一個決定，要單獨問。
