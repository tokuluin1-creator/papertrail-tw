import csv
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from papertrail.cli import main
from papertrail.review import review
from papertrail.review_report import render_html


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples/citation-audit", self.project)
        self.paper = self.root / "paper.md"
        self.paper.write_text("聯絡信箱 reviewer@example.invalid\n測試主張。[@R-sandve2013]\n[@R-sandve2013]", encoding="utf-8")
        self.claims = self.root / "claims.json"

    def test_summary_evidence_status_and_decision_template(self):
        self.claims.write_text(json.dumps([{"id": "C1", "statement": "測試主張。", "manuscript_locator": "段2", "sources": [{"id": "R-sandve2013", "locator": "Rule 1", "relation": "supports"}]}]))
        out = review(self.paper, self.project, self.root / "out", claims=self.claims)
        report = json.loads((out / "review.json").read_text())
        self.assertEqual(report["summary"]["claims_registered"], 1)
        self.assertGreater(report["summary"]["anonymity_flags"], 0)
        source = next(s for s in report["sources"] if s["id"] == "R-sandve2013")
        self.assertEqual(source["marker_count"], 2)
        self.assertEqual(source["claim_count"], 1)
        self.assertEqual(source["reading_status"], "unverified")
        self.assertEqual(report["claim_checks"][0]["relations"], {"supports": 1})
        self.assertIn("尚未登記全文核讀", (out / "review.md").read_text())
        self.assertNotIn("reviewer@example.invalid", (out / "review.html").read_text())
        with (out / "decisions.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), len(report["findings"]))
        self.assertTrue(all(row["決策（接受/部分接受/不接受/待查）"] == "待查" for row in rows))

    def test_html_escapes_every_input_surface(self):
        attack = '<script>alert(1)</script><img src="https://example.invalid">'
        report = {"summary": dict.fromkeys(["action_required", "missing_information", "human_review", "anonymity_flags", "claims_registered"], 0), "findings": [{"id": attack, "severity": attack, "location": attack, "issue": attack, "action": attack}], "coverage": attack, "limitations": [attack], "input_sha256": {attack: attack}}
        html = render_html(report, [{"id": attack, "reading_status": attack, "claim_count": 0, "marker_count": 0}])
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('Content-Security-Policy', html)

    def test_malformed_source_shapes_fail_with_friendly_cli_error(self):
        for link in [{"id": []}, {"id": "R-sandve2013", "relation": []}, None]:
            self.claims.write_text(json.dumps([{"id": "C1", "statement": "測試主張。", "manuscript_locator": "段2", "sources": [link]}]))
            err = io.StringIO()
            with redirect_stderr(err):
                code = main(["review", str(self.paper), "--project", str(self.project), "--claims", str(self.claims), "--out", str(self.root / "out")])
            self.assertEqual(code, 1)
            self.assertIn("稿證：", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())

    def test_invalid_docx_is_friendly_and_publishes_nothing(self):
        bad = self.root / "bad.docx"
        bad.write_bytes(b"not a word file")
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["review", str(bad), "--project", str(self.project), "--out", str(self.root / "out")])
        self.assertEqual(code, 1)
        self.assertIn("有效且未加密", err.getvalue())
        self.assertFalse((self.root / "out").exists())

    def test_claim_without_source_remains_visible(self):
        self.claims.write_text(json.dumps([{"id": "C-empty", "statement": "測試主張。", "manuscript_locator": "段2", "sources": []}]))
        out = review(self.paper, self.project, self.root / "out", claims=self.claims)
        html = (out / "review.html").read_text()
        self.assertIn('C-empty', html)
        self.assertIn('未連結來源', html)
