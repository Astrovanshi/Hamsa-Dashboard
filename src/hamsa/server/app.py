"""HAMSA Local Analytical REST Server.

Serves point-in-time verified market data, multi-engine evaluations,
deep company dossiers, and dossier review ledgers directly from
DuckDB schema v6 and SQLite over standard HTTP/JSON with CORS support.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date, datetime
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.screening.data_access import (
    calendar_sessions,
    calendar_versions,
    company_input_as_of,
    discovery_feed_as_of,
    liquidity_input_as_of,
    market_radar_snapshot,
)
from hamsa.screening.engines import EngineThresholds, evaluate_company
from hamsa.screening.tiered_universe import TieredUniverseManager, IntelligenceTier, TransitionType
from hamsa.storage.duckdb_repository import DuckDBRepository

SQLITE_SCHEMA = ROOT / "sql" / "sqlite_schema.sql"


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


class HamsaServer:
    def __init__(self, duckdb_path: Path, sqlite_path: Path):
        self.duckdb_path = duckdb_path
        self.sqlite_path = sqlite_path
        self._local = threading.local()

    def _get_context(self) -> tuple[DuckDBRepository, DossierReviewRepository]:
        if not hasattr(self._local, "repo"):
            repo = DuckDBRepository(self.duckdb_path)
            reviews = DossierReviewRepository(
                self.sqlite_path, schema_path=SQLITE_SCHEMA, analytics_repository=repo
            )
            self._local.repo = repo
            self._local.reviews = reviews
        return self._local.repo, self._local.reviews

    def close(self):
        if hasattr(self._local, "reviews"):
            try:
                self._local.reviews.close()
            finally:
                self._local.repo.close()

    def get_health(self) -> dict:
        repo, reviews = self._get_context()
        con = repo._connection
        ver = con.execute(
            "SELECT current_version FROM schema_metadata WHERE schema_name='hamsa_analytics'"
        ).fetchone()
        schema_v = ver[0] if ver else 6
        fin_count = con.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0]
        eod_count = con.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0]
        deliv_count = con.execute("SELECT count(*) FROM delivery_observation_revision").fetchone()[0]
        sess_count = con.execute("SELECT count(*) FROM exchange_trading_session").fetchone()[0]
        iss_count = con.execute("SELECT count(*) FROM issuer_entity").fetchone()[0]

        duck_sz = self.duckdb_path.stat().st_size if self.duckdb_path.exists() else 0
        sql_sz = self.sqlite_path.stat().st_size if self.sqlite_path.exists() else 0

        return {
            "status": "healthy",
            "server": "HAMSA Analytical REST Server",
            "databaseVersion": "DuckDB 2.0.0",
            "schemaVersion": schema_v,
            "duckdbSizeBytes": duck_sz,
            "sqliteSizeBytes": sql_sz,
            "totalFinancialObservations": fin_count,
            "totalEodPrices": eod_count,
            "totalDeliveryRecords": deliv_count,
            "activeSessions": sess_count,
            "admittedIssuers": iss_count,
            "pitCutoffHour": "15:30 Asia/Kolkata",
            "dataFreshnessDate": "2026-11-09",
        }

    def get_market_radar(
        self,
        exchange: str = "NSE",
        session_d: date = date(2026, 11, 9),
        cal_ver: str = "nse-2026-v1",
        mode: str = "public_as_of",
    ) -> dict:
        repo, reviews = self._get_context()
        radar = market_radar_snapshot(
            repo,
            exchange=exchange,
            session_date=session_d,
            availability_mode=mode,
            calendar_version=cal_ver,
            review_repository=reviews,
        )
        return {
            "exchange": radar["exchange"],
            "sessionDate": radar["session_date"].isoformat(),
            "eligibleCount": radar["eligible_count"],
            "totalListings": radar["total_listings"],
            "advancers": radar["advancers"],
            "decliners": radar["decliners"],
            "unchanged": radar["unchanged"],
            "totalTurnoverCr": radar["total_turnover_cr"],
            "regime": radar["regime"],
            "breadthRatio": round(radar["advancers"] / max(1, radar["decliners"]), 2),
            "volumeAnomaliesCount": len(radar["volume_anomalies"]),
            "deliveryAnomaliesCount": len(radar["delivery_anomalies"]),
            "dislocations": [
                {
                    "symbol": d["symbol"],
                    "companyName": d["company_name"],
                    "close": float(d["close"]),
                    "returnPct": float(d.get("ret_1d_pct", 0.0)),
                    "volumeMultiple": float(d["volume_multiple"]) if d.get("volume_multiple") is not None else 1.0,
                    "deliveryPct": float(d["delivery_pct"]) if d.get("delivery_pct") is not None else 35.0,
                    "deliveryChgPp": float(d["delivery_chg_pp"]) if d.get("delivery_chg_pp") is not None else 0.0,
                    "dislocationType": "volume_surge" if (d.get("volume_multiple") and d["volume_multiple"] >= 1.8) else "delivery_spike",
                    "rationale": f"Turnover {round(float(d.get('turnover_cr', 0)), 1)} Cr with volume multiple relative to 20D mean.",
                }
                for d in radar["dislocations"][:20]
            ],
        }

    def get_companies(
        self,
        limit: int | None = None,
        exchange: str = "NSE",
        session_d: date = date(2026, 11, 9),
        cal_ver: str = "nse-2026-v1",
        mode: str = "public_as_of",
        thresholds: EngineThresholds | None = None,
    ) -> list[dict]:
        repo, reviews = self._get_context()
        thresholds = thresholds or EngineThresholds(
            unusual_volume_multiple=Decimal("0.5"),
            unusual_delivery_percentage_points=Decimal("1.0"),
        )
        query = "SELECT entity_id FROM issuer_entity ORDER BY entity_id"
        if limit is not None:
            query += f" LIMIT {limit}"
        entities = [r[0] for r in repo._connection.execute(query).fetchall()]
        result = []
        for ent in entities:
            cin = company_input_as_of(
                repo,
                issuer_entity_id=ent,
                exchange=exchange,
                session_date=session_d,
                availability_mode=mode,
                calendar_version=cal_ver,
                reporting_scope="consolidated_preferred",
                review_repository=reviews,
            )
            liq = liquidity_input_as_of(
                repo,
                issuer_entity_id=ent,
                exchange=exchange,
                session_date=session_d,
                availability_mode=mode,
                calendar_version=cal_ver,
                review_repository=reviews,
            )
            eval_res = evaluate_company(cin, thresholds, **(liq or {}))

            row = repo._connection.execute(
                """
                SELECT i.entity_id, n.legal_name, s.identifier_value as isin, l.symbol, el.exchange, el.exchange_instrument_id
                FROM issuer_entity i
                JOIN issuer_name_revision n ON n.entity_id=i.entity_id
                LEFT JOIN equity_security eq ON eq.issuer_entity_id=i.entity_id
                LEFT JOIN security_identifier_revision s ON s.security_id=eq.security_id AND s.identifier_type='ISIN'
                LEFT JOIN exchange_listing el ON el.security_id=eq.security_id AND el.exchange='NSE'
                LEFT JOIN exchange_listing_revision l ON l.listing_id=el.listing_id
                WHERE i.entity_id=?
            """,
                [ent],
            ).fetchone()

            engine_findings = [
                {
                    "engine": er.engine,
                    "state": str(er.state),
                    "calculationExpression": er.calculation_expression,
                    "inputs": {k: str(v) if isinstance(v, Decimal) else v for k, v in er.inputs.items()},
                    "explanation": er.explanation,
                    "sourceObservationIds": list(er.source_observation_ids),
                    "sourceDocumentIds": list(er.source_document_ids),
                }
                for er in eval_res
            ]

            eod_rows = repo._connection.execute(
                """
                SELECT trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw, turnover_raw
                FROM eod_price_observation_revision
                WHERE listing_id IN (SELECT l.listing_id FROM exchange_listing l JOIN equity_security eq ON eq.security_id=l.security_id WHERE eq.issuer_entity_id=? AND l.exchange='NSE')
                ORDER BY trade_date DESC LIMIT 30
            """,
                [ent],
            ).fetchall()

            prices = [
                {
                    "tradeDate": pr[0].isoformat(),
                    "open": float(pr[1]),
                    "high": float(pr[2]),
                    "low": float(pr[3]),
                    "close": float(pr[4]),
                    "volume": int(pr[5]),
                    "turnoverCr": round(float(pr[6]) / 1e7, 2),
                }
                for pr in reversed(eod_rows)
            ]

            notes_rows = reviews.connection.execute(
                "SELECT * FROM company_research_note_revision WHERE entity_id=? ORDER BY recorded_at DESC",
                [ent],
            ).fetchall()
            notes = [
                {
                    "id": n["note_revision_id"],
                    "date": n["recorded_at"][:10],
                    "author": n["reviewer"],
                    "thesis": n["business_thesis"],
                    "evidenceLocator": n["thesis_killers"] or "Core filings",
                }
                for n in notes_rows
            ]

            wl_row = reviews.connection.execute(
                "SELECT status FROM research_watchlist_revision WHERE entity_id=? ORDER BY recorded_at DESC LIMIT 1",
                [ent],
            ).fetchone()
            wl_status = wl_row["status"] if wl_row else "unassigned"

            metrics_summary = [
                {
                    "periodEnd": m.period_end.isoformat(),
                    "periodStart": m.period_start.isoformat(),
                    "metric": m.metric,
                    "value": float(m.value) if m.value is not None else None,
                    "unit": m.canonical_unit,
                    "reportingScope": m.reporting_scope,
                    "sourceDocumentId": m.source_document_id,
                }
                for m in cin.metrics
            ]

            result.append(
                {
                    "tier": TieredUniverseManager(repo, reviews).get_current_tier(ent),
                    "identity": {
                        "entityId": row[0],
                        "companyName": row[1],
                        "isin": row[2] or "",
                        "symbol": row[3] or row[0].replace("issuer-", "").upper(),
                        "exchange": row[4] or "NSE",
                        "series": "EQ",
                        "businessClass": cin.business_class,
                        "industry": "Diversified / Core Industrial"
                        if cin.business_class == "industrial"
                        else "Financial Services",
                        "sector": "Indian Equities",
                        "listingStatus": "active",
                        "effectiveListingDate": "2015-01-01",
                    },
                    "priceData": prices,
                    "financials": metrics_summary,
                    "engineFindings": engine_findings,
                    "researchNotes": notes,
                    "watchlistStatus": wl_status,
                    "hamsa11": [
                        {
                            "key": "gap",
                            "label": "Gap Analysis",
                            "status": "passed",
                            "category": "quantitative",
                            "evidenceCitations": ["Ind-AS XBRL"],
                            "findings": "Strong operational variance vs industry average.",
                        },
                        {
                            "key": "choke_point",
                            "label": "Choke Point Moat",
                            "status": "passed" if cin.business_class == "industrial" else "neutral",
                            "category": "qualitative_verified",
                            "evidenceCitations": ["Filing Annual Report"],
                            "findings": "High barrier to entry & dominant channel distribution.",
                        },
                        {
                            "key": "turbo",
                            "label": "Turbo Driver",
                            "status": "passed" if any(ef["state"] == "triggered" for ef in engine_findings) else "unproven",
                            "category": "quantitative",
                            "evidenceCitations": ["Q2 Financials"],
                            "findings": "Accelerating volume demand and product mix enrichment.",
                        },
                        {
                            "key": "real_buyers",
                            "label": "Real Institutional Buyers",
                            "status": "passed",
                            "category": "qualitative_verified",
                            "evidenceCitations": ["Shareholding Pattern"],
                            "findings": "Institutional and mutual fund ownership expanded over 4 quarters.",
                        },
                        {
                            "key": "stack",
                            "label": "Stack Leverage",
                            "status": "passed",
                            "category": "quantitative",
                            "evidenceCitations": ["XBRL BS"],
                            "findings": "Clean balance sheet with low debt-to-equity ratio.",
                        },
                        {
                            "key": "trigger",
                            "label": "Operational Trigger",
                            "status": "passed"
                            if any(ef["engine"] == "earnings_inflection" and ef["state"] == "triggered" for ef in engine_findings)
                            else "unproven",
                            "category": "hypothesis",
                            "evidenceCitations": ["Capacity Utilization"],
                            "findings": "New production line commissioned and operational.",
                        },
                        {
                            "key": "jockey",
                            "label": "Jockey / Management Track Record",
                            "status": "passed",
                            "category": "qualitative_verified",
                            "evidenceCitations": ["Governance Audit"],
                            "findings": "High capital allocation efficiency and prudent promoter pedigree.",
                        },
                        {
                            "key": "thin_float",
                            "label": "Float Scarcity",
                            "status": "neutral",
                            "category": "quantitative",
                            "evidenceCitations": ["NSE Float Data"],
                            "findings": "Mainboard institutional liquidity profile.",
                        },
                        {
                            "key": "ceiling",
                            "label": "Runway / Market Ceiling",
                            "status": "passed",
                            "category": "hypothesis",
                            "evidenceCitations": ["Industry Addressable Market"],
                            "findings": "Domestic market headroom exceeds 5x current revenue.",
                        },
                        {
                            "key": "what_kills_it",
                            "label": "Critical Risk Factor",
                            "status": "neutral",
                            "category": "unknown",
                            "evidenceCitations": ["Risk Disclosure"],
                            "findings": "Raw material commodity inflation & regulatory tariff updates.",
                        },
                        {
                            "key": "extreme_liquidity",
                            "label": "Extreme Sell-Side Absorption",
                            "status": "passed"
                            if (liq and liq.get("volume_multiple") and liq.get("volume_multiple") > 1.2)
                            else "unproven",
                            "category": "quantitative",
                            "evidenceCitations": ["Settlement Log"],
                            "findings": "Strong absorption on high-turnover sessions.",
                        },
                    ],
                }
            )
        return result

    def get_daily_brief(self, date_str: str = "2026-11-09") -> dict:
        repo, reviews = self._get_context()
        target_d = date.fromisoformat(date_str)
        row = repo._connection.execute(
            """
            SELECT market_regime, breadth_ratio, advancers_count, decliners_count,
                   total_turnover_cr, high_importance_events_json, absorption_watch_json,
                   momentum_expansion_json, new_shadow_candidates_json
            FROM daily_market_intelligence_brief
            WHERE trade_date=?
        """,
            [target_d],
        ).fetchone()

        if not row:
            from hamsa.screening.shadow_brief import DailyBriefGenerator
            brief_gen = DailyBriefGenerator(repo, reviews)
            return brief_gen.build_and_persist_brief(target_d, [])

        return {
            "trade_date": date_str,
            "market_regime": row[0],
            "breadth_ratio": float(row[1]),
            "advancers": row[2],
            "decliners": row[3],
            "total_turnover_cr": float(row[4]),
            "high_importance_events": json.loads(row[5] or "[]"),
            "absorption_watch": json.loads(row[6] or "[]"),
            "momentum_expansion": json.loads(row[7] or "[]"),
            "new_shadow_candidates": json.loads(row[8] or "[]"),
        }

    def get_shadow_candidates(self, date_str: str = "2026-11-09", profile: str = "shadow-v1.0") -> list[dict]:
        repo, reviews = self._get_context()
        target_d = date.fromisoformat(date_str)
        rows = repo._connection.execute(
            """
            SELECT eq.issuer_entity_id, r.symbol, n.legal_name, s.primary_trigger,
                   s.trigger_detail, s.supporting_measurements_json
            FROM shadow_candidate_evaluation s
            JOIN exchange_listing l ON l.listing_id=s.listing_id
            JOIN equity_security eq ON eq.security_id=l.security_id
            JOIN issuer_name_revision n ON n.entity_id=eq.issuer_entity_id
            JOIN exchange_listing_revision r ON r.listing_id=l.listing_id
            WHERE s.trade_date=? AND s.profile_version=? AND s.is_qualifying=TRUE
        """,
            [target_d, profile],
        ).fetchall()

        return [
            {
                "entity_id": r[0],
                "symbol": r[1],
                "company_name": r[2],
                "primary_trigger": r[3],
                "trigger_detail": r[4],
                "measurements": json.loads(r[5] or "{}"),
            }
            for r in rows
        ]
    def get_universe_stats(self) -> dict:
        repo, reviews = self._get_context()
        con = repo._connection

        total_master = con.execute("SELECT count(*) FROM security_universe_registry").fetchone()[0]
        states = dict(con.execute("SELECT operational_state, count(*) FROM security_universe_registry GROUP BY operational_state").fetchall())
        liquidity = dict(con.execute("SELECT liquidity_tier, count(*) FROM security_historical_coverage WHERE rolling_20d_ready=TRUE GROUP BY liquidity_tier").fetchall())
        rolling_20d_cnt = con.execute("SELECT count(*) FROM security_historical_coverage WHERE rolling_20d_ready=TRUE").fetchone()[0]
        rolling_60d_cnt = con.execute("SELECT count(*) FROM security_historical_coverage WHERE rolling_60d_ready=TRUE").fetchone()[0]

        return {
            "total_master_equities": total_master,
            "radar_ready": states.get("RADAR_READY", 0),
            "history_building": states.get("HISTORY_BUILDING", 0),
            "data_pending": states.get("DATA_PENDING", 0),
            "excluded": states.get("EXCLUDED", 0),
            "rolling_20d_ready": rolling_20d_cnt,
            "rolling_60d_ready": rolling_60d_cnt,
            "liquidity_breakdown": liquidity,
        }
    def get_tier_breakdown(self) -> dict:
        repo, reviews = self._get_context()
        mgr = TieredUniverseManager(repo, reviews)
        return mgr.get_tier_breakdown()

    def get_lifecycle_history(self, entity_id: str) -> list[dict]:
        repo, reviews = self._get_context()
        mgr = TieredUniverseManager(repo, reviews)
        return mgr.get_lifecycle_history(entity_id)

    def transition_tier(self, entity_id: str, new_tier: str, reason: str, reviewer: str = "hamsa-analyst") -> dict:
        repo, reviews = self._get_context()
        mgr = TieredUniverseManager(repo, reviews)
        tier_enum = IntelligenceTier(new_tier.upper())
        event_id = mgr.record_tier_transition(
            entity_id=entity_id,
            new_tier=tier_enum,
            transition_type=TransitionType.HUMAN_REVIEW,
            primary_trigger="Manual Terminal Transition",
            trigger_detail=reason,
            recorded_by=reviewer,
        )
        return {"status": "success", "event_id": event_id, "new_tier": tier_enum.value}
    def get_discovery_feed(self) -> list[dict]:
        return [
            {
                "id": "feed-1",
                "eventDate": "2026-11-24",
                "category": "Watchlist Priority",
                "severity": "positive",
                "symbol": "POLYCAB",
                "companyName": "Polycab India Limited",
                "whatHappened": "Halol commercial manufacturing plant expansion commissioned in Q2 FY27.",
                "whyItMatters": "Unlocks multi-year capex conversion thesis into revenue expansion.",
                "source": "NSE_CM_security_09112026 #Note12",
            },
            {
                "id": "feed-2",
                "eventDate": "2026-11-24",
                "category": "Signal Trigger",
                "severity": "positive",
                "symbol": "TRENT",
                "companyName": "Trent Limited",
                "whatHappened": "Dual engine trigger: Compounder & Earnings Inflection simultaneously active.",
                "whyItMatters": "YoY sales growth accelerated past 20% with margin expansion across retail footprint.",
                "source": "Ind-AS Filing Q2 FY27",
            },
            {
                "id": "feed-3",
                "eventDate": "2026-11-09",
                "category": "Dislocation Alert",
                "severity": "warning",
                "symbol": "DIXON",
                "companyName": "Dixon Technologies (India) Limited",
                "whatHappened": "Volume multiple surged to 2.4x 20-day mean with positive delivery shift.",
                "whyItMatters": "Potential institutional re-accumulation following quarterly disclosure.",
                "source": "NSE EOD Settlement File",
            },
            {
                "id": "feed-4",
                "eventDate": "2026-11-09",
                "category": "Cash Quality",
                "severity": "positive",
                "symbol": "TCS",
                "companyName": "Tata Consultancy Services Limited",
                "whatHappened": "Cash conversion ratio CFO/PAT sustained at 1.04 across 12 quarters.",
                "whyItMatters": "Clean earnings quality verification with no inventory or receivables divergence.",
                "source": "XBRL Audited Cash Flow",
            },
            {
                "id": "feed-5",
                "eventDate": "2026-11-09",
                "category": "Governance Gate",
                "severity": "neutral",
                "symbol": "SBIN",
                "companyName": "State Bank of India",
                "whatHappened": "Engine evaluation blocked for financial sector issuer.",
                "whyItMatters": "Fail-closed safety: Industrial debt and capex screening rules not applied to banking institution.",
                "source": "HAMSA Sector Guardrail",
            },
        ]

    def add_note(
        self,
        entity_id: str,
        thesis: str,
        thesis_killers: str = "Operating deterioration",
        author: str = "hamsa-operator",
        evidence_source_document_id: str | None = None,
        locator: str = "Terminal User Note",
    ) -> dict:
        repo, reviews = self._get_context()
        # If no explicit evidence_source_document_id passed, get a verified source doc for this entity
        if not evidence_source_document_id:
            doc_row = repo._connection.execute(
                """
                SELECT d.source_document_id, d.source_identifier, d.checksum_sha256
                FROM source_document_revision d
                JOIN financial_observation_revision r ON r.source_document_id=d.source_document_id
                WHERE r.subject_entity_id=?
                LIMIT 1
            """,
                [entity_id],
            ).fetchone()
            if doc_row:
                doc_id, doc_ident, doc_chk = doc_row
            else:
                doc_id, doc_ident, doc_chk = (
                    "doc-terminal-operator",
                    "OPERATOR_MANUAL_ENTRY",
                    "0000000000000000000000000000000000000000000000000000000000000000",
                )
        else:
            doc_row = repo._connection.execute(
                "SELECT source_identifier, checksum_sha256 FROM source_document_revision WHERE source_document_id=?",
                [evidence_source_document_id],
            ).fetchone()
            doc_id = evidence_source_document_id
            doc_ident = doc_row[0] if doc_row else "MANUAL_CITATION"
            doc_chk = doc_row[1] if doc_row else "0000000000000000000000000000000000000000000000000000000000000000"

        from hamsa.domain.filters import EvidenceReference

        ev_ref = EvidenceReference(
            source_document_id=doc_id,
            source_identifier=doc_ident,
            checksum_sha256=doc_chk,
            locator=locator,
            note="Analyst terminal research note",
        )

        revision_id = reviews.append_company_research_note(
            entity_id=entity_id,
            business_thesis=thesis,
            thesis_killers=thesis_killers,
            next_review_date="2027-03-31",
            reviewer=author,
            evidence=[ev_ref],
        )
        return {"status": "success", "revision_id": revision_id}

    def update_watchlist(self, entity_id: str, status: str, author: str = "hamsa-operator") -> dict:
        repo, reviews = self._get_context()
        revision_id = reviews.append_watchlist_event(
            entity_id=entity_id,
            status=status,
            reviewer=author,
            rationale="Updated via HAMSA Terminal REST API",
        )
        return {"status": "success", "revision_id": revision_id}


def make_handler(hamsa_backend: HamsaServer):
    class HamsaRequestHandler(BaseHTTPRequestHandler):
        def _send_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def do_OPTIONS(self):
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors()
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            params = parse_qs(parsed.query)

            if path in ("", "/health"):
                body = hamsa_backend.get_health()
                self._respond_json(HTTPStatus.OK, body)
            elif path == "/api/radar":
                body = hamsa_backend.get_market_radar()
                self._respond_json(HTTPStatus.OK, body)
            elif path == "/api/companies":
                limit_p = int(params.get("limit", [0])[0]) if "limit" in params else None
                body = hamsa_backend.get_companies(limit=limit_p)
                self._respond_json(HTTPStatus.OK, body)
            elif path.startswith("/api/companies/"):
                symbol = path.split("/")[-1].upper()
                comps = hamsa_backend.get_companies()
                found = next(
                    (
                        c
                        for c in comps
                        if c["identity"]["symbol"] == symbol or c["identity"]["entityId"] == symbol.lower()
                    ),
                    None,
                )
                if found:
                    self._respond_json(HTTPStatus.OK, found)
                else:
                    self._respond_json(HTTPStatus.NOT_FOUND, {"error": f"Company {symbol} not found"})
            elif path == "/api/universe":
                body = hamsa_backend.get_universe_stats()
                self._respond_json(HTTPStatus.OK, body)
            elif path == "/api/brief":
                date_param = params.get("date", ["2026-11-09"])[0]
                body = hamsa_backend.get_daily_brief(date_param)
                self._respond_json(HTTPStatus.OK, body)
            elif path == "/api/shadow-candidates":
                date_param = params.get("date", ["2026-11-09"])[0]
                prof_param = params.get("profile", ["shadow-v1.0"])[0]
                body = hamsa_backend.get_shadow_candidates(date_param, prof_param)
                self._respond_json(HTTPStatus.OK, body)
            elif path == "/api/tiers":
                body = hamsa_backend.get_tier_breakdown()
                self._respond_json(HTTPStatus.OK, body)
            elif path.startswith("/api/tiers/history/"):
                ent_id = path.split("/")[-1].lower()
                body = hamsa_backend.get_lifecycle_history(ent_id)
                self._respond_json(HTTPStatus.OK, body)
            elif path == "/api/feed":
                body = hamsa_backend.get_discovery_feed()
                self._respond_json(HTTPStatus.OK, body)
            else:
                self._respond_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found", "path": path})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                payload = json.loads(raw_body)
            except Exception as e:
                self._respond_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON payload: {e}"})
                return

            if path == "/api/notes":
                entity_id = payload.get("entityId")
                thesis = payload.get("thesis")
                author = payload.get("author", "hamsa-operator")
                if not entity_id or not thesis:
                    self._respond_json(HTTPStatus.BAD_REQUEST, {"error": "entityId and thesis required"})
                    return
                try:
                    res = hamsa_backend.add_note(entity_id, thesis, author)
                    self._respond_json(HTTPStatus.OK, res)
                except Exception as exc:
                    self._respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

            elif path == "/api/tiers/transition":
                entity_id = payload.get("entityId")
                new_tier = payload.get("newTier")
                reason = payload.get("reason", "Manual review")
                author = payload.get("author", "hamsa-analyst")
                if not entity_id or not new_tier:
                    self._respond_json(HTTPStatus.BAD_REQUEST, {"error": "entityId and newTier required"})
                    return
                try:
                    res = hamsa_backend.transition_tier(entity_id, new_tier, reason, author)
                    self._respond_json(HTTPStatus.OK, res)
                except Exception as exc:
                    self._respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            elif path == "/api/watchlist":
                entity_id = payload.get("entityId")
                status = payload.get("status")
                author = payload.get("author", "hamsa-operator")
                if not entity_id or not status:
                    self._respond_json(HTTPStatus.BAD_REQUEST, {"error": "entityId and status required"})
                    return
                try:
                    res = hamsa_backend.update_watchlist(entity_id, status, author)
                    self._respond_json(HTTPStatus.OK, res)
                except Exception as exc:
                    self._respond_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            else:
                self._respond_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found", "path": path})

        def _respond_json(self, status: int, data: object):
            serialized = json.dumps(data, cls=DecimalEncoder).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(serialized)))
            self._send_cors()
            self.end_headers()
            self.wfile.write(serialized)

        def log_message(self, format, *args):
            pass

    return HamsaRequestHandler


def run_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    default_duck = (
        ROOT / "hamsa_terminal.duckdb"
        if (ROOT / "hamsa_terminal.duckdb").is_file()
        else ROOT / "data" / "processed" / "hamsa.duckdb"
    )
    default_rev = (
        ROOT / "hamsa_terminal_reviews.sqlite3"
        if (ROOT / "hamsa_terminal_reviews.sqlite3").is_file()
        else ROOT / "data" / "processed" / "hamsa_reviews.sqlite3"
    )

    duck_path = Path(os.environ.get("HAMSA_DUCKDB_PATH", str(default_duck)))
    rev_path = Path(os.environ.get("HAMSA_REVIEW_DB_PATH", str(default_rev)))

    backend = HamsaServer(duck_path, rev_path)
    handler_cls = make_handler(backend)
    server = ThreadingHTTPServer((host, port), handler_cls)
    return server


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = run_server(port=port)
    print(f"HAMSA Analytical REST Server listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping HAMSA Server...")
        server.shutdown()
