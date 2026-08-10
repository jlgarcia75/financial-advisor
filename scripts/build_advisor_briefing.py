#!/usr/bin/env python3
"""Build the ChatGPT advisor briefing and a safe upload bundle.

Generates a single "start here" orientation document (ADVISOR_BRIEFING.md) plus a
condensed project_instructions.md, and assembles Reviews/advisor_bundle/ containing
only the safe, derived artifacts to upload into a ChatGPT Project. Raw statements,
tax returns, and anything with SSNs / full account numbers (Tier 3) are never copied
— the privacy boundary is enforced in code, not by memory.

The briefing embeds a headline snapshot (net worth, allocation, RSU vests, tax
safe-harbor) computed here so the advisor is grounded before opening any CSV, an
inventory of every bundled file with what it is authoritative for, the household's
standing questions plus a "consider also" list, and the shared advisor guardrails.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import parse_frontmatter, parse_number, read_csv, read_json  # noqa: E402
from advisor_guardrails import GUARDRAILS  # noqa: E402

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance")
DEFAULT_REVIEWS_DIR = VAULT / "Reviews"
DEFAULT_INPUTS_DIR = VAULT / "Reviews/inputs"
REPO = Path(__file__).resolve().parent.parent
EXPORT_PROMPT = REPO / "docs" / "linked_export_prompt.md"

# Bundle spec: (base, relative-path-or-template). base is one of "reviews", "inputs",
# "finance" and is resolved to the matching --dir at runtime. Tier 1 = safe aggregates,
# Tier 2 = granular but free of SSNs / full account numbers (included by choice).
# Tier 3 (raw returns, raw statements, .env, logs) is NEVER listed — see FORBIDDEN.
BUNDLE = [
    ("reviews", "{dashboard}"),
    ("reviews", "NET_WORTH_snapshot.csv"),
    ("reviews", "allocation_summary.csv"),
    ("reviews", "networth_breakdown.csv"),
    ("reviews", "cash_flow_summary.csv"),
    ("reviews", "{tax_prompt}"),
    ("reviews", "{monthly_prompt}"),
    ("inputs", "advisor_inputs_manifest.json"),
    ("finance", "tax_profile.md"),
    ("finance", "tax_returns/tax_returns_summary.csv"),
    ("finance", "equity_comp/rsu_vesting.csv"),
    # Tier 2 — granular masters + linked data (no SSNs / full account numbers).
    ("inputs", "manual_statements_master_accounts.csv"),
    ("inputs", "manual_statements_master_holdings.csv"),
    ("inputs", "manual_statements_master_transactions.csv"),
    ("inputs", "manual_statements_master_activity.csv"),
    ("inputs", "manual_linked_reconciliation.csv"),
    ("inputs", "linked_accounts.csv"),
    ("inputs", "linked_holdings.csv"),
    ("inputs", "linked_transactions.csv"),
    ("inputs", "cost_basis_QFA339398.csv"),
]
# Defense in depth: refuse to bundle raw PII or raw broker exports. The normalized
# cost-basis CSV (cost_basis_*.csv) is fine; the raw export (*_unrealized-gl.csv,
# an .xlsx) is not.
FORBIDDEN = ("_return.md", "_statement.md", "_statement.pdf", ".env",
             "unrealized-gl.csv", ".xlsx")

WHAT = {
    "NET_WORTH_snapshot.csv": "Per-account balances, dedup'd; authoritative for net worth & per-account values",
    "allocation_summary.csv": "Market value by asset class and account type (unvested RSUs excluded)",
    "networth_breakdown.csv": "Net worth by tax treatment and by owner",
    "cash_flow_summary.csv": "Monthly inflow / outflow / net",
    "advisor_inputs_manifest.json": "Pipeline metadata: periods covered, row counts, freshness",
    "tax_profile.md": "Household tax facts: filing status, brackets, withholding, carryovers, the trust's character",
    "tax_returns_summary.csv": "Filed-return figures 2024-2025 (dollars only, no PII)",
    "rsu_vesting.csv": "RSU vesting schedule (ticker, dates, shares) — future ordinary income",
    "manual_statements_master_accounts.csv": "Empower/Pershing per-account balances (manual source of truth)",
    "manual_statements_master_holdings.csv": "Empower holdings — securities, values, asset class",
    "manual_statements_master_transactions.csv": "Empower transactions — dividends, fees, trades",
    "manual_statements_master_activity.csv": "Empower account activity totals",
    "manual_linked_reconciliation.csv": "Manual-vs-linked dedup status per account",
    "linked_accounts.csv": "ChatGPT-linked account balances (Chase, Fidelity, SoFi, Citi, etc.)",
    "linked_holdings.csv": "Linked brokerage/retirement positions",
    "linked_transactions.csv": "Linked account transactions",
    "cost_basis_QFA339398.csv": "Per-tax-lot cost basis + unrealized gain/loss for the trust brokerage (enables harvesting analysis)",
}

RECURRING_QUESTIONS = [
    "Allocation: is my mix drifting from target, and am I over-concentrated (INTC + the trust brokerage)?",
    "Cash flow: what's my savings rate and monthly net, and is any spending unusual?",
    "Safe harbor: am I on track for the 2026 target, and do I owe quarterly estimates?",
    "Tax-loss harvesting: harvest against the capital-loss carryover, or hold low-basis lots for the step-up?",
    "RSUs: how do the 2026-2030 vests hit AGI, withholding, and NIIT, and when should I sell vs hold INTC?",
    "Retirement: backdoor Roth this year, mega-backdoor in the Intel 401(k), HSA maxed and invested?",
]
CONSIDER_ALSO = [
    "Backdoor Roth pro-rata trap: LeAndra's Rollover IRA pre-tax balance can taint her backdoor Roth — resolve before contributing.",
    "Roth conversions in lower-AGI windows *before* the 2027 RSU income spike (~$213k).",
    "Asset location: are bonds in tax-deferred and equities in Roth/taxable, given ~95% equity and growing NIIT?",
    "Inherited-IRA 10-year drawdown schedule for LeAndra's inherited traditional + Roth IRAs.",
    "529 plans for Ila and Selene (CA) for education funding.",
    "Charitable bunching / donor-advised fund, given you itemize at a high CA marginal rate.",
    "Emergency-fund adequacy versus current cash balances.",
    "Estate hygiene: revocable trust avoids probate, but are beneficiary designations and titling current?",
    "Concentration risk: a written INTC sell/diversify plan (e.g. 10b5-1) as RSUs vest.",
    "K-1 suspended passive losses (Central Florida Income Fund, SQN, HSCRIA) — when do they free up?",
]

DO_NOT_UPLOAD = [
    "tax_returns/2024_return.md, tax_returns/2025_return.md — contain SSNs, DOB, home address, bank account numbers",
    "Statements/*.md and Statements/*.pdf — raw statements with full account numbers",
    ".env, logs/ — local paths and run logs",
    "Anything else showing a full account number, SSN, or login credential",
]


def money(value) -> str:
    n = parse_number(value)
    return f"${n:,.2f}" if n is not None else "—"


def latest_period(manifest: dict, reviews_dir: Path) -> str:
    periods = manifest.get("periods_covered") or []
    if periods:
        return periods[-1]
    dashes = sorted(reviews_dir.glob("*_dashboard.md"))
    return dashes[-1].name.split("_dashboard")[0] if dashes else ""


def resolve_bundle_names(reviews_dir: Path, period: str, tax_year: str) -> dict:
    """Fill the period/year-specific filenames referenced in the bundle spec."""
    tax_prompt = f"{tax_year}_tax_strategy_prompt.md"
    monthly = f"{period}_monthly_review_prompt.md"
    return {
        "dashboard": f"{period}_dashboard.md",
        "tax_prompt": tax_prompt if (reviews_dir / tax_prompt).exists() else "",
        "monthly_prompt": monthly if (reviews_dir / monthly).exists() else "",
    }


def net_worth_total(reviews_dir: Path) -> tuple[float, int]:
    rows = read_csv(reviews_dir / "NET_WORTH_snapshot.csv")
    incl = [r for r in rows if str(r.get("included_in_networth", "")).lower() == "true"]
    return sum(parse_number(r.get("current_value")) or 0.0 for r in incl), len(incl)


def breakdown_rows(reviews_dir: Path, filename: str, dimension: str) -> list[dict]:
    return [r for r in read_csv(reviews_dir / filename) if r.get("dimension") == dimension]


def rsu_by_year(finance_dir: Path) -> list[tuple[str, int]]:
    rows = read_csv(finance_dir / "equity_comp/rsu_vesting.csv")
    buckets: dict[str, int] = {}
    for r in rows:
        if (r.get("status", "").strip().lower() or "unvested") == "vested":
            continue
        year = str(r.get("vest_date", ""))[:4] or "Unscheduled"
        buckets[year] = buckets.get(year, 0) + int(parse_number(r.get("shares")) or 0)
    return sorted(buckets.items())


def snapshot_section(finance_dir: Path, reviews_dir: Path, fm: dict) -> str:
    lines = ["## Headline snapshot  [DATA]", ""]

    total, n = net_worth_total(reviews_dir)
    lines.append(f"- **Net worth: {money(total)}** across {n} included accounts.")

    tax_rows = breakdown_rows(reviews_dir, "networth_breakdown.csv", "tax_treatment")
    if tax_rows:
        parts = ", ".join(f"{r['key']} {money(r.get('value'))}" for r in tax_rows)
        lines.append(f"- By tax treatment: {parts}.")

    alloc = breakdown_rows(reviews_dir, "allocation_summary.csv", "asset_class")
    if alloc:
        parts = ", ".join(f"{r['key']} {r.get('percent_of_total', '')}%" for r in alloc[:4])
        lines.append(f"- Allocation (securities): {parts}.")

    rsu = rsu_by_year(finance_dir)
    if rsu:
        unvested = sum(s for _, s in rsu)
        by_year = ", ".join(f"{y}: {s:,}" for y, s in rsu)
        lines.append(f"- Unvested RSUs: {unvested:,} shares (by vest year — {by_year}). "
                     "Ordinary income at vest; see the tax prompt for $ projections.")

    sh = fm.get("safe_harbor_target_2026")
    pyt = fm.get("prior_year_total_tax")
    if sh or pyt:
        lines.append(f"- Tax: marginal {fm.get('marginal_bracket', '—')}; prior-year total tax "
                     f"{money(pyt)}; 2026 safe-harbor target {money(sh)}. "
                     f"Capital-loss carryover: {fm.get('capital_loss_carryover', '—')}.")
    return "\n".join(lines)


WHAT_SUFFIX = {
    "_dashboard.md": "Human-readable dashboard: net worth, allocation, and cash-flow narrative",
    "_tax_strategy_prompt.md": "Structured tax-strategy report prompt — paste for a ranked, deadline-tagged tax deliverable",
    "_monthly_review_prompt.md": "Monthly review prompt — budgeting, allocation drift, savings rate",
}


def what_is(name: str) -> str:
    if name in WHAT:
        return WHAT[name]
    for suffix, desc in WHAT_SUFFIX.items():
        if name.endswith(suffix):
            return desc
    return "derived artifact"


def inventory_section(bundle_files: list[str]) -> str:
    lines = ["## What's in this bundle  [DATA — safe, derived aggregates]", "",
             "| File | What it is |", "| --- | --- |"]
    for name in bundle_files:
        if name == "ADVISOR_BRIEFING.md":
            continue
        lines.append(f"| `{name}` | {what_is(name)} |")
    return "\n".join(lines)


def bullet_block(title: str, items: list[str]) -> str:
    return "\n".join([f"## {title}", ""] + [f"- {it}" for it in items])


def account_coverage(reviews_dir: Path, inputs_dir: Path) -> tuple[list[str], list[str], int, str]:
    """(manual institutions, linked institutions, total included accounts, linked as-of)."""
    incl = [r for r in read_csv(reviews_dir / "NET_WORTH_snapshot.csv")
            if str(r.get("included_in_networth", "")).lower() == "true"]

    def insts(source: str) -> list[str]:
        return sorted({r.get("institution", "").strip() for r in incl
                       if r.get("source") == source and r.get("institution", "").strip()})

    linked_rows = read_csv(inputs_dir / "linked_accounts.csv")
    asof = max((str(r.get("as_of_date", "")) for r in linked_rows if r.get("as_of_date")), default="")
    return insts("manual_statement"), insts("linked"), len(incl), asof


def coverage_section(manual: list[str], linked: list[str], total: int, asof: str) -> str:
    return "\n".join([
        "## Account coverage — everything is included  [DATA]",
        "",
        f"All **{total}** accounts are merged into net worth, allocation, and cash flow:",
        f"- **Manually ingested** (from statements): {', '.join(manual) or '—'}.",
        f"- **Plaid-linked** (from the monthly export, as of **{asof or '—'}**): "
        f"{', '.join(linked) or '—'}.",
        "",
        "Linked accounts are already counted **once** here. If you (ChatGPT) also have a live Plaid "
        "connection, treat this bundle as authoritative for all totals and use live Plaid only to "
        "flag what changed since the as-of date — never re-add a linked account or recompute net "
        "worth from Plaid. A Plaid-linked account **not** listed above is a coverage gap: flag it "
        "for the next export rather than silently adding it.",
    ])


def build_briefing(finance_dir: Path, reviews_dir: Path, inputs_dir: Path, manifest: dict,
                   fm: dict, period: str, bundle_files: list[str]) -> str:
    gen = datetime.now(timezone.utc).date().isoformat()
    manual_i, linked_i, total_acc, linked_asof = account_coverage(reviews_dir, inputs_dir)

    return "\n".join([
        "# Household Financial Advisor — Briefing",
        "",
        f"_Generated {gen}. This is the map for a ChatGPT Project: read it first, then use the "
        "attached files. Numbers here are computed deterministically by the pipeline — trust them "
        "over anything you re-derive._",
        "",
        "## Data freshness  ⚠️",
        "",
        f"- Statement data as of **{period}** (net worth, holdings, allocation).",
        f"- Linked accounts as of **{linked_asof or 'see linked_accounts.csv'}**.",
        f"- Periods covered: {', '.join(manifest.get('periods_covered', [])) or '—'}.",
        "- These files are a **static snapshot** until re-uploaded. If a question reaches past "
        "these dates, say so rather than guessing; ask for a refreshed bundle.",
        "",
        snapshot_section(finance_dir, reviews_dir, fm),
        "",
        coverage_section(manual_i, linked_i, total_acc, linked_asof),
        "",
        "## How to use this in ChatGPT",
        "",
        "1. Create a ChatGPT Project; paste `project_instructions.md` into the Project's custom "
        "instructions.",
        "2. Upload every file in this `advisor_bundle/` folder as Project knowledge.",
        "3. Ask questions freely (see below). For a rigorous, ranked deliverable, ask me to paste "
        "the tax-strategy or monthly-review prompt — those are structured report templates.",
        "4. Refresh monthly: re-run the pipeline and re-upload this folder.",
        "",
        inventory_section(bundle_files),
        "",
        bullet_block("Standing questions", RECURRING_QUESTIONS),
        "",
        bullet_block("Consider also (often missed)", CONSIDER_ALSO),
        "",
        "## Ground rules for the advisor",
        "",
        GUARDRAILS,
        "",
        "## Never upload these (they contain PII)  🚫",
        "",
        "\n".join(f"- {x}" for x in DO_NOT_UPLOAD),
        "",
        "---",
        "_Regenerated by `build_advisor_briefing.py`. Do not hand-edit — changes are overwritten._",
        "",
    ])


def build_instructions(period: str, linked: list[str], asof: str) -> str:
    linked_list = ", ".join(linked) or "the linked institutions in linked_accounts.csv"
    return "\n".join([
        "# ChatGPT Project — Custom Instructions",
        "",
        "You are our household's financial-advisor analyst. The uploaded bundle is your authoritative "
        "data; `ADVISOR_BRIEFING.md` is the index and headline snapshot. You are not filing returns "
        "or giving legal advice — be concrete and quantitative, but flag uncertainty.",
        "",
        f"Data is a static snapshot as of **{period}** (and the dates in `advisor_inputs_manifest.json`). "
        "If a question reaches past those dates, say so and ask for a refreshed bundle.",
        "",
        "Account coverage & live Plaid (avoid double-counting):",
        "- The bundle is the authoritative, reconciled source for ALL accounts — both manually "
        "ingested (Empower/Pershing, Central Lending) and Plaid-linked. Net worth, allocation, and "
        "cash-flow totals are pre-computed from it; use those numbers.",
        f"- The snapshot already includes the Plaid-linked accounts ({linked_list}), as of "
        f"**{asof or 'the linked as-of date'}**. They are counted once.",
        "- If you also have a live Plaid connection, use it ONLY to flag what changed since that "
        "as-of date (new/closed accounts, large balance moves, recent transactions). NEVER add live "
        "Plaid balances to the pre-computed totals or count a linked account twice.",
        "- If live Plaid and the snapshot disagree, report the delta and recommend refreshing the "
        "bundle — do not silently blend them. If a Plaid account isn't in the snapshot, flag it as a "
        "coverage gap for the next export.",
        "- To REFRESH the snapshot, I run `linked_export_prompt.md` (included here). That is the one "
        "step that deliberately pulls LIVE Plaid data to produce new CSVs — it does not read this "
        "bundle. Everywhere else, this bundle is authoritative.",
        "",
        "Ground rules:",
        GUARDRAILS,
        "",
        "Never ask me to paste raw tax returns or statements — they contain SSNs and full account "
        "numbers and are deliberately excluded. The aggregates you have are sufficient.",
        "",
        "For a structured deliverable (annual tax strategy, monthly review), tell me which prompt "
        "to paste; otherwise answer conversationally from the files.",
        "",
    ])


def assemble_bundle(finance_dir: Path, reviews_dir: Path, inputs_dir: Path,
                    names: dict) -> tuple[Path, list[str]]:
    """Copy Tier-1 + Tier-2 files into Reviews/advisor_bundle/, skipping missing ones
    and refusing anything that looks like raw PII. Returns (dir, bundled basenames)."""
    bases = {"reviews": reviews_dir, "inputs": inputs_dir, "finance": finance_dir}
    bundle_dir = reviews_dir / "advisor_bundle"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    bundled: list[str] = []
    for base, template in BUNDLE:
        rel = template.format(**names) if "{" in template else template
        if not rel or "{" in rel:
            continue  # an unresolved optional (e.g. no monthly prompt yet)
        src = bases[base] / rel
        if not src.exists():
            continue
        name = src.name
        if any(name.endswith(bad) for bad in FORBIDDEN):
            raise SystemExit(f"Refusing to bundle a forbidden (PII) file: {name}")
        shutil.copy2(src, bundle_dir / name)
        bundled.append(name)
    return bundle_dir, bundled


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the ChatGPT advisor briefing + safe upload bundle.")
    parser.add_argument("--finance-dir", type=Path, default=VAULT)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--tax-profile", type=Path, default=VAULT / "tax_profile.md")
    args = parser.parse_args()

    manifest_path = args.inputs_dir / "advisor_inputs_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    fm = parse_frontmatter(args.tax_profile) if args.tax_profile.exists() else {}

    period = latest_period(manifest, args.reviews_dir)
    tax_year = str(fm.get("tax_year") or (period[:4] if period else ""))
    names = resolve_bundle_names(args.reviews_dir, period, tax_year)

    bundle_dir, bundled = assemble_bundle(args.finance_dir, args.reviews_dir, args.inputs_dir, names)

    briefing = build_briefing(args.finance_dir, args.reviews_dir, args.inputs_dir,
                              manifest, fm, period, bundled)
    # Canonical copy in Reviews/, plus a copy inside the bundle as file #1.
    (args.reviews_dir / "ADVISOR_BRIEFING.md").write_text(briefing, encoding="utf-8")
    (bundle_dir / "ADVISOR_BRIEFING.md").write_text(briefing, encoding="utf-8")
    _, linked_i, _, linked_asof = account_coverage(args.reviews_dir, args.inputs_dir)
    (bundle_dir / "project_instructions.md").write_text(
        build_instructions(period, linked_i, linked_asof), encoding="utf-8")
    # The refresh prompt travels with the Project so you can regenerate the live
    # linked export from inside it (the one deliberate live-data-pull step).
    if EXPORT_PROMPT.exists():
        shutil.copy2(EXPORT_PROMPT, bundle_dir / EXPORT_PROMPT.name)

    print(f"Wrote {args.reviews_dir / 'ADVISOR_BRIEFING.md'}")
    print(f"Assembled {bundle_dir} with {len(bundled)} data file(s) + briefing + instructions + export prompt")
    for name in bundled:
        print(f"  + {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
