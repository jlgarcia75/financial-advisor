#!/usr/bin/env python3
"""Archive processed statements out of the active Statements inbox.

Once a statement has been extracted and its rows folded into the consolidated
masters, its raw files (PDF, Markdown, manifest, CSVs) can be moved into
Statements/Archive/<period>/ to keep the inbox clean. This is purely
organizational: build_advisor_inputs.py scans Statements/ recursively, so
archived statements still contribute to the masters and the dashboard's
history — nothing is dropped from the numbers.

Only statements that have a manifest with review_status: ready are archived,
so an unreviewed statement is never moved out from under you.

Examples:
  # Preview what would be archived (all processed statements)
  python3 scripts/archive_statements.py --all --dry-run

  # Archive everything already processed
  python3 scripts/archive_statements.py --all

  # Archive one statement by id
  python3 scripts/archive_statements.py --statement 2026-01_empower-garciatrust-1234_statement
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import read_json  # noqa: E402

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain")
DEFAULT_STATEMENTS_DIR = VAULT / "91_finance/Statements"
ARCHIVE_DIRNAME = "Archive"


def statement_period(manifest: dict, statement_id: str) -> str:
    as_of = str(manifest.get("as_of_date", "")).strip()
    if len(as_of) >= 7:
        return as_of[:7]
    return statement_id[:7] if statement_id[:7].count("-") == 1 else "undated"


def statement_files(statements_dir: Path, base: str) -> list[Path]:
    """All files belonging to one statement: <base>.{pdf,md,json} and <base>_*.csv."""
    files = []
    for suffix in (".pdf", ".md", ".json"):
        p = statements_dir / f"{base}{suffix}"
        if p.exists():
            files.append(p)
    files += sorted(statements_dir.glob(f"{base}_*.csv"))
    return files


def active_manifests(statements_dir: Path) -> list[Path]:
    """Top-level (non-archived) manifests only."""
    return sorted(statements_dir.glob("*_statement.json"))


def archive_one(manifest_path: Path, statements_dir: Path, archive_root: Path,
                dry_run: bool) -> bool:
    try:
        manifest = read_json(manifest_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Skipping {manifest_path.name}: unreadable manifest ({exc})", file=sys.stderr)
        return False
    if manifest.get("review_status") != "ready":
        print(f"Skipping {manifest_path.name}: not ready")
        return False

    base = manifest_path.with_suffix("").name
    statement_id = manifest.get("statement_id", base)
    period = statement_period(manifest, statement_id)
    dest = archive_root / period
    files = statement_files(statements_dir, base)

    if not files:
        print(f"Skipping {base}: no files found")
        return False

    action = "Would move" if dry_run else "Moving"
    print(f"{action} {len(files)} file(s) for {statement_id} -> {dest}")
    if dry_run:
        for f in files:
            print(f"    {f.name}")
        return True

    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        target = dest / f.name
        if target.exists():
            print(f"    exists, skipping: {target}", file=sys.stderr)
            continue
        shutil.move(str(f), str(target))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive processed statements out of the inbox.")
    parser.add_argument("--statements-dir", type=Path, default=DEFAULT_STATEMENTS_DIR)
    parser.add_argument("--archive-dir", type=Path,
                        help=f"Archive root (default: <statements-dir>/{ARCHIVE_DIRNAME}).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Archive every processed (ready) statement.")
    group.add_argument("--statement", help="Archive a single statement by id/base name.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would move without moving.")
    args = parser.parse_args()

    statements_dir = args.statements_dir
    archive_root = args.archive_dir or (statements_dir / ARCHIVE_DIRNAME)
    if not statements_dir.exists():
        print(f"Statements dir not found: {statements_dir}", file=sys.stderr)
        return 2

    if args.statement:
        manifest_path = statements_dir / f"{args.statement}.json"
        if not manifest_path.exists():
            print(f"No manifest for {args.statement} in {statements_dir}", file=sys.stderr)
            return 2
        targets = [manifest_path]
    else:
        targets = active_manifests(statements_dir)
        if not targets:
            print("No processed statements to archive.")
            return 0

    archived = sum(archive_one(m, statements_dir, archive_root, args.dry_run) for m in targets)
    verb = "would be archived" if args.dry_run else "archived"
    print(f"{archived} statement(s) {verb}.")
    if archived and not args.dry_run:
        print("Masters still include archived data (build_advisor_inputs scans recursively).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
