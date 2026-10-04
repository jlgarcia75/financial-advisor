#!/usr/bin/env python3
"""One command for the monthly review.

Thin wrapper over finance_statements.zsh, which now runs the whole chain: process
any new statements (no manual "status: ready" step), rebuild the combined view
(reconcile -> dashboard -> monthly review prompt -> advisor briefing/bundle), and
archive superseded prior-month artifacts. `--rebuild` forces that rebuild even when
no new statement was dropped (e.g. you only refreshed the linked export).

Usage:
    python3 scripts/monthly_review.py                # CSVs already in Reviews/inputs/
    python3 scripts/monthly_review.py --source <dir> # only if you saved the CSVs elsewhere
    python3 scripts/monthly_review.py --no-archive   # skip the archive step

The same chain also runs automatically whenever a statement lands in Statements/
(via the finance_statements LaunchAgent) — this command is for an on-demand refresh,
especially after a fresh linked export.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full monthly review on demand.")
    parser.add_argument("--source", help="Copy linked_*.csv from here into Reviews/inputs/ first "
                                         "(only if you saved them somewhere other than Reviews/inputs/).")
    parser.add_argument("--no-archive", action="store_true", help="Skip the archive step.")
    args = parser.parse_args()

    cmd = ["zsh", str(SCRIPTS / "finance_statements.zsh"), "--rebuild"]
    if args.source:
        cmd += ["--source", args.source]
    if args.no_archive:
        cmd += ["--no-archive"]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
