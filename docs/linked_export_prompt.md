# Linked-Account Export Prompt

Paste the block below into your ChatGPT Project to export your **live** Plaid-linked accounts as
three CSVs. This is the deliberate *refresh* step: it pulls live data (not the uploaded snapshot).
**State the reporting month** (e.g. 2026-08) when you run it. Save the three files into
`91_finance/Reviews/inputs/`, then run `python3 scripts/monthly_review.py`.

Safety: only `account_last4` is requested — never include full account numbers, SSNs, or
credentials.

```text
Export my currently live Plaid-linked financial accounts as three CSV files I can download,
for reporting month: <STATE THE MONTH, e.g. 2026-08>.

Source-of-truth requirement: Always query my live linked financial data at the time this prompt
is run. Do not use previously uploaded CSVs, static advisor-bundle snapshots, cached exports,
prior conversation results, or historical linked-account snapshots as the source for balances,
holdings, or transactions.

Before exporting:
- Refresh or query the current live linked-account data.
- Use the current live linked accounts and their current account IDs.
- For transactions, query the full requested reporting month directly from the live linked data,
  including dates after any older static export cutoff.
- Do not assume that an uploaded snapshot date is the latest available Plaid date.
- If live data is still syncing or has incomplete coverage, state that clearly rather than
  silently falling back to a static file.
- Do not merge live linked balances with manually uploaded/static account data.
- Do not invent missing data; leave a cell blank if unknown.
- Do not summarize or round — emit raw rows.

Use exactly these headers and column orders:

1) linked_accounts.csv
account_id,account_name,institution,account_type,account_last4,current_value,as_of_date,source
- One row per currently live linked account (checking, savings, credit card, brokerage,
  retirement, loan).
- current_value: numeric, no $ or commas; liabilities (credit cards, loans) negative.
- account_last4: last 4 digits as text.
- as_of_date: the live balance/data date returned for that account; do not substitute an older
  snapshot date.
- source: linked.

2) linked_holdings.csv
account_id,account_name,institution,account_last4,symbol,security_name,quantity,current_price,market_value,as_of_date,source
- Query current investment holdings directly from the live linked brokerage and retirement
  accounts. One row per live position. Preserve raw numeric precision; do not round.
- as_of_date: the position or price date returned by the live source. source: linked.
- If I have no live linked investment positions, output just the header.
- (asset_class is not required — the pipeline infers it from symbol/name.)

3) linked_transactions.csv
transaction_id,account_id,account_name,institution,date,description,merchant_name,amount,category,source
- Query transactions directly from the live linked accounts for the full reporting month above.
- Do not use a previously exported transaction file to determine the month's endpoint.
- Include every available posted transaction in the reporting month.
- Include transfers unless I explicitly ask to exclude them.
- amount: numeric, spending/withdrawals negative and income/deposits positive.
- date: YYYY-MM-DD. source: linked.

Use consistent account_id values from the live linked data across all three files. If a linked
account was added, removed, renamed, or changed since a prior export, use the current live state.

If the live source reports incomplete, partial, recent-only, syncing, or failed coverage for any
requested data, do not fill gaps from old exports. Instead, export only the live rows actually
available and clearly identify the coverage limitation separately.

Create all three CSVs as downloadable files.
```
