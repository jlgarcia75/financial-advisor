#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
ENV_FILE="$REPO_DIR/.env"
LOG_PREFIX="[finance-statements]"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "$LOG_PREFIX Missing .env at $ENV_FILE" >&2
  exit 1
fi

source "$ENV_FILE"

: "${STATEMENTS_DIR:?STATEMENTS_DIR must be set in .env}"
: "${ACCOUNTS_DIR:?ACCOUNTS_DIR must be set in .env}"
: "${REVIEWS_DIR:?REVIEWS_DIR must be set in .env}"

mkdir -p "$STATEMENTS_DIR" "$ACCOUNTS_DIR" "$REVIEWS_DIR" "$REPO_DIR/logs"

MARKITDOWN_BIN="${MARKITDOWN_BIN:-}"
if [[ -z "$MARKITDOWN_BIN" ]]; then
  MARKITDOWN_BIN="$(command -v markitdown || true)"
fi

if [[ -z "$MARKITDOWN_BIN" || ! -x "$MARKITDOWN_BIN" ]]; then
  echo "$LOG_PREFIX markitdown not found. Set MARKITDOWN_BIN in .env or add it to PATH." >&2
  echo "$LOG_PREFIX PATH=$PATH" >&2
  exit 1
fi

echo "$LOG_PREFIX Running at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "$LOG_PREFIX STATEMENTS_DIR=$STATEMENTS_DIR"
echo "$LOG_PREFIX MARKITDOWN_BIN=$MARKITDOWN_BIN"

found_any=false

for pdf in "$STATEMENTS_DIR"/*_statement.pdf(N); do
  found_any=true
  base="${pdf:r}"
  md="${base}.md"

  if [[ -f "$md" ]]; then
    echo "$LOG_PREFIX Skipping existing markdown: ${md:t}"
    continue
  fi

  filename="${pdf:t}"
  statement_id="${filename:r}"
  temp_md="$(mktemp)"

  echo "$LOG_PREFIX Converting: $filename"

  if "$MARKITDOWN_BIN" "$pdf" -o "$temp_md"; then
    {
      echo "---"
      echo "type: financial_statement"
      echo "statement_id: \"$statement_id\""
      echo "source: manual_statement"
      echo "source_file: \"$filename\""
      echo "imported_at: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
      echo "status: needs_review"
      echo "contains_sensitive_financial_data: true"
      echo "---"
      echo
      cat "$temp_md"
    } > "$md"

    echo "$LOG_PREFIX Created: ${md:t}"
  else
    echo "$LOG_PREFIX Failed to convert: $filename" >&2
    rm -f "$temp_md"
    exit 1
  fi

  rm -f "$temp_md"
done

if [[ "$found_any" == false ]]; then
  echo "$LOG_PREFIX No *_statement.pdf files found."
fi
