# Account Note Template

Create one note per account in the vault at `91_finance/Accounts/<account-slug>.md`. The
statement answers *what happened*; the account note answers *how to interpret this account*.
These notes drive net-worth inclusion, tax-aware advice, and source precedence during
reconciliation. Frontmatter is validated against `schemas/account-note.schema.json`.

Copy the block below per account and fill it in. Do not put transactions or holdings here.

```markdown
---
type: financial_account
account_id: empower-bda631373
institution: empower
provider_or_custodian: Pershing LLC
account_name: Jesus Garcia ROTH IRA
account_last4: "1234"
account_type: roth_ira
tax_treatment: tax_free
source_priority: manual_statement
include_in_networth: true
owner: Jesus
status: active
---

# Jesus Garcia ROTH IRA

This account appears inside the Empower multi-account brokerage statement.

## Advisor Context

Use holdings for portfolio allocation and retirement-account tracking. Contributions are
after-tax; qualified withdrawals are tax-free — prefer this account for tax-efficient asset
placement of high-growth holdings. Do not merge with household totals unless the analysis
asks for a consolidated household view.
```

## Field guidance

| Field | Notes |
|---|---|
| `account_id` | Must match the `account_id` used in the CSVs so notes join cleanly. |
| `source_priority` | `manual_statement` for Empower/Pershing accounts; `linked` for everything ChatGPT links. When both sources have an account, this decides which wins for the combined view. |
| `tax_treatment` | `taxable` (brokerage), `tax_deferred` (traditional/rollover IRA, 401k), `tax_free` (Roth, HSA), `liability` (credit card, loan, mortgage). |
| `include_in_networth` | Set `false` to keep an account out of net-worth/allocation rollups. |
| `owner` | Household role — used for per-owner and consolidated views. |

## Suggested accounts to create first

One note per real account, e.g. the four Empower sub-accounts (Garcia Family Trust, both
Roth IRAs, the Rollover IRA) plus each linked checking/savings/credit-card account.
