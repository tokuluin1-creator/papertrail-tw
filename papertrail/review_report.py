"""Self-contained, escaped HTML; no scripts, remote fonts, or telemetry."""
from html import escape


STATUS = {"unverified": "未核讀", "metadata_only": "僅書目", "excerpt_read": "已讀節錄", "full_text_read": "登記已讀全文"}


def render_html(report, sources):
    def h(value):
        return escape(str(value), quote=True)

    counts = report["summary"]
    parts = ['<!doctype html><html lang="zh-Hant"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<title>稿件審查｜不改稿</title><style>',
             'body{max-width:1000px;margin:auto;padding:24px;font:17px/1.7 system-ui,sans-serif;color:#163247;background:#f5f7fa}h1,h2{line-height:1.3}.notice,article{background:white;padding:20px;border-radius:10px;margin:16px 0;border:1px solid #cbd5df}.metrics{display:flex;flex-wrap:wrap;gap:12px}.metrics span{padding:12px;background:#e3edf6;border-radius:8px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;text-align:left;border:1px solid #ccd5dd;vertical-align:top;overflow-wrap:anywhere}p{overflow-wrap:anywhere}.scroll{overflow:auto}summary{cursor:pointer;font-weight:600}.small{font-size:14px;color:#496173}@media print{body{background:white;padding:0}details>div{display:block}article{break-inside:avoid}}',
             '</style><body><h1>稿件審查｜不改稿</h1>',
             '<p class="notice">離線規則初篩，不是匿名化認證、同行評審或錄用預測。零風險提示不表示沒有風險。原稿未修改。</p>',
             '<div class="metrics">']
    for label, key in [("需處理", "action_required"), ("待補資料", "missing_information"), ("人工覆核", "human_review"), ("匿名風險提示", "anonymity_flags"), ("已登記主張", "claims_registered")]:
        parts.append(f'<span>{label}：<strong>{counts[key]}</strong></span>')
    parts.extend(['</div><h2>先做什麼</h2><ol><li>先人工核對匿名風險及「需處理」項目。</li><li>回查來源原文，再記錄接受、部分接受、不接受或待查的決策。</li><li>確認後自行修改另一版本；原稿及本次雜湊保留。</li></ol>',
                  '<h2>引註與證據狀態</h2><p>核讀狀態由作者登記；不是來源真實性或支持關係認證。只核對工具格式的 [@ID] 與主張表，不完整解析一般註腳或作者年份引註。</p>',
                  '<div class="scroll"><table><thead><tr><th>來源ID</th><th>核讀狀態</th><th>連結主張數</th><th>稿內標記數</th></tr></thead><tbody>'])
    for s in sources:
        parts.append(f'<tr><td>{h(s["id"])}</td><td>{h(STATUS.get(s["reading_status"],s["reading_status"]))}</td><td>{s["claim_count"]}</td><td>{s["marker_count"]}</td></tr>')
    if not sources:
        parts.append('<tr><td colspan="4">本次沒有可列示的文獻卡。</td></tr>')
    parts.append('</tbody></table></div><h2>登記主張狀態</h2><p>只涵蓋主張表，不推定全稿已核。來源數為不同ID數量，不保證彼此獨立。支持關係由作者登記，並非語意驗證。</p>')
    relation_names = {"supports": "支持", "contradicts": "反對", "context": "背景", "uncertain": "不確定"}
    for claim in report.get("claim_checks", []):
        relationships = '、'.join(f'{relation_names[k]} {n}' for k,n in claim['relations'].items()) or '未連結來源'
        parts.append('<article><h3>' + h(claim['id']) + '</h3><p>' + h(claim['location']) + '</p><p>原句精確比對：' + ('找到（不等於支持成立）' if claim['exact_text_found'] else '未找到（請核版本／抽取限制）') + '</p><p>不同來源ID：' + str(len(claim['source_ids'])) + '</p><p>作者登記關係：' + h(relationships) + '</p></article>')
    if not report.get('claim_checks'):
        parts.append('<p class="notice">尚未登記主張，不能推定查核覆蓋率。</p>')
    parts.append('<h2>審查項目</h2>')
    priority = {"匿名風險": 0, "需處理": 1, "待補資料": 2, "人工覆核": 3}
    for finding in sorted(report["findings"], key=lambda f: priority.get(f["severity"], 4)):
        parts.append(f'<article><h3>{h(finding["id"])} · {h(finding["severity"])}</h3><p class="small">{h(finding["location"])}</p><p>{h(finding["issue"])}</p><p>{h(finding["action"])}</p><p class="small">決策：待作者判斷，請另填 decisions.csv。</p></article>')
    parts.append('<h2>範圍與版本</h2><p>' + h(report['coverage']) + '</p><ul>')
    parts.extend('<li>' + h(v) + '</li>' for v in report['limitations'])
    parts.append('</ul><details><summary>本次輸入 SHA256</summary><div>')
    parts.extend('<p>' + h(k) + ': <code>' + h(v) + '</code></p>' for k,v in report['input_sha256'].items())
    parts.append('</div></details><p class="notice">此報告與CSV可能包含私人研究資訊。請勿未經檢查便分享或上傳公開儲存庫。</p></body></html>')
    return ''.join(parts)
