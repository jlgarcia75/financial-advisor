#!/usr/bin/env python3
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _finance_common import read_json, write_json  # noqa: E402

DEFAULT_STATEMENTS_DIR = Path(
    "/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Statements"
)
DEFAULT_OUTPUT_DIR = Path(
    "/Users/jesusgarcia/ObsidianVaults/second-brain/91_finance/Reviews/inputs"
)

DATASETS = ["accounts", "holdings", "transactions", "activity"]

# One reconciliation CSV, produced by reconcile_manual_vs_linked.py, is included
# in the package when present so downstream tools have a single entry point.
RECONCILIATION_CSV = "manual_linked_reconciliation.csv"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({key for row in rows for key in row.keys()})

    preferred = [
        "statement_id",
        "institution",
        "statement_type",
        "as_of_date",
        "run_date",
        "source_manifest",
        "account_id",
        "account_name",
        "account_type",
        "asset_class",
        "security_name",
        "symbol",
        "date",
        "transaction_section",
        "amount",
        "market_value",
    ]

    ordered = [f for f in preferred if f in fieldnames] + [
        f for f in fieldnames if f not in preferred
    ]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def find_ready_manifests(statements_dir: Path) -> list[Path]:
    manifests = sorted(statements_dir.glob("*_statement.json"))

    ready = []
    for path in manifests:
        try:
            manifest = read_json(path)
        except Exception:
            continue

        if manifest.get("review_status") == "ready":
            ready.append(path)

    return ready


def load_dataset_rows(manifest_path: Path, manifest: dict, dataset: str) -> list[dict]:
    dataset_name = manifest.get("datasets", {}).get(dataset)
    if not dataset_name:
        return []

    csv_path = manifest_path.parent / dataset_name
    if not csv_path.exists():
        print(f"Missing {dataset} CSV: {csv_path}")
        return []

    rows = read_csv(csv_path)

    for row in rows:
        row.setdefault("statement_id", manifest.get("statement_id", ""))
        row.setdefault("institution", manifest.get("institution", ""))
        row.setdefault("statement_type", manifest.get("statement_type", ""))
        row.setdefault("as_of_date", manifest.get("as_of_date", ""))
        row.setdefault("run_date", manifest.get("run_date", ""))
        row["source_manifest"] = manifest_path.name

    return rows


def build_inputs(statements_dir: Path, output_dir: Path) -> None:
    manifests = find_ready_manifests(statements_dir)

    if not manifests:
        print("No ready statement manifests found.")
        return

    combined = {dataset: [] for dataset in DATASETS}

    for manifest_path in manifests:
        manifest = read_json(manifest_path)
        print(f"Loading {manifest_path.name}")

        for dataset in DATASETS:
            combined[dataset].extend(
                load_dataset_rows(manifest_path, manifest, dataset)
            )

    output_dir.mkdir(parents=True, exist_ok=True)

    row_counts = {}
    for dataset, rows in combined.items():
        out_path = output_dir / f"manual_statements_master_{dataset}.csv"
        write_csv(out_path, rows)
        row_counts[dataset] = len(rows)
        print(f"Wrote {out_path} ({len(rows)} rows)")

    write_manifest(output_dir, manifests, combined, row_counts)


def write_manifest(output_dir: Path, manifests: list[Path], combined: dict, row_counts: dict) -> None:
    """Emit advisor_inputs_manifest.json — one entry point tying the masters and
    reconciliation together for the dashboard, review prompt, and the advisor LLM."""
    periods = sorted({
        row.get("as_of_date", "")[:7]
        for row in combined.get("accounts", [])
        if row.get("as_of_date")
    })
    accounts = sorted({
        row.get("account_id", "") or row.get("account_name", "")
        for row in combined.get("accounts", [])
        if row.get("account_id") or row.get("account_name")
    })

    datasets = {
        dataset: f"manual_statements_master_{dataset}.csv"
        for dataset in DATASETS
    }
    reconciliation = (
        RECONCILIATION_CSV if (output_dir / RECONCILIATION_CSV).exists() else None
    )

    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_manifests": [p.name for p in manifests],
        "periods_covered": periods,
        "account_count": len(accounts),
        "row_counts": row_counts,
        "datasets": datasets,
        "reconciliation": reconciliation,
    }
    out = output_dir / "advisor_inputs_manifest.json"
    write_json(out, manifest)
    print(f"Wrote {out}")


def main():
    parser = argparse.ArgumentParser(
        description="Build consolidated advisor input CSVs from ready statement manifests."
    )
    parser.add_argument("--statements-dir", type=Path, default=DEFAULT_STATEMENTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    args = parser.parse_args()
    build_inputs(args.statements_dir, args.output_dir)


if __name__ == "__main__":
    main()
