#!/usr/bin/env python3
"""
Extract normalized JSON and CSV files from a MarkItDown-converted financial statement Markdown file.

This script is intentionally conservative:
- It reads YAML frontmatter from a statement .md file.
- It extracts obvious balances, due dates, and transaction-like rows using regex heuristics.
- It writes:
    <statement_id>.json
    <statement_id>_transactions.csv
- It does NOT delete or mutate the source .md.

Recommended use:
    python scripts/extract-statement.py \
      "$HOME/second-brain/91_finance/Statements/2026-06_chase-sapphire-1234_statement.md"

For production use, treat this as a first-pass extractor and review outputs before import.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

DATE_PATTERNS = [
    # 06/03/2026 or 6/3/26. Match 4-digit years first.
    re.compile(r"(?P<date>\b\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})\b)"),
    # 2026-06-03
    re.compile(r"(?P<date>\b\d{4}-\d{2}-\d{2}\b)"),
]

AMOUNT_PATTERN = re.compile(
    r"(?P<amount>[-+]?\$?\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,6})?\)?)"
)

BALANCE_PATTERNS = {
    "opening_balance": re.compile(
        r"(?:previous|opening)\s+balance\s*[:\-]?\s*\$?([\d,]+\.\d{2})", re.I
    ),
    "closing_balance": re.compile(
        r"(?:new|ending|closing)\s+balance\s*[:\-]?\s*\$?([\d,]+\.\d{2})", re.I
    ),
    "statement_balance": re.compile(
        r"statement\s+balance\s*[:\-]?\s*\$?([\d,]+\.\d{2})", re.I
    ),
    "minimum_payment": re.compile(
        r"minimum\s+payment(?:\s+due)?\s*[:\-]?\s*\$?([\d,]+\.\d{2})", re.I
    ),
}

DUE_DATE_PATTERN = re.compile(
    r"(?:payment\s+)?due\s+date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})|\d{4}-\d{2}-\d{2})",
    re.I,
)

FILENAME_RE = re.compile(
    r"^(?P<period>\d{4}-\d{2})_(?P<institution>[a-z0-9-]+)-(?P<account>[a-z0-9-]+)-(?P<last4>\d{4})_statement$",
    re.I,
)

BROKERAGE_KEYWORDS = re.compile(
    r"\b(brokerage|investment|portfolio|holdings|positions|securities|stock plan|equity award|"
    r"vested|unvested|shares|quantity|cost basis|date acquired|proceeds|realized gain|"
    r"dividend|capital gain|cusip|symbol|ticker)\b",
    re.I,
)

ACCOUNT_TYPE_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    (
        "brokerage",
        re.compile(
            r"\b(brokerage|individual brokerage|stock plan|investment account|portfolio|securities)\b",
            re.I,
        ),
    ),
    (
        "retirement",
        re.compile(r"\b(401\(?k\)?|403\(?b\)?|ira|retirement|pension)\b", re.I),
    ),
    ("hsa", re.compile(r"\b(hsa|health savings)\b", re.I)),
    (
        "credit_card",
        re.compile(
            r"\b(credit card|visa|mastercard|amex|american express|cardmember)\b", re.I
        ),
    ),
    ("checking", re.compile(r"\b(checking|debit account)\b", re.I)),
    ("savings", re.compile(r"\b(savings|money market deposit)\b", re.I)),
    ("mortgage", re.compile(r"\b(mortgage)\b", re.I)),
    ("loan", re.compile(r"\b(loan|student loan|auto loan)\b", re.I)),
]

# Broad, first-pass ticker pattern. This intentionally favors reviewability over certainty.
TICKER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9.\-]{0,8}\b")


@dataclass
class ParsedMarkdown:
    frontmatter: dict[str, Any]
    body: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract JSON and CSV from financial statement Markdown."
    )
    parser.add_argument(
        "markdown_file", type=Path, help="Path to a *_statement.md file"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to the Markdown file directory.",
    )
    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="Allow extraction even if frontmatter status is not ready.",
    )
    parser.add_argument(
        "--account-type",
        default="unknown",
        choices=[
            "checking",
            "savings",
            "credit_card",
            "brokerage",
            "retirement",
            "hsa",
            "loan",
            "mortgage",
            "unknown",
        ],
        help="Account type to use when not present in frontmatter.",
    )
    return parser.parse_args()


def read_markdown(path: Path) -> ParsedMarkdown:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            raw_fm = text[4:end].strip()
            body = text[end + len("\n---") :].lstrip("\n")
            if yaml is None:
                raise RuntimeError(
                    "PyYAML is required to read frontmatter. Install with: pip install pyyaml"
                )
            data = yaml.safe_load(raw_fm) or {}
            if not isinstance(data, dict):
                data = {}
            return ParsedMarkdown(frontmatter=data, body=body)
    return ParsedMarkdown(frontmatter={}, body=text)


def parse_money(value: str) -> float:
    value = value.strip().replace("$", "").replace(",", "")
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    amount = float(value)
    return -amount if negative else amount


def normalize_date(value: str, period: str | None = None) -> str:
    value = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    parts = value.split("/")
    if len(parts) != 3:
        return value
    month, day, year = parts
    year_i = int(year)
    if year_i < 100:
        year_i += 2000
    return f"{year_i:04d}-{int(month):02d}-{int(day):02d}"


def detect_account_type(
    md_path: Path, frontmatter: dict[str, Any], body: str, fallback: str
) -> str:
    """Infer account type from frontmatter, filename, and statement text.

    Frontmatter wins because it represents a human-approved account note. Filename/body
    heuristics are intentionally conservative and should be reviewed in generated JSON.
    """
    explicit = str(frontmatter.get("account_type") or "").strip().lower()
    if explicit and explicit != "unknown":
        return explicit

    haystack = " ".join(
        [md_path.stem, str(frontmatter.get("account") or ""), body[:8000]]
    )
    for account_type, pattern in ACCOUNT_TYPE_KEYWORDS:
        if pattern.search(haystack):
            return account_type

    return fallback


def infer_metadata(
    md_path: Path, frontmatter: dict[str, Any], account_type: str, body: str
) -> dict[str, Any]:
    statement_id = str(frontmatter.get("statement_id") or md_path.stem)
    match = FILENAME_RE.match(statement_id)

    period = frontmatter.get("period")
    institution = frontmatter.get("institution")
    account = frontmatter.get("account")
    account_last4 = frontmatter.get("account_last4")

    if match:
        period = period or match.group("period")
        institution = institution or match.group("institution")
        account = account or match.group("account")
        account_last4 = account_last4 or match.group("last4")

    detected_account_type = detect_account_type(
        md_path, frontmatter, body, account_type
    )

    return {
        "statement_id": statement_id,
        "source": str(frontmatter.get("source") or "manual_statement"),
        "source_file": str(
            frontmatter.get("source_file") or md_path.with_suffix(".pdf").name
        ),
        "institution": str(institution or "unknown"),
        "account": str(account or "unknown"),
        "account_last4": str(account_last4 or "0000"),
        "account_type": detected_account_type,
        "statement_period": {
            "period": str(period or "0000-00"),
        },
        "currency": str(frontmatter.get("currency") or "USD"),
    }


def extract_balances(body: str, period: str | None) -> dict[str, Any]:
    balances: dict[str, Any] = {}
    for key, pattern in BALANCE_PATTERNS.items():
        match = pattern.search(body)
        if match:
            balances[key] = parse_money(match.group(1))
    due = DUE_DATE_PATTERN.search(body)
    if due:
        balances["payment_due_date"] = normalize_date(due.group(1), period)
    return balances


def looks_like_transaction_line(line: str) -> bool:
    if len(line.strip()) < 8:
        return False
    if not any(p.search(line) for p in DATE_PATTERNS):
        return False
    # Need at least one amount after the date.
    return bool(AMOUNT_PATTERN.search(line))


def extract_date(line: str) -> tuple[str | None, str]:
    for pattern in DATE_PATTERNS:
        match = pattern.search(line)
        if match:
            date = match.group("date")
            remainder = (line[: match.start()] + " " + line[match.end() :]).strip()
            return date, remainder
    return None, line


def extract_amount(line: str) -> tuple[float | None, str]:
    matches = list(AMOUNT_PATTERN.finditer(line))
    if not matches:
        return None, line
    match = matches[-1]
    amount = parse_money(match.group("amount"))
    remainder = (line[: match.start()] + " " + line[match.end() :]).strip()
    return amount, remainder


def normalize_description(text: str) -> str:
    text = re.sub(r"[|]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -—\t")


def classify_transaction(amount: float, description: str) -> str:
    desc = description.lower()
    if "payment" in desc:
        return "payment"
    if "interest" in desc:
        return "interest"
    if "fee" in desc:
        return "fee"
    if "transfer" in desc:
        return "transfer"
    return "debit" if amount > 0 else "credit"


TRANSACTION_SECTION_HEADER = re.compile(
    r"^(?:#{1,6}\s*)?(?:transactions?|transaction\s+activity|transaction\s+detail|account\s+activity|activity\s+details?)\s*$",
    re.I,
)
SECTION_HEADING = re.compile(r"^(#{1,6})\s+.*$")
UNDERLINE_HEADING = re.compile(r"^[-=]{3,}\s*$")
SECTION_TERMINATOR = re.compile(
    r"^(?:account\s+holdings(?:\s+for)?|portfolio\s+summary|household\s+summary|asset\s+allocation|performance|account\s+holdings|account\s+performance)\b",
    re.I,
)


def extract_section_lines(body: str, section_header: re.Pattern[str]) -> list[str]:
    lines = body.splitlines()
    start_index = None
    section_level = 0

    for index, line in enumerate(lines):
        if section_header.match(line.strip()):
            if index + 1 < len(lines) and UNDERLINE_HEADING.match(
                lines[index + 1].strip()
            ):
                start_index = index + 2
                section_level = 1
            else:
                heading_match = SECTION_HEADING.match(line)
                section_level = len(heading_match.group(1)) if heading_match else 1
                start_index = index + 1
            break

    if start_index is None:
        return lines

    section_lines: list[str] = []
    for index in range(start_index, len(lines)):
        line = lines[index]
        if SECTION_TERMINATOR.match(line.strip()):
            break
        heading_match = SECTION_HEADING.match(line)
        if heading_match:
            next_level = len(heading_match.group(1))
            if next_level <= section_level:
                break
        elif index + 1 < len(lines) and UNDERLINE_HEADING.match(
            lines[index + 1].strip()
        ):
            if not TRANSACTION_SECTION_HEADER.match(line.strip()):
                break
        section_lines.append(line)

    return section_lines


def extract_transactions(body: str, period: str | None) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    section_lines = extract_section_lines(body, TRANSACTION_SECTION_HEADER)

    for raw_line in section_lines:
        line = raw_line.strip()
        if not looks_like_transaction_line(line):
            continue
        raw_date, remainder = extract_date(line)
        amount, remainder = extract_amount(remainder)
        if raw_date is None or amount is None:
            continue
        date = normalize_date(raw_date, period)
        description = normalize_description(remainder)
        if not description or len(description) < 2:
            continue
        key = (date, description.lower(), amount)
        if key in seen:
            continue
        seen.add(key)
        transactions.append(
            {
                "date": date,
                "description": description,
                "amount": amount,
                "type": classify_transaction(amount, description),
                "confidence": "medium",
            }
        )

    return transactions

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not looks_like_transaction_line(line):
            continue
        raw_date, remainder = extract_date(line)
        amount, remainder = extract_amount(remainder)
        if raw_date is None or amount is None:
            continue
        date = normalize_date(raw_date, period)
        description = normalize_description(remainder)
        if not description or len(description) < 2:
            continue
        key = (date, description.lower(), amount)
        if key in seen:
            continue
        seen.add(key)
        transactions.append(
            {
                "date": date,
                "description": description,
                "amount": amount,
                "type": classify_transaction(amount, description),
                "confidence": "medium",
            }
        )

    return transactions


def parse_number(value: str) -> float | None:
    value = value.strip().replace(",", "").replace("$", "")
    value = value.strip("()")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def line_section_hint(line: str) -> str:
    lower = line.lower()
    if any(
        word in lower
        for word in ["holding", "position", "portfolio", "asset allocation"]
    ):
        return "holding"
    if any(
        word in lower
        for word in ["sold", "sale", "proceeds", "realized", "gain", "loss"]
    ):
        return "sale"
    if any(
        word in lower for word in ["bought", "buy", "purchase", "acquired", "reinvest"]
    ):
        return "buy"
    if any(
        word in lower
        for word in ["dividend", "interest", "capital gain", "distribution"]
    ):
        return "income"
    return "unknown"


def extract_ticker(line: str) -> str | None:
    # Prefer explicit Symbol/Ticker labels.
    label = re.search(
        r"(?:symbol|ticker)\s*[:\-]?\s*([A-Z][A-Z0-9.\-]{0,8})", line, re.I
    )
    if label:
        return label.group(1).upper()

    # In markdown tables, ticker often appears as a short all-caps cell.
    cells = [c.strip() for c in line.strip("|").split("|")]
    for cell in cells:
        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,8}", cell) and cell.upper() not in {
            "DATE",
            "QTY",
            "PRICE",
            "VALUE",
            "TOTAL",
        }:
            return cell.upper()

    return None


def extract_brokerage_row(line: str, period: str | None) -> dict[str, Any] | None:
    """Extract a best-effort brokerage lot/holding/activity row from one markdown line.

    Brokerage statements vary heavily by institution. This intentionally captures common
    fields and leaves blanks when unavailable rather than guessing. Review generated CSVs.
    """
    original_line = line
    clean = normalize_description(line)
    lower_clean = clean.lower()
    if lower_clean.startswith(("# ", "## ", "### ")) or lower_clean in {
        "portfolio holdings",
        "holdings",
        "positions",
        "realized gains/losses",
    }:
        return None
    if any(
        header in lower_clean
        for header in [
            "symbol description shares",
            "symbol security shares",
            "ticker description shares",
        ]
    ):
        return None
    if len(clean) < 8 or not BROKERAGE_KEYWORDS.search(clean):
        # Still allow table rows with a ticker and multiple numeric values.
        ticker_probe = extract_ticker(original_line) or extract_ticker(clean)
        money_count = len(
            re.findall(r"\$?\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,6})?\)?", line)
        )
        if not ticker_probe or money_count < 2:
            return None

    raw_date, no_date = extract_date(clean)
    date = normalize_date(raw_date, period) if raw_date else ""
    ticker = extract_ticker(original_line) or extract_ticker(clean) or ""

    # Extract all monetary/decimal-looking values from left to right.
    numeric_matches = [
        m.group(0)
        for m in re.finditer(
            r"\$?\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,6})?\)?", clean
        )
    ]
    nums = [n for n in (parse_number(v) for v in numeric_matches) if n is not None]

    # Label-driven extraction where possible.
    shares = None
    price_paid = None
    current_price = None
    cost_basis = None
    market_value = None
    proceeds = None
    realized_gain_loss = None

    def labeled_amount(labels: str) -> float | None:
        m = re.search(
            labels + r"\s*[:\-]?\s*\$?\(?([\d,]+(?:\.\d{1,6})?)\)?", clean, re.I
        )
        return parse_number(m.group(1)) if m else None

    shares = labeled_amount(r"(?:shares|quantity|qty)")
    price_paid = labeled_amount(
        r"(?:price paid|purchase price|acquisition price|cost/share|cost per share)"
    )
    current_price = labeled_amount(r"(?:current price|price|market price)")
    cost_basis = labeled_amount(r"(?:cost basis|total cost|basis)")
    market_value = labeled_amount(r"(?:market value|value|ending value|current value)")
    proceeds = labeled_amount(r"(?:proceeds|sales proceeds)")
    realized_gain_loss = labeled_amount(
        r"(?:realized gain|realized loss|gain/loss|gain loss)"
    )

    # Heuristic fallback for common holding rows: SYMBOL NAME SHARES PRICE VALUE COST_BASIS.
    if nums:
        if shares is None and len(nums) >= 1:
            shares = nums[0]
        if current_price is None and len(nums) >= 2:
            current_price = nums[1]
        if market_value is None and len(nums) >= 3:
            market_value = nums[2]
        if cost_basis is None and len(nums) >= 4:
            cost_basis = nums[3]

    acquired = re.search(
        r"(?:date acquired|acquired|purchase date)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})",
        clean,
        re.I,
    )
    sold = re.search(
        r"(?:date sold|sold|sale date)\s*[:\-]?\s*(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})|\d{4}-\d{2}-\d{2})",
        clean,
        re.I,
    )

    activity_type = line_section_hint(clean)

    # Common Markdown table row: | Symbol | Description | Shares | Price | Value | Cost Basis |
    cells = [c.strip() for c in original_line.strip().strip("|").split("|")]
    security_name = None
    if len(cells) >= 5 and ticker and cells[0].upper() == ticker:
        security_name = cells[1] if len(cells) > 1 else security_name
        shares = parse_number(cells[2]) if len(cells) > 2 else shares
        current_price = parse_number(cells[3]) if len(cells) > 3 else current_price
        market_value = parse_number(cells[4]) if len(cells) > 4 else market_value
        cost_basis = parse_number(cells[5]) if len(cells) > 5 else cost_basis

    # Description is the line with ticker and obvious numeric values removed only lightly.
    security_name = security_name or clean
    if ticker:
        security_name = re.sub(rf"\b{re.escape(ticker)}\b", "", security_name).strip()
    security_name = re.sub(r"\s+", " ", security_name).strip(" |-—")

    if not any([ticker, security_name, shares, market_value, cost_basis, proceeds]):
        return None

    return {
        "date": date,
        "activity_type": activity_type,
        "symbol": ticker,
        "security_name": security_name,
        "shares": shares,
        "price_paid": price_paid,
        "current_price": current_price,
        "cost_basis": cost_basis,
        "market_value": market_value,
        "proceeds": proceeds,
        "realized_gain_loss": realized_gain_loss,
        "date_acquired": normalize_date(acquired.group(1), period) if acquired else "",
        "date_sold": normalize_date(sold.group(1), period) if sold else "",
        "raw_line": clean,
        "confidence": "low" if activity_type == "unknown" else "medium",
    }


def extract_brokerage_rows(body: str, period: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 8:
            continue
        row = extract_brokerage_row(line, period)
        if not row:
            continue
        key = json.dumps(row, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def build_statement(
    md_path: Path, parsed: ParsedMarkdown, account_type: str
) -> dict[str, Any]:
    metadata = infer_metadata(md_path, parsed.frontmatter, account_type, parsed.body)
    period = metadata["statement_period"].get("period")
    balances = extract_balances(parsed.body, period)
    transactions = extract_transactions(parsed.body, period)
    brokerage_rows = (
        extract_brokerage_rows(parsed.body, period)
        if metadata.get("account_type") in {"brokerage", "retirement", "hsa"}
        else []
    )

    holdings = []
    if metadata.get("account_type") in {"brokerage", "retirement", "hsa"}:
        for row in brokerage_rows:
            if row.get("activity_type") in {"holding", "unknown"} and (
                row.get("market_value") is not None or row.get("shares") is not None
            ):
                holdings.append(
                    {
                        "name": row.get("security_name")
                        or row.get("symbol")
                        or "unknown",
                        "ticker": row.get("symbol") or "",
                        "quantity": row.get("shares"),
                        "price": row.get("current_price"),
                        "value": row.get("market_value") or 0,
                        "cost_basis": row.get("cost_basis"),
                        "asset_type": "other",
                    }
                )

    statement = {
        **metadata,
        "balances": balances,
        "transactions": transactions,
        "brokerage_rows": brokerage_rows,
        "holdings": holdings,
        "extraction": {
            "tool": "scripts/extract-statement.py",
            "extracted_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "review_status": "needs_review",
            "notes": "Regex-based first-pass extraction from MarkItDown Markdown. Review before import.",
        },
    }
    return statement


def write_json(statement: dict[str, Any], out_path: Path) -> None:
    out_path.write_text(
        json.dumps(statement, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def write_transactions_csv(statement: dict[str, Any], out_path: Path) -> None:
    rows = statement.get("transactions", [])
    fieldnames = [
        "statement_id",
        "institution",
        "account",
        "account_last4",
        "period",
        "date",
        "posted_date",
        "description",
        "merchant",
        "amount",
        "type",
        "category",
        "confidence",
        "source_file",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "statement_id": statement.get("statement_id"),
                    "institution": statement.get("institution"),
                    "account": statement.get("account"),
                    "account_last4": statement.get("account_last4"),
                    "period": statement.get("statement_period", {}).get("period"),
                    "date": row.get("date"),
                    "posted_date": row.get("posted_date", ""),
                    "description": row.get("description", ""),
                    "merchant": row.get("merchant", ""),
                    "amount": row.get("amount"),
                    "type": row.get("type", "unknown"),
                    "category": row.get("category", ""),
                    "confidence": row.get("confidence", "low"),
                    "source_file": statement.get("source_file"),
                }
            )


def write_brokerage_csv(statement: dict[str, Any], out_path: Path) -> None:
    rows = statement.get("brokerage_rows", [])
    fieldnames = [
        "statement_id",
        "institution",
        "account",
        "account_last4",
        "account_type",
        "period",
        "date",
        "activity_type",
        "symbol",
        "security_name",
        "shares",
        "price_paid",
        "current_price",
        "cost_basis",
        "market_value",
        "proceeds",
        "realized_gain_loss",
        "date_acquired",
        "date_sold",
        "confidence",
        "raw_line",
        "source_file",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "statement_id": statement.get("statement_id"),
                    "institution": statement.get("institution"),
                    "account": statement.get("account"),
                    "account_last4": statement.get("account_last4"),
                    "account_type": statement.get("account_type"),
                    "period": statement.get("statement_period", {}).get("period"),
                    "date": row.get("date", ""),
                    "activity_type": row.get("activity_type", "unknown"),
                    "symbol": row.get("symbol", ""),
                    "security_name": row.get("security_name", ""),
                    "shares": row.get("shares", ""),
                    "price_paid": row.get("price_paid", ""),
                    "current_price": row.get("current_price", ""),
                    "cost_basis": row.get("cost_basis", ""),
                    "market_value": row.get("market_value", ""),
                    "proceeds": row.get("proceeds", ""),
                    "realized_gain_loss": row.get("realized_gain_loss", ""),
                    "date_acquired": row.get("date_acquired", ""),
                    "date_sold": row.get("date_sold", ""),
                    "confidence": row.get("confidence", "low"),
                    "raw_line": row.get("raw_line", ""),
                    "source_file": statement.get("source_file"),
                }
            )


def main() -> int:
    args = parse_args()
    md_path = args.markdown_file.expanduser().resolve()
    if not md_path.exists():
        print(f"Missing file: {md_path}", file=sys.stderr)
        return 2

    parsed = read_markdown(md_path)
    status = str(parsed.frontmatter.get("status", "")).strip().lower()
    if status != "ready" and not args.allow_unreviewed:
        print(
            f"Skipping {md_path.name}: frontmatter status is {status!r}, not 'ready'. "
            "Use --allow-unreviewed to override.",
            file=sys.stderr,
        )
        return 3

    out_dir = (args.out_dir or md_path.parent).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    statement = build_statement(md_path, parsed, args.account_type)
    statement_id = statement["statement_id"]

    json_path = out_dir / f"{statement_id}.json"
    csv_path = out_dir / f"{statement_id}_transactions.csv"

    write_json(statement, json_path)
    write_transactions_csv(statement, csv_path)

    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Extracted {len(statement.get('transactions', []))} transaction rows")

    if statement.get("account_type") in {"brokerage", "retirement", "hsa"}:
        brokerage_csv_path = out_dir / f"{statement_id}_brokerage.csv"
        write_brokerage_csv(statement, brokerage_csv_path)
        print(f"Wrote {brokerage_csv_path}")
        print(f"Extracted {len(statement.get('brokerage_rows', []))} brokerage rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
