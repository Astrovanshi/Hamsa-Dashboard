"""Dark-first institutional styling and shared status components for HAMSA Terminal."""

from __future__ import annotations

import streamlit as st


TERMINAL_CSS = """
<style>
    .stApp {
        background-color: #0b0e14;
        color: #e2e8f0;
    }
    [data-testid="stSidebar"] {
        background-color: #0f141d;
        border-right: 1px solid #1e293b;
    }
    [data-testid="stMetric"] {
        background-color: #111722;
        border: 1px solid #1e293b;
        border-radius: 4px;
        padding: 10px 14px;
    }
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
        font-variant-numeric: tabular-nums;
        font-size: 1.35rem !important;
    }
    .hamsa-topbar {
        background: #111722;
        border: 1px solid #1e293b;
        border-left: 3px solid #3b82f6;
        border-radius: 4px;
        padding: 10px 16px;
        margin-bottom: 14px;
        display: flex;
        flex-wrap: wrap;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        font-family: 'JetBrains Mono', Consolas, monospace;
        font-size: 0.82rem;
    }
    .hamsa-card {
        background: #111722;
        border: 1px solid #1e293b;
        border-radius: 4px;
        padding: 14px 16px;
        margin-bottom: 10px;
    }
    .hamsa-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 3px;
        font-family: 'JetBrains Mono', Consolas, monospace;
        font-size: 0.74rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .badge-triggered, .badge-pass {
        background: rgba(16, 185, 129, 0.16);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.4);
    }
    .badge-unproven, .badge-attention {
        background: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.4);
    }
    .badge-fail, .badge-risk {
        background: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.4);
    }
    .badge-neutral, .badge-not_triggered, .badge-blocked {
        background: rgba(100, 116, 139, 0.16);
        color: #94a3b8;
        border: 1px solid rgba(100, 116, 139, 0.35);
    }
    .badge-accent {
        background: rgba(59, 130, 246, 0.16);
        color: #60a5fa;
        border: 1px solid rgba(59, 130, 246, 0.4);
    }
</style>
"""


def inject_terminal_theme() -> None:
    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)


def badge_html(label: str, kind: str = "neutral") -> str:
    norm = kind.lower().strip()
    if norm in ("triggered", "pass", "positive", "approved", "research_priority"):
        cls = "badge-triggered"
    elif norm in ("unproven", "attention", "pending", "watch", "multi_signal", "new_signal"):
        cls = "badge-unproven"
    elif norm in ("fail", "rejected", "risk", "discrepancy"):
        cls = "badge-fail"
    elif norm in ("accent", "info"):
        cls = "badge-accent"
    else:
        cls = "badge-neutral"
    return f'<span class="hamsa-badge {cls}">{label}</span>'


def render_topbar(
    *,
    exchange: str,
    calendar_version: str | None,
    session_date_str: str,
    availability_mode: str,
    schema_version: int,
    focus_company_label: str,
) -> None:
    cal_label = calendar_version or "NO CALENDAR"
    st.markdown(
        f"""
        <div class="hamsa-topbar">
            <div>
                <strong>HAMSA INTELLIGENCE TERMINAL</strong> &nbsp;|&nbsp;
                VENUE: <span style="color:#60a5fa">{exchange}</span> &nbsp;|&nbsp;
                SESSION: <span style="color:#10b981">{session_date_str} @ 15:30 IST</span> &nbsp;|&nbsp;
                MODE: <span style="color:#f59e0b">{availability_mode}</span> &nbsp;|&nbsp;
                CALENDAR: <span>{cal_label}</span>
            </div>
            <div>
                FOCUS: <span style="color:#60a5fa">{focus_company_label}</span> &nbsp;|&nbsp;
                SCHEMA: <span>v{schema_version}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
