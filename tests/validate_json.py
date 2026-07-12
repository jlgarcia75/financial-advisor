#!/usr/bin/env python3
"""CI check: every committed JSON parses, and the JSON-Schema files are valid.

The empower/linked schemas are Frictionless-style table descriptors
({"fields": [...]}), not JSON Schema, so they're only parsed. account-note.schema.json
is a real Draft 2020-12 schema and is checked as one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    errors = []
    json_files = sorted(REPO.glob("schemas/**/*.json")) + sorted(REPO.glob("config/**/*.json"))
    schemas_checked = 0
    for path in json_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.relative_to(REPO)}: invalid JSON ({exc})")
            continue
        # Files declaring $schema are JSON Schema (account-note, tax-profile);
        # the empower/linked ones are Frictionless table descriptors — parse only.
        if isinstance(data, dict) and "$schema" in data:
            try:
                from jsonschema import Draft202012Validator
                Draft202012Validator.check_schema(data)
                schemas_checked += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.relative_to(REPO)}: not a valid JSON Schema ({exc})")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(json_files)} JSON file(s) valid; {schemas_checked} JSON Schema(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
