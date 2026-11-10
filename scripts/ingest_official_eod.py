"""Ingest user-downloaded official NSE/BSE EOD files; makes no network calls."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.ingestion.pipeline import SyntheticFileSpec, SyntheticIngestionPipeline  # noqa: E402
from hamsa.storage.duckdb_repository import DuckDBRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "real_eod.local.json")
    parser.add_argument("--trade-date", required=True, help="EOD session date, YYYY-MM-DD")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "processed" / "hamsa.duckdb")
    parser.add_argument("--archive", type=Path, default=ROOT / "data" / "raw" / "archive")
    parser.add_argument("--nse-udiff", type=Path)
    parser.add_argument("--nse-delivery", type=Path)
    parser.add_argument("--bse-prices", type=Path)
    args = parser.parse_args()
    trade_day = date.fromisoformat(args.trade_date)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    identity_map = {str(isin).upper(): tuple(ids) for isin, ids in config["identity_map"].items()}
    pipeline = None
    args.database.parent.mkdir(parents=True, exist_ok=True)
    repo = DuckDBRepository(args.database)
    try:
        pipeline = SyntheticIngestionPipeline(repo, archive_root=args.archive,
            metric_units={"revenue": "INR"}, identity_map=identity_map,
            parser_version=config["parser_version"])
        specs = []
        # Exchange page does not provide a reliable publication timestamp in
        # these downloaded files. Use the actual local ingestion day as a
        # conservative date-only availability bound, never the historical
        # trade date as an assumed publication date.
        availability_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        common = {"source_document_date": trade_day, "publication_date": availability_date,
                  "published_at": None, "source_as_of_date": trade_day,
                  "parser_version": config["parser_version"],
                  "license_reference": "user-directed personal EOD research; terms not independently adjudicated",
                  "license_status": "pending", "retention_authorized": True}
        if args.nse_udiff:
            specs.append(SyntheticFileSpec(path=args.nse_udiff, dataset="nse_udiff_eod",
                source_identifier=args.nse_udiff.name, provider="NSE", original_filename=args.nse_udiff.name,
                parser_options={"series_allowlist": config["nse_series_allowlist"],
                    "isin_allowlist": config.get("nse_isin_allowlist")}, **common))
        if args.nse_delivery:
            specs.append(SyntheticFileSpec(path=args.nse_delivery, dataset="nse_delivery",
                source_identifier=args.nse_delivery.name, provider="NSE", original_filename=args.nse_delivery.name,
                parser_options={"symbols_allowlist": config.get("nse_delivery_symbols_allowlist")}, **common))
        if args.bse_prices:
            mapping = config["bse_listing_mapping"]
            if date.fromisoformat(mapping["effective_from"]) > trade_day:
                raise ValueError("BSE listing mapping is not effective on the requested trade date")
            specs.append(SyntheticFileSpec(path=args.bse_prices, dataset="bse_stock_prices_eod",
                source_identifier=args.bse_prices.name, provider="BSE", original_filename=args.bse_prices.name,
                parser_options={"listing_mapping": mapping}, **common))
        if not specs:
            parser.error("provide at least one of --nse-udiff, --nse-delivery, or --bse-prices")
        report = pipeline.ingest_files(specs)
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return 1 if any(item.error for item in report.files) else 0
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
