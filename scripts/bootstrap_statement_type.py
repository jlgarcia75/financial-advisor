#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

SECTION_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

COMMON_FIELDS = [
    {"name": "statement_id", "type": "string", "constraints": {"required": True}},
    {"name": "institution", "type": "string", "constraints": {"required": True}},
    {"name": "statement_type", "type": "string", "constraints": {"required": True}},
    {"name": "as_of_date", "type": "date"},
    {"name": "source_file", "type": "string"},
]

FIELD_HINTS = {
    "accounts": [
        "account_id",
        "account_name",
        "account_type",
        "owner_name",
        "opening_balance",
        "closing_balance",
        "market_value",
    ],
    "holdings": [
        "account_id",
        "account_name",
        "asset_class",
        "security_name",
        "symbol",
        "quantity",
        "price",
        "market_value",
        "cost_basis",
        "date_acquired",
    ],
    "transactions": [
        "account_id",
        "account_name",
        "date",
        "posted_date",
        "description",
        "security_name",
        "symbol",
        "transaction_type",
        "quantity",
        "price",
        "amount",
        "fees",
    ],
    "activity": ["scope", "account_id", "account_name", "period", "metric", "amount"],
}


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def parse_frontmatter(text: str) -> dict:
    match = FRONTMATTER_RE.search(text)
    if not match:
        return {}

    data = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def find_sections(text: str):
    sections = []
    matches = list(SECTION_RE.finditer(text))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        sections.append(
            {
                "level": level,
                "title": title,
                "slug": slugify(title),
                "sample": body[:1200],
            }
        )

    return sections


def classify_statement_type(text: str, frontmatter: dict, sections: list) -> str:
    blob = " ".join([s["title"] for s in sections]).lower() + " " + text[:5000].lower()

    institution = frontmatter.get("institution", "unknown")
    account_type = frontmatter.get("account_type", "")

    if "holdings" in blob or "portfolio" in blob or "dividends" in blob:
        kind = "brokerage"
    elif (
        "minimum payment" in blob
        or "statement balance" in blob
        or "credit limit" in blob
    ):
        kind = "credit_card"
    elif (
        "escrow" in blob
        or "principal" in blob
        or "interest rate" in blob
        or "mortgage" in blob
    ):
        kind = "mortgage"
    elif "checking" in blob or "savings" in blob or "deposits" in blob:
        kind = "bank"
    else:
        kind = account_type or "unknown"

    return f"{slugify(institution)}-{slugify(kind)}"


def table_schema(fields):
    return {
        "fields": COMMON_FIELDS
        + [{"name": field, "type": guess_type(field)} for field in fields],
        "missingValues": [""],
    }


def guess_type(field: str) -> str:
    if field in {"date", "posted_date", "as_of_date", "date_acquired", "date_sold"}:
        return "date"
    if any(
        x in field
        for x in [
            "amount",
            "balance",
            "value",
            "price",
            "basis",
            "quantity",
            "shares",
            "fees",
        ]
    ):
        return "number"
    return "string"


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("statement_md", type=Path)
    parser.add_argument("--schema-root", type=Path, default=Path("schema"))
    parser.add_argument(
        "--config-root", type=Path, default=Path("config/statement-types")
    )
    args = parser.parse_args()

    text = args.statement_md.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(text)
    sections = find_sections(text)

    statement_type = classify_statement_type(text, frontmatter, sections)

    config = {
        "statement_type": statement_type,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "source_sample": str(args.statement_md),
        "frontmatter_detected": frontmatter,
        "sections_detected": [
            {"level": s["level"], "title": s["title"], "slug": s["slug"]}
            for s in sections
        ],
        "recommended_datasets": {
            "accounts": True,
            "holdings": any(
                "holding" in s["title"].lower() or "portfolio" in s["title"].lower()
                for s in sections
            ),
            "transactions": any(
                "transaction" in s["title"].lower() or "activity" in s["title"].lower()
                for s in sections
            ),
            "activity": any(
                "summary" in s["title"].lower() or "activity" in s["title"].lower()
                for s in sections
            ),
        },
        "notes": "Review this file and tighten schemas before using for production validation.",
    }

    write_json(args.config_root / f"{statement_type}.json", config)

    schema_dir = args.schema_root / statement_type

    write_json(
        schema_dir / "accounts.schema.json", table_schema(FIELD_HINTS["accounts"])
    )
    write_json(
        schema_dir / "holdings.schema.json", table_schema(FIELD_HINTS["holdings"])
    )
    write_json(
        schema_dir / "transactions.schema.json",
        table_schema(FIELD_HINTS["transactions"]),
    )
    write_json(
        schema_dir / "activity.schema.json", table_schema(FIELD_HINTS["activity"])
    )


if __name__ == "__main__":
    main()
