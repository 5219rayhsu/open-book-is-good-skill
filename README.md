# open-book-is-good

> 從**官方開放試題資料**復刻一套考古題自學系統的 Agent Skill。

這是「開卷有益 Open-Book-Is-Good」的**方法層**：一份給 AI agent 載入的判斷式復刻手冊，
教它把官方公布、可自由重製的試題（依著作權法 §9）長成一套可離線練習的考古題自學系統。

已在臺灣升學（學測 GSAT／會考 CAP）跑通，方法同樣適用國考等其他公開試題。

## 這個 skill 是什麼

一句話：**偵察資料源 → 下載轉檔 → 判斷式解析 → 題庫 → 裁圖 → 詳解（含查證紀律）→
紅隊抽驗 → build 單檔／網站。**

核心立場是 **judgment 式、不是死腳本**：每一卷的版面、題型、答案鍵格式都不同，agent 要先
「偵測這卷的實況」再選策略，而不是硬套萬用腳本；並內建品質門檻（紅隊抽驗、全形 lint、詳解
須查證），把維護者的判斷固化成每次都遵守、不漂移的規矩。

它不幫你做的事：不抄出版商的編排與詳解（那受著作權保護）、不 AI 代寫作文（改抓官方分級
樣卷）、不把任何 base64 圖內容塞進對話（內容過濾器鐵則）。

## 怎麼安裝

把整個目錄放進你的 skill 目錄（Claude Code 預設 `~/.claude/skills/`）：

```bash
git clone --depth 1 <repo-url> ~/.claude/skills/open-book-is-good
```

或在 agent 環境中把本目錄掛成可載入的 skill。skill 入口是 `SKILL.md`（含 YAML
frontmatter，`name: open-book-is-good`），agent 會依 `description` 自動辨識何時觸發。

## 怎麼使用

對載入此 skill 的 agent 說明你的目標即可，例如：

- 「幫我把某官方考試的某科某年度試題做成題庫」
- 「這套考試要新增一個科目／一個年度」
- 「復刻一整套新考試（換國家、換考別）」

agent 會依 `SKILL.md` 的 7 phase 流程執行，需要細節時載入對應的 `references/` 文件：

| 檔 | 主題 |
| --- | --- |
| [`SKILL.md`](SKILL.md) | 復刻手冊本體（給 agent 載入） |
| [`references/data-sources.md`](references/data-sources.md) | 資料源偵察、下載、著作權 §9、clean-room、bank.json schema |
| [`references/parsing.md`](references/parsing.md) | judgment 式解析、markitdown vs pymupdf、每科 parser、冪等 merge |
| [`references/figures.md`](references/figures.md) | 裁圖（整塊 render）、定位、band 邊界、base64 安全架構、保真 |
| [`references/explanations-redteam.md`](references/explanations-redteam.md) | clean-room 詳解、模型路由、反駁式紅隊、Wilson 停止規則、節制門、lint、作文政策 |
| [`references/build-deploy.md`](references/build-deploy.md) | build 單檔／網站、PWA／Service Worker、體積永續 |
| [`examples/walkthrough.md`](examples/walkthrough.md) | 端到端範例：學測社會 111（最難啃的一科） |

## 三層文件

復刻時要寫三份對象不同的文件，這份 README 是第二層：

- **`SKILL.md`（＋ `references/`）** — 給 AI agent 載入執行的復刻手冊。
- **這份 `README.md`** — 給逛 GitHub 的人的門面（這 skill 是什麼、怎麼裝、怎麼用）。
- **產物／專案 `README.md`** — 給大眾／貢獻者，寫理念 + 如何貢獻。

## 授權

本 skill（手冊、scripts、方法）採 **MIT**，見 [LICENSE](LICENSE)。

試題資料依著作權法 §9 屬公共所有；作文範本屬官方機關依其授權提供。理由：與其用 copyleft
強制衍生開源，不如把 fork／改作／商用的自由給滿，讓「開放比封閉更好用」自己長出規範。
