"""Reusable Streamlit components. Rendering only: no SQL, no agent calls, no credentials."""

from __future__ import annotations

import html
import re

import pandas as pd
import streamlit as st

from supplychain_copilot.agent.client import AgentAnswer
from supplychain_copilot.ui.citations import SourceRef
from supplychain_copilot.ui.data import Kpis

DISCLAIMER = (
    "**Independent portfolio prototype, not a Worthington Enterprises application.** "
    "Delivery metrics come from the public **DataCo Smart Supply Chain** sample dataset (retail/e-commerce, "
    "2015–2018, CC BY 4.0) and are **not Worthington data**. Procedures and disclosures come from "
    "Worthington's **publicly published** supplier documents and FY2026 annual report (10-K)."
)
TOOL_LABELS = {
    "delivery_analytics": "📊 Governed metrics (Cortex Analyst)",
    "supplier_documents": "📄 Document search (Cortex Search)",
}


CAPABILITIES = (
    (
        "🧭",
        "Delivery metrics",
        "Governed numbers from the semantic view, with the SQL shown.",
        "Which regions have the highest late-delivery rates?",
        "Which regions have the highest late-delivery rates?",
    ),
    (
        "📄",
        "Supplier procedures",
        "Answers from public supplier documents, cited to the page.",
        "What are the supplier corrective-action deadlines?",
        "What are the supplier corrective-action deadlines?",
    ),
    (
        "🔗",
        "Both at once",
        "Metrics and procedures in one answer, kept clearly separate.",
        "Which regions have the highest delayed-shipment rates in the sample data, and what "
        "supplier-quality procedures would apply if a quality issue were separately confirmed?",
        "Late regions, and the procedures that would apply",
    ),
)

# Design tokens (kept in sync with .streamlit/config.toml).
INK, MUTED, LINE, ACCENT = "#1E293B", "#64748B", "#E2E8F0", "#0F6E8C"

# Presentation only: static CSS, no user or model content. Selectors use Streamlit's stable
# data-testid attributes and st-key-* classes (Streamlit 1.67).
STYLES = """
<style>
.block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1280px; }
h1, h2, h3 { letter-spacing: -.015em; }
/* ---- app bar ---- */
.scc-appbar { display:flex; align-items:center; justify-content:space-between; gap:1rem;
  background:#FFFFFF; border:1px solid #E2E8F0; border-radius:14px; padding:.8rem 1.1rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04), 0 8px 24px rgba(15,23,42,.04); }
.scc-brand { display:flex; align-items:center; gap:.8rem; }
.scc-logo { width:42px; height:42px; border-radius:11px; display:grid; place-items:center;
  background:linear-gradient(135deg,#0F6E8C,#22A6B3); color:#fff; font-weight:700; font-size:1.05rem;
  box-shadow:0 4px 12px rgba(15,110,140,.30); }
.scc-name { font-size:1.22rem; font-weight:700; color:#0F172A; line-height:1.15; letter-spacing:-.02em; }
.scc-tag { font-size:.83rem; color:#64748B; margin-top:.1rem; }
.scc-chips { display:flex; flex-wrap:wrap; gap:.4rem; justify-content:flex-end; }
.scc-chip { display:inline-flex; align-items:center; gap:.35rem; font-size:.76rem; font-weight:600;
  padding:.28rem .65rem; border-radius:999px; border:1px solid #E2E8F0; background:#F8FAFC; color:#334155; }
.scc-chip.live { background:#ECFDF5; border-color:#A7F3D0; color:#047857; }
.scc-dot { width:7px; height:7px; border-radius:50%; background:#10B981;
  box-shadow:0 0 0 3px rgba(16,185,129,.18); }
/* ---- notice strip ---- */
.scc-notice { margin:.65rem 0 .9rem; padding:.55rem .9rem; border-radius:10px; background:#F8FAFC;
  border:1px solid #E2E8F0; border-left:3px solid #0F6E8C; color:#475569; font-size:.8rem; line-height:1.45; }
.scc-notice strong { color:#1E293B; font-weight:600; }
/* ---- KPI cards ---- */
.scc-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.85rem; margin-bottom:.35rem; }
@media (max-width: 900px) { .scc-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.scc-kpi { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:14px; padding:.95rem 1rem;
  box-shadow:0 1px 2px rgba(15,23,42,.04); transition:box-shadow .15s ease, transform .15s ease; }
.scc-kpi:hover { box-shadow:0 10px 24px rgba(15,23,42,.08); transform:translateY(-1px); }
.scc-kpi-top { display:flex; align-items:center; gap:.55rem; }
.scc-ico { width:30px; height:30px; border-radius:9px; display:grid; place-items:center; font-size:.95rem; }
.scc-label { font-size:.7rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#64748B; }
.scc-value { font-size:1.75rem; font-weight:700; color:#0F172A; margin:.45rem 0 .1rem;
  letter-spacing:-.02em; font-variant-numeric:tabular-nums; }
.scc-sub { font-size:.78rem; color:#64748B; }
.scc-meter { height:6px; border-radius:999px; background:#F1F5F9; margin-top:.5rem; overflow:hidden; }
.scc-meter > span { display:block; height:100%; border-radius:999px;
  background:linear-gradient(90deg,#F59E0B,#E07A5F); }
.scc-foot { font-size:.74rem; color:#94A3B8; margin:.2rem 0 .7rem; }
.scc-foot code { font-size:.72rem; background:#EDF2F7; color:#475569; padding:.05rem .3rem; border-radius:5px; }
/* ---- tabs ---- */
[role="tablist"] { gap:.4rem; border-bottom:none !important; box-shadow:none !important; }
[data-testid="stTab"] { background:#FFFFFF; border:1px solid #E2E8F0 !important; border-radius:999px !important;
  padding:.38rem 1.05rem !important; }
[data-testid="stTab"]:hover { border-color:#0F6E8C !important; }
[data-testid="stTab"][aria-selected="true"] { background:#0F6E8C; border-color:#0F6E8C !important;
  box-shadow:0 4px 12px rgba(15,110,140,.25); }
[data-testid="stTab"][aria-selected="true"] p { color:#FFFFFF !important; }
/* ---- cards built from bordered containers ---- */
div[class*="st-key-card_"], div[class*="st-key-cap_"] { background:#FFFFFF; border-radius:14px !important;
  box-shadow:0 1px 2px rgba(15,23,42,.04); }
.scc-card-head { display:flex; align-items:center; gap:.6rem; margin-bottom:.15rem; }
.scc-card-title { font-weight:650; color:#0F172A; font-size:.98rem; }
.scc-card-desc { color:#64748B; font-size:.83rem; line-height:1.45; margin:.15rem 0 .55rem; min-height:2.4em; }
div[class*="st-key-cap_"] .stButton button { width:100%; text-align:left; justify-content:flex-start;
  background:#F8FAFC; border-color:#E2E8F0; color:#0F6E8C; font-weight:550; font-size:.85rem; line-height:1.35; }
div[class*="st-key-cap_"] .stButton button:hover { background:#ECF7F9; border-color:#0F6E8C; }
.scc-welcome h3 { margin:.2rem 0 .1rem; font-size:1.3rem; color:#0F172A; }
.scc-welcome p { color:#64748B; margin:0 0 .8rem; font-size:.9rem; }
/* ---- chat ---- */
[data-testid="stChatMessage"] { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:14px;
  box-shadow:0 1px 2px rgba(15,23,42,.04); padding:.9rem 1rem; }
[data-testid="stChatInput"] { border-radius:14px; box-shadow:0 6px 20px rgba(15,23,42,.06); }
.scc-meta { display:flex; flex-wrap:wrap; gap:.35rem; margin:.35rem 0 .2rem; }
.scc-pill { font-size:.72rem; font-weight:600; padding:.2rem .6rem; border-radius:999px; border:1px solid; }
.scc-pill.metrics { background:#ECF7F9; border-color:#B6E0E8; color:#0B5C78; }
.scc-pill.docs { background:#FFF7ED; border-color:#FED7AA; color:#9A3412; }
.scc-pill.time { background:#F8FAFC; border-color:#E2E8F0; color:#475569; }
[data-testid="stExpander"] details { background:#FFFFFF; border-radius:12px; }
/* ---- sidebar ---- */
[data-testid="stSidebar"] { border-right:1px solid #E2E8F0; }
[data-testid="stSidebar"] .stButton button { justify-content:flex-start; text-align:left; background:#F8FAFC;
  font-size:.86rem; line-height:1.35; border-color:#E2E8F0; }
[data-testid="stSidebar"] .stButton button:hover { border-color:#0F6E8C; color:#0F6E8C; background:#ECF7F9; }
.scc-side-h { font-size:.7rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:#94A3B8;
  margin:.4rem 0 .5rem; }
.scc-status { background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px; padding:.35rem .75rem; }
.scc-row { display:flex; justify-content:space-between; gap:.5rem; padding:.42rem 0; font-size:.8rem;
  border-bottom:1px dashed #E2E8F0; }
.scc-row:last-child { border-bottom:none; }
.scc-row b { color:#334155; font-weight:600; }
.scc-row span { color:#64748B; text-align:right; }
.scc-ok::before { content:"●"; color:#10B981; margin-right:.35rem; font-size:.7rem; }
</style>
"""


def inject_styles() -> None:
    st.markdown(STYLES, unsafe_allow_html=True)


def _md_bold_to_html(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


def header() -> None:
    """Compact app bar plus a slim, always-visible data notice."""
    inject_styles()
    st.markdown(
        '<div class="scc-appbar"><div class="scc-brand"><div class="scc-logo">SC</div><div>'
        '<div class="scc-name">SupplyChain Copilot</div>'
        '<div class="scc-tag">Supply-chain analytics and supplier knowledge · Snowflake Cortex</div>'
        '</div></div><div class="scc-chips">'
        '<span class="scc-chip live"><span class="scc-dot"></span>Live</span>'
        '<span class="scc-chip">🧭 Governed metrics</span>'
        '<span class="scc-chip">📄 Cited sources</span>'
        '<span class="scc-chip">🔒 Read-only role</span>'
        "</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="scc-notice">ℹ️ {_md_bold_to_html(DISCLAIMER)}</div>', unsafe_allow_html=True
    )


def _kpi(
    icon: str, tint: str, label: str, value: str, sub: str, tip: str, meter: float | None = None
) -> str:
    bar = (
        f'<div class="scc-meter"><span style="width:{max(0.0, min(1.0, meter)) * 100:.1f}%"></span></div>'
        if meter is not None
        else ""
    )
    return (
        f'<div class="scc-kpi" title="{html.escape(tip)}"><div class="scc-kpi-top">'
        f'<div class="scc-ico" style="background:{tint}">{icon}</div>'
        f'<div class="scc-label">{html.escape(label)}</div></div>'
        f'<div class="scc-value">{html.escape(value)}</div><div class="scc-sub">{html.escape(sub)}</div>{bar}</div>'
    )


def kpi_row(k: Kpis) -> None:
    cards = [
        _kpi(
            "📦",
            "#ECF7F9",
            "Unique orders",
            f"{k.total_orders:,}",
            f"{k.eligible_shipments:,} eligible shipments",
            "Distinct orders (one shipment per order). Semantic view metric total_orders.",
        ),
        _kpi(
            "⏱️",
            "#FFF4E5",
            "Late-delivery rate",
            f"{k.late_delivery_rate:.1%}",
            f"{k.late_shipments:,} of {k.eligible_shipments:,} eligible · canceled excluded",
            "Late ÷ eligible shipments; canceled excluded. Metric late_delivery_rate.",
            meter=k.late_delivery_rate,
        ),
        _kpi(
            "🚚",
            "#EEF2FF",
            "Avg shipping duration",
            f"{k.avg_shipping_days:.2f} days",
            f"On-time rate {k.on_time_delivery_rate:.1%}",
            "Average actual shipping days over eligible shipments.",
        ),
        _kpi(
            "📚",
            "#F0FDF4",
            "Indexed documents",
            f"{k.documents}",
            f"{k.chunks} passages, cited to the page",
            "Public supplier and annual-report PDFs in Cortex Search.",
        ),
    ]
    st.markdown(f'<div class="scc-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="scc-foot">Live from the governed semantic view '
        "<code>SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV</code>, the same definitions the agent uses.</div>",
        unsafe_allow_html=True,
    )


def welcome() -> str | None:
    """Empty-state hero for the chat: three capability cards with one-click examples."""
    st.markdown(
        '<div class="scc-welcome"><h3>What would you like to know?</h3>'
        "<p>Ask in plain English. Every number comes from governed SQL and every procedure is cited.</p></div>",
        unsafe_allow_html=True,
    )
    picked = None
    for i, (col, (icon, title, desc, example, label)) in enumerate(
        zip(st.columns(len(CAPABILITIES)), CAPABILITIES, strict=True)
    ):
        with col, st.container(border=True, key=f"cap_{i}"):
            st.markdown(
                f'<div class="scc-card-head"><div class="scc-ico" style="background:#ECF7F9">{icon}</div>'
                f'<div class="scc-card-title">{html.escape(title)}</div></div>'
                f'<div class="scc-card-desc">{html.escape(desc)}</div>',
                unsafe_allow_html=True,
            )
            if st.button(f"“{label}”", key=f"cap_btn_{i}", width="stretch", help=example):
                picked = example
    return picked


def system_status(k: Kpis | None) -> None:
    docs = f"{k.documents} docs · {k.chunks}" if k else "3 docs"
    rows = [
        ("Agent", "2 tools"),
        ("Semantic view", "20 metrics"),
        ("Search", docs),
        ("Runtime role", "Read-only"),
    ]
    body = "".join(
        f'<div class="scc-row"><b class="scc-ok">{html.escape(a)}</b><span>{html.escape(b)}</span></div>'
        for a, b in rows
    )
    st.markdown(
        f'<div class="scc-side-h">System status</div><div class="scc-status">{body}</div>',
        unsafe_allow_html=True,
    )


def _result_table(columns: list[str], rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().all():
            df[col] = converted
    for col in [c for c in df.columns if c.endswith("_RATE")]:
        df[col] = df[col].map(lambda v: f"{v:.1%}" if pd.notna(v) else v)
    return df


def answer_block(answer: AgentAnswer, sources: list[SourceRef], note: str | None = None) -> None:
    if answer.error:
        st.error(answer.text, icon="⚠️")
        return
    if note:
        st.caption(note)
    st.markdown(answer.text)
    for spec in answer.charts:
        try:
            st.vega_lite_chart(spec, width="stretch")
        except Exception:  # noqa: BLE001 - a malformed chart must not hide the answer
            st.caption(
                "(The agent's chart couldn't be displayed; the figures above are unaffected.)"
            )
    # Only the two business-facing tools are shown; internal agent steps (charting, skills) are not.
    kinds = {"delivery_analytics": "metrics", "supplier_documents": "docs"}
    chips = [
        f'<span class="scc-pill {kinds[t]}">{html.escape(TOOL_LABELS[t])}</span>'
        for t in sorted(answer.tools_used)
        if t in TOOL_LABELS
    ] or ['<span class="scc-pill time">No tools needed</span>']
    chips.append(f'<span class="scc-pill time">⏱ {answer.latency_s:.1f}s</span>')
    st.markdown(f'<div class="scc-meta">{"".join(chips)}</div>', unsafe_allow_html=True)

    sql_calls = [t for t in answer.tool_calls if t.sql]
    if sql_calls:
        with st.expander("🔎 Verified results and SQL", expanded=False):
            for t in sql_calls:
                badge = (
                    "✅ steward-verified query"
                    if t.verified_query_used
                    else "governed semantic view"
                )
                st.caption(f"Executed on Snowflake as read-only role SCC_APP_ROLE · {badge}")
                if t.rows:
                    st.dataframe(_result_table(t.columns, t.rows), hide_index=True, width="stretch")
                st.code(t.sql.strip(), language="sql")
    if sources:
        with st.expander(f"📚 Sources ({len(sources)})", expanded=True):
            for s in sources:
                title = f"[{s.document_title}]({s.url})" if s.url else s.document_title
                version = f" · {s.version}" if s.version else ""
                st.markdown(f"**{title}**: {s.section} · {s.pages}{version}")
                if s.snippet:
                    st.caption(
                        s.snippet[:300].replace("\n", " ") + ("…" if len(s.snippet) > 300 else "")
                    )


def sources_table(docs: pd.DataFrame) -> None:
    if docs.empty:
        st.warning("No documents are loaded.")
        return
    view = docs.rename(
        columns={
            "DOCUMENT_TITLE": "Document",
            "DOCUMENT_VERSION": "Version",
            "PUBLICATION_DATE": "Published",
            "PAGES_INCLUDED": "Pages indexed",
            "PAGE_COUNT": "Total pages",
            "CHUNK_COUNT": "Passages",
            "SOURCE_URL": "Source",
        }
    )[["Document", "Version", "Published", "Pages indexed", "Total pages", "Passages", "Source"]]
    st.dataframe(
        view,
        hide_index=True,
        width="stretch",
        column_config={"Source": st.column_config.LinkColumn("Source", display_text="Open PDF")},
    )
