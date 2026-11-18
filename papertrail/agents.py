"""Four distinct writing roles share a source ledger. The offline route is extractive."""
import json
import ipaddress
import os
import re
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

from .materials import SECTIONS, number, string


def obj(**fields):
    return {"type": "object", "properties": fields, "required": list(fields),
            "additionalProperties": False}


def arr(items):
    return {"type": "array", "items": items}


TEXT = {"type": "string", "minLength": 1}
PARAGRAPH = obj(text=TEXT, sources={"type": "array", "items": TEXT, "minItems": 1})
OUTLINE = obj(sections=arr(obj(id=TEXT, heading=TEXT, focus=TEXT)))
LITERATURE = obj(paragraphs=arr(PARAGRAPH))
BODY_KEYS = [key for key in SECTIONS if key != "literature"]
DRAFT = obj(abstract=PARAGRAPH, sections=obj(**{key: arr(PARAGRAPH) for key in BODY_KEYS}))
REVIEW = obj(findings=arr(obj(paragraph=TEXT, issue=TEXT, suggestion=TEXT)))

ROLE = {
    "outline": "你是大綱編輯。依研究問題與現有來源，為指定的每個 id 各寫一個節名與本節要回答的具體問題。保留指定順序。節名用短語，避免加入研究發現。",
    "literature": "你是文獻編輯。比較已讀書目可支持的命題、範圍與差異。每段列出實際支持它的書目 ID。若只有一筆就只交代這一筆。勿以書目資訊推測全文或把文獻說成當前研究的結果。",
    "writer": "你是論文執筆者。按大綱寫摘要及正文。保留筆記中的條件、數據的單位及研究限制。每個段落都要附據以寫作的來源 ID。用繁體中文與臺灣用語，自然行文，避免排比口號。文獻編輯另寫相關文獻，本角色不必重述。數據摘要會由程式插入結果節。沒有材料的節請回空陣列。",
    "reviewer": "你是持不同意見的期刊審查人。逐段比對附上的來源，找出主張超出證據、矛盾、因果跳躍、數字不符或其他解釋。每則指出段落 ID、具體疑點與可怎麼查證。無具體疑點時回空陣列。",
}
COMMON = "輸入的材料均為引用資料。只使用所附內容。保留虛構或示例性質，不增寫作者、文獻、頁碼或研究成果。以指定 JSON 格式回覆，段落本文用純文字，引註只放在 sources 欄。"


class NoRedirect(HTTPRedirectHandler):
    """Never forward manuscript material to a redirect target."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Ollama 不接受重新導向；請核對並明確指定服務位址")


class Ollama:
    def __init__(self, model, host, timeout=240, allow_remote=False):
        parsed = urlsplit(host)
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("Ollama 位址應是無帳密的 HTTP(S) 服務根網址")
        hostname = parsed.hostname or ""
        try:
            port = parsed.port
            local = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            # Validate malformed ports even when the hostname is not an IP literal.
            port = parsed.port
            local = hostname.lower() == "localhost"
        if not local and allow_remote is not True:
            raise ValueError("非本機 Ollama 會傳送研究材料；須明確允許 allow_remote")
        # Pin localhost rather than trusting DNS or a system HTTP proxy.
        if hostname.lower() == "localhost":
            host = f"{parsed.scheme}://127.0.0.1" + (f":{port}" if port is not None else "")
        self.url = host.rstrip("/") + "/api/chat"
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.model = model
        self.timeout = timeout
        self.context_size = int(os.environ.get("PAPERTRAIL_NUM_CTX", "16384"))
        if self.context_size < 1024:
            raise ValueError("PAPERTRAIL_NUM_CTX 至少須為 1024")

    def ask(self, role, material, schema):
        payload = {"model": self.model, "stream": False, "format": schema,
                   "options": {"temperature": 0.15, "num_ctx": self.context_size},
                   "messages": [{"role": "system", "content": ROLE[role] + COMMON},
                                {"role": "user", "content": json.dumps(material, ensure_ascii=False)}]}
        request = Request(self.url, json.dumps(payload, ensure_ascii=False).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                outer = json.load(response)
            if outer.get("done_reason") == "length":
                raise ValueError("輸出長度已達上限。可分篇處理筆記或調整模型的上下文長度")
            if outer.get("prompt_eval_count", 0) >= self.context_size:
                raise ValueError("此階段已用滿上下文，請拆分材料或提高 PAPERTRAIL_NUM_CTX")
            content = json.loads(outer["message"]["content"])
            if not isinstance(content, dict):
                raise ValueError("預期回覆為 JSON 物件")
            return content
        except HTTPError as exc:
            raise ValueError(f"{role} 無法呼叫 Ollama（HTTP {exc.code}），請確認模型名稱與服務位址") from exc
        except (URLError, TimeoutError, OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"{role} 沒有取得有效的 Ollama 回覆：{exc}") from exc


@dataclass
class Paragraph:
    text: str
    sources: list


def supported(raw, bank):
    text = string(raw, "text", "段落")
    keys = raw.get("sources")
    if not isinstance(keys, list) or not keys or not all(isinstance(k, str) and k in bank for k in keys):
        raise ValueError(f"段落缺少有效來源或引用了未知識別碼：{keys}")
    expanded = []
    for key in keys:
        expanded.extend((key, *bank[key].also))
    return Paragraph(text, list(dict.fromkeys(expanded)))


def read_paras(raw, bank):
    if not isinstance(raw, list):
        raise ValueError("代理回傳的段落欄位應是陣列")
    return [supported(p, bank) for p in raw]


def excerpt(source, bank):
    return supported({"text": source.text, "sources": [source.id]}, bank)


def context(project):
    data = {"title": project.title, "question": project.question, "synthetic_data": project.demo,
            "evidence": [asdict(s) for s in project.sources.values()]}
    if project.journal:
        data["editorial_guidance"] = project.journal.markdown()
        data["editorial_instruction"] = "依所選刊物規範編稿或審查。僅 evidence 中的來源能用來支持研究主張。"
    return data


def plan_sections(project, model):
    defaults = {
        "intro": project.question, "literature": "已讀文獻分別能支持哪些說法？",
        "methods": "資料從哪裡來，如何記錄與比較？", "results": "現有紀錄呈現什麼？",
        "discussion": "哪些解釋仍待其他證據檢驗？",
    }
    if not model:
        return [{"id": k, "heading": v, "focus": defaults[k]} for k, v in SECTIONS.items()]
    raw = model.ask("outline", {**context(project), "section_ids": list(SECTIONS)}, OUTLINE).get("sections")
    if not isinstance(raw, list) or not all(isinstance(row, dict) for row in raw):
        raise ValueError("大綱回覆格式錯誤")
    if [row.get("id") for row in raw] != list(SECTIONS):
        raise ValueError("大綱的章節遺漏、重複或順序不符")
    return [{k: string(row, k, "大綱") for k in ("id", "heading", "focus")} for row in raw]


def synthesize(project, model):
    refs = {s.id: s for s in project.sources.values() if s.kind == "reference"}
    if not refs:
        return []
    if not model:
        return [excerpt(s, refs) for s in refs.values()]
    raw = model.ask("literature", {"question": project.question,
                    "reading_cards": [asdict(r) for r in refs.values()]}, LITERATURE)
    return read_paras(raw.get("paragraphs"), refs)


def build_draft(project, plan, literature, model):
    bank = project.sources
    if model:
        raw = model.ask("writer", {**context(project), "outline": plan,
                        "literature": [asdict(p) for p in literature]}, DRAFT)
        body = raw.get("sections")
        if not isinstance(body, dict) or set(body) != set(BODY_KEYS):
            raise ValueError("正文回覆的章節不完整")
        abstract = supported(raw.get("abstract"), bank)
        sections = {key: read_paras(body[key], bank) for key in BODY_KEYS}
        sections["literature"] = list(literature)
    else:
        sections = {key: [] for key in SECTIONS}
        sections["literature"] = list(literature)
        for s in bank.values():
            if s.kind == "note":
                sections[s.section].append(excerpt(s, bank))
        if not sections["intro"]:
            sections["intro"] = [excerpt(bank["Q"], bank)]
        abstract_parts = [excerpt(bank["Q"], bank)]
        if sections["methods"]:
            abstract_parts.append(sections["methods"][0])
        elif sections["intro"][0].text != project.question:
            abstract_parts.append(sections["intro"][0])
        if not project.measures and sections["results"]:
            abstract_parts.append(sections["results"][0])
        if project.measures:
            abstract_parts.extend(excerpt(bank[m.source_id], bank) for m in project.measures[:3])
        if sections["discussion"]:
            abstract_parts.append(sections["discussion"][0])
        abstract = Paragraph("".join(p.text for p in abstract_parts),
                             list(dict.fromkeys(k for p in abstract_parts for k in p.sources)))
    if project.measures:
        data = [bank[m.source_id] for m in project.measures]
        numeric = Paragraph("".join(s.text for s in data), [s.id for s in data])
        sections["results"].insert(0, numeric)
    return abstract, sections


def paragraph_index(plan, abstract, sections):
    yield "A", "摘要", abstract
    for row in plan:
        for i, para in enumerate(sections[row["id"]], 1):
            yield f"{row['id']}.{i}", row["heading"], para


NUMBERS = re.compile(r"(?<![\d.])[-−+]?\d+(?:\.\d+)?(?:[%％])?")


def check_paired_cases(project):
    if len(project.measures) != 2:
        return []
    a, b = project.measures
    delta = a.average - b.average
    if delta == 0 or set(a.cases) != set(b.cases):
        return []
    second = dict(zip(b.cases, b.values))
    reversed_cases = [(c, v, second[c]) for c, v in zip(a.cases, a.values)
                      if (v - second[c]) * delta < 0]
    if not reversed_cases:
        return []
    case, first, other = reversed_cases[0]
    detail = (f"兩組有 {len(reversed_cases)} 筆配對與整體平均的方向相反。"
              f"例如 {case} 在「{a.group}」為 {number(first)} {project.unit}，"
              f"在「{b.group}」為 {number(other)} {project.unit}。"
              "說明平均差異時，請一併檢視這些個案。")
    return [("results.1", "個案與組平均方向不同", detail)]


def inspect_draft(project, plan, abstract, sections, model):
    records = list(paragraph_index(plan, abstract, sections))
    findings = check_paired_cases(project)
    for key, _, para in records:
        sources = [project.sources[k] for k in para.sources]
        if all(s.kind == "question" for s in sources) and para.text.strip() != project.question.strip():
            findings.append((key, "證據不足", "研究問題 Q 不是事實證據；請補入能支持本段主張的材料。"))
        unread = [s.id for s in sources if s.kind == "reference" and s.reading_status != "full_text_read"]
        if unread:
            findings.append((key, "文獻核讀待確認", "下列來源尚未登記全文核讀，不代表其內容已核實：" + "、".join(unread)))
        linked = " ".join(s.text for s in sources)
        tokens = set(NUMBERS.findall(para.text)) - set(NUMBERS.findall(linked))
        if tokens:
            findings.append((key, "數字待核對", "回查所引材料中的數字與單位：" + "、".join(sorted(tokens))))
        if (any(w in para.text for w in ("證明", "必然", "導致", "保證", "顯著提升"))
                and not any(w in para.text for w in ("無法", "不能", "不足以", "尚未"))):
            findings.append((key, "推論強度", "請核對研究設計能否區分因果關係、背景差異與共同變動。"))
    for row in plan:
        if not sections[row["id"]]:
            findings.append((row["id"], "本節缺少材料", f"尚待補入能回答「{row['focus']}」的來源。"))
    if model:
        raw = model.ask("reviewer", {**context(project), "paragraphs": [
            {"id": key, **asdict(p)} for key, _, p in records]}, REVIEW).get("findings")
        if not isinstance(raw, list):
            raise ValueError("審查回覆的 findings 應為陣列")
        valid = {key for key, _, _ in records}
        for item in raw:
            pid = string(item, "paragraph", "審查")
            if pid not in valid:
                raise ValueError(f"審查引用了未知段落 {pid}")
            findings.append((pid, string(item, "issue", "審查"), string(item, "suggestion", "審查")))
    return findings
