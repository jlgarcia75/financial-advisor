#!/usr/bin/env python3
"""
extract_empower_statement.py

Parse an Empower monthly report converted to Markdown by MarkItDown and emit
CSV files for a financial-advisor ingestion pipeline.

Input:
  2025-12_empower-garciatrust-1234_statement.md

Outputs by default, next to the input file:
  2025-12_empower-garciatrust-1234_statement_holdings.csv
  2025-12_empower-garciatrust-1234_statement_transactions.csv
  2025-12_empower-garciatrust-1234_statement_accounts.csv
  2025-12_empower-garciatrust-1234_statement_activity.csv

Designed for Empower/Pershing-style consolidated advisory statements that
contain:
  - Household Snapshot
  - Household Summary
  - Portfolio Summary
  - Transactions / Transaction Detail
  - Account Holdings

This parser intentionally ignores Report Legend and Disclosures because those
are explanatory text, not account/position/transaction data.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
MONEY_RE = re.compile(r"\(?\$?\s*[-+]?\d[\d,]*\.\d{2}\s*\)?")
NUMBER_RE = re.compile(r"\(?[-+]?\d[\d,]*\.\d+\s*\)?")

HOLDING_PLAIN_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<symbol>[A-Z][A-Z0-9./:-]{0,12})\s+"
    r"(?P<price>\d[\d,]*\.\d{2})\s+"
    r"(?P<quantity>\d[\d,]*\.\d{3})\s+"
    r"(?P<market_value>\d[\d,]*\.\d{2})\s+"
    r"(?P<pct>\d[\d,]*\.\d{2})$"
)

TOTAL_RE = re.compile(
    r"^Total\s+(?P<label>.+?)\s+\$?(?P<value>[\d,]+\.\d{2})\s+(?P<pct>[\d,]+\.\d{2})\s*%?$"
)


@dataclass
class Holding:
    statement_id: str
    account_id: str
    account_name: str
    account_type: str | None
    asset_class: str
    security_name: str
    symbol: str | None
    shares: float | None
    quantity: float | None
    current_price: float | None
    market_value: float | None
    percent_of_account: float | None
    cost_basis: float | None = None
    price_paid: float | None = None
    date_acquired: str | None = None
    date_sold: str | None = None
    source_section: str = "Account Holdings"


@dataclass
class Transaction:
    statement_id: str
    transaction_type: str
    date: str
    account_id: str | None
    account_name: str | None
    security_name: str
    symbol: str | None
    quantity: float | None
    shares: float | None
    price: float | None
    amount: float | None
    cash_flow_direction: str | None
    source_section: str = "Transactions"


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"-", "—", "N/A", "NaN"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        out = float(s)
    except ValueError:
        return None
    return -out if neg else out


def parse_date_mmddyyyy(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return value


def markdown_cells(line: str) -> list[str]:
    """Return markdown table cells, cleaned, or [] if not a table row."""
    if "|" not in line:
        return []
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    # Remove separator and empty filler cells, but preserve meaningful zeros/dashes.
    if parts and all(re.fullmatch(r"[-:\s]+", p or "") for p in parts):
        return []
    return [p for p in parts if p and not re.fullmatch(r"[-:\s]+", p)]


def line_to_text(line: str) -> str:
    cells = markdown_cells(line)
    if cells:
        return " ".join(cells)
    return line.strip()


def get_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    raw = text[3:end].strip()
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def extract_statement_metadata(
    text: str, source_file: str | None = None
) -> dict[str, Any]:
    fm = get_frontmatter(text)
    statement_id = fm.get("statement_id")
    if not statement_id and source_file:
        statement_id = Path(source_file).stem

    def first(pattern: str) -> str | None:
        m = re.search(pattern, text, flags=re.I)
        return m.group(1).strip() if m else None

    household = first(r"Household\s+\|?\s*:([A-Za-z ,#]+)") or first(
        r"Household\s*:([A-Za-z ,#]+)"
    )
    run_date = first(r"Run Date\s*\|?\s*:?\s*(\d{2}/\d{2}/\d{4})")
    as_of_date = first(r"As of Date\s*\|?\s*:?\s*(\d{2}/\d{2}/\d{4})")
    inception_date = first(r"Inception Date\s*\|?\s*:?\s*(\d{2}/\d{2}/\d{4})")

    return {
        "statement_id": statement_id,
        "source": fm.get("source", "manual_statement"),
        "source_file": fm.get("source_file", source_file),
        "institution": "empower",
        "provider_or_custodian": "Pershing LLC",
        "household": household,
        "inception_date": parse_date_mmddyyyy(inception_date),
        "run_date": parse_date_mmddyyyy(run_date),
        "as_of_date": parse_date_mmddyyyy(as_of_date),
        "review_status": fm.get("status"),
    }


def extract_household_snapshot(text: str) -> dict[str, Any]:
    """Extract page-1 household snapshot values.

    MarkItDown sometimes places these values in table cells and sometimes as
    plain text, so this function first searches table cells and then falls back
    to plain regexes.
    """
    label_to_key = {
        "Total Value This Period": "total_value_this_period",
        "Total Value Last Period": "total_value_last_period",
        "Change Since Last Statement": "change_since_last_statement",
        "Year to Date Return1": "year_to_date_return_pct",
        "Since Inception Return1": "since_inception_return_pct",
        "S&P 500 Index Year to Date Return2": "sp500_ytd_return_pct",
        "FTSE All World ex-US Net Index Year to Date Return2": "ftse_all_world_ex_us_ytd_return_pct",
        "Barclays Capital Bond Index Year to Date Return2": "barclays_capital_bond_ytd_return_pct",
    }

    out: dict[str, Any] = {}

    for line in text.splitlines()[:90]:
        cells = markdown_cells(line)
        if not cells:
            continue
        for i, cell in enumerate(cells):
            label = cell.strip()
            if label in label_to_key:
                for nxt in cells[i + 1 :]:
                    val = parse_number(nxt)
                    if val is not None:
                        out[label_to_key[label]] = val
                        break

    # Plain-text fallbacks.
    fallback_patterns = {
        "total_value_this_period": r"Total Value This Period\s+\$?([\d,]+\.\d{2})",
        "total_value_last_period": r"Total Value Last Period\s+\$?([\d,]+\.\d{2})",
        "change_since_last_statement": r"Change Since Last Statement\s+\$?([\d,]+\.\d{2})",
        "year_to_date_return_pct": r"Year to Date Return1\s+([\d,]+\.\d{2})\s*%",
        "since_inception_return_pct": r"Since Inception Return1\s+([\d,]+\.\d{2})\s*%",
    }
    for key, pat in fallback_patterns.items():
        if key not in out:
            m = re.search(pat, text[:4000], flags=re.I)
            if m:
                out[key] = parse_number(m.group(1))
    return out


def extract_activity_rows(text: str, statement_id: str) -> list[dict[str, Any]]:
    """Extract Activity-at-a-Glance rows from Household/Portfolio pages where table rows are clean."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        cells = markdown_cells(line)
        if len(cells) >= 3 and cells[0] in {
            "Beginning Value",
            "Income",
            "Expenses",
            "Contributions (Withdrawals)",
            "Change in Investments Value",
            "Ending Value",
            "Change in Value",
            "Change in Value %",
        }:
            rows.append(
                {
                    "statement_id": statement_id,
                    "metric": cells[0],
                    "reporting_month_or_quarter_to_date": parse_number(cells[1]),
                    "year_to_date": parse_number(cells[2]),
                    "source_section": "Activity at a Glance",
                }
            )
    # Deduplicate exact rows caused by household/portfolio repeats.
    dedup: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        key = (r["metric"], r["reporting_month_or_quarter_to_date"], r["year_to_date"])
        dedup[key] = r
    return list(dedup.values())


def split_account_id_name(account_text: str | None) -> tuple[str | None, str | None]:
    if not account_text:
        return None, None
    account_text = account_text.strip()
    m = re.match(r"^([A-Z0-9]+)\s*-\s*(.+)$", account_text)
    if m:
        return m.group(1), m.group(2).strip()
    return None, account_text


def guess_symbol_and_name(description: str) -> tuple[str | None, str]:
    description = description.strip()
    m = re.match(r"^([A-Z0-9./:-]{1,12})\s+-\s+(.+)$", description)
    if m:
        return m.group(1), m.group(2).strip()
    return None, description


def parse_transaction_row_from_cells(
    cells: list[str], current_type: str, statement_id: str
) -> Transaction | None:
    if len(cells) < 5:
        return None

    # Most rows are: Description | Date | Account | Quantity | Price | Transaction Amount
    date_idx = next(
        (i for i, c in enumerate(cells) if DATE_RE.fullmatch(c.strip())), None
    )
    if date_idx is None or date_idx == 0:
        return None

    description = " ".join(cells[:date_idx]).strip()
    date = parse_date_mmddyyyy(cells[date_idx])
    tail = cells[date_idx + 1 :]
    if len(tail) < 3:
        return None

    # Amount is last numeric-like field. Price is usually the preceding field, quantity before it.
    amount = parse_number(tail[-1])
    price = parse_number(tail[-2])
    quantity = parse_number(tail[-3])
    account_text = " ".join(tail[:-3]).strip()
    account_id, account_name = split_account_id_name(account_text)
    symbol, security_name = guess_symbol_and_name(description)

    direction = {
        "Cash Dividends": "inflow",
        "Miscellaneous Income": "inflow",
        "Miscellaneous Expenses": "outflow",
        "Buys": "outflow",
        "Sells": "inflow",
    }.get(current_type)

    return Transaction(
        statement_id=statement_id,
        transaction_type=current_type,
        date=date or "",
        account_id=account_id,
        account_name=account_name,
        security_name=security_name,
        symbol=symbol,
        quantity=quantity,
        shares=quantity,
        price=price,
        amount=amount,
        cash_flow_direction=direction,
    )


def parse_transaction_plain(
    line: str, current_type: str, statement_id: str
) -> Transaction | None:
    if not DATE_RE.search(line):
        return None
    date_match = DATE_RE.search(line)
    assert date_match is not None
    description = line[: date_match.start()].strip()
    rest = line[date_match.end() :].strip()
    date = parse_date_mmddyyyy(date_match.group())

    tokens = rest.split()
    if len(tokens) < 4:
        return None

    amount = parse_number(tokens[-1])
    price = parse_number(tokens[-2])
    quantity = parse_number(tokens[-3])
    account_text = " ".join(tokens[:-3]).strip()
    account_id, account_name = split_account_id_name(account_text)
    symbol, security_name = guess_symbol_and_name(description)

    direction = {
        "Cash Dividends": "inflow",
        "Miscellaneous Income": "inflow",
        "Miscellaneous Expenses": "outflow",
        "Buys": "outflow",
        "Sells": "inflow",
    }.get(current_type)

    return Transaction(
        statement_id=statement_id,
        transaction_type=current_type,
        date=date or "",
        account_id=account_id,
        account_name=account_name,
        security_name=security_name,
        symbol=symbol,
        quantity=quantity,
        shares=quantity,
        price=price,
        amount=amount,
        cash_flow_direction=direction,
    )


def extract_transactions(text: str, statement_id: str) -> list[Transaction]:
    txns: list[Transaction] = []
    current_type: str | None = None

    # Limit to the populated Transactions section before Account Holdings.
    start = text.find("Transaction Detail")
    end = text.find("Account Holdings for")
    tx_text = text[start:end] if start != -1 and end != -1 else text

    type_patterns = {
        "Cash Dividends": re.compile(
            r"^Cash Dividends\b|^\|\s*Cash Dividends\s*\|", re.I
        ),
        "Miscellaneous Income": re.compile(
            r"^Miscellaneous Income\b|^\|\s*Miscellaneous Income\s*\|", re.I
        ),
        "Miscellaneous Expenses": re.compile(
            r"^Miscellaneous Expenses\b|^\|\s*Miscellaneous Expenses\s*\|", re.I
        ),
        "Buys": re.compile(r"^Buys\b|^\|\s*Buys\s*\|", re.I),
        "Sells": re.compile(r"^Sells\b|^\|\s*Sells\s*\|", re.I),
    }

    for raw in tx_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("| ---") or line.startswith("Report Legend"):
            continue
        if line.startswith("Total "):
            continue
        for name, pat in type_patterns.items():
            if pat.search(line):
                current_type = name
                break

        if current_type is None:
            continue
        if "Total " in line and "$" in line:
            continue
        if "Date" in line and ("Account" in line or "Quantity" in line):
            continue

        cells = markdown_cells(line)
        txn = (
            parse_transaction_row_from_cells(cells, current_type, statement_id)
            if cells
            else parse_transaction_plain(line, current_type, statement_id)
        )
        if txn and txn.date and txn.amount is not None:
            txns.append(txn)

    # Deduplicate rows that appear both as table fragments and plain text.
    dedup: dict[tuple, Transaction] = {}
    for t in txns:
        key = (
            t.transaction_type,
            t.date,
            t.account_id,
            t.symbol,
            t.security_name,
            t.quantity,
            t.price,
            t.amount,
        )
        dedup[key] = t
    return list(dedup.values())


def parse_holding_from_cells(
    cells: list[str],
    statement_id: str,
    account_id: str,
    account_name: str,
    account_type: str | None,
    asset_class: str,
) -> Holding | None:
    cleaned = [c for c in cells if c and c not in {"-", "—"}]
    if len(cleaned) < 6:
        return None
    # Skip headers/totals.
    if (
        cleaned[0]
        .lower()
        .startswith(("total ", "symbol", "price", "quantity", "market value"))
    ):
        return None

    # Common shape: name, symbol, price, quantity, market_value, percent.
    # Sometimes an extra filler column appears before quantity; use the last 4 numeric-like fields.
    numeric_positions = [
        i for i, c in enumerate(cleaned) if parse_number(c) is not None
    ]
    if len(numeric_positions) < 4:
        return None
    price_i, qty_i, mv_i, pct_i = numeric_positions[-4:]
    symbol_i = price_i - 1
    if symbol_i < 1:
        return None

    name = " ".join(cleaned[:symbol_i]).strip()
    symbol = cleaned[symbol_i].strip()
    return Holding(
        statement_id=statement_id,
        account_id=account_id,
        account_name=account_name,
        account_type=account_type,
        asset_class=asset_class,
        security_name=name,
        symbol=symbol,
        shares=parse_number(cleaned[qty_i]),
        quantity=parse_number(cleaned[qty_i]),
        current_price=parse_number(cleaned[price_i]),
        market_value=parse_number(cleaned[mv_i]),
        percent_of_account=parse_number(cleaned[pct_i]),
    )


def parse_holding_plain(
    line: str,
    statement_id: str,
    account_id: str,
    account_name: str,
    account_type: str | None,
    asset_class: str,
) -> Holding | None:
    m = HOLDING_PLAIN_RE.match(line.strip())
    if not m:
        return None
    d = m.groupdict()
    return Holding(
        statement_id=statement_id,
        account_id=account_id,
        account_name=account_name,
        account_type=account_type,
        asset_class=asset_class,
        security_name=d["name"].strip(),
        symbol=d["symbol"].strip(),
        shares=parse_number(d["quantity"]),
        quantity=parse_number(d["quantity"]),
        current_price=parse_number(d["price"]),
        market_value=parse_number(d["market_value"]),
        percent_of_account=parse_number(d["pct"]),
    )


def extract_holdings(
    text: str, statement_id: str
) -> tuple[list[Holding], list[dict[str, Any]]]:
    holdings: list[Holding] = []
    account_summaries: dict[str, dict[str, Any]] = {}

    current_account_id: str | None = None
    current_account_name: str | None = None
    current_account_type: str | None = None
    current_asset_class: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        plain = line_to_text(line)

        m = re.search(r"Account Holdings for\s+([A-Z0-9]+)\s+-\s+(.+)$", plain)
        if m:
            current_account_id = m.group(1)
            current_account_name = m.group(2).strip()
            current_account_type = None
            current_asset_class = None
            account_summaries.setdefault(
                current_account_id,
                {
                    "statement_id": statement_id,
                    "account_id": current_account_id,
                    "account_name": current_account_name,
                    "account_type": None,
                    "total_account": None,
                    "source_section": "Account Holdings",
                },
            )
            continue

        if current_account_id and plain.startswith("Account Type:"):
            current_account_type = plain.split(":", 1)[1].strip()
            account_summaries[current_account_id]["account_type"] = current_account_type
            continue

        if not current_account_id or not current_account_name:
            continue

        # Section transitions.
        if re.search(r"\bCash and Cash Equivalents\b", plain, re.I):
            current_asset_class = "Cash and Cash Equivalents"
            continue
        if re.match(r"^Equity\b", plain):
            current_asset_class = "Equity"
            continue
        if re.match(r"^Fixed Income\b", plain):
            current_asset_class = "Fixed Income"
            continue
        if plain.startswith("Total Account"):
            nums = MONEY_RE.findall(plain)
            if nums:
                account_summaries[current_account_id]["total_account"] = parse_number(
                    nums[0]
                )
            continue
        if (
            plain.startswith("Total ")
            or plain.startswith("Report Legend")
            or plain.isdigit()
        ):
            continue
        if current_asset_class is None:
            continue
        if any(
            h in plain
            for h in ["Symbol Price Quantity", "% of Account", "Market Value"]
        ):
            continue

        cells = markdown_cells(line)
        holding = (
            parse_holding_from_cells(
                cells,
                statement_id,
                current_account_id,
                current_account_name,
                current_account_type,
                current_asset_class,
            )
            if cells
            else None
        )
        if holding is None:
            holding = parse_holding_plain(
                plain,
                statement_id,
                current_account_id,
                current_account_name,
                current_account_type,
                current_asset_class,
            )
        if holding and holding.security_name and holding.market_value is not None:
            holdings.append(holding)

    # Deduplicate holdings.
    dedup: dict[tuple, Holding] = {}
    for h in holdings:
        key = (
            h.account_id,
            h.asset_class,
            h.symbol,
            h.security_name,
            h.quantity,
            h.current_price,
            h.market_value,
        )
        dedup[key] = h

    return list(dedup.values()), list(account_summaries.values())


def summarize_sections(text: str) -> list[dict[str, Any]]:
    """Return a human-readable section map based on headings and known report structure."""
    sections = [
        {
            "section": "Empower Monthly Report / Household Snapshot",
            "pages": "1",
            "purpose": "Top-level household value, period-over-period change, benchmark returns, table of contents.",
            "use_for_advisor": "Household net-worth snapshot and statement metadata.",
            "extract": True,
        },
        {
            "section": "Household Summary",
            "pages": "2",
            "purpose": "Activity at a Glance, asset allocation, and household breakdown.",
            "use_for_advisor": "Performance, contributions/withdrawals, income, expenses, and allocation summary.",
            "extract": True,
        },
        {
            "section": "Portfolio Summary",
            "pages": "3, 21",
            "purpose": "Portfolio-level activity, performance, and allocation. Garcia #2 is empty in this file.",
            "use_for_advisor": "Portfolio totals and data quality checks.",
            "extract": True,
        },
        {
            "section": "Transactions",
            "pages": "4-10, 22",
            "purpose": "Transaction Summary and Transaction Detail by subtype.",
            "subsections": [
                "Cash Dividends",
                "Miscellaneous Income",
                "Miscellaneous Expenses",
                "Buys",
                "Sells",
            ],
            "use_for_advisor": "Income, fees, buys, sells, realized activity, cash-flow classification.",
            "extract": True,
        },
        {
            "section": "Account Holdings",
            "pages": "11-20",
            "purpose": "Security holdings by account and asset class.",
            "subsections": ["Cash and Cash Equivalents", "Equity", "Fixed Income"],
            "use_for_advisor": "Portfolio allocation, positions, account totals, concentration analysis.",
            "extract": True,
        },
        {
            "section": "Disclosures",
            "pages": "23",
            "purpose": "Legal/explanatory text and source-document warnings.",
            "use_for_advisor": "Do not import as financial records; retain as audit context only.",
            "extract": False,
        },
    ]
    return sections


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract normalized data from an Empower statement Markdown file."
    )
    parser.add_argument("markdown_file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    text = args.markdown_file.read_text(encoding="utf-8", errors="ignore")
    out_dir = args.out_dir or args.markdown_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    metadata = extract_statement_metadata(text, source_file=args.markdown_file.name)
    statement_id = metadata["statement_id"] or args.markdown_file.stem

    holdings, accounts = extract_holdings(text, statement_id)
    transactions = extract_transactions(text, statement_id)
    activity = extract_activity_rows(text, statement_id)

    statement = {
        **metadata,
        "account_type_detected": "brokerage",
        "sections": summarize_sections(text),
        "household_snapshot": extract_household_snapshot(text),
        "accounts": accounts,
        "holdings": [asdict(h) for h in holdings],
        "transactions": [asdict(t) for t in transactions],
        "activity": activity,
        "extraction": {
            "tool": "extract_empower_statement.py",
            "extracted_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            + "Z",
            "source_format": "markitdown_md",
            "quality_flags": [
                "Empower statement has holdings and transaction tables split across pages.",
                "Cost basis, tax lots, date acquired, and realized gain/loss are not present in the visible Account Holdings tables and are emitted as null.",
                "Price paid is available for buy/sell transaction rows as transaction price, not as position cost basis.",
                "Use the custodian statement/1099 for tax-lot and tax reporting.",
            ],
        },
    }

    base = out_dir / statement_id

    write_csv(
        base.with_name(base.name + "_holdings.csv"),
        [asdict(h) for h in holdings],
        [
            "statement_id",
            "account_id",
            "account_name",
            "account_type",
            "asset_class",
            "security_name",
            "symbol",
            "shares",
            "quantity",
            "current_price",
            "market_value",
            "percent_of_account",
            "cost_basis",
            "price_paid",
            "date_acquired",
            "date_sold",
            "source_section",
        ],
    )
    write_csv(
        base.with_name(base.name + "_transactions.csv"),
        [asdict(t) for t in transactions],
        [
            "statement_id",
            "transaction_type",
            "date",
            "account_id",
            "account_name",
            "security_name",
            "symbol",
            "quantity",
            "shares",
            "price",
            "amount",
            "cash_flow_direction",
            "source_section",
        ],
    )
    write_csv(
        base.with_name(base.name + "_accounts.csv"),
        accounts,
        [
            "statement_id",
            "account_id",
            "account_name",
            "account_type",
            "total_account",
            "source_section",
        ],
    )
    write_csv(
        base.with_name(base.name + "_activity.csv"),
        activity,
        [
            "statement_id",
            "metric",
            "reporting_month_or_quarter_to_date",
            "year_to_date",
            "source_section",
        ],
    )

    print(
        json.dumps(
            {
                "statement_id": statement_id,
                "holdings": len(holdings),
                "transactions": len(transactions),
                "accounts": len(accounts),
                "activity_rows": len(activity),
                "outputs": [
                    str(base.with_name(base.name + "_holdings.csv")),
                    str(base.with_name(base.name + "_transactions.csv")),
                    str(base.with_name(base.name + "_accounts.csv")),
                    str(base.with_name(base.name + "_activity.csv")),
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
