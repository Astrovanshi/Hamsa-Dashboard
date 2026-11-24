"""Optional local real-file checks; raw sample files are ignored and not needed on clean checkout."""

from datetime import date
from decimal import Decimal
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from hamsa.ingestion.tejhq_parquet import TejHQParquetImporter, TejHQPartition
from hamsa.providers.official_eod import parse_nse_udiff
from hamsa.storage.duckdb_repository import DuckDBRepository


ROOT = Path(__file__).resolve().parents[1]
NSE_2026 = ROOT / "data/raw/tejhq-sample/nse/year=2026/nse_2026.parquet"
BSE_2026 = ROOT / "data/raw/tejhq-sample/bse/year=2026/bse_2026.parquet"
NSE_2010 = ROOT / "data/raw/tejhq-sample/nse/year=2010/nse_2010.parquet"
NSE_OFFICIAL = ROOT / "data/raw/real/eod/nse/BhavCopy_NSE_CM_0_0_0_20261109_F_0000.csv.zip"
NSE_DELIVERY_OFFICIAL = ROOT / "data/raw/real/eod/nse/sec_bhavdata_full_09112026.csv"
NSE_DELIVERY_2026 = ROOT / "data/raw/tejhq-sample/delivery/nse/year=2026/nse_2026.parquet"
BSE_OFFICIAL = ROOT / "data/raw/real/eod/bse/BhavCopy_BSE_CM_0_0_0_20261109_F_0000.CSV"


@skipUnless(NSE_2026.is_file(), "local ignored TejHQ sample is unavailable; portable tests remain active")
class TejHQRealSampleTests(TestCase):
    def test_actual_nse_partition_schema_and_unresolved_identity_quarantine(self):
        with TemporaryDirectory() as tmp, DuckDBRepository(":memory:") as repository:
            partition = TejHQPartition(
                NSE_2026, "NSE", "tejhq/indian-markets", "6cf4d20", "nse/year=2026/nse_2026.parquet",
                date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 10),
            )
            with TejHQParquetImporter(repository, archive_root=Path(tmp)) as importer:
                schema, rows = importer.read_rows(partition, trade_date=date(2026, 11, 9), symbols=("SBIN", "NIFTYBEES"))
                report = importer.ingest_pilot(partition, trade_date=date(2026, 11, 9), symbols=("SBIN", "NIFTYBEES"))
            self.assertIn(("date", "DATE"), schema)
            self.assertEqual({row.symbol for row in rows}, {"SBIN", "NIFTYBEES"})
            sbi = next(row for row in rows if row.symbol == "SBIN")
            self.assertEqual((sbi.isin, sbi.close, sbi.volume, sbi.turnover), ("INE062A01020", 1042.0, 24065897, 24974519875.55))
            self.assertEqual((report.accepted, report.quarantined), (0, 2))
            self.assertEqual(repository._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], 0)
            self.assertEqual(repository._connection.execute("SELECT count(*) FROM raw_source_file WHERE provider='TejHQ'").fetchone()[0], 1)

    @skipUnless(BSE_2026.is_file(), "local ignored TejHQ BSE sample is unavailable")
    def test_actual_bse_partition_is_kept_separate(self):
        with TemporaryDirectory() as tmp, DuckDBRepository(":memory:") as repository:
            partition = TejHQPartition(
                BSE_2026, "BSE", "tejhq/indian-markets", "6cf4d20", "bse/year=2026/bse_2026.parquet",
                date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 10),
            )
            with TejHQParquetImporter(repository, archive_root=Path(tmp)) as importer:
                _, rows = importer.read_rows(partition, trade_date=date(2026, 11, 9), symbols=("SBIN",))
                report = importer.ingest_pilot(partition, trade_date=date(2026, 11, 9), symbols=("SBIN",))
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0].isin, rows[0].series, rows[0].close, rows[0].volume),
                             ("INE062A01020", "A", 1041.45, 1456011))
            self.assertEqual((report.accepted, report.quarantined), (0, 1))
            self.assertEqual(repository._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], 0)

    @skipUnless(NSE_2010.is_file(), "local ignored TejHQ historical sample is unavailable")
    def test_actual_historical_null_isin_is_not_symbol_mapped(self):
        with TemporaryDirectory() as tmp, DuckDBRepository(":memory:") as repository:
            partition = TejHQPartition(
                NSE_2010, "NSE", "tejhq/indian-markets", "62a4096", "nse/year=2010/nse_2010.parquet",
                date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 10),
            )
            with TejHQParquetImporter(repository, archive_root=Path(tmp)) as importer:
                _, rows = importer.read_rows(partition, trade_date=date(2010, 1, 4), symbols=("SBIN",))
                report = importer.ingest_pilot(partition, trade_date=date(2010, 1, 4), symbols=("SBIN",))
            self.assertTrue(rows)
            self.assertIsNone(rows[0].isin)
            self.assertEqual(report.quarantined, 1)
            self.assertEqual(repository._connection.execute("SELECT reason_code FROM observation_quarantine").fetchone()[0], "missing_or_invalid_isin")

    @skipUnless(NSE_OFFICIAL.is_file(), "local official NSE UDiFF sample is unavailable")
    def test_actual_nse_sbi_row_matches_local_official_source(self):
        partition = TejHQPartition(
            NSE_2026, "NSE", "tejhq/indian-markets", "6cf4d20", "nse/year=2026/nse_2026.parquet",
            date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 10),
        )
        repository = DuckDBRepository(":memory:")
        try:
            with TemporaryDirectory() as tmp, TejHQParquetImporter(repository, archive_root=Path(tmp)) as importer:
                _, secondary_rows = importer.read_rows(partition, trade_date=date(2026, 11, 9), symbols=("SBIN",))
        finally:
            repository.close()
        official_rows, _, _ = parse_nse_udiff(NSE_OFFICIAL, allowed_series={"EQ"}, isin_allowlist={"INE062A01020"})
        secondary = secondary_rows[0]
        official = next(row for row in official_rows if row["isin"] == secondary.isin and row["trade_date"] == "2026-11-09")
        fields = ((secondary.open, official["open"]), (secondary.high, official["high"]),
                  (secondary.low, official["low"]), (secondary.close, official["close"]),
                  (secondary.volume, official["volume"]), (secondary.turnover, official["turnover"]))
        self.assertEqual([Decimal(str(left)) for left, _ in fields], [Decimal(right) for _, right in fields])

    @skipUnless(BSE_OFFICIAL.is_file(), "local official BSE UDiFF sample is unavailable")
    def test_actual_bse_sbi_row_matches_local_official_source(self):
        partition = TejHQPartition(
            BSE_2026, "BSE", "tejhq/indian-markets", "6cf4d20", "bse/year=2026/bse_2026.parquet",
            date(2026, 11, 10), date(2026, 11, 10), date(2026, 11, 10),
        )
        repository = DuckDBRepository(":memory:")
        try:
            with TemporaryDirectory() as tmp, TejHQParquetImporter(repository, archive_root=Path(tmp)) as importer:
                _, secondary_rows = importer.read_rows(partition, trade_date=date(2026, 11, 9), symbols=("SBIN",))
        finally:
            repository.close()
        official = None
        with BSE_OFFICIAL.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("ISIN") == "INE062A01020" and row.get("TradDt") == "2026-11-09":
                    official = row
                    break
        self.assertIsNotNone(official)
        secondary = secondary_rows[0]
        fields = ((secondary.open, official["OpnPric"]), (secondary.high, official["HghPric"]),
                  (secondary.low, official["LwPric"]), (secondary.close, official["ClsPric"]),
                  (secondary.volume, official["TtlTradgVol"]), (secondary.turnover, official["TtlTrfVal"]))
        self.assertEqual([Decimal(str(left)) for left, _ in fields], [Decimal(right) for _, right in fields])

    @skipUnless(
        NSE_2026.is_file() and NSE_DELIVERY_2026.is_file() and NSE_DELIVERY_OFFICIAL.is_file(),
        "local real 2026 NSE EOD and delivery files are unavailable",
    )
    def test_real_market_multi_company_dislocation_and_false_positive_discrimination(self):
        from datetime import datetime, timezone
        from hamsa.dossiers.repository import DossierReviewRepository
        from hamsa.screening.data_access import company_input_as_of, liquidity_input_as_of
        from hamsa.screening.engines import EngineThresholds, EvaluationState, evaluate_company
        import duckdb

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with DuckDBRepository(root / "real_val.duckdb") as repo:
                reviews = DossierReviewRepository(
                    root / "real_reviews.sqlite3",
                    schema_path=ROOT / "sql" / "sqlite_schema.sql",
                    analytics_repository=repo,
                )
                try:
                    src_file = root / "nse_evidence.txt"
                    src_file.write_text("real validation evidence", encoding="utf-8")
                    reg = repo.register_local_source_document(
                        src_file, archive_root=root / "archive", exchange="NSE",
                        dataset="validation_evidence", source_identifier="NSE_VAL_2026",
                        source_document_date=date(2025, 12, 31), publication_date=date(2025, 12, 31),
                        published_at=datetime(2025, 12, 31, 10, 0, tzinfo=timezone.utc),
                        parser_version="val-v1", retention_authorized=True,
                    )
                    doc_id = reg.source_document_id
                    con = repo._connection
                    proc_id = repo._ensure_extraction_revision_for_source(
                        doc_id, "val-v1", datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
                    )

                    # Load actual 2026 NSE trading dates from nse_2026.parquet
                    pcon = duckdb.connect(":memory:")
                    sessions = [
                        r[0] for r in pcon.execute(
                            "SELECT DISTINCT date FROM read_parquet(?) ORDER BY date", [str(NSE_2026)]
                        ).fetchall()
                    ]
                    for day in sessions:
                        con.execute(
                            "INSERT INTO exchange_trading_session VALUES ('NSE', ?, TRUE, 'regular', 'nse-2026-val', ?)",
                            [day, doc_id],
                        )

                    # Admit three real NSE industrial stocks with distinct market-structure behaviors:
                    # 1. RATEGAIN (INE0CLI01024): genuine high-delivery sell-side dislocation on 2026-11-09
                    # 2. FINCABLES (INE235A01022): high-volume low-delivery intraday churn on 2026-11-09
                    # 3. ZFCVINDIA (INE342J01019): 6:1 stock split/bonus ex-date reset on 2026-06-24
                    candidates = (
                        ("issuer-rategain", "sec-rategain", "list-rategain", "RATEGAIN", "INE0CLI01024", "Rategain Travel Technologies Limited"),
                        ("issuer-fincables", "sec-fincables", "list-fincables", "FINCABLES", "INE235A01022", "Finolex Cables Limited"),
                        ("issuer-zfcv", "sec-zfcv", "list-zfcv", "ZFCVINDIA", "INE342J01019", "ZF Commercial Vehicle Control Systems India Limited"),
                    )
                    for iss_id, sec_id, list_id, sym, isin, name in candidates:
                        res = repo.append_security_identity_candidate(
                            issuer_entity_id=iss_id, security_id=sec_id, listing_id=list_id,
                            exchange="NSE", exchange_instrument_id=sym, isin=isin,
                            legal_name=name, identity_observed_from=date(2020, 1, 1),
                            source_document_id=doc_id, source_locator=f"isin:{isin}",
                        )
                        repo.append_security_identifier_review(
                            identifier_revision_id=res["identifier_revision_id"], review_status="approved",
                            reviewer="analyst", reviewer_actor_type="human",
                            evidence_source_document_id=doc_id, evidence_locator=f"isin:{isin}",
                        )
                        lrev = repo.append_exchange_listing_revision({
                            "listing_revision_id": f"lrev-{sym}", "listing_id": list_id, "symbol": sym,
                            "series": "EQ", "status": "active", "effective_from": date(2020, 1, 1),
                            "source_document_id": doc_id, "extraction_locator": f"sym:{sym}", "parser_version": "val-v1",
                        })
                        repo.append_exchange_listing_revision_review({
                            "listing_revision_review_id": f"lrevchk-{sym}", "listing_revision_id": lrev,
                            "review_status": "approved", "reviewed_by": "analyst",
                            "evidence_source_document_id": doc_id, "evidence_locator": f"sym:{sym}",
                            "rationale": "Active mainboard listing",
                        })
                        snap = repo.append_listing_classification_snapshot({
                            "listing_classification_snapshot_id": f"snap-{sym}", "listing_id": list_id,
                            "exchange": "NSE", "source_document_id": doc_id, "source_snapshot_date": date(2026, 1, 1),
                            "raw_isin": isin, "raw_symbol": sym, "parser_version": "val-v1", "extraction_locator": f"sym:{sym}",
                        })
                        repo.append_listing_classification_review_revision({
                            "classification_review_revision_id": f"cchk-{sym}",
                            "listing_classification_snapshot_id": snap, "listing_id": list_id,
                            "rationale": "Mainboard ordinary equity",
                            "instrument_review_status": "approved", "instrument_class": "ordinary_equity",
                            "instrument_valid_from": date(2020, 1, 1), "instrument_evidence_source_document_id": doc_id,
                            "instrument_evidence_locator": f"sym:{sym}", "instrument_reviewed_by": "analyst",
                            "platform_review_status": "approved", "platform_class": "mainboard",
                            "platform_valid_from": date(2020, 1, 1), "platform_evidence_source_document_id": doc_id,
                            "platform_evidence_locator": f"sym:{sym}", "platform_reviewed_by": "analyst",
                        })
                        reviews.append_business_classification_review(
                            entity_id=iss_id, business_class="industrial", valid_from="2020-01-01",
                            valid_to=None, reviewer="analyst", rationale="Industrial operating business",
                            source_document_id=doc_id, locator=f"sym:{sym}",
                        )

                        # Load real 2026 EOD and delivery rows for this symbol
                        eod_rows = pcon.execute(
                            """SELECT date, open, high, low, close, volume, turnover
                               FROM read_parquet(?) WHERE symbol=? AND series='EQ' ORDER BY date""",
                            [str(NSE_2026), sym],
                        ).fetchall()
                        for d_val, o_v, h_v, l_v, c_v, vol_v, turn_v in eod_rows:
                            repo.append_eod_price_observation({
                                "observation_id": f"eod-{sym}-{d_val.isoformat()}",
                                "security_id": sec_id, "listing_id": list_id, "exchange": "NSE",
                                "trade_date": d_val,
                                "open_raw": Decimal(str(o_v)), "high_raw": Decimal(str(h_v)),
                                "low_raw": Decimal(str(l_v)), "close_raw": Decimal(str(c_v)),
                                "volume_raw": Decimal(str(vol_v)), "turnover_raw": Decimal(str(turn_v)),
                                "source_document_id": doc_id, "source_identifier": "NSE_VAL_2026",
                                "checksum_sha256": reg.checksum_sha256, "parser_version": "val-v1",
                                "extraction_timestamp": datetime.now(timezone.utc),
                                "extraction_locator": f"{sym}:{d_val.isoformat()}",
                                "quality_status": "observed", "extraction_revision_id": proc_id,
                            })
                        deliv_rows = pcon.execute(
                            """SELECT date, volume, delivery_qty, delivery_pct
                               FROM read_parquet(?) WHERE symbol=? AND series='EQ'
                                 AND date >= DATE '2026-10-01' ORDER BY date""",
                            [str(NSE_DELIVERY_2026), sym],
                        ).fetchall()
                        for d_val, vol_v, dqty_v, dpct_v in deliv_rows:
                            obs_id = f"deliv-{sym}-{d_val.isoformat()}"
                            con.execute(
                                """INSERT INTO normalized_observation_registry
                                   (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                                    parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                                   VALUES (?,'delivery',?,'NSE_VAL_2026',?,'val-v1',CURRENT_TIMESTAMP,?,?)""",
                                [obs_id, doc_id, reg.checksum_sha256, f"{sym}:{d_val.isoformat()}", proc_id],
                            )
                            con.execute(
                                """INSERT INTO delivery_observation_revision
                                   (observation_id,observation_type,security_id,listing_id,exchange,trade_date,
                                    delivery_quantity_raw,traded_quantity_raw,delivery_percentage_raw,source_document_id,
                                    parser_version,extraction_timestamp,extraction_locator,quality_status)
                                   VALUES (?,'delivery',?,?,'NSE',?,?,?,?,?,'val-v1',CURRENT_TIMESTAMP,?,'observed')""",
                                [obs_id, sec_id, list_id, d_val, dqty_v, vol_v, Decimal(str(dpct_v)), doc_id, f"{sym}:{d_val.isoformat()}"],
                            )

                    # Also append official 2026-11-09 NSE delivery for RATEGAIN and FINCABLES
                    with NSE_DELIVERY_OFFICIAL.open("r", encoding="utf-8-sig") as handle:
                        for row in csv.DictReader(handle):
                            sym = row.get("SYMBOL", "").strip()
                            if sym in ("RATEGAIN", "FINCABLES") and row.get(" SERIES", "").strip() == "EQ":
                                sec_id = "sec-rategain" if sym == "RATEGAIN" else "sec-fincables"
                                list_id = "list-rategain" if sym == "RATEGAIN" else "list-fincables"
                                obs_id = f"deliv-{sym}-2026-11-09"
                                con.execute(
                                    """INSERT INTO normalized_observation_registry
                                       (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                                        parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                                       VALUES (?,'delivery',?,'NSE_VAL_2026',?,'val-v1',CURRENT_TIMESTAMP,?,?)""",
                                    [obs_id, doc_id, reg.checksum_sha256, f"{sym}:2026-11-09", proc_id],
                                )
                                con.execute(
                                    """INSERT INTO delivery_observation_revision
                                       (observation_id,observation_type,security_id,listing_id,exchange,trade_date,
                                        delivery_quantity_raw,traded_quantity_raw,delivery_percentage_raw,source_document_id,
                                        parser_version,extraction_timestamp,extraction_locator,quality_status)
                                       VALUES (?,'delivery',?,?,'NSE',DATE '2026-11-09',?,?,?,?,'val-v1',CURRENT_TIMESTAMP,?,'observed')""",
                                    [obs_id, sec_id, list_id, int(row[" DELIV_QTY"].strip()), int(row[" TTL_TRD_QNTY"].strip()),
                                     Decimal(row[" DELIV_PER"].strip()), doc_id, f"{sym}:2026-11-09"],
                                )
                    pcon.close()

                    # 1. RATEGAIN on 2026-11-09: high volume (3.57x) + high delivery (60.9%, +19.19pp)
                    rg_liq = liquidity_input_as_of(
                        repo, issuer_entity_id="issuer-rategain", exchange="NSE",
                        session_date=date(2026, 11, 9), availability_mode="public_as_of",
                        calendar_version="nse-2026-val", review_repository=reviews,
                    )
                    self.assertGreater(rg_liq["volume_multiple"], Decimal("3.5"))
                    self.assertEqual(rg_liq["delivery_percentage"], Decimal("60.90"))
                    self.assertAlmostEqual(float(rg_liq["delivery_percentage_point_change"]), 19.19, places=2)
                    self.assertLess(rg_liq["drawdown_from_window_high_pct"], Decimal("-20"))

                    # Without human seller/absorption evidence, Engine 5 remains UNPROVEN even with 3.57x vol & +19.19pp delivery
                    rg_comp = company_input_as_of(
                        repo, issuer_entity_id="issuer-rategain", exchange="NSE",
                        session_date=date(2026, 11, 9), availability_mode="public_as_of",
                        calendar_version="nse-2026-val", business_class="industrial",
                        review_repository=reviews,
                    )
                    thresholds = EngineThresholds(unusual_volume_multiple=Decimal("3.0"), unusual_delivery_percentage_points=Decimal("15.0"))
                    rg_eval_before = next(
                        r for r in evaluate_company(rg_comp, thresholds, **rg_liq)
                        if r.engine == "extreme_sell_side_liquidity"
                    )
                    self.assertEqual(rg_eval_before.state, EvaluationState.UNPROVEN)

                    # Once human-reviewed forced-selling and absorption evidence is cited, Engine 5 triggers
                    rg_eval_after = next(
                        r for r in evaluate_company(
                            rg_comp, thresholds,
                            **{
                                **rg_liq,
                                "forced_selling_evidence": True,
                                "absorption_capacity_evidence": True,
                                "forced_selling_source_document_ids": (doc_id,),
                                "absorption_capacity_source_document_ids": (doc_id,),
                            },
                        )
                        if r.engine == "extreme_sell_side_liquidity"
                    )
                    self.assertEqual(rg_eval_after.state, EvaluationState.TRIGGERED)

                    # 2. FINCABLES on 2026-11-09: 10.79x volume but low delivery (14.83%, -38.60pp intraday churn)
                    fc_liq = liquidity_input_as_of(
                        repo, issuer_entity_id="issuer-fincables", exchange="NSE",
                        session_date=date(2026, 11, 9), availability_mode="public_as_of",
                        calendar_version="nse-2026-val", review_repository=reviews,
                    )
                    self.assertGreater(fc_liq["volume_multiple"], Decimal("10.0"))
                    self.assertEqual(fc_liq["delivery_percentage"], Decimal("14.83"))
                    self.assertLess(fc_liq["delivery_percentage_point_change"], Decimal("-35.0"))

                    # 3. ZFCVINDIA on 2026-06-25 (day after 6:1 split/bonus from 16,086 to 2,660):
                    # unadjusted split is flagged and pre-split volume is excluded from the baseline!
                    zf_liq = liquidity_input_as_of(
                        repo, issuer_entity_id="issuer-zfcv", exchange="NSE",
                        session_date=date(2026, 6, 25), availability_mode="public_as_of",
                        calendar_version="nse-2026-val", review_repository=reviews,
                    )
                    self.assertTrue(zf_liq["unadjusted_corporate_action_in_window"])
                    self.assertLess(zf_liq["volume_multiple"], Decimal("1.0"))
                finally:
                    reviews.close()
