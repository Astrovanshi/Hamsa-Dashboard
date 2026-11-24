"""Archive and ingest a local, explicit NSE/BSE calendar CSV."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.ingestion.exchange_calendar import CalendarImportSpec, import_exchange_calendar
from hamsa.storage.duckdb_repository import DuckDBRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange", choices=("NSE", "BSE"), required=True)
    parser.add_argument("--version", required=True, help="Explicit immutable calendar version")
    parser.add_argument("--source-file", type=Path, required=True,
                        help="Original downloaded exchange calendar CSV in the documented explicit-row format")
    parser.add_argument("--source-identifier", required=True, help="Official source URL or published document identifier")
    parser.add_argument("--source-document-date", type=date.fromisoformat, required=True)
    parser.add_argument("--publication-date", type=date.fromisoformat, required=True)
    parser.add_argument("--published-at", help="Reliable timestamp with timezone, ISO 8601")
    parser.add_argument("--source-as-of-date", type=date.fromisoformat)
    parser.add_argument("--parser-version", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--authorize-local-retention", action="store_true",
                        help="Confirm the supplied file may be retained locally; does not assert broader permissions")
    args = parser.parse_args()
    published_at = datetime.fromisoformat(args.published_at) if args.published_at else None
    spec = CalendarImportSpec(
        exchange=args.exchange, calendar_version=args.version,
        source_identifier=args.source_identifier,
        source_document_date=args.source_document_date,
        publication_date=args.publication_date,
        published_at=published_at,
        source_as_of_date=args.source_as_of_date,
        parser_version=args.parser_version,
        retention_authorized=args.authorize_local_retention,
    )
    with DuckDBRepository(args.database) as repository:
        report = import_exchange_calendar(
            repository, args.source_file, archive_root=args.archive_root,
            spec=spec,
        )
    print(json.dumps(asdict(report), default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
