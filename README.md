# 稿證 PaperTrail TW

稿證把研究日誌、讀書筆記和資料表整理成繁體中文論文草稿。修改一句話時，可以打開證據表，查到當初用的是哪一段筆記、哪一節文獻，或資料表裡的哪一列。

第一次使用，可以直接看範例。兩種引文筆記的模擬回查時間平均為 78 秒和 38 秒，第 4 條引文卻出現相反結果。審查筆記指出了這個例外，證據表則列出對應資料。範例的書目可回查原文，所有計時數值皆為教學用模擬資料。

[手機閱讀全文](preview/draft.md) · [逐頁看原稿](preview/README.md) · [下載 PDF](preview/draft.pdf?raw=true) · [下載 Word](preview/draft.docx?raw=true)

[看證據表](preview/evidence.csv) · [看審查筆記](preview/review.md)

## 在自己的電腦上試跑

使用 Python 3.11 以上版本，並安裝一套繁體中文字型。Windows 可用微軟正黑體，macOS 可用蘋方，Linux 可用 Noto CJK。解壓縮後，進入含有 `pyproject.toml` 的目錄執行以下指令。

```sh
python -m pip install .
python -m papertrail build examples/citation-audit --out output
```

終端機會印出本次成果的目錄。打開 `draft.docx` 就能改稿。每次執行都產生新目錄，已經修改過的稿件可以繼續保留。若要同時編譯 PDF，請安裝 XeLaTeX，並在 `build` 指令末尾加上 `--pdf`。內建版型在 Linux 使用 Noto Serif CJK TC，在 Windows、macOS 亦可使用新細明體或蘋方。

若繪圖程式找不到已安裝的字型，可將環境變數 `PAPERTRAIL_FONT` 指向中文字型的 `.otf` 或 `.ttf` 檔。

## 啟用多代理寫作

已有稿件而只想先審查時，請用 `python -m papertrail review 稿件.docx --project 研究材料目錄 --out reviews`，不要執行 `build`。此新路徑離線產生社會科學文獻研究清單、可定位疑點與主張證據表，不修改原稿、不呼叫模型；作者決定後才另行修訂。詳見[先審後改與核對範圍](docs/review-first.md)。

打開輸出目錄的 `review.html` 可看風險摘要、文獻核讀與主張來源狀態；`decisions.csv` 留給作者逐項回覆。新增匿名風險初篩只標記可辨識線索及DOCX中繼資料／批註／修訂風險，**不自動匿名化，也不保證零提示即匿名通過**。

預設的離線模式會按筆記標題編排段落，採用作者填寫的讀書摘要，從 CSV 計算平均數，並用規則檢查草稿。安裝依賴後，這條路徑可以離線執行，全程不需要 API 金鑰。

要從零散日誌撰寫新段落，可啟動本機 Ollama 服務，選用 `ollama list` 已列出的、支援結構化輸出的指令模型。下列指令的 `MODEL_NAME` 請換成完整模型名稱。

```sh
python -m papertrail build examples/citation-audit --model MODEL_NAME --out output
```

| 角色 | 拿到什麼材料 | 交付什麼 |
| --- | --- | --- |
| 大綱編輯 | 研究問題、筆記、文獻卡和數值摘要 | 五個章節各自的標題與問題 |
| 文獻編輯 | 已讀文獻卡及作者記下的頁節 | 有出處的文獻比較，交給執筆者 |
| 執筆者 | 大綱、文獻比較和研究材料 | 摘要、正文段落及支持每段的來源識別碼 |
| 審查人 | 已完成的段落與原始材料 | 可以定位到段落的疑點、其他解釋及查證方向 |

計算、畫圖和排版均由 Python 完成。模型若回傳不存在的來源，該次執行會指出錯誤，方便修改輸入後重跑。審查意見另存於 `review.md`，由作者決定如何改稿。

Ollama 預設連線至本機的 `http://127.0.0.1:11434`。使用其他主機時，可指定 `--ollama-url`，非loopback端點另需 `--allow-remote` 明確許可。參與該階段的研究材料會傳給所指定的主機，傳送前請先確認敏感資訊、資料權限與端點信任。較長的筆記可以分篇處理，也可依模型和電腦記憶體調整 `PAPERTRAIL_NUM_CTX`，預設值為 16384。

## 放入自己的資料

可複製 `examples/citation-audit/`，改成自己的研究目錄。將 `demo` 設為 `false` 前，先替換示例筆記和所有模擬數值。程式讀取 UTF-8 文字，亦接受含 BOM 的 CSV。

| 檔案 | 填寫方式 |
| --- | --- |
| `project.json` | 必填 `title` 和 `question`。可加 `author`、`keywords`、`demo`。有數值表時再填 `metric` 和 `unit`，可用 `group_label` 命名比較條件。 |
| `notes/*.md`、`notes/*.txt` | 每個空行分隔一段筆記。Markdown 標題如「方法」「觀察」「限制」協助離線歸類。無標題的日誌會先列入觀察材料。可使用子目錄。 |
| `references.json` | 每張已讀文獻卡有 `id`、`title`、`reading_note`、`locator`、`note_citation`、`bibliography`。`url` 可放 DOI 或網址，紙本可留空。兩個引註欄可分別依芝加哥註釋書目制填寫。 |
| `measurements.csv` | `case` 是案例編號，`group` 是比較條件，`value` 是數值。全表使用同一指標與單位。每對 `case`／`group` 一筆。額外的 `id` 欄可為每列命名，例如 `V-C04L`。 |

除 `project.json` 外，至少提供筆記、文獻卡或數值表其中一類。質性研究可直接從筆記和文獻開始。數值表適合單一指標的組別比較。程式會畫出單筆資料及平均數，以資料欄位產生研究設計圖。質性資料則會產出研究問題與材料的關係圖。

若某段筆記直接使用了一篇文獻，可在句末加 `[@R-sandve2013]`。若要指向一列數據，可寫 `[@V-C04L]`。識別碼分別來自文獻卡或 CSV。Word 會把文獻引註寫入原生頁下註，資料列則記入證據表。範例中的 `notes/observations.md` 示範了如何把一段觀察連到兩筆資料。

## 找文獻與核對主張

```sh
python -m papertrail search "reproducible computational research" --limit 5 --out candidates.json
```

這個指令將查詢詞送往 Crossref，取回標題、作者、出版年、刊名與 DOI。打開原文、核對段落後，把支持的說法和頁節寫進 `references.json`，再執行 `build`。候選書目與已讀文獻分開存放。

`evidence.csv` 將同一段落的每項來源各列一行。`run.json` 保存本次使用的材料摘要、輸入檔雜湊值及執行模式。規則可以找出未登錄的識別碼、部分數字差異、較強的因果措辭，以及兩組配對資料中的方向反轉。讀者查得到來源之後，還需要判斷那段原文究竟支持主張到什麼程度。

## 換投稿版型

內建為通用 A4 學術草稿，邊界 2.5 公分。針對特定期刊投稿，可先複製 `papertrail/article.tex`，再把六個插入位置放進刊方提供的 XeLaTeX 版型。各標記應出現一次。

`@@TITLE@@`、`@@BYLINE@@`、`@@ABSTRACT@@`、`@@KEYWORDS@@`、`@@BODY@@`、`@@REFERENCES@@`

```sh
python -m papertrail build examples/citation-audit --template my-journal --pdf
```

`my-journal/` 內放 `template.tex` 與刊方的 `.cls`、`.sty`。版頭或校徽等靜態檔案放在 `assets/`。也可把單一 `.tex` 檔直接給 `--template`。版型需支援中文、`graphicx`、`hyperref`、`\section` 與 `\footnote`。參考文獻直接排入正文末尾。版型選項僅套用於 LaTeX 與其 PDF，Word 使用內建可編輯樣式。

## 在 GitHub 執行範例

把專案存入自己的 GitHub 儲存庫後，在預設分支的 **Actions** 頁籤選取「產生論文範例」，按 **Run workflow**。作業會執行測試，接著產生這份教學範例的 Word、PDF、LaTeX、圖表與證據表。完成後可下載 `papertrail-example`。

本機可用 `python -m unittest discover -s tests -v` 執行測試。測試以模擬端點檢查 Ollama 四個角色的交接與 JSON 格式，寫作品質仍取決於實際選用的模型與輸入材料。

## 專案背景

Google Cloud AI Research 的 PaperOrchestra 將實驗日誌、文獻綜整、繪圖和 LaTeX 排版串成多代理流程。稿證為獨立實作，聚焦繁體中文寫作、Word 原生頁下註，以及段落與證據的對應。程式採 MIT 授權。

[PaperOrchestra 原始專案](https://github.com/google-research/paper-orchestra) · [專案介紹貼文](docs/introduction-zh-TW.md) · [Crossref API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) · [Ollama API](https://docs.ollama.com/api/chat) · [MIT 授權](LICENSE)
