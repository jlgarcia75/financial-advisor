#!/usr/bin/env python3
import argparse
import calendar
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import parse_date, parse_frontmatter  # noqa: E402

DEFAULT_STATEMENTS_DIR = Path(
    "/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Statements"
)

UNKNOWN = {"", "unknown", "none"}


def is_ready(md_path: Path) -> bool:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    fm = parse_frontmatter(text)
    return fm.get("status") == "ready" or fm.get("review_status") == "ready"


def _body_date(md_text: str, label: str) -> str:
    """Pull a `<label> :MM/DD/YYYY` value out of the statement body (e.g. the
    Empower 'As of Date' / 'Run Date' cells), normalized to ISO. '' if absent."""
    m = re.search(rf"{label}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})", md_text, flags=re.I)
    return parse_date(m.group(1)) if m else ""


def _period_end(statement_id: str) -> str:
    """End-of-month ISO date derived from a YYYY-MM_ statement_id prefix. '' if none."""
    m = re.match(r"(\d{4})-(\d{2})", statement_id)
    if not m:
        return ""
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return ""
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def resolve_as_of_date(fm: dict, md_text: str, statement_id: str) -> str:
    """as_of_date, preferring frontmatter, then the body 'As of Date', then the
    last day of the statement's period month."""
    fm_value = str(fm.get("as_of_date", "")).strip()
    if fm_value:
        return parse_date(fm_value)
    return _body_date(md_text, "As of Date") or _period_end(statement_id)


def clean(value, fallback):
    """Return fallback when value is missing/placeholder ('unknown')."""
    return fallback if str(value or "").strip().lower() in UNKNOWN else value


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
        "institution": clean(args.institution or fm.get("institution"), "unknown"),
        "provider_or_custodian": fm.get("provider_or_custodian"),
        "statement_type": clean(fm.get("statement_type"), args.statement_type),
        "source": fm.get("source", "manual_statement"),
        "source_files": {
            "pdf": fm.get("source_file", f"{statement_id}.pdf"),
            "markdown": md_path.name,
        },
        "as_of_date": resolve_as_of_date(fm, md_text, statement_id) or None,
        "run_date": str(fm.get("run_date", "")).strip() or _body_date(md_text, "Run Date") or None,
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
