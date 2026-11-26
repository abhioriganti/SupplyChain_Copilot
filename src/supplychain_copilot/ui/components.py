"""Reusable Streamlit components. Rendering only: no SQL, no agent calls, no credentials."""

from __future__ import annotations

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
    "📊 Governed semantic layer",
    "📄 Cited public documents",
    "🔒 Read-only runtime role",
    "🧑‍⚖️ Human-in-the-loop approvals",
)

# Presentation only. Selectors use Streamlit's stable data-testid attributes and st-key-* classes.
STYLES = """
<style>
.block-container { padding-top: 1.6rem; max-width: 1240px; }
.st-key-hero {
  background: linear-gradient(120deg, #0F6E8C 0%, #1B8FA6 55%, #5FB3B3 100%);
  border-radius: 1rem; padding: 1.4rem 1.6rem 1.1rem; margin-bottom: .4rem;
  box-shadow: 0 6px 20px rgba(15, 110, 140, .18);
}
.st-key-hero h1 { color: #FFFFFF !important; font-weight: 750; letter-spacing: -.01em;
  padding: 0 !important; margin: 0 !important; }
.st-key-hero [data-testid="stCaptionContainer"] p { color: #E3F4F7 !important; font-size: 1.02rem; }
.scc-pills { display: flex; flex-wrap: wrap; gap: .45rem; margin-top: .55rem; }
.scc-pill { background: rgba(255,255,255,.16); color: #FFFFFF; border: 1px solid rgba(255,255,255,.35);
  border-radius: 999px; padding: .18rem .7rem; font-size: .82rem; font-weight: 550; }
[data-testid="stAlert"] { border-radius: .75rem; }
[data-testid="stMetric"] { background: #FFFFFF; border-top: 4px solid #0F6E8C !important;
  box-shadow: 0 2px 10px rgba(31, 42, 55, .06); }
[data-testid="stMetricValue"] { color: #0F3D4C; }
[data-testid="stMetricLabel"] p { font-weight: 600; color: #4B5B6B; }
[role="tablist"] { gap: .4rem; border-bottom: none !important; box-shadow: none !important; }
[data-testid="stTab"] { background: #FFFFFF; border: 1px solid #D9E3EC !important;
  border-radius: 999px !important; padding: .35rem 1rem !important; }
[data-testid="stTab"]:hover { border-color: #0F6E8C !important; }
[data-testid="stTab"][aria-selected="true"] { background: #0F6E8C; border-color: #0F6E8C !important; }
[data-testid="stTab"][aria-selected="true"] p { color: #FFFFFF !important; }
[data-testid="stMetricValue"] > div { overflow: visible; text-overflow: clip; }
[data-testid="stSidebar"] { border-right: 1px solid #D9E3EC; }
[data-testid="stSidebar"] .stButton button { justify-content: flex-start; text-align: left;
  background: #F7FAFC; font-size: .9rem; line-height: 1.35; }
[data-testid="stSidebar"] .stButton button:hover { border-color: #0F6E8C; color: #0F6E8C; }
[data-testid="stChatMessage"] { background: #FFFFFF; border: 1px solid #E3EAF1; border-radius: .9rem;
  box-shadow: 0 1px 6px rgba(31, 42, 55, .04); }
[data-testid="stExpander"] details { background: #FFFFFF; }
</style>
"""


def inject_styles() -> None:
    st.markdown(STYLES, unsafe_allow_html=True)  # static CSS only; no user or model content


def header() -> None:
    inject_styles()
    with st.container(key="hero"):
        st.title("SupplyChain Copilot")
        st.caption("AI-powered supply-chain analytics and supplier knowledge, on Snowflake Cortex")
        pills = "".join(f'<span class="scc-pill">{c}</span>' for c in CAPABILITIES)
        st.markdown(f'<div class="scc-pills">{pills}</div>', unsafe_allow_html=True)
    st.info(DISCLAIMER, icon="ℹ️")


def kpi_row(k: Kpis) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Unique orders",
        f"{k.total_orders:,}",
        help="Distinct orders (one shipment per order). Semantic view metric total_orders.",
        border=True,
    )
    c2.metric(
        "Late-delivery rate",
        f"{k.late_delivery_rate:.1%}",
        help=f"Late ÷ eligible shipments ({k.late_shipments:,} of {k.eligible_shipments:,}); canceled excluded.",
        border=True,
    )
    c3.metric(
        "Avg shipping duration",
        f"{k.avg_shipping_days:.2f} days",
        help="Average actual shipping days, eligible shipments.",
        border=True,
    )
    c4.metric(
        "Indexed documents",
        f"{k.documents}",
        help=f"{k.chunks} searchable passages with page-level citations.",
        border=True,
    )
    st.caption(
        "KPIs are queried live from the governed semantic view `SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV`, "
        "the same definitions the agent uses."
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
    used = [TOOL_LABELS[t] for t in sorted(answer.tools_used) if t in TOOL_LABELS]
    st.caption(
        " · ".join(used + [f"⏱ {answer.latency_s:.1f}s"])
        if used
        else f"No tools needed · ⏱ {answer.latency_s:.1f}s"
    )

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
