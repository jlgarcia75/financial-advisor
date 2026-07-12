#!/usr/bin/env python3
"""End-to-end smoke test for the finance pipeline, using self-generated synthetic
data (no real financial data, no external fixtures). Exercises the behaviors that
have broken before:

  * multi-month point-in-time net worth (balances not summed across months)
  * masters retain full history
  * reconciliation flags an exact-duplicate account and a linked-only account
  * dashboard tax/owner breakdowns from account notes
  * data-quality gate passes on clean data

Runs each script as a subprocess with explicit --dirs so nothing touches a real
vault. Exits non-zero with context on the first failure.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
PY = sys.executable

# Two months so point-in-time can be distinguished from a naive sum.
# ACC1 = Roth (tax_free, owner Alice); ACC2 = Trust (taxable, owner joint).
DEC = {"ACC1": 100.0, "ACC2": 400.0}      # latest -> net worth should equal 500
NOV = {"ACC1": 90.0, "ACC2": 360.0}       # older -> must NOT be added in
ACCOUNTS = {
    "ACC1": ("Test Roth IRA", "roth_ira", "tax_free", "Alice"),
    "ACC2": ("Test Trust", "trust", "taxable", "joint"),
}


def run(args, **kw):
    proc = subprocess.run([PY, *map(str, args)], capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        print("COMMAND FAILED:", " ".join(map(str, args)), file=sys.stderr)
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(1)
    return proc


def write_csv(path: Path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def make_statement(statements: Path, period: str, totals: dict):
    base = f"{period}_test-brokerage-0000_statement"
    write_csv(statements / f"{base}_accounts.csv", [
        {"statement_id": base, "account_id": a, "account_name": ACCOUNTS[a][0],
         "account_type": ACCOUNTS[a][1], "total_account": totals[a]}
        for a in ACCOUNTS
    ])
    # Holdings foot exactly to the account totals (Equity 60% / Cash 40%).
    write_csv(statements / f"{base}_holdings.csv", [
        r for a in ACCOUNTS for r in (
            {"statement_id": base, "account_id": a, "account_name": ACCOUNTS[a][0],
             "account_type": ACCOUNTS[a][1], "asset_class": "Equity", "security_name": "Fund A",
             "symbol": "FNDA", "market_value": round(totals[a] * 0.6, 2)},
            {"statement_id": base, "account_id": a, "account_name": ACCOUNTS[a][0],
             "account_type": ACCOUNTS[a][1], "asset_class": "Cash and Cash Equivalents",
             "security_name": "Cash", "symbol": "USD", "market_value": round(totals[a] * 0.4, 2)},
        )
    ])
    write_csv(statements / f"{base}_transactions.csv", [
        {"statement_id": base, "account_id": "ACC1", "account_name": ACCOUNTS["ACC1"][0],
         "date": f"{period}-05", "amount": 10.0, "cash_flow_direction": "inflow"},
        {"statement_id": base, "account_id": "ACC2", "account_name": ACCOUNTS["ACC2"][0],
         "date": f"{period}-06", "amount": 5.0, "cash_flow_direction": "outflow"},
    ])
    write_csv(statements / f"{base}_activity.csv", [
        {"statement_id": base, "metric": "Ending Value",
         "reporting_month_or_quarter_to_date": sum(totals.values()), "year_to_date": ""},
    ])
    (statements / f"{base}.json").write_text(json.dumps({
        "schema_version": "1.0", "statement_id": base, "institution": "test",
        "statement_type": "multi_account_brokerage", "as_of_date": f"{period}-28",
        "review_status": "ready",
        "datasets": {ds: f"{base}_{ds}.csv" for ds in ("accounts", "holdings", "transactions", "activity")},
    }))


def write_notes(accounts: Path):
    for aid, (name, atype, tax, owner) in ACCOUNTS.items():
        (accounts / f"{aid}.md").write_text(
            f"---\ntype: financial_account\naccount_id: {aid}\ninstitution: test\n"
            f"account_name: {name}\naccount_type: {atype}\ntax_treatment: {tax}\n"
            f"source_priority: manual_statement\ninclude_in_networth: true\nowner: {owner}\n"
            f"status: active\n---\n\n# {name}\n"
        )


def check(cond, msg):
    if not cond:
        print(f"ASSERTION FAILED: {msg}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  ok: {msg}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        statements = root / "statements"; inputs = root / "inputs"
        reviews = root / "reviews"; accounts = root / "accounts"; linked = root / "linked"
        for d in (statements, inputs, reviews, accounts, linked):
            d.mkdir(parents=True)

        make_statement(statements, "2025-11", NOV)
        make_statement(statements, "2025-12", DEC)
        write_notes(accounts)

        print("[1] build_advisor_inputs")
        run([SCRIPTS / "build_advisor_inputs.py", "--statements-dir", statements, "--output-dir", inputs])
        acct_rows = list(csv.DictReader((inputs / "manual_statements_master_accounts.csv").open()))
        check(len(acct_rows) == 4, f"masters keep full history (4 account rows, got {len(acct_rows)})")
        check((inputs / "advisor_inputs_manifest.json").exists(), "advisor_inputs_manifest.json written")

        print("[2] build_finance_dashboard (point-in-time + breakdowns)")
        run([SCRIPTS / "build_finance_dashboard.py", "--inputs-dir", inputs,
             "--reviews-dir", reviews, "--accounts-dir", accounts])
        snap = list(csv.DictReader((reviews / "NET_WORTH_snapshot.csv").open()))
        included = [r for r in snap if r["included_in_networth"] == "True"]
        nw = round(sum(float(r["current_value"]) for r in included), 2)
        check(nw == 500.0, f"net worth is point-in-time Dec total 500.00 (not summed with Nov); got {nw}")
        bd = {(r["dimension"], r["key"]): float(r["value"])
              for r in csv.DictReader((reviews / "networth_breakdown.csv").open())}
        check(bd.get(("tax_treatment", "tax_free")) == 100.0, "by-tax: tax_free = 100.00")
        check(bd.get(("tax_treatment", "taxable")) == 400.0, "by-tax: taxable = 400.00")
        check(bd.get(("owner", "joint")) == 400.0, "by-owner: joint = 400.00")
        dash = (reviews / "2025-12_dashboard.md").read_text()
        check("Net worth by tax treatment" in dash and "Net worth by owner" in dash,
              "dashboard has tax + owner breakdown sections")
        cf = list(csv.DictReader((reviews / "cash_flow_summary.csv").open()))
        check({r["period"] for r in cf} == {"2025-11", "2025-12"}, "cash flow spans both months")

        print("[3] reconcile (duplicate + linked-only)")
        write_csv(linked / "linked_accounts.csv", [
            {"account_id": "ACC1", "account_name": "Test Roth IRA", "institution": "test",
             "account_type": "roth_ira", "account_last4": "0001", "current_value": 100.0,
             "as_of_date": "2025-12-28", "source": "linked"},
            {"account_id": "LINK2", "account_name": "Outside Checking", "institution": "bank",
             "account_type": "checking", "account_last4": "9999", "current_value": 50.0,
             "as_of_date": "2025-12-28", "source": "linked"},
        ])
        run([SCRIPTS / "validate_statement_csvs.py", "--linked", linked / "linked_accounts.csv"])
        run([SCRIPTS / "reconcile_manual_vs_linked.py", "--manual-dir", inputs,
             "--linked-dir", linked, "--output-dir", root / "recon", "--reviews-dir", reviews])
        recon = {r["manual_account_id"] or r["linked_account_id"]: r["status"]
                 for r in csv.DictReader((inputs / "manual_linked_reconciliation.csv").open())}
        check(recon.get("ACC1") == "probable_duplicate", f"ACC1 flagged probable_duplicate (got {recon.get('ACC1')})")
        check(recon.get("LINK2") == "linked_only", f"LINK2 flagged linked_only (got {recon.get('LINK2')})")

        print("[4] create_monthly_review_prompt")
        run([SCRIPTS / "create_monthly_review_prompt.py", "--inputs-dir", inputs, "--reviews-dir", reviews])
        check((reviews / "2025-12_monthly_review_prompt.md").exists(), "monthly review prompt written")

        print("[5] check_finance_data_quality (must pass, exit 0)")
        run([SCRIPTS / "check_finance_data_quality.py", "--statements-dir", statements,
             "--inputs-dir", inputs, "--reviews-dir", reviews])
        report = (reviews / "data_quality_report.md").read_text()
        check("Errors: **0**" in report, "data-quality report has 0 errors")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
