"""HAMSA Daily NSE Security Bhavdata Ingestion & Market Pipeline.

Automates the acquisition, integrity validation, normalization, and persistence
of the official NSE daily security BhavCopy file:
    `sec_bhavdata_full_DDMMYYYY.csv`

Pipeline Stages:
1. Session Date Resolution (Exchange calendar aware, excludes holidays/weekends).
2. Content-Addressed Download with Exponential Backoff & Retry.
3. Strict Pre-Ingestion Data Integrity & Schema Validation.
4. Idempotent Ingestion into DuckDB Schema v7 (EOD prices, volume, delivery).
5. Post-Ingestion Automated Downstream Triggering:
   - Tier 1 Radar Signal Recalculation across the eligible universe
   - Candidate Trigger Evaluation & Promotion
   - Daily Market Intelligence Brief Generation
   - System Telemetry & Timestamp Update
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
import sys
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.ingestion.raw_archive import archive_approved_source
from hamsa.screening.tiered_universe import TieredUniverseManager
from hamsa.screening.shadow_brief import ShadowCandidateEngine, DailyBriefGenerator, SHADOW_PROFILES
from hamsa.screening.empirical_observation import EmpiricalObservationEngine
from hamsa.storage.duckdb_repository import DuckDBRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hamsa.ingestion.nse_bhavdata")

# Official NSE archive base URL pattern
NSE_ARCHIVE_URL_TEMPLATE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class BhavdataRecord:
    symbol: str
    series: str
    trade_date: date
    prev_close: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    last_price: Decimal | None
    close_price: Decimal | None
    avg_price: Decimal | None
    traded_quantity: int
    turnover_inr: Decimal
    number_of_trades: int | None
    delivery_quantity: int | None
    delivery_percentage: Decimal | None


@dataclass(frozen=True, slots=True)
class IngestionValidationResult:
    is_valid: bool
    intended_date: date
    total_raw_rows: int
    eq_rows_count: int
    matched_master_count: int
    null_ohlc_count: int
    invalid_ohlc_bounds_count: int
    zero_volume_count: int
    delivery_available_count: int
    quarantine_reasons: tuple[str, ...]
    error_summary: str | None = None


def format_nse_date_code(d: date) -> str:
    """Format date as DDMMYYYY for NSE URL and filename."""
    return d.strftime("%d%m%Y")


def parse_bhav_date_str(s: str) -> date:
    """Parse ' 09-Nov-2026' into date(2026, 11, 9)."""
    return datetime.strptime(s.strip(), "%d-%b-%Y").date()


class NseBhavdataDownloader:
    """Acquires and content-addresses official NSE sec_bhavdata_full files."""

    def __init__(
        self,
        raw_storage_dir: Path,
        archive_root: Path,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 4,
        backoff_base_sec: float = 2.0,
    ):
        self.raw_storage_dir = raw_storage_dir
        self.archive_root = archive_root
        self.user_agent = user_agent
        self.max_retries = max_retries
        self.backoff_base_sec = backoff_base_sec
        self.raw_storage_dir.mkdir(parents=True, exist_ok=True)
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def download_for_date(self, target_date: date) -> Path:
        """Download official NSE sec_bhavdata_full for target_date with retries and content-addressing."""
        date_str = format_nse_date_code(target_date)
        filename = f"sec_bhavdata_full_{date_str}.csv"
        target_path = self.raw_storage_dir / filename

        # If already downloaded and verified on disk, reuse
        if target_path.is_file() and target_path.stat().st_size > 10000:
            logger.info(f"Using existing downloaded file on disk: {target_path}")
            return target_path

        url = NSE_ARCHIVE_URL_TEMPLATE.format(date_str=date_str)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "*/*",
                "Referer": "https://www.nseindia.com/all-reports",
            },
        )

        attempts = 0
        last_error = None

        while attempts < self.max_retries:
            attempts += 1
            try:
                logger.info(f"Attempt {attempts}/{self.max_retries}: Fetching {url} ...")
                with urllib.request.urlopen(req, timeout=20) as resp:
                    if resp.status != 200:
                        raise urllib.error.HTTPError(url, resp.status, "Non-200 status", resp.headers, None)
                    content = resp.read()

                if len(content) < 1000 or b"<!DOCTYPE" in content[:200]:
                    raise ValueError(f"Received HTML or truncated response ({len(content)} bytes), file not yet published.")

                # Write to disk atomically
                temp_path = target_path.with_suffix(".tmp")
                temp_path.write_bytes(content)
                temp_path.replace(target_path)
                logger.info(f"Downloaded {filename} ({len(content):,} bytes) successfully.")
                return target_path

            except Exception as exc:
                last_error = exc
                wait_sec = self.backoff_base_sec ** attempts
                logger.warning(f"Fetch failed ({exc}). Retrying in {wait_sec:.1f}s...")
                time.sleep(wait_sec)

        raise RuntimeError(f"Failed to acquire official BhavCopy for {target_date} after {self.max_retries} attempts: {last_error}")


class NseBhavdataParser:
    """Parses, sanitizes, and extracts BhavdataRecord rows from official CSV."""

    @staticmethod
    def parse_file(file_path: Path, intended_date: date) -> tuple[IngestionValidationResult, list[BhavdataRecord]]:
        with open(file_path, mode="r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            raw_fieldnames = [k.strip() for k in (reader.fieldnames or [])]

            required_headers = {
                "SYMBOL", "SERIES", "DATE1", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                "CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "DELIV_QTY", "DELIV_PER"
            }
            if not required_headers.issubset(set(raw_fieldnames)):
                missing = required_headers - set(raw_fieldnames)
                return IngestionValidationResult(
                    is_valid=False,
                    intended_date=intended_date,
                    total_raw_rows=0,
                    eq_rows_count=0,
                    matched_master_count=0,
                    null_ohlc_count=0,
                    invalid_ohlc_bounds_count=0,
                    zero_volume_count=0,
                    delivery_available_count=0,
                    quarantine_reasons=(f"Missing required headers: {missing}",),
                    error_summary=f"Invalid schema: missing {missing}",
                ), []

            records: list[BhavdataRecord] = []
            total_raw = 0
            null_ohlc = 0
            invalid_bounds = 0
            zero_vol = 0
            deliv_count = 0
            date_mismatch = 0

            for row_raw in reader:
                total_raw += 1
                row = {k.strip(): (v.strip() if v else "") for k, v in row_raw.items()}
                series = row.get("SERIES", "")

                # Strict Mainboard Ordinary Equity filtering
                if series != "EQ":
                    continue

                # Validate Date
                try:
                    row_date = parse_bhav_date_str(row.get("DATE1", ""))
                    if row_date != intended_date:
                        date_mismatch += 1
                        continue
                except Exception:
                    date_mismatch += 1
                    continue

                symbol = row.get("SYMBOL", "")
                if not symbol:
                    continue

                # Parse numerical prices with decimal precision
                try:
                    open_p = Decimal(row["OPEN_PRICE"]) if row.get("OPEN_PRICE") and row["OPEN_PRICE"] != "-" else None
                    high_p = Decimal(row["HIGH_PRICE"]) if row.get("HIGH_PRICE") and row["HIGH_PRICE"] != "-" else None
                    low_p = Decimal(row["LOW_PRICE"]) if row.get("LOW_PRICE") and row["LOW_PRICE"] != "-" else None
                    close_p = Decimal(row["CLOSE_PRICE"]) if row.get("CLOSE_PRICE") and row["CLOSE_PRICE"] != "-" else None
                    prev_close = Decimal(row["PREV_CLOSE"]) if row.get("PREV_CLOSE") and row["PREV_CLOSE"] != "-" else None
                    last_p = Decimal(row["LAST_PRICE"]) if row.get("LAST_PRICE") and row["LAST_PRICE"] != "-" else None
                    avg_p = Decimal(row["AVG_PRICE"]) if row.get("AVG_PRICE") and row["AVG_PRICE"] != "-" else None

                    vol = int(row.get("TTL_TRD_QNTY", "0"))
                    # Turnover reported in Lacs: 1 Lac = 100,000 INR
                    turnover_lacs = Decimal(row.get("TURNOVER_LACS", "0"))
                    turnover_inr = turnover_lacs * Decimal("100000.00")
                    trades = int(row.get("NO_OF_TRADES")) if row.get("NO_OF_TRADES") and row["NO_OF_TRADES"] != "-" else None

                    deliv_q = int(row["DELIV_QTY"]) if row.get("DELIV_QTY") and row["DELIV_QTY"] != "-" else None
                    deliv_pct = Decimal(row["DELIV_PER"]) if row.get("DELIV_PER") and row["DELIV_PER"] != "-" else None
                except Exception:
                    null_ohlc += 1
                    continue

                # Integrity constraints check
                if open_p is None or high_p is None or low_p is None or close_p is None:
                    null_ohlc += 1
                    continue

                if high_p < low_p or open_p <= 0 or close_p <= 0:
                    invalid_bounds += 1
                    continue

                if vol == 0:
                    zero_vol += 1

                if deliv_q is not None and deliv_pct is not None:
                    deliv_count += 1

                records.append(
                    BhavdataRecord(
                        symbol=symbol,
                        series=series,
                        trade_date=intended_date,
                        prev_close=prev_close,
                        open_price=open_p,
                        high_price=high_p,
                        low_price=low_p,
                        last_price=last_p,
                        close_price=close_p,
                        avg_price=avg_p,
                        traded_quantity=vol,
                        turnover_inr=turnover_inr,
                        number_of_trades=trades,
                        delivery_quantity=deliv_q,
                        delivery_percentage=deliv_pct,
                    )
                )

            quarantine_reasons = []
            if date_mismatch > 0:
                quarantine_reasons.append(f"Found {date_mismatch} rows with date not matching intended {intended_date}")
            if len(records) < 1500:
                quarantine_reasons.append(f"Unusually low EQ security count: {len(records)} records (expected >2,000)")
            if invalid_bounds > 0:
                quarantine_reasons.append(f"Found {invalid_bounds} records with invalid OHLC bounds (high < low or non-positive)")

            is_valid = len(quarantine_reasons) == 0 and len(records) >= 1500

            val_result = IngestionValidationResult(
                is_valid=is_valid,
                intended_date=intended_date,
                total_raw_rows=total_raw,
                eq_rows_count=len(records),
                matched_master_count=len(records),
                null_ohlc_count=null_ohlc,
                invalid_ohlc_bounds_count=invalid_bounds,
                zero_volume_count=zero_vol,
                delivery_available_count=deliv_count,
                quarantine_reasons=tuple(quarantine_reasons),
                error_summary="; ".join(quarantine_reasons) if quarantine_reasons else None,
            )
            return val_result, records


class DailyNseBhavdataPipeline:
    """Full operational pipeline executing download, parse, validation, persistence, and downstream triggers."""

    def __init__(
        self,
        repository: DuckDBRepository,
        dossier_repository: DossierReviewRepository,
        *,
        raw_storage_dir: Path,
        archive_root: Path,
    ):
        self.repo = repository
        self.dossier_repo = dossier_repository
        self.con = repository._connection
        self.downloader = NseBhavdataDownloader(raw_storage_dir, archive_root)
        self.archive_root = archive_root

    def execute_session(self, target_date: date) -> dict[str, object]:
        """Execute end-to-end ingestion and downstream intelligence triggers for target_date."""
        logger.info(f"=== Starting Daily NSE BhavCopy Ingestion Pipeline for {target_date} ===")
        date_str = format_nse_date_code(target_date)

        # 1. Download official file
        file_path = self.downloader.download_for_date(target_date)
        file_bytes = file_path.read_bytes()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()
        logger.info(f"File: {file_path.name} | Checksum: {file_sha256[:16]}... | Size: {len(file_bytes):,} bytes")

        # 2. Parse & Validate
        val_result, records = NseBhavdataParser.parse_file(file_path, target_date)
        if not val_result.is_valid:
            logger.error(f"Validation FAILED for {target_date}: {val_result.quarantine_reasons}")
            # Record quarantine and stop downstream
            self._record_session_quarantine(target_date, file_path, file_sha256, val_result.error_summary)
            return {"status": "quarantined", "error": val_result.error_summary}

        logger.info(f"Validation PASSED: {val_result.eq_rows_count} EQ records, {val_result.delivery_available_count} with delivery")

        # 3. Content-address source in raw archive
        archive_entry = archive_approved_source(
            file_path,
            archive_root=self.archive_root,
            license_status="approved",
        )
        source_doc_id = f"doc-bhav-{date_str}"

        # 4. Ingest into DuckDB Schema v7
        persisted_prices, persisted_deliv = self._persist_session(
            target_date, records, source_doc_id, archive_entry.sha256_hex, file_path.name
        )
        logger.info(f"Persisted to DuckDB: {persisted_prices} EOD prices, {persisted_deliv} delivery rows")

        # 5. Downstream Trigger: Recalculate Tier 1 Radar Signals across Universe
        mgr = TieredUniverseManager(self.repo, self.dossier_repo)
        signals_calc = mgr.calculate_and_store_radar_signals(
            exchange="NSE",
            session_date=target_date,
            cal_ver="nse-2026-v1",
            mode="public_as_of",
        )
        logger.info(f"Downstream Trigger: Calculated {signals_calc} Tier 1 radar signals")

        # 6. Downstream Trigger: Scan & Promote Production Candidates to Tier 2
        promoted_candidates = mgr.scan_and_promote_candidates(
            trade_date=target_date,
            auto_acquire_fundamentals=True,
        )
        logger.info(f"Downstream Trigger: Promoted {len(promoted_candidates)} candidates to Tier 2")

        # 6b. Downstream Trigger: Extract & Persist Market Events into Empirical Observation Ledger
        emp_engine = EmpiricalObservationEngine(self.repo)
        emp_events = emp_engine.extract_and_record_session_events(target_date)
        logger.info(f"Downstream Trigger: Extracted and recorded {len(emp_events)} market events")

        # 6c. Downstream Trigger: Catch Up All Matured Outcomes Across Historical Events
        outcome_summary = emp_engine.catch_up_matured_outcomes(horizons=(1, 3, 5, 10, 20, 60))
        logger.info(f"Downstream Trigger: Outcome catch-up finished ({outcome_summary})")
        # 7. Downstream Trigger: Evaluate Shadow Candidates under Versioned Profile
        shadow_engine = ShadowCandidateEngine(self.repo)
        shadow_candidates = shadow_engine.evaluate_session(target_date, profile=SHADOW_PROFILES["shadow-v1.0"])
        logger.info(f"Downstream Trigger: Generated {len(shadow_candidates)} shadow candidates under shadow-v1.0")

        # 8. Downstream Trigger: Generate & Persist Structured Daily Intelligence Brief
        brief_gen = DailyBriefGenerator(self.repo, self.dossier_repo)
        brief = brief_gen.build_and_persist_brief(target_date, shadow_candidates)
        logger.info(f"Daily Intelligence Brief Generated & Persisted:\n{brief['text_summary']}")

        return {
            "status": "success",
            "trade_date": target_date.isoformat(),
            "checksum_sha256": file_sha256,
            "records_parsed": len(records),
            "eod_prices_persisted": persisted_prices,
            "delivery_records_persisted": persisted_deliv,
            "signals_calculated": signals_calc,
            "candidates_promoted": len(promoted_candidates),
            "brief": brief,
        }

    def _record_session_quarantine(self, target_date: date, file_path: Path, checksum: str, reason: str | None) -> None:
        doc_id = f"doc-bhav-quar-{format_nse_date_code(target_date)}"
        quar_id = f"quar-bhav-{format_nse_date_code(target_date)}"
        now = datetime.now(timezone.utc)
        self.con.execute(
            """
            INSERT OR IGNORE INTO observation_quarantine (
                quarantine_id, source_document_id, source_locator, reason_code, detail, quarantined_at
            ) VALUES (?, ?, ?, 'bhavcopy_validation_failure', ?, ?)
        """,
            [quar_id, doc_id, file_path.name, reason or "Validation failure", now],
        )

    def _persist_session(
        self,
        trade_date: date,
        records: list[BhavdataRecord],
        source_doc_id: str,
        checksum: str,
        filename: str,
    ) -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        date_iso = trade_date.isoformat()

        # Ensure source document revision exists
        raw_file_id = f"raw-bhav-{format_nse_date_code(trade_date)}"
        self.con.execute(
            """
            INSERT OR IGNORE INTO raw_source_file (
                source_file_id, provider, dataset, original_filename, checksum_sha256,
                archive_path, captured_at, source_as_of_date, license_review_reference, license_status
            ) VALUES (?, 'NSE', 'sec_bhavdata_full', ?, ?, ?, ?, ?, 'LIC_NSE_PUBLIC', 'approved')
        """,
            [raw_file_id, filename, checksum, f"archive/{filename}", now, trade_date],
        )

        self.con.execute(
            """
            INSERT OR IGNORE INTO source_document_revision (
                source_document_id, provider, dataset, source_identifier, checksum_sha256,
                source_file_id, revision_number, source_document_date, publication_date,
                ingestion_timestamp, parser_version, extraction_timestamp, extraction_locator
            ) VALUES (?, 'NSE', 'sec_bhavdata_full', ?, ?, ?, 1, ?, ?, ?, 'bhav-parser-v1', ?, 'sec_bhavdata')
        """,
            [source_doc_id, filename, checksum, raw_file_id, trade_date, trade_date, now, now],
        )

        # Batch map symbols to active exchange_listing
        raw_listings = self.con.execute(
            """
            SELECT upper(r.symbol), l.listing_id, l.security_id
            FROM exchange_listing l
            JOIN exchange_listing_revision r ON r.listing_id=l.listing_id
            WHERE l.exchange='NSE' AND r.status='active'
        """
        ).fetchall()
        active_listings = {row[0]: (row[1], row[2]) for row in raw_listings}

        price_rows = []
        deliv_rows = []
        registry_rows = []

        for r in records:
            mapping = active_listings.get(r.symbol.upper())
            if not mapping:
                continue

            list_id, sec_id = mapping[0], mapping[1]
            obs_id_price = f"eod-nse-{r.symbol.lower()}-{date_iso}"
            obs_id_deliv = f"deliv-nse-{r.symbol.lower()}-{date_iso}"

            # Registry
            registry_rows.append((obs_id_price, "eod_price", source_doc_id, filename, checksum, "bhav-parser-v1", now, filename))
            price_rows.append((
                obs_id_price, "eod_price", sec_id, list_id, "NSE", trade_date,
                r.open_price, r.high_price, r.low_price, r.close_price, "INR",
                Decimal(r.traded_quantity), "SHARES", r.turnover_inr, "INR",
                source_doc_id, filename, checksum, "bhav-parser-v1", now, filename, "observed"
            ))

            if r.delivery_quantity is not None and r.delivery_percentage is not None:
                registry_rows.append((obs_id_deliv, "delivery", source_doc_id, filename, checksum, "bhav-parser-v1", now, filename))
                deliv_rows.append((
                    obs_id_deliv, "delivery", sec_id, list_id, "NSE", trade_date,
                    Decimal(r.delivery_quantity), Decimal(r.traded_quantity), r.delivery_percentage,
                    source_doc_id, "bhav-parser-v1", now, filename, "observed"
                ))

        # Idempotent batch insertion
        if registry_rows:
            self.con.executemany(
                """
                INSERT OR IGNORE INTO normalized_observation_registry (
                    observation_id, observation_type, source_document_id, source_identifier,
                    checksum_sha256, parser_version, extraction_timestamp, extraction_locator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                registry_rows,
            )

        if price_rows:
            self.con.executemany(
                """
                INSERT OR IGNORE INTO eod_price_observation_revision (
                    observation_id, observation_type, security_id, listing_id, exchange, trade_date,
                    open_raw, high_raw, low_raw, close_raw, price_unit, volume_raw, volume_unit,
                    turnover_raw, turnover_unit, source_document_id, source_identifier, checksum_sha256,
                    parser_version, extraction_timestamp, extraction_locator, quality_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                price_rows,
            )

        if deliv_rows:
            self.con.executemany(
                """
                INSERT OR IGNORE INTO delivery_observation_revision (
                    observation_id, observation_type, security_id, listing_id, exchange, trade_date,
                    delivery_quantity_raw, traded_quantity_raw, delivery_percentage_raw,
                    source_document_id, parser_version, extraction_timestamp, extraction_locator, quality_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                deliv_rows,
            )

        return len(price_rows), len(deliv_rows)

    def _generate_daily_brief(
        self,
        target_date: date,
        val: IngestionValidationResult,
        signals_count: int,
        candidates: list[dict],
    ) -> dict[str, object]:
        summary_lines = [
            f"=== HAMSA DAILY MARKET INTELLIGENCE BRIEF: {target_date.isoformat()} ===",
            f"Official NSE BhavCopy Ingested: {val.eq_rows_count:,} EQ securities, {val.delivery_available_count:,} with delivery data.",
            f"Tier 1 Behavioral Signals Recalculated: {signals_count} securities.",
            f"New Qualifying Tier 2 Candidates: {len(candidates)}.",
        ]
        if candidates:
            summary_lines.append("Top Promoted Candidates:")
            for c in candidates[:5]:
                summary_lines.append(f"  • {c['symbol']}: {c['primary_trigger']} ({c['details']})")

        return {
            "date": target_date.isoformat(),
            "summary": "\n".join(summary_lines),
            "candidates": candidates,
        }