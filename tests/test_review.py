import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from papertrail.cli import main
from papertrail.review import review

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/citation-audit"


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        shutil.copytree(EXAMPLE, self.project)
        self.paper = self.root / "paper.md"
        self.paper.write_text("本研究不能排除偏誤，但制度改革導致績效改善。\n背景材料。[@R-missing]", encoding="utf-8")

    def run_review(self, **kwargs):
        return review(self.paper, self.project, self.root / "reports", **kwargs)

    def test_offline_nonmutating_unique_report(self):
        before = self.paper.read_bytes()
        with patch("papertrail.agents.Ollama.ask", side_effect=AssertionError("no model")), patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
            out = self.run_review()
            second = self.run_review()
        self.assertNotEqual(out, second)
        self.assertEqual(self.paper.read_bytes(), before)
        self.assertFalse((out / "draft.docx").exists())
        report = json.loads((out / "review.json").read_text())
        self.assertEqual(report["input_sha256"]["manuscript"], hashlib.sha256(before).hexdigest())
        self.assertTrue(any("因果" in f["issue"] for f in report["findings"]))
        self.assertTrue(any("標記" in f["issue"] for f in report["findings"]))

    def test_claims_reject_question_unknown_and_invalid_relation(self):
        p = self.root / "claims.json"
        for source, relation in [("Q", "supports"), ("R-unknown", "supports"), ("R-sandve2013", "verified")]:
            p.write_text(json.dumps([{"id": "C1", "statement": "背景材料。", "manuscript_locator": "段2", "sources": [{"id": source, "relation": relation}]}]))
            with self.assertRaises(ValueError):
                self.run_review(claims=p)

    def test_context_is_not_support_and_csv_is_inert(self):
        p = self.root / "claims.json"
        p.write_text(json.dumps([{"id": "=C1", "statement": "背景材料。", "manuscript_locator": "段2", "sources": [{"id": "R-sandve2013", "relation": "context", "locator": "方法節"}]}]))
        out = self.run_review(claims=p)
        rows = list(csv.reader((out / "claim-evidence.csv").open(encoding="utf-8-sig")))
        self.assertEqual(rows[1][0], "'=C1")
        self.assertIn("沒有登記直接支持", (out / "review.md").read_text())

    def test_missing_source_locator_and_duplicate_claim(self):
        p = self.root / "claims.json"
        c = {"id": "C1", "statement": "背景材料。", "manuscript_locator": "段2", "sources": [{"id": "R-sandve2013", "relation": "supports"}]}
        p.write_text(json.dumps([c]))
        self.assertIn("缺少主張層級定位", (self.run_review(claims=p) / "review.md").read_text())
        p.write_text(json.dumps([c,c]))
        with self.assertRaisesRegex(ValueError, "重複"):
            self.run_review(claims=p)

    def test_invalid_protocol_and_output_overlap(self):
        p = self.root / "protocol.json"
        for data in [[], {"unknown": "x"}, {"ethics": False}]:
            p.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                self.run_review(protocol=p)
        with self.assertRaises(ValueError):
            review(self.paper, self.project, self.project / "output")
        with self.assertRaises(ValueError):
            review(self.paper, self.project, self.root)

    def test_docx_coverage_and_cli(self):
        from docx import Document
        p = self.root / "paper.docx"
        doc = Document(); doc.add_paragraph("社會科學文獻分析。")
        doc.add_table(rows=1, cols=1).cell(0,0).text = "表格材料"
        doc.save(p)
        out = review(p, self.project, self.root / "word-review")
        self.assertIn("未覆蓋註腳", (out / "review.md").read_text())
        self.assertEqual(main(["review", str(self.paper), "--project", str(self.project), "--out", str(self.root / "cli")]), 0)
