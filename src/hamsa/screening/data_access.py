"""Read-only, fail-closed data selection helpers used by the local UI."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Mapping

from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.screening.engines import CompanyInput, MetricPoint


def calendar_versions(repository, exchange: str) -> list[str]:
    return [row[0] for row in repository._connection.execute(
        "SELECT DISTINCT calendar_version FROM exchange_trading_session WHERE exchange=? ORDER BY calendar_version",
        [exchange],
    ).fetchall()]


def calendar_sessions(repository, exchange: str, version: str) -> list[date]:
    return [row[0] for row in repository._connection.execute(
        "SELECT session_date FROM exchange_trading_session WHERE exchange=? AND calendar_version=? AND is_trading_session=TRUE ORDER BY session_date",
        [exchange, version],
    ).fetchall()]


def source_freshness(repository) -> dict[str, date | None]:
    return {exchange: row[0] for exchange in ("NSE", "BSE") for row in [repository._connection.execute(
        "SELECT max(trade_date) FROM eod_price_observation_revision WHERE exchange=?", [exchange]
    ).fetchone()]}


def universe_for_session(repository, *, exchange: str, session_date: date,
                         availability_mode: str, calendar_version: str) -> list[dict[str, object]]:
    """Return listing-level current/historical dispositions; never collapses venues."""
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    rows = repository._connection.execute(
        """SELECT l.listing_id,l.security_id,s.issuer_entity_id,l.exchange,l.exchange_instrument_id
           FROM exchange_listing l JOIN equity_security s USING(security_id)
           WHERE l.exchange=? ORDER BY l.exchange_instrument_id""", [exchange]
    ).fetchall()
    result = []
    for row in rows:
        listing_id, security_id, issuer_id, venue, instrument = row
        revisions = repository._connection.execute(
            """SELECT listing_revision_id,symbol,series,status,effective_from,effective_to,source_document_id
               FROM exchange_listing_revision
               WHERE listing_id=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?)""",
            [listing_id, session_date, session_date],
        ).fetchall()
        reviewed_revisions = []
        for revision_id, symbol, series, status, start, end, source_id in revisions:
            if not repository._source_available(source_id, exchange=exchange, screen_date=session_date,
                    cutoff=cutoff, availability_mode=availability_mode, calendar_version=calendar_version):
                continue
            known_mode = availability_mode == "hamsa_known_as_of"
            reviews = repository._connection.execute(
                """SELECT review_status,evidence_source_document_id FROM exchange_listing_revision_review
                   WHERE listing_revision_id=? AND (? OR recorded_at<=?) AND reviewed_at IS NOT NULL AND (? OR reviewed_at<=?)
                     AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision_review n
                       WHERE n.supersedes_review_id=exchange_listing_revision_review.listing_revision_review_id
                         AND (? OR n.recorded_at<=?))""",
                [revision_id, not known_mode, cutoff, not known_mode, cutoff, not known_mode, cutoff],
            ).fetchall()
            approved = [item for item in reviews if item[0] == "approved" and repository._source_available(
                item[1], exchange=exchange, screen_date=session_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version)]
            if len(approved) == 1:
                reviewed_revisions.append((symbol, series, status, start, end))
        symbol, series, status, start, end = (
            reviewed_revisions[0] if len(reviewed_revisions) == 1 else (None, None, None, None, None)
        )
        disposition = repository.derive_universe_disposition(
            listing_id=listing_id, observation_date=session_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version,
        )
        result.append({"listing_id": listing_id, "security_id": security_id, "issuer_entity_id": issuer_id,
            "exchange": venue, "exchange_instrument_id": instrument, "symbol": symbol, "series": series,
            "effective_listing_status": status, "listing_valid_from": start, "listing_valid_to": end,
            "disposition": disposition, "session_date": session_date,
            "availability_mode": availability_mode, "calendar_version": calendar_version})
    return result


def company_input_as_of(repository, *, issuer_entity_id: str, exchange: str, session_date: date,
                        availability_mode: str, calendar_version: str,
                        metric_codes: Mapping[str, str] | None = None,
                        business_class: str = "unclassified",
                        reporting_scope: str = "consolidated",
                        review_repository=None) -> CompanyInput:
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    if review_repository is not None and business_class == "unclassified":
        business_class = review_repository.business_class_as_of(
            entity_id=issuer_entity_id, session_date=session_date, cutoff=cutoff,
            exchange=exchange, availability_mode=availability_mode, calendar_version=calendar_version,
        )
    rows = repository.financial_observations_as_of(exchange=exchange, session_date=session_date,
        cutoff=cutoff, availability_mode=availability_mode, calendar_version=calendar_version,
        subject_entity_id=issuer_entity_id)
    metrics: list[MetricPoint] = []
    metric_codes = metric_codes or {"sales": "revenue", "pat": "pat", "roce": "roce",
        "operating_margin": "operating_margin", "cfo": "cfo", "fcf": "fcf",
        "capex": "capex", "cwip": "cwip", "gross_block": "gross_block"}
    normalized_names = {db_code: ("revenue" if alias == "sales" else alias)
                        for alias, db_code in metric_codes.items()}
    effective_scope = reporting_scope
    if reporting_scope == "consolidated_preferred":
        has_cons = any(
            row["subject_entity_id"] == issuer_entity_id and row["reporting_scope"] == "consolidated"
            for row in rows
        )
        effective_scope = "consolidated" if has_cons else "standalone"
    for row in rows:
        if row["subject_entity_id"] != issuer_entity_id or row["reporting_scope"] != effective_scope:
            continue
        if row["period_start"] is None:
            # A duration-ambiguous period is not silently treated as annual or quarterly.
            continue
        metrics.append(MetricPoint(normalized_names.get(str(row["metric"]), str(row["metric"])), row["value"], row["period_start"], row["period_end"],
                                   str(row["observation_id"]), str(row["source_document_id"]),
                                   str(row["quality_status"]),str(row["reporting_scope"]),str(row["unit"])))
    observations = tuple(item.observation_id for item in metrics)
    documents = tuple(dict.fromkeys(item.source_document_id for item in metrics))
    evidence_map: dict[str, bool | None] = {}
    evidence_sources: dict[str, tuple[str, ...]] = {}
    if review_repository is not None:
        evidence_map, evidence_sources = review_repository.engine_evidence_as_of(
            entity_id=issuer_entity_id, session_date=session_date, cutoff=cutoff,
            exchange=exchange, availability_mode=availability_mode, calendar_version=calendar_version,
        )
    evidence_docs = tuple(dict.fromkeys(doc_id for docs in evidence_sources.values() for doc_id in docs))
    return CompanyInput(
        issuer_entity_id,
        business_class,
        tuple(metrics),
        observations,
        documents,
        evidence=evidence_map,
        evidence_document_ids=evidence_docs,
        evidence_source_document_ids=evidence_sources,
        reporting_scope=effective_scope,
    )


def liquidity_input_as_of(
    repository,
    *,
    issuer_entity_id: str,
    exchange: str,
    session_date: date,
    availability_mode: str,
    calendar_version: str,
    review_repository=None,
    baseline_sessions: int = 20,
    eligible_listing_id: str | None = None,
) -> dict[str, object]:
    """Compute point-in-time venue-specific liquidity inputs for Engine 5."""
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    if eligible_listing_id is not None:
        eligible_listings = [eligible_listing_id]
    else:
        candidate_listings = repository._connection.execute(
            """SELECT l.listing_id FROM exchange_listing l
               JOIN equity_security s USING(security_id)
               WHERE l.exchange=? AND s.issuer_entity_id=?""",
            [exchange, issuer_entity_id],
        ).fetchall()
        eligible_listings = [
            row[0] for row in candidate_listings
            if repository.derive_universe_disposition(
                listing_id=row[0], observation_date=session_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
            ) == "eligible_mainboard_ordinary_equity"
        ]
    forced_selling = absorption_capacity = None
    forced_docs: tuple[str, ...] = ()
    absorption_docs: tuple[str, ...] = ()
    if review_repository is not None:
        ev_map, ev_sources = review_repository.engine_evidence_as_of(
            entity_id=issuer_entity_id, session_date=session_date, cutoff=cutoff,
            exchange=exchange, availability_mode=availability_mode, calendar_version=calendar_version,
        )
        forced_selling = ev_map.get("forced_selling")
        absorption_capacity = ev_map.get("absorption_capacity")
        forced_docs = tuple(ev_sources.get("forced_selling", ()))
        absorption_docs = tuple(ev_sources.get("absorption_capacity", ()))

    result: dict[str, object] = {
        "volume_multiple": None,
        "turnover_multiple": None,
        "avg_turnover_20d_inr": None,
        "delivery_percentage": None,
        "delivery_percentage_point_change": None,
        "session_return_pct": None,
        "drawdown_from_window_high_pct": None,
        "close_range_position": None,
        "unadjusted_corporate_action_in_window": False,
        "forced_selling_evidence": forced_selling,
        "absorption_capacity_evidence": absorption_capacity,
        "forced_selling_source_document_ids": forced_docs,
        "absorption_capacity_source_document_ids": absorption_docs,
        "volume_source_observation_ids": (),
        "volume_source_document_ids": (),
        "delivery_source_observation_ids": (),
        "delivery_source_document_ids": (),
    }
    if len(eligible_listings) != 1:
        return result
    listing_id = str(eligible_listings[0])
    all_sessions = [day for day in calendar_sessions(repository, exchange, calendar_version) if day <= session_date]
    if not all_sessions or all_sessions[-1] != session_date:
        return result
    window_sessions = all_sessions[-(baseline_sessions + 1):]

    session_bars: list[tuple[date, dict[str, object]]] = []
    ambiguous_prior = False
    for day in window_sessions:
        day_rows = [
            row for row in repository.eod_observations_as_of(
                exchange=exchange, trade_date=day, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
                listing_id=listing_id,
            )
            if row["listing_id"] == listing_id and row["volume"] is not None
        ]
        if len(day_rows) > 1:
            if day == session_date:
                return result
            ambiguous_prior = True
            break
        if len(day_rows) == 1:
            session_bars.append((day, day_rows[0]))

    if session_bars and session_bars[-1][0] == session_date and not ambiguous_prior:
        curr_bar = session_bars[-1][1]
        # Detect unadjusted corporate-action overnight price step-discontinuities
        # (e.g. stock splits / bonus issues where open / prior_close < 0.65 or > 1.50)
        # so pre-split share counts and prices are never mixed with post-split ones.
        clean_start_idx = 0
        for idx in range(1, len(session_bars)):
            prev_close = session_bars[idx - 1][1].get("close")
            curr_open = session_bars[idx][1].get("open") or session_bars[idx][1].get("close")
            if prev_close is not None and curr_open is not None and Decimal(str(prev_close)) > 0:
                ratio = Decimal(str(curr_open)) / Decimal(str(prev_close))
                if ratio < Decimal("0.65") or ratio > Decimal("1.50"):
                    clean_start_idx = idx
                    result["unadjusted_corporate_action_in_window"] = True
        comparable_bars = session_bars[clean_start_idx:]
        prior_bars = [bar for _, bar in comparable_bars[:-1]]

        curr_close = Decimal(str(curr_bar["close"])) if curr_bar.get("close") is not None else None
        curr_high = Decimal(str(curr_bar["high"])) if curr_bar.get("high") is not None else None
        curr_low = Decimal(str(curr_bar["low"])) if curr_bar.get("low") is not None else None
        if curr_close is not None and curr_high is not None and curr_low is not None and curr_high > curr_low:
            result["close_range_position"] = (curr_close - curr_low) / (curr_high - curr_low)
        if curr_close is not None and prior_bars and prior_bars[-1].get("close") is not None:
            prev_c = Decimal(str(prior_bars[-1]["close"]))
            if prev_c > 0:
                result["session_return_pct"] = (curr_close - prev_c) / prev_c * Decimal("100")
        highs = [
            Decimal(str(b["high"])) if b.get("high") is not None else Decimal(str(b["close"]))
            for _, b in comparable_bars
            if b.get("high") is not None or b.get("close") is not None
        ]
        if curr_close is not None and highs:
            window_high = max(highs)
            if window_high > 0:
                result["drawdown_from_window_high_pct"] = (curr_close - window_high) / window_high * Decimal("100")

        if Decimal(str(curr_bar["volume"])) >= 0 and prior_bars:
            prior_volumes = [Decimal(str(b["volume"])) for b in prior_bars if Decimal(str(b["volume"])) > 0]
            prior_turnovers = [
                Decimal(str(b["turnover"])) for b in prior_bars
                if b.get("turnover") is not None and Decimal(str(b["turnover"])) > 0
            ]
            vol_obs_ids = [str(curr_bar["observation_id"]), *(str(b["observation_id"]) for b in prior_bars if Decimal(str(b["volume"])) > 0)]
            vol_doc_ids = [str(curr_bar["source_document_id"]), *(str(b["source_document_id"]) for b in prior_bars if Decimal(str(b["volume"])) > 0)]
            if prior_volumes:
                avg_prior_vol = sum(prior_volumes, Decimal("0")) / Decimal(len(prior_volumes))
                if avg_prior_vol > 0:
                    result["volume_multiple"] = Decimal(str(curr_bar["volume"])) / avg_prior_vol
                    result["volume_source_observation_ids"] = tuple(dict.fromkeys(vol_obs_ids))
                    result["volume_source_document_ids"] = tuple(dict.fromkeys(vol_doc_ids))
            if prior_turnovers:
                avg_prior_turn = sum(prior_turnovers, Decimal("0")) / Decimal(len(prior_turnovers))
                result["avg_turnover_20d_inr"] = avg_prior_turn
                if avg_prior_turn > 0 and curr_bar.get("turnover") is not None:
                    result["turnover_multiple"] = Decimal(str(curr_bar["turnover"])) / avg_prior_turn

    current_delivery = [
        row for row in repository.delivery_observations_as_of(
            exchange=exchange, trade_date=session_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version,
            listing_id=listing_id,
        )
        if row["listing_id"] == listing_id
        and row["quality_status"] == "observed"
        and row["delivery_percentage"] is not None
    ]
    if len(current_delivery) == 1:
        result["delivery_percentage"] = Decimal(str(current_delivery[0]["delivery_percentage"]))
    if len(current_delivery) == 1 and len(window_sessions) >= 2:
        for prior_day in reversed(window_sessions[:-1]):
            prior_delivery = [
                row for row in repository.delivery_observations_as_of(
                    exchange=exchange, trade_date=prior_day, cutoff=cutoff,
                    availability_mode=availability_mode, calendar_version=calendar_version,
                    listing_id=listing_id,
                )
                if row["listing_id"] == listing_id
                and row["quality_status"] == "observed"
                and row["delivery_percentage"] is not None
            ]
            if len(prior_delivery) > 1:
                break
            if len(prior_delivery) == 1:
                curr_pct = Decimal(str(current_delivery[0]["delivery_percentage"]))
                prev_pct = Decimal(str(prior_delivery[0]["delivery_percentage"]))
                result["delivery_percentage_point_change"] = curr_pct - prev_pct
                result["delivery_source_observation_ids"] = (
                    str(current_delivery[0]["observation_id"]),
                    str(prior_delivery[0]["observation_id"]),
                )
                result["delivery_source_document_ids"] = tuple(dict.fromkeys((
                    str(current_delivery[0]["source_document_id"]),
                    str(prior_delivery[0]["source_document_id"]),
                )))
                break
    return result


def known_source_documents(repository) -> list[tuple[str, str, str, str]]:
    return repository._connection.execute(
        """SELECT source_document_id,source_identifier,checksum_sha256,provider || '/' || dataset
           FROM source_document_revision ORDER BY ingestion_timestamp DESC,source_document_id"""
    ).fetchall()


CORE_ENGINE_METRICS: tuple[str, ...] = (
    "revenue", "pat", "roce", "operating_margin", "cfo", "fcf", "capex", "cwip", "gross_block",
)


def financial_coverage_matrix(
    repository,
    *,
    review_repository=None,
    exchange: str = "NSE",
    session_date: date | None = None,
    availability_mode: str = "public_as_of",
    calendar_version: str | None = None,
) -> list[dict[str, object]]:
    """Return per-company financial coverage, temporal precision, and engine-silence diagnosis."""
    con = repository._connection
    issuers = con.execute(
        """SELECT i.entity_id,
                  coalesce((SELECT legal_name FROM issuer_name_revision n WHERE n.entity_id=i.entity_id
                            ORDER BY effective_from DESC LIMIT 1), i.entity_id) AS legal_name
           FROM issuer_entity i ORDER BY legal_name, i.entity_id"""
    ).fetchall()
    if not issuers:
        return []

    if session_date is not None and calendar_version is not None:
        cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
        fin_rows = repository.financial_observations_as_of(
            exchange=exchange, session_date=session_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version,
        )
    else:
        cutoff = None
        raw = con.execute(
            """SELECT f.observation_id,f.subject_entity_id,f.metric,f.canonical_value,f.canonical_unit,
                      f.period_start,f.period_end,f.reporting_scope,f.quality_status,f.source_document_id,
                      f.publication_precision
               FROM financial_observation_revision f
               WHERE NOT EXISTS (
                 SELECT 1 FROM financial_observation_revision c
                 WHERE c.supersedes_observation_id=f.observation_id
               )"""
        ).fetchall()
        fin_rows = [
            {
                "observation_id": r[0], "subject_entity_id": r[1], "metric": r[2],
                "value": r[3], "unit": r[4], "period_start": r[5], "period_end": r[6],
                "reporting_scope": r[7], "quality_status": r[8], "source_document_id": r[9],
                "publication_precision": r[10],
            }
            for r in raw
        ]

    precision_by_obs = {
        str(r[0]): str(r[1])
        for r in con.execute("SELECT observation_id, publication_precision FROM financial_observation_revision").fetchall()
    }

    by_issuer: dict[str, list[dict[str, object]]] = {}
    for row in fin_rows:
        by_issuer.setdefault(str(row["subject_entity_id"]), []).append(row)

    output: list[dict[str, object]] = []
    for entity_id, legal_name in issuers:
        listings = con.execute(
            """SELECT l.exchange, coalesce((SELECT symbol FROM exchange_listing_revision r
                                            WHERE r.listing_id=l.listing_id ORDER BY effective_from DESC LIMIT 1), l.exchange_instrument_id),
                      coalesce((SELECT identifier_value FROM security_identifier_revision s
                                WHERE s.security_id=l.security_id AND s.identifier_type='ISIN'
                                ORDER BY effective_from DESC LIMIT 1), '')
               FROM equity_security e JOIN exchange_listing l USING(security_id)
               WHERE e.issuer_entity_id=? ORDER BY l.exchange""",
            [entity_id],
        ).fetchall()
        exchanges = ", ".join(sorted({r[0] for r in listings})) if listings else "—"
        symbol = next((r[1] for r in listings if r[0] == "NSE"), listings[0][1] if listings else entity_id)
        isin = next((r[2] for r in listings if r[2]), "—")

        b_class = "unclassified"
        if review_repository is not None:
            if cutoff is not None and session_date is not None and calendar_version is not None:
                b_class = review_repository.business_class_as_of(
                    entity_id=entity_id, session_date=session_date, cutoff=cutoff,
                    exchange=exchange, availability_mode=availability_mode, calendar_version=calendar_version,
                )
            else:
                b_row = review_repository.connection.execute(
                    """SELECT business_class FROM issuer_business_classification_review_revision r
                       WHERE r.entity_id=? AND r.review_status='approved'
                         AND NOT EXISTS (
                           SELECT 1 FROM issuer_business_classification_review_revision n
                           WHERE n.supersedes_review_revision_id=r.review_revision_id
                         )
                       ORDER BY r.recorded_at DESC LIMIT 1""",
                    (entity_id,),
                ).fetchone()
                if b_row:
                    b_class = str(b_row[0])

        rows = [
            r for r in by_issuer.get(entity_id, [])
            if r.get("quality_status") == "observed" and r.get("value") is not None and r.get("period_start") is not None
        ]
        scopes = sorted({str(r["reporting_scope"]) for r in rows})
        annual_years = sorted({
            r["period_end"].year for r in rows
            if (r["period_end"] - r["period_start"]).days >= 300
        })
        quarterly_ends = sorted({
            r["period_end"].isoformat() for r in rows
            if 60 <= (r["period_end"] - r["period_start"]).days <= 120
        })
        metrics_present = sorted({str(r["metric"]) for r in rows})
        missing_core = [m for m in CORE_ENGINE_METRICS if m not in metrics_present]

        ts_count = sum(
            1 for r in rows
            if (r.get("publication_precision") or precision_by_obs.get(str(r["observation_id"]))) == "timestamp"
        )
        temporal_confidence = (
            f"{round(ts_count / len(rows) * 100)}% timestamp ({ts_count}/{len(rows)})"
            if rows else "No observations"
        )

        # Diagnose per-engine readiness
        annual_metrics = {
            str(r2["metric"]): sorted({r["period_end"].year for r in rows if r["metric"] == r2["metric"] and (r["period_end"] - r["period_start"]).days >= 300})
            for r2 in rows if (r2["period_end"] - r2["period_start"]).days >= 300
        }
        q_metrics = {
            str(r2["metric"]): sorted({r["period_end"] for r in rows if r["metric"] == r2["metric"] and 60 <= (r["period_end"] - r["period_start"]).days <= 120})
            for r2 in rows if 60 <= (r2["period_end"] - r2["period_start"]).days <= 120
        }
        comp_ready = (
            b_class == "industrial"
            and len(annual_metrics.get("revenue", [])) >= 4
            and len(annual_metrics.get("pat", [])) >= 4
            and len(annual_metrics.get("roce", [])) >= 1
            and len(q_metrics.get("revenue", [])) >= 8
        )
        inflect_ready = (
            b_class == "industrial"
            and len(q_metrics.get("revenue", [])) >= 5
            and len(q_metrics.get("pat", [])) >= 5
            and len(q_metrics.get("operating_margin", [])) >= 5
        )
        capex_ready = (
            b_class == "industrial"
            and any(len(annual_metrics.get(m, [])) >= 2 for m in ("capex", "cwip", "gross_block"))
        )
        cash_ready = (
            b_class == "industrial"
            and len(annual_metrics.get("cfo", [])) >= 3
            and len(annual_metrics.get("pat", [])) >= 3
            and len(annual_metrics.get("fcf", [])) >= 3
        )

        if b_class == "financial":
            silence_reason = "financial_sector_profile_required"
        elif b_class != "industrial":
            silence_reason = "unclassified_business_class"
        elif not rows:
            silence_reason = "no_financial_data"
        elif len(annual_years) < 3:
            silence_reason = "insufficient_annual_history (<3 years)"
        elif len(quarterly_ends) < 5:
            silence_reason = "insufficient_quarterly_history (<5 quarters)"
        else:
            silence_reason = "ready_for_all_financial_engines"

        output.append({
            "issuer_entity_id": entity_id,
            "company_name": legal_name,
            "symbol": symbol,
            "isin": isin,
            "exchanges": exchanges,
            "business_class": b_class,
            "scopes": ", ".join(scopes) if scopes else "—",
            "annual_years": len(annual_years),
            "annual_span": f"{annual_years[0]}–{annual_years[-1]}" if annual_years else "—",
            "quarterly_periods": len(quarterly_ends),
            "quarterly_span": f"{quarterly_ends[0]}..{quarterly_ends[-1]}" if quarterly_ends else "—",
            "metrics_count": len(metrics_present),
            "missing_core_metrics": ", ".join(missing_core) if missing_core else "None (Complete)",
            "temporal_confidence": temporal_confidence,
            "compounders_ready": comp_ready,
            "earnings_inflection_ready": inflect_ready,
            "capex_conversion_ready": capex_ready,
            "cash_quality_ready": cash_ready,
            "engine_readiness_status": silence_reason,
        })
    return output


def market_radar_snapshot(
    repository,
    *,
    exchange: str,
    session_date: date,
    availability_mode: str,
    calendar_version: str,
    review_repository=None,
    thresholds=None,
) -> dict[str, object]:
    """Compute session market breadth, dislocations, cross-venue blocks, and active discoveries."""
    from hamsa.screening.engines import EngineThresholds, EvaluationState, evaluate_company

    thresholds = thresholds or EngineThresholds()
    universe = universe_for_session(
        repository, exchange=exchange, session_date=session_date,
        availability_mode=availability_mode, calendar_version=calendar_version,
    )
    eligible = [r for r in universe if r["disposition"] == "eligible_mainboard_ordinary_equity"]
    con = repository._connection
    names = {
        r[0]: r[1]
        for r in con.execute(
            """SELECT i.entity_id, coalesce((SELECT legal_name FROM issuer_name_revision n
                                            WHERE n.entity_id=i.entity_id ORDER BY effective_from DESC LIMIT 1), i.entity_id)
               FROM issuer_entity i"""
        ).fetchall()
    }
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    session_eod = {
        str(r["listing_id"]): r
        for r in repository.eod_observations_as_of(
            exchange=exchange, trade_date=session_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version,
        )
    }

    # Check if secondary venue has EOD observations on session_date for cross-venue comparison
    other_exchange = "BSE" if exchange == "NSE" else "NSE"
    other_cal_versions = calendar_versions(repository, other_exchange)
    other_eod_by_sec: dict[str, dict[str, object]] = {}
    if other_cal_versions:
        try:
            for row in repository.eod_observations_as_of(
                exchange=other_exchange, trade_date=session_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=other_cal_versions[-1],
            ):
                other_eod_by_sec[str(row["security_id"])] = row
        except Exception:
            pass

    security_rows: list[dict[str, object]] = []
    discoveries: list[dict[str, object]] = []
    advancers = decliners = unchanged = 0
    total_turnover = Decimal("0")

    for u_row in eligible:
        issuer_id = str(u_row["issuer_entity_id"])
        listing_id = str(u_row["listing_id"])
        security_id = str(u_row["security_id"])
        symbol = str(u_row["symbol"] or u_row["exchange_instrument_id"])
        company_name = names.get(issuer_id, issuer_id)
        eod = session_eod.get(listing_id)
        liq = liquidity_input_as_of(
            repository, issuer_entity_id=issuer_id, exchange=exchange,
            session_date=session_date, availability_mode=availability_mode,
            calendar_version=calendar_version, review_repository=review_repository,
            eligible_listing_id=listing_id,
        )
        ret_1d = liq.get("session_return_pct")
        if isinstance(ret_1d, Decimal):
            if ret_1d > Decimal("0.05"):
                advancers += 1
            elif ret_1d < Decimal("-0.05"):
                decliners += 1
            else:
                unchanged += 1

        turn_cr = Decimal("0")
        close_px = None
        if eod:
            close_px = eod.get("close")
            if eod.get("turnover") is not None:
                total_turnover += Decimal(str(eod["turnover"]))
                turn_cr = Decimal(str(eod["turnover"])) / Decimal("1e7")

        other_eod = other_eod_by_sec.get(security_id)
        other_turn_cr = (
            Decimal(str(other_eod["turnover"])) / Decimal("1e7")
            if other_eod and other_eod.get("turnover") is not None else Decimal("0")
        )

        comp_input = company_input_as_of(
            repository, issuer_entity_id=issuer_id, exchange=exchange,
            session_date=session_date, availability_mode=availability_mode,
            calendar_version=calendar_version, reporting_scope="consolidated_preferred",
            review_repository=review_repository,
        )
        evals = evaluate_company(comp_input, thresholds, **liq)
        triggered_engines = [e.engine for e in evals if e.state == EvaluationState.TRIGGERED]
        unproven_engines = [e.engine for e in evals if e.state == EvaluationState.UNPROVEN]

        row_summary = {
            "issuer_entity_id": issuer_id,
            "symbol": symbol,
            "company_name": company_name,
            "close": float(close_px) if close_px is not None else None,
            "ret_1d_pct": round(float(ret_1d), 2) if isinstance(ret_1d, Decimal) else None,
            "drawdown_20d_pct": round(float(liq["drawdown_from_window_high_pct"]), 2) if isinstance(liq.get("drawdown_from_window_high_pct"), Decimal) else None,
            "volume_multiple": round(float(liq["volume_multiple"]), 2) if isinstance(liq.get("volume_multiple"), Decimal) else None,
            "turnover_multiple": round(float(liq["turnover_multiple"]), 2) if isinstance(liq.get("turnover_multiple"), Decimal) else None,
            "delivery_pct": round(float(liq["delivery_percentage"]), 2) if isinstance(liq.get("delivery_percentage"), Decimal) else None,
            "delivery_chg_pp": round(float(liq["delivery_percentage_point_change"]), 2) if isinstance(liq.get("delivery_percentage_point_change"), Decimal) else None,
            "close_range_pos": round(float(liq["close_range_position"]), 2) if isinstance(liq.get("close_range_position"), Decimal) else None,
            "turnover_cr": round(float(turn_cr), 2),
            "other_venue_turnover_cr": round(float(other_turn_cr), 2),
            "triggered_engines": ", ".join(triggered_engines) if triggered_engines else "—",
            "triggered_count": len(triggered_engines),
            "unproven_count": len(unproven_engines),
        }
        security_rows.append(row_summary)
        if triggered_engines:
            discoveries.append({
                **row_summary,
                "engine_details": {e.engine: {"state": e.state.value, "inputs": e.inputs, "explanation": e.explanation} for e in evals},
            })

    dislocations = sorted(
        [
            r for r in security_rows
            if (r["drawdown_20d_pct"] is not None and r["drawdown_20d_pct"] <= -10.0)
            and (
                (r["volume_multiple"] is not None and r["volume_multiple"] >= 1.8)
                or (r["delivery_chg_pp"] is not None and r["delivery_chg_pp"] >= 10.0)
                or r["other_venue_turnover_cr"] >= 20.0
            )
        ],
        key=lambda r: (-(r["volume_multiple"] or 0.0) * (r["delivery_pct"] or 30.0)),
    )

    volume_anomalies = sorted(
        [r for r in security_rows if r["volume_multiple"] is not None and r["volume_multiple"] >= 2.0],
        key=lambda r: -(r["volume_multiple"] or 0.0),
    )
    delivery_anomalies = sorted(
        [r for r in security_rows if r["delivery_chg_pp"] is not None and abs(r["delivery_chg_pp"]) >= 10.0],
        key=lambda r: -abs(r["delivery_chg_pp"] or 0.0),
    )

    if advancers + decliners > 0:
        breadth_ratio = advancers / max(1, decliners)
        if breadth_ratio >= 1.5:
            regime = "Broad Expansion (Advancers Lead)"
        elif breadth_ratio <= 0.67:
            regime = "Risk-Off / Sell-Side Pressure"
        else:
            regime = "Selective / Rotational Dispersion"
    else:
        regime = "No Active Session Prints"

    return {
        "exchange": exchange,
        "session_date": session_date,
        "eligible_count": len(eligible),
        "total_listings": len(universe),
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "total_turnover_cr": round(float(total_turnover / Decimal("1e7")), 2),
        "regime": regime,
        "security_rows": security_rows,
        "dislocations": dislocations,
        "volume_anomalies": volume_anomalies,
        "delivery_anomalies": delivery_anomalies,
        "discoveries": sorted(discoveries, key=lambda d: (-d["triggered_count"], d["symbol"])),
    }


def discovery_feed_as_of(
    repository,
    *,
    exchange: str,
    session_date: date,
    availability_mode: str,
    calendar_version: str,
    review_repository=None,
    thresholds=None,
) -> list[dict[str, object]]:
    """Build a chronological, source-cited intelligence feed as of the session cutoff."""
    from hamsa.screening.engines import EngineThresholds, EvaluationState, evaluate_company

    thresholds = thresholds or EngineThresholds()
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    universe = universe_for_session(
        repository, exchange=exchange, session_date=session_date,
        availability_mode=availability_mode, calendar_version=calendar_version,
    )
    eligible = [r for r in universe if r["disposition"] == "eligible_mainboard_ordinary_equity"]
    con = repository._connection
    names = {
        r[0]: r[1]
        for r in con.execute(
            """SELECT i.entity_id, coalesce((SELECT legal_name FROM issuer_name_revision n
                                            WHERE n.entity_id=i.entity_id ORDER BY effective_from DESC LIMIT 1), i.entity_id)
               FROM issuer_entity i"""
        ).fetchall()
    }

    feed: list[dict[str, object]] = []
    for u_row in eligible:
        issuer_id = str(u_row["issuer_entity_id"])
        symbol = str(u_row["symbol"] or u_row["exchange_instrument_id"])
        company_name = names.get(issuer_id, issuer_id)
        comp = company_input_as_of(
            repository, issuer_entity_id=issuer_id, exchange=exchange,
            session_date=session_date, availability_mode=availability_mode,
            calendar_version=calendar_version, reporting_scope="consolidated_preferred",
            review_repository=review_repository,
        )
        liq = liquidity_input_as_of(
            repository, issuer_entity_id=issuer_id, exchange=exchange,
            session_date=session_date, availability_mode=availability_mode,
            calendar_version=calendar_version, review_repository=review_repository,
            eligible_listing_id=str(u_row["listing_id"]),
        )
        for res in evaluate_company(comp, thresholds, **liq):
            if res.state == EvaluationState.TRIGGERED:
                feed.append({
                    "event_date": session_date.isoformat(),
                    "category": f"Engine Trigger · {res.engine.replace('_', ' ').title()}",
                    "severity": "positive",
                    "issuer_entity_id": issuer_id,
                    "symbol": symbol,
                    "company_name": company_name,
                    "what_happened": f"{symbol} triggered {res.engine.replace('_', ' ').title()} at {session_date.isoformat()} cutoff",
                    "why_it_matters": res.calculation_expression,
                    "what_changed": json.dumps({k: v for k, v in res.inputs.items() if k != "input_quality_states" and v is not None}),
                    "source": ", ".join(res.source_document_ids[:3]) or " analytical registry",
                })

        vol_m = liq.get("volume_multiple")
        deliv_pct = liq.get("delivery_percentage")
        deliv_chg = liq.get("delivery_percentage_point_change")
        dd_pct = liq.get("drawdown_from_window_high_pct")
        if isinstance(vol_m, Decimal) and vol_m >= Decimal("2.5"):
            is_absorption = isinstance(deliv_pct, Decimal) and deliv_pct >= Decimal("50")
            feed.append({
                "event_date": session_date.isoformat(),
                "category": "Liquidity & Absorption Anomaly" if is_absorption else "Volume Expansion",
                "severity": "attention" if is_absorption else "neutral",
                "issuer_entity_id": issuer_id,
                "symbol": symbol,
                "company_name": company_name,
                "what_happened": f"{symbol} traded {vol_m:.2f}x 20-session volume ({deliv_pct:.1f}% delivery)" if isinstance(deliv_pct, Decimal) else f"{symbol} traded {vol_m:.2f}x 20-session volume",
                "why_it_matters": "High delivery during drawdown signals potential institutional absorption" if is_absorption else "Elevated activity relative to 20-session baseline",
                "what_changed": f"20d drawdown: {dd_pct:.1f}%, 1d delivery change: {deliv_chg:+.1f}pp" if isinstance(dd_pct, Decimal) and isinstance(deliv_chg, Decimal) else f"Volume multiple: {vol_m:.2f}x",
                "source": ", ".join(liq.get("volume_source_document_ids", ())[:2]),
            })
        elif isinstance(deliv_chg, Decimal) and deliv_chg >= Decimal("15.0") and isinstance(deliv_pct, Decimal) and deliv_pct >= Decimal("55.0"):
            feed.append({
                "event_date": session_date.isoformat(),
                "category": "Delivery Accumulation Spike",
                "severity": "attention",
                "issuer_entity_id": issuer_id,
                "symbol": symbol,
                "company_name": company_name,
                "what_happened": f"{symbol} delivery jumped +{deliv_chg:.1f}pp to {deliv_pct:.1f}%",
                "why_it_matters": "Sharp rise in demat delivery share vs prior trading session",
                "what_changed": f"Delivery %: {deliv_pct:.1f}% ({deliv_chg:+.1f}pp), 20d drawdown: {dd_pct:.1f}%" if isinstance(dd_pct, Decimal) else f"Delivery %: {deliv_pct:.1f}%",
                "source": ", ".join(liq.get("delivery_source_document_ids", ())[:2]),
            })

    for action in repository.corporate_action_events_as_of(
        exchange=exchange, session_date=session_date, cutoff=cutoff,
        availability_mode=availability_mode, calendar_version=calendar_version,
    ):
        sec_row = con.execute(
            "SELECT issuer_entity_id FROM equity_security WHERE security_id=?",
            [action["affected_security_id"]],
        ).fetchone()
        iss_id = str(sec_row[0]) if sec_row else str(action["affected_security_id"])
        feed.append({
            "event_date": str(action["publication_date"]),
            "category": f"Corporate Action · {str(action['action_type']).title()}",
            "severity": "neutral",
            "issuer_entity_id": iss_id,
            "symbol": names.get(iss_id, iss_id),
            "company_name": names.get(iss_id, iss_id),
            "what_happened": f"{action['action_type']} filing (ex-date: {action['ex_date'] or 'TBD'})",
            "why_it_matters": "Lifecycle / capital-structure event requiring factor or thesis review",
            "what_changed": f"Terms complete: {action['terms_complete']} · {action['terms_json']}",
            "source": str(action["source_identifier"]),
        })

    if review_repository is not None:
        for w_row in review_repository.watchlist():
            iss_id = str(w_row["entity_id"])
            feed.append({
                "event_date": str(w_row["recorded_at"])[:10],
                "category": f"Watchlist · {str(w_row['status']).replace('_', ' ').title()}",
                "severity": "positive" if w_row["status"] == "research_priority" else "neutral",
                "issuer_entity_id": iss_id,
                "symbol": names.get(iss_id, iss_id),
                "company_name": names.get(iss_id, iss_id),
                "what_happened": f"Watchlist status set to {w_row['status']} by {w_row['reviewer']}",
                "why_it_matters": str(w_row["rationale"]),
                "what_changed": f"Recorded at {w_row['recorded_at']}",
                "source": f"SQLite review {w_row['revision_id']}",
            })

    return sorted(feed, key=lambda item: (str(item["event_date"]), str(item["category"])), reverse=True)
