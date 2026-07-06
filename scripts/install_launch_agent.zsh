#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
ENV_FILE="$REPO_DIR/.env"
TEMPLATE="$REPO_DIR/launchd/com.jesus.finance_statements.plist.template"
TARGET="$HOME/Library/LaunchAgents/com.jesus.finance_statements.plist"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing .env at $ENV_FILE" >&2
  exit 1
fi

source "$ENV_FILE"
: "${STATEMENTS_DIR:?STATEMENTS_DIR must be set in .env}"

mkdir -p "$HOME/Library/LaunchAgents" "$REPO_DIR/logs" "$STATEMENTS_DIR"

# Escape replacement strings for sed.
escape_sed() {
  printf '%s' "$1" | sed 's/[&\\]/\\&/g'
}

REPO_ESC="$(escape_sed "$REPO_DIR")"
HOME_ESC="$(escape_sed "$HOME")"
STATEMENTS_ESC="$(escape_sed "$STATEMENTS_DIR")"

sed \
  -e "s#__REPO_DIR__#$REPO_ESC#g" \
  -e "s#__HOME__#$HOME_ESC#g" \
  -e "s#__STATEMENTS_DIR__#$STATEMENTS_ESC#g" \
  "$TEMPLATE" > "$TARGET"

plutil -lint "$TARGET"

launchctl bootout "gui/$(id -u)" "$TARGET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
launchctl enable "gui/$(id -u)/com.jesus.finance_statements"

echo "Installed LaunchAgent: $TARGET"
launchctl print "gui/$(id -u)/com.jesus.finance_statements" | head -40
