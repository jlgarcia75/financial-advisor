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
  print -r -- "[finance_statements] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
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
# flag for creating advisor inputs manifest if any new statements are processed
advisor_inputs_dirty=false

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

  # Institution-specific extractor routing. Each branch sets the extractor plus the
  # institution and statement_type used for the manifest.
  extractor="" ; inst="" ; stype=""
  if grep -Eiq '^institution:[[:space:]]*empower|Empower Monthly Report|provider_or_custodian:[[:space:]]*Pershing' "$md"; then
    log "Detected Empower/Pershing statement"
    extractor="extract_empower_statement.py" ; inst="empower" ; stype="multi_account_brokerage"
  elif grep -Eiq '^institution:[[:space:]]*central-lending|Capital Account Statement|Central Florida Income Fund|Central Lending' "$md"; then
    log "Detected Central Lending capital-account statement"
    extractor="extract_central_lending.py" ; inst="central-lending" ; stype="central-lending-capital-account"
  else
    fail_file "$md" "No extractor route for this statement type"
    continue
  fi

  if [[ -f "$REPO_DIR/scripts/$extractor" ]]; then
    "$PYTHON_BIN" "$REPO_DIR/scripts/$extractor" "$md"
  else
    fail_file "$md" "Extractor not found: $extractor"
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
    "$PYTHON_BIN" "$REPO_DIR/scripts/create_statement_manifest.py" "$md" --institution "$inst" --statement-type "$stype"
    # Advisor inputs manifest needs to be updated since a new statement was processed
    advisor_inputs_dirty=true
  else
    fail_file "$md" "create_statement_manifest.py not found"
    continue
  fi

  log "Completed pipeline for: ${md:t}"
done

# Rebuild consolidated advisor inputs once, after all new statements are processed
# (not per-statement), then gate on data quality.
if [[ "$advisor_inputs_dirty" == true ]]; then
  log "Rebuilding consolidated advisor inputs"

  if "$PYTHON_BIN" "$REPO_DIR/scripts/build_advisor_inputs.py"; then
    log "Advisor inputs rebuilt successfully"
  else
    log "FAILED: Advisor input rebuild failed" >&2
    exit 1
  fi

  # Gate: run data-quality checks after rebuilding masters. Warnings are logged;
  # hard errors are logged but do not abort (the report captures the detail).
  if [[ -f "$REPO_DIR/scripts/check_finance_data_quality.py" ]]; then
    log "Running data-quality checks"
    if "$PYTHON_BIN" "$REPO_DIR/scripts/check_finance_data_quality.py"; then
      log "Data-quality checks passed"
    else
      log "WARNING: Data-quality checks reported errors; see Reviews/data_quality_report.md" >&2
    fi
  fi
else
  log "Advisor inputs unchanged; rebuild not required"
fi