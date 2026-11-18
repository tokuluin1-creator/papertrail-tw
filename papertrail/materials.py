"""Load author materials and compute descriptive values directly from the CSV."""
import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from .journals import Journal, lookup

SECTIONS = {
    "intro": "研究問題", "literature": "相關文獻", "methods": "研究方法",
    "results": "研究結果", "discussion": "討論與限制",
}
HEADINGS = {
    "intro": ("前言", "背景", "研究問題", "動機", "introduction", "background", "question"),
    "literature": ("文獻", "literature", "related work"),
    "methods": ("方法", "設計", "材料", "method", "design", "procedure"),
    "results": ("結果", "觀察", "發現", "result", "finding", "observation"),
    "discussion": ("討論", "限制", "待查", "解釋", "discussion", "limitation"),
}
CITE = re.compile(r"\[@([RVD]-[\w.-]+)\]")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def string(obj, key, where):
    value = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} 缺少文字欄位 {key}")
    return value.strip()


@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    section: str
    text: str
    location: str
    title: str = ""
    citation: str = ""
    bibliography: str = ""
    url: str = ""
    also: tuple = ()
    reading_status: str = "unverified"


@dataclass(frozen=True)
class Measure:
    group: str
    values: tuple
    rows: tuple
    cases: tuple
    source_id: str

    @property
    def average(self):
        return mean(self.values)


@dataclass
class Project:
    root: Path
    title: str
    question: str
    author: str
    keywords: list
    demo: bool
    metric: str
    group_label: str
    unit: str
    sources: dict
    measures: list
    hashes: dict
    journal: Journal | None = None


def number(value):
    return format(value, ".6g") if value else "0"


def section_id(heading):
    for key, names in HEADINGS.items():
        if any(name in heading.casefold() for name in names):
            return key
    return "results"


def note_blocks(path, root, content):
    rel = path.relative_to(root).as_posix()
    section = "results"
    lines = content.splitlines()
    start = 0
    parts = []
    for i, line in enumerate([*lines, ""], 1):
        naked = line.strip()
        heading = re.match(r"^#{1,6}\s+(.+)", naked)
        if naked and not heading:
            if not parts:
                start = i
            parts.append(naked)
            continue
        if parts:
            original = " ".join(parts)
            text = CITE.sub("", original).strip()
            if "[@" in text:
                raise ValueError(f"{rel} 第 {start} 行有未辨識的引註標記")
            if not text:
                raise ValueError(f"{rel} 第 {start} 行只有引註，請補入筆記內容")
            key = "N-" + hashlib.sha256(f"{rel}:{start}".encode()).hexdigest()[:10]
            yield Source(key, "note", section, text, f"{rel} 第 {start}–{i-1} 行",
                         also=tuple(dict.fromkeys(CITE.findall(original))))
            parts.clear()
        if heading:
            section = section_id(heading[1])


def reference_cards(content):
    cards = json.loads(content)
    if not isinstance(cards, list):
        raise ValueError("references.json 應為書目卡陣列")
    for index, card in enumerate(cards, 1):
        place = f"references.json 第 {index} 筆"
        key = string(card, "id", place)
        if not re.fullmatch(r"R-[A-Za-z0-9_.-]+", key):
            raise ValueError(f"{place} 的 id 請使用 R- 開頭的英數識別碼")
        url = card.get("url", "")
        if not isinstance(url, str) or (url and not re.fullmatch(r"https?://[^\s<>]+", url)):
            raise ValueError(f"{place} 的 url 需是完整的 http(s) 網址，紙本可留空")
        status = card.get("reading_status", "unverified")
        if not isinstance(status, str) or status not in {"unverified", "metadata_only", "excerpt_read", "full_text_read"}:
            raise ValueError(f"{place} 的 reading_status 須為 unverified/metadata_only/excerpt_read/full_text_read")
        yield Source(key, "reference", "literature", string(card, "reading_note", place),
                     string(card, "locator", place), string(card, "title", place),
                     string(card, "note_citation", place), string(card, "bibliography", place), url, reading_status=status)


def measurement_groups(content, metric, unit):
    records = []
    groups = {}
    seen = set()
    with io.StringIO(content, newline="") as f:
        reader = csv.DictReader(f)
        if not {"case", "group", "value"} <= set(reader.fieldnames or []):
            raise ValueError("measurements.csv 需要 case、group、value 三欄")
        for row in reader:
            line = reader.line_num
            group = string(row, "group", f"CSV 第 {line} 行")
            case = string(row, "case", f"CSV 第 {line} 行")
            if (case, group) in seen:
                raise ValueError(f"CSV 第 {line} 行的 case 及 group 重複")
            try:
                value = float(row["value"])
                if not math.isfinite(value):
                    raise ValueError
            except (TypeError, ValueError):
                raise ValueError(f"CSV 第 {line} 行的 value 應為有限數值") from None
            if "id" in row:
                key = string(row, "id", f"CSV 第 {line} 行")
                if not re.fullmatch(r"V-[A-Za-z0-9_.-]+", key):
                    raise ValueError(f"CSV 第 {line} 行的 id 應以 V- 開頭")
                records.append(Source(key, "record", "results",
                                      f"{case} 的「{group}」{metric}為 {row['value']} {unit}。",
                                      f"measurements.csv 第 {line} 行"))
            seen.add((case, group))
            values, indices, cases = groups.setdefault(group, ([], [], []))
            values.append(value)
            indices.append(line)
            cases.append(case)
    if not groups:
        raise ValueError("measurements.csv 沒有資料列。質性研究可省略此檔")
    return [Measure(group, tuple(values), tuple(rows), tuple(cases),
                    "D-" + hashlib.sha256(group.encode()).hexdigest()[:10])
            for group, (values, rows, cases) in groups.items()], records


def load_project(directory, journal=None):
    root = Path(directory).resolve()
    config = root / "project.json"
    hashes = {}

    def content(path):
        data = path.read_bytes()
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(data).hexdigest()
        return data.decode("utf-8-sig")

    meta = json.loads(content(config))
    journal_name = journal if journal is not None else meta.get("journal")
    target = lookup(journal_name) if journal_name is not None else None
    title = string(meta, "title", "project.json")
    question = string(meta, "question", "project.json")
    demo = meta.get("demo", False)
    keywords = meta.get("keywords", [])
    author = meta.get("author", "")
    if not isinstance(demo, bool) or not isinstance(author, str):
        raise ValueError("project.json 的 demo 應為布林值，author 應為文字")
    if not isinstance(keywords, list) or not all(isinstance(k, str) and k.strip() for k in keywords):
        raise ValueError("keywords 應為文字陣列")
    bank = {}
    def add(s):
        if s.id in bank:
            raise ValueError(f"來源識別碼重複：{s.id}")
        bank[s.id] = s

    add(Source("Q", "question", "intro", question, "project.json / question"))
    refs = root / "references.json"
    if refs.is_file():
        for s in reference_cards(content(refs)):
            add(s)
    for path in sorted((root / "notes").rglob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            for s in note_blocks(path, root, content(path)):
                add(s)
    group_label = string(meta, "group_label", "project.json") if "group_label" in meta else "比較條件"
    measures = []
    metric, unit = "", ""
    data = root / "measurements.csv"
    if data.is_file():
        metric = string(meta, "metric", "有數值資料的 project.json")
        unit = string(meta, "unit", "有數值資料的 project.json")
        measures, records = measurement_groups(content(data), metric, unit)
        for item in records:
            add(item)
        for m in measures:
            text = f"「{m.group}」共 {len(m.values)} 筆，{metric}平均為 {number(m.average)} {unit}。"
            lines = ", ".join(map(str, m.rows))
            add(Source(m.source_id, "data", "results", text, f"measurements.csv 第 {lines} 行"))
    for s in bank.values():
        for key in s.also:
            if key not in bank:
                raise ValueError(f"{s.location} 引用了未登錄來源 {key}")
    if len(bank) == 1:
        raise ValueError("請加入一份研究筆記、已讀書目或數值資料")
    return Project(root, title, question, author.strip(), keywords, demo, metric, group_label, unit,
                   bank, measures, hashes, target)
