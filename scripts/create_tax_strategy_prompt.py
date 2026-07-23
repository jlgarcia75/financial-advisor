#!/usr/bin/env python3
"""Generate a data-grounded tax-strategy prompt for the advisor LLM.

Fills the template in docs/tax-strategy-prompt.md with real figures from the
pipeline (net worth by tax treatment, per-account snapshot, allocation, YTD
income/fees) plus the household tax_profile note, then writes
Reviews/<year>_tax_strategy_prompt.md. Keeps the guardrails (VERIFY tags,
[DATA]/[ASSUMPTION]/[RULE] tagging, entity scoping, deadline ranking).

Cost basis / realized gains are not in the pipeline, so tax-loss-harvesting is
flagged as needing data rather than fabricated.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import (  # noqa: E402
    first_value,
    parse_frontmatter,
    parse_number,
    read_csv,
    read_json,
)

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance")
DEFAULT_INPUTS_DIR = VAULT / "Reviews/inputs"
DEFAULT_REVIEWS_DIR = VAULT / "Reviews"
DEFAULT_TAX_PROFILE = VAULT / "tax_profile.md"
DEFAULT_RETURNS_DIR = VAULT / "tax_returns"
DEFAULT_EQUITY_COMP_DIR = VAULT / "equity_comp"

RETURN_SUMMARY_COLS = [
    ("tax_year", "Year"), ("agi", "AGI"), ("taxable_income", "Taxable income"),
    ("total_tax", "Total tax"), ("effective_rate", "Eff. rate"),
    ("net_lt_cap_gain", "LTCG"), ("qualified_dividends", "Qual. div"), ("niit", "NIIT"),
]

DIVIDEND = lambda t: "dividend" in t  # noqa: E731
INTEREST = lambda t: "interest" in t  # noqa: E731
FEES = lambda t: "expense" in t or "fee" in t  # noqa: E731


def money(value) -> str:
    n = parse_number(value)
    return f"${n:,.2f}" if n is not None else (str(value).strip() or "<blank — VERIFY>")


def profile_line(fm: dict, key: str) -> str:
    v = str(fm.get(key, "")).strip()
    return v if v else "<blank — VERIFY>"


def sum_transactions(tx_rows, year: str, match) -> float:
    total = 0.0
    for r in tx_rows:
        if not str(first_value(r, ("date", "posted_date", "transaction_date"))).startswith(year):
            continue
        if match((r.get("transaction_type") or "").lower()):
            amt = parse_number(first_value(r, ("amount", "transaction_amount")))
            if amt is not None:
                total += amt
    return round(total, 2)


def breakdown_value(rows, dimension, key):
    for r in rows:
        if r.get("dimension") == dimension and r.get("key") == key:
            return r.get("value", "")
    return ""


def returns_section(returns_dir: Path) -> str:
    """Prior-year returns: reference docs to attach + a compact multi-year summary."""
    docs = sorted(p.name for p in returns_dir.glob("*_return.md")) if returns_dir.exists() else []
    summary = read_csv(returns_dir / "tax_returns_summary.csv")
    if not docs and not summary:
        return ("PRIOR-YEAR RETURNS\n- None provided yet. See docs/tax-return-ingest.md to add "
                "redacted returns (exact total tax, bracket, capital gains, NIIT, prior conversions).")

    lines = ["PRIOR-YEAR RETURNS  [DATA — from filed returns]"]
    if docs:
        lines.append(f"- Reference documents (attach these, redacted): {', '.join(docs)}")
    if summary:
        summary = sorted(summary, key=lambda r: str(r.get("tax_year", "")))
        header = " | ".join(label for _, label in RETURN_SUMMARY_COLS)
        lines += ["- Multi-year summary:", f"  | {header} |",
                  "  | " + " | ".join("---" for _ in RETURN_SUMMARY_COLS) + " |"]
        for row in summary:
            cells = []
            for col, _ in RETURN_SUMMARY_COLS:
                raw = row.get(col, "")
                cells.append(money(raw) if col not in ("tax_year", "effective_rate") and raw else (str(raw).strip() or "—"))
            lines.append("  | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _fmt_shares(n: float) -> str:
    return f"{n:,.0f}" if abs(n - round(n)) < 1e-9 else f"{n:,.4f}".rstrip("0").rstrip(".")


def rsu_section(equity_dir: Path, price_overrides: dict[str, float]) -> str:
    """Unvested RSUs: projected ordinary income by tax year (income only, no
    withholding math). Future vests are valued at an assumed flat price
    (price_per_share, overridable per symbol via --rsu-price); actual income is
    the FMV on the real vest date, so figures are tagged [ASSUMPTION]/VERIFY."""
    rows = [r for r in read_csv(equity_dir / "rsu_vesting.csv")
            if (r.get("status", "").strip().lower() or "unvested") != "vested"]
    if not rows:
        return ("EQUITY COMPENSATION — RSUs\n- None tracked yet. See docs/rsu-tracker.md to add "
                "equity_comp/rsu_vesting.csv (vest dates + shares) for projected vest income.")

    # Aggregate by (tax_year, symbol); blank vest_date -> "Unscheduled".
    by_bucket: dict[tuple[str, str], dict[str, float]] = {}
    total_shares = total_value = 0.0
    priced_symbols: dict[str, float] = {}
    unpriced = False
    for r in rows:
        symbol = (first_value(r, ("symbol",)) or "").strip().upper()
        shares = parse_number(first_value(r, ("shares",))) or 0.0
        price = price_overrides.get(symbol)
        if price is None:
            price = parse_number(first_value(r, ("price_per_share",)))
        year = str(first_value(r, ("vest_date",)) or "")[:4] or "Unscheduled"
        bucket = by_bucket.setdefault((year, symbol), {"shares": 0.0, "value": 0.0, "priced": 1.0})
        bucket["shares"] += shares
        total_shares += shares
        if price is not None:
            bucket["value"] += shares * price
            total_value += shares * price
            priced_symbols[symbol] = price
        else:
            bucket["priced"] = 0.0
            unpriced = True

    price_note = "; ".join(f"{s} @ ${p:,.2f}" for s, p in sorted(priced_symbols.items()))
    lines = ["EQUITY COMPENSATION — RSUs  [DATA — from equity_comp/rsu_vesting.csv]"]
    lines.append(
        f"- Unvested: {_fmt_shares(total_shares)} shares"
        + (f" ≈ {money(round(total_value, 2))} projected ordinary income at vest"
           f" (assumed price {price_note} — held flat [ASSUMPTION], VERIFY current price)"
           if total_value else " (price per share not set — VERIFY)")
    )
    lines += ["- Projected vest income by tax year (added to W-2 wages at vest):",
              "  | Tax year | Symbol | Shares vesting | Projected income |",
              "  | --- | --- | --- | --- |"]
    for (year, symbol), b in sorted(by_bucket.items()):
        value = money(round(b["value"], 2)) if b["priced"] and b["value"] else "VERIFY (no price)"
        lines.append(f"  | {year} | {symbol} | {_fmt_shares(b['shares'])} | {value} |")
    if unpriced:
        lines.append("  - Some tranches have no price_per_share — set it or pass --rsu-price SYMBOL=PRICE.")
    lines.append("- RSU vesting is ordinary income that raises AGI/MAGI in the vest year — revisit "
                 "withholding adequacy and the safe-harbor target for that year. [RULE]")
    return "\n".join(lines)


def parse_price_overrides(pairs) -> dict[str, float]:
    """Parse repeated --rsu-price SYMBOL=PRICE args into {SYMBOL: price}."""
    out: dict[str, float] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--rsu-price expects SYMBOL=PRICE, got {pair!r}")
        sym, _, price = pair.partition("=")
        value = parse_number(price)
        if value is None:
            raise SystemExit(f"--rsu-price price is not numeric: {pair!r}")
        out[sym.strip().upper()] = value
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a data-grounded tax-strategy prompt.")
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--tax-profile", type=Path, default=DEFAULT_TAX_PROFILE)
    parser.add_argument("--tax-year", help="Override the tax year (default: profile.tax_year or latest period).")
    parser.add_argument("--returns-dir", type=Path, default=DEFAULT_RETURNS_DIR,
                        help="Folder with redacted prior-year returns + tax_returns_summary.csv.")
    parser.add_argument("--equity-comp-dir", type=Path, default=DEFAULT_EQUITY_COMP_DIR,
                        help="Folder with rsu_vesting.csv for projected RSU vest income.")
    parser.add_argument("--rsu-price", action="append", metavar="SYMBOL=PRICE",
                        help="Override assumed price for a symbol's unvested RSUs (repeatable).")
    parser.add_argument("--out", type=Path, help="Output path (default: <reviews>/<year>_tax_strategy_prompt.md).")
    args = parser.parse_args()

    manifest_path = args.inputs_dir / "advisor_inputs_manifest.json"
    if not manifest_path.exists():
        print(f"Missing {manifest_path}. Run build_advisor_inputs.py first.", file=sys.stderr)
        return 2
    manifest = read_json(manifest_path)

    fm = parse_frontmatter(args.tax_profile) if args.tax_profile.exists() else {}
    if not fm:
        print(f"Warning: no tax profile at {args.tax_profile} — profile fields will be VERIFY placeholders.",
              file=sys.stderr)

    year = str(args.tax_year or fm.get("tax_year")
               or (manifest.get("periods_covered") or [""])[-1][:4] or "")
    if not year:
        print("Could not determine tax year; pass --tax-year.", file=sys.stderr)
        return 2

    snapshot = read_csv(args.reviews_dir / "NET_WORTH_snapshot.csv")
    breakdown = read_csv(args.reviews_dir / "networth_breakdown.csv")
    allocation = read_csv(args.reviews_dir / "allocation_summary.csv")
    transactions = read_csv(args.inputs_dir / manifest.get("datasets", {}).get(
        "transactions", "manual_statements_master_transactions.csv"))

    included = [r for r in snapshot if str(r.get("included_in_networth", "")).lower() == "true"]
    account_lines = "\n".join(
        f"  - {r.get('account_name','')} | {r.get('account_type','')} | "
        f"{r.get('tax_treatment') or 'unspecified'} | {r.get('owner') or '—'} | "
        f"{money(r.get('current_value'))} | as of {r.get('as_of','')}"
        for r in included
    ) or "  - <no accounts — run build_finance_dashboard.py>"

    asset_lines = "\n".join(
        f"  - {r.get('key','')}: {money(r.get('market_value'))} ({r.get('percent_of_total','')}%)"
        for r in allocation if r.get("dimension") == "asset_class"
    ) or "  - <no allocation data>"

    inherited = [r for r in included if "inherit" in (r.get("account_type", "").lower())]
    inherited_lines = "\n".join(
        f"  - {r.get('account_name','')} ({r.get('tax_treatment','')}): {money(r.get('current_value'))}"
        for r in inherited
    ) or "  - none detected"

    dividends = sum_transactions(transactions, year, DIVIDEND)
    interest = sum_transactions(transactions, year, INTEREST)
    fees = sum_transactions(transactions, year, FEES)
    prior_returns = returns_section(args.returns_dir)
    rsu_comp = rsu_section(args.equity_comp_dir, parse_price_overrides(args.rsu_price))

    prompt = f"""# {year} Tax Strategy — Advisor Prompt

_Generated from the finance pipeline. Attach these files when you paste this:_
_`NET_WORTH_snapshot.csv`, `networth_breakdown.csv`, `allocation_summary.csv`,_
_`inputs/manual_statements_master_transactions.csv`, `inputs/manual_statements_master_activity.csv`._

ROLE
You are a tax-planning analyst helping a household with proactive tax strategy. You are NOT
filing a return and NOT giving legal advice. Be concrete and quantitative, but flag
uncertainty instead of guessing.

TAX YEAR & GROUND RULES
- Tax year: {year}. Current-year constants provided by me (blank = you must supply and mark VERIFY):
  standard deduction {profile_line(fm, 'std_deduction')}; 401k limit {profile_line(fm, 'contribution_limit_401k')};
  IRA limit {profile_line(fm, 'contribution_limit_ira')}; HSA limit {profile_line(fm, 'contribution_limit_hsa')};
  LTCG thresholds {profile_line(fm, 'ltcg_thresholds')}.
  If any constant is blank or looks wrong for {year} given your knowledge cutoff, state the
  value you assume and mark it "VERIFY" — never silently use stale numbers.
- Tag every claim as [DATA] (from figures below), [ASSUMPTION] (yours, stated), or [RULE]
  (a general tax rule to verify). Show the math for any dollar figure.
- Rank recommendations by estimated after-tax $ impact AND deadline; call out hard deadlines.
- Scope advice per entity/return; do not blend the personal return with the trust.
- End with: (a) assumptions you made, and (b) the missing data that would most change your advice.

HOUSEHOLD PROFILE
- Filing status: {profile_line(fm, 'filing_status')}; State: {profile_line(fm, 'state')}; Dependents: {profile_line(fm, 'dependents')}
- Taxpayers: {profile_line(fm, 'taxpayers')}
- Entities / returns in scope: {profile_line(fm, 'entities')}
- Est. AGI/MAGI: {profile_line(fm, 'est_agi')}; marginal/effective bracket: {profile_line(fm, 'marginal_bracket')} / {profile_line(fm, 'effective_bracket')}
- YTD wages: {profile_line(fm, 'ytd_wages')}; withholding: {profile_line(fm, 'ytd_withholding')}; estimated payments made: {profile_line(fm, 'estimated_payments_made')}
- Prior-year AGI: {profile_line(fm, 'prior_year_agi')}; prior-year total federal tax: {profile_line(fm, 'prior_year_total_tax')} \
(safe-harbor base — prior AGI over $150k, so the underpayment target is 110% of this; check it against YTD withholding + estimated payments)
- Carryovers — capital loss {profile_line(fm, 'capital_loss_carryover')}, charitable {profile_line(fm, 'charitable_carryover')}

ACCOUNTS & POSITIONS  [DATA — authoritative, deduplicated]
- Net worth by tax treatment: taxable {money(breakdown_value(breakdown, 'tax_treatment', 'taxable'))}, \
tax-deferred {money(breakdown_value(breakdown, 'tax_treatment', 'tax_deferred'))}, \
tax-free {money(breakdown_value(breakdown, 'tax_treatment', 'tax_free'))}
- Accounts (name | type | tax treatment | owner | value | as-of):
{account_lines}
- Allocation by asset class:
{asset_lines}
- YTD from processed statements only: dividends {money(dividends)}, interest {money(interest)}, fees {money(fees)}
- Realized gains/losses: NOT AVAILABLE — the pipeline has no cost basis. Attach a 1099-B or
  provide basis to enable tax-loss-harvesting and cap-gains analysis.
- Inherited IRAs subject to the 10-year rule:
{inherited_lines}

{rsu_comp}

{prior_returns}

DELIVERABLES  (prioritized, deadline-tagged action plan)
1. Top strategies ranked by after-tax $ impact — each with the move, est. savings, deadline,
   target account/entity, and a one-line rationale. Consider at least: asset location across
   taxable/deferred/free; Roth conversion sizing to fill lower brackets; tax-loss harvesting
   (or why not, given no cost basis); inherited-IRA distribution plan under the 10-year rule;
   retirement/HSA contribution room and backdoor/mega-backdoor Roth; charitable (bunching,
   DAF, QCD); trust-vs-personal income placement.
2. Estimated liability under 2-3 scenarios (baseline vs recommended), with the math.
3. Quarterly estimated-payment guidance and a safe-harbor check for the rest of {year}.
4. State-specific considerations for {profile_line(fm, 'state')} (and community-property notes if relevant).
5. Documents to gather (W-2s, 1099-DIV/B/INT, K-1s, prior return) and common mistakes for this profile.
6. Whether this profile needs a CPA vs tax software, and why.
7. What data is missing that would most sharpen this analysis (especially cost basis).

VERIFY EVERYTHING TAX-LAW-SPECIFIC AGAINST CURRENT IRS/STATE GUIDANCE OR A CPA BEFORE ACTING.
"""

    out = args.out or (args.reviews_dir / f"{year}_tax_strategy_prompt.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(f"Wrote {out}")
    if not fm:
        print("Note: create 91_finance/tax_profile.md (see docs/tax-profile-template.md) for a complete prompt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
