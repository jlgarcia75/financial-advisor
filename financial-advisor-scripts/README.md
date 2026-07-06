# Financial Advisor Statement Extraction Scripts

Copy these files into your `jlgarcia75/financial-advisor` repo.

## Install dependencies

```bash
python3 -m pip install pyyaml jsonschema
```

## Configure

```bash
cp config/local.example.env .env
```

Edit `.env` if your Obsidian vault path differs from:

```text
~/second-brain/91_finance
```

## Workflow

1. Convert a PDF statement to Markdown with your MarkItDown workflow.
2. Review the `.md` in Obsidian.
3. Change frontmatter to:

```yaml
status: ready
```

4. Extract JSON and CSV:

```bash
scripts/extract-ready-statements.zsh
```

Or extract one file:

```bash
python3 scripts/extract-statement.py "$HOME/second-brain/91_finance/Statements/2026-06_chase-sapphire-1234_statement.md"
```

5. Validate the JSON:

```bash
python3 scripts/validate-statement-json.py "$HOME/second-brain/91_finance/Statements/2026-06_chase-sapphire-1234_statement.json"
```

## Outputs

For:

```text
2026-06_chase-sapphire-1234_statement.md
```

The extractor writes:

```text
2026-06_chase-sapphire-1234_statement.json
2026-06_chase-sapphire-1234_statement_transactions.csv
```

## Security

Do not commit statement PDFs, Markdown, JSON, CSV, `.env`, or logs containing financial data.

## Brokerage statement extraction

`extract-statement.py` now detects account type from frontmatter, filename, and statement text. If `account_type` is `brokerage`, `retirement`, or `hsa`, it also writes:

```text
<statement_id>_brokerage.csv
```

This CSV is a first-pass brokerage extraction with fields for `symbol`, `security_name`, `shares`, `price_paid`, `current_price`, `cost_basis`, `market_value`, `proceeds`, `realized_gain_loss`, `date_acquired`, and `date_sold` when those fields are visible in the Markdown conversion.

For best results, set account type explicitly in the statement frontmatter or account note:

```yaml
account_type: brokerage
```

Brokerage statements vary a lot by institution, so review `_brokerage.csv` before import. The script preserves `raw_line` and `confidence` to make review and mapping easier.
