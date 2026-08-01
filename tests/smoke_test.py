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
import shutil
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
        statements = root / "statements"
        inputs = root / "inputs"
        reviews = root / "reviews"
        accounts = root / "accounts"
        linked = root / "linked"
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
        # Linked holdings arrive with no asset_class column; the dashboard must
        # classify them deterministically so none land in "Unclassified".
        write_csv(inputs / "linked_holdings.csv", [
            {"account_id": "LINK4", "account_name": "Employer 401k", "institution": "fidelity",
             "symbol": "SCHZ", "security_name": "Schwab US Aggregate Bond ETF",
             "market_value": 120.0, "as_of_date": "2025-12-28", "source": "linked"},
            {"account_id": "LINK4", "account_name": "Employer 401k", "institution": "fidelity",
             "symbol": "SPAXX", "security_name": "Fidelity Government Money Market Fund",
             "market_value": 80.0, "as_of_date": "2025-12-28", "source": "linked"},
            {"account_id": "LINK4", "account_name": "Employer 401k", "institution": "fidelity",
             "symbol": "VOO", "security_name": "Vanguard S&P 500 ETF",
             "market_value": 200.0, "as_of_date": "2025-12-28", "source": "linked"},
        ])
        run([SCRIPTS / "build_finance_dashboard.py", "--inputs-dir", inputs,
             "--reviews-dir", reviews, "--accounts-dir", accounts])
        alloc = {(r["dimension"], r["key"]): float(r["market_value"])
                 for r in csv.DictReader((reviews / "allocation_summary.csv").open())}
        check(("asset_class", "Unclassified") not in alloc,
              "no Unclassified asset class (linked holdings inferred from symbol/name)")
        check(alloc.get(("asset_class", "Fixed Income")) == 120.0,
              "linked bond ETF inferred as Fixed Income")
        check(alloc.get(("asset_class", "Cash and Cash Equivalents")) == 80.0 + (500.0 * 0.4),
              "linked money-market inferred as Cash, added to manual cash")
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
        # Two non-matching linked accounts (LINK2, LINK3) tie at score 0 for each
        # manual account — this reproduces the dict-comparison crash if match_accounts
        # ever sorts by the raw rows again.
        write_csv(linked / "linked_accounts.csv", [
            {"account_id": "ACC1", "account_name": "Test Roth IRA", "institution": "test",
             "account_type": "roth_ira", "account_last4": "0001", "current_value": 100.0,
             "as_of_date": "2025-12-28", "source": "linked"},
            {"account_id": "LINK2", "account_name": "Outside Checking", "institution": "bank",
             "account_type": "checking", "account_last4": "9999", "current_value": 50.0,
             "as_of_date": "2025-12-28", "source": "linked"},
            {"account_id": "LINK3", "account_name": "Outside Savings", "institution": "bank",
             "account_type": "savings", "account_last4": "8888", "current_value": 75.0,
             "as_of_date": "2025-12-28", "source": "linked"},
            {"account_id": "LINK4", "account_name": "Employer 401k", "institution": "fidelity",
             "account_type": "401k", "account_last4": "7777", "current_value": 200.0,
             "as_of_date": "2025-12-28", "source": "linked"},
        ])
        run([SCRIPTS / "validate_statement_csvs.py", "--linked", linked / "linked_accounts.csv"])
        run([SCRIPTS / "reconcile_manual_vs_linked.py", "--manual-dir", inputs,
             "--linked-dir", linked, "--output-dir", root / "recon", "--reviews-dir", reviews])
        recon = {r["manual_account_id"] or r["linked_account_id"]: r["status"]
                 for r in csv.DictReader((inputs / "manual_linked_reconciliation.csv").open())}
        check(recon.get("ACC1") == "probable_duplicate", f"ACC1 flagged probable_duplicate (got {recon.get('ACC1')})")
        check(recon.get("LINK2") == "linked_only", f"LINK2 flagged linked_only (got {recon.get('LINK2')})")
        check(recon.get("LINK3") == "linked_only", f"LINK3 flagged linked_only (got {recon.get('LINK3')})")
        check(recon.get("LINK4") == "linked_only", f"LINK4 flagged linked_only (got {recon.get('LINK4')})")

        print("[4] create_monthly_review_prompt")
        run([SCRIPTS / "create_monthly_review_prompt.py", "--inputs-dir", inputs, "--reviews-dir", reviews])
        check((reviews / "2025-12_monthly_review_prompt.md").exists(), "monthly review prompt written")

        print("[5] check_finance_data_quality (must pass, exit 0)")
        run([SCRIPTS / "check_finance_data_quality.py", "--statements-dir", statements,
             "--inputs-dir", inputs, "--reviews-dir", reviews])
        report = (reviews / "data_quality_report.md").read_text()
        check("Errors: **0**" in report, "data-quality report has 0 errors")

        print("[6] ingest_linked_export (one-command orchestration)")
        (inputs / "manual_linked_reconciliation.csv").unlink()  # prove ingest regenerates it
        run([SCRIPTS / "ingest_linked_export.py", "--source", linked, "--inputs-dir", inputs,
             "--reviews-dir", reviews, "--accounts-dir", accounts, "--statements-dir", statements])
        check((inputs / "manual_linked_reconciliation.csv").exists(),
              "ingest regenerated manual_linked_reconciliation.csv")
        check((reviews / "2025-12_dashboard.md").exists(), "ingest rebuilt the dashboard")

        print("[7] create_tax_strategy_prompt (data-grounded tax prompt)")
        tax_profile = root / "tax_profile.md"
        tax_profile.write_text(
            "---\ntype: tax_profile\ntax_year: 2025\nfiling_status: married_filing_jointly\n"
            "state: CA\ntaxpayers: \"Alice\"\n---\n\n# profile\n"
        )
        returns_dir = root / "tax_returns"
        returns_dir.mkdir()
        (returns_dir / "2024_return.md").write_text("redacted return\n")
        write_csv(returns_dir / "tax_returns_summary.csv", [
            {"tax_year": "2024", "agi": "300000", "taxable_income": "270000",
             "total_tax": "45000", "effective_rate": "16.7%", "net_lt_cap_gain": "5000",
             "qualified_dividends": "3000", "niit": "1200", "source_doc": "2024_return.md"},
        ])
        equity_dir = root / "equity_comp"
        equity_dir.mkdir()
        # One vested tranche (must be ignored) + two future unvested tranches; AAPL
        # priced via --rsu-price override, INTC priced from the row.
        write_csv(equity_dir / "rsu_vesting.csv", [
            {"symbol": "INTC", "grant_id": "G2", "grant_date": "2023-05-01", "vest_date": "2025-05-01",
             "shares": "500", "status": "vested", "price_per_share": "45.00", "source": "etrade", "notes": ""},
            {"symbol": "INTC", "grant_id": "G1", "grant_date": "2024-11-15", "vest_date": "2026-11-15",
             "shares": "1000", "status": "unvested", "price_per_share": "100.00", "source": "etrade", "notes": ""},
            {"symbol": "AAPL", "grant_id": "G3", "grant_date": "2025-02-01", "vest_date": "2027-08-01",
             "shares": "50", "status": "unvested", "price_per_share": "", "source": "etrade", "notes": ""},
        ])
        run([SCRIPTS / "create_tax_strategy_prompt.py", "--inputs-dir", inputs,
             "--reviews-dir", reviews, "--tax-profile", tax_profile, "--returns-dir", returns_dir,
             "--equity-comp-dir", equity_dir, "--rsu-price", "AAPL=200"])
        tax_prompt = reviews / "2025_tax_strategy_prompt.md"
        check(tax_prompt.exists(), "tax strategy prompt written")
        text = tax_prompt.read_text()
        check("2024_return.md" in text and "$45,000.00" in text,
              "prior-year returns section lists the doc and its total tax")
        check("tax-free $100.00" in text, "tax prompt embeds net worth by tax treatment [DATA]")
        check("married_filing_jointly" in text, "tax prompt pulls filing status from profile")
        check("NOT AVAILABLE" in text, "tax prompt flags missing cost basis instead of fabricating")
        check("tax-deferred $200.00" in text,
              "note-less 401k inferred as tax_deferred (not left unspecified)")
        check("EQUITY COMPENSATION — RSUs" in text and "| 2026 | INTC | 1,000 | $100,000.00 |" in text,
              "RSU section projects future vest income by year (row price)")
        check("| 2027 | AAPL | 50 | $10,000.00 |" in text,
              "RSU --rsu-price override values the unpriced tranche")
        check("| INTC | 500 |" not in text,
              "already-vested RSU tranche excluded from projection")

        print("[8] extract_central_lending (capital-account statement type)")
        cl_md = statements / "2025-02_test-capital_statement.md"
        cl_md.write_text(
            '---\ntype: financial_statement\nstatement_id: "2025-02_test-capital_statement"\n'
            "institution: central-lending\nstatement_type: central-lending-capital-account\n"
            "status: ready\n---\n\n"
            "02/28/2025\nCapital Account Statement\nTest Income Fund\nInvestor: Alice\n"
            "| | Beginning Balance | | $1,000.00 | 0 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| | Ending Balance | | $1,100.00 | $1,100.00 |\n"
            "| Ownership | | 2.5% | Return of capital | $0 |\n"
            "| Total Commitment | | $5,000 | Return on capital | $50 |\n"
            "Contributions to date $1,050.00 Distributions to date $50.00\n"
            "Transactions\n| Date | Transaction Type | Description | Amount |\n"
            "| 02/28/2025 | Distribution | Distribution | $50.00 |\n"
        )
        run([SCRIPTS / "extract_central_lending.py", cl_md, "--out-dir", statements])
        acc = list(csv.DictReader((statements / "2025-02_test-capital_statement_accounts.csv").open()))
        check(len(acc) == 1 and float(acc[0]["ending_balance"]) == 1100.0,
              "capital-account ending balance parsed (1100.00)")
        check(float(acc[0]["ownership_pct"]) == 2.5, "capital-account ownership parsed (2.5%)")
        tx = list(csv.DictReader((statements / "2025-02_test-capital_statement_transactions.csv").open()))
        check(len(tx) == 1 and float(tx[0]["amount"]) == 50.0, "capital-account transaction parsed")
        run([SCRIPTS / "validate_statement_csvs.py", cl_md])
        check(True, "central-lending CSVs validate against schemas/central-lending-capital-account")

        print("[9] import_rsu_grants (grant notice MD -> rsu_vesting.csv)")
        grants = root / "grants"
        grants.mkdir()
        # Flattened MarkItDown layout: labels/values pooled, then the schedule as a
        # block of dates followed by a block of share counts. Total = 300.
        (grants / "intc_20000001_rsu.md").write_text(
            "INTEL CORPORATION\nNOTICE OF GRANT\n\nParticipant Name:\n\nJESUS GARCIA\n\n"
            "Grant Number:\n\nGrant Date:\n\nNumber of RSUs:\n\nVesting Schedule:\n\n"
            "20000001\n\nMay 30, 2023\n\n300 RSUs\n\nVesting Date\n\nRSUs\n\n"
            "February 29, 2024\n\nNovember 30, 2026\n\nMay 30, 2027\n\n"
            "100\n\n100\n\n100\n\nRetirement Vesting Acceleration:\n\nYes\n"
        )
        rsu_csv = grants / "rsu_vesting.csv"
        run([SCRIPTS / "import_rsu_grants.py", grants / "intc_20000001_rsu.md",
             "--csv", rsu_csv, "--today", "2026-07-23"])
        rrows = list(csv.DictReader(rsu_csv.open()))
        check(len(rrows) == 3 and {r["grant_id"] for r in rrows} == {"20000001"},
              "3 tranches imported for the grant (checksum 300 passed)")
        by_date = {r["vest_date"]: r for r in rrows}
        check(by_date["2024-02-29"]["status"] == "vested", "past tranche marked vested")
        check(by_date["2026-11-30"]["status"] == "unvested", "future tranche marked unvested")
        check(by_date["2024-02-29"]["symbol"] == "INTC" and by_date["2024-02-29"]["grant_date"] == "2023-05-30",
              "symbol from filename, grant_date parsed from notice")
        run([SCRIPTS / "import_rsu_grants.py", grants / "intc_20000001_rsu.md",
             "--csv", rsu_csv, "--today", "2026-07-23"])
        check(len(list(csv.DictReader(rsu_csv.open()))) == 3, "re-import is idempotent (no duplicate rows)")

        # Newer Intel template: 'Vesting Date:' colon header, mail-merge %%TAGS%-%,
        # the total inside the schedule region, and a stray page-number line.
        (grants / "intc_20000002_rsu.md").write_text(
            "INTEL CORPORATION\nNOTICE OF GRANT\n\nGrant Number:\n\nGrant Date:\n\n"
            "20000002\n%%OPTION_NUMBER%-%\n\nMarch 1, 2026\n%%OPTION_DATE%-%\n\n"
            "Vesting Schedule:\n\nVesting Date:\n\n300\n%%TOTAL_SHARES_GRANTED,'999,999,999'%-%\n\n"
            "RSUs:\n\nMay 31, 2026\n%%VEST_DATE_PERIOD1,'Month DD, YYYY'%-%\n\n"
            "100\n%%SHARES_PERIOD1,'999,999,999'%-%\n\n1\n\n"
            "November 30, 2026\n%%VEST_DATE_PERIOD2,'Month DD, YYYY'%-%\n\n"
            "100\n%%SHARES_PERIOD2,'999,999,999'%-%\n\n"
            "February 28, 2027\n%%VEST_DATE_PERIOD3,'Month DD, YYYY'%-%\n\n"
            "100\n%%SHARES_PERIOD3,'999,999,999'%-%\n\nRetirement Vesting Acceleration:\n\nYes\n"
        )
        tagged_csv = grants / "rsu_tagged.csv"
        run([SCRIPTS / "import_rsu_grants.py", grants / "intc_20000002_rsu.md",
             "--csv", tagged_csv, "--today", "2026-07-23"])
        trows = {r["vest_date"]: r for r in csv.DictReader(tagged_csv.open())}
        check(len(trows) == 3 and all(int(r["shares"]) == 100 for r in trows.values()),
              "tagged template: 3 tranches parsed, stray page-number ignored (checksum 300)")
        check(trows["2026-05-31"]["status"] == "vested" and trows["2026-11-30"]["status"] == "unvested",
              "tagged template: vested/unvested status correct")
        check(trows["2026-05-31"]["grant_date"] == "2026-03-01",
              "tagged template: grant_date parsed from pre-schedule date")

        print("[10] resolve_statement_type (registry-driven routing)")
        r = run([SCRIPTS / "resolve_statement_type.py", cl_md, "--format", "json"])
        route = json.loads(r.stdout)
        check(route["extractor"] == "extract_central_lending.py"
              and route["schema_dir"] == "central-lending-capital-account"
              and route["institution"] == "central-lending",
              "registry routes the capital-account statement by content")
        emp_md = statements / "2099-01_test-empower_statement.md"
        emp_md.write_text("---\ninstitution: empower\nstatement_type: unknown\n---\n\nEmpower Monthly Report\n")
        check(run([SCRIPTS / "resolve_statement_type.py", emp_md, "--field", "schema_dir"]).stdout.strip() == "empower",
              "registry routes an Empower statement to schemas/empower")
        unknown_md = statements / "2099-02_test-mystery_statement.md"
        unknown_md.write_text("---\ntype: financial_statement\n---\n\nUnrecognized bank e-statement\n")
        rc = subprocess.run([sys.executable, str(SCRIPTS / "resolve_statement_type.py"), str(unknown_md)],
                            capture_output=True, text=True)
        check(rc.returncode == 1, "registry exits non-zero when no statement type matches")
        # Standalone manifest picks institution/statement_type from the registry (no --flags).
        run([SCRIPTS / "create_statement_manifest.py", cl_md, "--overwrite", "--no-stamp"])
        man = json.loads((cl_md.with_suffix(".json")).read_text())
        check(man["institution"] == "central-lending"
              and man["statement_type"] == "central-lending-capital-account",
              "manifest resolves institution/statement_type from the registry without flags")

        print("[11] build_advisor_briefing (briefing + safe upload bundle)")
        # equity_comp/rsu_vesting.csv must live under the finance root for the finance-based
        # bundle entries; step [9] wrote it under grants/, so place a copy at root/equity_comp.
        (root / "equity_comp").mkdir(exist_ok=True)
        shutil.copy(rsu_csv, root / "equity_comp" / "rsu_vesting.csv")
        # A raw return (PII) exists in the fixture vault and must NOT reach the bundle.
        assert (returns_dir / "2024_return.md").exists(), "fixture should have a raw return"
        run([SCRIPTS / "build_advisor_briefing.py", "--finance-dir", root,
             "--reviews-dir", reviews, "--inputs-dir", inputs, "--tax-profile", tax_profile])
        briefing = (reviews / "ADVISOR_BRIEFING.md").read_text()
        bundle = reviews / "advisor_bundle"
        names = {p.name for p in bundle.iterdir()} if bundle.is_dir() else set()
        check({"ADVISOR_BRIEFING.md", "project_instructions.md"} <= names,
              "bundle contains the briefing + project instructions")
        check({"NET_WORTH_snapshot.csv", "tax_returns_summary.csv", "rsu_vesting.csv",
               "manual_statements_master_holdings.csv"} <= names,
              "bundle includes Tier-1 aggregates and Tier-2 masters")
        leaked = [n for n in names if n.endswith(("_return.md", "_statement.md", ".pdf", ".env"))]
        check(not leaked, f"no raw returns/statements/PDFs reach the bundle (leaked: {leaked})")
        check("grantor trust" in briefing.lower() and "§1014" in briefing,
              "briefing carries the corrected grantor-trust guardrail")
        check("Never upload" in briefing and "SSN" in briefing,
              "briefing lists the do-not-upload PII set")
        instructions = (bundle / "project_instructions.md").read_text()
        check("Account coverage" in briefing and "counted **once**" in briefing,
              "briefing states all manual + linked accounts are merged and counted once")
        check("live Plaid" in instructions and "count a linked account twice" in instructions,
              "instructions warn against double-counting live Plaid against the snapshot")

        print("[12] import_unrealized_gl + cost basis in tax prompt & bundle")
        sys.path.insert(0, str(SCRIPTS))
        import import_unrealized_gl as ugl
        header = ["Asset Category", "Security Description", "Security Type", "Quantity", "Unit Cost",
                  "Current Total Cost", "Market Value", "Gain/Loss", "Gain/Loss %", "Term",
                  "Trade Date", "Taxlot ID", "Covered/NonCovered", "Symbol", "Security Identifier"]
        meta = {"Account": "QFA339398", "As Of": "Jul 30, 2026 8:14 PM EDT",
                "Net Unrealized Gain/loss": "1,500.00"}
        data = [
            # security-level rollup (no Taxlot ID) — must be skipped, not double-counted
            ("Large Growth", "NVDA CORP", "Common Stocks", 20, None, 77, 4077, 4000, "", "long",
             "Multiple", "", "Covered", "NVDA", "NVDA"),
            ("Large Growth", "NVDA CORP", "Common Stocks", 10, 3.87, 38.71, 2038.71, 2000.00, "",
             "long", "2019-05-21 00:00:00", "LOT1", "Covered", "NVDA", "NVDA"),
            ("Large Value", "XYZ INC", "Common Stocks", 5, 100, 500, 0.0, -500.00, "", "short",
             "2026-01-15 00:00:00", "LOT2", "Covered", "XYZ", "XYZ"),
        ]
        lots = ugl.build_lots(meta, header, data, meta["Account"])
        check(len(lots) == 2 and {r["taxlot_id"] for r in lots} == {"LOT1", "LOT2"},
              "rollup row (no Taxlot ID) skipped; only real lots kept")
        check(lots[0]["as_of_date"] == "2026-07-30", "as-of parsed from 'Mon DD, YYYY ...' preamble")
        ugl.verify(meta, lots)  # 2000 - 500 == 1500, should not raise
        try:
            ugl.verify({"Net Unrealized Gain/loss": "999"}, lots)
            raised = False
        except SystemExit:
            raised = True
        check(raised, "checksum aborts when lot sum != report's Net Unrealized")

        write_csv(inputs / "cost_basis_QFA339398.csv", [
            {"account_id": "QFA339398", "as_of_date": "2026-07-30", "symbol": "NVDA", "term": "long",
             "cost_basis": "38.71", "market_value": "2038.71", "gain_loss": "2000.00"},
            {"account_id": "QFA339398", "as_of_date": "2026-07-30", "symbol": "XYZ", "term": "short",
             "cost_basis": "500", "market_value": "0", "gain_loss": "-500.00"},
        ])
        run([SCRIPTS / "create_tax_strategy_prompt.py", "--inputs-dir", inputs,
             "--reviews-dir", reviews, "--tax-profile", tax_profile, "--returns-dir", returns_dir])
        tptext = (reviews / "2025_tax_strategy_prompt.md").read_text()
        check("Cost basis & unrealized gains" in tptext and "NOT AVAILABLE" not in tptext,
              "tax prompt shows the cost-basis section instead of 'NOT AVAILABLE'")
        check("§1014" in tptext and "harvest the losses, not the gains" in tptext,
              "cost-basis section carries the revocable-trust step-up guidance")
        run([SCRIPTS / "build_advisor_briefing.py", "--finance-dir", root,
             "--reviews-dir", reviews, "--inputs-dir", inputs, "--tax-profile", tax_profile])
        names = {p.name for p in (reviews / "advisor_bundle").iterdir()}
        check("cost_basis_QFA339398.csv" in names, "normalized cost-basis CSV is bundled (Tier 2)")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
