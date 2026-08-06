---
name: open-book-is-good
description: 考古題自學系統（官方開放試題→題庫→詳解→上線）的方法正本與品質門檻。對這類系統做以下任何一件事，動手前先載入本 skill：建置新考試／新科目／新年度、下載轉檔、解析入庫、答案驗證、裁圖、生成詳解、跑批、紅隊查核、修復（修復站／修詳解／修題）、模型量測比較、build／上線／發佈／部署。觸發用語：「跑紅隊」「抽查」「修一下詳解」「修復站」「上線」「發佈」「部署」「解析」「入庫」「裁圖」「跑批」「加一科」「加年度」，或任何會讀寫 bank.json／explanations.json 的工作。四道必跑門（答案配對全驗、題數缺號、圖題掛載、詳解紅隊）與段落級修復架構都定義在這裡，跳過本 skill 等於重犯已解過的 bug。已跑通臺灣國考，方法延伸至升學（學測／會考）等公開試題。不適用：與題庫資料無關的純前端樣式雜務；受著作權保護的商業題本。
---

# 開卷有益 Open-Book-Is-Good：考古題自學系統復刻手冊

把**官方開放試題資料**長成一套「考古題自學系統」的判斷式復刻手冊。
已在臺灣國考跑通，方法延伸至升學（學測 GSAT／會考 CAP）等其他公開試題。

**本檔是目錄，不是全文。** 對著「任務路由表」查你要做的事，讀它指的那一份 reference
的那一節——不要從頭讀到尾。方法細節、程式、實測案例都在 `references/`，
同一件事只寫在一個地方。

---

## 四道不可略過的必跑門

> 前三道零 token。**證據、程式與實測案例在 `references/gates.md`；本清單是宣告，
> 讀不讀證據都不構成跳過的理由。**
>
> 1. **答案配對全驗** —— 每題答案**逐題**對官方標準答案核對，**全跑、不抽樣**。
>    擋的是解析時的整體錯位（某題答案套到下一題），結構檢查擋不到。→ `gates.md §A`
> 1a. **每卷題數與缺號檢查** —— 官方宣告題數／最大題號／入庫筆數三者相等且無缺號。
>    上一道只驗「入庫的題」對不對，**驗不到「該入庫卻沒入庫的題」**；實測抓出一卷少 32 題。
>    → `gates.md §A2`
> 1b. **圖題掛載雙向檢查** —— 引用圖卻無圖檔、有圖檔卻不引用圖、同一 PNG 掛多題。
>    實測抓出 5 題圖掛錯、2 題該有圖卻掉引用（且選項退化、根本無法作答）。→ `gates.md §A3`
> 1c. **答案狀態在入庫時就標注** —— 官方送分／官方未公布／多答皆給分／非選題／
>    **我們讀不出來**，五件事各有各的值。**「我不知道」與任何合法值同形，解析失敗就會
>    偽裝成合法資料**：實測兩整卷 100 題被標成送分，前端把任何作答都判對，存活數月。
>    → `gates.md §A4`
> 2. **詳解紅隊** —— AI 生成**選擇題與申論題**解析後，**一定**要反駁式紅隊查核；執行前
>    **詢問使用者要「全跑」還是「抽查」**，不得跳過、不得自作主張。
>    → `gates.md §B`、`explanations-redteam.md` §3
> 3. **模型比較必過臂等價閘** —— 任何跨模型／跨供應商比較，判分器**必先**
>    `assert_parity()`（**查無紀錄＝失敗**），報告必附 parity 段落。實測：同一個模型、
>    同一批題、同一支判分器，只改啟動包裝，lint 從 0/20 變 20/20——**差 100 個百分點
>    是啟動者的差異，而它長得像結果**。→ `batching-and-measurement.md` §15
>
> 🔴 **缺產物＝未跑**：四道門各留一份可查產物（建議 `data/_gate_reports/`）。
> 「檔不存在」與「檔存在但是空的」必須分得開——否則沒跑跟跑了全過長得一模一樣。

> **教訓畢業律**：凡 `references/` 中的教訓**重犯一次**，即升級為「必經之路上的機器閘
> ＋本清單一行」，不得停留在散文；不可機檢者至少升級為**產物形狀要求**（缺了看得見）。
> 散文規則要生效得先被想起來，而重犯正是「想不起來」的證據——同一條規則重犯 N 次，
> 不是 N 次注意力失敗，是它**在錯誤的形態裡待了 N 次**。

---

## 不適用（執行期的範圍判斷；「何時用」在 frontmatter）

- 受著作權保護的商業題本（出版商編排、詳解）；非公開、需授權的試題。
- 與題庫資料無關的純前端樣式雜務。

---

## 任務路由表（本檔的心臟：對著任務查，別從頭讀）

第一欄的動詞就是 frontmatter 的觸發詞。查到列 → 讀「先讀」欄那一份的那一節 → 跑「必跑門」欄。

| 你被叫來做什麼 | 先讀 | 必跑門 |
| --- | --- | --- |
| 建置新考試／新科目 | `data-sources.md`＋`shared-question-banks.md` | A、A2 |
| 下載轉檔 | `parsing.md` §1＋`dirty-data-robustness.md` | — |
| 解析入庫 | `parsing.md` §2–§12（題組作答政策看 §4′） | A、A2 |
| 裁圖／表格 | `figures.md`＋skill `exam-pdf-asset-extractor` | A3 |
| 詳解生成 | `explanations-redteam.md` §1–§2 | 紅隊 |
| 紅隊查核 | `explanations-redteam.md` §3＋`reviewer-input-parity.md` | 必跑；**先問使用者全跑或抽查** |
| 修復站／修詳解／修題 | `explanations-redteam.md` §13＋`dirty-data-robustness.md` 四 | 段落級；修題必檢詳解 |
| 跑批／量測／選模型 | `batching-and-measurement.md` §12′、§13、§14、§15、§21 | 臂等價閘 |
| build／上線／發佈 | `build-deploy.md` | preview smoke 0 console error；**推送須使用者當次授權** |
| 前端作答引擎 | `frontend-engine-rules.md` | — |
| 四道門的證據與程式 | `gates.md` | — |

**每份 reference 開頭都有目錄（超過百行者）——用節名搜尋，不要從頭讀。**
最大的三份是 `parsing.md`、`batching-and-measurement.md`、`explanations-redteam.md`。
常用定位：

```bash
rg -n 'PUA|ToUnicode|造字'      references/parsing.md          # 選項標記毀損
rg -n '臂等價|arm_parity'        references/batching-and-measurement.md
rg -n '段落級|寫入屏障'           references/explanations-redteam.md
```

---

## 外部正本（先自檢，失效即報，不得靜默略過）

本 skill 只存**方法**。「現在該做什麼」與「為什麼這樣決定」都在 skill 之外，
而且會隨時間變——所以這裡只放**指向與定位方式，絕不抄內容**（抄過來的當天就開始腐爛）。

載入本 skill 後、動工前，在專案根目錄跑一次：

```bash
test -f 國考與升學/LOOP_PLAN.md \
  && test -d 國考與升學/_dev/docs/adr \
  && test -e ~/.claude/skills/exam-pdf-asset-extractor/SKILL.md \
  || echo "POINTER-ROT：有指向失效，回報使用者，不要憑記憶繞過"
```

- **三條全過** → 你在「開卷有益」原始專案裡：
  - **本輪待辦** ＝ `國考與升學/LOOP_PLAN.md`（每輪覆寫，只信最新版）。
    **本 skill 不存任何進度數字**，別在這裡找「做到哪了」。
  - **已完成的事** ＝ `國考與升學/_build_features/runbook/progress_log.md`（按日期＋commit 追加）。
  - **決策紀錄** ＝ `_dev/docs/adr/`：公開系列 `ADR-` 必須連號，私有系列 `IDR-` 永不公開；
    引用一律帶前綴。**改方法論規則前先讀對應那則**。
  - **裁圖正本** ＝ skill `exam-pdf-asset-extractor`（以名字查可用 skill 清單；查無此名＝
    已改名或未掛載 → 回報後再動裁圖，不要自己手刻裁圖腳本）。
- **前兩條不存在**而你不在該專案 → 你是復刻者，跳過本節。
- **應存在卻不存在** → 那就是 POINTER-ROT，當場回報，不要略過。

> 為什麼要有這段自檢：`~/.claude/CLAUDE.md` 的「若上面沒展開成規則文字就先 `cat`」之所以
> 有效，是因為**失敗條件在讀的當下就看得見**。一條違反了也沒人看得見的散文路由，
> 觀測上等同於不存在——2026-08-06 實測，一整輪 8 小時的紅隊／修復／上線工作，
> 專案 CLAUDE.md 有寫路由，本 skill 仍**一次都沒被載入**。

---

## 核心哲學：judgment 式，不是死腳本

- **judgment 式**：每一卷的版面、題型、答案鍵格式都不同。解析器要先偵測「這卷的實況」，
  再選對應策略——而不是硬套一支萬用腳本。所以幾乎**每科一個 parser**。
- **內建品質門檻**：judgment 不是隨意，而是把維護者的判斷固化成**每次都遵守、不漂移**
  的門檻。寧可漏、不可錯：規則分情況（圖片題 vs 文字題、題組 vs 獨立題），不一刀切。
- **先查真實資料再下判斷**：判斷依據是資料，不是規格或假設。手法見 `parsing.md` §2。

---

## 7 phase 流程概覽

```
偵察 → 下載轉檔 → 判斷式解析 → 題庫 →【答案配對全驗・必跑】→ 裁圖 → 詳解
  →【詳解紅隊・必跑（全跑或抽查，問使用者）】→ build
```

| Phase | 一句話判斷 | 正本 |
| --- | --- | --- |
| 1 偵察資料源 | 碰到新資料源，第一步永遠是**偵察它的渲染方式**（伺服器渲染 curl 直取／JS 渲染走 iframe 或 API），再決定怎麼抓。政府開放資料的檔名年年漂移，比對**絕不 exact-match**。 | `data-sources.md` §1–§2、`dirty-data-robustness.md` |
| 2 下載轉檔 | PDF 先用 **markitdown** 轉 md（版面理解好），但它**不是萬靈丹**——多欄選項、複雜表、特殊版面會翻車，改走 pymupdf 座標序。判斷哪邊可靠正是 judgment。答案 PDF **不轉 md**，走 `find_tables()`。 | `parsing.md` §1 |
| 3 判斷式解析 | 先偵測「這卷長怎樣」再選策略：題型由答案推斷、答案表當權威題號清單、選項殘缺就 fallback 座標重抓。**題組的 `standalone` 要在此時一次標好**，進了題庫就補不回來。 | `parsing.md` §2–§4′ |
| 4 題庫 bank.json | 純文字題庫，**圖只存檔名、永不存影像**（可 lint、可 diff、git 可 delta）。共用圖與 passage 要寫進題組的**每一個**子題；改寫過 stem 就必須留 `locate_anchor`。 | `data-sources.md` §5 |
| 5 裁圖 | 圖式題缺圖等於廢題 → **裁原卷版面區塊 render 成 PNG**，忠實重現不簡化重排；不靠 `get_images()`（矢量圖抓不到）。圖→題對應**隨考試家族變**，別套同一管線。 | `figures.md`、skill `exam-pdf-asset-extractor` |
| 6 詳解 | **clean-room 自行生成，絕不抄出版商**：輸入只有題幹＋選項＋官方答案鍵。每則 `{t, c}`，`c` 是把握度。**修題必檢詳解**——回頭改了 bank，該 qid 詳解一律送檢，不做局部縫補。 | `explanations-redteam.md` §1–§2 |
| 7 紅隊＋build | 紅隊必跑、先問使用者全跑或抽查。**🔴 修復要走段落級，不要讓模型看著整則詳解改**——安全來自「模型物理上寫不進其他段落」這個不變式，不來自挑一個比較克制的模型。build 一場考試一份自足單檔，圖在此步才 base64 內嵌。 | `explanations-redteam.md` §3、§13；`build-deploy.md` |

完整端到端範例見 `examples/walkthrough.md`（學測社會 111，最難啃的一科）。

---

## 品質門檻（每次都遵守、不漂移）

| 門檻 | 規則 |
| --- | --- |
| **答案配對全驗（必跑）** | 每題 `answer` 逐題對官方標準答案核對、**全跑不抽樣**，修到 0 mismatch 才往下。 |
| **詳解紅隊（必跑）** | AI 生成解析後一定要反駁式紅隊；**執行前問使用者全跑或抽查**。抽查時真錯達 k≥4、n≈40（Wilson CI 下界 ≥ 4%）才升級該科到更強模型。 |
| **全形 lint** | 中文段落不可混半形標點；CI 一道門。修正用 **CJK 後綴規則**（`explanations-redteam.md` §5.2），**寧可漏轉、不可誤轉**（保住比值 `3:1`、數字後標點）。 |
| **詳解須查證** | 每則標把握度 `c` ＋ `meta.note` 寫明「AI 整理，非官方標準答案，須查證」。 |
| **節制門** | 只修確認的錯，不為純措辭改；改完重 lint、重驗，最小變動面。 |
| **逐字忠實** | 解析絕不改寫／摘要／翻譯；題組絕不拆散；自驗把「忠實」變可檢查條件。 |

---

## 模型路由：只記不會過期的部分

具體模型名、分層表與實測百分比都在 `explanations-redteam.md` §2（現行五層表）、
§2.2′（舊三檔表，保留供對照）、**§2.2″（反駁式紅隊不下放中階的裁決與六臂實測）**。
**那些會過期，下面四條不會**：

1. **紅隊往上查（reviewer ≥ generator）**：查核者須 ≥ 被查者，否則漏抓真錯又亂標假錯。
2. **避免成本倒置**：便宜模型生成、被強模型大量重寫＝付兩次。一次到位更省。
3. **降階必須寫明兜底驗證網是哪道門，寫不出即不准降。**
4. **選型的單位是（模型，effort）這個組合，不是模型本身。** 實測：紅隊站勝出的是
   Opus 5 **medium**，比 high 便宜 1.27× 而召回不輸——只寫「用最強模型」會讓人
   預設開 high，多付 27% 買不到東西。

> **模型名有保鮮期，原則沒有。** 改版與降價的節奏是數月一次，**照抄一年前的配置等於
> 用過期的尺**。重測時的三個坑（外部跑分不可照抄、先分辨模型層／prompt 層／架構層、
> 樣本量先算）見 `batching-and-measurement.md` §12′。
> 跨模型比較前先過**臂等價閘**（§15、`scripts/arm_parity.py`）。

---

## base64 安全鐵則（最高優先）

把任何 base64 字串塞進對話／終端／工具輸出，會觸發內容過濾器、**kill 掉 session**。
整套圖架構就是為了讓 base64 全程不進那些通道。

- **絕不**把 base64 放進對話、終端輸出、工具參數、Read 結果。
- 裁圖／批次腳本只 print **計數與大小**；要看圖就**用 Read 開 PNG 檔**，不 `cat`、不 `head`。
- `bank.json`／staging JSON 只存**檔名**；base64 只活在 `build_app.py` 內部與最終 HTML。

資料流三段與 `js_safe_json()` 等細節見 `figures.md` 四。

---

## 著作權與範圍

- **著作權法 §9.1.5**：依法令舉行之各類考試**試題及其備用試題**，不得為著作權之標的
  ⇒ 官方試題與標準答案**可自由重製**，標準答案作為權威答案鍵使用。
- **但 §9 不解放出版商加值的部分**：不抄編排、不抄詳解，出版商寫法**不餵進**任何 prompt。
  clean-room 紀律、作文政策與三層授權（MIT／§9／官方樣卷）見 `data-sources.md` §3。
- **範圍是對象決策，不是技術決策**：收哪些年度／課綱／考別由維護者依服務對象拍板，
  其餘流程不變。→ `data-sources.md` §4
- **開一套新考試前先做「科目重疊矩陣」**：共用科目建一次、用 `exams` 陣列標歸屬、
  題庫層去重。→ `shared-question-banks.md`

---

## references 索引

| 檔 | 主題 |
| --- | --- |
| `references/gates.md` | **四道必跑門的證據庫**：rationale、程式、實測案例、產物形狀要求 |
| `references/data-sources.md` | 資料源偵察、下載、著作權 §9、clean-room、三層授權、bank.json schema（含 `standalone`／`locate_anchor`） |
| `references/parsing.md` | judgment 式解析、markitdown vs pymupdf、每科 parser、**§4′ 題組作答政策分類**、冪等 merge、自驗、PUA 造字與 ToUnicode 毀損 |
| `references/figures.md` | 裁圖（整塊 render）、定位、**圖→題對應隨考試家族變**、**KaTeX 分流與假圖訊號**、band 邊界、base64 安全架構、保真 |
| `references/explanations-redteam.md` | clean-room 詳解、三段固定結構、品質拉齊五機制、token 工程七槓桿、**§2 模型五層表＋§2.2′ 舊表對照**、反駁式紅隊、Wilson 停止規則、**§13 段落級修復**、作文政策 |
| `references/build-deploy.md` | build 單檔／網站、PWA／Service Worker、體積永續、發佈閘門、落地頁數字會過期、**三層文件**、skill 觸發面事故 |
| `references/dirty-data-robustness.md` | NFKC 正規化、寬鬆匹配、零筆即報、不吞錯、原子寫入、官方 PDF 文字層毀損的偵測與 vision 復原硬門、**四、修題必檢詳解** |
| `references/batching-and-measurement.md` | 消除工具往返、批次大小算式、token 量測紀律、**§12′ 重測三坑**、§13 評測環境須與生產一致、§14 樣本量先算、**§15 臂等價**、§21 量測迴路的污染 |
| `references/reviewer-input-parity.md` | 審查者輸入等價：欄位可見性註冊表、源頭可審性 lint、物化 payload parity、熔斷器、圖片盲區協議 |
| `references/shared-question-banks.md` | 科目重疊矩陣、共用科目建一次、`exams` 陣列、去重紀律、混卷模擬考內容指紋去重、跨年孿生題不可 stem-only 去重 |
| `references/frontend-engine-rules.md` | 題組／承上題情境引入規則、出題演算法、標記與儲存的職責分工 |
| `examples/walkthrough.md` | 端到端範例：學測社會 111（最難啃的一科） |
| `examples/sample-output/` | 真實產出切片：學測社會 111 題組（passage＋小題＋圖＋詳解 JSON） |
| `examples/pipeline-templates.md` | 管線範本：操作卡、金樣詳解、錨定素材包各一則 |
| `docs/adr/` | 方法論決策紀錄；**改方法論規則前先讀對應 ADR** |
| `scripts/` | 各 phase 的參考實作；judgment 式、需依自身資料調整，見 `scripts/README.md` |
| `CONTRIBUTING.md` | 如何參與、三層授權、全形標點規範 |
