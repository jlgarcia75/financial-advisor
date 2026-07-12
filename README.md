# Empower Statement Extractor

This package contains a Python extractor tailored to the uploaded Empower Monthly Report Markdown file.

## What it extracts

- Household snapshot metadata and top-level value fields
- Activity-at-a-glance rows
- Transaction detail rows:
  - Cash Dividends
  - Miscellaneous Income
  - Miscellaneous Expenses
  - Buys
  - Sells
- Account holdings by account and asset class:
  - Cash and Cash Equivalents
  - Equity
  - Fixed Income

## What it intentionally does not extract

- Report Legend
- Disclosures
- Chart images
- Tax-lot data not present in the visible holdings tables, such as cost basis and date acquired

## Usage

```bash
python3 scripts/extract_empower_statement.py /path/to/2025-12_empower-garciatrust-1234_statement.md --out-dir /path/to/output
```

## Outputs

CSV datasets, written next to the input Markdown:

- `<statement_id>_holdings.csv`
- `<statement_id>_transactions.csv`
- `<statement_id>_accounts.csv`
- `<statement_id>_activity.csv`

The extractor also prints a JSON summary of row counts to stdout (it does not
write a `<statement_id>.json` file — the compact manifest is produced separately
by `create_statement_manifest.py`).
