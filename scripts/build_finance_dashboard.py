#!/usr/bin/env python3
"""Build a local, deterministic finance dashboard from the advisor input package.

Consumes the consolidated manual masters (via advisor_inputs_manifest.json), the
linked-account exports, the reconciliation output, and per-account interpretation
notes, then produces trustworthy pre-computed rollups the advisor LLM can narrate:

  Reviews/NET_WORTH_snapshot.csv    one row per account, dedup + include rules applied
  Reviews/allocation_summary.csv    market value by asset class and by account type
  Reviews/cash_flow_summary.csv     inflow/outflow/net by month
  Reviews/<period>_dashboard.md     human-readable summary

Numbers are computed here (not by the LLM) so totals are reproducible and auditable.
Duplicate accounts flagged by reconciliation are excluded from the combined view;
accounts whose note sets `include_in_networth: false` are excluded from net worth.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import (  # noqa: E402
    first_value,
    latest_per_account,
    normalize_text,
    parse_number,
    period_of,
    read_csv,
    read_json,
    recency_key,
    write_csv,
)

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain")
DEFAULT_INPUTS_DIR = VAULT / "91_finance/Reviews/inputs"
DEFAULT_REVIEWS_DIR = VAULT / "91_finance/Reviews"
DEFAULT_ACCOUNTS_DIR = VAULT / "91_finance/Accounts"

ACCOUNT_ID_FIELDS = ("account_id", "persistent_account_id", "id")
ACCOUNT_NAME_FIELDS = ("account_name", "name", "official_name")
ACCOUNT_TYPE_FIELDS = ("account_type", "type", "subtype")
INSTITUTION_FIELDS = ("institution", "institution_name", "provider", "brokerage")
ACCOUNT_VALUE_FIELDS = ("total_account", "current_value", "market_value", "value", "balance")
HOLDING_VALUE_FIELDS = ("market_value", "current_value", "value")
TX_AMOUNT_FIELDS = ("amount", "transaction_amount")
TX_DATE_FIELDS = ("date", "posted_date", "authorized_date", "transaction_date")
DUPLICATE_STATUSES = {"probable_duplicate", "confirmed_duplicate"}


def load_account_notes(accounts_dir: Path) -> dict[str, dict[str, str]]:
    """Map account_id -> note frontmatter for interpretation rules."""
    from _finance_common import parse_frontmatter

    notes: dict[str, dict[str, str]] = {}
    if not accounts_dir.exists():
        return notes
    for md in sorted(accounts_dir.glob("*.md")):
        fm = parse_frontmatter(md)
        if fm.get("type") == "financial_account" and fm.get("account_id"):
            notes[normalize_text(fm["account_id"])] = fm
    return notes


def reconciliation_status_map(inputs_dir: Path) -> dict[str, str]:
    """Map a manual account key (id or normalized name) -> canonical status."""
    rows = read_csv(inputs_dir / "manual_linked_reconciliation.csv")
    result: dict[str, str] = {}
    for row in rows:
        status = row.get("status", "")
        for key in (row.get("manual_account_id"), row.get("manual_account_name")):
            if key:
                result[normalize_text(key)] = status
    return result


def account_key(row: dict[str, str]) -> str:
    return normalize_text(first_value(row, ACCOUNT_ID_FIELDS) or first_value(row, ACCOUNT_NAME_FIELDS))


def infer_tax_treatment(account_type: str) -> str:
    """Coarse tax treatment from an account type, for accounts without a note.
    Account notes always take precedence over this."""
    t = normalize_text(account_type)
    if not t:
        return ""
    if "roth" in t or "hsa" in t or "health savings" in t:
        return "tax_free"
    if any(k in t for k in ("401", "403", "457", "pension", "retirement", "ira", "sep", "simple")):
        return "tax_deferred"
    if any(k in t for k in ("credit", "card", "loan", "mortgage", "liabilit")):
        return "liability"
    if any(k in t for k in ("checking", "saving", "brokerage", "individual", "trust",
                            "cash", "money market", "taxable", "tod", "stock", "investment")):
        return "taxable"
    return ""


def build_networth(manual_accounts, linked_accounts, recon, notes):
    """One row per account with dedup + include rules applied."""
    snapshot = []
    for source, rows in (("manual_statement", manual_accounts), ("linked", linked_accounts)):
        for row in rows:
            key = account_key(row)
            note = notes.get(normalize_text(first_value(row, ACCOUNT_ID_FIELDS)), {})
            status = recon.get(key, "") if source == "manual_statement" else ""
            value = parse_number(first_value(row, ACCOUNT_VALUE_FIELDS))
            account_type = first_value(row, ACCOUNT_TYPE_FIELDS) or note.get("account_type", "")
            # Notes win; otherwise infer treatment from the account type.
            tax_treatment = note.get("tax_treatment") or infer_tax_treatment(account_type)

            excluded_reason = ""
            if source == "manual_statement" and status in DUPLICATE_STATUSES:
                excluded_reason = f"reconciliation:{status}"
            elif note.get("include_in_networth", "").lower() == "false":
                excluded_reason = "account_note:include_in_networth=false"

            snapshot.append({
                "account_id": first_value(row, ACCOUNT_ID_FIELDS),
                "account_name": first_value(row, ACCOUNT_NAME_FIELDS),
                "institution": first_value(row, INSTITUTION_FIELDS),
                "account_type": account_type,
                "tax_treatment": tax_treatment,
                "owner": note.get("owner", ""),
                "source": source,
                "as_of": recency_key(row),
                "current_value": value,
                "reconciliation_status": status,
                "included_in_networth": not excluded_reason,
                "excluded_reason": excluded_reason,
            })
    return snapshot


def build_networth_breakdown(snapshot, dimension, unlabeled="unspecified"):
    """Sum included net worth by a snapshot dimension (e.g. tax_treatment, owner),
    returning rows sorted high-to-low with a percent of total."""
    included = [r for r in snapshot if r["included_in_networth"]]
    total = sum(r["current_value"] or 0.0 for r in included)
    buckets: dict[str, float] = {}
    for r in included:
        buckets[r.get(dimension) or unlabeled] = buckets.get(r.get(dimension) or unlabeled, 0.0) + (r["current_value"] or 0.0)
    return [
        {
            "dimension": dimension,
            "key": key,
            "value": round(value, 2),
            "percent_of_networth": round(value / total * 100, 2) if total else 0.0,
        }
        for key, value in sorted(buckets.items(), key=lambda kv: -kv[1])
    ]


def build_allocation(manual_holdings, linked_holdings, recon, notes):
    """Market value by asset_class and by account_type, duplicates/excludes dropped."""
    by_class: dict[str, float] = {}
    by_type: dict[str, float] = {}
    total = 0.0
    for source, rows in (("manual_statement", manual_holdings), ("linked", linked_holdings)):
        for row in rows:
            key = account_key(row)
            note = notes.get(normalize_text(first_value(row, ACCOUNT_ID_FIELDS)), {})
            if source == "manual_statement" and recon.get(key, "") in DUPLICATE_STATUSES:
                continue
            if note.get("include_in_networth", "").lower() == "false":
                continue
            mv = parse_number(first_value(row, HOLDING_VALUE_FIELDS)) or 0.0
            asset_class = first_value(row, ("asset_class",)) or "Unclassified"
            acct_type = first_value(row, ACCOUNT_TYPE_FIELDS) or note.get("account_type", "") or "Unclassified"
            by_class[asset_class] = by_class.get(asset_class, 0.0) + mv
            by_type[acct_type] = by_type.get(acct_type, 0.0) + mv
            total += mv

    rows = []
    for dim, mapping in (("asset_class", by_class), ("account_type", by_type)):
        for key, mv in sorted(mapping.items(), key=lambda kv: -kv[1]):
            rows.append({
                "dimension": dim,
                "key": key,
                "market_value": round(mv, 2),
                "percent_of_total": round(mv / total * 100, 2) if total else 0.0,
            })
    return rows, total


def signed_amount(row: dict[str, str]) -> float | None:
    amount = parse_number(first_value(row, TX_AMOUNT_FIELDS))
    if amount is None:
        return None
    direction = normalize_text(first_value(row, ("cash_flow_direction",)))
    if direction == "inflow":
        return abs(amount)
    if direction == "outflow":
        return -abs(amount)
    return amount


def build_cash_flow(manual_tx, linked_tx, recon, notes):
    """Inflow/outflow/net by YYYY-MM month across both sources.

    Manual transactions belonging to a reconciled-duplicate or note-excluded
    account are dropped so they are not double-counted against linked data.
    """
    months: dict[str, dict[str, float]] = {}
    for source, rows in (("manual_statement", manual_tx), ("linked", linked_tx)):
        for row in rows:
            key = account_key(row)
            note = notes.get(normalize_text(first_value(row, ACCOUNT_ID_FIELDS)), {})
            if source == "manual_statement" and recon.get(key, "") in DUPLICATE_STATUSES:
                continue
            if note.get("include_in_networth", "").lower() == "false":
                continue
            month = period_of(first_value(row, TX_DATE_FIELDS))
            if not month:
                continue
            amt = signed_amount(row)
            if amt is None:
                continue
            bucket = months.setdefault(month, {"inflows": 0.0, "outflows": 0.0})
            if amt >= 0:
                bucket["inflows"] += amt
            else:
                bucket["outflows"] += amt
    rows = []
    for month in sorted(months):
        inflows, outflows = months[month]["inflows"], months[month]["outflows"]
        rows.append({
            "period": month,
            "inflows": round(inflows, 2),
            "outflows": round(outflows, 2),
            "net": round(inflows + outflows, 2),
        })
    return rows


def fmt_money(value) -> str:
    return f"${value:,.2f}" if isinstance(value, (int, float)) else "—"


def _breakdown_lines(title, label, rows):
    """Render a net-worth breakdown as a Markdown section (value + % columns)."""
    lines = ["", f"## {title}", "", f"| {label} | Value | % |", "| --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['key'] or '—'} | {fmt_money(r['value'])} | {r['percent_of_networth']}% |")
    return lines


def write_dashboard_md(path, period, snapshot, net_worth, allocation, alloc_total,
                       cash_flow, by_tax, by_owner):
    included = [r for r in snapshot if r["included_in_networth"]]
    excluded = [r for r in snapshot if not r["included_in_networth"]]
    asset_rows = [r for r in allocation if r["dimension"] == "asset_class"]

    lines = [
        f"# {period} Financial Dashboard",
        "",
        f"_Generated {datetime.now(timezone.utc).date().isoformat()} from validated CSVs. "
        "Numbers are computed deterministically; duplicates and excluded accounts are removed._",
        "",
        "## Net worth",
        "",
        f"**{fmt_money(net_worth)}** across {len(included)} included accounts "
        "(each account valued at its most recent statement).",
        "",
        "| Account | Institution | Type | Tax | Source | As of | Value |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(included, key=lambda r: -(r["current_value"] or 0)):
        lines.append(
            f"| {r['account_name']} | {r['institution']} | {r['account_type']} | "
            f"{r['tax_treatment'] or '—'} | {r['source']} | {r['as_of'] or '—'} | {fmt_money(r['current_value'])} |"
        )
    if excluded:
        lines += ["", "### Excluded from net worth", "",
                  "| Account | Source | Reason |", "| --- | --- | --- |"]
        for r in excluded:
            lines.append(f"| {r['account_name']} | {r['source']} | {r['excluded_reason']} |")

    if by_tax:
        lines += _breakdown_lines("Net worth by tax treatment", "Tax treatment", by_tax)
    if by_owner:
        lines += _breakdown_lines("Net worth by owner", "Owner", by_owner)

    lines += ["", "## Allocation by asset class", "",
              "| Asset class | Market value | % |", "| --- | --- | --- |"]
    for r in asset_rows:
        lines.append(f"| {r['key']} | {fmt_money(r['market_value'])} | {r['percent_of_total']}% |")
    if alloc_total:
        lines.append(f"| **Total** | **{fmt_money(round(alloc_total, 2))}** | **100%** |")

    if cash_flow:
        recent = cash_flow[-6:]
        lines += ["", "## Cash flow (recent months)", "",
                  "| Month | Inflows | Outflows | Net |", "| --- | --- | --- | --- |"]
        for r in recent:
            lines.append(f"| {r['period']} | {fmt_money(r['inflows'])} | "
                         f"{fmt_money(r['outflows'])} | {fmt_money(r['net'])} |")

    lines += ["", "---", "",
              "_Source: `Reviews/inputs/advisor_inputs_manifest.json`. See "
              "`NET_WORTH_snapshot.csv`, `networth_breakdown.csv`, `allocation_summary.csv`, "
              "`cash_flow_summary.csv` for the underlying rows._", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local finance dashboard from advisor inputs.")
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--reviews-dir", type=Path, default=DEFAULT_REVIEWS_DIR)
    parser.add_argument("--accounts-dir", type=Path, default=DEFAULT_ACCOUNTS_DIR)
    parser.add_argument("--period", help="YYYY-MM for the dashboard filename (default: latest manifest period).")
    args = parser.parse_args()

    manifest_path = args.inputs_dir / "advisor_inputs_manifest.json"
    if not manifest_path.exists():
        print(f"Missing {manifest_path}. Run build_advisor_inputs.py first.", file=sys.stderr)
        return 2
    manifest = read_json(manifest_path)
    datasets = manifest.get("datasets", {})

    # Balances and holdings are point-in-time: when masters hold several months,
    # use only each account's latest statement so net worth is not summed across
    # months. Transactions are flows and stay as a full multi-month time series.
    manual_accounts = latest_per_account(read_csv(args.inputs_dir / datasets.get("accounts", "manual_statements_master_accounts.csv")))
    manual_holdings = latest_per_account(read_csv(args.inputs_dir / datasets.get("holdings", "manual_statements_master_holdings.csv")))
    manual_tx = read_csv(args.inputs_dir / datasets.get("transactions", "manual_statements_master_transactions.csv"))
    linked_accounts = latest_per_account(read_csv(args.inputs_dir / "linked_accounts.csv"))
    linked_holdings = latest_per_account(read_csv(args.inputs_dir / "linked_holdings.csv"))
    linked_tx = read_csv(args.inputs_dir / "linked_transactions.csv")

    recon = reconciliation_status_map(args.inputs_dir)
    notes = load_account_notes(args.accounts_dir)

    snapshot = build_networth(manual_accounts, linked_accounts, recon, notes)
    net_worth = round(sum(r["current_value"] or 0.0 for r in snapshot if r["included_in_networth"]), 2)
    allocation, alloc_total = build_allocation(manual_holdings, linked_holdings, recon, notes)
    cash_flow = build_cash_flow(manual_tx, linked_tx, recon, notes)
    by_tax = build_networth_breakdown(snapshot, "tax_treatment")
    by_owner = build_networth_breakdown(snapshot, "owner")

    period = args.period or (manifest.get("periods_covered") or [""])[-1] or \
        datetime.now(timezone.utc).strftime("%Y-%m")

    write_csv(args.reviews_dir / "NET_WORTH_snapshot.csv", snapshot,
              preferred=["account_id", "account_name", "institution", "account_type",
                         "tax_treatment", "owner", "source", "as_of", "current_value", "included_in_networth"])
    write_csv(args.reviews_dir / "allocation_summary.csv", allocation)
    write_csv(args.reviews_dir / "cash_flow_summary.csv", cash_flow)
    write_csv(args.reviews_dir / "networth_breakdown.csv", by_tax + by_owner,
              preferred=["dimension", "key", "value", "percent_of_networth"])
    write_dashboard_md(args.reviews_dir / f"{period}_dashboard.md", period,
                       snapshot, net_worth, allocation, alloc_total, cash_flow, by_tax, by_owner)

    print(f"Net worth: {fmt_money(net_worth)} ({sum(1 for r in snapshot if r['included_in_networth'])} accounts)")
    print(f"Wrote dashboard artifacts to {args.reviews_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
