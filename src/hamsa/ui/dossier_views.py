"""Company Dossier and HAMSA 11 investigative workspaces for the HAMSA Terminal."""

from __future__ import annotations

from datetime import datetime
import json
import streamlit as st

from hamsa.domain.filters import FILTERS, EvidenceReference
from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.screening.data_access import (
    calendar_sessions,
    calendar_versions,
    company_input_as_of,
    known_source_documents,
    liquidity_input_as_of,
    universe_for_session,
)
from hamsa.screening.engines import evaluate_company
from hamsa.ui.theme import badge_html


def _issuer_metadata(repository, entity_id: str) -> dict[str, object]:
    con = repository._connection
    name_row = con.execute(
        """SELECT coalesce((SELECT legal_name FROM issuer_name_revision n
                            WHERE n.entity_id=i.entity_id ORDER BY effective_from DESC LIMIT 1), i.entity_id)
           FROM issuer_entity i WHERE i.entity_id=?""",
        [entity_id],
    ).fetchone()
    securities = con.execute(
        "SELECT security_id, share_class FROM equity_security WHERE issuer_entity_id=? ORDER BY security_id",
        [entity_id],
    ).fetchall()
    listings = con.execute(
        """SELECT l.listing_id, l.exchange, l.exchange_instrument_id, r.symbol, r.series,
                  r.status, r.effective_from, r.effective_to
           FROM equity_security s
           JOIN exchange_listing l USING(security_id)
           LEFT JOIN exchange_listing_revision r USING(listing_id)
           WHERE s.issuer_entity_id=?
           ORDER BY l.exchange, r.effective_from DESC""",
        [entity_id],
    ).fetchall()
    isins = con.execute(
        """SELECT i.identifier_value, i.effective_from, i.effective_to, r.review_status
           FROM equity_security s
           JOIN security_identifier_revision i USING(security_id)
           LEFT JOIN security_identifier_revision_review r
             ON r.identifier_revision_id=i.identifier_revision_id
            AND NOT EXISTS (
              SELECT 1 FROM security_identifier_revision_review n
              WHERE n.supersedes_review_id=r.review_id
            )
           WHERE s.issuer_entity_id=? AND i.identifier_type='ISIN'
           ORDER BY i.effective_from DESC""",
        [entity_id],
    ).fetchall()
    return {
        "legal_name": name_row[0] if name_row else entity_id,
        "securities": securities,
        "listings": listings,
        "isins": isins,
    }


def render_company_dossier(
    repository,
    reviews,
    session_ctx,
    thresholds,
    metric_codes,
    issuer_labels: dict[str, str],
) -> None:
    st.title("Company Intelligence Dossier")
    if not issuer_labels:
        st.info("No issuer identities are registered yet. Register and admit a security in Data & System Health.")
        return

    issuer_ids = list(issuer_labels.keys())
    default_idx = issuer_ids.index(st.session_state.get("focus_issuer_id")) if st.session_state.get("focus_issuer_id") in issuer_ids else 0
    entity_id = st.selectbox(
        "Active Company / Issuer",
        issuer_ids,
        index=default_idx,
        format_func=lambda k: issuer_labels[k],
        key="dossier_company_select",
    )
    st.session_state["focus_issuer_id"] = entity_id
    meta = _issuer_metadata(repository, entity_id)
    sources = known_source_documents(repository)

    primary_isin = meta["isins"][0][0] if meta["isins"] else "Unresolved"
    id_status = meta["isins"][0][3] if meta["isins"] else "pending"
    primary_symbol = next((r[3] for r in meta["listings"] if r[1] == "NSE" and r[3]), meta["listings"][0][3] if meta["listings"] else entity_id)
    venues_str = ", ".join(sorted({r[1] for r in meta["listings"]})) if meta["listings"] else "—"

    b_reviews = reviews.connection.execute(
        """SELECT r.* FROM issuer_business_classification_review_revision r
           WHERE r.entity_id=?
             AND NOT EXISTS (
               SELECT 1 FROM issuer_business_classification_review_revision n
               WHERE n.supersedes_review_revision_id=r.review_revision_id
             )
           ORDER BY r.valid_from, r.recorded_at""",
        (entity_id,),
    ).fetchall()
    latest_b_class = b_reviews[-1]["business_class"] if b_reviews else "unclassified"

    o1, o2, o3, o4, o5 = st.columns(5)
    o1.metric("Symbol", str(primary_symbol))
    o2.metric("ISIN", str(primary_isin))
    o3.metric("Venues", venues_str)
    o4.metric("Business Class", str(latest_b_class).title())
    o5.metric("Identity Confidence", str(id_status or "pending").title())

    with st.expander("Identity, Listings & Business Classification Ledger", expanded=False):
        st.write(" Venue-specific exchange listings:")
        st.dataframe(
            [
                {
                    "listing_id": r[0], "exchange": r[1], "instrument_id": r[2],
                    "symbol": r[3], "series": r[4], "status": r[5],
                    "effective_from": r[6], "effective_to": r[7],
                }
                for r in meta["listings"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        if b_reviews:
            st.dataframe([dict(r) for r in b_reviews], use_container_width=True, hide_index=True)
        with st.form("business_class_form"):
            st.caption("Append an evidence-backed issuer business-class review (`industrial` vs `financial`):")
            b_class_val = st.selectbox("Business class", ("industrial", "financial"))
            b_status_val = st.selectbox("Review status", ("approved", "rejected"))
            b_from = st.date_input("Applicability start date", value=None, key="b_class_from")
            b_to = st.date_input("Applicability end date (optional)", value=None, key="b_class_to")
            b_rev = st.text_input("Reviewer", key="b_class_reviewer")
            b_rat = st.text_area("Classification rationale")
            b_src_idx = st.selectbox(
                "Evidence source",
                [None, *range(len(sources))],
                key="b_class_source",
                format_func=lambda idx: "Select source" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}",
            )
            b_loc = st.text_input("Source locator", key="b_class_locator")
            if st.form_submit_button("Append business-class review"):
                try:
                    if b_from is None or b_src_idx is None:
                        raise ValueError("applicability start date and source document are required")
                    reviews.append_business_classification_review(
                        entity_id=entity_id, business_class=b_class_val,
                        valid_from=b_from.isoformat(),
                        valid_to=b_to.isoformat() if b_to else None,
                        reviewer=b_rev, rationale=b_rat,
                        source_document_id=sources[b_src_idx][0],
                        locator=b_loc, review_status=b_status_val,
                    )
                    st.success("Business-class review appended.")
                except Exception as exc:
                    st.error(f"Business-class review was not saved: {exc}")

    if session_ctx is None:
        st.info("Select an exchange calendar and session in the sidebar to inspect point-in-time financials, price/volume structure, and 5-engine analysis.")
        return

    exchange, calendar_version, session_date, mode = session_ctx
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)

    # 1. Five-Engine Analysis Section
    st.subheader("1 · Five-Engine Intelligence Analysis")
    comp_input = company_input_as_of(
        repository, issuer_entity_id=entity_id, exchange=exchange,
        session_date=session_date, availability_mode=mode,
        calendar_version=calendar_version, metric_codes=metric_codes,
        reporting_scope="consolidated_preferred", review_repository=reviews,
    )
    liq_input = liquidity_input_as_of(
        repository, issuer_entity_id=entity_id, exchange=exchange,
        session_date=session_date, availability_mode=mode,
        calendar_version=calendar_version, review_repository=reviews,
    )
    engine_results = evaluate_company(comp_input, thresholds, **liq_input)

    eng_cols = st.columns(5)
    for idx, res in enumerate(engine_results):
        with eng_cols[idx]:
            st.markdown(
                f"""
                <div class="hamsa-card" style="min-height:145px;">
                    <div style="font-size:0.78rem;color:#94a3b8;margin-bottom:4px;">ENGINE {idx+1}</div>
                    <div style="font-weight:700;margin-bottom:8px;">{res.engine.replace('_', ' ').title()}</div>
                    <div style="margin-bottom:8px;">{badge_html(res.state.value, res.state.value)}</div>
                    <div style="font-size:0.75rem;color:#94a3b8;">{len(res.source_observation_ids)} obs · {len(res.source_document_ids)} docs</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.dataframe(
        [
            {
                "Engine": item.engine,
                "State": item.state.value,
                "Formula / Gate": item.calculation_expression,
                "Evaluated Inputs": json.dumps({k: v for k, v in item.inputs.items() if k != "input_quality_states" and v is not None}, sort_keys=True),
                "Source Documents": ", ".join(item.source_document_ids[:4]),
                "Explanation": item.explanation,
            }
            for item in engine_results
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Engine Qualitative Evidence Gates · Human Review Only", expanded=False):
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
            ev_source_idx = st.selectbox(
                "Evidence source document",
                [None, *range(len(sources))],
                key="ev_source",
                format_func=lambda idx: "Select source" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}",
            )
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

    # 2. Financial Intelligence Section
    st.subheader("2 · Financial Intelligence (Point-in-Time As-Reported & Derived)")
    fin_rows = [
        row for row in repository.financial_observations_as_of(
            exchange=exchange, session_date=session_date, cutoff=cutoff,
            availability_mode=mode, calendar_version=calendar_version,
            subject_entity_id=entity_id,
        )
        if row["subject_entity_id"] == entity_id
    ]
    if not fin_rows:
        st.info(
            "Financial statements not yet available for this company as of the selected session cutoff. "
            "This prevents HAMSA from evaluating Engines 1–4 (Compounders, Earnings Inflection, Capex Conversion, and Cash Quality)."
        )
    else:
        avail_scopes = sorted({str(r["reporting_scope"]) for r in fin_rows})
        fc1, fc2 = st.columns(2)
        fin_scope = fc1.selectbox("Reporting Scope", avail_scopes, index=0, key="dossier_fin_scope")
        fin_cadence = fc2.selectbox("Period Cadence", ("Annual (>=300d)", "Quarterly (60..120d)", "All Periods"), key="dossier_fin_cadence")

        scoped_fin = [r for r in fin_rows if r["reporting_scope"] == fin_scope and r["period_start"] is not None]
        if fin_cadence.startswith("Annual"):
            filtered_fin = [r for r in scoped_fin if (r["period_end"] - r["period_start"]).days >= 300]
        elif fin_cadence.startswith("Quarterly"):
            filtered_fin = [r for r in scoped_fin if 60 <= (r["period_end"] - r["period_start"]).days <= 120]
        else:
            filtered_fin = scoped_fin

        if not filtered_fin:
            st.info(f"No {fin_cadence} observations recorded under `{fin_scope}` scope as of {session_date.isoformat()}.")
        else:
            periods = sorted({r["period_end"] for r in filtered_fin})
            by_metric_period: dict[tuple[str, object], float] = {}
            for r in filtered_fin:
                if r["quality_status"] == "observed" and r["value"] is not None:
                    val = float(r["value"])
                    if r["unit"] == "INR":
                        val = round(val / 1e7, 2)
                    else:
                        val = round(val, 2)
                    by_metric_period[(str(r["metric"]), r["period_end"])] = val

            display_metrics = [
                ("revenue", "Revenue (₹ Cr)"),
                ("ebitda", "Operating EBITDA (₹ Cr)"),
                ("operating_margin", "Operating Margin (%)"),
                ("pat", "Profit After Tax (₹ Cr)"),
                ("eps", "Basic EPS (₹)"),
                ("roce", "ROCE (%)"),
                ("cfo", "Operating Cash Flow (₹ Cr)"),
                ("capex", "Capex (₹ Cr)"),
                ("fcf", "Free Cash Flow (₹ Cr)"),
                ("gross_block", "Gross Block / PPE (₹ Cr)"),
                ("cwip", "Capital WIP (₹ Cr)"),
                ("net_worth", "Net Worth (₹ Cr)"),
                ("borrowings", "Total Borrowings (₹ Cr)"),
                ("receivables", "Trade Receivables (₹ Cr)"),
                ("inventory", "Inventories (₹ Cr)"),
                ("trade_payables", "Trade Payables (₹ Cr)"),
            ]
            pivot_rows = []
            for m_code, m_label in display_metrics:
                if any((m_code, p) in by_metric_period for p in periods):
                    row_dict: dict[str, object] = {"Metric": m_label}
                    for p in periods:
                        row_dict[p.isoformat()] = by_metric_period.get((m_code, p), None)
                    pivot_rows.append(row_dict)
            st.dataframe(pivot_rows, use_container_width=True, hide_index=True)

            # Trajectory charts for real observed series
            ch1, ch2 = st.columns(2)
            with ch1:
                rev_pat_chart = [
                    {
                        "Period": p.isoformat(),
                        "Revenue (₹ Cr)": by_metric_period.get(("revenue", p)),
                        "PAT (₹ Cr)": by_metric_period.get(("pat", p)),
                    }
                    for p in periods
                    if ("revenue", p) in by_metric_period or ("pat", p) in by_metric_period
                ]
                if rev_pat_chart:
                    st.caption("Revenue & PAT Trajectory (₹ Crore)")
                    st.bar_chart(rev_pat_chart, x="Period", y=["Revenue (₹ Cr)", "PAT (₹ Cr)"])
            with ch2:
                cf_chart = [
                    {
                        "Period": p.isoformat(),
                        "CFO (₹ Cr)": by_metric_period.get(("cfo", p)),
                        "Capex (₹ Cr)": by_metric_period.get(("capex", p)),
                        "FCF (₹ Cr)": by_metric_period.get(("fcf", p)),
                    }
                    for p in periods
                    if ("cfo", p) in by_metric_period or ("capex", p) in by_metric_period
                ]
                if cf_chart:
                    st.caption("Cash Conversion & Capex Trajectory (₹ Crore)")
                    st.bar_chart(cf_chart, x="Period", y=["CFO (₹ Cr)", "Capex (₹ Cr)", "FCF (₹ Cr)"])

    # 3. Price, Volume, Delivery & Venue Structure
    st.subheader("3 · Price, Volume, Delivery & Cross-Venue Market Structure")
    listing_rows = repository._connection.execute(
        """SELECT l.listing_id, l.exchange, l.exchange_instrument_id
           FROM exchange_listing l JOIN equity_security s USING(security_id)
           WHERE s.issuer_entity_id=? ORDER BY l.exchange""",
        [entity_id],
    ).fetchall()

    venue_dispositions = {}
    for l_id, venue, _ in listing_rows:
        if venue == exchange:
            venue_dispositions[l_id] = repository.derive_universe_disposition(
                listing_id=l_id, observation_date=session_date, cutoff=cutoff,
                availability_mode=mode, calendar_version=calendar_version,
            )
    st.caption(f"Listing eligibility on {exchange} @ {session_date.isoformat()}: {venue_dispositions}")

    active_listing_id = next(
        (l_id for l_id, disp in venue_dispositions.items() if disp == "eligible_mainboard_ordinary_equity"),
        None,
    )
    if active_listing_id is None:
        st.info("No eligible listing on this venue for the selected session; EOD price/delivery series are withheld.")
    else:
        recent_days = [d for d in calendar_sessions(repository, exchange, calendar_version) if d <= session_date][-60:]
        eod_series = []
        for day in recent_days:
            p_rows = repository.eod_observations_as_of(
                exchange=exchange, trade_date=day, cutoff=cutoff,
                availability_mode=mode, calendar_version=calendar_version,
                listing_id=active_listing_id,
            )
            d_rows = repository.delivery_observations_as_of(
                exchange=exchange, trade_date=day, cutoff=cutoff,
                availability_mode=mode, calendar_version=calendar_version,
                listing_id=active_listing_id,
            )
            if len(p_rows) == 1:
                pr = p_rows[0]
                dr = d_rows[0] if len(d_rows) == 1 else {}
                eod_series.append({
                    "Date": day.isoformat(),
                    "Close (₹)": float(pr["close"]) if pr["close"] is not None else None,
                    "Volume": int(pr["volume"]) if pr["volume"] is not None else 0,
                    "Turnover (₹ Cr)": round(float(pr["turnover"]) / 1e7, 2) if pr["turnover"] is not None else 0.0,
                    "Delivery (%)": round(float(dr["delivery_percentage"]), 2) if dr.get("delivery_percentage") is not None else None,
                    "Source": pr["source_document_id"],
                })
        if eod_series:
            pc1, pc2 = st.columns(2)
            with pc1:
                st.caption(f"{exchange} Close Price Trajectory (Trailing {len(eod_series)} Sessions)")
                st.line_chart(eod_series, x="Date", y="Close (₹)")
            with pc2:
                st.caption(f"{exchange} Traded Turnover (₹ Cr) & Delivery %")
                st.bar_chart(eod_series, x="Date", y="Turnover (₹ Cr)")
            with st.expander("Trailing Session EOD & Delivery Ledger", expanded=False):
                st.dataframe(list(reversed(eod_series)), use_container_width=True, hide_index=True)

    actions = repository.corporate_action_events_as_of(
        exchange=exchange, session_date=session_date, cutoff=cutoff,
        availability_mode=mode, calendar_version=calendar_version, issuer_entity_id=entity_id,
    )
    with st.expander(f"Point-in-Time Corporate-Action Filings ({len(actions)})", expanded=bool(actions)):
        st.dataframe(actions, use_container_width=True, hide_index=True)

    # 4. Business Thesis & Hypothesis Ledger
    st.subheader("4 · Business Thesis & Pre-Mortem Ledger")
    note = reviews.latest_company_research_note(entity_id)
    if note:
        st.markdown(
            f"""
            <div class="hamsa-card">
                <div><strong>Business Thesis:</strong> {note['business_thesis']}</div>
                <div style="margin-top:6px;color:#f87171;"><strong>What Kills It (Pre-Mortem):</strong> {note['thesis_killers']}</div>
                <div style="margin-top:6px;font-size:0.80rem;color:#94a3b8;">
                    Reviewer: {note['reviewer']} · Recorded: {note['recorded_at']} · Next Checkpoint: {note['next_review_date'] or 'Not set'}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.dataframe([dict(row) for row in reviews.company_research_note_evidence(note["note_revision_id"])], use_container_width=True, hide_index=True)
    with st.expander("Append Sourced Company Thesis Revision", expanded=False):
        with st.form("company_thesis_form"):
            thesis = st.text_area("Business thesis (sourced facts and explicit hypotheses)", value=note["business_thesis"] if note else "")
            killers = st.text_area("Thesis killers / what would invalidate the business case", value=note["thesis_killers"] if note else "")
            next_review = st.date_input("Next review date (optional)", value=None)
            reviewer = st.text_input("Reviewer", key="thesis_reviewer")
            note_source_index = st.selectbox(
                "Evidence source",
                [None, *range(len(sources))],
                key="thesis_source",
                format_func=lambda idx: "Select a registered source document" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}",
            )
            note_locator = st.text_input("Source locator", key="thesis_locator")
            note_evidence = st.text_input("What this source supports", key="thesis_evidence")
            if st.form_submit_button("Append thesis revision"):
                try:
                    if note_source_index is None:
                        raise ValueError("a thesis revision requires at least one registered source citation")
                    src = sources[note_source_index]
                    evidence = (EvidenceReference(src[0], src[1], src[2], note_locator, note_evidence),)
                    reviews.append_company_research_note(
                        entity_id=entity_id, business_thesis=thesis,
                        thesis_killers=killers, reviewer=reviewer,
                        next_review_date=next_review.isoformat() if next_review else None,
                        evidence=evidence,
                    )
                    st.success("Thesis revision appended.")
                except Exception as exc:
                    st.error(f"Thesis was not saved: {exc}")


def render_hamsa_11(repository, reviews, session_ctx, issuer_labels: dict[str, str]) -> None:
    st.title("HAMSA 11 · Investigative Filter Workbench")
    st.caption(
        "The 11 analytical lenses are investigative tools for human judgment—never an automated checklist or numerical score. "
        "Pass and Fail assessments require cited analytical source documents; unknown remains explicitly Unproven."
    )
    if not issuer_labels:
        st.info("No issuer identities are registered yet.")
        return

    issuer_ids = list(issuer_labels.keys())
    default_idx = issuer_ids.index(st.session_state.get("focus_issuer_id")) if st.session_state.get("focus_issuer_id") in issuer_ids else 0
    entity_id = st.selectbox(
        "Company Under Investigation",
        issuer_ids,
        index=default_idx,
        format_func=lambda k: issuer_labels[k],
        key="h11_company_select",
    )
    st.session_state["focus_issuer_id"] = entity_id

    state = reviews.current_reviews(entity_id)
    pass_cnt = sum(1 for r in state.values() if r["status"] == "Pass")
    fail_cnt = sum(1 for r in state.values() if r["status"] == "Fail")
    unproven_cnt = len(FILTERS) - pass_cnt - fail_cnt

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Filters Evaluated", f"{len(state)} / {len(FILTERS)}")
    s2.metric("Pass (Evidenced)", pass_cnt)
    s3.metric("Unproven (Unknowns Remain)", unproven_cnt)
    s4.metric("Fail (Thesis Risk)", fail_cnt)

    # 11-Filter Overview Matrix
    overview_rows = []
    for fdef in FILTERS:
        curr = state.get(fdef.key.value)
        ev_rows = reviews.evidence_for(curr["review_id"]) if curr else []
        overview_rows.append({
            "Filter": fdef.name,
            "Analytical Prompt": fdef.prompt,
            "Status": curr["status"] if curr else "Unproven",
            "Reviewer": curr["reviewer"] if curr else "—",
            "Reviewed At": curr["reviewed_at"][:19] if curr else "—",
            "Citations": len(ev_rows),
            "Rationale / What Remains Unknown": curr["rationale"] if curr else "Unreviewed: requires source-cited human investigation.",
        })
    st.dataframe(overview_rows, use_container_width=True, hide_index=True)

    st.subheader("Inspect & Record Filter Assessment")
    selected_filter = st.selectbox("Select Filter Lens", FILTERS, format_func=lambda item: f"{item.name} — {item.prompt}")
    current = state.get(selected_filter.key.value)
    if current:
        st.markdown(
            f"""
            <div class="hamsa-card">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <strong>{selected_filter.name} · Current Human Assessment</strong>
                    {badge_html(current['status'], current['status'])}
                </div>
                <div style="margin-top:6px;">{current['rationale']}</div>
                <div style="margin-top:6px;font-size:0.80rem;color:#94a3b8;">
                    Reviewed by {current['reviewer']} at {current['reviewed_at']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        ev_list = [dict(row) for row in reviews.evidence_for(current["review_id"])]
        if ev_list:
            st.dataframe(ev_list, use_container_width=True, hide_index=True)
    else:
        st.warning(f"**{selected_filter.name}** is currently **Unproven** for this company. No source-cited assessment has been recorded yet.")

    sources = known_source_documents(repository)
    with st.form("filter_review_form"):
        status = st.selectbox("Assessment", ("Unproven", "Pass", "Fail"), index=0)
        reviewer = st.text_input("Reviewer", key="filter_reviewer")
        rationale = st.text_area("Evidence-backed rationale / what remains unproven")
        source_index = st.selectbox(
            "Evidence source (required for Pass/Fail; optional for Unproven)",
            [None, *range(len(sources))],
            format_func=lambda idx: "No source citation" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}",
        )
        locator = st.text_input("Source page / section / XBRL tag / row locator")
        evidence_note = st.text_input("What this source supports")
        if st.form_submit_button("Append Hamsa 11 review"):
            try:
                evidence = ()
                if source_index is not None:
                    if not locator.strip() or not evidence_note.strip():
                        raise ValueError("source citation requires locator and support note")
                    src = sources[source_index]
                    evidence = (EvidenceReference(src[0], src[1], src[2], locator.strip(), evidence_note.strip()),)
                reviews.append_review(
                    entity_id=entity_id, filter_key=selected_filter.key.value,
                    status=status, reviewer=reviewer, rationale=rationale, evidence=evidence,
                )
                st.success("Review appended. Earlier reviews and citations remain preserved in history.")
            except Exception as exc:
                st.error(f"Review was not saved: {exc}")

    with st.expander("Append-Only Filter Review History", expanded=False):
        history = reviews.history(entity_id, selected_filter.key.value)
        st.dataframe([dict(row) for row in history], use_container_width=True, hide_index=True)
