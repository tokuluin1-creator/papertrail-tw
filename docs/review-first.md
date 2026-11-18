# 先審查，再由作者決定是否改稿

`review` 與 `build` 是不同操作：前者讀取既有稿件，輸出疑點與查核表；後者明確產生新草稿。審查不呼叫模型、不聯網、不寫回原稿、不自動接受修改。沒有發現問題不等於通過同行評審，也不保證刊登。

```sh
python -m papertrail review my-manuscript.docx --project my-research --out reviews
python -m papertrail review my-manuscript.md --project my-research \
  --protocol my-research/review-protocol.json \
  --claims my-research/claims.json --out reviews
```

輸出須在材料目錄之外，也不能包含原稿位置。每次建立新目錄，包含 `review.md`、機器可讀的 `review.json` 與 `claim-evidence.csv`。輸入雜湊記錄此次版本；`review.json` 的 `material_sha256` 對應材料。原稿不需要改成工具的格式。

現在也產生可離線直接開啟的 **`review.html`**，優先顯示匿名風險、需處理事項、核讀狀態及登記主張的來源關係。沒有外部腳本、字型或追蹤。數量不是品質分數，也不估計全稿查核覆蓋率；同一來源重複被引只計一個來源ID，不保證不同ID就是獨立證據。`decisions.csv` 為待作者填寫的決策表，不會自動採納或回寫修改。

## 投稿匿名風險初篩

每次 `review` 會標記可抽取正文中的 email、部分電話格式及明確作者欄位用語。DOCX另檢查作者／最後修改者中繼資料、批註檔存在及常見追蹤修訂XML標記。風險提示不重印匹配的個人資料，只列類別及位置；不會刪除任何資料或產生「匿名版」。

**零提示不代表匿名通過。** 引用、機構自述、致謝、檔名、圖片、頁首頁尾、註腳、資助資訊與間接身分線索仍需人工核對。電話規則可能誤報；公開聯絡資料及引用中的作者標籤也可能不屬於投稿身分洩漏，須依刊方匿名要求判斷。批註／修訂標記存在只代表需檢查，不代表內容一定洩漏身分。損壞或超過掃描限制的XML會記錄「未完成」，不冒充無風險。

審查報告不是匿名投稿附件：主張表、protocol、來源ID或定位若含個資，仍可能出現在報告或CSV。請先人工去識別，再決定是否分享。

## 文獻研究程序

`review-protocol.json` 是物件，以下欄位的值均為非空文字；不適用請附理由，不能只填 `true`。資料缺漏列為「待補資料」，有陳述仍是「人工覆核」，不把勾選當成完成。

| 欄位 | 應留下的依據 |
| --- | --- |
| contribution | 研究問題、概念界定、理論或經驗貢獻及相較既有研究的增量 |
| search_strategy | 資料庫、完整檢索式、檢索日、時間、語言與取得範圍 |
| selection | 納排理由、篩選方式與紀錄；目的性取樣不冒稱完整母體 |
| source_criticism | 來源立場、獨立性、品質、可取得程度與官方敘事偏差 |
| synthesis | 理論、方法、發現與證據比較，不能只逐篇摘要 |
| counterevidence | 反例、競爭解釋及相反結果的處理 |
| scope | 時空與案例範圍、分析層級、因果與外推限制 |
| ethics | 倫理、利益衝突、個資、版權、AI使用揭露與資料可得性 |
| journal_fit | 目標期刊當期規範及查核日期、匿名與投稿聲明 |

這是社會科學投稿前的透明性清單，不是所有國際期刊的統一規範。敘事、範疇、系統性回顧、文件分析與個案研究須依設計分別說明；需要採用特定報告準則時，由作者查閱原規範並說明適用範圍。

## 主張與證據分開

`claims.json` 例子（來源ID必須存在於自己的材料表；文字與位置由作者提供）：

```json
[
  {
    "id": "C1",
    "statement": "這裡填原稿中需要審查的一句話。",
    "manuscript_locator": "第二節第三段",
    "sources": [
      {"id": "R-example", "locator": "第12頁第二段", "relation": "supports"}
    ]
  }
]
```

`relation` 為 `supports`、`contradicts`、`context` 或 `uncertain`，全部是作者登記，不是工具認證。文獻卡有DOI、題名或摘要，不代表讀過全文；原文定位與支持強度需逐條覆核。研究問題 `Q` 只能構成研究背景，不能作為事實主張證據。反對、背景與不確定來源不自動計為支持。沒有列入表中的主張也不算已核。

`references.json` 可新增 `reading_status`：`unverified`（預設）、`metadata_only`、`excerpt_read`、`full_text_read`。既有文獻卡保持相容，未填者不推定已讀全文。即使填 `full_text_read` 也只是作者登記，不等於工具已下載原文或驗證支持關係。

審查分四輪由人完成：問題與論證結構、來源及外推界線、學術語言與臺灣用語、投稿文件一致性。語言調整應保護術語、原始題名、引文、數字與保留語，不將學術文章自動口語化。工具目前只標記部分因果詞，**不宣稱完整語言審校或語意判讀**。

作者可另存修訂決策表：`finding_id、接受/部分接受/不接受/待查、理由、補充證據、修訂版位置`。確認後自行改稿並再次審查；本命令不提供自動改寫或接受全部意見的捷徑。

## 已知限制與隱私

- Markdown與文字檔以抽取行號定位；DOCX只抽取正文段落與表格，不保持頁碼或原順序，亦未完整抽取註腳、追蹤修訂、文字方塊及圖片，須另核原稿。
- 精確字串找不到可能來自換行或抽取差異，不自動判為不存在的主張。
- 工具不下載全文、不查撤稿、不評估研究品質分數，不判定相關性、因果性或研究發現真假。
- 報告可能包含稿件主張、檔案定位與方法資訊。只在受信任的本機使用；不得直接把私人稿件、訪談、收款資訊、API金鑰或產出報告提交公開repo。這不是自動匿名化工具。
- `build --model` 仍會向選用Ollama傳送材料。非loopback端點需要另加 `--allow-remote` 明示許可；許可不代表端點安全，傳送前自行去識別與查核資料權限。

## 概念參考與授權界線

本次新增程式與文字為獨立實作，未搬入下列倉庫的程式或提示詞，未執行其安裝腳本。授權紀錄以2026-11-18檢視為準；後續若引入原始內容必須重新檢查授權與署名義務。

| 專案 | 查得授權 | 僅參考的概念 |
| --- | --- | --- |
| [WenyuChiou/academic-writing-skills](https://github.com/WenyuChiou/academic-writing-skills) | MIT | 分階段審查與作者決策 |
| [binary-husky/gpt_academic](https://github.com/binary-husky/gpt_academic) | GPL-3.0 | 長文件處理與原文對照；不嵌入其程式 |
| [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills) | CC BY-NC 4.0 | 來源定位、競爭解釋與修訂追蹤；不納入提示詞 |
| [Raymondhou0917/speak-human-tw](https://github.com/Raymondhou0917/speak-human-tw) | MIT | 臺灣用語檢視與事實保護；不採自動改寫 |

MIT是本專案獨立程式的授權，不代表以上所有參考倉庫都採MIT，也不代表國際審查認證。
