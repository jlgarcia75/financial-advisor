#!/usr/bin/env python3
# scripts/infer_csv_schema.py

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REQUIRED_BY_NAME = {
    "statement_id",
    "institution",
    "as_of_date",
    "account_id",
    "account_name",
}


def looks_int(v):
    try:
        int(v.replace(",", ""))
        return True
    except Exception:
        return False


def looks_number(v):
    try:
        float(v.replace(",", "").replace("$", "").replace("%", ""))
        return True
    except Exception:
        return False


def looks_date(v):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            datetime.strptime(v, fmt)
            return True
        except Exception:
            pass
    return False


def infer_type(values):
    values = [v.strip() for v in values if v and v.strip()]
    if not values:
        return "string"

    if all(looks_date(v) for v in values):
        return "date"
    if all(looks_int(v) for v in values):
        return "integer"
    if all(looks_number(v) for v in values):
        return "number"
    return "string"


def infer_schema(csv_path: Path):
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fields = []
    for col in reader.fieldnames or []:
        sample_values = [row.get(col, "") for row in rows[:500]]
        field = {"name": col, "type": infer_type(sample_values)}

        if col in REQUIRED_BY_NAME:
            field["constraints"] = {"required": True}

        fields.append(field)

    return {"fields": fields, "missingValues": [""]}


def main():
    if len(sys.argv) < 3:
        print("Usage: infer_csv_schema.py input.csv output.schema.json")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    schema = infer_schema(csv_path)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
