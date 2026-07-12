#!/usr/bin/env python3
"""Shared helpers for the financial-advisor pipeline.

Small, dependency-free utilities used across the extraction, reconciliation,
dashboard, and review scripts. Kept in one place so the CSV/number/date/
frontmatter handling behaves identically everywhere.
"""
from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


# --------------------------------------------------------------------------- #
# CSV / JSON IO
# --------------------------------------------------------------------------- #
def read_csv(path: Path | None) -> list[dict[str, str]]:
    """Read a CSV into a list of dicts. Missing/None path yields []."""
    if path is None or not Path(path).exists():
        return []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: Iterable[str] = ()) -> None:
    """Write rows to CSV, preserving first-seen column order.

    `preferred` columns (when present) are emitted first, in the given order.
    An empty rows list writes an empty file (keeps downstream globs happy).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields, seen = [], set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    preferred = [f for f in preferred if f in seen]
    ordered = preferred + [f for f in fields if f not in preferred]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Field access / text normalization
# --------------------------------------------------------------------------- #
def first_value(row: dict[str, Any], fields: Iterable[str]) -> str:
    """Return the first non-empty value among `fields` in `row`."""
    for field in fields:
        value = row.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_text(value: Any) -> str:
    text = str(value or "").lower().strip().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


# --------------------------------------------------------------------------- #
# Number / date parsing
# --------------------------------------------------------------------------- #
def parse_number(value: Any) -> float | None:
    """Parse a currency/percentage-ish string into a float, or None."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def parse_date(value: Any) -> str:
    """Normalize a date string to ISO (YYYY-MM-DD); pass through if unknown."""
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def is_date(value: Any) -> bool:
    """True if the value parses as a supported date format."""
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            pass
    return False


def period_of(value: Any) -> str:
    """Return the YYYY-MM period from a date-ish value, else ''."""
    iso = parse_date(value)
    return iso[:7] if re.match(r"^\d{4}-\d{2}", iso) else ""


# --------------------------------------------------------------------------- #
# Point-in-time selection (multi-month masters)
# --------------------------------------------------------------------------- #
ACCOUNT_ID_FIELDS = ("account_id", "persistent_account_id", "id")
ACCOUNT_NAME_FIELDS = ("account_name", "name", "official_name")


def recency_key(row: dict[str, Any]) -> str:
    """A sortable recency string for a row: prefer as_of_date, else the
    YYYY-MM prefix of statement_id. Used to pick the newest statement per
    account when masters hold several months."""
    for field in ("as_of_date", "run_date"):
        value = str(row.get(field, "")).strip()
        if value:
            return parse_date(value)
    sid = str(row.get("statement_id", "")).strip()
    m = re.match(r"(\d{4}-\d{2})", sid)
    return m.group(1) if m else ""


def account_identity(row: dict[str, Any]) -> str:
    return first_value(row, ACCOUNT_ID_FIELDS) or normalize_text(first_value(row, ACCOUNT_NAME_FIELDS))


def latest_per_account(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the rows belonging to each account's most recent statement.

    Balances and holdings are point-in-time; summing them across months
    double-counts. Rows for an account that share its latest recency_key are
    all retained (so every holding of the newest statement survives)."""
    if not rows:
        return rows
    latest: dict[str, str] = {}
    for row in rows:
        acct = account_identity(row)
        latest[acct] = max(latest.get(acct, ""), recency_key(row))
    return [row for row in rows if recency_key(row) == latest[account_identity(row)]]


# --------------------------------------------------------------------------- #
# Markdown frontmatter
# --------------------------------------------------------------------------- #
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def parse_frontmatter(md_text_or_path: str | Path) -> dict[str, str]:
    """Parse simple `key: value` YAML frontmatter from Markdown text or a file.

    Deliberately a flat scalar parser (no nested YAML) to stay dependency-free
    and match the frontmatter the pipeline actually writes.
    """
    if isinstance(md_text_or_path, Path):
        md_text = md_text_or_path.read_text(encoding="utf-8", errors="ignore")
    else:
        md_text = md_text_or_path
    match = _FRONTMATTER_RE.search(md_text)
    data: dict[str, str] = {}
    if not match:
        return data
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data
