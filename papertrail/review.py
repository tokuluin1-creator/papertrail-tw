"""Offline, non-mutating manuscript triage. Findings are prompts, not certification."""
import csv
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .materials import load_project
from .privacy import scan_anonymity
from .review_report import render_html

# Original checklist: applicability depends on design, not a universal journal score.
CHECKS = {
    "contribution": "研究問題、理論貢獻及相較既有文獻的增量為何？",
    "search_strategy": "記錄資料庫、完整檢索式、日期、語言與時間範圍；敘事回顧也須交代選材。",
    "selection": "納排條件、篩選者與排除理由是否可回查？目的性選材不冒稱系統性回顧。",
    "source_criticism": "區分政策主張、宣傳、學術研究與獨立觀察；檢視來源立場與取得限制。",
    "synthesis": "比較理論、概念、方法、證據及分歧，避免逐篇摘要代替綜合。",
    "counterevidence": "納入反例、競爭解釋與不支持假設的文獻，並說明如何處理。",
    "scope": "界定案例、時空、分析層級與外推界線；相關不直接等於因果。",
    "ethics": "確認倫理、利益衝突、AI使用、版權與敏感資料處理要求。",
    "journal_fit": "逐項核對目標期刊當期規範、匿名、摘要、引註、篇幅及投稿聲明。",
}
RELATIONS = {"supports", "contradicts", "context", "uncertain"}


def _text(path):
    if path.suffix.lower() in {".md", ".txt"}:
        return path.read_text(encoding="utf-8-sig"), "UTF-8全文；行號定位"
    if path.suffix.lower() == ".docx":
        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError
        from zipfile import BadZipFile
        from lxml.etree import XMLSyntaxError
        try:
            doc = Document(path)
        except (PackageNotFoundError, BadZipFile, XMLSyntaxError, KeyError) as exc:
            raise ValueError("無法讀取 DOCX，請確認是有效且未加密的 Word 檔") from exc
        parts = [p.text for p in doc.paragraphs]
        parts.extend(" | ".join(c.text for c in row.cells) for t in doc.tables for row in t.rows)
        return "\n".join(parts), "DOCX正文段落及表格文字；不是原頁碼，未覆蓋註腳、修訂標記、圖像與文字方塊"
    raise ValueError("審查稿件僅接受 .md、.txt 或 .docx")


def _object_file(path, default):
    if path is None:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _cell(value):
    # Keep exported ledgers inert when opened in spreadsheet software.
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def review(manuscript, input_dir, out, protocol=None, claims=None, journal=None):
    """Produce a fresh review folder; never rewrite manuscript or claim verification."""
    manuscript = Path(manuscript).resolve()
    project = load_project(input_dir, journal)
    parent = Path(out).resolve()
    if parent == project.root or parent.is_relative_to(project.root):
        raise ValueError("審查輸出請設在研究材料目錄之外")
    if manuscript.is_relative_to(parent):
        raise ValueError("審查輸出不可包含原稿位置")
    inputs = {"manuscript": manuscript, "project": project.root / "project.json"}
    for key, path in (("protocol", protocol), ("claims", claims)):
        if path is not None:
            inputs[key] = Path(path).resolve()
    hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in inputs.items()}
    text, coverage = _text(manuscript)
    if not text.strip():
        raise ValueError("稿件沒有可抽取的文字")
    procedure = _object_file(protocol, {})
    if not isinstance(procedure, dict) or any(k not in CHECKS for k in procedure):
        raise ValueError("protocol 須為已定義審查項目的物件；見 docs/review-first.md")
    if any(not isinstance(v, str) or not v.strip() for v in procedure.values()):
        raise ValueError("protocol 每一項須為非空文字；不適用請寫明理由")
    ledger = _object_file(claims, [])
    if not isinstance(ledger, list):
        raise ValueError("claims 須為陣列")
    findings, links, seen, claim_checks = [], [], set(), []

    def add(severity, location, issue, action):
        findings.append({"id": f"F{len(findings)+1:03}", "severity": severity,
                         "location": location, "issue": issue, "action": action,
                         "decision": "待作者判斷"})

    for flag in scan_anonymity(manuscript, text):
        add("匿名風險", flag["location"], flag["issue"], flag["action"])

    for key, question in CHECKS.items():
        if key == "journal_fit" and project.journal:
            question = f"請依《{project.journal.name}》所附投稿規範逐項比對，並記錄稿件位置與符合情形。"
            if key not in procedure:
                add("人工覆核", "protocol / journal_fit", "已載入刊方規範，待核對實際稿件", question)
                continue
        if key not in procedure:
            add("待補資料", "protocol / " + key, "未提供審查依據，不等於稿件必然缺失", question)
        else:
            add("人工覆核", "protocol / " + key, "已有作者陳述，尚未獨立核實", question)
    if not ledger:
        add("待補資料", "claims", "未提供主張—來源表", "逐項登記重要主張、稿件位置、來源與支持關係；未列入的主張不在本次逐項核對範圍。")
    for claim in ledger:
        if not isinstance(claim, dict):
            raise ValueError("claims 每筆須為物件")
        for key in ("id", "statement", "manuscript_locator"):
            if not isinstance(claim.get(key), str) or not claim[key].strip():
                raise ValueError(f"claim 缺少 {key}")
        if claim["id"] in seen:
            raise ValueError("主張 ID 重複：" + claim["id"])
        seen.add(claim["id"])
        sources = claim.get("sources")
        if not isinstance(sources, list):
            raise ValueError("claim sources 須為陣列")
        if claim["statement"] not in text:
            add("需處理", claim["id"], "主張文字未在抽取稿件中精確找到", "核對版本與定位，可能涉及換行或DOCX抽取限制；不可當作虛構證據定論。")
        if not sources:
            add("需處理", claim["id"], "主張尚未連到來源", "補來源或限制主張；不得補造文獻。")
        for link in sources:
            if not isinstance(link, dict) or not isinstance(link.get("id"), str) or link["id"] not in project.sources:
                raise ValueError("主張引用未知來源")
            source = project.sources[link["id"]]
            if source.kind == "question":
                raise ValueError("研究問題 Q 不能當作主張的事實證據")
            relation = link.get("relation")
            if not isinstance(relation, str) or relation not in RELATIONS:
                raise ValueError("來源 relation 須為 supports/contradicts/context/uncertain")
            locator = link.get("locator", "")
            if not isinstance(locator, str):
                raise ValueError("來源 locator 須為文字")
            if not locator.strip():
                add("需處理", claim["id"], "來源缺少主張層級定位", "填寫原文頁、節、段或資料列，不用DOI存在代替支持判斷。")
            if source.kind == "reference" and source.reading_status != "full_text_read":
                add("人工覆核", claim["id"] + " / " + source.id, "來源尚未登記全文核讀", "先核原文與主張定位；已有書目或節錄不等於已驗證支持關係。")
            # Relations and status are author assertions, never semantic validation.
            links.append([claim["id"], claim["manuscript_locator"], claim["statement"],
                          source.id, locator, relation, source.reading_status,
                          "作者登記；支持關係待人工核對"])
        if sources and not any(s["relation"] == "supports" for s in sources):
            add("需處理", claim["id"], "沒有登記直接支持關係", "背景或反對來源不能自動算支持；若為作者推論，另說明推導與限制。")
        claim_checks.append({"id": claim["id"], "location": claim["manuscript_locator"],
                             "exact_text_found": claim["statement"] in text,
                             "source_ids": sorted({s["id"] for s in sources}),
                             "relations": dict(Counter(s["relation"] for s in sources))})
    for line_no, line in enumerate(text.splitlines(), 1):
        if re.search(r"導致|造成|證明|必然|causes?|proves?", line, re.I):
            add("人工覆核", f"抽取文字第{line_no}行", "偵測到因果或強斷言用語（也可能是否定、引文或假設）", "逐句判讀設計、反例與保留語；本工具不自動改寫、不判定因果成立。")
    markers = Counter(re.findall(r"\[@([^\]]+)\]", text))
    for marker in markers:
        if marker not in project.sources:
            add("需處理", "引註 " + marker, "稿件標記不在材料來源表", "核對識別碼及原始文獻。")
    sources = [{"id": s.id, "reading_status": s.reading_status,
                "claim_count": len({row[0] for row in links if row[3] == s.id}),
                "marker_count": markers[s.id]}
               for s in project.sources.values() if s.kind == "reference"]
    counts = Counter(f["severity"] for f in findings)
    summary = {"action_required": counts["需處理"], "missing_information": counts["待補資料"],
               "human_review": counts["人工覆核"], "anonymity_flags": counts["匿名風險"],
               "claims_registered": len(ledger), "source_links": len(links),
               "unknown_markers": sum(marker not in project.sources for marker in markers)}
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".review-", dir=parent))
    try:
        report = {"mode": "review-only-offline", "coverage": coverage,
                  "schema_version": 2, "summary": summary, "sources": sources, "claim_checks": claim_checks,
                  "input_sha256": hashes, "material_sha256": project.hashes,
                  "protocol": procedure, "findings": findings,
                  "limitations": ["未上網查核或呼叫模型", "不是國際同行評審認證或錄用預測", "匿名風險僅規則提示，不保證匿名；未改稿或刪除中繼資料", "DOCX匿名檢查與正文抽取的涵蓋範圍不同；圖片、檔名與間接身分線索仍須人工核對", "未掃描所有敏感資訊；報告及證據CSV分享前需人工檢查"]}
        if project.journal:
            report["journal"] = project.journal.record()
            (staging / "journal.md").write_text(project.journal.markdown(), encoding="utf-8", newline="\n")
        (staging / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md = ["# 稿件審查｜不改稿", "", coverage, "", "本報告是離線規則初篩與人工核對清單，不是同行評審或接受保證。已有材料不等於通過；未提供材料不等於稿件缺失。", ""]
        if project.journal:
            md.extend([f"投稿目標為《{project.journal.name}》。[核對本次投稿規範與出處](journal.md)", ""])
        md.extend(["## 本次摘要", f"需處理 {summary['action_required']}；待補資料 {summary['missing_information']}；人工覆核 {summary['human_review']}；匿名風險 {summary['anonymity_flags']}。", "這些數量不是品質分數。零提示不表示匿名或可投稿。", "先核風險及需處理項目，再填 decisions.csv；未自動採納任何修改。", "", "## 文獻核讀與連結", "| 來源ID | 核讀狀態（作者登記） | 連結主張數 | 稿內標記數 |", "| --- | --- | --- | --- |"])
        md.extend(f"| {s['id']} | {s['reading_status']} | {s['claim_count']} | {s['marker_count']} |" for s in sources)
        md.append("")
        for f in findings:
            md.extend([f"## {f['id']}｜{f['severity']}｜{f['location']}", f["issue"], f["action"], "決策：待作者判斷。", ""])
        (staging / "review.md").write_text("\n".join(md), encoding="utf-8")
        (staging / "review.html").write_text(render_html(report, sources), encoding="utf-8")
        with (staging / "decisions.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["finding_id", "決策（接受/部分接受/不接受/待查）", "理由", "補充證據", "修訂版本與位置"])
            writer.writerows([[finding["id"], "待查", "", "", ""] for finding in findings])
        with (staging / "claim-evidence.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["主張ID", "稿件定位", "主張", "來源ID", "原文定位", "支持關係", "核讀狀態", "查核界線"])
            writer.writerows([_cell(v) for v in row] for row in links)
        for key, path in inputs.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
                raise ValueError("輸入在審查期間變動，未發布本次報告")
        if load_project(input_dir, journal).hashes != project.hashes:
            raise ValueError("研究材料在審查期間變動，未發布本次報告")
        final = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-review-" + uuid.uuid4().hex[:8])
        staging.rename(final)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging)
