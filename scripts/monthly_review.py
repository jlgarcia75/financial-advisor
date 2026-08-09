#!/usr/bin/env python3
"""One command for the monthly review.

Processes new statements, rebuilds the combined view (reconcile -> dashboard ->
monthly review prompt -> advisor briefing/bundle), then archives superseded
prior-month artifacts. Prints the review prompt to paste.

Usage:
    python3 scripts/monthly_review.py                # CSVs already in Reviews/inputs/
    python3 scripts/monthly_review.py --source <dir> # only if you saved the CSVs elsewhere
    python3 scripts/monthly_review.py --no-archive   # skip the archive step

Statement processing runs finance_statements.zsh (which resolves its own venv
interpreter); the remaining steps are stdlib-only Python and run under this same
interpreter.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance")
REVIEWS_DIR = VAULT / "Reviews"


def run(cmd: list[str], label: str) -> None:
    print(f"[monthly_review] {label}")
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full monthly review (statements -> combined view -> archive).")
    parser.add_argument("--source", help="Copy linked_*.csv from here into Reviews/inputs/ first "
                                         "(only if you saved them somewhere other than Reviews/inputs/).")
    parser.add_argument("--no-archive", action="store_true", help="Skip the archive step.")
    args = parser.parse_args()

    py = sys.executable
    run(["zsh", str(SCRIPTS / "finance_statements.zsh")], "Step 1/3 — process new/ready statements")

    ingest = [py, str(SCRIPTS / "ingest_linked_export.py")]
    if args.source:
        ingest += ["--source", args.source]
    run(ingest, "Step 2/3 — rebuild combined view (reconcile, dashboard, review prompt, briefing)")

    if args.no_archive:
        print("[monthly_review] Step 3/3 — skipped (--no-archive)")
    else:
        run([py, str(SCRIPTS / "archive_month.py")], "Step 3/3 — archive superseded prior-month artifacts")

    print("[monthly_review] Done.")
    prompts = sorted(REVIEWS_DIR.glob("*_monthly_review_prompt.md"))
    if prompts:
        print(f"\n  ▶ Paste into ChatGPT:  {prompts[-1]}")
        print(f"  ▶ Upload bundle:       {REVIEWS_DIR / 'advisor_bundle'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
