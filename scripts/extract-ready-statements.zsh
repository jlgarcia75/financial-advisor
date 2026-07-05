#!/bin/zsh
# Extract JSON and CSV files for every reviewed statement Markdown file.

set -euo pipefail

REPO_DIR="${0:A:h:h}"
ENV_FILE="$REPO_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
else
  echo "Missing .env. Copy config/local.example.env to .env and edit it." >&2
  exit 1
fi

: "${STATEMENTS_DIR:?STATEMENTS_DIR must be set in .env}"

for md in "$STATEMENTS_DIR"/*_statement.md(N); do
  if grep -qE '^status:[[:space:]]*ready[[:space:]]*$' "$md"; then
    echo "Extracting ${md:t}"
    python3 "$REPO_DIR/scripts/extract_empower_statement.py" "$md"
  else
    echo "Skipping ${md:t}: status is not ready"
  fi
done
