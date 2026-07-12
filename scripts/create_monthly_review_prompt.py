#!/usr/bin/env python3
"""Generate a review-ready Markdown prompt for the advisor LLM (ChatGPT).

Reads the advisor input manifest and the generated dashboard, then produces a
self-contained prompt that tells the advisor exactly which files are authoritative,
what has already been computed, and which standing questions to answer. Pairing
this prompt with the master CSVs is the monthly "ask the advisor" step.

  Output: Reviews/<period>_monthly_review_prompt.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import read_json  # noqa: E402

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain")
DEFAULT_INPUTS_DIR = VAULT / "91_finance/Reviews/inputs"
DEFAULT_REVIEWS_DIR = VAULT / "91_finance/Reviews"

STANDING_QUESTIONS = [
    ("Net worth & trend", "What is my current net worth and how has it changed vs. prior periods? "
     "Call out the biggest drivers."),
    ("Portfolio allocation", "Is my asset allocation reasonable for a long-term investor? Flag "
     "concentration risk (single-name or sector) and any drift worth rebalancing."),
    ("Budgeting & cash flow", "Summarize inflows vs. outflows. Where is money going, what is my "
     "savings rate, and which recurring or discretionary categories could be trimmed?"),
    ("Tax strategy", "Given account tax treatments (taxable / tax-deferred / tax-free), suggest "
     "tax-loss-harvesting, asset-location, and contribution opportunities. Do not give filing advice."),
    ("Savings & goals", "Am I on track for retirement and emergency savings? Suggest concrete next actions."),
    ("Data quality", "Note anything that looks off or needs reconciliation before I trust these numbers."),
]


def build_prompt(period: str, manifest: dict, dashboard_rel: str, has_reconciliation: bool) -> str:
    datasets = manifest.get("datasets", {})
    periods = ", ".join(manifest.get("periods_covered", [])) or "unknown"
    lines = [
        f"# {period} Monthly Financial Review — Advisor Prompt",
        "",
        "You are my virtual financial advisor. Use the files listed below as the authoritative,",
        "already-validated data. Totals in the dashboard were computed deterministically — trust",
        "them over recomputing from raw rows, but verify if something looks inconsistent.",
        "",
        "## Data available",
        "",
        f"- Periods covered: **{periods}**",
        f"- Accounts: **{manifest.get('account_count', 'unknown')}**",
        f"- Row counts: {manifest.get('row_counts', {})}",
        "",
        "### Files (attach or point the connector at these)",
        "",
        f"- Dashboard summary: `{dashboard_rel}`",
        f"- Accounts: `inputs/{datasets.get('accounts', '')}`",
        f"- Holdings: `inputs/{datasets.get('holdings', '')}`",
        f"- Transactions: `inputs/{datasets.get('transactions', '')}`",
        f"- Activity: `inputs/{datasets.get('activity', '')}`",
        f"- Net worth snapshot: `NET_WORTH_snapshot.csv`",
        f"- Allocation: `allocation_summary.csv`",
        f"- Cash flow: `cash_flow_summary.csv`",
    ]
    if has_reconciliation:
        lines.append(f"- Reconciliation: `inputs/{manifest.get('reconciliation')}`")
    lines += [
        "",
        "## Ground rules",
        "",
        "- Preserve provenance: distinguish manual-statement data from linked data (`source` column).",
        "- Do not double-count: accounts/holdings flagged `probable_duplicate` are already excluded",
        "  from the dashboard totals; respect that.",
        "- Do not treat transfers between my own accounts as income or expense.",
        "- Do not treat credit-card payments as spending when the card's transactions are represented.",
        "- Flag anything unclear for review rather than guessing.",
        "",
        "## Questions to answer",
        "",
    ]
    for i, (topic, question) in enumerate(STANDING_QUESTIONS, start=1):
        lines.append(f"{i}. **{topic}.** {question}")
    lines += [
        "",
        "## Output",
        "",
        f"Write a concise review I can save as `Reviews/{period}_monthly_financial_review.md`, with a",
        "short executive summary followed by one section per question above and a final action list.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the monthly advisor review prompt.")
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--period", help="YYYY-MM (default: latest manifest period).")
    args = parser.parse_args()

    manifest_path = args.inputs_dir / "advisor_inputs_manifest.json"
    if not manifest_path.exists():
        print(f"Missing {manifest_path}. Run build_advisor_inputs.py first.", file=sys.stderr)
        return 2
    manifest = read_json(manifest_path)

    period = args.period or (manifest.get("periods_covered") or [""])[-1]
    if not period:
        print("Could not determine period; pass --period YYYY-MM.", file=sys.stderr)
        return 2

    dashboard = args.reviews_dir / f"{period}_dashboard.md"
    dashboard_rel = dashboard.name if dashboard.exists() else f"{period}_dashboard.md (run build_finance_dashboard.py)"
    has_reconciliation = bool(manifest.get("reconciliation"))

    out = args.reviews_dir / f"{period}_monthly_review_prompt.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_prompt(period, manifest, dashboard_rel, has_reconciliation), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
