"""HAMSA local Streamlit research workspace. Run: streamlit run app.py"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hamsa.domain.filters import FILTERS, EvidenceReference
from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.screening.data_access import (
    calendar_sessions, calendar_versions, company_input_as_of, known_source_documents,
    liquidity_input_as_of, source_freshness, universe_for_session,
)
from hamsa.screening.engines import (
    EngineThresholds, EvaluationState, evaluate_capex_conversion, evaluate_cash_quality,
    evaluate_company, evaluate_compounders, evaluate_earnings_inflection,
    evaluate_extreme_sell_side_liquidity,
)
from hamsa.storage.duckdb_repository import DuckDBRepository


DB_PATH = Path(os.environ.get("HAMSA_DUCKDB_PATH", str(ROOT / "data" / "processed" / "hamsa.duckdb")))
REVIEW_PATH = Path(os.environ.get("HAMSA_REVIEW_DB_PATH", str(ROOT / "data" / "processed" / "hamsa_reviews.sqlite3")))
SQLITE_SCHEMA = ROOT / "sql" / "sqlite_schema.sql"
ENGINE_NAMES = ("compounders", "earnings_inflection", "capex_conversion", "cash_quality", "extreme_sell_side_liquidity")


def _screening_config() -> dict[str, object]:
    configured = Path(os.environ.get("HAMSA_SCREENING_CONFIG", str(ROOT / "configs" / "screening.local.json")))
    path = configured if configured.is_file() else ROOT / "configs" / "screening.example.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read screening config {path}: {exc}") from exc


def _screening_defaults() -> dict[str, float | None]:
    path = Path(os.environ.get("HAMSA_SCREENING_CONFIG", str(ROOT / "configs" / "screening.local.json")))
    if not path.is_file():
        path = ROOT / "configs" / "screening.example.json"
    try:
        values = _screening_config()["thresholds"]
        result = {name: (float(values[name]) if values.get(name) is not None else None) for name in (
            "sales_cagr_min", "pat_cagr_min", "roce_min", "earnings_sales_growth_min",
            "earnings_pat_growth_min", "cash_cfo_pat_min", "unusual_volume_multiple",
            "unusual_delivery_percentage_points")}
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"invalid screening threshold configuration at {path}: {exc}") from exc


def _open_repositories():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DuckDBRepository(DB_PATH)


def _freshness_text(value):
    return value.isoformat() if value else "No EOD observations"


def _calendar_controls(repository, key: str):
    exchange = st.selectbox("Exchange-specific session context", ("NSE", "BSE"), key=f"{key}_exchange")
    versions = calendar_versions(repository, exchange)
    if not versions:
        st.warning(f"No imported {exchange} calendar version exists. Point-in-time screens are disabled for this venue.")
        return None
    version = st.selectbox("Explicit calendar version", versions, key=f"{key}_calendar")
    sessions = calendar_sessions(repository, exchange, version)
    if not sessions:
        st.warning("The selected calendar version contains no trading sessions.")
        return None
    selected = st.selectbox("EOD session", sessions, index=len(sessions) - 1, format_func=lambda d: d.isoformat(), key=f"{key}_date")
    mode = st.selectbox("Historical availability mode", ("public_as_of", "hamsa_known_as_of"), key=f"{key}_mode")
    st.caption(f"Screen cutoff: {selected.isoformat()} 15:30 Asia/Kolkata · Calendar: {version} · Mode: {mode}")
    return exchange, version, selected, mode


def _render_radar(repository):
    st.title("Market Radar")
    st.caption("NSE and BSE listings remain separate. No price averaging or unresolved listing enters the investment universe.")
    fresh = source_freshness(repository)
    c1, c2, c3 = st.columns(3)
    c1.metric("Latest stored NSE EOD date", _freshness_text(fresh["NSE"]))
    c2.metric("Latest stored BSE EOD date", _freshness_text(fresh["BSE"]))
    c3.metric("Schema version", str(repository._connection.execute("SELECT current_version FROM schema_metadata WHERE schema_name='hamsa_analytics'").fetchone()[0]))
    st.info("Stored EOD rows are observations, not proof of mainboard eligibility. A listing enters Radar only when identity, effective status, ordinary-equity class, platform class, calendar, and cutoff evidence all resolve.")
    selected = _calendar_controls(repository, "radar")
    if selected is None:
        st.subheader("Current coverage state")
        st.write("No production exchange calendar is available, so the system cannot establish a screen session or current eligible universe.")
        st.write("The local workspace contains user-downloaded EOD and master samples, but source records in those files are not automatically admitted as approved identity/classification evidence.")
        return
    exchange, version, session_date, mode = selected
    try:
        rows = universe_for_session(repository, exchange=exchange, session_date=session_date,
                                    availability_mode=mode, calendar_version=version)
        counts = {}
        for row in rows:
            counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
        columns = st.columns(6)
        columns[0].metric("Listings observed", len(rows))
        columns[1].metric("Eligible", counts.get("eligible_mainboard_ordinary_equity", 0))
        columns[2].metric("Unresolved", counts.get("unresolved_classification", 0))
        columns[3].metric("SME excluded", counts.get("excluded_sme", 0))
        columns[4].metric("Non-equity excluded", counts.get("excluded_non_equity", 0))
        columns[5].metric("Inactive excluded", counts.get("excluded_inactive_non_trading", 0))
        st.dataframe(rows, use_container_width=True, hide_index=True)
        if not counts.get("eligible_mainboard_ordinary_equity"):
            st.warning("No listing currently meets all approved evidence gates. No discovery engine will receive an issuer from this snapshot.")
        bars = repository.eod_observations_as_of(exchange=exchange, trade_date=session_date,
            cutoff=datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30),
            availability_mode=mode, calendar_version=version)
        st.metric(f"{exchange} EOD observations selected for session", len(bars))
    except Exception as exc:
        st.error(f"Point-in-time universe could not be evaluated: {exc}")


def _threshold_controls() -> EngineThresholds:
    st.subheader("Discovery thresholds")
    st.caption("Growth thresholds use decimal ratios (12% = 0.12); ROCE and delivery changes use percentage points. Liquidity thresholds have no project-approved default and remain unset until configured.")
    defaults = _screening_defaults()
    a, b, c = st.columns(3)
    sales = Decimal(str(a.number_input("3-year sales CAGR minimum", min_value=0.0, max_value=5.0, value=defaults["sales_cagr_min"], step=0.01, format="%.2f")))
    pat = Decimal(str(b.number_input("3-year PAT CAGR minimum", min_value=0.0, max_value=5.0, value=defaults["pat_cagr_min"], step=0.01, format="%.2f")))
    roce = Decimal(str(c.number_input("ROCE minimum (percentage points)", min_value=0.0, max_value=100.0, value=defaults["roce_min"], step=0.5, format="%.1f")))
    a, b, c = st.columns(3)
    sales_yoy = Decimal(str(a.number_input("Earnings sales YoY minimum", min_value=0.0, max_value=5.0, value=defaults["earnings_sales_growth_min"], step=0.01, format="%.2f")))
    pat_yoy = Decimal(str(b.number_input("Earnings PAT YoY minimum", min_value=0.0, max_value=5.0, value=defaults["earnings_pat_growth_min"], step=0.01, format="%.2f")))
    cfo_pat = Decimal(str(c.number_input("CFO / PAT minimum", min_value=0.0, max_value=10.0, value=defaults["cash_cfo_pat_min"], step=0.05, format="%.2f")))
    a, b = st.columns(2)
    volume_raw = a.text_input("Unusual volume multiple threshold (leave blank until configured)", value="" if defaults["unusual_volume_multiple"] is None else str(defaults["unusual_volume_multiple"]))
    delivery_raw = b.text_input("Delivery change threshold, percentage points (leave blank until configured)", value="" if defaults["unusual_delivery_percentage_points"] is None else str(defaults["unusual_delivery_percentage_points"]))
    try:
        volume = Decimal(volume_raw) if volume_raw.strip() else None
        delivery = Decimal(delivery_raw) if delivery_raw.strip() else None
        if any(item is not None and (not item.is_finite() or item < 0) for item in (volume, delivery)):
            raise ValueError("liquidity thresholds must be finite and non-negative")
    except Exception as exc:
        st.error(f"Invalid liquidity threshold: {exc}")
        st.stop()
    return EngineThresholds(sales, pat, roce, sales_yoy, pat_yoy, cfo_pat, volume, delivery)


def _all_engine_results(company, thresholds, liquidity_kwargs=None):
    return list(evaluate_company(company, thresholds, **(liquidity_kwargs or {})))


def _render_discovery(repository, reviews):
    st.title("Discovery Workbenches")
    st.caption("Research flags only. Every row shows its expression and inputs; no automatic buy/sell recommendation is produced.")
    selected = _calendar_controls(repository, "discovery")
    thresholds = _threshold_controls()
    engine = st.selectbox("Engine", ENGINE_NAMES, format_func=lambda x: x.replace("_", " ").title())
    reporting_scope = st.selectbox("Financial reporting scope", ("consolidated", "standalone"))
    if selected is None:
        st.warning("A verified, explicitly selected exchange calendar is required before any historical screen can run.")
        return
    exchange, version, session_date, mode = selected
    try:
        listings = universe_for_session(repository, exchange=exchange, session_date=session_date,
            availability_mode=mode, calendar_version=version)
        eligible = [row for row in listings if row["disposition"] == "eligible_mainboard_ordinary_equity"]
        issuers = sorted({row["issuer_entity_id"] for row in eligible})
        if not issuers:
            st.info("There are no evidence-qualified mainboard issuers for this session. Unresolved and excluded records are not screened.")
            return
        outputs = []
        metric_codes = _screening_config().get("metric_codes", {})
        for issuer_id in issuers:
            cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
            business_class = reviews.business_class_as_of(entity_id=issuer_id, session_date=session_date,
                cutoff=cutoff, exchange=exchange, availability_mode=mode, calendar_version=version)
            company = company_input_as_of(repository, issuer_entity_id=issuer_id, exchange=exchange,
                session_date=session_date, availability_mode=mode, calendar_version=version,
                metric_codes=metric_codes, business_class=business_class, reporting_scope=reporting_scope,
                review_repository=reviews)
            liq_kwargs = liquidity_input_as_of(repository, issuer_entity_id=issuer_id, exchange=exchange,
                session_date=session_date, availability_mode=mode, calendar_version=version,
                review_repository=reviews)
            all_results = _all_engine_results(company, thresholds, liq_kwargs)
            chosen = next(item for item in all_results if item.engine == engine)
            triggered_count = sum(item.state == EvaluationState.TRIGGERED for item in all_results)
            if triggered_count >= 2 and all(item.state not in (EvaluationState.UNPROVEN, EvaluationState.BLOCKED) for item in all_results):
                priority = "research_priority"
            elif triggered_count >= 2:
                priority = "multi_signal"
            elif triggered_count == 1:
                priority = "new_signal"
            else:
                priority = "no_trigger"
            outputs.append({"screen_session": session_date.isoformat(), "availability_mode": mode,
                "calendar_version": version, "issuer_entity_id": issuer_id, "engine_state": chosen.state.value,
                "research_triage": priority, "calculation": chosen.calculation_expression,
                "inputs": json.dumps(chosen.inputs, sort_keys=True),
                "source_observation_ids": ", ".join(chosen.source_observation_ids),
                "source_document_ids": ", ".join(chosen.source_document_ids),
                "explanation": chosen.explanation})
        st.dataframe(outputs, use_container_width=True, hide_index=True)
        st.caption("Triage labels are deterministic workflow states, not investment recommendations. Unproven/blocked inputs are never treated as passes.")
    except Exception as exc:
        st.error(f"Screen run stopped safely: {exc}")


def _issuer_rows(repository):
    return repository._connection.execute(
        """SELECT i.entity_id,coalesce((SELECT legal_name FROM issuer_name_revision n WHERE n.entity_id=i.entity_id
                     ORDER BY effective_from DESC LIMIT 1),i.entity_id) AS name
           FROM issuer_entity i ORDER BY name,entity_id"""
    ).fetchall()


def _render_dossier(repository, reviews):
    st.title("Company Intelligence Dossier")
    entities = _issuer_rows(repository)
    if not entities:
        st.info("No issuer identities are registered. Import an official security master through a supported local workflow and review identity/classification evidence before creating company records.")
        return
    labels = {row[0]: f"{row[1]} · {row[0]}" for row in entities}
    entity_id = st.selectbox("Company / issuer", list(labels), format_func=lambda key: labels[key])
    profile = repository._connection.execute(
        """SELECT security_id,share_class FROM equity_security WHERE issuer_entity_id=? ORDER BY security_id""",
        [entity_id],
    ).fetchall()
    listing_details = repository._connection.execute(
        """SELECT l.exchange,l.exchange_instrument_id,r.symbol,r.series,r.status,r.effective_from,r.effective_to,
                  s.identifier_value,s.effective_from,s.effective_to
           FROM equity_security e JOIN exchange_listing l USING(security_id)
           LEFT JOIN exchange_listing_revision r USING(listing_id)
           LEFT JOIN security_identifier_revision s ON s.security_id=e.security_id AND s.identifier_type='ISIN'
           WHERE e.issuer_entity_id=? ORDER BY l.exchange,l.exchange_instrument_id,r.effective_from""", [entity_id]
    ).fetchall()
    st.subheader("Identity and listing history")
    st.dataframe([{"security_id": item[0], "share_class": item[1]} for item in profile], use_container_width=True, hide_index=True)
    st.dataframe([dict(zip(("exchange","exchange_instrument_id","symbol","series","listing_status","listing_from","listing_to","isin","isin_from","isin_to"), row)) for row in listing_details], use_container_width=True, hide_index=True)
    st.subheader("Financial-sector / industrial screening classification")
    business_reviews = reviews.connection.execute(
        """SELECT r.* FROM issuer_business_classification_review_revision r WHERE entity_id=? AND NOT EXISTS
           (SELECT 1 FROM issuer_business_classification_review_revision n WHERE n.supersedes_review_revision_id=r.review_revision_id)
           ORDER BY valid_from""", (entity_id,)
    ).fetchall()
    st.dataframe([dict(row) for row in business_reviews], use_container_width=True, hide_index=True)
    sources = known_source_documents(repository)
    with st.form("business_classification_form"):
        business_class = st.selectbox("Reviewed business class", ("financial", "industrial"))
        st.caption("Use only the independently evidenced effective date. A source snapshot or review date is not an effective date.")
        valid_from = st.date_input("Applicability begins", value=None)
        valid_to = st.date_input("Applicability ends (optional)", value=None)
        classification_reviewer = st.text_input("Reviewer", key="business_class_reviewer")
        classification_reason = st.text_area("What does the cited source establish?")
        class_source_index = st.selectbox("Classification source", [None, *range(len(sources))], key="business_source",
            format_func=lambda idx: "Select source" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}")
        class_locator = st.text_input("Classification source locator")
        if st.form_submit_button("Append business-class review"):
            try:
                if valid_from is None:
                    raise ValueError("an evidence-backed effective applicability start date is required")
                if class_source_index is None:
                    raise ValueError("classification review requires a registered source citation")
                src = sources[class_source_index]
                reviews.append_business_classification_review(entity_id=entity_id,business_class=business_class,
                    valid_from=valid_from.isoformat(),valid_to=valid_to.isoformat() if valid_to else None,
                    reviewer=classification_reviewer,rationale=classification_reason,
                    source_document_id=src[0],locator=class_locator)
                st.success("Business-class review appended. Screening can use it only after both review and source are eligible at the selected cutoff.")
            except Exception as exc:
                st.error(f"Business-class review was not saved: {exc}")
    st.subheader("Point-in-time market and financial history")
    selected = _calendar_controls(repository, "dossier")
    if selected is None:
        st.info("Historical market and financial snapshots require an explicitly selected sourced exchange calendar version.")
    else:
        exchange, calendar_version, session_date, mode = selected
        cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
        eligible_rows = universe_for_session(repository, exchange=exchange, session_date=session_date,
            availability_mode=mode, calendar_version=calendar_version)
        listing_rows = [r for r in eligible_rows if r["issuer_entity_id"] == entity_id]
        listing_states = {r["listing_id"]: r["disposition"] for r in listing_rows}
        all_listing_ids = {r["listing_id"] for r in listing_rows}
        if not any(state == "eligible_mainboard_ordinary_equity" for state in listing_states.values()):
            st.warning("No listing qualifies for this historical mainboard universe snapshot. Any raw observations below are for source research only and cannot enter discovery engines.")
        selected_prices = repository.eod_observations_as_of(exchange=exchange, trade_date=session_date,
            cutoff=cutoff, availability_mode=mode, calendar_version=calendar_version)
        price_rows = [{**row, "universe_disposition": listing_states.get(row["listing_id"], "unresolved_classification")}
                      for row in selected_prices if row["listing_id"] in all_listing_ids]
        st.write("Venue-specific raw EOD observations for the selected session:")
        st.dataframe(price_rows, use_container_width=True, hide_index=True)
        if price_rows:
            st.caption("NSE and BSE raw prices remain separate and are never averaged. Eligibility is shown independently.")
        history_rows = []
        sessions = calendar_sessions(repository, exchange, calendar_version)[-120:]
        for market_day in sessions:
            day_cutoff = datetime.combine(market_day, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
            for observation in repository.eod_observations_as_of(exchange=exchange, trade_date=market_day,
                    cutoff=day_cutoff, availability_mode=mode, calendar_version=calendar_version):
                if observation["listing_id"] in all_listing_ids:
                    history_rows.append({"session": market_day, "listing": observation["listing_id"],
                                         "close_raw_INR_per_share": observation["close"]})
        if history_rows:
            import pandas as pd
            price_frame = pd.DataFrame(history_rows).pivot_table(index="session", columns="listing",
                values="close_raw_INR_per_share", aggfunc="last")
            st.caption("Last 120 sessions present in the selected calendar version; each listing is a separate series.")
            st.line_chart(price_frame)
        financial = repository.financial_observations_as_of(exchange=exchange,session_date=session_date,
            cutoff=cutoff,availability_mode=mode,calendar_version=calendar_version)
        financial_rows = [row for row in financial if row["subject_entity_id"] == entity_id]
        st.write("As-reported financial history selected at the cutoff (null and quality states are preserved):")
        st.dataframe(financial_rows, use_container_width=True, hide_index=True)
        market_caps = [row for row in financial_rows if row["metric"] == "market_cap" and row["value"] is not None
                       and row["quality_status"] == "observed"]
        if market_caps:
            latest_market_cap = max(market_caps, key=lambda row: row["period_end"])
            st.metric("Reported market capitalisation", f"{latest_market_cap['value']} {latest_market_cap['unit']}",
                      help=f"Source period end {latest_market_cap['period_end']}; no current market-cap freshness policy is configured.")
        else:
            st.caption("Market capitalisation: no point-in-time eligible sourced value is available.")
        st.caption("No metric/source freshness thresholds are configured. The database quality status and period end are shown without inventing a stale/ fresh classification.")
        if financial_rows:
            import pandas as pd
            metrics = sorted({str(item["metric"]) for item in financial_rows if item["value"] is not None and item["quality_status"] == "observed"})
            for metric in metrics:
                chart_rows = [{"period_end": item["period_end"], "value": float(item["value"])}
                              for item in financial_rows if item["metric"] == metric and item["value"] is not None and item["quality_status"] == "observed"]
                if chart_rows:
                    st.caption(f"{metric} · canonical unit {next(item['unit'] for item in financial_rows if item['metric']==metric)}")
                    st.line_chart(pd.DataFrame(chart_rows).set_index("period_end"))
        actions = repository.corporate_action_events_as_of(
            exchange=exchange, session_date=session_date, cutoff=cutoff,
            availability_mode=mode, calendar_version=calendar_version, issuer_entity_id=entity_id,
        )
        st.write("Point-in-time corporate-action events recorded in the local archive (not applied as adjusted prices):")
        st.dataframe([
            {key: row[key] for key in ("action_type","publication_date","published_at","ex_date","record_date","effective_date","source_document_id","terms_complete")}
            for row in actions
        ], use_container_width=True, hide_index=True)
        if any(state == "eligible_mainboard_ordinary_equity" for state in listing_states.values()):
            metric_codes = _screening_config().get("metric_codes", {})
            defaults = _screening_defaults()
            dossier_thresholds = EngineThresholds(
                Decimal(str(defaults["sales_cagr_min"])), Decimal(str(defaults["pat_cagr_min"])),
                Decimal(str(defaults["roce_min"])), Decimal(str(defaults["earnings_sales_growth_min"])),
                Decimal(str(defaults["earnings_pat_growth_min"])), Decimal(str(defaults["cash_cfo_pat_min"])),
                Decimal(str(defaults["unusual_volume_multiple"])) if defaults["unusual_volume_multiple"] is not None else None,
                Decimal(str(defaults["unusual_delivery_percentage_points"])) if defaults["unusual_delivery_percentage_points"] is not None else None,
            )
            dossier_company = company_input_as_of(
                repository, issuer_entity_id=entity_id, exchange=exchange, session_date=session_date,
                availability_mode=mode, calendar_version=calendar_version, metric_codes=metric_codes,
                review_repository=reviews,
            )
            dossier_liq = liquidity_input_as_of(
                repository, issuer_entity_id=entity_id, exchange=exchange, session_date=session_date,
                availability_mode=mode, calendar_version=calendar_version, review_repository=reviews,
            )
            engine_evals = _all_engine_results(dossier_company, dossier_thresholds, dossier_liq)
            st.write("Point-in-time discovery-engine evaluations at the selected session cutoff:")
            st.dataframe([
                {
                    "engine": item.engine,
                    "state": item.state.value,
                    "expression": item.calculation_expression,
                    "inputs": json.dumps(item.inputs, sort_keys=True),
                    "source_documents": ", ".join(item.source_document_ids),
                    "explanation": item.explanation,
                }
                for item in engine_evals
            ], use_container_width=True, hide_index=True)
    with st.expander("Engine qualitative evidence gates · human review only", expanded=False):
        st.caption("Capex Conversion, Cash Quality, and Extreme Sell-Side Liquidity require source-cited human reviews for qualitative gates.")
        current_engine_ev = reviews.current_engine_evidence_reviews(entity_id)
        if current_engine_ev:
            st.dataframe([dict(row) for row in current_engine_ev], use_container_width=True, hide_index=True)
        with st.form("engine_evidence_form"):
            ev_key = st.selectbox("Evidence gate", reviews.ENGINE_EVIDENCE_KEYS)
            ev_status = st.selectbox("Review status", ("approved", "rejected", "unproven"))
            ev_valid_from = st.date_input("Applicability begins (evidence-backed)", value=None, key="ev_valid_from")
            ev_valid_to = st.date_input("Applicability ends (optional)", value=None, key="ev_valid_to")
            ev_reviewer = st.text_input("Reviewer", key="ev_reviewer")
            ev_rationale = st.text_area("Evidence rationale", key="ev_rationale")
            ev_source_idx = st.selectbox("Evidence source document", [None, *range(len(sources))], key="ev_source",
                format_func=lambda idx: "Select source" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}")
            ev_locator = st.text_input("Precise source locator", key="ev_locator")
            if st.form_submit_button("Append engine-evidence review"):
                try:
                    if ev_valid_from is None:
                        raise ValueError("an evidence-backed applicability start date is required")
                    ev_doc_id = sources[ev_source_idx][0] if ev_source_idx is not None else None
                    reviews.append_engine_evidence_review(
                        entity_id=entity_id, evidence_key=ev_key, review_status=ev_status,
                        valid_from=ev_valid_from.isoformat(),
                        valid_to=ev_valid_to.isoformat() if ev_valid_to else None,
                        reviewer=ev_reviewer, rationale=ev_rationale,
                        source_document_id=ev_doc_id, locator=ev_locator,
                    )
                    st.success("Engine-evidence review appended.")
                except Exception as exc:
                    st.error(f"Engine-evidence review was not saved: {exc}")
    state = reviews.current_reviews(entity_id)
    note = reviews.latest_company_note(entity_id)
    with st.expander("Business thesis, thesis killers, and checkpoint", expanded=True):
        with st.form("company_thesis_form"):
            thesis = st.text_area("Business thesis", value=note["business_thesis"] if note else "")
            killers = st.text_area("What could permanently impair the thesis", value=note["thesis_killers"] if note else "")
            next_review = st.date_input("Next review checkpoint", value=date.fromisoformat(note["next_review_date"]) if note and note["next_review_date"] else None)
            reviewer = st.text_input("Reviewer", key="thesis_reviewer")
            note_source_index = st.selectbox("Thesis source citation", [None, *range(len(sources))], key="thesis_source",
                format_func=lambda idx: "Select source" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}")
            note_locator = st.text_input("Thesis source locator")
            note_evidence = st.text_input("What does this source support?")
            if st.form_submit_button("Append thesis revision"):
                try:
                    if note_source_index is None:
                        raise ValueError("a thesis revision requires at least one registered source citation")
                    src = sources[note_source_index]
                    evidence = (EvidenceReference(src[0],src[1],src[2],note_locator,note_evidence),)
                    reviews.append_company_research_note(entity_id=entity_id,business_thesis=thesis,
                        thesis_killers=killers,reviewer=reviewer,next_review_date=next_review.isoformat() if next_review else None,
                        evidence=evidence)
                    st.success("Thesis revision appended.")
                except Exception as exc:
                    st.error(f"Thesis was not saved: {exc}")
    st.subheader("Hamsa 11 · human review only")
    selected_filter = st.selectbox("Filter", FILTERS, format_func=lambda item: f"{item.name}: {item.prompt}")
    current = state.get(selected_filter.key.value)
    if current:
        st.write(f"Current status: **{current['status']}** · reviewed {current['reviewed_at']} · {current['rationale']}")
        st.dataframe([dict(row) for row in reviews.evidence_for(current["review_id"])], use_container_width=True, hide_index=True)
    sources = known_source_documents(repository)
    with st.form("filter_review_form"):
        status = st.selectbox("Assessment", ("Unproven", "Pass", "Fail"), index=0)
        reviewer = st.text_input("Reviewer", key="filter_reviewer")
        rationale = st.text_area("Evidence-backed rationale / reason it remains unproven")
        source_index = st.selectbox("Evidence source (optional for Unproven)", [None, *range(len(sources))],
            format_func=lambda idx: "No source citation" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}")
        locator = st.text_input("Source page / section / row locator")
        evidence_note = st.text_input("What this source supports")
        if st.form_submit_button("Append Hamsa 11 review"):
            try:
                evidence = ()
                if source_index is not None:
                    if not locator.strip() or not evidence_note.strip():
                        raise ValueError("source citation requires locator and support note")
                    src = sources[source_index]
                    evidence = (EvidenceReference(src[0], src[1], src[2], locator.strip(), evidence_note.strip()),)
                reviews.append_review(entity_id=entity_id,filter_key=selected_filter.key.value,status=status,
                    reviewer=reviewer,rationale=rationale,evidence=evidence)
                st.success("Review appended. Earlier reviews and citations remain available in history.")
            except Exception as exc:
                st.error(f"Review was not saved: {exc}")
    with st.expander("Review history"):
        history = reviews.history(entity_id, selected_filter.key.value)
        st.dataframe([dict(row) for row in history], use_container_width=True, hide_index=True)
    st.subheader("Source documents")
    st.dataframe([{"document_id": row[0], "identifier": row[1], "sha256": row[2], "provider/dataset": row[3]}
                  for row in sources], use_container_width=True, hide_index=True)


def _render_watchlist(repository, reviews):
    st.title("Watchlist and Thesis Monitor")
    entries = reviews.watchlist()
    labels = {row[0]: f"{row[1]} · {row[0]}" for row in _issuer_rows(repository)}
    st.dataframe([{**dict(row), "issuer_name": labels.get(row["entity_id"], row["entity_id"])}
                  for row in entries], use_container_width=True, hide_index=True)
    if not labels:
        st.info("No issuer identities are registered yet.")
        return
    with st.form("watchlist_form"):
        entity_id = st.selectbox("Company / issuer", list(labels), format_func=lambda key: labels[key])
        status = st.selectbox("Workflow status", ("watch", "research_priority", "cooling", "rejected"))
        reviewer = st.text_input("Reviewer", key="watch_reviewer")
        rationale = st.text_area("Why this state changed")
        if st.form_submit_button("Append watchlist event"):
            try:
                reviews.append_watchlist_event(entity_id=entity_id,status=status,reviewer=reviewer,rationale=rationale)
                st.success("Watchlist event appended.")
            except Exception as exc:
                st.error(f"Watchlist event was not saved: {exc}")
    st.caption("Workflow status is user recorded. It does not represent a buy/sell instruction.")


def _render_events(repository):
    st.title("Market & Event Intelligence")
    selected = _calendar_controls(repository, "events")
    if selected is None:
        st.info("An explicit venue calendar is required before event availability or liquidity history can be selected.")
        return
    exchange, version, session_date, mode = selected
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    visible_events = repository.corporate_action_events_as_of(
        exchange=exchange, session_date=session_date, cutoff=cutoff,
        availability_mode=mode, calendar_version=version,
    )
    st.subheader("Corporate-action and security-lifecycle filings")
    st.dataframe(visible_events, use_container_width=True, hide_index=True)
    st.subheader("Venue-specific EOD liquidity observations")
    universe = universe_for_session(repository, exchange=exchange, session_date=session_date,
        availability_mode=mode, calendar_version=version)
    eligible_listings = {row["listing_id"] for row in universe if row["disposition"] == "eligible_mainboard_ordinary_equity"}
    sessions = calendar_sessions(repository, exchange, version)[-20:]
    liquidity = []
    for day in sessions:
        day_cutoff = datetime.combine(day, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
        prices = repository.eod_observations_as_of(exchange=exchange,trade_date=day,cutoff=day_cutoff,
            availability_mode=mode,calendar_version=version)
        deliveries = {
            drow["listing_id"]: drow
            for drow in repository.delivery_observations_as_of(
                exchange=exchange, trade_date=day, cutoff=day_cutoff,
                availability_mode=mode, calendar_version=version,
            )
            if drow["quality_status"] == "observed"
        }
        for price in prices:
            if price["listing_id"] not in eligible_listings:
                continue
            drow = deliveries.get(price["listing_id"], {})
            liquidity.append({"session": day,"exchange": exchange,"listing_id": price["listing_id"],
                "observation_id": price["observation_id"],"close_raw": price["close"],"volume_raw": price["volume"],
                "price_source_document_id": price["source_document_id"],
                "delivery_observation_id": drow.get("observation_id"),
                "delivery_quantity": drow.get("delivery_quantity"),
                "traded_quantity": drow.get("traded_quantity"),
                "delivery_percentage": drow.get("delivery_percentage"),
                "delivery_source_document_id": drow.get("source_document_id")})
    st.dataframe(liquidity, use_container_width=True, hide_index=True)
    st.caption("No unusual-volume threshold, forced-selling classification, or absorption-capacity evidence is configured here. Falling prices and delivery percentages alone never trigger an opportunity.")
    if not visible_events:
        st.info("No point-in-time-eligible event filings are present for this snapshot.")
    if not liquidity:
        st.info("No source-backed, eligible listing EOD rows are present for these sessions.")


def _render_data_operations(repository):
    st.title("Data Operations")
    st.write("All source ingestion is local-file-only. HAMSA makes no market-data network requests.")
    _render_security_admission_workflow(repository)
    st.subheader("Available operational paths")
    st.code(".venv\\Scripts\\python.exe scripts\\admit_security.py --help", language="powershell")
    st.code(".venv\\Scripts\\python.exe scripts\\ingest_official_eod.py --help", language="powershell")
    st.code(".venv\\Scripts\\python.exe scripts\\ingest_financial_results.py --help", language="powershell")
    st.code(".venv\\Scripts\\python.exe scripts\\ingest_exchange_calendar.py --help", language="powershell")
    st.code(".venv\\Scripts\\python.exe scripts\\ingest_tejhq_pilot.py --help", language="powershell")
    st.warning("Official EOD remains the daily path; TejHQ is the historical source only after source, identity, classification, calendar, and point-in-time gates pass. No bulk backfill is run here.")
    st.subheader("Database inventory")
    tables = [row[0] for row in repository._connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()]
    counts = []
    for table in tables:
        if table in {"issuer_entity", "equity_security", "exchange_listing", "source_document_revision",
                     "exchange_trading_session", "eod_price_observation_revision", "financial_observation_revision",
                     "observation_quarantine", "listing_classification_snapshot", "listing_classification_review_revision"}:
            counts.append({"table": table, "rows": repository._connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]})
    st.dataframe(counts, use_container_width=True, hide_index=True)
    st.subheader("Known external evidence blockers")
    st.markdown("""
- Production calendar versions must be supplied for each venue and date range.
- Current NSE/BSE masters need dated source snapshots and reviewed identity mappings.
- NSE ordinary-equity and board crosswalk evidence is incomplete; BSE current SCRIP.ZIP and classification evidence are not in this workspace.
- No normalized quarterly/annual company financial data is loaded.
- No sourced block/bulk-deal, ownership-change, order/commissioning or cash-collection event feed is loaded.
- The BSE historical sample's immutable TejHQ file-revision provenance remains unresolved.
""")


def _render_security_admission_workflow(repository):
    st.subheader("Evidence-backed security admission")
    st.caption("Every source and review is appended. Candidate identity, listing status, instrument class, platform class, and calendar remain separate. No field or review is auto-approved.")
    with st.expander("1 · Register a local source document", expanded=False):
        st.warning("Enter the original local file and cite its actual source page/URL plus a precise record, row, page, or section locator. A filename or operator-entered origin does not verify authenticity.")
        with st.form("admission_source_registration"):
            source_path = st.text_input("Original local file path")
            source_exchange = st.selectbox("Exchange / source owner", ("NSE", "BSE"))
            source_dataset = st.text_input("Dataset", placeholder="e.g. CM-UDiFF-EOD")
            source_identifier = st.text_input("Immutable source identifier", placeholder="Exact exchange document/file identifier")
            source_doc_date = st.date_input("Source document date", value=None, key="admission_source_doc_date")
            source_publication_date = st.date_input("Publication date", value=None, key="admission_publication_date")
            source_published_at = st.text_input("Reliable publication timestamp (optional, ISO-8601 with timezone)")
            source_locator = st.text_input("Source locator", placeholder="Official page URL + file name, or document/page reference")
            source_origin = st.text_area("What establishes the source origin?", placeholder="Record evidence, or state that origin is unverified.")
            source_parser = st.text_input("Parser / intake version", value="manual-source-registration-v1")
            retain_source = st.checkbox("Authorize local archival of these exact bytes")
            register_submitted = st.form_submit_button("Archive and register source")
        if register_submitted:
            try:
                if not source_path.strip() or source_doc_date is None or source_publication_date is None:
                    raise ValueError("file path, source document date, and publication date are required")
                if not source_identifier.strip() or not source_locator.strip() or not source_origin.strip():
                    raise ValueError("source identifier, source locator, and source-origin note are required")
                published_at = datetime.fromisoformat(source_published_at) if source_published_at.strip() else None
                result = repository.register_local_source_document(
                    source_path, archive_root=ROOT / "data" / "raw" / "archive" / "admission-evidence",
                    exchange=source_exchange, dataset=source_dataset, source_identifier=source_identifier,
                    source_document_date=source_doc_date, publication_date=source_publication_date,
                    published_at=published_at, parser_version=source_parser,
                    retention_authorized=retain_source, source_locator=source_locator,
                    source_metadata={"source_origin": source_origin, "source_origin_review": "operator_recorded_not_automatically_verified"},
                )
                st.success(f"Source registered: {result.source_document_id} · SHA-256 {result.checksum_sha256} · revision {result.revision_number}" + (" · identical bytes" if result.duplicate else ""))
            except Exception as exc:
                st.error(f"Source registration failed: {exc}")

    sources = repository.source_documents_for_review()
    source_by_id = {item["source_document_id"]: item for item in sources}
    candidates = repository.security_admission_candidates()
    with st.expander("2 · Create or resolve an ISIN identity candidate", expanded=False):
        exchange_sources = [item for item in sources if item["provider"] in ("NSE", "BSE")]
        if not exchange_sources:
            st.info("Register exchange evidence before creating an identity candidate.")
        else:
            def source_label(doc_id):
                item = source_by_id[doc_id]
                origin = item["source_origin"]
                return f"{item['provider']} · {item['original_filename']} · {item['checksum_sha256'][:12]} · origin: {origin}"
            with st.form("admission_identity_candidate"):
                identity_source_id = st.selectbox("Evidence source", [item["source_document_id"] for item in exchange_sources], format_func=source_label)
                identity_exchange = source_by_id[identity_source_id]["provider"]
                identity_company = st.text_input("Issuer name as shown in cited source")
                identity_issuer_id = st.text_input("Issuer entity ID", placeholder="Stable local ID")
                identity_security_id = st.text_input("Security ID", placeholder="Stable local ID; one security per ISIN/share class")
                identity_listing_id = st.text_input("Exchange listing ID", placeholder="Stable venue-specific listing ID")
                identity_instrument_id = st.text_input("Exchange instrument identifier")
                identity_isin = st.text_input("ISIN")
                identity_observed_from = st.date_input("ISIN mapping supported from (evidence date)", value=None, key="identity_observed_from")
                identity_locator = st.text_input("Exact source locator", placeholder="e.g. zip:member.csv:csv:line:3147")
                identity_submit = st.form_submit_button("Create pending identity candidate")
            st.caption("Candidate creation only adds a pending ISIN mapping. It does not approve identity, establish listing status/effective history, or classify the instrument/platform.")
            if identity_submit:
                try:
                    if identity_observed_from is None:
                        raise ValueError("an evidence-backed date for the observed identity mapping is required")
                    result = repository.append_security_identity_candidate(
                        issuer_entity_id=identity_issuer_id, security_id=identity_security_id, listing_id=identity_listing_id,
                        exchange=identity_exchange, exchange_instrument_id=identity_instrument_id, isin=identity_isin,
                        legal_name=identity_company, identity_observed_from=identity_observed_from,
                        source_document_id=identity_source_id, source_locator=identity_locator,
                    )
                    st.success(f"Pending candidate created: {result}")
                except Exception as exc:
                    st.error(f"Identity candidate not saved: {exc}")

    with st.expander("3 · Review an ISIN mapping", expanded=False):
        identity_revisions = [row for row in repository.security_identity_revisions()
                              if row["review_status"] in (None, "pending", "rejected")]
        if not identity_revisions:
            st.info("No pending/rejected ISIN mappings require review.")
        elif not sources:
            st.info("Register evidence before reviewing an ISIN mapping.")
        else:
            identity_map_by_id = {row["identifier_revision_id"]: row for row in identity_revisions}
            identity_ids = list(identity_map_by_id)
            with st.form("admission_identity_review"):
                target_id = st.selectbox("Pending ISIN mapping", identity_ids,
                    format_func=lambda key: f"{identity_map_by_id[key]['identifier_value']} · {identity_map_by_id[key]['security_id']} · {identity_map_by_id[key]['review_status']} · {key}")
                identity_review_status = st.selectbox("Human decision", ("approved", "rejected"))
                identity_reviewer = st.text_input("Reviewer name")
                identity_evidence_id = st.selectbox("Review evidence document", [s["source_document_id"] for s in sources], format_func=source_label)
                identity_evidence_locator = st.text_input("Precise evidence locator")
                identity_rationale = st.text_area("Review rationale", key="identity_rationale")
                reviewer_confirmed = st.checkbox("I reviewed this exact evidence and am making this identity decision.", key="identity_review_confirm")
                identity_review_submit = st.form_submit_button("Append identity review")
            if identity_review_submit:
                try:
                    if not identity_reviewer.strip() or not identity_evidence_locator.strip():
                        raise ValueError("reviewer and evidence locator are required")
                    if not reviewer_confirmed:
                        raise ValueError("explicit human confirmation is required")
                    prior_review_id = identity_map_by_id[target_id].get("active_review_id")
                    review_id = repository.append_security_identifier_review(
                        identifier_revision_id=target_id, review_status=identity_review_status,
                        reviewer=identity_reviewer, reviewer_actor_type="human",
                        evidence_source_document_id=identity_evidence_id,
                        evidence_locator=identity_evidence_locator,
                        rationale=identity_rationale,
                        supersedes_review_id=prior_review_id,
                    )
                    st.success(f"Identity review appended as {review_id}")
                except Exception as exc:
                    st.error(f"Identity review not saved: {exc}")

    with st.expander("4 · Record an effective listing interval and review it", expanded=False):
        listing_candidates = [row for row in candidates if row.get("listing_id")]
        if not listing_candidates or not sources:
            st.info("A listing candidate and registered source are required first.")
        else:
            listing_ids = [row["listing_id"] for row in listing_candidates]
            with st.form("admission_listing_revision"):
                selected_listing = st.selectbox("Venue-specific listing", listing_ids,
                    format_func=lambda key: next(f"{row['exchange']} · {row['exchange_instrument_id']} · {row['isin'] or 'ISIN unproven'} · {key}" for row in listing_candidates if row['listing_id']==key))
                list_source = st.selectbox("Listing evidence source", [s["source_document_id"] for s in sources if s["provider"] == next(x["exchange"] for x in listing_candidates if x["listing_id"]==selected_listing)],
                    format_func=source_label, key="listing_source")
                listing_symbol = st.text_input("Symbol exactly as evidenced")
                listing_series = st.text_input("Series / class label as evidenced (optional)")
                listing_status = st.selectbox("Status to be reviewed", ("active", "suspended", "delisted", "relisted"))
                listing_start = st.date_input("Effective from (must be source-backed)", value=None, key="listing_start")
                listing_end = st.date_input("Effective to (optional)", value=None, key="listing_end")
                listing_locator = st.text_input("Exact source locator", key="listing_locator")
                listing_parser = st.text_input("Parser / entry version", value="operator-listing-entry-v1")
                listing_submit = st.form_submit_button("Append unreviewed listing revision")
            if listing_submit:
                try:
                    if listing_start is None:
                        raise ValueError("effective_from is required and cannot be inferred from a snapshot date")
                    listing_revision_id = repository.append_exchange_listing_revision({
                        "listing_revision_id": repository._admission_id("listingrev", selected_listing, listing_start, list_source, listing_locator),
                        "listing_id": selected_listing, "symbol": listing_symbol, "series": listing_series or None,
                        "status": listing_status, "effective_from": listing_start, "effective_to": listing_end,
                        "source_document_id": list_source, "extraction_locator": listing_locator,
                        "parser_version": listing_parser,
                    })
                    st.success(f"Unreviewed listing revision appended: {listing_revision_id}")
                except Exception as exc:
                    st.error(f"Listing revision not saved: {exc}")
            listing_revisions = [row for row in repository.exchange_listing_revisions()
                                 if row["review_status"] in (None, "pending", "rejected")]
            if listing_revisions:
                review_map = {row["listing_revision_id"]: row for row in listing_revisions}
                with st.form("admission_listing_review"):
                    review_listing_id = st.selectbox("Listing revision to review", list(review_map),
                        format_func=lambda key: f"{review_map[key]['symbol']} · {review_map[key]['status']} · {review_map[key]['effective_from']} · {key}")
                    listing_review_status = st.selectbox("Human decision", ("approved", "rejected"), key="listing_review_status")
                    listing_reviewer = st.text_input("Reviewer", key="listing_reviewer")
                    listing_review_evidence = st.selectbox("Review evidence document", [s["source_document_id"] for s in sources], format_func=source_label, key="listing_review_evidence")
                    listing_review_locator = st.text_input("Evidence locator", key="listing_review_locator")
                    listing_rationale = st.text_area("Review rationale", key="listing_rationale")
                    listing_review_confirm = st.checkbox("I reviewed the cited listing-status and effective-date evidence.", key="listing_review_confirm")
                    listing_review_submit = st.form_submit_button("Append listing-status review")
                if listing_review_submit:
                    try:
                        if not listing_review_confirm:
                            raise ValueError("explicit human confirmation is required")
                        prior_listing_review_id = review_map[review_listing_id].get("active_review_id")
                        review_id = repository.append_exchange_listing_revision_review({
                            "listing_revision_review_id": repository._admission_id("listingreview", review_listing_id, listing_review_status, listing_review_evidence, listing_review_locator, prior_listing_review_id),
                            "listing_revision_id": review_listing_id, "review_status": listing_review_status,
                            "reviewed_by": listing_reviewer, "evidence_source_document_id": listing_review_evidence,
                            "evidence_locator": listing_review_locator, "rationale": listing_rationale,
                            "supersedes_review_id": prior_listing_review_id,
                        })
                        st.success(f"Listing review appended: {review_id}")
                    except Exception as exc:
                        st.error(f"Listing review not saved: {exc}")

    with st.expander("5 · Record classification evidence and independent reviews", expanded=False):
        eligible_listings = []
        for row in candidates:
            if not row.get("listing_id") or not row.get("exchange"):
                continue
            approved_isin = [item for item in repository.security_identity_revisions(row["security_id"])
                             if item["identifier_type"] == "ISIN" and item["identifier_value"] == row.get("isin")
                             and item["review_status"] == "approved"]
            if approved_isin:
                eligible_listings.append(row)
        if not eligible_listings:
            st.info("Classification snapshots attach to a reviewed listing identity. Approve the ISIN mapping first; no classification will be inferred from symbols or series.")
        elif not sources:
            st.info("Register exchange source evidence first.")
        else:
            listing_ids = [row["listing_id"] for row in eligible_listings]
            with st.form("admission_classification_snapshot"):
                snapshot_listing = st.selectbox("Reviewed listing identity", listing_ids,
                    format_func=lambda key: next(f"{row['exchange']} · {row['exchange_instrument_id']} · {row['isin']} · {key}" for row in eligible_listings if row['listing_id']==key))
                snapshot_exchange = next(row["exchange"] for row in eligible_listings if row["listing_id"]==snapshot_listing)
                snapshot_source = st.selectbox("Raw classification source", [s["source_document_id"] for s in sources if s["provider"]==snapshot_exchange], format_func=source_label, key="snapshot_source")
                snapshot_date = st.date_input("Source snapshot date", value=None, key="classification_snapshot_date")
                raw_instrument = st.text_input("Raw instrument-class field/value (optional)")
                raw_platform = st.text_input("Raw platform field/value (optional)")
                raw_status = st.text_input("Raw listing-status field/value (optional)")
                raw_series = st.text_input("Raw series (source fact only; not an eligibility rule)")
                snapshot_locator = st.text_input("Exact row/page locator", key="snapshot_locator")
                snapshot_fields = st.text_area("Raw source fields as JSON", value="{}")
                snapshot_submit = st.form_submit_button("Append raw classification snapshot")
            if snapshot_submit:
                try:
                    if snapshot_date is None or not snapshot_locator.strip():
                        raise ValueError("snapshot date and precise source locator are required")
                    snapshot_id = repository._admission_id("class-snapshot", snapshot_listing, snapshot_source, snapshot_locator)
                    repository.append_listing_classification_snapshot({
                        "listing_classification_snapshot_id": snapshot_id, "listing_id": snapshot_listing,
                        "exchange": snapshot_exchange, "source_document_id": snapshot_source,
                        "source_snapshot_date": snapshot_date, "raw_isin": next(row["isin"] for row in eligible_listings if row["listing_id"]==snapshot_listing),
                        "raw_symbol": next(row["exchange_instrument_id"] for row in eligible_listings if row["listing_id"]==snapshot_listing),
                        "raw_series": raw_series or None, "raw_listing_status": raw_status or None,
                        "raw_instrument_class_value": raw_instrument or None, "raw_platform_class_value": raw_platform or None,
                        "source_fields_json": json.loads(snapshot_fields), "parser_version": "operator-classification-snapshot-v1",
                        "extraction_locator": snapshot_locator,
                    })
                    st.success(f"Raw classification snapshot appended: {snapshot_id}; it is not an approval.")
                except Exception as exc:
                    st.error(f"Classification snapshot not saved: {exc}")
            snapshots = repository.classification_snapshots()
            pending_snapshots = [row for row in snapshots if row["review_revision_id"] is None or
                row["instrument_review_status"] in (None, "pending", "rejected") or row["platform_review_status"] in (None, "pending", "rejected")]
            if pending_snapshots:
                snapshot_map = {row["snapshot_id"]: row for row in pending_snapshots}
                with st.form("admission_classification_review"):
                    selected_snapshot = st.selectbox("Classification evidence snapshot", list(snapshot_map),
                        format_func=lambda key: f"{snapshot_map[key]['exchange']} · {snapshot_map[key]['raw_isin']} · {snapshot_map[key]['source_snapshot_date']} · {key}")
                    selected_row = snapshot_map[selected_snapshot]
                    source_options = [s["source_document_id"] for s in sources if s["provider"]==selected_row["exchange"]]
                    instrument_status = st.selectbox("Instrument review", ("pending", "approved", "rejected"), key="instrument_status")
                    instrument_class = st.selectbox("Instrument class", ("unknown", "ordinary_equity", "etf", "mutual_fund", "reit", "invit", "preference", "warrant", "rights", "debt", "other"), key="instrument_class")
                    instrument_from = st.date_input("Instrument class valid from", value=None, key="instrument_from")
                    instrument_to = st.date_input("Instrument class valid to (optional)", value=None, key="instrument_to")
                    instrument_source = st.selectbox("Instrument evidence document", [None, *source_options], format_func=lambda x: "Select evidence" if x is None else source_label(x), key="instrument_source")
                    instrument_locator = st.text_input("Instrument evidence locator", key="instrument_locator")
                    instrument_reviewer = st.text_input("Instrument reviewer", key="instrument_reviewer")
                    platform_status = st.selectbox("Platform review", ("pending", "approved", "rejected"), key="platform_status")
                    platform_class = st.selectbox("Platform class", ("unknown", "mainboard", "sme", "other_platform"), key="platform_class")
                    platform_from = st.date_input("Platform valid from", value=None, key="platform_from")
                    platform_to = st.date_input("Platform valid to (optional)", value=None, key="platform_to")
                    platform_source = st.selectbox("Platform evidence document", [None, *source_options], format_func=lambda x: "Select evidence" if x is None else source_label(x), key="platform_source")
                    platform_locator = st.text_input("Platform evidence locator", key="platform_locator")
                    platform_reviewer = st.text_input("Platform reviewer", key="platform_reviewer")
                    class_rationale = st.text_area("Review rationale", key="classification_rationale")
                    class_confirm = st.checkbox("I reviewed each approved dimension against its cited source evidence.", key="classification_confirm")
                    class_review_submit = st.form_submit_button("Append independent classification review")
                if class_review_submit:
                    try:
                        if not class_confirm:
                            raise ValueError("explicit human confirmation is required")
                        for dim, status, valid_from, evidence, locator, reviewer in (
                            ("instrument", instrument_status, instrument_from, instrument_source, instrument_locator, instrument_reviewer),
                            ("platform", platform_status, platform_from, platform_source, platform_locator, platform_reviewer),
                        ):
                            if status == "approved" and (valid_from is None or evidence is None or not locator.strip() or not reviewer.strip()):
                                raise ValueError(f"approved {dim} review requires effective date, evidence, locator, and reviewer")
                        prior_id = selected_row["review_revision_id"]
                        review_id = repository._admission_id("class-review", selected_snapshot, instrument_status, platform_status,
                            instrument_source, instrument_locator, platform_source, platform_locator)
                        repository.append_listing_classification_review_revision({
                            "classification_review_revision_id": review_id, "listing_classification_snapshot_id": selected_snapshot,
                            "listing_id": selected_row["listing_id"], "rationale": class_rationale,
                            "supersedes_review_revision_id": prior_id,
                            "instrument_review_status": instrument_status, "instrument_class": instrument_class,
                            "instrument_valid_from": instrument_from, "instrument_valid_to": instrument_to,
                            "instrument_evidence_source_document_id": instrument_source, "instrument_evidence_locator": instrument_locator,
                            "instrument_reviewed_by": instrument_reviewer,
                            "platform_review_status": platform_status, "platform_class": platform_class,
                            "platform_valid_from": platform_from, "platform_valid_to": platform_to,
                            "platform_evidence_source_document_id": platform_source, "platform_evidence_locator": platform_locator,
                            "platform_reviewed_by": platform_reviewer,
                        })
                        st.success(f"Independent classification review appended: {review_id}")
                    except Exception as exc:
                        st.error(f"Classification review not saved: {exc}")

    with st.expander("6 · Qualification status and outstanding prerequisites", expanded=True):
        if not candidates:
            st.info("No identity candidates exist yet.")
        else:
            listing_candidates = [row for row in candidates if row.get("listing_id")]
            if listing_candidates:
                listing_map = {row["listing_id"]: row for row in listing_candidates}
                selected_listing = st.selectbox("Listing to assess", list(listing_map),
                    format_func=lambda key: f"{listing_map[key]['exchange']} · {listing_map[key]['legal_name'] or listing_map[key]['issuer_entity_id']} · {listing_map[key]['isin'] or 'ISIN unproven'} · {key}",
                    key="admission_status_listing")
                selected = listing_map[selected_listing]
                status_date = st.date_input("Observation date for prerequisite check", value=date.today(), key="admission_status_date")
                status_mode = st.selectbox("Availability mode", ("public_as_of", "hamsa_known_as_of"), key="admission_status_mode")
                available_calendars = calendar_versions(repository, selected["exchange"])
                calendar_version = st.selectbox("Explicit calendar version", [None, *available_calendars],
                    format_func=lambda x: "No calendar selected" if x is None else x, key="admission_status_calendar")
                status_cutoff = datetime.combine(status_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
                try:
                    summary = repository.security_admission_checklist(listing_id=selected_listing,
                        observation_date=status_date, cutoff=status_cutoff, availability_mode=status_mode,
                        calendar_version=calendar_version)
                    st.dataframe(summary["checks"], use_container_width=True, hide_index=True)
                    st.metric("Derived universe disposition", summary["disposition"])
                except Exception as exc:
                    st.error(f"Prerequisite check failed closed: {exc}")


def main() -> None:
    st.set_page_config(page_title="HAMSA · Investment Research", layout="wide")
    st.title("HAMSA")
    st.caption("Local end-of-day investment research · no automated buy/sell recommendations")
    try:
        repository = _open_repositories()
    except Exception as exc:
        st.error(f"Could not open the local DuckDB database at {DB_PATH}: {exc}")
        st.stop()
    try:
        reviews = DossierReviewRepository(REVIEW_PATH, schema_path=SQLITE_SCHEMA, analytics_repository=repository)
        page = st.sidebar.radio("Workspace", ("Market Radar", "Discovery Engines", "Company Dossier", "Event & Liquidity", "Watchlist", "Data Operations"))
        if page == "Market Radar":
            _render_radar(repository)
        elif page == "Discovery Engines":
            _render_discovery(repository, reviews)
        elif page == "Company Dossier":
            _render_dossier(repository, reviews)
        elif page == "Event & Liquidity":
            _render_events(repository)
        elif page == "Watchlist":
            _render_watchlist(repository, reviews)
        else:
            _render_data_operations(repository)
    finally:
        try:
            reviews.close()
        except UnboundLocalError:
            pass
        repository.close()


if __name__ == "__main__":
    main()
