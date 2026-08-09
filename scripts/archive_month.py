#!/usr/bin/env python3
"""Archive superseded finance artifacts so the active folders show only the latest of each.

A dated file (name prefixed `YYYY-MM_`) is archived only when a newer-month file of the same
kind exists — e.g. `2026-06_dashboard.md` once `2026-07_dashboard.md` is present, or June's
statement once July's is ingested. The latest of every kind is always kept, so this is safe to
run before or after generating the current month's review and never hides a still-current file.

Superseded statements move to `Statements/Archive/YYYY-MM/` and dated Reviews outputs to
`Reviews/Archive/YYYY-MM/`. Archived statements remain in the masters because build_advisor_inputs
reads Statements recursively (rglob), so no cash-flow history is lost. Rolling-latest files
(NET_WORTH_snapshot, ADVISOR_BRIEFING, the year-based tax prompt, inputs/, advisor_bundle/) have
no YYYY-MM prefix and are never touched. `--dry-run` prints the moves without changing anything.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance")
DEFAULT_STATEMENTS_DIR = VAULT / "Statements"
DEFAULT_REVIEWS_DIR = VAULT / "Reviews"
ARCHIVE_DIRNAME = "Archive"
MONTH_PREFIX = re.compile(r"^(\d{4}-\d{2})[_-]")


def month_of(name: str) -> str | None:
    m = MONTH_PREFIX.match(name)
    return m.group(1) if m else None


def kind_of(name: str) -> str:
    """The file's identity without its month — e.g. 'dashboard.md' or
    'empower-garciatrust-1234_statement_holdings.csv'. Files of the same kind across
    months supersede one another."""
    return MONTH_PREFIX.sub("", name)


def dated_files(directory: Path) -> list[Path]:
    """Files directly in `directory` (not subfolders) carrying a YYYY-MM prefix."""
    if not directory.exists():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and month_of(p.name))


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive superseded prior-month statement + review artifacts.")
    parser.add_argument("--statements-dir", type=Path, default=DEFAULT_STATEMENTS_DIR)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Print the moves; change nothing.")
    args = parser.parse_args()

    # (path, month, kind) tagged with the archive root the file belongs under.
    entries: list[tuple[Path, str, tuple[Path, str]]] = []
    for base in (args.statements_dir, args.reviews_dir):
        for p in dated_files(base):
            entries.append((p, month_of(p.name), (base, kind_of(p.name))))

    if not entries:
        print("No dated artifacts found; nothing to archive.")
        return 0

    latest: dict[tuple[Path, str], str] = {}
    for _, month, key in entries:
        latest[key] = max(month, latest.get(key, month))

    plan = [(p, key[0] / ARCHIVE_DIRNAME / month / p.name)
            for p, month, key in entries if month < latest[key]]
    if not plan:
        print("Every artifact is the latest of its kind; nothing to archive.")
        return 0

    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(VAULT))
        except ValueError:
            return str(p)

    for src, dest in sorted(plan):
        print(f"{'[dry-run] ' if args.dry_run else ''}{rel(src)} -> {rel(dest)}")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))

    months = ", ".join(sorted({month_of(s.name) for s, _ in plan}))
    print(f"{'Would archive' if args.dry_run else 'Archived'} {len(plan)} superseded file(s) from {months}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
