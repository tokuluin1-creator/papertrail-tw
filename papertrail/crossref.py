"""Find candidate records; only author-curated reading cards enter the manuscript."""
import json
import re
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def search(query, limit):
    if not query.strip() or not 1 <= limit <= 30:
        raise ValueError("請輸入查詢詞，筆數限 1 至 30")
    params = urlencode({"query.bibliographic": query, "rows": limit})
    request = Request("https://api.crossref.org/works?" + params,
                      headers={"Accept": "application/json", "User-Agent": "PaperTrail-TW/0.1"})
    try:
        with urlopen(request, timeout=25) as response:
            items = json.load(response)["message"]["items"]
    except (HTTPError, URLError, TimeoutError, OSError, KeyError, ValueError) as exc:
        raise ValueError(f"Crossref 查詢失敗：{exc}") from exc
    rows = []
    for item in items:
        title = (item.get("title") or [""])[0]
        if not title or not item.get("DOI"):
            continue
        authors = [" ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "")
                   for a in item.get("author", [])]
        date = (item.get("published") or item.get("issued") or {}).get("date-parts") or [[]]
        rows.append({"title": unescape(re.sub("<[^>]+>", "", title)), "authors": authors,
                     "year": date[0][0] if date[0] else None,
                     "journal": (item.get("container-title") or [""])[0],
                     "doi": item["DOI"], "url": "https://doi.org/" + item["DOI"],
                     "status": "待讀原文"})
    return {"query": query, "source": "Crossref", "candidates": rows}
