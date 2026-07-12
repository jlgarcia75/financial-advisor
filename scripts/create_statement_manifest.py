#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import parse_frontmatter  # noqa: E402

DEFAULT_STATEMENTS_DIR = Path(
    "/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Statements"
)


def is_ready(md_path: Path) -> bool:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(text)
    return fm.get("status") == "ready" or fm.get("review_status") == "ready"


def dataset_files(base: Path) -> dict:
    datasets = {}
    for name in ["accounts", "holdings", "transactions", "activity"]:
        path = base.with_name(f"{base.name}_{name}.csv")
        if path.exists():
            datasets[name] = path.name
    return datasets


def find_statement_files(args) -> list[Path]:
    if args.statement_md:
        return [args.statement_md]

    statements_dir = args.statements_dir or DEFAULT_STATEMENTS_DIR
    files = sorted(statements_dir.glob("*_statement.md"))

    if args.all_ready:
        return [p for p in files if is_ready(p)]

    return [p for p in files if not p.with_suffix(".json").exists()]


def create_manifest(md_path: Path, args) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(md_text)

    base = md_path.with_suffix("")
    out = base.with_suffix(".json")

    if out.exists() and not args.overwrite:
        print(f"Skipping existing manifest: {out}")
        return

    statement_id = fm.get("statement_id") or base.name

    manifest = {
        "schema_version": args.schema_version,
        "statement_id": statement_id,
        "institution": args.institution or fm.get("institution", "unknown"),
        "provider_or_custodian": fm.get("provider_or_custodian"),
        "statement_type": fm.get("statement_type", args.statement_type),
        "source": fm.get("source", "manual_statement"),
        "source_files": {
            "pdf": fm.get("source_file", f"{statement_id}.pdf"),
            "markdown": md_path.name,
        },
        "as_of_date": fm.get("as_of_date"),
        "run_date": fm.get("run_date"),
        "review_status": fm.get("review_status", fm.get("status", "needs_review")),
        "datasets": dataset_files(base),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    manifest = {k: v for k, v in manifest.items() if v is not None}

    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


def main():
    parser = argparse.ArgumentParser(
        description="Create compact statement manifest JSON files from statement Markdown."
    )
    parser.add_argument("statement_md", type=Path, nargs="?")
    parser.add_argument("--statements-dir", type=Path, default=None)
    parser.add_argument("--all-ready", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--institution", default=None)
    parser.add_argument("--statement-type", default="multi_account_brokerage")
    parser.add_argument("--schema-version", default="1.0")

    args = parser.parse_args()

    files = find_statement_files(args)
    if not files:
        print("No statement manifests to create.")
        return

    for md_path in files:
        create_manifest(md_path, args)


if __name__ == "__main__":
    main()
