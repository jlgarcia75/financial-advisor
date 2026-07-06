#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
ENV_FILE="$REPO_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
fi

: "${VAULT:=/Users/jesusgarcia/ObsidianVaults/second-brain}"
: "${FINANCE_DIR:=$VAULT/91_finance}"
: "${STATEMENTS_DIR:=$FINANCE_DIR/Statements}"
: "${MARKITDOWN_BIN:=/Users/jesusgarcia/.venv/bin/markitdown}"
: "${PYTHON_BIN:=python3}"

mkdir -p "$STATEMENTS_DIR" "$REPO_DIR/logs"

log() {
  print -r -- "[finance-statements] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

fail_file() {
  local file="$1"
  local reason="$2"
  log "FAILED: ${file:t} — $reason"
}

if [[ ! -x "$MARKITDOWN_BIN" ]]; then
  log "markitdown not found or not executable: $MARKITDOWN_BIN" >&2
  exit 1
fi

# 1) Convert new PDFs to Markdown.
for pdf in "$STATEMENTS_DIR"/*_statement.pdf(N); do
  base="${pdf:r}"
  md="${base}.md"

  if [[ -f "$md" ]]; then
    continue
  fi

  filename="${pdf:t}"
  statement_id="${filename:r}"
  temp_md="$(mktemp)"

  log "Converting PDF to MD: $filename"

  if "$MARKITDOWN_BIN" "$pdf" -o "$temp_md"; then
    {
      echo "---"
      echo "type: financial_statement"
      echo "statement_id: \"$statement_id\""
      echo "source: manual_statement"
      echo "source_file: \"$filename\""
      echo "institution: unknown"
      echo "statement_type: unknown"
      echo "imported_at: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
      echo "status: needs_review"
      echo "contains_sensitive_financial_data: true"
      echo "---"
      echo
      cat "$temp_md"
    } > "$md"

    log "Created MD: ${md:t}"
  else
    fail_file "$pdf" "MarkItDown conversion failed"
  fi

  rm -f "$temp_md"
done

# 2) Extract CSVs for ready Markdown statements.
for md in "$STATEMENTS_DIR"/*_statement.md(N); do
  base="${md:r}"
  manifest="${base}.json"

  if ! grep -Eq '^status:[[:space:]]*ready|^review_status:[[:space:]]*ready' "$md"; then
    continue
  fi

  if [[ -f "$manifest" ]]; then
    log "Skipping ready statement with existing manifest: ${manifest:t}"
    continue
  fi

  log "Processing ready statement: ${md:t}"

  # Institution-specific extractor routing.
  if grep -Eiq '^institution:[[:space:]]*empower|Empower Monthly Report|provider_or_custodian:[[:space:]]*Pershing' "$md"; then
    log "Detected Empower/Pershing statement"

    if [[ -x "$REPO_DIR/scripts/extract_empower_statement.py" ]]; then
      "$PYTHON_BIN" "$REPO_DIR/scripts/extract_empower_statement.py" "$md"
    elif [[ -x "$REPO_DIR/scripts/empower_statement_extractor.py" ]]; then
      "$PYTHON_BIN" "$REPO_DIR/scripts/empower_statement_extractor.py" "$md"
    else
      fail_file "$md" "No Empower extractor found"
      continue
    fi
  else
    fail_file "$md" "No extractor route for this statement type"
    continue
  fi

  # 3) Validate CSVs if validator exists.
  if [[ -x "$REPO_DIR/scripts/validate_statement_csvs.py" ]]; then
    log "Validating CSVs for: ${md:t}"
    "$PYTHON_BIN" "$REPO_DIR/scripts/validate_statement_csvs.py" "$md"
  else
    log "No validate_statement_csvs.py found; skipping CSV validation"
  fi

  # 4) Create compact manifest JSON.
  if [[ -f "$REPO_DIR/scripts/create_statement_manifest.py" ]]; then
    log "Creating manifest for: ${md:t}"
    "$PYTHON_BIN" "$REPO_DIR/scripts/create_statement_manifest.py" "$md" --institution empower
  else
    fail_file "$md" "create_statement_manifest.py not found"
    continue
  fi

  log "Completed pipeline for: ${md:t}"
done