"""Market Radar and Opportunity Radar workspaces for the HAMSA Intelligence Terminal."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import streamlit as st

from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.screening.data_access import (
    company_input_as_of,
    liquidity_input_as_of,
    market_radar_snapshot,
    source_freshness,
    universe_for_session,
)
from hamsa.screening.engines import EvaluationState, evaluate_company
from hamsa.ui.theme import badge_html


ENGINE_NAMES = (
    "compounders",
    "earnings_inflection",
    "capex_conversion",
    "cash_quality",
    "extreme_sell_side_liquidity",
)


def render_market_radar(repository, reviews, session_ctx, thresholds, issuer_labels: dict[str, str]) -> None:
    st.title("Market Radar")
    st.caption(
        "Primary intelligence landing screen · NSE/BSE mainboard ordinary-equity activity, "
        "liquidity dislocations, cross-venue blocks, and active engine discoveries."
    )
    freshness = source_freshness(repository)
    schema_v = repository._connection.execute(
        "SELECT current_version FROM schema_metadata WHERE schema_name='hamsa_analytics'"
    ).fetchone()[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("NSE EOD Freshness", freshness["NSE"].isoformat() if freshness["NSE"] else "No EOD observations")
    m2.metric("BSE EOD Freshness", freshness["BSE"].isoformat() if freshness["BSE"] else "No EOD observations")
    m3.metric("Analytical Schema", f"v{schema_v}")
    m4.metric("Watchlist Queue", len(reviews.watchlist()))

    if session_ctx is None:
        st.info("Select an imported exchange calendar and EOD session in the sidebar to activate Market Radar.")
        return

    exchange, version, session_date, mode = session_ctx
    universe = universe_for_session(
        repository, exchange=exchange, session_date=session_date,
        availability_mode=mode, calendar_version=version,
    )
    counts: dict[str, int] = {}
    for row in universe:
        counts[str(row["disposition"])] = counts.get(str(row["disposition"]), 0) + 1

    u1, u2, u3, u4, u5, u6 = st.columns(6)
    u1.metric("Listings Observed", len(universe))
    u2.metric("Eligible Mainboard", counts.get("eligible_mainboard_ordinary_equity", 0))
    u3.metric("Unresolved", counts.get("unresolved_classification", 0))
    u4.metric("SME Excluded", counts.get("excluded_sme", 0))
    u5.metric("Non-Equity Excluded", counts.get("excluded_non_equity", 0))
    u6.metric("Inactive Excluded", counts.get("excluded_inactive_non_trading", 0))

    if counts.get("eligible_mainboard_ordinary_equity", 0) == 0:
        st.warning("No eligible mainboard listings exist for this session. Inspect universe dispositions below:")
        st.dataframe(universe, use_container_width=True, hide_index=True)
        return

    snap = market_radar_snapshot(
        repository, exchange=exchange, session_date=session_date,
        availability_mode=mode, calendar_version=version,
        review_repository=reviews, thresholds=thresholds,
    )

    b1, b2, b3, b4, b5 = st.columns(5)
    b1.metric("Session Regime", str(snap["regime"]))
    b2.metric("Breadth (Adv / Dec / Unch)", f"{snap['advancers']} / {snap['decliners']} / {snap['unchanged']}")
    b3.metric(f"{exchange} Eligible Turnover", f"₹{snap['total_turnover_cr']:,.1f} Cr")
    b4.metric("Engine Discoveries", len(snap["discoveries"]))
    b5.metric("Liquidity Dislocations", len(snap["dislocations"]))

    st.subheader("1 · Active Engine Discoveries (Triggered Signals)")
    if snap["discoveries"]:
        disc_rows = [
            {
                "Symbol": r["symbol"],
                "Company": r["company_name"],
                "Triggered Engines": r["triggered_engines"],
                "Triggers": r["triggered_count"],
                "Close (₹)": r["close"],
                "1D Return (%)": r["ret_1d_pct"],
                "20D Drawdown (%)": r["drawdown_20d_pct"],
                "Vol Multiple (x)": r["volume_multiple"],
                "Delivery (%)": r["delivery_pct"],
                "Turnover (₹ Cr)": r["turnover_cr"],
            }
            for r in snap["discoveries"]
        ]
        st.dataframe(disc_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No eligible company triggered an engine threshold on this session.")

    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("2 · Sell-Side Dislocations & Cross-Venue Blocks")
        if snap["dislocations"]:
            st.dataframe(
                [
                    {
                        "Symbol": r["symbol"],
                        "20D DD (%)": r["drawdown_20d_pct"],
                        "1D Ret (%)": r["ret_1d_pct"],
                        "Vol Mult (x)": r["volume_multiple"],
                        "Deliv (%)": r["delivery_pct"],
                        "Deliv Δ (pp)": r["delivery_chg_pp"],
                        f"{exchange} Turn (Cr)": r["turnover_cr"],
                        "Other Venue (Cr)": r["other_venue_turnover_cr"],
                    }
                    for r in snap["dislocations"]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No drawdown dislocations met the volume/delivery/cross-venue activity filters on this session.")

    with col_right:
        st.subheader("3 · Volume Expansion & Delivery Accumulation")
        anomalies = snap["volume_anomalies"][:8] or snap["delivery_anomalies"][:8]
        if anomalies:
            st.dataframe(
                [
                    {
                        "Symbol": r["symbol"],
                        "Vol Mult (x)": r["volume_multiple"],
                        "Deliv (%)": r["delivery_pct"],
                        "Deliv Δ (pp)": r["delivery_chg_pp"],
                        "1D Ret (%)": r["ret_1d_pct"],
                        "Range Pos": r["close_range_pos"],
                        "Turn (Cr)": r["turnover_cr"],
                    }
                    for r in anomalies
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No unusual volume or delivery anomalies on this session.")

    with st.expander("Full Session Universe & Disposition Table", expanded=False):
        st.dataframe(universe, use_container_width=True, hide_index=True)


def render_opportunity_radar(repository, reviews, session_ctx, thresholds, metric_codes, issuer_labels: dict[str, str]) -> None:
    st.title("Opportunity Radar")
    st.caption(
        "Five-Engine Discovery Workbench · Every signal exposes its exact formula, evaluated inputs, "
        "missing evidence gates, and source lineage. Never a buy/sell recommendation."
    )
    if session_ctx is None:
        st.warning("A verified, explicitly selected exchange calendar is required before any historical screen can run.")
        return

    exchange, version, session_date, mode = session_ctx
    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
    view_mode = c1.selectbox(
        "Engine View",
        ("all_engines", *ENGINE_NAMES),
        format_func=lambda x: "All 5 Engines (Combined Matrix)" if x == "all_engines" else x.replace("_", " ").title(),
    )
    reporting_scope = c2.selectbox(
        "Financial Reporting Scope",
        ("consolidated_preferred", "consolidated", "standalone"),
        format_func=lambda s: "Consolidated (fallback Standalone)" if s == "consolidated_preferred" else s.title(),
    )
    state_filter = c3.selectbox(
        "Filter by State",
        ("all", "triggered", "unproven", "not_triggered", "blocked"),
        format_func=lambda s: "All States" if s == "all" else s.replace("_", " ").upper(),
    )
    search_query = c4.text_input("Search Symbol / Company / ISIN", placeholder="e.g. RATEGAIN, POLYCAB, TRENT")

    listings = universe_for_session(
        repository, exchange=exchange, session_date=session_date,
        availability_mode=mode, calendar_version=version,
    )
    eligible = [row for row in listings if row["disposition"] == "eligible_mainboard_ordinary_equity"]
    if not eligible:
        st.info("There are no evidence-qualified mainboard issuers for this session. Unresolved and excluded records are not screened.")
        return

    by_issuer_listing = {str(r["issuer_entity_id"]): r for r in eligible}
    issuers = sorted(by_issuer_listing.keys())
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)

    matrix_rows: list[dict[str, object]] = []
    detailed_by_issuer: dict[str, dict[str, object]] = {}

    for issuer_id in issuers:
        l_row = by_issuer_listing[issuer_id]
        sym = str(l_row.get("symbol") or l_row.get("exchange_instrument_id") or issuer_id)
        label = issuer_labels.get(issuer_id, sym)
        if search_query.strip():
            q = search_query.strip().lower()
            if q not in sym.lower() and q not in label.lower() and q not in issuer_id.lower():
                continue

        b_class = reviews.business_class_as_of(
            entity_id=issuer_id, session_date=session_date, cutoff=cutoff,
            exchange=exchange, availability_mode=mode, calendar_version=version,
        )
        company = company_input_as_of(
            repository, issuer_entity_id=issuer_id, exchange=exchange,
            session_date=session_date, availability_mode=mode, calendar_version=version,
            metric_codes=metric_codes, business_class=b_class,
            reporting_scope=reporting_scope, review_repository=reviews,
        )
        liq = liquidity_input_as_of(
            repository, issuer_entity_id=issuer_id, exchange=exchange,
            session_date=session_date, availability_mode=mode, calendar_version=version,
            review_repository=reviews, eligible_listing_id=str(l_row["listing_id"]),
        )
        all_results = evaluate_company(company, thresholds, **liq)
        by_eng = {r.engine: r for r in all_results}
        trig_count = sum(r.state == EvaluationState.TRIGGERED for r in all_results)
        if trig_count >= 2 and all(r.state not in (EvaluationState.UNPROVEN, EvaluationState.BLOCKED) for r in all_results):
            triage = "research_priority"
        elif trig_count >= 2:
            triage = "multi_signal"
        elif trig_count == 1:
            triage = "new_signal"
        else:
            triage = "no_trigger"

        if view_mode != "all_engines":
            chosen = by_eng[view_mode]
            if state_filter != "all" and chosen.state.value != state_filter:
                continue
            matrix_rows.append({
                "issuer_entity_id": issuer_id,
                "symbol": sym,
                "company": label,
                "scope": company.reporting_scope,
                "engine": view_mode,
                "engine_state": chosen.state.value,
                "research_triage": triage,
                "calculation": chosen.calculation_expression,
                "inputs": json.dumps(chosen.inputs, sort_keys=True),
                "source_document_ids": ", ".join(chosen.source_document_ids[:4]),
                "explanation": chosen.explanation,
            })
        else:
            if state_filter == "triggered" and trig_count == 0:
                continue
            if state_filter != "all" and state_filter != "triggered":
                if not any(r.state.value == state_filter for r in all_results):
                    continue
            c_in = by_eng["compounders"].inputs
            ei_in = by_eng["earnings_inflection"].inputs
            cq_in = by_eng["cash_quality"].inputs
            el_in = by_eng["extreme_sell_side_liquidity"].inputs
            matrix_rows.append({
                "issuer_entity_id": issuer_id,
                "symbol": sym,
                "company": label,
                "scope": company.reporting_scope,
                "triage": triage,
                "triggers": trig_count,
                "compounders": by_eng["compounders"].state.value,
                "earnings_inflection": by_eng["earnings_inflection"].state.value,
                "capex_conversion": by_eng["capex_conversion"].state.value,
                "cash_quality": by_eng["cash_quality"].state.value,
                "extreme_liquidity": by_eng["extreme_sell_side_liquidity"].state.value,
                "3Y Sales CAGR": f"{float(c_in['sales_cagr_3y'])*100:.1f}%" if c_in.get("sales_cagr_3y") else "—",
                "3Y PAT CAGR": f"{float(c_in['pat_cagr_3y'])*100:.1f}%" if c_in.get("pat_cagr_3y") else "—",
                "ROCE (%)": f"{float(c_in['latest_roce']):.1f}%" if c_in.get("latest_roce") else "—",
                "Qtr YoY Sales": f"{float(ei_in['sales_growth_yoy'])*100:+.1f}%" if ei_in.get("sales_growth_yoy") else "—",
                "3Y CFO/PAT": f"{float(cq_in['cfo_pat_ratio_3y']):.2f}x" if cq_in.get("cfo_pat_ratio_3y") else "—",
                "Vol Mult (x)": f"{float(el_in['volume_multiple']):.2f}x" if el_in.get("volume_multiple") else "—",
                "Deliv (%)": f"{float(el_in['delivery_percentage']):.1f}%" if el_in.get("delivery_percentage") else "—",
            })

        detailed_by_issuer[issuer_id] = {
            "symbol": sym,
            "label": label,
            "scope": company.reporting_scope,
            "triage": triage,
            "results": all_results,
        }

    st.dataframe(matrix_rows, use_container_width=True, hide_index=True)

    if detailed_by_issuer:
        st.subheader("Why Did This Company Appear? · Signal & Evidence Inspector")
        avail_ids = list(detailed_by_issuer.keys())
        default_idx = avail_ids.index(st.session_state.get("focus_issuer_id")) if st.session_state.get("focus_issuer_id") in avail_ids else 0
        inspected_id = st.selectbox(
            "Select company to inspect trigger details and source evidence",
            avail_ids,
            index=default_idx,
            format_func=lambda k: f"{detailed_by_issuer[k]['symbol']} · {detailed_by_issuer[k]['label']} ({detailed_by_issuer[k]['triage']})",
        )
        st.session_state["focus_issuer_id"] = inspected_id
        detail = detailed_by_issuer[inspected_id]

        for res in detail["results"]:
            badge = badge_html(res.state.value, res.state.value)
            clean_inputs = {k: v for k, v in res.inputs.items() if k != "input_quality_states" and v is not None}
            st.markdown(
                f"""
                <div class="hamsa-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                        <strong>{res.engine.replace('_', ' ').upper()}</strong>
                        {badge}
                    </div>
                    <div style="font-size:0.84rem;color:#94a3b8;margin-bottom:6px;">
                        <strong>Rule:</strong> <code>{res.calculation_expression}</code>
                    </div>
                    <div style="font-size:0.82rem;margin-bottom:4px;">
                        <strong>Evaluated Inputs:</strong> <code>{json.dumps(clean_inputs, sort_keys=True)}</code>
                    </div>
                    <div style="font-size:0.80rem;color:#94a3b8;">
                        <strong>Note:</strong> {res.explanation} &nbsp;|&nbsp;
                        <strong>Sources:</strong> {len(res.source_document_ids)} docs, {len(res.source_observation_ids)} observations
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        act1, act2 = st.columns(2)
        with act1:
            with st.form("opp_quick_watchlist_form"):
                w_status = st.selectbox("Quick Watchlist Action", ("research_priority", "watch", "cooling", "rejected"))
                w_rev = st.text_input("Analyst", value="hamsa-analyst", key="opp_w_rev")
                w_rat = st.text_input("Investigation hypothesis / reason", value=f"Surfaced in Opportunity Radar ({detail['triage']}) on {session_date.isoformat()}")
                if st.form_submit_button(f"Add / Update {detail['symbol']} on Watchlist"):
                    try:
                        reviews.append_watchlist_event(
                            entity_id=inspected_id, status=w_status, reviewer=w_rev, rationale=w_rat,
                        )
                        st.success(f"Updated {detail['symbol']} on Watchlist as {w_status}.")
                    except Exception as exc:
                        st.error(f"Watchlist update failed: {exc}")
        with act2:
            target_engine = view_mode if view_mode != "all_engines" else "compounders"
            if st.button(f"Persist {target_engine.replace('_', ' ').title()} Screen Run to Analytical Ledger"):
                try:
                    run_key = f"{target_engine}|{exchange}|{session_date.isoformat()}|{mode}|{version}|{datetime.now().isoformat()}"
                    run_id = "run-" + sha256(run_key.encode("utf-8")).hexdigest()[:24]
                    run_results = []
                    for iss_k, d_obj in detailed_by_issuer.items():
                        eng_res = next(r for r in d_obj["results"] if r.engine == target_engine)
                        res_id = "sres-" + sha256(f"{run_id}|{iss_k}".encode("utf-8")).hexdigest()[:24]
                        run_results.append({
                            "result_id": res_id,
                            "subject_entity_id": iss_k,
                            "calculation_expression": eng_res.calculation_expression,
                            "inputs": eng_res.inputs,
                            "result": eng_res.state.value,
                            "explanation": eng_res.explanation,
                            "source_document_ids": eng_res.source_document_ids,
                            "source_observation_ids": eng_res.source_observation_ids,
                        })
                    repository.append_screen_run(
                        run_id=run_id, engine=target_engine, profile_id="hamsa-terminal-ind",
                        profile_version="v1", business_class="industrial",
                        configuration={"scope": reporting_scope},
                        venue_policy_id=f"venue-{exchange.lower()}", venue_policy_version="v1",
                        primary_exchange=exchange, as_of_session=session_date, cutoff=cutoff,
                        availability_mode=mode, exchange_calendar_version=version,
                        code_version="0.1.0", created_by="hamsa-analyst", results=run_results,
                    )
                    st.success(f"Recorded immutable screen run {run_id} ({len(run_results)} results).")
                except Exception as exc:
                    st.error(f"Screen run not saved: {exc}")
