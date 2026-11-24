"""Discover, archive, and ingest NSE XBRL company financial filings into DuckDB.

Supports both live NSE XBRL discovery/caching (`--symbols`) and offline local
XBRL directory/file ingestion (`--local-dir` or `--local-file`).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.ingestion.nse_xbrl import (
    XbrlIngestionSummary,
    fetch_and_ingest_symbols,
    ingest_local_xbrl_file,
)
from hamsa.storage.duckdb_repository import DuckDBRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "processed" / "hamsa.duckdb")
    parser.add_argument("--archive-root", type=Path, default=ROOT / "data" / "raw" / "archive" / "nse-xbrl")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "raw" / "real" / "xbrl")
    parser.add_argument("--symbols", help="Comma-separated NSE symbols to fetch and ingest")
    parser.add_argument("--local-dir", type=Path, help="Ingest already-downloaded XBRL files with .meta.json sidecars")
    parser.add_argument("--min-period-end", type=date.fromisoformat, default=date(2022, 3, 31))
    parser.add_argument("--preferred-scope", choices=("consolidated", "standalone"))
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--authorize-local-retention", action="store_true", required=True)
    args = parser.parse_args()

    if not args.symbols and not args.local_dir:
        parser.error("Provide either --symbols or --local-dir")

    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.archive_root.mkdir(parents=True, exist_ok=True)

    with DuckDBRepository(args.database) as repo:
        if args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            summary = fetch_and_ingest_symbols(
                repo,
                symbols,
                download_cache_dir=args.cache_dir,
                archive_root=args.archive_root,
                min_period_end=args.min_period_end,
                preferred_scope=args.preferred_scope,
                delay_seconds=args.delay_seconds,
            )
        else:
            summary = XbrlIngestionSummary()
            for meta_path in sorted(args.local_dir.rglob("*.meta.json")):
                xml_path = meta_path.with_suffix("")
                if not xml_path.is_file():
                    continue
                summary.filings_processed += 1
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                pub_at = datetime.fromisoformat(meta["published_at"]) if meta.get("published_at") else None
                try:
                    acc, rev, quar = ingest_local_xbrl_file(
                        repo,
                        xml_path,
                        archive_root=args.archive_root,
                        source_identifier=str(meta["source_identifier"]),
                        source_document_date=date.fromisoformat(str(meta["period_end"])),
                        publication_date=date.fromisoformat(str(meta["publication_date"])),
                        published_at=pub_at,
                        fallback_symbol=meta.get("symbol"),
                        fallback_scope=meta.get("reporting_scope"),
                        retention_authorized=args.authorize_local_retention,
                        source_url=meta.get("xbrl_url"),
                    )
                    if quar > 0:
                        summary.filings_quarantined += 1
                    elif acc == 0 and rev == 0:
                        summary.filings_duplicated += 1
                    else:
                        summary.filings_succeeded += 1
                        summary.observations_accepted += acc
                        summary.observations_revised += rev
                except Exception as exc:
                    summary.filings_failed += 1
                    summary.errors.append(f"{xml_path.name}: {exc}")

    print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
