# Linked-Account CSV Export

Your Empower/Pershing brokerage is ingested from PDF statements. Everything else is
**linked** inside ChatGPT/Finances. To build a single consolidated view — and to let the
reconciler detect double-counting — the linked data has to leave ChatGPT as CSV.

This document defines that hand-off: a fixed export prompt you run monthly, and the exact
CSV shapes the pipeline expects.

## Where the files go

Save the three exported files into the same folder the manual masters live in:

```text
~/ObsidianVaults/second-brain/91_finance/Reviews/inputs/
├── linked_accounts.csv
├── linked_holdings.csv        # only if you hold linked investment positions
└── linked_transactions.csv
```

`reconcile_manual_vs_linked.py` reads these by default (`--linked-dir` points at
`Reviews/inputs`). Only `linked_accounts.csv` is strictly required; holdings/transactions
are optional but recommended.

## Required columns

The column names below match what the reconciler and dashboard look for. Extra columns are
fine and are ignored. Validated by `schemas/linked/{accounts,holdings,transactions}.schema.json`.

**linked_accounts.csv** — one row per account
`account_id, account_name, institution, account_type, account_last4, current_value, as_of_date, source`

**linked_holdings.csv** — one row per position
`account_id, account_name, institution, account_last4, symbol, security_name, quantity, current_price, market_value, as_of_date, source`

**linked_transactions.csv** — one row per transaction
`transaction_id, account_id, account_name, institution, date, description, merchant_name, amount, category, source`

Conventions:
- `account_last4` — last 4 digits of the account number as a string (keep leading zeros).
- `current_value` / `market_value` / `amount` — plain numbers; no `$` or thousands commas.
  Outflows/withdrawals are negative.
- `as_of_date` / `date` — `YYYY-MM-DD`.
- `source` — put `linked` so provenance is preserved after merging.

## The monthly export prompt

Paste this into your ChatGPT Financial Advisor project after your linked accounts refresh:

```text
Export my linked financial accounts as three CSV code blocks I can copy verbatim. Do not
summarize or round — emit raw rows. Use exactly these headers and column orders:

1) linked_accounts.csv
account_id,account_name,institution,account_type,account_last4,current_value,as_of_date,source
- One row per linked account (checking, savings, credit card, brokerage, retirement, loan).
- current_value: numeric, no $ or commas; liabilities (credit cards, loans) negative.
- account_last4: last 4 digits as text; source: linked.

2) linked_holdings.csv
account_id,account_name,institution,account_last4,symbol,security_name,quantity,current_price,market_value,as_of_date,source
- One row per investment position in any linked brokerage/retirement account.
- Numbers only; source: linked. If I have no linked investment positions, output just the header.

3) linked_transactions.csv
transaction_id,account_id,account_name,institution,date,description,merchant_name,amount,category,source
- One row per transaction for the reporting month.
- amount numeric, spending/withdrawals negative, income/deposits positive.
- date as YYYY-MM-DD; source: linked.

Use consistent account_id values across all three files. Do not invent data; leave a cell
blank if unknown.
```

Copy each code block into the matching file in `Reviews/inputs/`.

## Monthly checklist

1. Refresh linked accounts in ChatGPT/Finances.
2. Run the export prompt above; save the three CSVs into `Reviews/inputs/`.
3. Ingest in one command — validates the CSVs, then reconciles and rebuilds the dashboard,
   manifest, and monthly review prompt:

   ```bash
   python3 scripts/ingest_linked_export.py
   # or, if you saved the CSVs elsewhere:
   python3 scripts/ingest_linked_export.py --source ~/Downloads/linked
   ```

4. Review `Reviews/YYYY-MM_reconciliation_review.md` and resolve any `needs_review` accounts.

The extraction from ChatGPT (steps 1–2) is manual by design — there is no supported API to
pull linked-account data automatically. Everything after the export is automated by the
ingest script. To run a single stage by hand instead, see
`validate_statement_csvs.py --help`, `reconcile_manual_vs_linked.py --help`, and
`build_finance_dashboard.py --help`.

## Safety

Per the project safety rules: do not paste full account numbers, SSNs, or credentials into
ChatGPT. `account_last4` is sufficient for matching. These CSVs live only in the gitignored
vault, never in the repo.
