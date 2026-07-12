#!/usr/bin/env python3
"""Extract a Central Lending capital-account statement (MarkItDown Markdown) to CSVs.

Designed for the "Capital Account Statement" produced for investors in Central
Lending-managed funds (e.g. Central Florida Income Fund). A capital account is a
single LP interest, not a set of security holdings, so this emits:

  <base>_accounts.csv       one row: ending balance, commitment, ownership, to-date flows
  <base>_activity.csv       capital roll-forward + P&L as metric / value / basis
  <base>_transactions.csv   date / type / description / amount

No holdings dataset (a capital account has no security positions).

The source Markdown is inconsistent (mixed pipe tables and plain lines), so parsing
is intentionally label-driven and tolerant. Re-check if the statement format changes.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import (  # noqa: E402
    parse_date,
    parse_frontmatter,
    parse_number,
    normalize_text,
    write_csv,
)

DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
MONEY_CELL_RE = re.compile(r"^\(?-?\$?[\d,]+(?:\.\d+)?%?\)?$")

ROLLFORWARD = [
    "Beginning Balance", "Reinvest", "Redemption", "Purchase",
    "Net Income (Loss)", "Adjustment", "Distribution", "Ending Balance",
]
TX_TYPES = ["Net Income", "Reinvestment", "Distribution", "Redemption",
            "Purchase", "Contribution", "Adjustment"]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_money(cell: str) -> bool:
    cell = cell.strip()
    return bool(cell) and bool(MONEY_CELL_RE.match(cell)) and any(ch.isdigit() for ch in cell)


def money_cells(cs: list[str]) -> list[float]:
    return [parse_number(c) for c in cs if is_money(c)]


def find_row(lines: list[str], label: str) -> list[str] | None:
    """First pipe row that has `label` as an exact cell."""
    for line in lines:
        if "|" in line:
            cs = cells(line)
            if any(c == label for c in cs):
                return cs
    return None


def extract_meta(text: str) -> dict:
    as_of = ""
    m = DATE_RE.search(text)
    if m:
        as_of = parse_date(m.group(1))
    fund = ""
    fm = re.search(r"^(.*Fund.*)$", text, re.MULTILINE)
    if fm:
        fund = fm.group(1).strip()
    inv = re.search(r"Investor:\s*(.+)", text)
    investor = inv.group(1).strip() if inv else ""
    return {"as_of_date": as_of, "fund": fund, "investor": investor}


def extract_accounts(text, lines, statement_id, meta) -> list[dict]:
    def rf_current(label):
        row = find_row(lines, label)
        vals = money_cells(row) if row else []
        return vals[0] if vals else None

    ending = rf_current("Ending Balance")
    own_row = find_row(lines, "Ownership")
    commit_row = find_row(lines, "Total Commitment")
    ownership = money_cells(own_row)[0] if own_row and money_cells(own_row) else None
    commitment = money_cells(commit_row)[0] if commit_row and money_cells(commit_row) else None

    ctd = dtd = None
    m = re.search(r"Contributions to date\s+(\S+).*?Distributions to date\s+(\S+)", text)
    if m:
        ctd, dtd = parse_number(m.group(1)), parse_number(m.group(2))

    return [{
        "statement_id": statement_id,
        "account_id": normalize_text(meta["fund"]).replace(" ", "-") or "central-lending-capital-account",
        "account_name": meta["fund"] or "Central Lending Capital Account",
        "account_type": "capital_account",
        "institution": "central-lending",
        "investor": meta["investor"],
        "ownership_pct": ownership,
        "total_commitment": commitment,
        "contributions_to_date": ctd,
        "distributions_to_date": dtd,
        "ending_balance": ending,
        "total_account": ending,
        "as_of_date": meta["as_of_date"],
        "source_section": "Capital Account",
    }]


def extract_activity(lines, statement_id) -> list[dict]:
    rows = []
    for label in ROLLFORWARD:
        row = find_row(lines, label)
        if not row:
            continue
        vals = money_cells(row)
        for value, basis in zip(vals, ("current_period", "inception_to_date")):
            rows.append({"statement_id": statement_id, "metric": label, "value": value,
                         "basis": basis, "source_section": "Capital Account"})
    pnl = {
        "Profit & Loss current": "current_period",
        "Profit & Loss year to date": "year_to_date",
        "Profit & Loss to date": "inception_to_date",
    }
    for label, basis in pnl.items():
        row = find_row(lines, label)
        if row and money_cells(row):
            rows.append({"statement_id": statement_id, "metric": "Profit & Loss",
                         "value": money_cells(row)[0], "basis": basis,
                         "source_section": "Profit & Loss Summary"})
    return rows


def extract_transactions(text, statement_id) -> list[dict]:
    section = text.split("Transactions", 1)
    body = section[1] if len(section) > 1 else ""
    rows, seen = [], set()
    for line in body.splitlines():
        if not DATE_RE.search(line):
            continue
        if set(line.strip()) <= set("|-: "):  # separator
            continue
        date = txn_type = desc = ""
        amount = None
        if "|" in line:
            cs = cells(line)
            if len(cs) >= 4 and DATE_RE.match(cs[0]):
                date, txn_type, desc = parse_date(cs[0]), cs[1], cs[2]
                amount = money_cells(cs[3:])[-1] if money_cells(cs[3:]) else None
        else:
            m = DATE_RE.match(line.strip())
            if m:
                date = parse_date(m.group(1))
                monies = re.findall(r"\(?-?\$[\d,]+(?:\.\d+)?\)?", line)
                amount = parse_number(monies[-1]) if monies else None
                remainder = line.strip()[len(m.group(1)):].strip()
                if monies:
                    remainder = remainder.rsplit(monies[-1], 1)[0].strip()
                txn_type = next((t for t in TX_TYPES if remainder.startswith(t)), remainder.split(" ")[0])
                desc = remainder
        if amount is None:
            continue
        key = (date, txn_type, desc, amount)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"statement_id": statement_id, "date": date, "transaction_type": txn_type,
                     "description": desc, "amount": amount, "source_section": "Transactions"})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a Central Lending capital-account statement to CSVs.")
    parser.add_argument("statement_md", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    text = args.statement_md.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    statement_id = fm.get("statement_id") or args.statement_md.with_suffix("").name
    lines = text.splitlines()
    meta = extract_meta(text)

    accounts = extract_accounts(text, lines, statement_id, meta)
    activity = extract_activity(lines, statement_id)
    transactions = extract_transactions(text, statement_id)

    out_dir = args.out_dir or args.statement_md.parent
    base = out_dir / args.statement_md.with_suffix("").name
    write_csv(base.with_name(f"{base.name}_accounts.csv"), accounts)
    write_csv(base.with_name(f"{base.name}_activity.csv"), activity)
    write_csv(base.with_name(f"{base.name}_transactions.csv"), transactions)

    print(f"accounts={len(accounts)} activity={len(activity)} transactions={len(transactions)} "
          f"ending_balance={accounts[0]['ending_balance']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
