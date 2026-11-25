"""HAMSA Tiered Universe & Intelligent Data Acquisition Engine.

Implements the three-tier dynamic intelligence lifecycle:
- TIER 1: RADAR (Entire eligible market, continuous EOD/delivery & behavioral signal monitoring)
- TIER 2: CANDIDATE (Behavioral admission trigger for selective fundamental intelligence acquisition & 5-engine evaluation)
- TIER 3: INVESTIGATION (Deep human research, HAMSA 11 mental model gates & thesis development)
Plus WATCH and ARCHIVED lifecycle states with automatic re-entry and complete audit transition history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.ingestion.nse_xbrl import fetch_and_ingest_symbols, ingest_local_xbrl_file
from hamsa.screening.data_access import (
    company_input_as_of,
    liquidity_input_as_of,
    market_radar_snapshot,
)
from hamsa.screening.engines import EngineThresholds, evaluate_company
from hamsa.storage.duckdb_repository import DuckDBRepository


class IntelligenceTier(StrEnum):
    RADAR = "RADAR"
    CANDIDATE = "CANDIDATE"
    INVESTIGATION = "INVESTIGATION"
    WATCH = "WATCH"
    ARCHIVED = "ARCHIVED"


class TransitionType(StrEnum):
    AUTOMATED_SIGNAL = "automated_signal"
    HUMAN_REVIEW = "human_review"
    SYSTEM_INITIALIZATION = "system_initialization"
    DECAY_DEMOTION = "decay_demotion"
    RE_ENTRY = "re_entry"


@dataclass(frozen=True, slots=True)
class RadarSignalRow:
    listing_id: str
    symbol: str
    trade_date: date
    exchange: str
    volume_multiple: Decimal | None
    turnover_multiple: Decimal | None
    avg_turnover_20d_inr: Decimal | None
    delivery_percentage: Decimal | None
    delivery_chg_pp: Decimal | None
    session_return_pct: Decimal | None
    drawdown_20d_pct: Decimal | None
    close_range_position: Decimal | None
    is_volume_dislocation: bool
    is_delivery_surge: bool
    is_extreme_sell_side: bool
    is_52w_high: bool
    is_52w_low: bool
    is_range_expansion: bool
    is_breakout: bool


class TieredUniverseManager:
    """Manages the full eligible universe, radar signals, candidate triggers, and selective ingestion."""

    def __init__(
        self,
        repository: DuckDBRepository,
        dossier_repository: DossierReviewRepository,
        *,
        archive_root: Path | None = None,
        xbrl_cache_dir: Path | None = None,
    ):
        self.repo = repository
        self.dossier_repo = dossier_repository
        self.con = repository._connection
        self.archive_root = archive_root
        self.xbrl_cache_dir = xbrl_cache_dir

    def record_tier_transition(
        self,
        *,
        entity_id: str,
        new_tier: IntelligenceTier,
        transition_type: TransitionType,
        primary_trigger: str,
        trigger_detail: str | None = None,
        supporting_signals: dict | None = None,
        recorded_by: str = "hamsa-system",
        source_document_id: str | None = None,
        transition_time: datetime | None = None,
    ) -> str:
        """Record an append-only lifecycle event."""
        now = transition_time or datetime.now(timezone.utc)
        prev_tier = self.get_current_tier(entity_id)

        if prev_tier == new_tier.value:
            return ""  # Idempotent: already at requested tier

        event_id = f"tier-{entity_id}-{new_tier.value.lower()}-{int(now.timestamp())}"
        signals_json = json.dumps(supporting_signals or {})

        self.con.execute(
            """
            INSERT OR IGNORE INTO company_intelligence_lifecycle_event (
                event_id, entity_id, previous_tier, new_tier, transition_timestamp,
                transition_type, primary_trigger, trigger_detail, supporting_signals_json,
                recorded_by, recorded_at, source_document_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                event_id,
                entity_id,
                prev_tier or "NONE",
                new_tier.value,
                now,
                transition_type.value,
                primary_trigger,
                trigger_detail,
                signals_json,
                recorded_by,
                now,
                source_document_id,
            ],
        )
        return event_id

    def get_current_tier(self, entity_id: str) -> str:
        """Return the current active tier for an entity (defaults to RADAR if admitted)."""
        row = self.con.execute(
            """
            SELECT new_tier FROM company_intelligence_lifecycle_event
            WHERE entity_id=?
            ORDER BY transition_timestamp DESC
            LIMIT 1
        """,
            [entity_id],
        ).fetchone()

        if row:
            return row[0]

        # Check if already admitted in issuer_entity
        exists = self.con.execute(
            "SELECT 1 FROM issuer_entity WHERE entity_id=?", [entity_id]
        ).fetchone()
        return IntelligenceTier.RADAR.value if exists else "NONE"

    def get_tier_breakdown(self) -> dict[str, int]:
        """Return counts of companies in each tier."""
        tiers = {t.value: 0 for t in IntelligenceTier}
        entities = [r[0] for r in self.con.execute("SELECT entity_id FROM issuer_entity").fetchall()]
        for ent in entities:
            t = self.get_current_tier(ent)
            if t in tiers:
                tiers[t] += 1
            else:
                tiers[IntelligenceTier.RADAR.value] += 1
        return tiers

    def calculate_and_store_radar_signals(
        self,
        *,
        exchange: str = "NSE",
        session_date: date = date(2026, 11, 9),
        cal_ver: str = "nse-2026-v1",
        mode: str = "public_as_of",
    ) -> int:
        """Compute deterministic behavioral signals for all admitted listings on session_date."""
        listings = self.con.execute(
            """
            SELECT l.listing_id, l.security_id, eq.issuer_entity_id, r.symbol
            FROM exchange_listing l
            JOIN equity_security eq ON eq.security_id=l.security_id
            JOIN exchange_listing_revision r ON r.listing_id=l.listing_id
            WHERE l.exchange=? AND r.status='active'
        """,
            [exchange],
        ).fetchall()

        inserted_count = 0
        now = datetime.now(timezone.utc)

        for row in listings:
            list_id, sec_id, ent_id, sym = row
            liq = liquidity_input_as_of(
                self.repo,
                issuer_entity_id=ent_id,
                exchange=exchange,
                session_date=session_date,
                availability_mode=mode,
                calendar_version=cal_ver,
                review_repository=self.dossier_repo,
            )

            if not liq:
                continue

            vol_mult = liq.get("volume_multiple")
            to_mult = liq.get("turnover_multiple")
            avg_to = liq.get("avg_turnover_20d_inr")
            del_pct = liq.get("delivery_percentage")
            del_chg = liq.get("delivery_percentage_point_change")
            ret_pct = liq.get("session_return_pct")
            dd_pct = liq.get("drawdown_from_window_high_pct")
            close_pos = liq.get("close_range_position")

            is_vol_disloc = bool(vol_mult and vol_mult >= Decimal("1.5"))
            is_del_surge = bool(del_chg and del_chg >= Decimal("5.0"))
            is_extreme_sell = bool(
                is_vol_disloc and dd_pct and dd_pct <= Decimal("-5.0") and close_pos and close_pos >= Decimal("0.3")
            )
            is_range_exp = bool(abs(ret_pct or 0) >= Decimal("4.0"))
            is_breakout = bool(ret_pct and ret_pct >= Decimal("3.0") and is_vol_disloc)
            is_52w_high = bool(dd_pct is not None and dd_pct >= Decimal("-0.5"))
            is_52w_low = bool(dd_pct is not None and dd_pct <= Decimal("-40.0"))

            sig_id = f"sig-{list_id}-{session_date.isoformat()}"
            flags = {
                "vol_disloc": is_vol_disloc,
                "del_surge": is_del_surge,
                "extreme_sell": is_extreme_sell,
                "range_exp": is_range_exp,
                "breakout": is_breakout,
            }

            self.con.execute(
                """
                INSERT OR IGNORE INTO security_radar_signal_daily (
                    signal_id, listing_id, trade_date, exchange,
                    volume_multiple, turnover_multiple, avg_turnover_20d_inr,
                    delivery_percentage, delivery_chg_pp, session_return_pct,
                    drawdown_20d_pct, close_range_position,
                    is_52w_high, is_52w_low, is_range_expansion, is_breakout,
                    is_volume_dislocation, is_delivery_surge, is_extreme_sell_side,
                    composite_radar_flags_json, calculated_at, source_document_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                [
                    sig_id,
                    list_id,
                    session_date,
                    exchange,
                    vol_mult,
                    to_mult,
                    avg_to,
                    del_pct,
                    del_chg,
                    ret_pct,
                    dd_pct,
                    close_pos,
                    is_52w_high,
                    is_52w_low,
                    is_range_exp,
                    is_breakout,
                    is_vol_disloc,
                    is_del_surge,
                    is_extreme_sell,
                    json.dumps(flags),
                    now,
                    "doc-b14cf998fefb3e8fe69486eed9410071",
                ],
            )
            inserted_count += 1

        return inserted_count

    def scan_and_promote_candidates(
        self,
        *,
        trade_date: date = date(2026, 11, 9),
        auto_acquire_fundamentals: bool = True,
    ) -> list[dict]:
        """Scan daily signals against admission rules and promote qualifying Radar equities to Tier 2 Candidate."""
        candidates_promoted = []

        signals = self.con.execute(
            """
            SELECT
                s.listing_id, eq.issuer_entity_id, r.symbol, n.legal_name,
                s.volume_multiple, s.delivery_chg_pp, s.drawdown_20d_pct,
                s.is_volume_dislocation, s.is_delivery_surge, s.is_extreme_sell_side, s.is_breakout,
                s.composite_radar_flags_json
            FROM security_radar_signal_daily s
            JOIN exchange_listing l ON l.listing_id=s.listing_id
            JOIN equity_security eq ON eq.security_id=l.security_id
            JOIN issuer_name_revision n ON n.entity_id=eq.issuer_entity_id
            JOIN exchange_listing_revision r ON r.listing_id=l.listing_id
            WHERE s.trade_date=?
        """,
            [trade_date],
        ).fetchall()

        for sig in signals:
            (
                list_id,
                ent_id,
                sym,
                name,
                vol_m,
                del_chg,
                dd_pct,
                is_vol,
                is_del,
                is_ext,
                is_bo,
                flags_json,
            ) = sig

            current_tier = self.get_current_tier(ent_id)

            # Check qualifying trigger conditions
            qualifies = False
            primary_trigger = ""
            details = []

            if is_ext:
                qualifies = True
                primary_trigger = "Extreme Sell-Side Absorption"
                details.append(f"Volume multiple {vol_m:.2f}x with drawdown {dd_pct:.1f}%")
            elif is_bo:
                qualifies = True
                primary_trigger = "Volume Breakout"
                details.append(f"Breakout expansion with volume {vol_m:.2f}x")
            elif is_vol and is_del:
                qualifies = True
                primary_trigger = "Dual Volume & Delivery Surge"
                details.append(f"Vol {vol_m:.2f}x and Deliv Δ +{del_chg:.1f}pp")
            elif is_vol:
                qualifies = True
                primary_trigger = "Abnormal Volume Dislocation"
                details.append(f"Volume multiple {vol_m:.2f}x 20D mean")

            if qualifies and current_tier in (IntelligenceTier.RADAR.value, IntelligenceTier.ARCHIVED.value, "NONE"):
                # Promote to Tier 2 Candidate
                tr_type = (
                    TransitionType.RE_ENTRY
                    if current_tier == IntelligenceTier.ARCHIVED.value
                    else TransitionType.AUTOMATED_SIGNAL
                )
                self.record_tier_transition(
                    entity_id=ent_id,
                    new_tier=IntelligenceTier.CANDIDATE,
                    transition_type=tr_type,
                    primary_trigger=primary_trigger,
                    trigger_detail="; ".join(details),
                    supporting_signals=json.loads(flags_json or "{}"),
                )

                # Check if selective fundamental acquisition is required
                has_financials = (
                    self.con.execute(
                        "SELECT count(*) FROM financial_observation_revision WHERE subject_entity_id=?",
                        [ent_id],
                    ).fetchone()[0]
                    > 0
                )

                acq_status = "already_acquired"
                if not has_financials and auto_acquire_fundamentals and self.archive_root and self.xbrl_cache_dir:
                    try:
                        sum_obj = fetch_and_ingest_symbols(
                            self.repo,
                            [sym],
                            download_cache_dir=self.xbrl_cache_dir,
                            archive_root=self.archive_root,
                            delay_seconds=0.3,
                        )
                        acq_status = f"acquired_{sum_obj.filings_succeeded}_filings"
                    except Exception as exc:
                        acq_status = f"acquisition_error: {exc}"

                candidates_promoted.append(
                    {
                        "entity_id": ent_id,
                        "symbol": sym,
                        "company_name": name,
                        "primary_trigger": primary_trigger,
                        "details": "; ".join(details),
                        "fundamental_acquisition": acq_status,
                    }
                )

        return candidates_promoted

    def demote_candidate_to_radar(self, entity_id: str, reason: str = "Signal decayed without inflection") -> str:
        """Demote candidate back to Tier 1 Radar while preserving all acquired historical fundamentals."""
        return self.record_tier_transition(
            entity_id=entity_id,
            new_tier=IntelligenceTier.RADAR,
            transition_type=TransitionType.DECAY_DEMOTION,
            primary_trigger="Signal Decay",
            trigger_detail=reason,
            recorded_by="hamsa-system",
        )

    def promote_candidate_to_investigation(
        self,
        entity_id: str,
        reason: str,
        reviewer: str = "hamsa-analyst",
    ) -> str:
        """Promote candidate to Tier 3 Deep Investigation."""
        # Also mark research watchlist as research_priority in SQLite review ledger
        self.dossier_repo.append_watchlist_event(
            entity_id=entity_id,
            status="research_priority",
            reviewer=reviewer,
            rationale=reason,
        )
        return self.record_tier_transition(
            entity_id=entity_id,
            new_tier=IntelligenceTier.INVESTIGATION,
            transition_type=TransitionType.HUMAN_REVIEW,
            primary_trigger="Analyst Thesis Promotion",
            trigger_detail=reason,
            recorded_by=reviewer,
        )

    def archive_company(self, entity_id: str, reason: str, reviewer: str = "hamsa-operator") -> str:
        """Archive company from active monitoring while keeping all history for automatic re-entry."""
        return self.record_tier_transition(
            entity_id=entity_id,
            new_tier=IntelligenceTier.ARCHIVED,
            transition_type=TransitionType.HUMAN_REVIEW,
            primary_trigger="Archived",
            trigger_detail=reason,
            recorded_by=reviewer,
        )

    def get_lifecycle_history(self, entity_id: str) -> list[dict]:
        """Return chronological transition history for an entity."""
        rows = self.con.execute(
            """
            SELECT
                event_id, previous_tier, new_tier, strftime(transition_timestamp, '%Y-%m-%d %H:%M:%S'),
                transition_type, primary_trigger, trigger_detail, recorded_by
            FROM company_intelligence_lifecycle_event
            WHERE entity_id=?
            ORDER BY transition_timestamp DESC
        """,
            [entity_id],
        ).fetchall()

        return [
            {
                "event_id": r[0],
                "previous_tier": r[1],
                "new_tier": r[2],
                "timestamp": r[3],
                "transition_type": r[4],
                "primary_trigger": r[5],
                "trigger_detail": r[6],
                "recorded_by": r[7],
            }
            for r in rows
        ]
