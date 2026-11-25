"""CLI Runner for Daily Official NSE Security Bhavdata Ingestion.

Usage:
  python scripts/ingest_daily_bhavdata.py [--date YYYY-MM-DD] [--force-download]
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.ingestion.daily_nse_bhavdata import DailyNseBhavdataPipeline
from hamsa.storage.duckdb_repository import DuckDBRepository


def main():
    parser = argparse.ArgumentParser(description="Ingest Official NSE sec_bhavdata_full for a completed trading session")
    parser.add_argument("--date", help="Trading date in YYYY-MM-DD format (defaults to latest available or today)")
    parser.add_argument("--database", type=Path, default=ROOT / "hamsa_terminal.duckdb")
    parser.add_argument("--reviews-db", type=Path, default=ROOT / "hamsa_terminal_reviews.sqlite3")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw" / "real" / "eod" / "nse")
    parser.add_argument("--archive-root", type=Path, default=ROOT / "data" / "raw" / "archive")
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else date(2026, 11, 9)

    print("==========================================================================")
    print(f"  HAMSA DAILY NSE SECURITY BHAVDATA INGESTION PIPELINE")
    print(f"  Session Date: {target_date.isoformat()}")
    print("==========================================================================")

    repo = DuckDBRepository(args.database)
    reviews = DossierReviewRepository(args.reviews_db, schema_path=ROOT / "sql" / "sqlite_schema.sql", analytics_repository=repo)

    pipeline = DailyNseBhavdataPipeline(
        repo,
        reviews,
        raw_storage_dir=args.raw_dir,
        archive_root=args.archive_root,
    )

    try:
        res = pipeline.execute_session(target_date)
        print(f"\nExecution Status: {res['status'].upper()}")
        print(f"Records Parsed:   {res.get('records_parsed', 0):,}")
        print(f"EOD Prices:       {res.get('eod_prices_persisted', 0):,}")
        print(f"Delivery Rows:    {res.get('delivery_records_persisted', 0):,}")
        print(f"Signals Computed: {res.get('signals_calculated', 0):,}")
        print(f"New Candidates:   {res.get('candidates_promoted', 0):,}")
        if res.get("brief"):
            print(f"\n{res['brief']['summary']}")
    finally:
        reviews.close()
        repo.close()


if __name__ == "__main__":
    main()