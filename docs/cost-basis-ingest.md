# Cost-Basis Ingest (Unrealized Gain/Loss)

The monthly Empower statement carries market value but **no cost basis**, so the pipeline
can't do tax-loss harvesting or capital-gains planning on its own. Empower's separate
**Unrealized Gain Loss** export fills that gap with per-tax-lot cost basis.

## Get the export

In Empower/Pershing, export the account's **Unrealized Gain Loss** report (Excel). The browser
often saves it as `.xlsx` — sometimes with a `.csv` extension, which is fine; the importer reads
it either way. Save it into the vault:

```text
~/ObsidianVaults/second-brain/91_finance/cost_basis/
└── QFA339398_2026-07_unrealized-gl.csv     # raw Empower export (xlsx bytes)
```

This raw file is **Tier 3** — it stays in the gitignored vault and is never added to the ChatGPT
advisor bundle.

## Import

```bash
python3 scripts/import_unrealized_gl.py                 # newest export in cost_basis/
python3 scripts/import_unrealized_gl.py <file> --dry-run
```

The importer:

- reads the preamble (account, as-of date, and the summary totals),
- keeps **only rows with a Taxlot ID** — security-level rollup rows are skipped so gains are not
  double-counted,
- **checksums** the summed lot Gain/Loss against the report's *Net Unrealized Gain/loss* and
  refuses to write on a mismatch,
- writes a normalized per-lot CSV to `Reviews/inputs/cost_basis_<account>.csv`
  (validated by `schemas/empower/unrealized-gain-loss.schema.json`).

Columns: `account_id, as_of_date, asset_category, symbol, security_description, security_type,
quantity, unit_cost, cost_basis, market_value, gain_loss, gain_loss_pct, term, trade_date,
taxlot_id, covered`.

The normalized CSV is **Tier 2** (security names + dollars, no SSN) and is included in the advisor
bundle.

## Integration

`create_tax_strategy_prompt.py` reads the normalized CSV and replaces its "cost basis NOT AVAILABLE"
note with a real section: net unrealized gain/loss, short- vs long-term split, harvestable losses
(paired with the capital-loss carryover), and — for the **revocable** Garcia Family Trust — a flag
that large embedded *long-term* gains favor holding for the §1014 step-up over harvesting. See
[[tax-return-ingest]] and `tax_profile.md`.

## Dependency

Reading the `.xlsx` needs `openpyxl` (in `requirements.txt`). It is imported lazily, so the rest of
the pipeline runs without it.
