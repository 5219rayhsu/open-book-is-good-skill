# sample-output/ — 真實產出切片

這是「開卷有益・升學」**實際 `bank.json` / `explanations.json` 的真實切片**，讓你在讀
[`../walkthrough.md`](../walkthrough.md)（學測社會 111 端到端流程）之餘，直接看到管線**跑完後長什麼樣**。

## 內容

| 檔 | 是什麼 |
|---|---|
| `gsat_社會_111_題組切片.json` | 學測社會 111 一個題組（`group_id = 111_社會_g59_60`）的 2 小題：共用 `passage`、各自 `stem`／`options`／`answer`／`type`，並標 `needs_figure` 與裁圖檔名。 |
| `gsat_社會_111_詳解切片.json` | 對應 2 題的詳解（`{qid: {t, c}}`，t＝解析、c＝信心）。 |
| `S111_g59_60.png` | 該題組共用的原卷圖（美墨邊界都會區域圖）。`extract_figures.py` 整塊 render 的產物。 |

## 看點

- **題組綁定**：兩小題共用同一 `passage` 與 `group_id`，前端據此「一篇文章只顯示一次、底下列小題」。
- **圖式題**：`needs_figure=true` 且 `figure` 指向 PNG 檔名；原圖獨立存放（`bank.json` 只存檔名、純文字可 lint，base64 只在 build 時內嵌）。
- **試題逐字**：題幹／選項忠實保留（著作權法 §9 不受著作權保護）；詳解為 AI 整理、標信心、非官方標準答案。

換年份／科目／考試，產出格式相同 —— 這就是本 skill 要長出來的東西。
