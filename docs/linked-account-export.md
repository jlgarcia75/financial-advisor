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
`account_id, account_name, institution, account_last4, symbol, security_name, asset_class, quantity, current_price, market_value, as_of_date, source`

**linked_transactions.csv** — one row per transaction
`transaction_id, account_id, account_name, institution, date, description, merchant_name, amount, category, source`

Conventions:
- `account_last4` — last 4 digits of the account number as a string (keep leading zeros).
- `current_value` / `market_value` / `amount` — plain numbers; no `$` or thousands commas.
  Outflows/withdrawals are negative.
- `as_of_date` / `date` — `YYYY-MM-DD`.
- `source` — put `linked` so provenance is preserved after merging.
- `asset_class` — `Equity`, `Fixed Income`, or `Cash and Cash Equivalents`. Optional:
  if left blank the dashboard infers it from the symbol/security name, but providing
  it (when ChatGPT knows the security) is more accurate than the inference.

## The monthly export prompt

The exact prompt to paste is in **[linked_export_prompt.md](linked_export_prompt.md)** — the single
canonical copy (also shipped inside the advisor bundle, so it's available in your ChatGPT Project).

It forces ChatGPT to query **live** Plaid data at run time — not the uploaded snapshot, cached
exports, or the advisor bundle — and to state coverage gaps rather than silently falling back to a
stale file. That live-pull is the one deliberate exception to "the bundle is authoritative"; run it
to *produce* a fresh snapshot, then re-ingest. State the reporting month when you run it, and save the
three code blocks into `Reviews/inputs/`.

## Monthly checklist

1. Refresh linked accounts in ChatGPT/Finances.
2. Run the export prompt above; save the three CSVs into `Reviews/inputs/`.
3. Run the **monthly review** — the full one command that processes any new statements, then
   validates these CSVs, reconciles, rebuilds the dashboard / review prompt / advisor bundle, and
   archives the previous month. It prints the review prompt to paste:

   ```bash
   python3 scripts/monthly_review.py   # reads the CSVs you saved in Reviews/inputs/ (step 2)
   ```

   See [monthly-review.md](monthly-review.md) for the full ritual. Add `--source <dir>` only if you
   saved the CSVs somewhere other than `Reviews/inputs/` (it copies them in first). If you *only*
   refreshed linked data (no new statements, no archiving), run just the linked half instead:

   ```bash
   python3 scripts/ingest_linked_export.py
   ```

4. Review `Reviews/YYYY-MM_reconciliation_review.md` and resolve any `needs_review` accounts.

The extraction from ChatGPT (steps 1–2) is manual by design — there is no supported API to
pull linked-account data automatically. Everything after the export is automated. To run a single
stage by hand instead, see `validate_statement_csvs.py --help`,
`reconcile_manual_vs_linked.py --help`, and `build_finance_dashboard.py --help`.

## Safety

Per the project safety rules: do not paste full account numbers, SSNs, or credentials into
ChatGPT. `account_last4` is sufficient for matching. These CSVs live only in the gitignored
vault, never in the repo.
