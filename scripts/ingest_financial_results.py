"""Archive and ingest local company financial-results or corporate-filings CSVs.

Resolves company/security identity strictly from reviewed ISIN mappings in DuckDB.
Performs no network access.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.ingestion.pipeline import SyntheticFileSpec, SyntheticIngestionPipeline
from hamsa.storage.duckdb_repository import DuckDBRepository


DEFAULT_METRIC_UNITS: dict[str, str] = {
    "revenue": "INR",
    "pat": "INR",
    "roce": "PERCENT",
    "operating_margin": "PERCENT",
    "cfo": "INR",
    "fcf": "INR",
    "capex": "INR",
    "cwip": "INR",
    "gross_block": "INR",
    "market_cap": "INR",
    "net_profit": "INR",
    "cash_flow": "INR",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "processed" / "hamsa.duckdb")
    parser.add_argument("--archive-root", type=Path, default=ROOT / "data" / "raw" / "archive" / "financial-filings")
    parser.add_argument("--source-file", type=Path, required=True, help="Local CSV file in HAMSA financial or corporate-filings format")
    parser.add_argument("--kind", choices=("financial", "corporate_filings"), default="financial")
    parser.add_argument("--provider", choices=("NSE", "BSE"), default="NSE")
    parser.add_argument("--dataset", help="Dataset label; defaults to financial_results or corporate_filings")
    parser.add_argument("--source-identifier", required=True, help="Immutable source document/filing identifier")
    parser.add_argument("--source-document-date", type=date.fromisoformat, required=True)
    parser.add_argument("--publication-date", type=date.fromisoformat, required=True)
    parser.add_argument("--published-at", help="Optional reliable ISO-8601 timestamp with timezone")
    parser.add_argument("--parser-version", default="hamsa-financial-csv-v1")
    parser.add_argument("--metric-units-json", help="Optional JSON object overriding metric->canonical_unit map")
    parser.add_argument("--authorize-local-retention", action="store_true", required=True)
    args = parser.parse_args()

    published_at = datetime.fromisoformat(args.published_at) if args.published_at else None
    metric_units = dict(DEFAULT_METRIC_UNITS)
    if args.metric_units_json:
        metric_units.update(json.loads(args.metric_units_json))
    dataset = args.dataset or ("financial_results" if args.kind == "financial" else "corporate_filings")
    if args.kind == "financial" and not dataset.startswith(("financial_results", "quarterly_results")):
        dataset = f"financial_results_{dataset}"
    elif args.kind == "corporate_filings" and not dataset.startswith("corporate_filings"):
        dataset = f"corporate_filings_{dataset}"

    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.archive_root.mkdir(parents=True, exist_ok=True)
    with DuckDBRepository(args.database) as repo:
        pipeline = SyntheticIngestionPipeline(
            repo,
            archive_root=args.archive_root,
            metric_units=metric_units,
            identity_map=None,
            parser_version=args.parser_version,
        )
        spec = SyntheticFileSpec(
            path=args.source_file,
            dataset=dataset,
            source_identifier=args.source_identifier,
            source_document_date=args.source_document_date,
            publication_date=args.publication_date,
            published_at=published_at,
            source_as_of_date=args.source_document_date,
            parser_version=args.parser_version,
            original_filename=args.source_file.name,
            provider=args.provider,
            license_reference="user-authorized-local-retention;terms-unreviewed",
            license_status="pending",
            retention_authorized=args.authorize_local_retention,
        )
        result = pipeline.ingest_file(spec)
    payload = {
        "source_identifier": result.source_identifier,
        "checksum_sha256": result.checksum_sha256,
        "accepted": result.accepted,
        "rejected": result.rejected,
        "quarantined": result.quarantined,
        "duplicates": result.duplicates,
        "revised": result.revised,
        "out_of_scope": result.out_of_scope,
        "error": result.error,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if result.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
