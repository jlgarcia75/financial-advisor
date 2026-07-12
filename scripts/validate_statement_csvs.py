#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import is_date, parse_frontmatter, parse_number  # noqa: E402

REPO_DIR = Path(__file__).resolve().parents[1]

SCHEMA_MAP = {
    "accounts": "accounts.schema.json",
    "holdings": "holdings.schema.json",
    "transactions": "transactions.schema.json",
    "activity": "activity.schema.json",
}


def load_schema(statement_type: str, dataset: str, schema_dir: str | None = None) -> dict:
    candidates = []
    if schema_dir:
        candidates.append(REPO_DIR / "schemas" / schema_dir / SCHEMA_MAP[dataset])
    candidates += [
        REPO_DIR / "schemas" / statement_type / SCHEMA_MAP[dataset],
        REPO_DIR / "schemas" / "empower" / SCHEMA_MAP[dataset],
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"No schema found for dataset={dataset}, statement_type={statement_type}, schema_dir={schema_dir}"
    )


def validate_csv(csv_path: Path, schema: dict) -> list[str]:
    errors = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    headers = set(reader.fieldnames or [])
    fields = schema.get("fields", [])

    for field in fields:
        name = field["name"]
        required = field.get("constraints", {}).get("required", False)
        if required and name not in headers:
            errors.append(f"{csv_path.name}: missing required column {name}")

    for i, row in enumerate(rows, start=2):
        for field in fields:
            name = field["name"]
            if name not in row:
                continue

            value = row.get(name, "")
            required = field.get("constraints", {}).get("required", False)

            if required and value == "":
                errors.append(
                    f"{csv_path.name}: row {i}: required value missing for {name}"
                )

            if value == "":
                continue

            # value is non-empty here (empties are skipped above).
            ftype = field.get("type", "string")
            if ftype == "number" and parse_number(value) is None:
                errors.append(
                    f"{csv_path.name}: row {i}: {name} is not a number: {value}"
                )
            elif ftype == "date" and not is_date(value):
                errors.append(
                    f"{csv_path.name}: row {i}: {name} is not a date: {value}"
                )

    return errors


def _dataset_from_name(name: str) -> str | None:
    """Infer dataset (accounts/holdings/...) from a CSV filename stem."""
    for dataset in SCHEMA_MAP:
        if name.endswith(dataset):
            return dataset
    return None


def validate_linked(csv_paths: list[Path]) -> None:
    all_errors = []
    checked = 0
    for csv_path in csv_paths:
        dataset = _dataset_from_name(csv_path.stem)
        if not dataset:
            print(f"Skipping {csv_path.name}: cannot infer dataset", file=sys.stderr)
            continue
        if not csv_path.exists():
            print(f"Skipping {csv_path}: not found", file=sys.stderr)
            continue
        schema = load_schema("linked", dataset, schema_dir="linked")
        all_errors.extend(validate_csv(csv_path, schema))
        checked += 1

    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        sys.exit(1)
    print(f"CSV validation passed for {checked} linked file(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Validate statement CSVs against reusable schemas."
    )
    parser.add_argument("statement_md", type=Path, nargs="?",
                        help="Statement Markdown whose sibling CSVs to validate.")
    parser.add_argument("--linked", type=Path, nargs="+",
                        help="Validate linked-account CSVs against schemas/linked/.")
    parser.add_argument("--schema-dir",
                        help="Preferred schema subdirectory to check first (e.g. an institution).")
    args = parser.parse_args()

    if args.linked:
        validate_linked(args.linked)
        return

    if not args.statement_md:
        parser.error("provide a statement_md path or --linked <csv...>")

    md_path = args.statement_md
    fm = parse_frontmatter(md_path)
    statement_type = fm.get("statement_type", "empower-brokerage")
    base = md_path.with_suffix("")

    all_errors = []

    for dataset in SCHEMA_MAP:
        csv_path = base.with_name(f"{base.name}_{dataset}.csv")
        if not csv_path.exists():
            continue

        schema = load_schema(statement_type, dataset, schema_dir=args.schema_dir)
        all_errors.extend(validate_csv(csv_path, schema))

    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    print(f"CSV validation passed for {md_path.name}")


if __name__ == "__main__":
    main()
