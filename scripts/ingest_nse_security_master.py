"""Archive and reconcile supplied NSE CM MII masters against schema v3."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hamsa.domain.security import is_valid_isin
from hamsa.ingestion.exchange_master import (
    decode_nse_master_time,
    ingest_nse_mii_file,
    nse_snapshot_date_from_filename,
    parse_nse_mii_master,
)
from hamsa.ingestion.source_registry import register_local_crosscheck_file
from hamsa.storage.duckdb_repository import DuckDBRepository


def _read_equity_list(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if not reader.fieldnames:
            raise ValueError("EQUITY_L file has no header")
        headers = [header.strip() for header in reader.fieldnames]
        required = {"SYMBOL", "ISIN NUMBER"}
        if not required.issubset(headers):
            raise ValueError("EQUITY_L file must contain SYMBOL and ISIN NUMBER")
        return [{(key or "").strip(): (value or "").strip() for key, value in row.items()}
                for row in reader]


def _compare_masters(paths: list[Path]) -> dict[str, object]:
    if len(paths) < 2:
        return {"compared": False}
    earlier = {row.exchange_instrument_id: row for row in parse_nse_mii_master(paths[0])}
    later = {row.exchange_instrument_id: row for row in parse_nse_mii_master(paths[1])}
    common = set(earlier) & set(later)
    changed = []
    all_fields: set[str] = set()
    for instrument_id in common:
        old, new = earlier[instrument_id].source_fields, later[instrument_id].source_fields
        fields = {field for field in set(old) | set(new) if old.get(field) != new.get(field)}
        if fields:
            changed.append(instrument_id)
            all_fields.update(fields)
    return {
        "earlier_file": paths[0].name,
        "later_file": paths[1].name,
        "common_instrument_ids": len(common),
        "added_in_later": len(set(later) - set(earlier)),
        "removed_from_later": len(set(earlier) - set(later)),
        "changed_common_records": len(changed),
        "changed_fields": sorted(all_fields),
    }


def _crosscheck_equity_list(master_path: Path, equity_path: Path) -> dict[str, object]:
    master = parse_nse_mii_master(master_path)
    equity = _read_equity_list(equity_path)
    master_isins: dict[str, set[str]] = {}
    for row in master:
        if row.isin:
            master_isins.setdefault(row.isin.upper(), set()).add(row.symbol or "")
    equity_by_isin = {row["ISIN NUMBER"].upper(): row["SYMBOL"] for row in equity if row.get("ISIN NUMBER")}
    shared = set(master_isins) & set(equity_by_isin)
    return {
        "equity_list_source_file": equity_path.name,
        "equity_list_rows": len(equity),
        "equity_list_unique_isins": len(equity_by_isin),
        "shared_isins": len(shared),
        "shared_isins_with_symbol_match": sum(
            equity_by_isin[isin] in master_isins[isin] for isin in shared
        ),
        "equity_list_valid_isins": sum(is_valid_isin(value) for value in equity_by_isin),
        "eligibility_use": "cross-check only; no admission or platform/class inference",
    }


def run(
    *, database: Path, archive_root: Path, master_paths: list[Path], equity_list: Path,
    retention_authorized: bool, parser_version: str,
) -> dict[str, object]:
    if len(master_paths) != 2:
        raise ValueError("supply exactly the two NSE CM MII files for this reconciliation run")
    archive_root.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, object]] = []
    with DuckDBRepository(database) as repository:
        for path in master_paths:
            source_date = nse_snapshot_date_from_filename(path)
            result = ingest_nse_mii_file(
                repository, path, archive_root=archive_root, source_snapshot_date=source_date,
                parser_version=parser_version, retention_authorized=retention_authorized,
            )
            files.append({
                "filename": path.name,
                "source_file_id": result.source.source_file_id,
                "source_document_id": result.source.source_document_id,
                "source_revision": result.source.revision_number,
                "sha256": result.source.checksum_sha256,
                "archive_path": result.source.archive_path,
                "rows_parsed": (result.report.accepted_records + result.report.unresolved_records +
                                result.report.conflicting_records + result.report.deleted_records +
                                result.report.out_of_scope_records + result.report.rejected_records +
                                result.report.duplicates),
                "accepted_snapshot_rows": result.report.accepted_records,
                "unresolved_rows": result.report.unresolved_records,
                "conflicting_rows": result.report.conflicting_records,
                "deleted_flag_rows": result.report.deleted_records,
                "out_of_scope_rows": result.report.out_of_scope_records,
                "documented_test_rows": result.report.test_instrument_records,
                "source_suspended_rows": result.report.suspended_records,
                "source_not_permitted_to_trade_rows": result.report.not_permitted_records,
                "bse_exclusive_flag_rows": result.report.exchange_exclusive_records,
                "rejected_malformed_rows": result.report.rejected_records,
                "duplicate_rows": result.report.duplicates,
                "quarantine_rows_written": result.report.quarantined,
                "processing_revision_id": result.processing_revision_id,
                "source_snapshot_date_claim": source_date.isoformat(),
            })
        crosscheck = register_local_crosscheck_file(
            repository, equity_list, archive_root=archive_root,
            dataset="NSE-EQUITY-L-crosscheck", source_identifier=equity_list.name,
            retention_authorized=retention_authorized,
            source_origin="user-supplied; file bytes not independently authenticated",
        )
        crosscheck_result = _crosscheck_equity_list(master_paths[1], equity_list)
        crosscheck_result.update({
            "source_file_id": crosscheck.source_file_id,
            "sha256": crosscheck.checksum_sha256,
            "archive_path": crosscheck.archive_path,
            "source_publication_date": None,
        })
        schema_version = repository._connection.execute(
            "SELECT current_version FROM schema_metadata WHERE schema_name=?",
            [repository.SCHEMA_NAME],
        ).fetchone()[0]
    return {
        "schema_version": schema_version,
        "dataset": "official NSE CM MII security files supplied locally; publication not independently verified",
        "files": files,
        "revision_comparison": _compare_masters(master_paths),
        "equity_list_crosscheck": crosscheck_result,
        "admitted_mainboard_ordinary_equity": 0,
        "reason_no_admissions": "No pre-existing reviewed identity mappings were present; instrument/platform eligibility remains unresolved.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cm", action="append", type=Path, required=True,
                        help="NSE_CM_security_DDMMYYYY.csv.gz (supply exactly twice)")
    parser.add_argument("--equity-list", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/hamsa.duckdb")
    parser.add_argument("--archive-root", type=Path, default=ROOT / "data/raw/archive/security-masters")
    parser.add_argument("--parser-version", default="nse-mii-master-v2")
    parser.add_argument("--retain-raw", action="store_true",
                        help="explicitly authorize local archival of the supplied files")
    args = parser.parse_args()
    try:
        result = run(database=args.database, archive_root=args.archive_root,
                     master_paths=args.cm, equity_list=args.equity_list,
                     retention_authorized=args.retain_raw, parser_version=args.parser_version)
    except Exception as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
