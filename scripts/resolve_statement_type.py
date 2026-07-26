#!/usr/bin/env python3
"""Resolve a statement Markdown file to its statement-type route.

Reads config/statement_types.yml (the single source of truth) and matches the
statement's content against each type's `detect` regexes, returning the extractor,
institution, statement_type, and schema_dir the pipeline should use. The zsh
orchestrator plus the validate and manifest tools all consult this, so routing
lives in one place — add a statement type by editing the YAML, not the code.

CLI:
  resolve_statement_type.py <md> --format sh     # eval-able extractor/inst/stype/schema_dir
  resolve_statement_type.py <md> --format json
  resolve_statement_type.py <md> --field extractor
Exit 1 if no type matches, 2 on bad input.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # PyYAML is only needed to read the registry.
    yaml = None

REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_DIR / "config" / "statement_types.yml"

FIELDS = ("extractor", "institution", "statement_type", "schema_dir")


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict:
    if yaml is None:
        raise SystemExit("PyYAML is required to read the statement-type registry (pip install pyyaml).")
    if not path.exists():
        raise SystemExit(f"Statement-type registry not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("statement_types", {})


def resolve_text(text: str, registry: dict) -> dict | None:
    """First statement type whose any `detect` regex matches the text."""
    for key, cfg in registry.items():
        for pattern in cfg.get("detect", []):
            if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                route = {"key": key, "outputs": cfg.get("outputs", [])}
                route.update({f: cfg.get(f, "") for f in FIELDS})
                return route
    return None


def resolve(md_path: Path, registry: dict | None = None) -> dict | None:
    registry = load_registry() if registry is None else registry
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    return resolve_text(text, registry)


def try_resolve(md_path: Path) -> dict | None:
    """Never-raising resolve for callers that fall back to legacy behavior when the
    registry or PyYAML is unavailable."""
    try:
        return resolve(md_path)
    except (SystemExit, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a statement Markdown file to its route via config/statement_types.yml.")
    parser.add_argument("statement_md", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--field", choices=FIELDS + ("key",), help="Print a single field value.")
    parser.add_argument("--format", choices=("sh", "json"), default="sh",
                        help="sh (default): eval-able KEY='value' lines; json: the full route.")
    args = parser.parse_args()

    if not args.statement_md.exists():
        print(f"Statement not found: {args.statement_md}", file=sys.stderr)
        return 2

    route = resolve(args.statement_md, load_registry(args.registry))
    if route is None:
        print(f"No statement-type route matched {args.statement_md.name}", file=sys.stderr)
        return 1

    if args.field:
        print(route.get(args.field, ""))
    elif args.format == "json":
        import json
        print(json.dumps(route))
    else:  # sh — uses the variable names finance_statements.zsh expects
        print(f"extractor='{route['extractor']}'")
        print(f"inst='{route['institution']}'")
        print(f"stype='{route['statement_type']}'")
        print(f"schema_dir='{route['schema_dir']}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
