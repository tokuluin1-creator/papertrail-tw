"""Export one manuscript representation to Markdown, XeLaTeX, Word and an audit ledger."""
import csv
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.shared import Cm, Pt, RGBColor

from . import __version__
from .agents import paragraph_index
from .materials import write_json

DEMO = "教學示例，數值為模擬資料"
MISSING = "待補資料。"


def refs_for(project, p):
    return [project.sources[key] for key in p.sources if project.sources[key].kind == "reference"]


def reftext(source):
    return f"{source.citation.rstrip('。 .')}，{source.location}。"


def caption(n, f):
    return f"圖 {n}　{f.title}"


def used_refs(project, indexed):
    keys = {s.id for _, _, p in indexed for s in refs_for(project, p)}
    return sorted((project.sources[k] for k in keys), key=lambda s: s.bibliography.casefold())


def tex_escape(s):
    chars = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
             "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(chars.get(c, c) for c in s)


def tex_link(url):
    if not url:
        return ""
    # Use normal escaped text inside a link so XeTeX can break long URLs.
    return r" \href{" + tex_escape(url) + "}{" + tex_escape(url) + "}"


def note_tex(project, p):
    notes = [tex_escape(reftext(s)) + tex_link(s.url) for s in refs_for(project, p)]
    return tex_escape(p.text) + (r"\footnote{" + r"\enspace ".join(notes) + "}" if notes else "")


def template_text(template, dest):
    if template is None:
        return Path(__file__).with_name("article.tex").read_text(encoding="utf-8")
    if template.is_dir():
        for file in template.iterdir():
            if file.is_file() and file.suffix in {".cls", ".sty"}:
                shutil.copy2(file, dest / file.name)
        assets = template / "assets"
        if assets.is_dir():
            if dest.resolve().is_relative_to(assets.resolve()):
                raise ValueError("輸出位置請設在版型的 assets 目錄外")
            shutil.copytree(assets, dest / "assets")
        template = template / "template.tex"
    return template.read_text(encoding="utf-8-sig")


def write_tex(project, plan, abstract, sections, figures, refs, dest, template):
    body = []
    for row in plan:
        key = row["id"]
        body.append(r"\section{" + tex_escape(row["heading"]) + "}")
        body.extend(note_tex(project, p) for p in sections[key])
        if not sections[key]:
            body.append(tex_escape(MISSING))
        for i, f in enumerate(figures, 1):
            if f.section == key:
                body.append("\n".join([r"\begin{center}\begin{minipage}{0.94\linewidth}\centering",
                             r"\includegraphics[width=0.86\linewidth]{figures/" + f.stem + ".pdf}",
                             r"\par\small\bfseries " + tex_escape(caption(i, f)),
                             r"\par\normalfont\footnotesize 資料來源　" + tex_escape(f.source),
                             r"\end{minipage}\end{center}"]))
    bib = [r"\section{參考文獻}", r"\begingroup\small\raggedright", *[tex_escape(s.bibliography) + tex_link(s.url) + r"\par" for s in refs], r"\endgroup"]
    values = {"TITLE": tex_escape(project.title), "BYLINE": tex_escape("　｜　".join(filter(None, [
                  project.author, DEMO if project.demo else ""]))),
              "ABSTRACT": note_tex(project, abstract), "KEYWORDS": tex_escape(
                  "關鍵詞　" + "、".join(project.keywords) if project.keywords else ""),
              "BODY": "\n\n".join(body), "REFERENCES": "\n".join(bib) if refs else ""}
    text = template_text(template, dest)
    for key in values:
        if text.count("@@" + key + "@@") != 1:
            raise ValueError(f"LaTeX 版型必須且只能含有一個 @@{key}@@")
    # A single substitution never interprets text supplied by the researcher as a template token.
    text = re.sub(r"@@(TITLE|BYLINE|ABSTRACT|KEYWORDS|BODY|REFERENCES)@@", lambda m: values[m[1]], text)
    (dest / "draft.tex").write_text(text, encoding="utf-8")


def compile_tex(dest):
    engine = shutil.which("xelatex")
    if not engine:
        raise ValueError("找不到 XeLaTeX。可省略 --pdf 產生 Word 與 LaTeX 原始稿")
    for _ in range(2):
        result = subprocess.run([engine, "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode",
                                 "draft.tex"], cwd=dest, capture_output=True, timeout=150, check=False)
        if result.returncode or not (dest / "draft.pdf").is_file():
            tail = result.stdout.decode(errors="replace").splitlines()[-18:]
            raise ValueError("XeLaTeX 編譯失敗。\n" + "\n".join(tail))
    for suffix in (".aux", ".log", ".out", ".toc"):
        (dest / ("draft" + suffix)).unlink(missing_ok=True)


def md_text(s):
    return re.sub(r"([\\`*_{}\[\]<>!#|~])", r"\\\1", s)


def write_markdown(project, plan, abstract, sections, figures, refs, dest):
    def para(p):
        return md_text(p.text) + "".join(f"[^{s.id}]" for s in refs_for(project, p))
    lines = ["# " + md_text(project.title), md_text(project.author)]
    if project.demo:
        lines.append("**" + DEMO + "**")
    lines += ["## 摘要", para(abstract)]
    if project.keywords:
        lines.append("關鍵詞　" + "、".join(map(md_text, project.keywords)))
    for row in plan:
        key = row["id"]
        lines.append("## " + md_text(row["heading"]))
        lines.extend(para(p) for p in sections[key])
        if not sections[key]:
            lines.append(MISSING)
        for i, f in enumerate(figures, 1):
            if f.section == key:
                lines.extend([f"![{md_text(caption(i, f))}](figures/{f.stem}.png)",
                              md_text(caption(i, f)), "資料來源　" + md_text(f.source)])
    if refs:
        lines.append("## 參考文獻")
        for s in refs:
            lines.append(md_text(s.bibliography) + (f" <{s.url}>" if s.url else ""))
        for s in refs:
            lines.append(f"[^{s.id}]: " + md_text(reftext(s)) + (f" <{s.url}>" if s.url else ""))
    (dest / "draft.md").write_text("\n\n".join(filter(None, lines)) + "\n", encoding="utf-8")


def word_font(style, size, bold=False):
    style.font.name = "Arial"
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string("171B1E")
    style.font.bold = bold
    fonts = style.element.get_or_add_rPr().rFonts
    for k in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme"):
        fonts.attrib.pop(qn("w:" + k), None)
    fonts.set(qn("w:eastAsia"), "Microsoft JhengHei")


def elem(parent, name, **attrs):
    node = OxmlElement(name)
    for k, v in attrs.items():
        node.set(qn(k), str(v))
    parent.append(node)
    return node


def footnotes_root():
    root = OxmlElement("w:footnotes")
    for i, typ in [(-1, "separator"), (0, "continuationSeparator")]:
        node = elem(root, "w:footnote", **{"w:id": i, "w:type": typ})
        run = elem(elem(node, "w:p"), "w:r")
        elem(run, "w:" + typ)
    return root


def word_link(parent, part, url):
    relation = part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = elem(parent, "w:hyperlink", **{"r:id": relation})
    r = elem(link, "w:r")
    fmt = elem(r, "w:rPr")
    elem(fmt, "w:color", **{"w:val": "216160"})
    elem(fmt, "w:u", **{"w:val": "single"})
    elem(r, "w:t").text = url


def add_note(paragraph, part, index, sources):
    marker = paragraph.add_run()
    marker.font.superscript = True
    elem(marker._r, "w:footnoteReference", **{"w:id": index})
    foot = elem(part.element, "w:footnote", **{"w:id": index})
    p = elem(foot, "w:p")
    elem(elem(p, "w:pPr"), "w:pStyle", **{"w:val": "FootnoteText"})
    r = elem(p, "w:r")
    elem(elem(r, "w:rPr"), "w:vertAlign", **{"w:val": "superscript"})
    elem(r, "w:footnoteRef")
    for source in sources:
        t = elem(elem(p, "w:r"), "w:t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = " " + reftext(source) + " "
        if source.url:
            word_link(p, part, source.url)


def write_word(project, plan, abstract, sections, figures, refs, dest):
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(2.5)
    styles = doc.styles
    normal = styles["Normal"]
    word_font(normal, 12)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.30
    for name, size, bold in (("Title", 21, True), ("Heading 1", 15, True), ("Caption", 10, False)):
        s = styles[name]
        word_font(s, size, bold)
        s.font.italic = False
        s.paragraph_format.space_before = Pt(1 if name == "Caption" else 6)
        s.paragraph_format.space_after = Pt(2 if name == "Caption" else 3)
        s.paragraph_format.keep_with_next = name != "Caption"
        pr = s.element.get_or_add_pPr()
        for border in list(pr.findall(qn("w:pBdr"))):
            pr.remove(border)
    footstyle = (styles["Footnote Text"] if "Footnote Text" in styles else
                 styles.add_style("Footnote Text", WD_STYLE_TYPE.PARAGRAPH))
    word_font(footstyle, 9)
    footstyle.paragraph_format.space_after = Pt(2)
    footstyle.paragraph_format.line_spacing = 1.05
    doc.core_properties.title = project.title
    doc.core_properties.author = project.author
    doc.core_properties.description = DEMO if project.demo else "論文草稿"
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = elem(footer._p, "w:fldSimple", **{"w:instr": "PAGE"})
    elem(elem(field, "w:r"), "w:t").text = "1"
    foots = XmlPart(PackURI("/word/footnotes.xml"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
                    footnotes_root(), doc.part.package)
    count = 0

    def paragraph(p):
        nonlocal count
        line = doc.add_paragraph(p.text)
        cited = refs_for(project, p)
        if cited:
            count += 1
            add_note(line, foots, count, cited)
    doc.add_paragraph(project.title, "Title")
    byline = "　｜　".join(filter(None, [project.author, DEMO if project.demo else ""]))
    if byline:
        doc.add_paragraph(byline, "Caption")
    doc.add_heading("摘要", 1)
    paragraph(abstract)
    if project.keywords:
        doc.add_paragraph("關鍵詞　" + "、".join(project.keywords), "Caption")
    for row in plan:
        key = row["id"]
        doc.add_heading(row["heading"], 1)
        for p in sections[key]:
            paragraph(p)
        if not sections[key]:
            doc.add_paragraph(MISSING)
        for i, f in enumerate(figures, 1):
            if f.section == key:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.keep_with_next = True
                p.add_run().add_picture(str(dest / "figures" / (f.stem + ".png")), width=Cm(13.4))
                cap = doc.add_paragraph(caption(i, f), "Caption")
                cap.paragraph_format.keep_with_next = True
                doc.add_paragraph("資料來源　" + f.source, "Caption")
    if refs:
        doc.add_heading("參考文獻", 1)
        for s in refs:
            p = doc.add_paragraph(s.bibliography)
            if s.url:
                p.add_run(" ")
                word_link(p._p, doc.part, s.url)
            p.paragraph_format.left_indent = Cm(.65)
            p.paragraph_format.first_line_indent = Cm(-.65)
    if count:
        doc.part.relate_to(foots, RT.FOOTNOTES)
    doc.save(dest / "draft.docx")


def write_audit(project, plan, indexed, findings, model_name, dest):
    with (dest / "evidence.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["段落 ID", "章節", "草稿段落", "來源 ID", "來源類型", "出處定位", "來源文字或讀書筆記", "網址"])
        for pid, heading, p in indexed:
            for key in p.sources:
                s = project.sources[key]
                w.writerow([pid, heading, p.text, key, s.kind, s.location, s.text, s.url])
    outline = ["# 論文大綱", project.question]
    for row in plan:
        outline.extend(["## " + row["heading"], row["focus"]])
    (dest / "outline.md").write_text("\n\n".join(outline) + "\n", encoding="utf-8")
    review = ["# 審查筆記", "本次檢查方式　" + ("Ollama 多代理及規則檢查" if model_name else "離線規則檢查")]
    if project.journal:
        (dest / "journal.md").write_text(project.journal.markdown(), encoding="utf-8", newline="\n")
        review.append(f"投稿目標為《{project.journal.name}》。[查閱本次所用的投稿規範與出處](journal.md)")
    if project.demo:
        review.append(DEMO + "。請以這份輸出練習回查來源。")
    if findings:
        review.extend(f"- **{pid}｜{issue}**　{fix}" for pid, issue, fix in findings)
    else:
        review.append("本輪未標出具體疑點。")
    review.append("逐段覆核可開啟 evidence.csv，比對草稿與所引材料。規則檢查能比對數字字串、來源識別碼與部分強因果用語。來源是否真正支持主張，仍由作者判讀。")
    (dest / "review.md").write_text("\n\n".join(review) + "\n", encoding="utf-8")
    write_json(dest / "run.json", {
        "version": __version__, "mode": "ollama" if model_name else "extractive",
        "model": model_name, "synthetic": project.demo, "input_sha256": project.hashes,
        "outline": plan, "sources": [asdict(s) for s in project.sources.values()],
        "paragraphs": [{"id": k, "section": section, **asdict(p)} for k, section, p in indexed],
        "review": findings,
        **({"journal": project.journal.record()} if project.journal else {}),
    })


def export_all(project, plan, abstract, sections, figures, findings, model, dest, template, pdf):
    indexed = list(paragraph_index(plan, abstract, sections))
    refs = used_refs(project, indexed)
    write_markdown(project, plan, abstract, sections, figures, refs, dest)
    write_tex(project, plan, abstract, sections, figures, refs, dest, template)
    write_word(project, plan, abstract, sections, figures, refs, dest)
    write_audit(project, plan, indexed, findings, model, dest)
    if pdf:
        compile_tex(dest)
