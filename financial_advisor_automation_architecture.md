# Financial Advisor Automation Architecture

## Purpose

This document tracks the architecture for the `jlgarcia75/financial-advisor` automation stack. The goal is to combine linked financial accounts with manually downloaded statements stored in the Obsidian `second-brain` vault, while keeping the system auditable, repeatable, and safe for financial analysis.

## Current Architecture

```text
GitHub repo: /Users/jesusgarcia/git/financial-advisor
  scripts/        automation and extraction scripts
  schema/         reusable validation schemas
  launchd/        macOS LaunchAgent templates
  logs/           local automation logs, not committed

Obsidian vault: /Users/jesusgarcia/ObsidianVaults/second-brain
  91_finance/
    Statements/   PDFs, MD, CSVs, compact manifests
    Accounts/     account interpretation notes
    Reviews/
      inputs/     consolidated advisor-ready CSVs
      *.md        advisor-generated reviews and decisions
```

## Source-of-Truth Layers

```text
PDF   = original statement source of truth
MD    = human/AI-readable audit copy created by MarkItDown
CSV   = normalized calculation layer
JSON  = compact statement manifest only
Schemas = reusable validation contracts
```

The `*_statement.json` manifest should not contain inline transactions or holdings. It should point to the CSV datasets.

## Existing Automated Pipeline

```text
1. Save PDF into 91_finance/Statements
2. launchd detects folder change
3. finance_statements.zsh runs
4. MarkItDown converts PDF to *_statement.md
5. User reviews MD and sets status: ready
6. Extractor creates normalized CSVs
7. CSVs are validated against schemas
8. create_statement_manifest.py creates compact *_statement.json
9. build_advisor_inputs.py creates master input CSVs in Reviews/inputs
```

## Important Scripts

```text
scripts/finance_statements.zsh
  Main orchestration script called by launchd.

scripts/extract_empower_statement.py
  Extracts accounts, holdings, transactions, and activity from Empower/Pershing MD statements.
  Must only create CSV outputs, not large JSON files.

scripts/validate_statement_csvs.py
  Validates extracted CSVs against reusable schemas.

scripts/create_statement_manifest.py
  Creates compact manifest JSON files from ready MD statements and existing CSVs.

scripts/build_advisor_inputs.py
  Combines all ready manifests into master CSVs for advisor analysis.

scripts/install_launch_agent.zsh
  Installs/reinstalls the LaunchAgent.
```

## Current Output Files Per Statement

For each statement:

```text
YYYY-MM_institution-account-last4_statement.pdf
YYYY-MM_institution-account-last4_statement.md
YYYY-MM_institution-account-last4_statement.json
YYYY-MM_institution-account-last4_statement_accounts.csv
YYYY-MM_institution-account-last4_statement_holdings.csv
YYYY-MM_institution-account-last4_statement_transactions.csv
YYYY-MM_institution-account-last4_statement_activity.csv
```

The compact manifest should look like:

```json
{
  "schema_version": "1.0",
  "statement_id": "2026-01_empower-garciatrust-1234_statement",
  "institution": "empower",
  "provider_or_custodian": "Pershing LLC",
  "statement_type": "multi_account_brokerage",
  "source": "manual_statement",
  "source_files": {
    "pdf": "2026-01_empower-garciatrust-1234_statement.pdf",
    "markdown": "2026-01_empower-garciatrust-1234_statement.md"
  },
  "as_of_date": "2026-01-31",
  "review_status": "ready",
  "datasets": {
    "accounts": "2026-01_empower-garciatrust-1234_statement_accounts.csv",
    "holdings": "2026-01_empower-garciatrust-1234_statement_holdings.csv",
    "transactions": "2026-01_empower-garciatrust-1234_statement_transactions.csv",
    "activity": "2026-01_empower-garciatrust-1234_statement_activity.csv"
  }
}
```

## Schema Strategy

Use stable reusable schemas, not one schema per statement month.

```text
schema/
  statement-manifest.schema.json
  empower/
    accounts.schema.json
    holdings.schema.json
    transactions.schema.json
    activity.schema.json
```

Add a new schema family only when a new statement type has a materially different structure, such as credit card, mortgage, bank, or a different brokerage format.

## Adding a New Statement Type

```text
1. Save one sample PDF into Statements.
2. Let MarkItDown create MD.
3. Inspect sections and identify useful datasets.
4. Bootstrap draft schemas if needed.
5. Write institution-specific extractor.
6. Validate CSV outputs.
7. Add route in finance_statements.zsh.
8. Create compact manifest.
9. Confirm build_advisor_inputs.py includes the new datasets.
10. Document quirks in this architecture file.
```

Recommended extractor contract:

```text
Input:  *_statement.md
Output: *_accounts.csv, *_holdings.csv, *_transactions.csv, *_activity.csv as applicable
Never output large *_statement.json files.
```

## Remaining Automation Steps To Build

### 1. Reconciliation Layer

Create:

```text
scripts/reconcile_manual_vs_linked.py
```

Purpose:

```text
- Compare manual-statement accounts against linked financial accounts.
- Detect likely duplicates by institution, custodian, account name, account last4, balance, holdings, and as_of_date.
- Produce a review CSV/MD with match confidence.
- Prevent double-counting in advisor analysis.
```

Output:

```text
91_finance/Reviews/inputs/manual_linked_reconciliation.csv
91_finance/Reviews/YYYY-MM_reconciliation_review.md
```

Suggested statuses:

```text
manual_only
linked_only
probable_duplicate
confirmed_duplicate
needs_review
```

### 2. Advisor Analysis Input Package

Create a single manifest for the consolidated advisor inputs:

```text
91_finance/Reviews/inputs/advisor_inputs_manifest.json
```

It should point to:

```text
manual_statements_master_accounts.csv
manual_statements_master_holdings.csv
manual_statements_master_transactions.csv
manual_statements_master_activity.csv
manual_linked_reconciliation.csv
```

### 3. Monthly Review Generator

Create:

```text
scripts/create_monthly_review_prompt.py
```

Purpose:

```text
- Read advisor input manifest.
- Summarize available periods and accounts.
- Produce a review-ready Markdown prompt for ChatGPT.
```

Output:

```text
91_finance/Reviews/YYYY-MM_monthly_review_prompt.md
```

### 4. Account Notes Integration

Use account notes in:

```text
91_finance/Accounts/
```

Each account note should define interpretation rules, for example:

```yaml
---
type: financial_account
account_id: QFA339398
institution: empower
provider_or_custodian: Pershing LLC
account_name: The Garcia Family Trust
account_type: trust
source_priority: manual_statement
status: active
---
```

These notes should help the advisor interpret ownership, tax type, household role, and whether to include/exclude an account from certain analyses.

### 5. Data Quality Checks

Add automated checks for:

```text
- Missing account_id on any holding or transaction row
- Missing statement_id
- Missing as_of_date
- Negative or non-numeric market values
- Holdings totals that do not match account totals
- Duplicate rows across statements
- Manifest datasets that point to missing files
- Ready MD files without manifests
- Manifests without CSVs
```

Potential script:

```text
scripts/check_finance_data_quality.py
```

### 6. Reporting Outputs

Generate periodic review files in:

```text
91_finance/Reviews/
```

Suggested files:

```text
YYYY-MM_monthly_financial_review.md
YYYY-MM_portfolio_review.md
YYYY-MM_cash_flow_review.md
YYYY-MM_reconciliation_review.md
YYYY-QN_quarterly_financial_review.md
```

## launchd Notes

Current LaunchAgent label should be:

```text
com.jesus.finance_statements
```

Installed plist:

```text
~/Library/LaunchAgents/com.jesus.finance_statements.plist
```

Only one LaunchAgent should be active. The old hyphenated label should stay removed or disabled:

```text
com.jesus.finance-statements
```

Useful commands:

```bash
launchctl print gui/$(id -u) | grep -E "finance[-_]statements"
launchctl kickstart -k gui/$(id -u)/com.jesus.finance_statements
tail -n 50 logs/finance_statements.out.log
tail -n 50 logs/finance_statements.err.log
```

## Naming Conventions

Use underscores in script names:

```text
finance_statements.zsh
create_statement_manifest.py
build_advisor_inputs.py
validate_statement_csvs.py
extract_empower_statement.py
```

Statement filenames keep hyphens inside descriptive account names if needed, but use a consistent structure:

```text
YYYY-MM_institution-account-last4_statement.ext
```

## Safety Rules

```text
- Do not commit PDFs, MD statements, CSV outputs, manifests, logs, or .env.
- Do commit scripts, schemas, templates, docs, and tests.
- Do not store secrets/API keys in Obsidian.
- Do not expose the whole Obsidian vault to ChatGPT; expose only 91_finance if needed.
- Do not calculate from MD tables when validated CSVs exist.
- Do not double-count manual and linked accounts without reconciliation.
```

Recommended `.gitignore` coverage:

```gitignore
.env
logs/
*.pdf
*_statement.md
*_statement.json
*_accounts.csv
*_holdings.csv
*_transactions.csv
*_activity.csv
manual_statements_master_*.csv
```

## Target End State

```text
Linked accounts
      +
Manual statement CSV master inputs
      +
Account notes
      +
Reconciliation layer
      ↓
Virtual financial advisor
      ↓
Reviews saved back to Obsidian
```

The final system should let the advisor answer questions about net worth, portfolio allocation, spending, cash flow, fees, income, transactions, account ownership, and trends while preserving provenance for every number.
