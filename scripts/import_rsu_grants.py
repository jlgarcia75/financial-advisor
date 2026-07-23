#!/usr/bin/env python3
"""Import RSU Notice of Grant documents (Markdown) into rsu_vesting.csv.

Each grant notice PDF is converted to Markdown (e.g. via MarkItDown) and named
`<symbol>_<grant_number>_*.md` (e.g. `intc_14128360_rsu.md`) — the filename is the
authoritative source of symbol + grant number, because the PDF-to-Markdown flatten
makes the in-body "Grant Number" ambiguous with the WWID. This reads the vesting
schedule (one vest date + share count per tranche) and upserts one row per tranche
into equity_comp/rsu_vesting.csv, computing vested/unvested from today.

Re-running is idempotent: rows for a grant are replaced (so status refreshes), and any
price_per_share you set on a matching (grant_id, vest_date) row is preserved.

Usage:
  python3 scripts/import_rsu_grants.py [notice.md ...]
  python3 scripts/import_rsu_grants.py --grants-dir ~/.../equity_comp/grant_notices
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import first_value, read_csv, write_csv  # noqa: E402

VAULT = Path("/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance")
DEFAULT_CSV = VAULT / "equity_comp/rsu_vesting.csv"
DEFAULT_GRANTS_DIR = VAULT / "equity_comp/grant_notices"

COLUMNS = ["symbol", "grant_id", "grant_date", "vest_date", "shares",
           "status", "price_per_share", "source", "notes"]

FILENAME_RE = re.compile(r"^([A-Za-z]{1,6})_([0-9]{4,})", re.IGNORECASE)
DATE_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}$", re.IGNORECASE)
INT_RE = re.compile(r"^\d[\d,]*$")
TOTAL_RE = re.compile(r"(\d[\d,]*)\s+RSUs\b", re.IGNORECASE)
ANCHOR_RE = re.compile(r"^vesting\s+date:?$", re.IGNORECASE)
TERMINATOR_RE = re.compile(
    r"^(retirement vesting|additional documents|grant acceptance|you agree|you understand)",
    re.IGNORECASE)
# Newer Intel notices carry mail-merge tags after each value, e.g.
#   May 31, 2026
#   %%VEST_DATE_PERIOD1,'Month DD, YYYY'%-%
PERIOD_TAG_RE = re.compile(r"%%\s*(VEST_DATE|SHARES)_PERIOD(\d+)", re.IGNORECASE)
TOTAL_TAG_RE = re.compile(r"%%\s*TOTAL_SHARES_GRANTED", re.IGNORECASE)


def parse_filename(path: Path) -> tuple[str, str]:
    """(symbol, grant_id) from `<symbol>_<grant_number>_*.md`."""
    m = FILENAME_RE.match(path.name)
    if not m:
        raise SystemExit(
            f"Cannot read symbol/grant number from filename {path.name!r}. "
            f"Name grant notices like 'intc_14128360_rsu.md' (<symbol>_<grantnumber>_*.md).")
    return m.group(1).upper(), m.group(2)


def _cells(line: str) -> list[str]:
    """A line's candidate tokens — splits any Markdown-table pipes so both the
    flattened (one value per line) and table (| date | shares |) layouts work."""
    return [c.strip() for c in line.split("|") if c.strip()]


def to_iso(date_text: str) -> str:
    return datetime.strptime(date_text.strip(), "%B %d, %Y").date().isoformat()


def extract_schedule(text: str) -> tuple[list[tuple[str, int]], int | None]:
    """(list of (vest_date_iso, shares), grant_total_or_None) from the notice.

    Two Intel layouts are supported: newer notices tag each value with a mail-merge
    placeholder (VEST_DATE_PERIODn / SHARES_PERIODn / TOTAL_SHARES_GRANTED); older
    ones are a flat block of dates then a block of counts. The total is returned when
    the tagged layout provides it, else None (the caller falls back to extract_total)."""
    lines = [ln.strip() for ln in text.splitlines()]
    if any(PERIOD_TAG_RE.search(ln) for ln in lines):
        return _schedule_from_tags(lines)
    return _schedule_from_blocks(lines), None


def _schedule_from_tags(lines: list[str]) -> tuple[list[tuple[str, int]], int | None]:
    """Pair each mail-merge tag with the nearest preceding value line. Immune to
    stray page numbers and to the total sitting inside the schedule region."""
    dates: dict[int, str] = {}
    counts: dict[int, int] = {}
    total: int | None = None
    prev: str | None = None
    for ln in lines:
        pm = PERIOD_TAG_RE.search(ln)
        if pm and prev:
            kind, n = pm.group(1).upper(), int(pm.group(2))
            if kind == "VEST_DATE" and DATE_RE.match(prev):
                dates[n] = to_iso(prev)
            elif kind == "SHARES" and INT_RE.match(prev):
                counts[n] = int(prev.replace(",", ""))
        elif TOTAL_TAG_RE.search(ln) and prev and INT_RE.match(prev):
            total = int(prev.replace(",", ""))
        if ln and "%%" not in ln:
            prev = ln
    periods = sorted(set(dates) & set(counts))
    schedule = [(dates[p], counts[p]) for p in periods]
    if not schedule:
        raise SystemExit("No tagged vesting periods parsed — check the converted Markdown.")
    return schedule, total


def _schedule_from_blocks(lines: list[str]) -> list[tuple[str, int]]:
    """Older flat layout: anchor on the 'Vesting Date' header, stop at the next
    section, then zip date tokens with integer tokens in document order."""
    anchor = next((i for i, ln in enumerate(lines) if ANCHOR_RE.match(ln)), None)
    if anchor is None:
        raise SystemExit("No 'Vesting Date' header found — is this an RSU Notice of Grant?")
    end = anchor + 1
    while end < len(lines) and not TERMINATOR_RE.match(lines[end]):
        end += 1

    dates: list[str] = []
    counts: list[int] = []
    for ln in lines[anchor + 1:end]:
        for cell in _cells(ln):
            if DATE_RE.match(cell):
                dates.append(to_iso(cell))
            elif INT_RE.match(cell):
                counts.append(int(cell.replace(",", "")))
    if not dates or len(dates) != len(counts):
        raise SystemExit(
            f"Vesting schedule parse mismatch: {len(dates)} dates vs {len(counts)} share "
            f"counts. Check the converted Markdown.")
    return list(zip(dates, counts))


def extract_total(text: str) -> int | None:
    """The grant's 'Number of RSUs' total, for a checksum against the schedule."""
    totals = [int(m.replace(",", "")) for m in TOTAL_RE.findall(text)]
    # The largest 'N RSUs' figure is the grant total (tranche lines have no 'RSUs').
    return max(totals) if totals else None


def extract_grant_date(text: str) -> str:
    """Best-effort grant/commencement date: the earliest date token appearing
    before the vesting-schedule header. Optional — blank if not found."""
    lines = [ln.strip() for ln in text.splitlines()]
    anchor = next((i for i, ln in enumerate(lines) if ANCHOR_RE.match(ln)), len(lines))
    pre = [to_iso(ln) for ln in lines[:anchor] if DATE_RE.match(ln)]
    return min(pre) if pre else ""


def parse_notice(path: Path, today: date) -> list[dict]:
    symbol, grant_id = parse_filename(path)
    text = path.read_text(encoding="utf-8", errors="ignore")
    schedule, total = extract_schedule(text)
    if total is None:
        total = extract_total(text)
    scheduled = sum(s for _, s in schedule)
    if total is not None and total != scheduled:
        raise SystemExit(
            f"{path.name}: schedule sums to {scheduled} but the notice says {total} RSUs — "
            f"not writing. Check the converted Markdown.")
    grant_date = extract_grant_date(text)
    rows = []
    for vest_date, shares in schedule:
        vested = datetime.fromisoformat(vest_date).date() < today
        rows.append({
            "symbol": symbol, "grant_id": grant_id, "grant_date": grant_date,
            "vest_date": vest_date, "shares": shares,
            "status": "vested" if vested else "unvested",
            "price_per_share": "", "source": "grant_notice", "notes": f"from {path.name}",
        })
    return rows


def upsert(csv_path: Path, new_rows: list[dict]) -> tuple[int, int, list[str]]:
    """Replace rows for the imported grant_ids, preserving any price_per_share the
    user set on a matching (grant_id, vest_date). Returns (added, replaced, warnings)."""
    existing = read_csv(csv_path) if csv_path.exists() else []
    grant_ids = {r["grant_id"] for r in new_rows}
    price_by_key = {
        (r.get("grant_id", ""), r.get("vest_date", "")): r.get("price_per_share", "")
        for r in existing if (r.get("price_per_share") or "").strip()
    }
    for r in new_rows:
        kept = price_by_key.get((r["grant_id"], r["vest_date"]))
        if kept:
            r["price_per_share"] = kept

    replaced = sum(1 for r in existing if first_value(r, ("grant_id",)) in grant_ids)
    kept_rows = [r for r in existing if first_value(r, ("grant_id",)) not in grant_ids]

    warnings = []
    scaffold = [r for r in kept_rows if not (r.get("grant_id") or "").strip()]
    if scaffold:
        warnings.append(
            f"{len(scaffold)} row(s) with no grant_id (scaffold/aggregate) remain — delete them "
            f"to avoid double-counting now that per-tranche grants are imported.")

    merged = kept_rows + new_rows
    merged.sort(key=lambda r: (r.get("symbol", ""), r.get("grant_id", ""), r.get("vest_date", "")))
    write_csv(csv_path, merged, preferred=COLUMNS)
    return len(new_rows), replaced, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Import RSU grant notices (Markdown) into rsu_vesting.csv.")
    parser.add_argument("notices", nargs="*", type=Path, help="Grant-notice .md files.")
    parser.add_argument("--grants-dir", type=Path, default=DEFAULT_GRANTS_DIR,
                        help="Folder of grant-notice .md files (used when no files are listed).")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Target rsu_vesting.csv.")
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD) for vested/unvested.")
    parser.add_argument("--dry-run", action="store_true", help="Print parsed rows; do not write.")
    args = parser.parse_args()

    today = datetime.fromisoformat(args.today).date() if args.today else date.today()
    notices = args.notices or sorted(args.grants_dir.glob("*.md"))
    if not notices:
        print(f"No grant-notice .md files given or found in {args.grants_dir}.", file=sys.stderr)
        return 2

    all_rows: list[dict] = []
    for path in notices:
        if not path.exists():
            print(f"Missing: {path}", file=sys.stderr)
            return 2
        rows = parse_notice(path, today)
        unvested = sum(1 for r in rows if r["status"] == "unvested")
        print(f"{path.name}: {rows[0]['symbol']} grant {rows[0]['grant_id']} — "
              f"{len(rows)} tranches ({unvested} unvested), {sum(int(r['shares']) for r in rows)} shares total")
        all_rows.extend(rows)

    if args.dry_run:
        for r in all_rows:
            print(f"  {r['vest_date']}  {r['symbol']:<5} {r['shares']:>6}  {r['status']}")
        print(f"(dry run — {len(all_rows)} rows not written to {args.csv})")
        return 0

    added, replaced, warnings = upsert(args.csv, all_rows)
    print(f"Wrote {args.csv}: +{added} rows ({replaced} replaced).")
    for w in warnings:
        print(f"  ⚠️  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
