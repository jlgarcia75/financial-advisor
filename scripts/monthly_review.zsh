#!/bin/zsh
# One command for the monthly review: process new statements, rebuild the combined
# view (reconcile -> dashboard -> monthly review prompt -> advisor briefing/bundle),
# then archive superseded prior-month artifacts. Prints the review prompt to paste.
#
# Usage:
#   scripts/monthly_review.zsh                      # use the linked CSVs already in inputs/
#   scripts/monthly_review.zsh --source ~/Downloads/linked   # copy a fresh linked export first
#   scripts/monthly_review.zsh --no-archive         # skip the archive step
set -euo pipefail

REPO_DIR="${0:A:h:h}"
ENV_FILE="$REPO_DIR/.env"
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"

: "${VAULT:=/Users/jesusgarcia/ObsidianVaults/second-brain}"
: "${FINANCE_DIR:=$VAULT/91_finance}"
: "${REVIEWS_DIR:=$FINANCE_DIR/Reviews}"
: "${MARKITDOWN_BIN:=/Users/jesusgarcia/.venv/bin/markitdown}"
# Same interpreter as the statement pipeline (has PyYAML/openpyxl/jsonschema).
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "${MARKITDOWN_BIN:h}/python3" ]]; then
    PYTHON_BIN="${MARKITDOWN_BIN:h}/python3"
  else
    PYTHON_BIN="python3"
  fi
fi

log() { print -r -- "[monthly_review] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

# Split off --no-archive; forward the rest (e.g. --source DIR) to ingest_linked_export.
do_archive=1
forward=()
for a in "$@"; do
  if [[ "$a" == "--no-archive" ]]; then do_archive=0; else forward+=("$a"); fi
done

log "Step 1/3 — process new/ready statements"
zsh "$REPO_DIR/scripts/finance_statements.zsh"

log "Step 2/3 — rebuild combined view (reconcile, dashboard, review prompt, briefing)"
"$PYTHON_BIN" "$REPO_DIR/scripts/ingest_linked_export.py" "${forward[@]}"

if (( do_archive )); then
  log "Step 3/3 — archive superseded prior-month artifacts"
  "$PYTHON_BIN" "$REPO_DIR/scripts/archive_month.py"
else
  log "Step 3/3 — skipped (--no-archive)"
fi

log "Done."
prompts=("$REVIEWS_DIR"/*_monthly_review_prompt.md(Nom))
if (( ${#prompts} )); then
  print -r -- ""
  print -r -- "  ▶ Paste into ChatGPT:  ${prompts[1]}"
  print -r -- "  ▶ Upload bundle:       $REVIEWS_DIR/advisor_bundle/"
fi
