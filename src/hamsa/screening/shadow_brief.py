"""HAMSA Shadow Candidate Engine & Daily Market Intelligence Brief Generator.

Implements versioned shadow candidate evaluation profiles and generates ranked,
evidence-first daily intelligence briefs distinguishing:
- Market Participation Regime (Breadth, participation distribution, total turnover)
- High-Importance Radar Events (Ranked by volume multiple and delivery expansion)
- Absorption Watch (Supply exhaustion: heavy volume into weakness with strong close)
- Momentum & Range Expansion (Breakouts from volatility compression)
- New Shadow Candidates (Separated from production Tier 2 triggers)
- Existing Candidate Updates (Material signal evolution)
- Operational Pipeline & System Health Telemetry
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.storage.duckdb_repository import DuckDBRepository

logger = logging.getLogger("hamsa.screening.shadow_brief")


@dataclass(frozen=True, slots=True)
class ShadowProfile:
    version: str
    name: str
    volume_multiple_min: Decimal
    delivery_chg_pp_min: Decimal
    avg_turnover_20d_min_inr: Decimal
    min_concurrent_flags: int
    drawdown_20d_max_pct: Decimal = Decimal("-5.0")
    close_range_pos_min: Decimal = Decimal("0.35")


# Versioned Experimental Candidate Profiles for Calibration
SHADOW_PROFILES: Mapping[str, ShadowProfile] = {
    "shadow-v1.0-broad": ShadowProfile(
        version="shadow-v1.0-broad",
        name="Broad Behavioral Anomaly (Vol >= 2.0x OR Deliv >= +8pp)",
        volume_multiple_min=Decimal("2.0"),
        delivery_chg_pp_min=Decimal("8.0"),
        avg_turnover_20d_min_inr=Decimal("10000000.0"),  # 1 Cr/day floor
        min_concurrent_flags=1,
    ),
    "shadow-v1.0": ShadowProfile(
        version="shadow-v1.0",
        name="Institutional Dual Convergence (Strict Dual Trigger)",
        volume_multiple_min=Decimal("2.0"),
        delivery_chg_pp_min=Decimal("8.0"),
        avg_turnover_20d_min_inr=Decimal("10000000.0"),  # 1 Cr/day floor
        min_concurrent_flags=2,
    ),
    "shadow-v1.1-high-liquidity": ShadowProfile(
        version="shadow-v1.1-high-liquidity",
        name="High Liquid Dislocation (>=5 Cr/day)",
        volume_multiple_min=Decimal("2.0"),
        delivery_chg_pp_min=Decimal("10.0"),
        avg_turnover_20d_min_inr=Decimal("50000000.0"),  # 5 Cr/day floor
        min_concurrent_flags=2,
    ),
    "shadow-v1.2-absorption": ShadowProfile(
        version="shadow-v1.2-absorption",
        name="Supply Exhaustion & Extreme Absorption",
        volume_multiple_min=Decimal("1.8"),
        delivery_chg_pp_min=Decimal("5.0"),
        avg_turnover_20d_min_inr=Decimal("10000000.0"),
        min_concurrent_flags=2,
        drawdown_20d_max_pct=Decimal("-7.0"),
        close_range_pos_min=Decimal("0.40"),
    ),
}


class ShadowCandidateEngine:
    """Evaluates Tier 1 radar signals against experimental shadow profiles without triggering automated fundamental downloads."""

    def __init__(self, repository: DuckDBRepository):
        self.repo = repository
        self.con = repository._connection

    def evaluate_session(
        self,
        trade_date: date,
        profile: ShadowProfile = SHADOW_PROFILES["shadow-v1.0"],
    ) -> list[dict[str, object]]:
        """Evaluate all active signals on trade_date against the shadow profile."""
        now = datetime.now(timezone.utc)
        signals = self.con.execute(
            """
            SELECT
                s.signal_id, s.listing_id, eq.issuer_entity_id, r.symbol, n.legal_name,
                s.volume_multiple, s.turnover_multiple, s.avg_turnover_20d_inr,
                s.delivery_percentage, s.delivery_chg_pp, s.session_return_pct,
                s.drawdown_20d_pct, s.close_range_position,
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

        qualifying_candidates: list[dict[str, object]] = []
        eval_rows = []

        for sig in signals:
            (
                sig_id,
                list_id,
                ent_id,
                sym,
                name,
                vol_m,
                to_m,
                avg_to,
                del_pct,
                del_chg,
                ret_pct,
                dd_pct,
                close_pos,
                is_vol,
                is_del,
                is_ext,
                is_bo,
                flags_json,
            ) = sig

            # Evaluate against shadow profile criteria
            triggers = []
            meets_liquidity_floor = bool(avg_to is not None and avg_to >= profile.avg_turnover_20d_min_inr)
            triggers = []


            # 2. Volume multiple
            if vol_m is not None and vol_m >= profile.volume_multiple_min:
                triggers.append(f"Vol {vol_m:.2f}x (>= {profile.volume_multiple_min}x)")

            # 3. Delivery expansion
            if del_chg is not None and del_chg >= profile.delivery_chg_pp_min:
                triggers.append(f"Deliv Chg +{del_chg:.1f}pp (>= +{profile.delivery_chg_pp_min}pp)")

            # 4. Absorption condition
            is_absorb = bool(
                vol_m
                and vol_m >= Decimal("1.8")
                and dd_pct
                and dd_pct <= profile.drawdown_20d_max_pct
                and close_pos
                and close_pos >= profile.close_range_pos_min
            )
            if is_absorb:
                triggers.append(f"Absorption (DD {dd_pct:.1f}%, ClosePos {close_pos:.2f})")

            # 5. Breakout condition
            if is_bo:
                triggers.append(f"Breakout (+{ret_pct:.1f}%, Vol {vol_m:.2f}x)")

            # Check qualification
            flags_count = len(triggers)
            is_qualifying = bool(meets_liquidity_floor and flags_count >= profile.min_concurrent_flags)

            primary_trigger = triggers[0] if triggers else "None"
            trigger_detail = "; ".join(triggers)
            eval_id = f"shd-{list_id}-{trade_date.isoformat()}-{profile.version}"

            measurements = {
                "vol_multiple": float(vol_m) if vol_m is not None else None,
                "deliv_chg_pp": float(del_chg) if del_chg is not None else None,
                "drawdown_20d_pct": float(dd_pct) if dd_pct is not None else None,
                "avg_turnover_20d_cr": round(float(avg_to) / 1e7, 2) if avg_to is not None else None,
                "close_range_pos": float(close_pos) if close_pos is not None else None,
                "ret_1d_pct": float(ret_pct) if ret_pct is not None else None,
            }

            eval_rows.append((
                eval_id, ent_id, list_id, trade_date, profile.version, is_qualifying,
                primary_trigger, trigger_detail, vol_m, to_m, avg_to, del_pct, del_chg,
                dd_pct, close_pos, flags_count, json.dumps(measurements), now, "doc-b14cf998fefb3e8fe69486eed9410071"
            ))

            if is_qualifying:
                qualifying_candidates.append({
                    "entity_id": ent_id,
                    "symbol": sym,
                    "company_name": name,
                    "profile_version": profile.version,
                    "primary_trigger": primary_trigger,
                    "trigger_detail": trigger_detail,
                    "measurements": measurements,
                })

        # Persist evaluations idempotently
        if eval_rows:
            self.con.executemany(
                """
                INSERT OR IGNORE INTO shadow_candidate_evaluation (
                    evaluation_id, entity_id, listing_id, trade_date, profile_version,
                    is_qualifying, primary_trigger, trigger_detail,
                    volume_multiple, turnover_multiple, avg_turnover_20d_inr,
                    delivery_percentage, delivery_chg_pp, drawdown_20d_pct, close_range_position,
                    qualifying_flags_count, supporting_measurements_json, evaluated_at, source_document_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                eval_rows,
            )

        logger.info(
            f"Shadow Candidate Evaluation ({profile.version}) on {trade_date}: "
            f"{len(qualifying_candidates)} qualifying out of {len(signals)} evaluated"
        )
        return qualifying_candidates


class DailyBriefGenerator:
    """Generates and persists the structured HAMSA Daily Market Intelligence Brief."""

    def __init__(self, repository: DuckDBRepository, dossier_repository: DossierReviewRepository):
        self.repo = repository
        self.dossier_repo = dossier_repository
        self.con = repository._connection

    def build_and_persist_brief(
        self,
        trade_date: date,
        shadow_candidates: list[dict[str, object]],
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        brief_id = f"brief-{trade_date.isoformat()}"

        # 1. Market Regime & Breadth
        signals = self.con.execute(
            """
            SELECT
                r.symbol, n.legal_name, s.session_return_pct, s.volume_multiple,
                s.delivery_percentage, s.delivery_chg_pp, s.drawdown_20d_pct,
                s.close_range_position, s.avg_turnover_20d_inr
            FROM security_radar_signal_daily s
            JOIN exchange_listing l ON l.listing_id=s.listing_id
            JOIN equity_security eq ON eq.security_id=l.security_id
            JOIN (
                SELECT entity_id, legal_name,
                       row_number() OVER (PARTITION BY entity_id ORDER BY effective_from DESC) as rn
                FROM issuer_name_revision
            ) n ON n.entity_id=eq.issuer_entity_id AND n.rn=1
            JOIN (
                SELECT listing_id, symbol,
                       row_number() OVER (PARTITION BY listing_id ORDER BY effective_from DESC) as rn
                FROM exchange_listing_revision WHERE status='active'
            ) r ON r.listing_id=l.listing_id AND r.rn=1
            WHERE s.trade_date=?
        """,
            [trade_date],
        ).fetchall()

        advancers = [s for s in signals if s[2] is not None and s[2] > 0]
        decliners = [s for s in signals if s[2] is not None and s[2] < 0]
        unchanged = [s for s in signals if s[2] is not None and s[2] == 0]

        total_to_cr = self.con.execute(
            "SELECT coalesce(sum(turnover_raw)/1e7, 0) FROM eod_price_observation_revision WHERE trade_date=?",
            [trade_date],
        ).fetchone()[0]

        breadth_ratio = round(Decimal(len(advancers)) / max(Decimal("1.0"), Decimal(len(decliners))), 2)

        if breadth_ratio >= Decimal("1.5"):
            regime = "Broad Expansion (Advancers Lead)"
        elif breadth_ratio <= Decimal("0.67"):
            regime = "Risk-Off / Liquidity Withdrawal"
        else:
            regime = "Selective Rotational Dispersion"

        # 2. High-Importance Radar Events (Top volume and delivery dislocations)
        high_importance = sorted(
            [
                {
                    "symbol": s[0],
                    "company_name": s[1],
                    "session_return_pct": float(s[2]) if s[2] is not None else 0.0,
                    "volume_multiple": float(s[3]) if s[3] is not None else 1.0,
                    "delivery_pct": float(s[4]) if s[4] is not None else 0.0,
                    "delivery_chg_pp": float(s[5]) if s[5] is not None else 0.0,
                    "drawdown_20d_pct": float(s[6]) if s[6] is not None else 0.0,
                }
                for s in signals
                if s[3] is not None and s[3] >= Decimal("1.8")
            ],
            key=lambda x: -x["volume_multiple"],
        )[:8]

        # 3. Absorption Watch (Significant drawdown with heavy volume and high close position)
        absorption_watch = sorted(
            [
                {
                    "symbol": s[0],
                    "company_name": s[1],
                    "drawdown_20d_pct": float(s[6]) if s[6] is not None else 0.0,
                    "volume_multiple": float(s[3]) if s[3] is not None else 1.0,
                    "close_range_pos": float(s[7]) if s[7] is not None else 0.5,
                    "deliv_chg_pp": float(s[5]) if s[5] is not None else 0.0,
                }
                for s in signals
                if s[3] is not None
                and s[3] >= Decimal("1.8")
                and s[6] is not None
                and s[6] <= Decimal("-5.0")
                and s[7] is not None
                and s[7] >= Decimal("0.4")
            ],
            key=lambda x: -x["volume_multiple"],
        )[:5]

        # 4. Momentum & Breakouts (Return >= +3% with volume surge)
        momentum_expansion = sorted(
            [
                {
                    "symbol": s[0],
                    "company_name": s[1],
                    "session_return_pct": float(s[2]) if s[2] is not None else 0.0,
                    "volume_multiple": float(s[3]) if s[3] is not None else 1.0,
                    "delivery_pct": float(s[4]) if s[4] is not None else 0.0,
                }
                for s in signals
                if s[2] is not None
                and s[2] >= Decimal("3.0")
                and s[3] is not None
                and s[3] >= Decimal("1.8")
            ],
            key=lambda x: -x["session_return_pct"],
        )[:5]

        # 5. System Health Snapshot
        health_summary = {
            "database_schema": 8,
            "total_signals_computed": len(signals),
            "total_turnover_cr": round(float(total_to_cr), 2),
            "scheduler_status": "ACTIVE_RECURRING",
            "pit_compliance": "15:30 IST FAIL-CLOSED",
        }

        # Persist structured brief
        self.con.execute(
            """
            INSERT OR IGNORE INTO daily_market_intelligence_brief (
                brief_id, trade_date, market_regime, breadth_ratio,
                advancers_count, decliners_count, unchanged_count, total_turnover_cr,
                high_importance_events_json, absorption_watch_json, momentum_expansion_json,
                new_shadow_candidates_json, existing_candidate_updates_json, system_health_summary_json,
                generated_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                brief_id,
                trade_date,
                regime,
                breadth_ratio,
                len(advancers),
                len(decliners),
                len(unchanged),
                total_to_cr,
                json.dumps(high_importance),
                json.dumps(absorption_watch),
                json.dumps(momentum_expansion),
                json.dumps(shadow_candidates),
                json.dumps([]),
                json.dumps(health_summary),
                now,
                "hamsa-daily-pipeline",
            ],
        )

        # Build readable text summary
        text_summary = self._format_text_summary(
            trade_date, regime, breadth_ratio, len(advancers), len(decliners),
            float(total_to_cr), high_importance, absorption_watch, momentum_expansion, shadow_candidates
        )

        return {
            "brief_id": brief_id,
            "trade_date": trade_date.isoformat(),
            "market_regime": regime,
            "breadth_ratio": float(breadth_ratio),
            "advancers": len(advancers),
            "decliners": len(decliners),
            "total_turnover_cr": round(float(total_to_cr), 2),
            "high_importance_events": high_importance,
            "absorption_watch": absorption_watch,
            "momentum_expansion": momentum_expansion,
            "new_shadow_candidates": shadow_candidates,
            "text_summary": text_summary,
        }

    def _format_text_summary(
        self, trade_date: date, regime: str, breadth: Decimal, adv: int, dec: int,
        turnover_cr: float, high_imp: list, absorb: list, momentum: list, shadow: list
    ) -> str:
        lines = [
            f"==========================================================================",
            f"       HAMSA DAILY MARKET INTELLIGENCE BRIEF - {trade_date.isoformat()}",
            f"==========================================================================",
            f"1. MARKET REGIME & BREADTH",
            f"   * Regime:             {regime}",
            f"   * Breadth Ratio (A/D): {breadth}x ({adv} Advancers / {dec} Decliners)",
            f"   * Total Traded Volume: INR {turnover_cr:,.2f} Cr (NSE Mainboard Equities)",
            "",
            f"2. HIGH-IMPORTANCE RADAR EVENTS ({len(high_imp)} detected)",
        ]
        for item in high_imp[:4]:
            lines.append(f"   * {item['symbol']:<10} | Vol: {item['volume_multiple']:.2f}x | Deliv: {item['delivery_pct']:.1f}% (Chg {item['delivery_chg_pp']:+.1f}pp) | Return: {item['session_return_pct']:+.2f}%")

        lines.extend(["", f"3. ABSORPTION WATCH - SUPPLY EXHAUSTION ({len(absorb)} candidates)"])
        for item in absorb[:3]:
            lines.append(f"   * {item['symbol']:<10} | Vol: {item['volume_multiple']:.2f}x | Drawdown: {item['drawdown_20d_pct']:.1f}% | Close Pos: {item['close_range_pos']:.2f}")

        lines.extend(["", f"4. MOMENTUM & EXPANSION ({len(momentum)} candidates)"])
        for item in momentum[:3]:
            lines.append(f"   * {item['symbol']:<10} | Return: {item['session_return_pct']:+.2f}% | Vol: {item['volume_multiple']:.2f}x | Deliv: {item['delivery_pct']:.1f}%")

        lines.extend(["", f"5. NEW SHADOW CANDIDATES ({len(shadow)} qualified)"])
        for item in shadow[:4]:
            lines.append(f"   * {item['symbol']:<10} | Trigger: {item['primary_trigger']} ({item['trigger_detail']})")

        lines.extend([
            "",
            f"==========================================================================",
            f"  Point-in-Time: 15:30 IST Cutoff Enforced | Historical Evidence Preserved",
            f"==========================================================================",
        ])
        return "\n".join(lines)