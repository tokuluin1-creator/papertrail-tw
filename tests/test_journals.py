import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.resources import files
from pathlib import Path

from papertrail.agents import context
from papertrail.cli import main
from papertrail.journals import catalogue, lookup
from papertrail.materials import load_project


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "citation-audit"


class JournalTests(unittest.TestCase):
    def test_catalogue_links_names_and_provenance(self):
        guide = files("papertrail").joinpath("journal-guides.md").read_text(encoding="utf-8")
        self.assertEqual(len(catalogue()), 24)
        names = set()
        for number, journal in enumerate(catalogue(), 1):
            self.assertIn(f"](#{journal.name})", guide)
            self.assertIn(f"第 {number} 項", dict(journal.rules)["出處"])
            self.assertIn("2026-09-24", journal.edition)
            for name in (journal.name, *journal.aliases):
                with self.subTest(name=name):
                    self.assertNotIn(name, names)
                    self.assertIs(lookup(name), journal)
                    names.add(name)

    def test_spoken_targets_and_errors(self):
        for instruction, name in [
            ("這篇要投《海軍雙月刊》，請依稿證檢查。", "海軍學術雙月刊"),
            ("我想改投海軍官校季刊", "海軍軍官季刊"),
            ("稿件預計投稿至 空軍雙月刊", "空軍學術雙月刊"),
            ("投空軍官校雙月刊", "空軍軍官雙月刊"),
            ("目標期刊：通識學報", "國防大學通識教育學報"),
            ("投稿期刊：空軍雙月刊", "空軍學術雙月刊"),
            ("《通識學報》的投稿規定", "國防大學通識教育學報"),
            ("我要投稿的期刊是《中共研究》", "中共研究"),
        ]:
            with self.subTest(instruction=instruction):
                self.assertEqual(lookup(instruction).name, name)
        for query in ["雙月刊", "投海軍雙月刊或空軍雙月刊", "未知季刊", "不要投海軍雙月刊", "", 123]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                lookup(query)
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            self.assertEqual(main(["journal"]), 0)
            self.assertEqual(main(["journal", "我要投稿到國防雜誌"]), 0)
            self.assertEqual(main(["journal", "雙月刊"]), 1)
        self.assertIn("作者、年代與頁碼", output.getvalue())
        self.assertIn("空軍軍官雙月刊", error.getvalue())

    def test_scoped_rules(self):
        self.assertIn("含註釋", lookup("海軍雙月刊").markdown())
        self.assertIn("不含註釋", lookup("通識學報").markdown())
        self.assertIn("專題研究", lookup("中共研究").markdown())
        self.assertIn("書評", lookup("中國大陸研究").markdown())
        self.assertIn("4 個中文關鍵詞", lookup("中國大陸研究").markdown())
        self.assertIn("第 256 期", lookup("裝甲兵季刊").markdown())

    def test_build_review_and_project_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "inputs"
            shutil.copytree(EXAMPLE, project)
            self.assertNotIn("editorial_guidance", context(load_project(project)))
            config = project / "project.json"
            meta = json.loads(config.read_text(encoding="utf-8"))
            meta["journal"] = "通識學報"
            config.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            data = context(load_project(project))
            self.assertIn("不含註釋", data["editorial_guidance"])
            self.assertNotIn("彙編", str(data["evidence"]))

            def run(args):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(args), 0)
                return Path(output.getvalue().strip())

            draft = run(["build", str(project), "-o", str(root / "builds")])
            result = run(["review", str(draft / "draft.docx"), "--project", str(project),
                          "--journal", "陸軍雙月刊", "-o", str(root / "reviews")])
            for folder, report, name in [(draft, "run.json", "國防大學通識教育學報"),
                                         (result, "review.json", "陸軍學術雙月刊")]:
                entry = json.loads((folder / report).read_text(encoding="utf-8"))["journal"]
                self.assertEqual(entry["name"], name)
                self.assertEqual(entry["sha256"], hashlib.sha256((folder / "journal.md").read_bytes()).hexdigest())
                self.assertIn("journal.md", (folder / "review.md").read_text(encoding="utf-8"))
            html = (result / "review.html").read_text(encoding="utf-8")
            self.assertIn("篇幅與提要", html)
            self.assertIn("12,000 字", html)
            self.assertNotIn("國防大學通識教育學報", html)
            self.assertNotIn("彙編版本", (draft / "draft.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["journal"], "通識學報")


if __name__ == "__main__":
    unittest.main()
