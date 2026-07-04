#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
source "$REPO_DIR/.env"
echo "before mkdri"
mkdir -p "$STATEMENTS_DIR" "$ACCOUNTS_DIR" "$REVIEWS_DIR"
echo $STATEMENTS_DIR

for pdf in "$STATEMENTS_DIR"/*_statement.pdf(N); do
  echo "in for"
  base="${pdf:r}"
  md="${base}.md"

  [[ -f "$md" ]] && continue

  filename="${pdf:t}"
  statement_id="${filename:r}"
  echo $filename
  temp_md="$(mktemp)"

  if markitdown "$pdf" -o "$temp_md"; then
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
  fi

  rm -f "$temp_md"
done