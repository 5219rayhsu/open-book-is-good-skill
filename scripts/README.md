# scripts/ — 參考實作（reference implementations）

這裡放「開卷有益・升學」實際在用的管線腳本，作為本 skill 各 phase 的**參考實作**。

> ⚠️ **judgment 式，不是 turnkey**：這些腳本含升學專案的硬寫路徑、檔名與科目假設。
> 它們示範「怎麼做」，不是拿來原封不動跑。請先讀 [`../SKILL.md`](../SKILL.md) 與對應
> `../references/*.md`，再依你的資料源、檔名、答案鍵格式調整。核心精神是
> **先查真實資料再選策略、內建品質門檻**，不是套死腳本。

| 腳本 | Phase | 角色 |
|---|---|---|
| `scrape_ceec_math.py` | 1 偵察 | 掃官方試題列表、依檔名抓 PDF 連結；**dirty-data 硬化模範**（NFKC、寬鬆匹配、零筆守門、不吞錯）。見 `references/dirty-data-robustness.md`。 |
| `parse_soc.py` | 3 解析 | 最難啃的社會科 parser：題組 passage 綁定、領域推斷、答案鍵對齊、`needs_figure` 標記。**model parser**。 |
| `parse_cap_社會.py` | 3 解析 | 會考社會 parser（與學測結構不同的對照範例）。 |
| `extract_figures.py` | 5 裁圖 | 學測圖式題：用 stem 前綴在原卷 PDF 定位、整塊 render 成 PNG（保真、不重排）。 |
| `extract_figures_cap.py` | 5 裁圖 | 會考版裁圖（科別簡碼）。 |
| `merge_cap_to_bank.py` | 4 題庫 | 冪等 upsert 進 bank.json（qid 為鍵、備份、驗 JSON、查重）。 |
| `merge_expl_to_main.py` | 6 詳解 | 把分批生成的詳解併回 explanations.json。 |
| `anchor_pack.py` | 6 詳解 | 法規科的錨定素材包：`--build` 抓官方現行條文全文＋版本戳記、`--check` 比對異動日期當波次啟動閘、`--verify` 零 token 掃詳解的法條引用（`fail`／`historical`／`flag` 三類）。見 `references/explanations-redteam.md`。憑證與 IPv6 繞道見 `references/dirty-data-robustness.md` §5。 |
| `law_impact.py` | 6 詳解 | 月維護：比對修法前後的素材包，列出引用到異動條號的**已上線**詳解 qid。 |
| `build_app.py` | 7 build | 把題庫＋圖＋前端打包成單檔 HTML（base64 只在 build 期內嵌，絕不進對話／stdout）。 |
| `arm_parity.py` | 跨階段 | **實驗臂等價登記簿**：跨模型／跨供應商比較時，啟動端 `record()` 記下真正送出去那串字的雜湊，判分器 `assert_parity()` 不一致就拋錯、**查無紀錄＝失敗**。純標準庫、自帶六方向自檢。見 `references/batching-and-measurement.md` §15。 |

其餘未收錄的腳本（各科 parser、整題 render、答案鍵解析、題庫拆小檔＋schema＋CI 等）
同屬這條管線；需要時依同樣 judgment 原則撰寫。授權 MIT。
