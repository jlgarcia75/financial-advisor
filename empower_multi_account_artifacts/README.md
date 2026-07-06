# Empower Multi-Account Statement Artifacts

This package treats the Empower monthly report as one statement package with multiple sub-accounts.

## Normalized outputs

- `output/2025-12_empower-garciatrust-1234_statement.json` — full normalized statement object.
- `output/2025-12_empower-garciatrust-1234_statement_accounts.csv` — one row per sub-account.
- `output/2025-12_empower-garciatrust-1234_statement_holdings.csv` — one row per holding, always carrying `account_id`, `account_name`, and `account_type`.
- `output/2025-12_empower-garciatrust-1234_statement_transactions.csv` — one row per transaction, always carrying `account_id` and `account_name`.
- `output/2025-12_empower-garciatrust-1234_statement_activity.csv` — household/portfolio-level activity totals.
- `output/per_account/` — convenience splits for holdings and transactions by sub-account.

## Parser

Run:

```bash
python3 scripts/extract_empower_statement.py \
  ~/second-brain/91_finance/Statements/2025-12_empower-garciatrust-1234_statement.md \
  --out-dir ~/second-brain/91_finance/Statements
```

The parser intentionally keeps the original PDF/MD as one audit artifact and normalizes rows by account.

## Account rule

Every holding and transaction row must include:

- `statement_id`
- `account_id`
- `account_name`
- `account_type` where available
- `source_section`

This prevents rows from The Garcia Family Trust, Jesus Garcia ROTH IRA, LeAndra Garcia RO IRA, and LeAndra Garcia ROTH IRA from being mixed together.
