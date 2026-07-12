# Obsidian Statement Workflow for Financial Advisor

This document describes the recommended workflow for using an Obsidian vault, local PDF-to-Markdown conversion, GitHub-managed automation scripts, and ChatGPT as part of a virtual financial advisor system.

The goal is to combine:

- Linked financial accounts from ChatGPT/Finances
- Manual financial statements from institutions that cannot connect through Plaid
- Obsidian notes as the human-readable audit layer
- GitHub as the version-controlled automation layer
- ChatGPT as the advisor and analysis layer

## 1. Core Design Principles

Keep the system split into clear layers:

```text
GitHub repo = automation code, scripts, schemas, docs
Obsidian vault = private financial source documents and reviews
ChatGPT/Finances = linked account data and financial analysis
Cloud connector or uploads = controlled access path for reviewed Markdown statements
```

Do not commit private financial statements, converted statement Markdown, normalized financial exports, account numbers, balances, transaction history, or logs containing financial data to GitHub.

## 2. Local Paths

Obsidian vault:

```text
~/second-brain
```

Finance area inside the vault:

```text
~/second-brain/91_finance
```

Recommended two-level structure:

```text
second-brain/
└── 91_finance/
    ├── Statements/
    ├── Accounts/
    └── Reviews/
```

### Folder Purposes

| Folder | Purpose |
|---|---|
| `Statements/` | Original PDF statements and converted Markdown statements. |
| `Accounts/` | One persistent note per account with interpretation rules and context. |
| `Reviews/` | Advisor-generated summaries, monthly reviews, audits, and action plans. |

Keep this structure flat. Use strong filenames and YAML metadata instead of deep folder nesting.

## 3. GitHub Repo Structure

Repository:

```text
jlgarcia75/financial-advisor
```

Recommended repo layout:

```text
financial-advisor/
├── scripts/
│   ├── finance-statements.zsh
│   └── install-launch-agent.zsh
├── launchd/
│   └── com.jesus.finance-statements.plist.template
├── config/
│   └── local.example.env
├── docs/
│   └── obsidian-statement-workflow.md
├── schemas/
│   ├── empower/
│   │   ├── statement-manifest.schema.json
│   │   ├── accounts.schema.json
│   │   ├── holdings.schema.json
│   │   ├── transactions.schema.json
│   │   └── activity.schema.json
│   └── <institution-or-statement-type>/
│       └── ...
├── .gitignore
└── README.md
```

The repo should manage code, templates, docs, schemas, and automation. It should not store actual statements or extracted financial records.

## 4. Git Ignore Rules

Add or verify the following in `.gitignore`:

```gitignore
# Local config
.env
*.local.env

# Financial source documents
*.pdf
*.csv
*.tsv
*.xlsx
*.xls
*.ofx
*.qfx
*.qbo

# Converted sensitive statement docs
*_statement.md
*_statement.json
*_statement.csv

# Logs that may contain financial data
logs/
*.log

# macOS / editor noise
.DS_Store
.vscode/settings.json

# Allow repo documentation
!README.md
!docs/**/*.md
!config/*.example.env
```

If the repo ever needs sample data, use synthetic examples only.

## 5. Filename Convention

Use one deterministic filename pattern for every statement:

```text
YYYY-MM_institution-account-last4_statement.ext
```

Examples:

```text
2026-06_chase-sapphire-1234_statement.pdf
2026-06_chase-sapphire-1234_statement.md

2026-06_fidelity-brokerage-5678_statement.pdf
2026-06_fidelity-brokerage-5678_statement.md

2026-06_sofi-checking-9012_statement.pdf
2026-06_sofi-checking-9012_statement.md
```

The PDF and Markdown filenames should match except for extension.

The filename creates a stable statement ID:

```text
2026-06_chase-sapphire-1234_statement
```

Use this ID for deduplication, audit trails, and advisor references.

## 6. Statement Markdown Frontmatter

Every converted statement Markdown file should start with YAML frontmatter:

```yaml
---
type: financial_statement
statement_id: "2026-06_chase-sapphire-1234_statement"
institution: "chase"
account: "sapphire"
account_last4: "1234"
period: "2026-06"
source: manual_statement
source_file: "2026-06_chase-sapphire-1234_statement.pdf"
imported_at: "2026-07-04T18:30:00Z"
status: needs_review
contains_sensitive_financial_data: true
---
```

Valid statuses:

```text
needs_review
ready
conversion_issue
archived
```

Only statements marked `status: ready` should be used for advisor calculations.

## 7. Account Notes

Create one note per account in:

```text
second-brain/91_finance/Accounts
```

Example filename:

```text
chase-sapphire-1234.md
```

Example account note:

```markdown
---
type: financial_account
account_id: chase-sapphire-1234
institution: chase
account_name: sapphire
account_last4: "1234"
account_type: credit_card
data_source: manual_statement
status: active
---

# Chase Sapphire

This account is imported from monthly statements.

## Advisor Context

Primary personal credit card.

Use for spending and recurring-charge analysis.

Do not treat payments to this account as spending when the underlying credit-card transactions are separately represented.
```

The statement answers: what happened?

The account note answers: how should this account be interpreted?

## 8. Local Config

Create a repo template at:

```text
config/local.example.env
```

Contents:

```bash
VAULT="$HOME/second-brain"
FINANCE_DIR="$VAULT/91_finance"
STATEMENTS_DIR="$FINANCE_DIR/Statements"
ACCOUNTS_DIR="$FINANCE_DIR/Accounts"
REVIEWS_DIR="$FINANCE_DIR/Reviews"
```

Copy it locally to:

```text
.env
```

Do not commit `.env`.

## 9. PDF-to-Markdown Conversion Script

Create:

```text
scripts/finance-statements.zsh
```

Script:

```zsh
#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
source "$REPO_DIR/.env"

mkdir -p "$STATEMENTS_DIR" "$ACCOUNTS_DIR" "$REVIEWS_DIR"

for pdf in "$STATEMENTS_DIR"/*_statement.pdf(N); do
  base="${pdf:r}"
  md="${base}.md"

  # Skip statements already converted.
  if [[ -f "$md" ]]; then
    continue
  fi

  filename="${pdf:t}"
  statement_id="${filename:r}"

  # Expected format: YYYY-MM_institution-account-last4_statement.pdf
  period="${statement_id%%_*}"
  remainder="${statement_id#*_}"
  account_part="${remainder%_statement}"

  institution="${account_part%%-*}"
  account_and_last4="${account_part#*-}"
  account="${account_and_last4%-*}"
  account_last4="${account_and_last4##*-}"

  echo "Converting: $filename"

  temp_md="$(mktemp)"

  if markitdown "$pdf" -o "$temp_md"; then
    {
      echo "---"
      echo "type: financial_statement"
      echo "statement_id: \"$statement_id\""
      echo "institution: \"$institution\""
      echo "account: \"$account\""
      echo "account_last4: \"$account_last4\""
      echo "period: \"$period\""
      echo "source: manual_statement"
      echo "source_file: \"$filename\""
      echo "imported_at: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
      echo "status: needs_review"
      echo "contains_sensitive_financial_data: true"
      echo "---"
      echo
      cat "$temp_md"
    } > "$md"

    echo "Created: ${md:t}"
  else
    echo "FAILED: $filename" >&2
  fi

  rm -f "$temp_md"
done
```

Make it executable:

```bash
chmod +x scripts/finance-statements.zsh
```

Manual test:

```bash
./scripts/finance-statements.zsh
```

## 10. Automated macOS Workflow with launchd

Use `launchd` to run the repo script whenever the `Statements` folder changes.

Create template:

```text
launchd/com.jesus.finance-statements.plist.template
```

Template:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.jesus.finance-statements</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>__REPO_DIR__/scripts/finance-statements.zsh</string>
  </array>

  <key>WatchPaths</key>
  <array>
    <string>__HOME__/second-brain/91_finance/Statements</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>__REPO_DIR__/logs/finance-statements.out.log</string>

  <key>StandardErrorPath</key>
  <string>__REPO_DIR__/logs/finance-statements.err.log</string>
</dict>
</plist>
```

Create installer:

```text
scripts/install-launch-agent.zsh
```

Installer:

```zsh
#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
TEMPLATE="$REPO_DIR/launchd/com.jesus.finance-statements.plist.template"
TARGET="$HOME/Library/LaunchAgents/com.jesus.finance-statements.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$REPO_DIR/logs"

sed \
  -e "s#__REPO_DIR__#$REPO_DIR#g" \
  -e "s#__HOME__#$HOME#g" \
  "$TEMPLATE" > "$TARGET"

launchctl bootout "gui/$(id -u)" "$TARGET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
launchctl enable "gui/$(id -u)/com.jesus.finance-statements"

printf "Installed LaunchAgent: %s\n" "$TARGET"
```

Make executable:

```bash
chmod +x scripts/install-launch-agent.zsh
```

Install:

```bash
./scripts/install-launch-agent.zsh
```

Now the workflow is:

```text
Download statement PDF
  ↓
Move/save into ~/second-brain/91_finance/Statements
  ↓
launchd detects folder change
  ↓
scripts/finance-statements.zsh runs
  ↓
MarkItDown creates Markdown next to PDF
  ↓
Open Markdown in Obsidian
  ↓
Review and set status: ready
```

## 11. Recommended Download Automation

Start simple:

1. Download statements manually from financial institutions.
2. Save them directly to:

```text
~/second-brain/91_finance/Statements
```

Then rename them using the standard filename convention.

Recommended future automation:

- Use a browser download rule, Hazel, Shortcuts, or a small script to detect statement PDFs in `~/Downloads`.
- Rename them into the standard convention.
- Move them to `Statements/`.
- Let `launchd` handle conversion.

Avoid fully automating bank login and statement downloads unless you are using a secure, institution-approved API or trusted tool. Do not store bank credentials in scripts, shell history, plaintext config, or GitHub secrets for this workflow.

## 12. VS Code Workflow

Use VS Code for all repo development.

Recommended tasks:

```text
- edit scripts
- run shellcheck or manual script tests
- install/update launchd agent
- maintain docs
- maintain schemas
```

Suggested VS Code workspace settings should not contain private local paths unless excluded from Git.

Do not commit `.vscode/settings.json` if it contains machine-specific paths.

## 13. ChatGPT Access Options

There are three practical access patterns.

### Option A: Manual Upload to ChatGPT Project

Use this for early testing.

1. Create a ChatGPT Project named `Financial Advisor`.
2. Upload selected `.md` files from:

```text
~/second-brain/91_finance/Statements
```

3. Ask ChatGPT to analyze only files where YAML frontmatter says:

```yaml
status: ready
```

Pros:

- Simple
- Controlled
- Good for testing

Cons:

- Not automatically synced

### Option B: Cloud Folder Mirror

Mirror only:

```text
~/second-brain/91_finance
```

or only:

```text
~/second-brain/91_finance/Statements
```

into a cloud storage provider supported by ChatGPT connectors, such as Google Drive, Dropbox, Box, SharePoint, or OneDrive.

Then connect that storage provider to ChatGPT and grant access only to the finance subset.

Recommended access scope:

```text
91_finance/
├── Statements/
├── Accounts/
└── Reviews/
```

Do not expose your entire `second-brain` vault unless you intentionally want ChatGPT to access unrelated notes.

### Option C: GitHub Connector for Code Only

Connect the GitHub repo for scripts and documentation:

```text
jlgarcia75/financial-advisor
```

Use GitHub for:

- workflow docs
- scripts
- schemas
- templates
- tests

Do not use GitHub for financial source data.

## 14. Recommended ChatGPT Project Instructions

Use instructions like this in the ChatGPT Project:

```text
You are my virtual financial advisor.

Use my linked financial accounts when available.
Use files in 91_finance only as supporting financial documents.
Only treat financial statements with YAML frontmatter `type: financial_statement` and `status: ready` as approved manual statement data.
Ignore statements marked `needs_review`, `conversion_issue`, or `archived` for calculations.
Use files in Accounts as interpretation guidance for account behavior, duplicate handling, and transfer treatment.
Use files in Reviews as prior advisor outputs, not as source transaction data.

When combining linked-account data and manual statements, preserve source provenance.
Do not silently deduplicate. Identify likely duplicates and explain reconciliation assumptions.
Separate linked data, manual statement data, and inferred classifications.
Do not treat credit-card payments as spending if the underlying credit-card transactions are already represented.
Do not treat transfers between my own accounts as income or expenses unless I explicitly say otherwise.
Flag unclear rows for review instead of guessing.
```

## 15. Normalized Data Layer

The Markdown statement is the audit trail, not the database.

Over time, add a normalized layer generated from reviewed Markdown:

```text
second-brain/91_finance/Statements/
2026-06_chase-sapphire-1234_statement.md
```

could produce private local normalized files such as:

```text
2026-06_chase-sapphire-1234_statement_manifest.json
2026-06_chase-sapphire-1234_statement_accounts.csv
2026-06_chase-sapphire-1234_statement_holdings.csv
2026-06_chase-sapphire-1234_statement_transactions.csv
2026-06_chase-sapphire-1234_statement_activity.csv
```

Keep these files out of Git unless they are synthetic samples.

Recommended normalized transaction fields:

```text
statement_id
source_type
institution
account_id
account_last4
period
transaction_date
posted_date
description
merchant
amount
currency
category
source_confidence
raw_text
```

Recommended normalized holding fields:

```text
statement_id
source_type
institution
account_id
account_last4
period
security_name
ticker
quantity
price
market_value
cost_basis
currency
source_confidence
raw_text
```

## 16. Adding New Statement Types and Accounts

Use a repeatable onboarding process whenever you add a new institution, account, or statement format. The goal is to keep Obsidian as the audit layer, CSV as the normalized calculation layer, and the GitHub repo as the versioned automation layer.

### 16.1 Statement Type Registry

Create a lightweight registry in the repo:

```text
financial-advisor/config/statement_types.yml
```

Example:

```yaml
statement_types:
  empower_multi_account_brokerage:
    institution: empower
    statement_kind: multi_account_brokerage
    filename_pattern: "YYYY-MM_empower-*-*_statement.pdf"
    extractor: scripts/extractors/empower_multi_account.py
    schemas:
      manifest: schemas/empower/statement-manifest.schema.json
      accounts: schemas/empower/accounts.schema.json
      holdings: schemas/empower/holdings.schema.json
      transactions: schemas/empower/transactions.schema.json
      activity: schemas/empower/activity.schema.json
    outputs:
      - accounts
      - holdings
      - transactions
      - activity

  generic_credit_card:
    statement_kind: credit_card
    extractor: scripts/extractors/generic_credit_card.py
    schemas:
      manifest: schemas/credit_card/statement-manifest.schema.json
      transactions: schemas/credit_card/transactions.schema.json
      activity: schemas/credit_card/activity.schema.json
    outputs:
      - transactions
      - activity
```

This registry lets automation determine which extractor and schemas to use based on the statement metadata and filename.

### 16.2 Standard Onboarding Checklist

For each new statement type, follow this checklist:

```text
1. Save the original PDF in 91_finance/Statements.
2. Convert it to Markdown with MarkItDown.
3. Inspect the Markdown and identify the document sections and tables.
4. Decide what data is relevant for advisor calculations.
5. Create or update an extractor under scripts/extractors/.
6. Generate sample CSVs from one real reviewed statement.
7. Infer draft schemas from the sample CSVs.
8. Manually tighten schemas and commit them.
9. Validate the generated CSVs against the schemas.
10. Add or update an Account note in 91_finance/Accounts.
11. Mark the statement Markdown as status: ready only after review.
```

Do not regenerate committed schemas every month. Generate schemas once from a high-quality sample, then maintain them by hand.

### 16.3 Choosing the Right Normalized Outputs

Different statement types need different CSV outputs.

| Statement type | Recommended CSVs | Notes |
|---|---|---|
| Checking or savings | `transactions.csv`, `activity.csv` | Focus on cash movement, deposits, withdrawals, fees, and balances. |
| Credit card | `transactions.csv`, `activity.csv` | Include statement balance, minimum payment, due date, APR if available, and transaction rows. |
| Single-account brokerage | `holdings.csv`, `transactions.csv`, `activity.csv` | Include symbol, quantity, price, market value, cost basis, income, buys, sells, fees. |
| Multi-account brokerage | `accounts.csv`, `holdings.csv`, `transactions.csv`, `activity.csv` | Every row must include `account_id` and `account_name`. |
| Mortgage or loan | `liabilities.csv`, `activity.csv` | Track principal, interest rate, payment due date, escrow, fees, and payoff fields. |
| Retirement or HSA | `holdings.csv`, `transactions.csv`, `activity.csv` | Treat like brokerage, but preserve tax/account type metadata. |

For complex brokerage statements, keep the PDF and Markdown as one statement package, but normalize data by sub-account. Never allow holdings or transactions to exist without an `account_id` when a statement contains multiple accounts.

### 16.4 Per-Account Notes for New Accounts

When adding a new account, create or update a note in:

```text
second-brain/91_finance/Accounts/
```

Example:

```markdown
---
type: financial_account
account_id: empower-bda631373
institution: empower
account_name: Jesus Garcia ROTH IRA
account_last4: "1234"
account_type: ira_roth
data_source: manual_statement
statement_type: empower_multi_account_brokerage
status: active
---

# Jesus Garcia ROTH IRA

This account appears inside the Empower multi-account brokerage statement.

## Advisor Context

Use holdings for portfolio allocation and retirement-account tracking.
Do not mix this account with household-level totals unless the analysis asks for consolidated household view.
```

Account notes are interpretation metadata. They should not duplicate every transaction or holding.

### 16.5 Manifest JSON

Each statement package may have one small manifest JSON that points to the normalized CSVs. Do not create JSON duplicates of every CSV unless a downstream system requires it.

Example:

```json
{
  "schema_version": "1.0",
  "statement_id": "2025-12_empower-garciatrust-1234_statement",
  "institution": "empower",
  "statement_type": "empower_multi_account_brokerage",
  "as_of_date": "2025-12-31",
  "source": {
    "pdf": "2025-12_empower-garciatrust-1234_statement.pdf",
    "markdown": "2025-12_empower-garciatrust-1234_statement.md"
  },
  "datasets": {
    "accounts": "2025-12_empower-garciatrust-1234_statement_accounts.csv",
    "holdings": "2025-12_empower-garciatrust-1234_statement_holdings.csv",
    "transactions": "2025-12_empower-garciatrust-1234_statement_transactions.csv",
    "activity": "2025-12_empower-garciatrust-1234_statement_activity.csv"
  },
  "review_status": "ready"
}
```

### 16.6 Extractor Design Pattern

Each extractor should be deterministic and section-aware. It should not depend on an LLM for routine monthly processing once the statement type is supported.

Recommended extractor interface:

```bash
python3 scripts/extractors/empower_multi_account.py \
  --md ~/second-brain/91_finance/Statements/2025-12_empower-garciatrust-1234_statement.md \
  --out ~/second-brain/91_finance/Statements
```

Recommended behavior:

```text
- Read Markdown frontmatter.
- Identify section headings and table blocks.
- Extract only relevant sections.
- Preserve statement_id, institution, period, as_of_date, account_id, account_name, and source_file on every row.
- Write normalized CSVs.
- Write a manifest JSON.
- Validate generated files against the relevant schemas.
- Fail loudly if required fields are missing.
```

### 16.7 Monthly Processing After a Statement Type Exists

Once a statement type has a working extractor and schemas, the monthly workflow is short:

```text
1. Save the PDF using the standard filename.
2. Let MarkItDown create the Markdown.
3. Review the Markdown and set status: ready.
4. Run the matching extractor.
5. Validate CSVs and manifest.
6. Use the CSVs for calculations and reconciliation.
7. Save advisor output in Reviews.
```

The only time you need to revisit schemas or extractor logic is when the institution changes the statement format or you add a materially different account type.

## 17. Security Recommendations

- Do not paste bank credentials, MFA codes, full account numbers, or full SSNs into ChatGPT.
- Do not store financial institution passwords in repo scripts.
- Do not commit financial statements or converted statement Markdown.
- Limit ChatGPT access to `91_finance`, not the entire vault.
- Treat statement Markdown as sensitive because it may contain account identifiers, balances, addresses, and transactions.
- Prefer manual review before setting `status: ready`.
- Preserve original PDFs as the audit source.
- Keep provenance fields on every normalized record.
- Avoid using untrusted PDFs in automated conversion pipelines.

## 18. End-to-End Workflow

```text
1. Develop automation in VS Code
2. Commit scripts/docs/templates to jlgarcia75/financial-advisor
3. Download PDF statement from financial institution
4. Save PDF to ~/second-brain/91_finance/Statements
5. Rename PDF using YYYY-MM_institution-account-last4_statement.pdf
6. launchd runs scripts/finance-statements.zsh
7. MarkItDown creates matching Markdown file
8. Open Markdown in Obsidian
9. Verify statement period, account, balances, transactions, and holdings
10. Change status from needs_review to ready
11. ChatGPT reads ready statement Markdown through Project upload or cloud connector
12. ChatGPT combines manual statements with linked financial accounts
13. Advisor output is saved to ~/second-brain/91_finance/Reviews
```

## 19. Recommended Next Automations

Build these incrementally:

### Phase 1: Conversion Automation

- Done with `launchd` and `finance-statements.zsh`.
- Converts new PDFs into Markdown.
- Adds deterministic YAML frontmatter.

### Phase 2: Filename Validation

Add a script that checks every statement file matches:

```text
YYYY-MM_institution-account-last4_statement.pdf
```

and reports invalid files.

### Phase 3: Metadata Validation

Add a script that checks every `.md` statement has:

```yaml
type: financial_statement
statement_id:
institution:
account:
account_last4:
period:
status:
source_file:
```

### Phase 4: Ready Statement Index

Generate an index file:

```text
second-brain/91_finance/Statements/index.md
```

or:

```text
second-brain/91_finance/Statements/index.json
```

containing only statements marked `status: ready`.

### Phase 5: Normalized Extraction

Add an extraction script that turns reviewed Markdown into normalized local CSV/JSON.

Do not commit extracted real financial data.

### Phase 6: Advisor Review Generation

Use ChatGPT to create periodic review files in:

```text
second-brain/91_finance/Reviews
```

Examples:

```text
2026-06_monthly-financial-review.md
2026-Q2_portfolio-review.md
2026-07_subscription-audit.md
2026-07_debt-review.md
```

## 20. Recommended Final State

```text
second-brain/
└── 91_finance/
    ├── Statements/
    │   ├── 2026-06_chase-sapphire-1234_statement.pdf
    │   ├── 2026-06_chase-sapphire-1234_statement.md
    │   ├── 2026-06_fidelity-brokerage-5678_statement.pdf
    │   └── 2026-06_fidelity-brokerage-5678_statement.md
    │
    ├── Accounts/
    │   ├── chase-sapphire-1234.md
    │   ├── fidelity-brokerage-5678.md
    │   └── sofi-checking-9012.md
    │
    └── Reviews/
        ├── 2026-06_monthly-financial-review.md
        └── 2026-Q2_portfolio-review.md
```

```text
financial-advisor/
├── scripts/
│   ├── finance-statements.zsh
│   └── install-launch-agent.zsh
├── launchd/
│   └── com.jesus.finance-statements.plist.template
├── config/
│   └── local.example.env
├── docs/
│   └── obsidian-statement-workflow.md
├── schemas/
│   ├── empower/
│   │   ├── statement-manifest.schema.json
│   │   ├── accounts.schema.json
│   │   ├── holdings.schema.json
│   │   ├── transactions.schema.json
│   │   └── activity.schema.json
│   └── <institution-or-statement-type>/
│       └── ...
├── .gitignore
└── README.md
```
