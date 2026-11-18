"""Read-only anonymity-risk triage, never anonymization or a privacy guarantee.

Text checks cover only the caller's extracted text. DOCX checks additionally
inspect core identity properties, comment parts, and revision XML markers.
Matched personal values are deliberately omitted from returned findings.
"""
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

_EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# Restrict unlabelled numbers to recognizable mobile/international forms. A
# bare year, DOI, page range or ten-digit identifier is not evidence of identity.
_MOBILE = re.compile(r"(?<!\d)09\d{2}[ -]?\d{3}[ -]?\d{3}(?!\d)")
_INTERNATIONAL = re.compile(r"(?<!\w)\+\d{1,3}[ -]?(?:\(\d{1,4}\)[ -]?)?(?:\d[ -]?){6,13}\d(?!\d)")
_PHONE_LABEL = re.compile(r"(?:電話|手機|聯絡電話|联系电话|电话|手机|telephone|phone|tel\.?|mobile)\s*[:：]?\s*(?:\+?\d|\(\d)", re.I)
_IDENTITY = re.compile(
    r"(?:^|[;；|])\s*(?:作者|通訊作者|通讯作者|姓名|服務單位|服务单位|作者單位|作者单位|"
    r"author(?:s)?|corresponding author|affiliation(?:s)?)\s*[:：]\s*\S|作者簡介|作者简介", re.I
)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CORE_FIELDS = {
    "{http://purl.org/dc/elements/1.1/}creator": "作者中繼資料",
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy": "最後修改者中繼資料",
}
_MAX_XML_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024


def scan_anonymity(path, text):
    """Return location/issue/action risk hints without exposing matching values.

    Does not edit files, resolve external relationships, invoke a model, or use
    the network. Absence of findings never means a manuscript is anonymous.
    """
    findings = []

    def add(location, issue, action):
        findings.append({"location": location, "issue": issue, "action": action})

    for number, line in enumerate(text.splitlines(), 1):
        location = f"抽取文字第{number}行"
        if _EMAIL.search(line):
            add(location, "電子郵件格式可能透露身分", "確認是否屬作者或受訪者聯絡資訊；引文中的公開資訊須依投稿規範判斷，不自動刪除。")
        if _MOBILE.search(line) or _INTERNATIONAL.search(line) or _PHONE_LABEL.search(line):
            add(location, "電話格式或聯絡電話標籤可能透露身分", "回查原文判斷是否為電話、識別碼或引用內容；必要時由作者製作去識別副本。")
        if _IDENTITY.search(line):
            add(location, "作者身分或所屬單位標籤", "檢查作者資料是否應僅置於獨立標題頁；不可直接刪除文獻作者或引文。")
    if Path(path).suffix.lower() != ".docx":
        return findings

    try:
        with ZipFile(path) as archive:
            total = 0
            for item in archive.infolist():
                name = item.filename
                # Do not include filenames supplied inside an untrusted document
                # in the report: those filenames can themselves contain identity.
                if name.startswith("word/comments") and name.endswith(".xml"):
                    add("DOCX 註解區", "存在註解資料，可能保留作者或審閱者資訊", "在副本中人工檢查所有註解與審閱者資料；本工具不移除註解。")
                if name != "docProps/core.xml" and not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                total += item.file_size
                if item.file_size > _MAX_XML_BYTES or total > _MAX_TOTAL_BYTES:
                    add("DOCX 套件", "部分 XML 超過安全掃描大小，匿名檢查未完成", "使用可信任的文書軟體人工檢查中繼資料、註解與追蹤修訂；不得視為已通過。")
                    break
                try:
                    root = ET.fromstring(archive.read(item))
                except ET.ParseError:
                    add("DOCX 套件", "部分 XML 無法解析，匿名檢查未完成", "以原始文件人工檢查；本結果不能排除身分資訊。")
                    continue
                if name == "docProps/core.xml":
                    for node in root.iter():
                        if node.tag in _CORE_FIELDS and (node.text or "").strip():
                            add("DOCX 核心屬性", "存在" + _CORE_FIELDS[node.tag], "在投稿副本中人工檢查及清除可識別的文件屬性；本工具不修改中繼資料。")
                elif any(node.tag.startswith(_W) and (
                        node.tag[len(_W):] in {"ins", "del", "moveFrom", "moveTo", "moveFromRangeStart", "moveToRangeStart"}
                        or node.tag[len(_W):].endswith("PrChange")) for node in root.iter()):
                    add("DOCX 修訂標記", "存在追蹤修訂，可能保留刪除內容或修訂者身分", "由作者在副本中逐項判斷修訂，再檢查修訂者資訊；本工具不自動接受或拒絕修訂。")
    except (BadZipFile, OSError, RuntimeError, NotImplementedError):
        add("DOCX 套件", "無法完整讀取 DOCX，匿名檢查未完成", "使用可信任的文書軟體檢查原稿；不可將無法掃描視為沒有風險。")
    # Multiple OOXML parts can contain the same class of revision or comment.
    return [dict(items) for items in dict.fromkeys(tuple(f.items()) for f in findings)]
