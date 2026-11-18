"""Look up editorial requirements in the same guide that readers see on GitHub."""
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib.resources import files


@dataclass(frozen=True)
class Journal:
    name: str
    aliases: tuple[str, ...]
    edition: str
    rules: tuple[tuple[str, str], ...]

    def markdown(self):
        lines = [f"# {self.name}｜投稿規範", "", self.edition, ""]
        lines.extend(f"- **{label}**　{text}" for label, text in self.rules)
        return "\n".join(lines) + "\n"

    def record(self):
        return {"name": self.name, "edition": self.edition, "rules": dict(self.rules),
                "sha256": hashlib.sha256(self.markdown().encode("utf-8")).hexdigest()}


@cache
def catalogue():
    guide = files("papertrail").joinpath("journal-guides.md").read_text(encoding="utf-8")
    intro, *sections = re.split(r"^## ", guide, flags=re.MULTILINE)
    edition = next(line for line in intro.splitlines() if line.startswith("彙編版本　"))
    journals = []
    for section in sections:
        name, alias_line, *lines = (line for line in section.splitlines() if line.strip())
        aliases = tuple(alias_line.removeprefix("別名　").split("、"))
        rules = tuple(re.fullmatch(r"- \*\*(.+?)\*\*　(.+)", line).groups() for line in lines)
        journals.append(Journal(name, aliases, edition, rules))
    return tuple(journals)


def lookup(query):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("請提供期刊全名或簡稱。")
    target = unicodedata.normalize("NFKC", query).strip()
    # Accept an instruction as well as a name. Keep both targets in an either/or request.
    target = re.sub(r"的?投稿(?:規範|要求|規定|格式)[。.!！?？]*$", "", target)
    request = re.search(r"投(?:稿)?(?:(?:的)?(?:目標)?期刊[是為]?|到|至|給|於|向)?", target)
    if request:
        if re.search(r"(?:不|別|不要|不想|不打算)$", target[:request.start()]):
            raise ValueError("請直接指定要投稿的期刊。")
        target = target[request.end():].lstrip(" :：")
    else:
        target = re.sub(r"^(?:目標|指定)期刊\s*[是為:：]?\s*", "", target)
    target = re.split(r"[,，。；;]\s*(?=請|幫我|依|按|麻煩)", target, maxsplit=1)[0]
    key = re.sub(r"[\s《》〈〉「」『』]", "", target).strip("。.!！?？")
    journals = catalogue()
    for journal in journals:
        if key in (journal.name, *journal.aliases):
            return journal
    candidates = [j.name for j in journals if key and any(
        key in name or name in key for name in (j.name, *j.aliases))]
    if candidates:
        raise ValueError("請指定一個完整刊名或簡稱，可選擇：" + "、".join(candidates))
    raise ValueError(f"未收錄期刊「{query}」。執行 papertrail journal 可查看刊名與簡稱。")
