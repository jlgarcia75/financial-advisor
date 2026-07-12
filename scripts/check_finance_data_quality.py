#!/usr/bin/env python3
"""Automated data-quality checks for the finance pipeline.

Runs the checklist from the architecture doc across statement manifests, their
CSVs, and the consolidated masters. Writes a Markdown report and exits non-zero
when a hard error is found, so it can gate the pipeline before advisor inputs are
rebuilt.

Severity:
  error   — breaks trust in the numbers (missing key ids, non-numeric values,
            broken manifest -> CSV links). Non-zero exit.
  warning — worth a look but not fatal (missing dates, negative values, totals
            that don't foot, duplicate rows, ready MD without a manifest).
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import (  # noqa: E402
    first_value,
    parse_frontmatter,
    parse_number,
    read_csv,
    read_json,
)

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain")
DEFAULT_STATEMENTS_DIR = VAULT / "91_finance/Statements"
DEFAULT_INPUTS_DIR = VAULT / "91_finance/Reviews/inputs"
DEFAULT_REVIEWS_DIR = VAULT / "91_finance/Reviews"

ACCOUNT_ID_FIELDS = ("account_id",)
VALUE_FIELDS = ("market_value", "current_value", "total_account", "value")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def check_manifests(statements_dir: Path, report: Report) -> None:
    manifests = sorted(statements_dir.glob("*_statement.json"))
    ready_mds = {
        p.with_suffix("").name
        for p in statements_dir.glob("*_statement.md")
        if parse_frontmatter(p).get("status") == "ready"
        or parse_frontmatter(p).get("review_status") == "ready"
    }
    manifest_bases = set()

    for path in manifests:
        try:
            manifest = read_json(path)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{path.name}: unreadable manifest ({exc})")
            continue
        manifest_bases.add(path.with_suffix("").name)
        if not manifest.get("as_of_date"):
            report.warn(f"{path.name}: missing as_of_date")
        datasets = manifest.get("datasets", {})
        if not datasets:
            report.error(f"{path.name}: manifest has no datasets")
        for name, filename in datasets.items():
            if not (path.parent / filename).exists():
                report.error(f"{path.name}: dataset '{name}' points to missing file {filename}")

    for base in sorted(ready_mds - manifest_bases):
        report.warn(f"{base}.md is ready but has no manifest")


def check_csv_rows(path: Path, report: Report, require_account_id: bool = True) -> None:
    rows = read_csv(path)
    if not rows:
        return
    seen = Counter()
    for i, row in enumerate(rows, start=2):
        if not first_value(row, ("statement_id",)) and "statement_id" in row:
            report.error(f"{path.name}: row {i} missing statement_id")
        if require_account_id and "account_id" in row and not first_value(row, ACCOUNT_ID_FIELDS):
            report.error(f"{path.name}: row {i} missing account_id")
        for field in VALUE_FIELDS:
            if field in row and str(row[field]).strip():
                num = parse_number(row[field])
                if num is None:
                    report.error(f"{path.name}: row {i} non-numeric {field}={row[field]!r}")
                elif num < 0 and field in ("market_value", "total_account"):
                    report.warn(f"{path.name}: row {i} negative {field}={num}")
        seen[tuple(sorted(row.items()))] += 1
    dupes = sum(c - 1 for c in seen.values() if c > 1)
    if dupes:
        report.warn(f"{path.name}: {dupes} exact-duplicate row(s)")


def check_holdings_foot(inputs_dir: Path, report: Report) -> None:
    """Per-account holdings market value should be close to the account total."""
    accounts = read_csv(inputs_dir / "manual_statements_master_accounts.csv")
    holdings = read_csv(inputs_dir / "manual_statements_master_holdings.csv")
    if not accounts or not holdings:
        return
    holding_totals: dict[str, float] = {}
    for h in holdings:
        acct = first_value(h, ACCOUNT_ID_FIELDS)
        holding_totals[acct] = holding_totals.get(acct, 0.0) + (parse_number(first_value(h, ("market_value",))) or 0.0)
    for a in accounts:
        acct = first_value(a, ACCOUNT_ID_FIELDS)
        total = parse_number(first_value(a, ("total_account", "current_value")))
        if acct in holding_totals and total is not None:
            diff = abs(holding_totals[acct] - total)
            if diff > max(1.0, total * 0.01):
                report.warn(f"account {acct}: holdings sum {holding_totals[acct]:.2f} "
                            f"!= account total {total:.2f} (diff {diff:.2f})")


def write_report(path: Path, report: Report) -> None:
    lines = ["# Finance Data Quality Report", ""]
    lines.append(f"- Errors: **{len(report.errors)}**")
    lines.append(f"- Warnings: **{len(report.warnings)}**")
    lines.append("")
    if report.errors:
        lines += ["## Errors", ""] + [f"- {e}" for e in report.errors] + [""]
    if report.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in report.warnings] + [""]
    if not report.errors and not report.warnings:
        lines.append("All checks passed. ✅")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run finance data-quality checks.")
    parser.add_argument("--statements-dir", type=Path, default=DEFAULT_STATEMENTS_DIR)
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--report", type=Path, help="Report path (default: <reviews-dir>/data_quality_report.md).")
    args = parser.parse_args()

    report = Report()
    if args.statements_dir.exists():
        check_manifests(args.statements_dir, report)
    for name in ("accounts", "holdings", "transactions", "activity"):
        check_csv_rows(args.inputs_dir / f"manual_statements_master_{name}.csv", report,
                       require_account_id=name in ("holdings", "transactions"))
    for name in ("linked_accounts", "linked_holdings", "linked_transactions"):
        check_csv_rows(args.inputs_dir / f"{name}.csv", report, require_account_id=False)
    check_holdings_foot(args.inputs_dir, report)

    report_path = args.report or (args.reviews_dir / "data_quality_report.md")
    write_report(report_path, report)
    print(f"Wrote {report_path} — {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
