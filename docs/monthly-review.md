# Monthly Review (one command)

`scripts/monthly_review.py` runs the whole monthly chain so the only thing left to do is paste
the generated prompt into ChatGPT.

## What it does

1. **Process statements** — runs `finance_statements.zsh` (new PDFs → Markdown → CSVs → manifests →
   masters → data quality).
2. **Rebuild the combined view** — runs `ingest_linked_export.py`: validate linked exports →
   reconcile manual vs linked → **dashboard** → **monthly review prompt** → **advisor briefing +
   upload bundle**.
3. **Archive superseded artifacts** — runs `archive_month.py`.

It prints the path to the fresh `YYYY-MM_monthly_review_prompt.md` and the `advisor_bundle/`.

## Monthly ritual

```bash
# 1. Drop new statement PDFs into 91_finance/Statements/ and set each to status: ready.
# 2. Run the ChatGPT linked-account export (docs/linked-account-export.md); save the 3 CSVs
#    into 91_finance/Reviews/inputs/.
# 3. One command:
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
