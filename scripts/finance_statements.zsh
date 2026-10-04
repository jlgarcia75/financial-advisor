#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
# FINANCE_ENV_FILE lets callers point at a different config (or /dev/null to skip it,
# e.g. in tests); defaults to the repo .env.
ENV_FILE="${FINANCE_ENV_FILE:-$REPO_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
fi

: "${VAULT:=/Users/jesusgarcia/ObsidianVaults/second-brain}"
: "${FINANCE_DIR:=$VAULT/91_finance}"
: "${STATEMENTS_DIR:=$FINANCE_DIR/Statements}"
: "${INPUTS_DIR:=$FINANCE_DIR/Reviews/inputs}"
: "${REVIEWS_DIR:=$FINANCE_DIR/Reviews}"
: "${ACCOUNTS_DIR:=$FINANCE_DIR/Accounts}"
: "${MARKITDOWN_BIN:=/Users/jesusgarcia/.venv/bin/markitdown}"

log() {
  print -r -- "[finance_statements] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
}

fail_file() {
  log "FAILED: ${1:t} — $2"
}

# Options: --rebuild forces the downstream rebuild (dashboard, review prompt, bundle,
# archive) even when no new statement was processed; --no-archive skips archiving;
# --source DIR copies a fresh linked export into inputs first.
force_rebuild=false
do_archive=true
source_dir=""
while (( $# )); do
  case "$1" in
    --rebuild) force_rebuild=true ;;
    --no-archive) do_archive=false ;;
    --source) shift; source_dir="${1:-}" ;;
    *) log "Ignoring unknown argument: $1" ;;
  esac
  shift
done

# Default the interpreter to the same venv markitdown lives in — it has the pipeline
# deps (PyYAML for statement-type routing, openpyxl for cost-basis import). Under the
# LaunchAgent's minimal PATH a bare `python3` is the system Python without them.
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "${MARKITDOWN_BIN:h}/python3" ]]; then
    PYTHON_BIN="${MARKITDOWN_BIN:h}/python3"
  else
    PYTHON_BIN="python3"
  fi
fi

mkdir -p "$STATEMENTS_DIR" "$REPO_DIR/logs"

# Preflight: fail early with an actionable message if the interpreter is missing a
# required dep, rather than mid-run inside a routing/extract step.
if ! "$PYTHON_BIN" -c 'import yaml' 2>/dev/null; then
  log "PYTHON_BIN ($PYTHON_BIN) can't import PyYAML — set PYTHON_BIN in .env to a venv " \
      "that has the deps (pip install -r requirements.txt), e.g. ${MARKITDOWN_BIN:h}/python3" >&2
  exit 1
fi

# flag: did we process a new statement this run?
advisor_inputs_dirty=false

# 1) Convert new PDFs to Markdown.
for pdf in "$STATEMENTS_DIR"/*_statement.pdf(N); do
  base="${pdf:r}"
  md="${base}.md"

  if [[ -f "$md" ]]; then
    continue
  fi

  if [[ ! -x "$MARKITDOWN_BIN" ]]; then
    fail_file "$pdf" "markitdown not found ($MARKITDOWN_BIN); cannot convert PDF"
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
      echo "status: ready"
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

# 2) Extract CSVs for Markdown statements. Every un-processed statement is handled
#    automatically — no manual "status: ready" step. To hold one back, set its
#    frontmatter `status:` to hold / skip / draft / ignore.
for md in "$STATEMENTS_DIR"/*_statement.md(N); do
  base="${md:r}"
  manifest="${base}.json"

  if [[ -f "$manifest" ]]; then
    continue  # already processed
  fi

  if grep -Eiq '^status:[[:space:]]*(hold|skip|draft|ignore)\b' "$md"; then
    log "Holding ${md:t} (frontmatter status marks it on hold); skipping"
    continue
  fi

  log "Processing statement: ${md:t}"

  # Route via the statement-type registry (config/statement_types.yml). The resolver
  # emits eval-able assignments for extractor, inst, stype, and schema_dir.
  extractor="" ; inst="" ; stype="" ; schema_dir=""
  if ! route="$("$PYTHON_BIN" "$REPO_DIR/scripts/resolve_statement_type.py" "$md" --format sh)"; then
    fail_file "$md" "No extractor route for this statement type"
    continue
  fi
  eval "$route"
  log "Routed to $extractor ($inst / $stype)"

  if [[ -f "$REPO_DIR/scripts/$extractor" ]]; then
    "$PYTHON_BIN" "$REPO_DIR/scripts/$extractor" "$md"
  else
    fail_file "$md" "Extractor not found: $extractor"
    continue
  fi

  # 3) Validate CSVs if validator exists.
  if [[ -x "$REPO_DIR/scripts/validate_statement_csvs.py" ]]; then
    log "Validating CSVs for: ${md:t}"
    "$PYTHON_BIN" "$REPO_DIR/scripts/validate_statement_csvs.py" "$md" --schema-dir "$schema_dir"
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

# After processing, rebuild the whole combined view so the dashboard and monthly
# review prompt are always current — no manual step. Runs when a new statement was
# processed, or when --rebuild is passed (e.g. a linked-only refresh).
if [[ "$advisor_inputs_dirty" == true || "$force_rebuild" == true ]]; then
  log "Rebuilding combined view (masters, reconcile, dashboard, review prompt, bundle)"
  ingest_args=( "$REPO_DIR/scripts/ingest_linked_export.py"
                --inputs-dir "$INPUTS_DIR" --reviews-dir "$REVIEWS_DIR"
                --accounts-dir "$ACCOUNTS_DIR" --statements-dir "$STATEMENTS_DIR" )
  [[ -n "$source_dir" ]] && ingest_args+=( --source "$source_dir" )
  if ! "$PYTHON_BIN" "${ingest_args[@]}"; then
    log "FAILED: combined-view rebuild failed" >&2
    exit 1
  fi

  # Data-quality gate on the rebuilt masters (warnings are logged, not fatal).
  if "$PYTHON_BIN" "$REPO_DIR/scripts/check_finance_data_quality.py" \
       --statements-dir "$STATEMENTS_DIR" --inputs-dir "$INPUTS_DIR" --reviews-dir "$REVIEWS_DIR"; then
    log "Data-quality checks passed"
  else
    log "WARNING: data-quality errors; see $REVIEWS_DIR/data_quality_report.md" >&2
  fi

  if [[ "$do_archive" == true ]]; then
    "$PYTHON_BIN" "$REPO_DIR/scripts/archive_month.py" \
      --statements-dir "$STATEMENTS_DIR" --reviews-dir "$REVIEWS_DIR" \
      || log "WARNING: archive step reported a problem" >&2
  fi

  review_prompts=( "$REVIEWS_DIR"/*_monthly_review_prompt.md(Nom) )
  if (( ${#review_prompts} )); then
    log "Done. Paste into ChatGPT: ${review_prompts[1]}"
    log "Upload bundle: $REVIEWS_DIR/advisor_bundle/"
  fi
else
  log "No new statements and no --rebuild; nothing to rebuild."
fi