"""Import a narrow local TejHQ raw-price Parquet sample; no network access."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.ingestion.tejhq_parquet import TejHQParquetImporter, TejHQPartition
from hamsa.storage.duckdb_repository import DuckDBRepository


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from exc


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("retrieved-at requires an explicit timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="local DuckDB database file")
    parser.add_argument("--archive-root", type=Path, required=True, help="ignored raw archive directory")
    parser.add_argument("--file", type=Path, required=True, help="already-downloaded raw price Parquet file")
    parser.add_argument("--exchange", choices=("NSE", "BSE"), required=True)
    parser.add_argument("--dataset-id", default="tejhq/indian-markets")
    parser.add_argument("--dataset-revision", required=True, help="immutable commit hash, 7-40 hex digits")
    parser.add_argument("--dataset-path", required=True, help="original path inside the dataset, e.g. nse/year=2026/nse_2026.parquet")
    parser.add_argument("--source-document-date", type=_date, required=True)
    parser.add_argument("--first-verified-public-date", type=_date, required=True,
                        help="date-only earliest verified public availability; not trade date")
    parser.add_argument("--retrieval-date", type=_date, required=True,
                        help="date the local file was retrieved; provide actual evidence")
    parser.add_argument("--retrieved-at", type=_timestamp, help="optional sourced retrieval timestamp")
    parser.add_argument("--trade-date", type=_date, required=True)
    parser.add_argument("--symbols", required=True, help="comma-separated bounded pilot rows, at most 10")
    args = parser.parse_args()
    symbols = tuple(item.strip() for item in args.symbols.split(",") if item.strip())
    partition = TejHQPartition(
        path=args.file, exchange=args.exchange, dataset_id=args.dataset_id,
        dataset_revision=args.dataset_revision, original_dataset_path=args.dataset_path,
        source_document_date=args.source_document_date,
        first_verified_public_date=args.first_verified_public_date,
        retrieval_date=args.retrieval_date, retrieved_at=args.retrieved_at,
    )
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.archive_root.mkdir(parents=True, exist_ok=True)
    with DuckDBRepository(args.database) as repository, TejHQParquetImporter(
        repository, archive_root=args.archive_root
    ) as importer:
        report = importer.ingest_pilot(partition, trade_date=args.trade_date, symbols=symbols)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
