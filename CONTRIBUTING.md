# 參與貢獻 Contributing

歡迎一起把「開卷有益 Open-Book-Is-Good」復刻手冊做得更好。這份 skill 是一套判斷式的方法論，
不是死腳本；你的實測、案例與修正，往往比新增規則更有價值。

## 怎麼參與

- **回報問題／提案**：開一個 [GitHub Issue](https://github.com/5219rayhsu/open-book-is-good-skill/issues)。
  復刻某個新考試踩到坑、發現某條規則在你的資料上不成立、或有更好的做法，都歡迎。
- **改文件**：`SKILL.md` 是手冊本體、`references/` 是各階段深入文件、`docs/adr/` 是方法論決策紀錄。
  修錯字、補案例、釐清語意，直接發 Pull Request。
- **改方法論規則之前，先讀對應的公開 ADR**（見下「改方法論前先讀 ADR」）。
- **分享復刻成果**：你把方法用到新的考試／科目／國家，歡迎在 Issue 分享，讓手冊的適用範圍長出來。

Pull Request 請說明「改了什麼、為什麼」；動到方法論規則的，請在描述裡連回對應 ADR。

## 改方法論前先讀 ADR

`docs/adr/` 收的是**方法論決策紀錄**（Architecture Decision Records）：每個影響整套管線的取捨，
為什麼這樣做、考慮過哪些替代方案、帶來什麼後果。**動方法論規則前，先讀對應 ADR**，理解它為何
長這樣——很多看似可以簡化的規則，是實測踩坑後刻意保留的。

- 詳解結構（三段固定、合併解析、A–E 指稱）→ [ADR-0003](docs/adr/0003-explanation-three-part-structure.md)
- 舊詳解重構 vs 重寫 → [ADR-0004](docs/adr/0004-reconstruct-not-rewrite.md)
- 大批量 token 工程 → [ADR-0005](docs/adr/0005-token-engineering-seven-levers.md)
- 模型分層與不降清單 → [ADR-0006](docs/adr/0006-model-tier-criteria-and-no-downgrade-list.md)
- 紅隊抽樣率 → [ADR-0007](docs/adr/0007-default-full-redteam-sampling.md)
- 三層防錯分工 → [ADR-0008](docs/adr/0008-three-layer-error-defense.md)

規則正典與操作層文件（`references/`）不可分家：改了某條規則，請同步更新它所在的 ADR 與 references，
並在 PR 說明。有不同看法但還沒定案的，先開 Issue 連回 ADR 討論，別直接改正典。

## 授權分三層（請勿混為一談）

本專案的內容分三層，授權與出處各自不同：

| 層 | 範圍 | 授權 |
| --- | --- | --- |
| **程式碼／手冊** | `SKILL.md`、`references/`、`docs/`、`scripts/`、`examples/` 的文字與工具 | **MIT**（見 [LICENSE](LICENSE)） |
| **試題資料** | 題幹、選項、官方標準答案 | 依**著作權法第 9 條**「依法令舉行之各類考試試題」不得為著作權之標的、得自由利用；引用請註明出處（機關、年度、科目） |
| **AI 生成衍生物** | 依本手冊生成的詳解、關聯資料、裁切圖 | **[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)**（公眾領域貢獻）——複製、修改、散布、商業利用皆可，不需許可、不需標示來源 |

送出貢獻即表示你同意：你新增的**程式碼／文件**以 MIT 授權釋出、新增的**衍生物內容**以 CC0 釋出，
且你有權這麼做。AI 生成內容一律標「AI 整理、須查證」與把握度，不是官方標準答案。

## 文字與標點規範

面向讀者的中文採**繁體中文（臺灣）**，不用簡體字、不用中國大陸慣用詞——優先用影片、軟體、螢幕、
登入等臺灣用語。地名一律用「臺」（臺灣、臺北）；官方全稱本身即含異體字的專有名詞（如某些機構名稱）
照原樣照抄、不改。

標點寬窄（重要）：

- **中文句子用全形標點**：`，` `。` `、` `？` `！` `：` `；` `「」` `『』` `（）` `……` `——`。
- **英文、數字、日期、URL、程式碼、`§`、縮寫**（MIT、CC0、ADR、JSON、PDF、API…）**一律半形**。
- 中英混排的句子，依該句主要語言決定標點寬窄。
- **Markdown 連結語法 `[文字](url)` 的括號是半形，這是語法、不是文案，不算違規**——CI 的全形 lint
  會放行連結語法，不要為了「補全形」去改連結括號。

`references/` 與 `docs/` 內的中文段落會過全形 lint（見 `references/explanations-redteam.md` §5）；
發 PR 前若能自己先掃一遍最好。程式碼、程式碼區塊與程式碼註解不受此規範約束。

## 行為準則

就事論事、對人友善。這是一個幫人自學考古題的公益向專案，歡迎任何能讓它更準確、更好用的貢獻。
