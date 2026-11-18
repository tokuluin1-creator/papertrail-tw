"""Offline, non-mutating manuscript triage. Findings are prompts, not certification."""
import csv
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .materials import load_project

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
        doc = Document(path)
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


def review(manuscript, input_dir, out, protocol=None, claims=None):
    """Produce a fresh review folder; never rewrite manuscript or claim verification."""
    manuscript = Path(manuscript).resolve()
    project = load_project(input_dir)
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
    findings, links, seen = [], [], set()

    def add(severity, location, issue, action):
        findings.append({"id": f"F{len(findings)+1:03}", "severity": severity,
                         "location": location, "issue": issue, "action": action,
                         "decision": "待作者判斷"})

    for key, question in CHECKS.items():
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
            if not isinstance(link, dict) or link.get("id") not in project.sources:
                raise ValueError("主張引用未知來源")
            source = project.sources[link["id"]]
            if source.kind == "question":
                raise ValueError("研究問題 Q 不能當作主張的事實證據")
            relation = link.get("relation")
            if relation not in RELATIONS:
                raise ValueError("來源 relation 須為 supports/contradicts/context/uncertain")
            locator = link.get("locator", "")
            if not isinstance(locator, str):
                raise ValueError("來源 locator 須為文字")
            if not locator.strip():
                add("需處理", claim["id"], "來源缺少主張層級定位", "填寫原文頁、節、段或資料列，不用DOI存在代替支持判斷。")
            # Relations and status are author assertions, never semantic validation.
            links.append([claim["id"], claim["manuscript_locator"], claim["statement"],
                          source.id, locator, relation, source.reading_status,
                          "作者登記；支持關係待人工核對"])
        if sources and not any(s["relation"] == "supports" for s in sources):
            add("需處理", claim["id"], "沒有登記直接支持關係", "背景或反對來源不能自動算支持；若為作者推論，另說明推導與限制。")
    for line_no, line in enumerate(text.splitlines(), 1):
        if re.search(r"導致|造成|證明|必然|causes?|proves?", line, re.I):
            add("人工覆核", f"抽取文字第{line_no}行", "偵測到因果或強斷言用語（也可能是否定、引文或假設）", "逐句判讀設計、反例與保留語；本工具不自動改寫、不判定因果成立。")
    for marker in re.findall(r"\[@([^\]]+)\]", text):
        if marker not in project.sources:
            add("需處理", "引註 " + marker, "稿件標記不在材料來源表", "核對識別碼及原始文獻。")
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".review-", dir=parent))
    try:
        report = {"mode": "review-only-offline", "coverage": coverage,
                  "input_sha256": hashes, "material_sha256": project.hashes,
                  "protocol": procedure, "findings": findings,
                  "limitations": ["未上網查核或呼叫模型", "不是國際同行評審認證或錄用預測", "未改稿；未掃描所有敏感資訊；分享前需人工檢查"]}
        (staging / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md = ["# 稿件審查｜不改稿", "", coverage, "", "本報告是離線規則初篩與人工核對清單，不是同行評審或接受保證。已有材料不等於通過；未提供材料不等於稿件缺失。", ""]
        for f in findings:
            md.extend([f"## {f['id']}｜{f['severity']}｜{f['location']}", f["issue"], f["action"], "決策：待作者判斷。", ""])
        (staging / "review.md").write_text("\n".join(md), encoding="utf-8")
        with (staging / "claim-evidence.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["主張ID", "稿件定位", "主張", "來源ID", "原文定位", "支持關係", "核讀狀態", "查核界線"])
            writer.writerows([_cell(v) for v in row] for row in links)
        for key, path in inputs.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[key]:
                raise ValueError("輸入在審查期間變動，未發布本次報告")
        if load_project(input_dir).hashes != project.hashes:
            raise ValueError("研究材料在審查期間變動，未發布本次報告")
        final = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-review-" + uuid.uuid4().hex[:8])
        staging.rename(final)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging)
