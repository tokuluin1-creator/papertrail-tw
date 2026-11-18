import csv
import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from lxml import etree

from papertrail.agents import BODY_KEYS, SECTIONS, supported
from papertrail.cli import build
from papertrail.crossref import search
from papertrail.export import tex_escape
from papertrail.materials import load_project

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "citation-audit"
W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.space = tempfile.TemporaryDirectory()
        self.addCleanup(self.space.cleanup)
        self.root = Path(self.space.name)
        self.paper = self.root / "paper"
        shutil.copytree(EXAMPLE, self.paper)

    def test_original_records_and_case_exception(self):
        project = load_project(self.paper)
        self.assertEqual([m.average for m in project.measures], [78, 38])
        self.assertEqual(project.sources["V-C04L"].location, "measurements.csv 第 9 行")
        self.assertIn("46 秒", project.sources["V-C04L"].text)
        self.assertIn("measurements.csv", project.hashes)

    def test_extract_and_export(self):
        out = build(self.paper, self.root / "runs")
        with (out / "evidence.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        ids = {r["來源 ID"] for r in rows if r["段落 ID"] == "results.2"}
        self.assertTrue({"V-C04B", "V-C04L"}.issubset(ids))
        self.assertIn("C04", (out / "review.md").read_text())
        self.assertIn("教學示例", (out / "draft.tex").read_text())
        self.assertTrue((out / "figures" / "values.pdf").is_file())
        with ZipFile(out / "draft.docx") as z:
            doc = etree.fromstring(z.read("word/document.xml"))
            notes = etree.fromstring(z.read("word/footnotes.xml"))
            refs = doc.xpath("//w:footnoteReference/@w:id", namespaces=W)
            self.assertEqual(refs, ["1", "2"])
            self.assertEqual(notes.xpath("count(//w:footnoteRef)", namespaces=W), len(refs))
            links = etree.fromstring(z.read("word/_rels/footnotes.xml.rels")).xpath("//@Target")
            self.assertIn("https://doi.org/10.1371/journal.pcbi.1003285", links)

    def test_unknown_reference_and_invalid_number(self):
        project = load_project(self.paper)
        with self.assertRaisesRegex(ValueError, "未知"):
            supported({"text": "未查證的說法", "sources": ["R-missing"]}, project.sources)
        data = self.paper / "measurements.csv"
        data.write_text(data.read_text().replace(",82", ",NaN"))
        with self.assertRaisesRegex(ValueError, "有限數值"):
            load_project(self.paper)

    def test_duplicate_measurement_fails_with_row_number(self):
        data = self.paper / "measurements.csv"
        with data.open("a") as f:
            f.write("V-new,C01,僅記書目,82\n")
        with self.assertRaisesRegex(ValueError, "第 14 行"):
            load_project(self.paper)

    def test_unknown_reference_in_notes(self):
        (self.paper / "notes" / "extra.md").write_text("新的註記。[@R-missing]")
        with self.assertRaisesRegex(ValueError, "R-missing"):
            load_project(self.paper)

    def test_qualitative_without_a_spreadsheet(self):
        (self.paper / "measurements.csv").unlink()
        (self.paper / "notes" / "observations.md").write_text("## 討論\n此記錄留供解釋。")
        out = build(self.paper, self.root / "qual")
        self.assertFalse((out / "figures" / "values.png").exists())
        self.assertTrue((out / "figures" / "concept.png").is_file())
        self.assertIn("本節缺少材料", (out / "review.md").read_text())

    def test_template_tokens_and_failed_run_do_not_publish_partial_files(self):
        self.assertEqual(tex_escape("A&B_5%"), r"A\&B\_5\%")
        template = self.root / "template.tex"
        template.write_text("@@TITLE@@")
        out = self.root / "work"
        with self.assertRaisesRegex(ValueError, "版型"):
            build(self.paper, out, template=template)
        self.assertEqual(list(out.iterdir()), [])

    def test_crossref_candidate_is_separate_from_reading_cards(self):
        from io import BytesIO
        body = {"message": {"items": [{"DOI": "10.1234/example", "title": ["An example"],
                "author": [{"given": "A.", "family": "Smith"}], "published": {"date-parts": [[2020]]}}]}}
        with patch("papertrail.crossref.urlopen", return_value=BytesIO(json.dumps(body).encode())):
            found = search("a test", 1)["candidates"][0]
        self.assertEqual(found["status"], "待讀原文")
        self.assertNotIn("reading_note", found)

    def test_ollama_protocol_and_agent_handoffs(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                payload = json.loads(req["messages"][1]["content"])
                calls.append((self.path, req, payload))
                stage = len(calls)
                if stage == 1:
                    reply = {"sections": [{"id": k, "heading": v, "focus": "已有什麼資料？"}
                                          for k, v in SECTIONS.items()]}
                elif stage == 2:
                    reply = {"paragraphs": [{"text": "這是測試用的文獻段落。", "sources": ["R-prov2013"]}]}
                elif stage == 3:
                    intro = {"text": "這是介面測試。", "sources": ["Q"]}
                    reply = {"abstract": intro, "sections": {k: [intro] for k in BODY_KEYS}}
                else:
                    reply = {"findings": [{"paragraph": "intro.1", "issue": "測試疑點", "suggestion": "回查筆記。"}]}
                content = {"message": {"content": json.dumps(reply)}, "done": True}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(content).encode())

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                out = build(self.paper, self.root / "remote", "protocol-fixture",
                            f"http://127.0.0.1:{server.server_port}")
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(path == "/api/chat" and req["stream"] is False for path, req, _ in calls))
        self.assertIn("這是測試用的文獻段落。", calls[2][2]["literature"][0]["text"])
        self.assertTrue(any(p["id"] == "intro.1" for p in calls[3][2]["paragraphs"]))
        self.assertIn("測試疑點", (out / "review.md").read_text())


if __name__ == "__main__":
    unittest.main()
