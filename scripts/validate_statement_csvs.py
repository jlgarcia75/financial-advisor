#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]

SCHEMA_MAP = {
    "accounts": "accounts.schema.json",
    "holdings": "holdings.schema.json",
    "transactions": "transactions.schema.json",
    "activity": "activity.schema.json",
}


def load_schema(statement_type: str, dataset: str) -> dict:
    candidates = [
        REPO_DIR / "schemas" / statement_type / SCHEMA_MAP[dataset],
        REPO_DIR / "schemas" / "empower" / SCHEMA_MAP[dataset],
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"No schema found for dataset={dataset}, statement_type={statement_type}"
    )


def parse_frontmatter(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    data = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def clean_number(value: str):
    if value is None or value == "":
        return None
    try:
        float(str(value).replace(",", "").replace("$", "").replace("%", ""))
        return True
    except ValueError:
        return False


def clean_date(value: str):
    if value is None or value == "":
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            pass
    return False


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

            ftype = field.get("type", "string")
            if ftype == "number" and clean_number(value) is False:
                errors.append(
                    f"{csv_path.name}: row {i}: {name} is not a number: {value}"
                )
            elif ftype == "date" and clean_date(value) is False:
                errors.append(
                    f"{csv_path.name}: row {i}: {name} is not a date: {value}"
                )

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("statement_md", type=Path)
    args = parser.parse_args()

    md_path = args.statement_md
    fm = parse_frontmatter(md_path)
    statement_type = fm.get("statement_type", "empower-brokerage")
    base = md_path.with_suffix("")

    all_errors = []

    for dataset in SCHEMA_MAP:
        csv_path = base.with_name(f"{base.name}_{dataset}.csv")
        if not csv_path.exists():
            continue

        schema = load_schema(statement_type, dataset)
        all_errors.extend(validate_csv(csv_path, schema))

    if all_errors:
        for err in all_errors:
            print(err, file=sys.stderr)
        sys.exit(1)

    print(f"CSV validation passed for {md_path.name}")


if __name__ == "__main__":
    main()
