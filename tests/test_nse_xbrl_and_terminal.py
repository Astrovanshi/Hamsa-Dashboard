"""Tests for NSE XBRL financial parsing/ingestion and HAMSA Terminal analytics."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.ingestion.nse_xbrl import (
    ingest_local_xbrl_file,
    parse_nse_broadcast_timestamp,
    parse_nse_xbrl_bytes,
)
from hamsa.screening.data_access import (
    company_input_as_of,
    discovery_feed_as_of,
    financial_coverage_matrix,
    market_radar_snapshot,
)
from hamsa.screening.engines import EngineThresholds, EvaluationState, evaluate_company
from hamsa.storage.duckdb_repository import DuckDBRepository

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_XBRL = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2024/03/31/in-capmkt">
  <xbrli:context id="OneD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">TESTCO</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2026-01-01</xbrli:startDate>
      <xbrli:endDate>2026-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="FourD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">TESTCO</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2025-04-01</xbrli:startDate>
      <xbrli:endDate>2026-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="OneI">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">TESTCO</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:instant>2026-03-31</xbrli:instant>
    </xbrli:period>
  </xbrli:context>

  <in-capmkt:Symbol contextRef="OneD">TESTCO</in-capmkt:Symbol>
  <in-capmkt:ISIN contextRef="OneD">INE062A01020</in-capmkt:ISIN>
  <in-capmkt:NameOfTheCompany contextRef="OneD">Test Industrial Limited</in-capmkt:NameOfTheCompany>
  <in-capmkt:TypeOfCompany contextRef="OneD">Main Board</in-capmkt:TypeOfCompany>
  <in-capmkt:ClassOfSecurity contextRef="OneD">Equity</in-capmkt:ClassOfSecurity>
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
  <in-capmkt:WhetherResultsAreAuditedOrUnaudited contextRef="OneD">Audited</in-capmkt:WhetherResultsAreAuditedOrUnaudited>
  <in-capmkt:DateOfStartOfReportingPeriod contextRef="OneD">2026-01-01</in-capmkt:DateOfStartOfReportingPeriod>
  <in-capmkt:DateOfEndOfReportingPeriod contextRef="OneD">2026-03-31</in-capmkt:DateOfEndOfReportingPeriod>
  <in-capmkt:RevenueFromOperations contextRef="OneD">5000000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:OtherIncome contextRef="OneD">100000000</in-capmkt:OtherIncome>
  <in-capmkt:FinanceCosts contextRef="OneD">50000000</in-capmkt:FinanceCosts>
  <in-capmkt:DepreciationDepletionAndAmortisationExpense contextRef="OneD">150000000</in-capmkt:DepreciationDepletionAndAmortisationExpense>
  <in-capmkt:ProfitBeforeExceptionalItemsAndTax contextRef="OneD">900000000</in-capmkt:ProfitBeforeExceptionalItemsAndTax>
  <in-capmkt:ProfitBeforeTax contextRef="OneD">900000000</in-capmkt:ProfitBeforeTax>
  <in-capmkt:ProfitLossForPeriod contextRef="OneD">680000000</in-capmkt:ProfitLossForPeriod>
  <in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD">12.50</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>

  <in-capmkt:DateOfStartOfReportingPeriod contextRef="FourD">2025-04-01</in-capmkt:DateOfStartOfReportingPeriod>
  <in-capmkt:DateOfEndOfReportingPeriod contextRef="FourD">2026-03-31</in-capmkt:DateOfEndOfReportingPeriod>
  <in-capmkt:RevenueFromOperations contextRef="FourD">18000000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:OtherIncome contextRef="FourD">300000000</in-capmkt:OtherIncome>
  <in-capmkt:FinanceCosts contextRef="FourD">200000000</in-capmkt:FinanceCosts>
  <in-capmkt:DepreciationDepletionAndAmortisationExpense contextRef="FourD">600000000</in-capmkt:DepreciationDepletionAndAmortisationExpense>
  <in-capmkt:ProfitBeforeExceptionalItemsAndTax contextRef="FourD">3200000000</in-capmkt:ProfitBeforeExceptionalItemsAndTax>
  <in-capmkt:ProfitBeforeTax contextRef="FourD">3200000000</in-capmkt:ProfitBeforeTax>
  <in-capmkt:ProfitLossForPeriod contextRef="FourD">2400000000</in-capmkt:ProfitLossForPeriod>
  <in-capmkt:CashFlowsFromUsedInOperatingActivities contextRef="FourD">2600000000</in-capmkt:CashFlowsFromUsedInOperatingActivities>
  <in-capmkt:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities contextRef="FourD">800000000</in-capmkt:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities>

  <in-capmkt:PropertyPlantAndEquipment contextRef="OneI">4500000000</in-capmkt:PropertyPlantAndEquipment>
  <in-capmkt:CapitalWorkInProgress contextRef="OneI">650000000</in-capmkt:CapitalWorkInProgress>
  <in-capmkt:Assets contextRef="OneI">14000000000</in-capmkt:Assets>
  <in-capmkt:Equity contextRef="OneI">8500000000</in-capmkt:Equity>
  <in-capmkt:BorrowingsNoncurrent contextRef="OneI">1000000000</in-capmkt:BorrowingsNoncurrent>
  <in-capmkt:BorrowingsCurrent contextRef="OneI">500000000</in-capmkt:BorrowingsCurrent>
  <in-capmkt:TradeReceivablesCurrent contextRef="OneI">1200000000</in-capmkt:TradeReceivablesCurrent>
  <in-capmkt:Inventories contextRef="OneI">1500000000</in-capmkt:Inventories>
  <in-capmkt:TradePayablesCurrent contextRef="OneI">900000000</in-capmkt:TradePayablesCurrent>
  <in-capmkt:CashAndCashEquivalents contextRef="OneI">1100000000</in-capmkt:CashAndCashEquivalents>
</xbrli:xbrl>
"""


class NseXbrlAndTerminalAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = DuckDBRepository(self.root / "test.duckdb")
        self.reviews = DossierReviewRepository(
            self.root / "reviews.sqlite3",
            schema_path=ROOT / "sql" / "sqlite_schema.sql",
            analytics_repository=self.repo,
        )

    def tearDown(self) -> None:
        self.reviews.close()
        self.repo.close()
        self.temp.cleanup()

    def test_parse_nse_xbrl_extracts_quarterly_annual_balance_sheet_and_derived_metrics(self) -> None:
        parsed = parse_nse_xbrl_bytes(SAMPLE_XBRL)
        self.assertEqual(parsed.symbol, "TESTCO")
        self.assertEqual(parsed.isin, "INE062A01020")
        self.assertEqual(parsed.reporting_scope, "consolidated")
        self.assertTrue(parsed.audited)

        by_key = {(f.metric, f.period_start, f.period_end): f for f in parsed.facts}
        # Quarterly revenue & derived operating margin (OneD: 2026-01-01..2026-03-31)
        q_start, q_end = date(2026, 1, 1), date(2026, 3, 31)
        self.assertEqual(by_key[("revenue", q_start, q_end)].value, Decimal("5000000000"))
        self.assertIsNone(by_key[("revenue", q_start, q_end)].formula_version)
        # Operating EBITDA = PBT(900M) + Interest(50M) + Dep(150M) - OtherIncome(100M) = 1000M -> 20% of 5000M
        self.assertEqual(by_key[("ebitda", q_start, q_end)].value, Decimal("1000000000"))
        self.assertEqual(by_key[("operating_margin", q_start, q_end)].value, Decimal("20"))
        self.assertIsNotNone(by_key[("operating_margin", q_start, q_end)].formula_version)

        # Annual CFO, Capex, derived FCF, and derived ROCE (FourD + OneI: 2025-04-01..2026-03-31)
        fy_start, fy_end = date(2025, 4, 1), date(2026, 3, 31)
        self.assertEqual(by_key[("cfo", fy_start, fy_end)].value, Decimal("2600000000"))
        self.assertEqual(by_key[("capex", fy_start, fy_end)].value, Decimal("800000000"))
        self.assertEqual(by_key[("fcf", fy_start, fy_end)].value, Decimal("1800000000"))
        # EBIT = 3200M + 200M = 3400M; Capital Employed = Equity(8500M) + Debt(1500M) = 10000M -> ROCE = 34%
        self.assertEqual(by_key[("roce", fy_start, fy_end)].value, Decimal("34"))

    def test_ingest_local_xbrl_persists_lineage_and_populates_coverage_and_radar(self) -> None:
        pub_date, pub_at = parse_nse_broadcast_timestamp("24-Apr-2026 19:30:00", fallback_date=date(2026, 4, 24))
        self.assertEqual(pub_date, date(2026, 4, 24))
        self.assertIsNotNone(pub_at)

        xbrl_file = self.root / "TESTCO_FY26.xml"
        xbrl_file.write_bytes(SAMPLE_XBRL)

        # Unmapped ISIN is quarantined first
        acc_q, rev_q, quar_q = ingest_local_xbrl_file(
            self.repo, xbrl_file, archive_root=self.root / "archive",
            source_identifier="NSE-IF-TESTCO-1", source_document_date=date(2026, 3, 31),
            publication_date=pub_date, published_at=pub_at,
        )
        self.assertEqual((acc_q, rev_q, quar_q), (0, 0, 1))

        # Admit TESTCO (INE062A01020) and re-ingest a new filing
        src_doc = self.repo.register_local_source_document(
            xbrl_file, archive_root=self.root / "archive", exchange="NSE",
            dataset="master", source_identifier="MASTER-1",
            source_document_date=date(2020, 1, 1), publication_date=date(2020, 1, 1),
            published_at=datetime(2020, 1, 1, 9, 0, tzinfo=MARKET_TIMEZONE),
            parser_version="v1", retention_authorized=True,
        )
        cand = self.repo.append_security_identity_candidate(
            issuer_entity_id="issuer-testco", security_id="sec-testco", listing_id="list-testco",
            exchange="NSE", exchange_instrument_id="100", isin="INE062A01020",
            legal_name="Test Industrial Limited", identity_observed_from=date(2020, 1, 1),
            source_document_id=src_doc.source_document_id, source_locator="row:1",
        )
        self.repo.append_security_identifier_review(
            identifier_revision_id=cand["identifier_revision_id"], review_status="approved",
            reviewer="analyst", reviewer_actor_type="human",
            evidence_source_document_id=src_doc.source_document_id, evidence_locator="row:1",
        )
        lrev = self.repo.append_exchange_listing_revision({
            "listing_revision_id": "lrev-1", "listing_id": "list-testco", "symbol": "TESTCO",
            "series": "EQ", "status": "active", "effective_from": date(2020, 1, 1),
            "source_document_id": src_doc.source_document_id, "extraction_locator": "row:1", "parser_version": "v1",
        })
        self.repo.append_exchange_listing_revision_review({
            "listing_revision_review_id": "lchk-1", "listing_revision_id": lrev,
            "review_status": "approved", "reviewed_by": "analyst",
            "evidence_source_document_id": src_doc.source_document_id, "evidence_locator": "row:1",
            "rationale": "Active",
        })
        snap = self.repo.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": "snap-1", "listing_id": "list-testco",
            "exchange": "NSE", "source_document_id": src_doc.source_document_id,
            "source_snapshot_date": date(2026, 1, 1), "raw_isin": "INE062A01020",
            "raw_symbol": "TESTCO", "parser_version": "v1", "extraction_locator": "row:1",
        })
        self.repo.append_listing_classification_review_revision({
            "classification_review_revision_id": "cchk-1", "listing_classification_snapshot_id": snap,
            "listing_id": "list-testco", "rationale": "Mainboard ordinary equity",
            "instrument_review_status": "approved", "instrument_class": "ordinary_equity",
            "instrument_valid_from": date(2020, 1, 1),
            "instrument_evidence_source_document_id": src_doc.source_document_id,
            "instrument_evidence_locator": "row:1", "instrument_reviewed_by": "analyst",
            "platform_review_status": "approved", "platform_class": "mainboard",
            "platform_valid_from": date(2020, 1, 1),
            "platform_evidence_source_document_id": src_doc.source_document_id,
            "platform_evidence_locator": "row:1", "platform_reviewed_by": "analyst",
        })
        self.reviews.append_business_classification_review(
            entity_id="issuer-testco", business_class="industrial", valid_from="2020-01-01",
            valid_to=None, reviewer="analyst", rationale="Industrial",
            source_document_id=src_doc.source_document_id, locator="row:1",
            reviewed_at=datetime(2020, 1, 2, 10, 0, tzinfo=timezone.utc),
        )
        self.repo._connection.execute(
            "INSERT INTO exchange_trading_session VALUES ('NSE', DATE '2026-05-04', TRUE, 'regular', 'nse-cal', ?)",
            [src_doc.source_document_id],
        )

        acc, rev, quar = ingest_local_xbrl_file(
            self.repo, xbrl_file, archive_root=self.root / "archive",
            source_identifier="NSE-IF-TESTCO-2", source_document_date=date(2026, 3, 31),
            publication_date=pub_date, published_at=pub_at, parser_version="nse-xbrl-v2",
        )
        self.assertGreater(acc, 20)
        self.assertEqual((rev, quar), (0, 0))
        lineage_cnt = self.repo._connection.execute("SELECT count(*) FROM observation_lineage_input").fetchone()[0]
        self.assertGreater(lineage_cnt, 0)

        cov = financial_coverage_matrix(
            self.repo, review_repository=self.reviews, exchange="NSE",
            session_date=date(2026, 5, 4), availability_mode="public_as_of", calendar_version="nse-cal",
        )
        self.assertEqual(len(cov), 1)
        self.assertEqual(cov[0]["symbol"], "TESTCO")
        self.assertEqual(cov[0]["annual_years"], 1)
        self.assertEqual(cov[0]["quarterly_periods"], 1)

        radar = market_radar_snapshot(
            self.repo, exchange="NSE", session_date=date(2026, 5, 4),
            availability_mode="public_as_of", calendar_version="nse-cal",
            review_repository=self.reviews,
        )
        self.assertEqual(radar["eligible_count"], 1)
        feed = discovery_feed_as_of(
            self.repo, exchange="NSE", session_date=date(2026, 5, 4),
            availability_mode="public_as_of", calendar_version="nse-cal",
            review_repository=self.reviews,
        )
        self.assertIsInstance(feed, list)


if __name__ == "__main__":
    unittest.main()
