#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
SCRIPTS_DIR="$REPO_DIR/scripts"

cd "$REPO_DIR"

typeset -A RENAMES

# Build rename map first.
for old_path in "$SCRIPTS_DIR"/*-*.(py|zsh|sh)(N); do
  old_name="${old_path:t}"
  new_name="${old_name//-/_}"

  if [[ "$old_name" != "$new_name" ]]; then
    RENAMES[$old_name]="$new_name"
  fi
done

if (( ${#RENAMES[@]} == 0 )); then
  print "No script names need normalization."
  exit 0
fi

print "Planned renames:"
for old_name new_name in ${(kv)RENAMES}; do
  print "  $old_name -> $new_name"
done

print
read "reply?Continue? [y/N] "

if [[ "${reply:l}" != "y" ]]; then
  print "Cancelled."
  exit 0
fi

# Rename with git mv when tracked; otherwise use mv.
for old_name new_name in ${(kv)RENAMES}; do
  old_path="$SCRIPTS_DIR/$old_name"
  new_path="$SCRIPTS_DIR/$new_name"

  if [[ -e "$new_path" ]]; then
    print -u2 "ERROR: target already exists: $new_path"
    exit 1
  fi

  if git ls-files --error-unmatch "scripts/$old_name" >/dev/null 2>&1; then
    git mv "scripts/$old_name" "scripts/$new_name"
  else
    mv "$old_path" "$new_path"
  fi
done

# Update textual references throughout the repo.
for old_name new_name in ${(kv)RENAMES}; do
  grep -IlRZ \
    --exclude-dir=.git \
    --exclude-dir=.venv \
    --exclude-dir=logs \
    -- "$old_name" . |
  while IFS= read -r -d $'\0' file; do
    perl -pi -e "s/\Q${old_name}\E/${new_name}/g" "$file"
    print "Updated reference: $file"
  done
done

print
print "Normalization complete."
print
git status --short