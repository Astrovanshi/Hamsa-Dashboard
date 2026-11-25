"""Discovery Feed, Watchlist & Investigation, and Data & System Health views."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import streamlit as st

from hamsa.domain.filters import EvidenceReference
from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.screening.data_access import (
    calendar_sessions,
    calendar_versions,
    discovery_feed_as_of,
    financial_coverage_matrix,
    known_source_documents,
    universe_for_session,
)
from hamsa.ui.theme import badge_html


def render_discovery_feed(repository, reviews, session_ctx, thresholds, issuer_labels: dict[str, str]) -> None:
    st.title("Discovery Feed · Chronological Intelligence Stream")
    st.caption(
        "Prioritizes high-signal developments: engine triggers, high-delivery liquidity dislocations, "
        "corporate-action filings, and research watchlist updates."
    )
    if session_ctx is None:
        st.info("An explicit venue calendar is required before event availability or liquidity history can be selected.")
        return

    exchange, version, session_date, mode = session_ctx
    cutoff = datetime.combine(session_date, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
    feed = discovery_feed_as_of(
        repository, exchange=exchange, session_date=session_date,
        availability_mode=mode, calendar_version=version,
        review_repository=reviews, thresholds=thresholds,
    )

    fc1, fc2 = st.columns(2)
    categories = ["All Categories", *sorted({str(item["category"]) for item in feed})]
    selected_cat = fc1.selectbox("Filter by Event Category", categories)
    feed_search = fc2.text_input("Filter by Symbol / Keyword", placeholder="e.g. RATEGAIN, TRENT, Trigger")

    filtered = feed
    if selected_cat != "All Categories":
        filtered = [item for item in filtered if item["category"] == selected_cat]
    if feed_search.strip():
        q = feed_search.strip().lower()
        filtered = [
            item for item in filtered
            if q in str(item["symbol"]).lower()
            or q in str(item["company_name"]).lower()
            or q in str(item["what_happened"]).lower()
            or q in str(item["category"]).lower()
        ]

    st.metric("Intelligence Events Surfaced", len(filtered))
    if filtered:
        st.dataframe(
            [
                {
                    "When": item["event_date"],
                    "Category": item["category"],
                    "Symbol": item["symbol"],
                    "Company": item["company_name"],
                    "What Happened": item["what_happened"],
                    "Why It Matters": item["why_it_matters"],
                    "What Changed": item["what_changed"],
                    "Underlying Source": item["source"],
                }
                for item in filtered
            ],
            use_container_width=True,
            hide_index=True,
        )
        for item in filtered[:12]:
            st.markdown(
                f"""
                <div class="hamsa-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <div><strong>{item['symbol']} · {item['company_name']}</strong> &nbsp;—&nbsp; <span style="color:#94a3b8">{item['event_date']}</span></div>
                        {badge_html(str(item['category']), str(item['severity']))}
                    </div>
                    <div style="margin-bottom:4px;"><strong>What Happened:</strong> {item['what_happened']}</div>
                    <div style="font-size:0.84rem;color:#94a3b8;margin-bottom:4px;"><strong>Why It Matters:</strong> {item['why_it_matters']}</div>
                    <div style="font-size:0.80rem;color:#cbd5e1;">
                        <strong>What Changed:</strong> <code>{item['what_changed']}</code> &nbsp;|&nbsp;
                        <strong>Source:</strong> <code>{item['source']}</code>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("No intelligence events matched the current filters for this session.")

    with st.expander("Venue-Specific EOD & Delivery Liquidity Ledger (Trailing 20 Sessions)", expanded=False):
        universe = universe_for_session(
            repository, exchange=exchange, session_date=session_date,
            availability_mode=mode, calendar_version=version,
        )
        eligible_listings = {row["listing_id"] for row in universe if row["disposition"] == "eligible_mainboard_ordinary_equity"}
        sessions = [d for d in calendar_sessions(repository, exchange, version) if d <= session_date][-10:]
        liquidity_rows = []
        for day in sessions:
            day_cutoff = datetime.combine(day, datetime.min.time(), tzinfo=MARKET_TIMEZONE).replace(hour=15, minute=30)
            prices = repository.eod_observations_as_of(
                exchange=exchange, trade_date=day, cutoff=day_cutoff,
                availability_mode=mode, calendar_version=version,
            )
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
                liquidity_rows.append({
                    "session": day,
                    "exchange": exchange,
                    "listing_id": price["listing_id"],
                    "close_raw": price["close"],
                    "volume_raw": price["volume"],
                    "delivery_quantity": drow.get("delivery_quantity"),
                    "delivery_percentage": drow.get("delivery_percentage"),
                    "price_source": price["source_document_id"],
                })
        if liquidity_rows:
            st.dataframe(liquidity_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No source-backed, eligible listing EOD rows are present for these sessions.")


def render_watchlist(repository, reviews, issuer_labels: dict[str, str]) -> None:
    st.title("Watchlist & Investigation Queue")
    st.caption(
        "User-controlled research queue for tracking hypotheses, thesis killers, and review checkpoints. "
        "Watchlist membership is an investigation priority—never a buy/sell instruction."
    )
    entries = reviews.watchlist()
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Total Tracked Companies", len(entries))
    w2.metric("Research Priority", sum(1 for r in entries if r["status"] == "research_priority"))
    w3.metric("Active Watch", sum(1 for r in entries if r["status"] == "watch"))
    w4.metric("Cooling / Rejected", sum(1 for r in entries if r["status"] in ("cooling", "rejected")))

    enriched = []
    for row in entries:
        ent_id = str(row["entity_id"])
        note = reviews.latest_company_research_note(ent_id)
        f_state = reviews.current_reviews(ent_id)
        pass_c = sum(1 for v in f_state.values() if v["status"] == "Pass")
        fail_c = sum(1 for v in f_state.values() if v["status"] == "Fail")
        enriched.append({
            "entity_id": ent_id,
            "company": issuer_labels.get(ent_id, ent_id),
            "status": row["status"],
            "reviewer": row["reviewer"],
            "recorded_at": row["recorded_at"][:19],
            "rationale": row["rationale"],
            "business_thesis": note["business_thesis"] if note else "No thesis note recorded yet",
            "what_kills_it": note["thesis_killers"] if note else "—",
            "next_checkpoint": note["next_review_date"] if note else "—",
            "hamsa_11_summary": f"{pass_c} Pass · {fail_c} Fail · {11 - pass_c - fail_c} Unproven",
        })
    st.dataframe(enriched, use_container_width=True, hide_index=True)

    if not issuer_labels:
        st.info("No issuer identities are registered yet.")
        return

    c_left, c_right = st.columns(2)
    with c_left:
        st.subheader("Update Investigation Status")
        with st.form("watchlist_form"):
            entity_id = st.selectbox("Company / issuer", list(issuer_labels), format_func=lambda key: issuer_labels[key])
            status = st.selectbox("Workflow status", ("watch", "research_priority", "cooling", "rejected"))
            reviewer = st.text_input("Reviewer", key="watch_reviewer")
            rationale = st.text_area("Why this state changed / what needs confirmation")
            if st.form_submit_button("Append watchlist event"):
                try:
                    reviews.append_watchlist_event(entity_id=entity_id, status=status, reviewer=reviewer, rationale=rationale)
                    st.session_state["focus_issuer_id"] = entity_id
                    st.success("Watchlist event appended.")
                except Exception as exc:
                    st.error(f"Watchlist event was not saved: {exc}")

    with c_right:
        st.subheader("Record Hypothesis & What Needs Confirmation")
        sources = known_source_documents(repository)
        with st.form("watchlist_hypothesis_form"):
            h_entity = st.selectbox("Target Company", list(issuer_labels), format_func=lambda key: issuer_labels[key], key="wh_entity")
            h_thesis = st.text_area("Hypothesis & supporting observations")
            h_killers = st.text_area("What needs confirmation / what kills the thesis")
            h_next = st.date_input("Next review checkpoint (optional)", value=None, key="wh_next")
            h_rev = st.text_input("Reviewer", key="wh_rev")
            h_src_idx = st.selectbox(
                "Supporting source document",
                [None, *range(len(sources))],
                key="wh_src",
                format_func=lambda idx: "Select source document" if idx is None else f"{sources[idx][3]} · {sources[idx][1]}",
            )
            h_loc = st.text_input("Source locator", key="wh_loc")
            h_note = st.text_input("Citation note", key="wh_note")
            if st.form_submit_button("Append hypothesis note"):
                try:
                    if h_src_idx is None:
                        raise ValueError("a hypothesis note requires a registered source citation")
                    src = sources[h_src_idx]
                    ev = (EvidenceReference(src[0], src[1], src[2], h_loc, h_note),)
                    reviews.append_company_research_note(
                        entity_id=h_entity, business_thesis=h_thesis, thesis_killers=h_killers,
                        reviewer=h_rev, next_review_date=h_next.isoformat() if h_next else None, evidence=ev,
                    )
                    st.success("Hypothesis note appended.")
                except Exception as exc:
                    st.error(f"Hypothesis note was not saved: {exc}")


def render_data_health(repository, reviews, session_ctx, admission_renderer) -> None:
    st.title("Data & System Health")
    st.caption(
        "Exposes source provenance, financial & market coverage, quarantine diagnostics, "
        "and why any engine is silent (no opportunity vs. missing data vs. insufficient history vs. missing human evidence)."
    )
    con = repository._connection
    tables = (
        "issuer_entity",
        "equity_security",
        "exchange_listing",
        "source_document_revision",
        "exchange_trading_session",
        "eod_price_observation_revision",
        "delivery_observation_revision",
        "financial_observation_revision",
        "observation_quarantine",
        "listing_classification_snapshot",
    )
    counts = {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    d1, d2, d3, d4, d5, d6 = st.columns(6)
    d1.metric("Registered Issuers", counts["issuer_entity"])
    d2.metric("Source Documents", counts["source_document_revision"])
    d3.metric("EOD Price Rows", f"{counts['eod_price_observation_revision']:,}")
    d4.metric("Delivery Rows", f"{counts['delivery_observation_revision']:,}")
    d5.metric("Financial Rows", f"{counts['financial_observation_revision']:,}")
    d6.metric("Quarantined Rows", f"{counts['observation_quarantine']:,}")

    st.subheader("1 · Financial Coverage & Engine-Silence Diagnosis Matrix")
    if session_ctx is not None:
        exchange, version, session_date, mode = session_ctx
        cov = financial_coverage_matrix(
            repository, review_repository=reviews, exchange=exchange,
            session_date=session_date, availability_mode=mode, calendar_version=version,
        )
    else:
        cov = financial_coverage_matrix(repository, review_repository=reviews)

    if cov:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Compounders Ready", f"{sum(1 for r in cov if r['compounders_ready'])} / {len(cov)}")
        c2.metric("Earnings Inflection Ready", f"{sum(1 for r in cov if r['earnings_inflection_ready'])} / {len(cov)}")
        c3.metric("Capex Conversion Ready", f"{sum(1 for r in cov if r['capex_conversion_ready'])} / {len(cov)}")
        c4.metric("Cash Quality Ready", f"{sum(1 for r in cov if r['cash_quality_ready'])} / {len(cov)}")
        st.dataframe(cov, use_container_width=True, hide_index=True)
    else:
        st.info("No issuers registered yet; financial coverage matrix is empty.")

    col_q, col_p = st.columns(2)
    with col_q:
        st.subheader("2 · Quarantine Diagnostics by Reason Code")
        q_rows = con.execute(
            """SELECT reason_code, count(*) AS quarantined_rows, min(detail) AS sample_detail
               FROM observation_quarantine GROUP BY reason_code ORDER BY quarantined_rows DESC"""
        ).fetchall()
        if q_rows:
            st.dataframe(
                [{"reason_code": r[0], "quarantined_rows": r[1], "sample_detail": str(r[2])[:120]} for r in q_rows],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("Zero quarantined observations in the current analytical database.")

    with col_p:
        st.subheader("3 · Source Processing & Ingestion Ledger")
        proc_rows = con.execute(
            """SELECT p.status, count(*) AS runs, sum(p.accepted_count) AS accepted,
                      sum(p.rejected_count) AS rejected, sum(p.quarantined_count) AS quarantined
               FROM source_document_processing_revision p GROUP BY p.status ORDER BY runs DESC"""
        ).fetchall()
        st.dataframe(
            [{"status": r[0], "runs": r[1], "accepted": r[2], "rejected": r[3], "quarantined": r[4]} for r in proc_rows],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("4 · Evidence-Backed Security Admission & Operational CLI Paths")
    admission_renderer(repository)

    with st.expander("Operational CLI Commands & Local-File Ingestion Reference", expanded=False):
        st.code(".venv\\Scripts\\python.exe scripts\\ingest_nse_xbrl.py --help", language="powershell")
        st.code(".venv\\Scripts\\python.exe scripts\\ingest_financial_results.py --help", language="powershell")
        st.code(".venv\\Scripts\\python.exe scripts\\admit_security.py --help", language="powershell")
        st.code(".venv\\Scripts\\python.exe scripts\\ingest_official_eod.py --help", language="powershell")
        st.code(".venv\\Scripts\\python.exe scripts\\ingest_exchange_calendar.py --help", language="powershell")
        st.code(".venv\\Scripts\\python.exe scripts\\ingest_tejhq_pilot.py --help", language="powershell")
        st.dataframe([{"table": t, "rows": counts[t]} for t in tables], use_container_width=True, hide_index=True)
