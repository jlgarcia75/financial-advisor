# Tax Profile Template

Create one household tax profile note in the vault at `91_finance/tax_profile.md`. It holds
the tax inputs the pipeline can't derive (filing status, brackets, withholding, carryovers,
current-year constants). `create_tax_strategy_prompt.py` reads it to fill the generated tax
prompt. Frontmatter is validated against `schemas/tax-profile.schema.json`.

Copy the block below and fill it in. Leave a field blank if unknown — the generated prompt
forces the advisor to state its assumptions and mark them `VERIFY` for anything missing.

```markdown
---
type: tax_profile
tax_year: 2026
filing_status: married_filing_jointly
state: ""                      # e.g. CA — used for state-specific + community-property notes
dependents: 0
taxpayers: "Jesus, LeAndra"
entities: "Personal (MFJ); The Garcia Family Trust"
est_agi: ""
marginal_bracket: ""
effective_bracket: ""
ytd_wages: ""
ytd_withholding: ""
estimated_payments_made: ""
prior_year_agi: ""
capital_loss_carryover: ""
charitable_carryover: ""
# Current-year constants from irs.gov (leave blank to force VERIFY tags):
std_deduction: ""
contribution_limit_401k: ""
contribution_limit_ira: ""
contribution_limit_hsa: ""
ltcg_thresholds: ""
---

# Household Tax Profile

Notes on entities, prior-year context, and anything the advisor should know
(e.g. inherited-IRA start year for the 10-year clock, planned charitable gifts).
```

## Field guidance

| Field | Notes |
|---|---|
| `filing_status` | One of the schema enum values (e.g. `married_filing_jointly`). |
| `state` | Drives state-specific and community-property considerations. |
| `entities` | List every return in scope. The Garcia Family Trust is a separate taxpayer. |
| `est_agi` / brackets | Rough is fine; the prompt tags them `[ASSUMPTION]`. |
| `ytd_withholding`, `estimated_payments_made` | Needed for the safe-harbor / quarterly check. |
| carryovers | Prior-year capital-loss and charitable carryovers. |
| constants | Paste from irs.gov for the tax year; blanks become `VERIFY` items. |

## Privacy
Aggregates only — no full account numbers or SSNs. This note lives in the gitignored vault.
