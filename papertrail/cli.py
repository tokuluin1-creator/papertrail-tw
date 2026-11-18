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
from .journals import catalogue, lookup
from .materials import load_project


def build(input_dir, out, model=None, host="http://127.0.0.1:11434", pdf=False, template=None, allow_remote=False, journal=None):
    from .export import export_all
    from .figures import draw_figures
    project = load_project(input_dir, journal)
    parent = Path(out).resolve()
    if parent.is_relative_to(project.root / "notes"):
        raise ValueError("輸出目錄請設在輸入筆記目錄之外")
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".writing-", dir=parent))
    try:
        client = Ollama(model, host, allow_remote=allow_remote) if model else None
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
    run.add_argument("--allow-remote", action="store_true", help="明確允許將研究材料傳給非本機 Ollama；先確認敏感資訊與主機信任")
    run.add_argument("--pdf", action="store_true", help="以已安裝的 XeLaTeX 編譯 PDF")
    run.add_argument("--template", type=Path, help="自訂 XeLaTeX 檔或含 template.tex 的目錄")
    run.add_argument("--journal", help="投稿刊名或簡稱，可覆寫 project.json 的 journal")
    guide = subs.add_parser("journal", help="依刊名查投稿規範，省略刊名可列出全部期刊")
    guide.add_argument("name", nargs="?", help="刊名、簡稱，或包含投稿目標的短句")
    find = subs.add_parser("search", help="透過 Crossref 尋找候選文獻")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=6)
    find.add_argument("-o", "--out", type=Path, help="新 JSON 檔，省略時印到終端機")
    audit = subs.add_parser("review", help="離線審查既有稿件；不改稿、不呼叫模型")
    audit.add_argument("manuscript", type=Path)
    audit.add_argument("--project", type=Path, required=True, help="研究材料目錄")
    audit.add_argument("--protocol", type=Path, help="社科文獻研究程序與投稿核對JSON")
    audit.add_argument("--claims", type=Path, help="主張—來源對照JSON")
    audit.add_argument("-o", "--out", type=Path, default=Path("reviews"))
    audit.add_argument("--journal", help="在審查報告引用指定刊物的投稿規範")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print(build(args.input, args.out, args.model, args.ollama_url, args.pdf, args.template, args.allow_remote, args.journal))
        elif args.command == "review":
            from .review import review
            print(review(args.manuscript, args.project, args.out, args.protocol, args.claims, args.journal))
        elif args.command == "journal":
            if args.name is None:
                print("\n".join(f"{j.name}（{'、'.join(j.aliases)}）" for j in catalogue()))
            else:
                print(lookup(args.name).markdown(), end="")
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
