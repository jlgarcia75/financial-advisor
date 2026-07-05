#!/usr/bin/env python3
"""Validate extracted statement JSON files against schema/financial-statement.schema.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    print("Missing dependency: jsonschema. Install with: pip install jsonschema", file=sys.stderr)
    raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate financial statement JSON files.")
    parser.add_argument("json_files", nargs="+", type=Path)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "schema" / "financial-statement.schema.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    failed = False
    for path in args.json_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        if errors:
            failed = True
            print(f"INVALID {path}")
            for err in errors:
                loc = "/".join(str(p) for p in err.path) or "<root>"
                print(f"  - {loc}: {err.message}")
        else:
            print(f"VALID {path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
