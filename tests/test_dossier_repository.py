from datetime import datetime, timezone
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.domain.filters import EvidenceReference
from hamsa.domain.financials import AsReportedStatus,FinancialObservationRevision,PublicationPrecision,QualityStatus
from hamsa.screening.data_access import company_input_as_of, liquidity_input_as_of, universe_for_session
from hamsa.screening.engines import EngineThresholds, EvaluationState, evaluate_capex_conversion, evaluate_company
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError

ROOT = Path(__file__).resolve().parents[1]


class DossierRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.analytics = DuckDBRepository(folder / "analytics.duckdb")
        self.analytics._connection.execute("INSERT INTO issuer_entity VALUES ('issuer-1',CURRENT_TIMESTAMP)")
        self.path = folder / "reviews.sqlite3"
        self.repo = DossierReviewRepository(self.path, schema_path=ROOT / "sql" / "sqlite_schema.sql",
                                            analytics_repository=self.analytics)

    def tearDown(self):
        self.repo.close()
        self.analytics.close()
        self.temp.cleanup()

    def test_review_history_is_append_only_and_superseded(self):
        first = self.repo.append_review(entity_id="issuer-1", filter_key="gap", status="Unproven",
            reviewer="analyst", rationale="No sourced market-perception comparison yet.")
        second = self.repo.append_review(entity_id="issuer-1", filter_key="gap", status="Unproven",
            reviewer="analyst", rationale="Same conclusion after review.")
        self.assertNotEqual(first, second)
        self.assertEqual(self.repo.current_reviews("issuer-1")["gap"]["review_id"], second)
        self.assertEqual(len(self.repo.history("issuer-1", "gap")), 2)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.repo.connection.execute("UPDATE filter_review SET rationale='rewritten' WHERE review_id=?", (first,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.repo.connection.execute("DELETE FROM filter_review WHERE review_id=?", (first,))

    def test_pass_or_fail_requires_cited_evidence(self):
        with self.assertRaisesRegex(ValueError, "source citation"):
            self.repo.append_review(entity_id="issuer-1", filter_key="gap", status="Pass",
                reviewer="analyst", rationale="Strong thesis.")

    def test_watchlist_and_thesis_records_are_revisioned(self):
        first = self.repo.append_watchlist_event(entity_id="issuer-1", status="watch", reviewer="analyst", rationale="Initial review.")
        second = self.repo.append_watchlist_event(entity_id="issuer-1", status="cooling", reviewer="analyst", rationale="A checkpoint is due.")
        self.assertNotEqual(first, second)
        self.assertEqual(self.repo.watchlist()[0]["status"], "cooling")
        checksum, _ = self._seed_source_and_calendar()
        citation = (EvidenceReference("doc-class", "classification.csv", checksum, "page 1", "Supports the thesis statement."),)
        note1 = self.repo.append_company_research_note(entity_id="issuer-1",business_thesis="Thesis v1",
            thesis_killers="Demand permanently weakens.",reviewer="analyst",next_review_date="2026-12-31",evidence=citation)
        note2 = self.repo.append_company_research_note(entity_id="issuer-1",business_thesis="Thesis v2",
            thesis_killers="Demand permanently weakens.",reviewer="analyst",evidence=citation)
        self.assertNotEqual(note1, note2)
        self.assertEqual(self.repo.latest_company_note("issuer-1")["note_revision_id"], note2)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.repo.connection.execute("UPDATE research_watchlist_revision SET status='watch' WHERE revision_id=?", (first,))

    def _seed_source_and_calendar(self):
        con = self.analytics._connection
        checksum = sha256(b"official classification source").hexdigest()
        pub = datetime(2025, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        captured = datetime(2025, 5, 1, 11, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        con.execute("""INSERT INTO raw_source_file
            (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
             source_as_of_date,license_review_reference,license_status)
            VALUES ('file-class','NSE','classification','classification.csv',?,'archive/classification',?,
                    DATE '2025-05-01','synthetic-test','approved')""", [checksum, captured])
        con.execute("""INSERT INTO source_document_revision
            (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,revision_number,
             source_document_date,publication_date,published_at,ingestion_timestamp,parser_version,
             extraction_timestamp,extraction_locator)
            VALUES ('doc-class','NSE','classification','classification.csv','file-class',?,1,
                    DATE '2025-05-01',DATE '2025-05-01',?,?, 'parser-1',?,'csv')""",
            [checksum, pub, captured, captured])
        today = datetime.now(timezone.utc).date()
        for day in (today - timedelta(days=1), today, today + timedelta(days=1)):
            con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',?,TRUE,'regular','nse-test-cal','doc-class')", [day])
        return checksum, today

    def test_business_class_review_requires_evidence_and_is_point_in_time(self):
        _, today = self._seed_source_and_calendar()
        previous_day = today - timedelta(days=1)
        with self.assertRaisesRegex(ValueError, "source locator"):
            self.repo.append_business_classification_review(entity_id="issuer-1",business_class="industrial",
                valid_from="2020-01-01",valid_to=previous_day.isoformat(),reviewer="analyst",rationale="Evidence supports industrial operations.",
                source_document_id="doc-class",locator="")
        first = self.repo.append_business_classification_review(entity_id="issuer-1",business_class="industrial",
            valid_from="2020-01-01",valid_to=previous_day.isoformat(),reviewer="analyst",rationale="Evidence supports industrial operations.",
            source_document_id="doc-class",locator="page 1")
        with self.assertRaisesRegex(ValueError, "intervals overlap"):
            self.repo.append_business_classification_review(entity_id="issuer-1",business_class="financial",
                valid_from=previous_day.isoformat(),valid_to=None,reviewer="analyst",rationale="Incorrect overlapping interval.",
                source_document_id="doc-class",locator="page 2")
        second = self.repo.append_business_classification_review(entity_id="issuer-1",business_class="financial",
            valid_from=today.isoformat(),valid_to=None,reviewer="analyst",rationale="Independently reviewed financial-sector classification.",
            source_document_id="doc-class",locator="page 3")
        self.assertNotEqual(first, second)
        tz = timezone(timedelta(hours=5, minutes=30))
        before_review = datetime.combine(previous_day, datetime.min.time(), tzinfo=tz).replace(hour=15, minute=30)
        self.assertEqual(self.repo.business_class_as_of(entity_id="issuer-1",session_date=previous_day,
            cutoff=before_review,exchange="NSE",availability_mode="public_as_of",calendar_version="nse-test-cal"),"unclassified")
        after_day = today + timedelta(days=1)
        after_review = datetime.combine(after_day, datetime.min.time(), tzinfo=tz).replace(hour=15, minute=30)
        self.assertEqual(self.repo.business_class_as_of(entity_id="issuer-1",session_date=after_day,
            cutoff=after_review,exchange="NSE",availability_mode="hamsa_known_as_of",calendar_version="nse-test-cal"),"financial")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.repo.connection.execute("DELETE FROM issuer_business_classification_review_revision WHERE review_revision_id=?", (second,))

    def test_financial_read_view_uses_selected_calendar_and_preserves_period_scope(self):
        checksum, today = self._seed_source_and_calendar()
        con = self.analytics._connection
        con.execute("INSERT INTO financial_metric_definition VALUES ('revenue','INR','currency','Revenue','v1')")
        pub = datetime(2025, 5, 1, 10, 0, tzinfo=timezone(timedelta(hours=5,minutes=30)))
        ingested = datetime(2025, 5, 1, 11, 0, tzinfo=timezone(timedelta(hours=5,minutes=30)))
        self.analytics.append_financial_observation(FinancialObservationRevision(
            observation_id="financial-revenue-1",subject_id="issuer-1",metric="revenue",raw_value=Decimal("10"),
            raw_unit="INR",canonical_value=Decimal("10"),canonical_unit="INR",period_start=date(2025,1,1),
            period_end=date(2025,3,31),source_document_date=date(2025,5,1),publication_date=date(2025,5,1),
            publication_precision=PublicationPrecision.TIMESTAMP,published_at=pub,ingestion_timestamp=ingested,
            revision_number=1,source_document_id="doc-class",as_reported_status=AsReportedStatus.ORIGINAL,
            quality_status=QualityStatus.OBSERVED,quality_reason=None,reporting_scope="consolidated",
            source_locator="page 5",parser_version="parser-1",extraction_timestamp=ingested))
        screen_day = today + timedelta(days=1)
        cutoff = datetime.combine(screen_day, datetime.min.time(),tzinfo=timezone(timedelta(hours=5,minutes=30))).replace(hour=15,minute=30)
        snapshot = self.analytics.financial_observations_as_of(exchange="NSE",session_date=screen_day,
            cutoff=cutoff,availability_mode="public_as_of",calendar_version="nse-test-cal")
        self.assertEqual(len(snapshot),1)
        self.assertEqual((snapshot[0]["observation_id"],snapshot[0]["period_start"],snapshot[0]["reporting_scope"]),
                         ("financial-revenue-1",date(2025,1,1),"consolidated"))
        with self.assertRaises(RepositoryIntegrityError):
            self.analytics.financial_observations_as_of(exchange="NSE",session_date=screen_day,cutoff=cutoff,
                availability_mode="public_as_of",calendar_version="missing-calendar")

    def test_historical_universe_does_not_display_future_listing_revision(self):
        _, screen_day = self._seed_source_and_calendar()
        con = self.analytics._connection
        con.execute("INSERT INTO equity_security VALUES ('security-1','issuer-1','EQ',CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-1','security-1','NSE','NSE-1',CURRENT_TIMESTAMP)")
        future_pub = datetime.combine(screen_day + timedelta(days=1), datetime.min.time(),
            tzinfo=timezone(timedelta(hours=5, minutes=30))).replace(hour=10)
        checksum = sha256(b"future listing source").hexdigest()
        con.execute("""INSERT INTO raw_source_file
            (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
             source_as_of_date,license_review_reference,license_status)
            VALUES ('file-future-listing','NSE','master','master.csv',?,'archive/master',?,?,'test','approved')""",
            [checksum, future_pub, screen_day + timedelta(days=1)])
        con.execute("""INSERT INTO source_document_revision
            (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,revision_number,
             source_document_date,publication_date,published_at,ingestion_timestamp,parser_version,
             extraction_timestamp,extraction_locator)
            VALUES ('doc-future-listing','NSE','master','master.csv','file-future-listing',?,1,?,?,?,?, 'p1',?,'csv')""",
            [checksum, screen_day + timedelta(days=1), screen_day + timedelta(days=1), future_pub,
             datetime.now(timezone.utc), future_pub,])
        con.execute("""INSERT INTO exchange_listing_revision
            (listing_revision_id,listing_id,symbol,series,status,effective_from,effective_to,source_document_id)
            VALUES ('listing-rev-future','listing-1','FUTURE','EQ','active',DATE '2020-01-01',NULL,'doc-future-listing')""")
        con.execute("""INSERT INTO exchange_listing_revision_review
            (listing_revision_review_id,listing_revision_id,review_status,recorded_by,recorded_at,
             reviewed_by,reviewed_at,evidence_source_document_id,evidence_locator,rationale)
            VALUES ('listing-review','listing-rev-future','approved','reviewer',CURRENT_TIMESTAMP,
                    'reviewer',CURRENT_TIMESTAMP,'doc-class','page 1','Verified listing revision')""")
        rows = universe_for_session(self.analytics, exchange="NSE", session_date=screen_day,
            availability_mode="public_as_of", calendar_version="nse-test-cal")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["symbol"])
        self.assertEqual(rows[0]["disposition"], "unresolved_classification")

    def test_engine_evidence_reviews_and_end_to_end_pit_company_and_liquidity_inputs(self):
        _, today = self._seed_source_and_calendar()
        tz = timezone(timedelta(hours=5, minutes=30))
        con = self.analytics._connection
        # Admit security and listing on NSE so universe_for_session marks it eligible
        con.execute("INSERT INTO equity_security VALUES ('security-1','issuer-1','ordinary',CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-1','security-1','NSE','3045',CURRENT_TIMESTAMP)")
        con.execute("""INSERT INTO security_identifier_revision
            (identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,source_document_id,mapping_review_status)
            VALUES ('id-1','security-1','ISIN','INE062A01020',DATE '2020-01-01','doc-class','pending')""")
        self.analytics.append_security_identifier_review(
            identifier_revision_id="id-1", review_status="approved", reviewer="analyst",
            reviewer_actor_type="human", evidence_source_document_id="doc-class",
            evidence_locator="row 1", rationale="Verified ISIN",
        )
        self.analytics.append_exchange_listing_revision({
            "listing_revision_id": "listrev-1", "listing_id": "listing-1", "symbol": "SBIN",
            "series": "EQ", "status": "active", "effective_from": date(2020, 1, 1),
            "source_document_id": "doc-class", "extraction_locator": "row 1", "parser_version": "p1",
        })
        self.analytics.append_exchange_listing_revision_review({
            "listing_revision_review_id": "listrev-chk-1", "listing_revision_id": "listrev-1",
            "review_status": "approved", "reviewed_by": "analyst",
            "evidence_source_document_id": "doc-class", "evidence_locator": "row 1",
            "rationale": "Verified active listing",
        })
        self.analytics.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": "snap-1", "listing_id": "listing-1",
            "exchange": "NSE", "source_document_id": "doc-class", "source_snapshot_date": date(2025, 5, 1),
            "raw_isin": "INE062A01020", "raw_symbol": "SBIN", "parser_version": "p1", "extraction_locator": "row 1",
        })
        self.analytics.append_listing_classification_review_revision({
            "classification_review_revision_id": "class-chk-1", "listing_classification_snapshot_id": "snap-1",
            "listing_id": "listing-1", "rationale": "Mainboard ordinary equity",
            "instrument_review_status": "approved", "instrument_class": "ordinary_equity",
            "instrument_valid_from": date(2020, 1, 1), "instrument_evidence_source_document_id": "doc-class",
            "instrument_evidence_locator": "row 1", "instrument_reviewed_by": "analyst",
            "platform_review_status": "approved", "platform_class": "mainboard",
            "platform_valid_from": date(2020, 1, 1), "platform_evidence_source_document_id": "doc-class",
            "platform_evidence_locator": "row 1", "platform_reviewed_by": "analyst",
        })
        self.repo.append_business_classification_review(
            entity_id="issuer-1", business_class="industrial", valid_from="2020-01-01", valid_to=None,
            reviewer="analyst", rationale="Industrial issuer", source_document_id="doc-class", locator="page 1",
        )
        # Seed capex metrics for 2 consecutive years
        con.execute("INSERT INTO financial_metric_definition VALUES ('capex','INR','currency','Capex','v1')")
        pub = datetime(2025, 5, 1, 10, 0, tzinfo=tz)
        ingested = datetime(2025, 5, 1, 11, 0, tzinfo=tz)
        for idx, (yr, val) in enumerate(((2023, "100"), (2024, "160")), start=1):
            self.analytics.append_financial_observation(FinancialObservationRevision(
                observation_id=f"capex-{idx}", subject_id="issuer-1", metric="capex",
                raw_value=Decimal(val), raw_unit="INR", canonical_value=Decimal(val), canonical_unit="INR",
                period_start=date(yr, 4, 1), period_end=date(yr + 1, 3, 31),
                source_document_date=date(2025, 5, 1), publication_date=date(2025, 5, 1),
                publication_precision=PublicationPrecision.TIMESTAMP, published_at=pub,
                ingestion_timestamp=ingested, revision_number=1, source_document_id="doc-class",
                as_reported_status=AsReportedStatus.ORIGINAL, quality_status=QualityStatus.OBSERVED,
                source_locator=f"line {idx}", parser_version="parser-1", extraction_timestamp=ingested,
            ))

        # Engine evidence requires source citation when approved
        with self.assertRaisesRegex(ValueError, "source_document_id and locator"):
            self.repo.append_engine_evidence_review(
                entity_id="issuer-1", evidence_key="commissioning", review_status="approved",
                valid_from="2024-01-01", reviewer="analyst", rationale="Missing source",
            )
        for key in ("commissioning", "demand", "customer_evidence", "forced_selling", "absorption_capacity"):
            rev_id = self.repo.append_engine_evidence_review(
                entity_id="issuer-1", evidence_key=key, review_status="approved",
                valid_from="2024-01-01", reviewer="analyst", rationale=f"Verified {key}",
                source_document_id="doc-class", locator=f"section-{key}",
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.repo.connection.execute(
                "DELETE FROM engine_evidence_review_revision WHERE review_revision_id=?", (rev_id,)
            )

        # Seed EOD & delivery observations across two sessions (today - 1 day and today + 1 day)
        prev_day = today - timedelta(days=1)
        screen_day = today + timedelta(days=1)
        for idx, (day, vol, deliv_pct) in enumerate(((prev_day, 1000, Decimal("35.0")), (screen_day, 4000, Decimal("65.0"))), start=1):
            proc_id = con.execute("SELECT processing_revision_id FROM source_document_processing_revision WHERE parser_version='parser-1' LIMIT 1").fetchone()[0]
            self.analytics.append_eod_price_observation({
                "observation_id": f"eod-{idx}", "security_id": "security-1", "listing_id": "listing-1",
                "exchange": "NSE", "trade_date": day, "open_raw": Decimal("100"), "high_raw": Decimal("110"),
                "low_raw": Decimal("95"), "close_raw": Decimal("105"), "volume_raw": Decimal(vol),
                "turnover_raw": Decimal(vol * 100), "source_document_id": "doc-class",
                "source_identifier": "classification.csv",
                "checksum_sha256": sha256(b"official classification source").hexdigest(),
                "parser_version": "parser-1", "extraction_timestamp": ingested,
                "extraction_locator": f"eod-row-{idx}", "quality_status": "observed",
                "extraction_revision_id": proc_id,
            })
            con.execute(
                """INSERT INTO normalized_observation_registry
                   (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                    parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                   VALUES (?,'delivery','doc-class','classification.csv',?,'parser-1',?,?,?)""",
                [f"deliv-{idx}", sha256(b"official classification source").hexdigest(), ingested, f"deliv-row-{idx}", proc_id],
            )
            con.execute(
                """INSERT INTO delivery_observation_revision
                   (observation_id,observation_type,security_id,listing_id,exchange,trade_date,
                    delivery_quantity_raw,traded_quantity_raw,delivery_percentage_raw,source_document_id,
                    parser_version,extraction_timestamp,extraction_locator,quality_status)
                   VALUES (?,'delivery','security-1','listing-1','NSE',?,?,?,?, 'doc-class','parser-1',?,?,'observed')""",
                [f"deliv-{idx}", day, Decimal(vol) * deliv_pct / Decimal("100"), Decimal(vol), deliv_pct, ingested, f"deliv-row-{idx}"],
            )

        # Also seed a corporate action with TIMESTAMPTZ published_at and verify corporate_action_events_as_of
        con.execute(
            """INSERT INTO normalized_observation_registry
               (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                parser_version,extraction_timestamp,extraction_locator)
               VALUES ('ca-1','corporate_action','doc-class','classification.csv',?,'parser-1',?,'ca-row-1')""",
            [sha256(b"official classification source").hexdigest(), ingested],
        )
        con.execute(
            """INSERT INTO corporate_action_event_revision
               (event_revision_id,observation_type,event_id,revision_number,action_type,affected_security_id,
                source_document_id,publication_date,published_at,source_document_date,ex_date,terms_complete,terms_json)
               VALUES ('ca-1','corporate_action','evt-1',1,'bonus','security-1','doc-class',DATE '2025-05-01',?,
                       DATE '2025-05-01',DATE '2025-06-01',TRUE,'{"ratio":"1:1"}')""",
            [pub],
        )
        cutoff = datetime.combine(screen_day, datetime.min.time(), tzinfo=tz).replace(hour=15, minute=30)
        events = self.analytics.corporate_action_events_as_of(
            exchange="NSE", session_date=screen_day, cutoff=cutoff,
            availability_mode="public_as_of", calendar_version="nse-test-cal", issuer_entity_id="issuer-1",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_revision_id"], "ca-1")

        company = company_input_as_of(
            self.analytics, issuer_entity_id="issuer-1", exchange="NSE", session_date=screen_day,
            availability_mode="public_as_of", calendar_version="nse-test-cal", review_repository=self.repo,
        )
        self.assertEqual(company.business_class, "industrial")
        self.assertEqual(evaluate_capex_conversion(company).state, EvaluationState.TRIGGERED)

        liq = liquidity_input_as_of(
            self.analytics, issuer_entity_id="issuer-1", exchange="NSE", session_date=screen_day,
            availability_mode="public_as_of", calendar_version="nse-test-cal", review_repository=self.repo,
        )
        self.assertEqual(liq["volume_multiple"], Decimal("4"))
        self.assertEqual(liq["turnover_multiple"], Decimal("4"))
        self.assertEqual(liq["delivery_percentage"], Decimal("65.0"))
        self.assertEqual(liq["delivery_percentage_point_change"], Decimal("30.0"))
        self.assertFalse(liq["unadjusted_corporate_action_in_window"])
        all_evals = evaluate_company(
            company,
            EngineThresholds(unusual_volume_multiple=Decimal("3"), unusual_delivery_percentage_points=Decimal("20")),
            **liq,
        )
        by_engine = {item.engine: item for item in all_evals}
        self.assertEqual(by_engine["capex_conversion"].state, EvaluationState.TRIGGERED)
        self.assertEqual(by_engine["extreme_sell_side_liquidity"].state, EvaluationState.TRIGGERED)
        self.assertEqual(Decimal(by_engine["extreme_sell_side_liquidity"].inputs["delivery_percentage"]), Decimal("65.0"))

        # Verify unadjusted corporate-action split/bonus step-discontinuity guard:
        # if open/prev_close drops by >35% on today (e.g. 5:1 split from 105 to 21),
        # pre-split volume (1000) is not compared against post-split volume (4000).
        proc_id = con.execute("SELECT processing_revision_id FROM source_document_processing_revision WHERE parser_version='parser-1' LIMIT 1").fetchone()[0]
        self.analytics.append_eod_price_observation({
            "observation_id": "eod-split-day", "security_id": "security-1", "listing_id": "listing-1",
            "exchange": "NSE", "trade_date": today, "open_raw": Decimal("21"), "high_raw": Decimal("22"),
            "low_raw": Decimal("20"), "close_raw": Decimal("21"), "volume_raw": Decimal("4000"),
            "turnover_raw": Decimal("84000"), "source_document_id": "doc-class",
            "source_identifier": "classification.csv",
            "checksum_sha256": sha256(b"official classification source").hexdigest(),
            "parser_version": "parser-1", "extraction_timestamp": ingested,
            "extraction_locator": "eod-split-row", "quality_status": "observed",
            "extraction_revision_id": proc_id,
        })
        split_cutoff = datetime.combine(today, datetime.min.time(), tzinfo=tz).replace(hour=15, minute=30)
        liq_on_split = liquidity_input_as_of(
            self.analytics, issuer_entity_id="issuer-1", exchange="NSE", session_date=today,
            availability_mode="public_as_of", calendar_version="nse-test-cal", review_repository=self.repo,
        )
        self.assertTrue(liq_on_split["unadjusted_corporate_action_in_window"])
        self.assertIsNone(liq_on_split["volume_multiple"])

        # Persist screen run and verify lineage rows
        run_id = self.analytics.append_screen_run(
            run_id="run-1", engine="capex_conversion", profile_id="prof-ind", profile_version="v1",
            business_class="industrial", configuration={"capex": True},
            venue_policy_id="venue-nse", venue_policy_version="v1", primary_exchange="NSE",
            as_of_session=screen_day, cutoff=cutoff, availability_mode="public_as_of",
            exchange_calendar_version="nse-test-cal", code_version="0.1.0", created_by="analyst",
            results=[{
                "result_id": "res-1",
                "subject_entity_id": "issuer-1",
                "calculation_expression": by_engine["capex_conversion"].calculation_expression,
                "inputs": by_engine["capex_conversion"].inputs,
                "result": by_engine["capex_conversion"].state.value,
                "explanation": by_engine["capex_conversion"].explanation,
                "source_document_ids": by_engine["capex_conversion"].source_document_ids,
                "source_observation_ids": by_engine["capex_conversion"].source_observation_ids,
            }],
        )
        self.assertEqual(run_id, "run-1")
        self.assertEqual(con.execute("SELECT count(*) FROM screen_result_source_observation WHERE result_id='res-1'").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
