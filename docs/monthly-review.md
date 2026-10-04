# Monthly Review

## Statements process themselves

You do **not** set `status: ready` or run anything to ingest a statement. Drop a statement
(PDF or Markdown) into `91_finance/Statements/` and the `finance_statements` LaunchAgent runs the
full chain automatically: convert → extract → validate → masters → data-quality → **dashboard** →
**monthly review prompt** → **advisor briefing/bundle** → archive superseded months. The fresh
`YYYY-MM_dashboard.md` and `YYYY-MM_monthly_review_prompt.md` just appear in `Reviews/`.

To hold a statement back from processing, set its frontmatter `status:` to `hold` (or `skip` /
`draft` / `ignore`).

## `monthly_review.py` — on-demand refresh

`scripts/monthly_review.py` runs the same chain by hand — use it after a fresh **linked export**
(which is manual), or any time you want to force a rebuild without dropping a statement. It wraps
`finance_statements.zsh --rebuild`, which:

1. **Processes statements** — convert → extract → validate → masters → data quality (no `ready` step).
2. **Rebuilds the combined view** — reconcile (if linked data present) → **dashboard** →
   **monthly review prompt** → **advisor briefing + upload bundle**.
3. **Archives superseded artifacts** — `archive_month.py`.

It prints the path to the fresh `YYYY-MM_monthly_review_prompt.md` and the `advisor_bundle/`.

## Monthly ritual

```bash
# 1. Drop new statement PDFs into 91_finance/Statements/ — they process automatically.
# 2. Run the ChatGPT linked-account export (docs/linked-account-export.md); save the 3 CSVs
#    into 91_finance/Reviews/inputs/.
# 3. Refresh so the dashboard/prompt pick up the new linked data:
python3 scripts/monthly_review.py
# 4. Paste the printed monthly_review_prompt.md into your ChatGPT Project and upload the bundle.
```

Flags: `--source <dir>` — only if you saved the CSVs somewhere other than `Reviews/inputs/`;
it copies them in first. `--no-archive` skips the archive step.

The interpreter comes from `PYTHON_BIN` (defaults to the venv `markitdown` uses), so it has the
deps. See `config/local.example.env`.

## Archiving

`archive_month.py` keeps the active folders showing only the latest of each artifact. A dated file
(`YYYY-MM_…`) is archived **only when a newer-month file of the same kind exists**:

- superseded statements → `Statements/Archive/YYYY-MM/`
- superseded dated Reviews outputs (dashboard, review prompt, reconciliation review) →
  `Reviews/Archive/YYYY-MM/`

Because it only moves *superseded* files, the latest statement of every account and the current
month's review always stay put — it's safe to run any time, and idempotent. Archived statements are
still read into the masters (`build_advisor_inputs.py` reads `Statements/` recursively), so
cash-flow history is preserved. Rolling-latest files (`NET_WORTH_snapshot.csv`, `ADVISOR_BRIEFING.md`,
the year-based tax prompt, `inputs/`, `advisor_bundle/`) have no month prefix and are never touched.

Run `archive_month.py --dry-run` to preview moves.

## Data-quality signals

- **Staleness:** `check_finance_data_quality.py` flags any account whose as-of date lags the
  freshest data by more than 45 days (catches e.g. a quarterly fund statement that hasn't been
  refreshed). It's a warning, not a hard error.
- **Linked history:** each ingest snapshots the three `linked_*.csv` into
  `Reviews/inputs/linked_history/<YYYY-MM>/`, so month-over-month linked history accrues even though
  the live files are overwritten.
- **Account coverage:** the monthly review prompt labels manual-statement counts separately from the
  combined (manual + linked) account count, so "8 accounts" isn't mistaken for total coverage.
