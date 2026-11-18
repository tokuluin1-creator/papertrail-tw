import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from unittest.mock import patch

from papertrail.privacy import scan_anonymity


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_docx(self, parts):
        path = self.root / "synthetic.docx"
        with ZipFile(path, "w", compression=ZIP_DEFLATED) as z:
            for name, body in parts.items():
                z.writestr(name, body)
        return path

    def test_text_categories_locations_without_sensitive_values(self):
        text = "一般論文。\n電子信箱: synthetic.person@example.invalid\n電話：02-2345-6789\n作者：合成人名\n0912-345-678\n+886 2 2345 6789"
        findings = scan_anonymity(self.root / "paper.md", text)
        self.assertEqual(len(findings), 5)
        self.assertEqual(findings[0]["location"], "抽取文字第2行")
        output = json.dumps(findings, ensure_ascii=False)
        for secret in ("synthetic.person", "example.invalid", "合成人名", "2345", "0912", "886"):
            self.assertNotIn(secret, output)
        self.assertTrue(all(set(f) == {"location", "issue", "action"} for f in findings))

    def test_dates_doi_and_cited_names_not_identity_labels(self):
        text = "2026-11-18\nDOI: 10.1234/5678901234\n王甲（2025）討論制度。\n頁 100-120\n作者認為此說仍待驗證。"
        self.assertEqual(scan_anonymity(self.root / "paper.txt", text), [])

    def test_docx_properties_comments_revisions_are_read_only(self):
        path = self.make_docx({
            "docProps/core.xml": '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>SyntheticCreator</dc:creator><cp:lastModifiedBy>SyntheticEditor</cp:lastModifiedBy></cp:coreProperties>',
            "word/comments.xml": '<comments>secret comment</comments>',
            "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:ins w:author="SyntheticReviewer"/><w:del/></w:document>',
            "word/header1.xml": '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:rPrChange/></w:hdr>',
        })
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline")):
            findings = scan_anonymity(path, "正文")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertEqual(len(findings), 4)  # both properties, comments, deduplicated revisions
        output = json.dumps(findings)
        for value in ("SyntheticCreator", "SyntheticEditor", "SyntheticReviewer", "secret comment"):
            self.assertNotIn(value, output)

    def test_empty_properties_and_revision_setting_not_actual_revision(self):
        path = self.make_docx({
            "docProps/core.xml": '<dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/"> </dc:creator>',
            "word/settings.xml": '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:trackRevisions/></w:settings>',
        })
        self.assertEqual(scan_anonymity(path, "正文"), [])

    def test_corrupt_package_or_xml_warns_incomplete_without_exception_text(self):
        path = self.root / "private-person.docx"
        path.write_text("not a zip")
        for candidate in (path, self.make_docx({"word/document.xml": "<broken synthetic-secret"})):
            findings = scan_anonymity(candidate, "")
            self.assertTrue(any("未完成" in f["issue"] for f in findings))
            self.assertNotIn("private-person", json.dumps(findings))
            self.assertNotIn("synthetic-secret", json.dumps(findings))

    def test_size_limit_does_not_silently_pass(self):
        path = self.make_docx({"word/document.xml": "<document>synthetic</document>"})
        with patch("papertrail.privacy._MAX_XML_BYTES", 4):
            findings = scan_anonymity(path, "")
        self.assertTrue(any("未完成" in f["issue"] for f in findings))
