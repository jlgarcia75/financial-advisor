# Prior-Year Tax Return Ingest

Filed returns are one of the best inputs for tax strategy — they give exact figures
(total tax, taxable income, bracket, capital gains/carryovers, qualified dividends, NIIT,
AMT, prior Roth conversions) that the statement pipeline can't derive. Multiple years let
the advisor plan conversions across low vs high years.

## 1. Redact before anything reaches an LLM ⚠️

Tax returns contain identifiers that must never go to ChatGPT. Strip these from the `.md`
before saving it (keep every dollar amount and line item — those are the useful part):

- SSN / ITIN / EIN (taxpayer, spouse, dependents, employers, preparer)
- Full bank account and routing numbers (direct deposit / debit)
- Dates of birth
- Home address, phone, email
- Driver's license / state ID numbers

`account_last4` / masked values are fine. Dependent first names are fine; drop SSNs and DOBs.

## 2. Where the files go

```text
~/ObsidianVaults/second-brain/91_finance/tax_returns/
├── 2023_return.md            # redacted 1040 (+ CA 540) converted to Markdown
├── 2024_return.md
├── 2025_return.md
└── tax_returns_summary.csv   # canonical figures extracted from the returns (see below)
```

These live only in the gitignored vault, never in the repo.

## 3. Canonical summary (`tax_returns_summary.csv`)

One row per filed year, validated by `schemas/tax/return-summary.schema.json`. Only
`tax_year` is required; fill what the return shows and leave the rest blank.

Columns:
`tax_year, filing_status, state, agi, taxable_income, total_tax, effective_rate,
marginal_rate, total_income, wages, taxable_interest, ordinary_dividends,
qualified_dividends, net_st_cap_gain, net_lt_cap_gain, capital_loss_carryover_st,
capital_loss_carryover_lt, roth_conversions, deduction_type, total_deductions,
qbi_deduction, niit, amt, ctc, federal_withholding, estimated_payments, source_doc`

The generated tax prompt embeds a compact multi-year view (AGI, taxable income, total tax,
effective rate, LTCG, qualified dividends, NIIT) and lists the reference docs to attach.

## 4. Workflow

1. Export each filed return to Markdown and **redact** per section 1.
2. Save as `tax_returns/<year>_return.md`.
3. Fill `tax_returns/tax_returns_summary.csv` (I can extract these from the redacted `.md`
   if you share it).
4. Regenerate: `python3 scripts/create_tax_strategy_prompt.py --tax-year <year>` — the prompt
   now includes the prior-year returns section.
5. Update `tax_profile.md` exact figures (e.g. `prior_year_total_tax`) from the latest return.

The advisor reads the summary for trend + the attached redacted returns for full detail.
