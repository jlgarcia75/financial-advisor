#!/usr/bin/env python3
"""One-command ingest for ChatGPT linked-account exports.

You still export the linked CSVs from ChatGPT by hand (see
docs/linked-account-export.md) — there is no supported API to pull them
automatically. This script automates everything *after* that: it validates the
linked CSVs against schemas/linked, then runs the full downstream chain so the
combined view is up to date:

    validate -> build_advisor_inputs -> reconcile -> build_advisor_inputs
             -> build_finance_dashboard -> create_monthly_review_prompt

Typical use after pasting the CSVs into Reviews/inputs/:

    python3 scripts/ingest_linked_export.py

Or point at wherever you saved them and have them copied into place first:

    python3 scripts/ingest_linked_export.py --source ~/Downloads/linked
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
PY = sys.executable

sys.path.insert(0, str(SCRIPTS))
from validate_statement_csvs import (  # noqa: E402
    _dataset_from_name,
    load_schema,
    validate_csv,
)

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance")
DEFAULT_INPUTS_DIR = VAULT / "Reviews/inputs"
DEFAULT_REVIEWS_DIR = VAULT / "Reviews"
DEFAULT_ACCOUNTS_DIR = VAULT / "Accounts"
DEFAULT_STATEMENTS_DIR = VAULT / "Statements"

LINKED_FILES = ("linked_accounts.csv", "linked_holdings.csv", "linked_transactions.csv")


def run(args: list, label: str) -> None:
    print(f"\n=== {label} ===")
    proc = subprocess.run([PY, *map(str, args)])
    if proc.returncode != 0:
        print(f"FAILED: {label} (exit {proc.returncode})", file=sys.stderr)
        raise SystemExit(proc.returncode)


def copy_from_source(source: Path, inputs_dir: Path) -> None:
    copied = []
    for name in LINKED_FILES:
        src = source / name
        if src.exists():
            inputs_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, inputs_dir / name)
            copied.append(name)
    if not copied:
        print(f"No linked_*.csv found in {source}", file=sys.stderr)
        raise SystemExit(2)
    print(f"Copied {len(copied)} file(s) from {source}: {', '.join(copied)}")


def validate_linked(inputs_dir: Path) -> list[Path]:
    present = [inputs_dir / n for n in LINKED_FILES if (inputs_dir / n).exists()]
    if not (inputs_dir / "linked_accounts.csv").exists():
        print(
            f"Missing {inputs_dir / 'linked_accounts.csv'}.\n"
            "Export it from ChatGPT first — see docs/linked-account-export.md.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    print("=== validate linked CSVs ===")
    errors = []
    for path in present:
        dataset = _dataset_from_name(path.stem)
        if not dataset:
            print(f"  skip (unknown dataset): {path.name}")
            continue
        schema = load_schema("linked", dataset, schema_dir="linked")
        file_errors = validate_csv(path, schema)
        errors.extend(file_errors)
        print(f"  {path.name}: {'OK' if not file_errors else str(len(file_errors)) + ' error(s)'}")
    if errors:
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print("Validation failed; not proceeding.", file=sys.stderr)
        raise SystemExit(1)
    return present


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate + ingest linked-account CSVs and rebuild the combined view.")
    parser.add_argument("--source", type=Path, help="Copy linked_*.csv from here into --inputs-dir first.")
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--accounts-dir", type=Path, default=DEFAULT_ACCOUNTS_DIR)
    parser.add_argument("--statements-dir", type=Path, default=DEFAULT_STATEMENTS_DIR)
    parser.add_argument("--period", help="YYYY-MM passed to reconcile/review (default: latest).")
    args = parser.parse_args()

    if args.source:
        copy_from_source(args.source, args.inputs_dir)

    validate_linked(args.inputs_dir)

    recon_out = args.reviews_dir / "reconciliation"
    period_args = ["--period", args.period] if args.period else []

    # Masters must exist/be current before reconcile reads them.
    run([SCRIPTS / "build_advisor_inputs.py", "--statements-dir", args.statements_dir,
         "--output-dir", args.inputs_dir], "build advisor inputs")
    run([SCRIPTS / "reconcile_manual_vs_linked.py", "--manual-dir", args.inputs_dir,
         "--linked-dir", args.inputs_dir, "--output-dir", recon_out,
         "--reviews-dir", args.reviews_dir, *period_args], "reconcile manual vs linked")
    # Re-run so advisor_inputs_manifest.json picks up manual_linked_reconciliation.csv.
    run([SCRIPTS / "build_advisor_inputs.py", "--statements-dir", args.statements_dir,
         "--output-dir", args.inputs_dir], "refresh advisor inputs manifest")
    run([SCRIPTS / "build_finance_dashboard.py", "--inputs-dir", args.inputs_dir,
         "--reviews-dir", args.reviews_dir, "--accounts-dir", args.accounts_dir,
         *period_args], "build dashboard")
    run([SCRIPTS / "create_monthly_review_prompt.py", "--inputs-dir", args.inputs_dir,
         "--reviews-dir", args.reviews_dir, *period_args], "create monthly review prompt")

    print(f"\nDone. Combined view refreshed under {args.reviews_dir}")
    print("Review reconciliation before trusting totals: "
          f"{args.reviews_dir}/<period>_reconciliation_review.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
