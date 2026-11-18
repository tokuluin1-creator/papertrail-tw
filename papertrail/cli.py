import argparse
import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired

from .agents import Ollama, build_draft, inspect_draft, plan_sections, synthesize
from .crossref import search
from .materials import load_project


def build(input_dir, out, model=None, host="http://127.0.0.1:11434", pdf=False, template=None):
    from .export import export_all
    from .figures import draw_figures
    project = load_project(input_dir)
    parent = Path(out).resolve()
    if parent.is_relative_to(project.root / "notes"):
        raise ValueError("輸出目錄請設在輸入筆記目錄之外")
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".writing-", dir=parent))
    try:
        client = Ollama(model, host) if model else None
        plan = plan_sections(project, client)
        literature = synthesize(project, client)
        abstract, sections = build_draft(project, plan, literature, client)
        review = inspect_draft(project, plan, abstract, sections, client)
        figures = draw_figures(project, staging / "figures")
        export_all(project, plan, abstract, sections, figures, review, model, staging,
                   Path(template) if template else None, pdf)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        final = parent / (stamp + "-" + uuid.uuid4().hex[:8])
        staging.rename(final)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description="稿證｜從研究筆記編製論文草稿")
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("build", help="整理材料並輸出論文與審查筆記")
    run.add_argument("input", type=Path)
    run.add_argument("-o", "--out", type=Path, default=Path("output"))
    run.add_argument("--model", help="本機 Ollama 已安裝的模型，省略時採離線摘錄")
    run.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    run.add_argument("--pdf", action="store_true", help="以已安裝的 XeLaTeX 編譯 PDF")
    run.add_argument("--template", type=Path, help="自訂 XeLaTeX 檔或含 template.tex 的目錄")
    find = subs.add_parser("search", help="透過 Crossref 尋找候選文獻")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=6)
    find.add_argument("-o", "--out", type=Path, help="新 JSON 檔，省略時印到終端機")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(build(args.input, args.out, args.model, args.ollama_url, args.pdf, args.template))
        else:
            result = json.dumps(search(args.query, args.limit), ensure_ascii=False, indent=2)
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                with args.out.open("x", encoding="utf-8") as f:
                    f.write(result + "\n")
            else:
                print(result)
        return 0
    except (OSError, ValueError, TimeoutExpired, OverflowError) as exc:
        print(f"稿證：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
