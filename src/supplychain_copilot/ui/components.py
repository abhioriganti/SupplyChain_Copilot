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


def header() -> None:
    st.title("SupplyChain Copilot")
    st.caption("AI-powered supply-chain analytics and supplier knowledge")
    st.info(DISCLAIMER, icon="ℹ️")


def kpi_row(k: Kpis) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Unique orders",
        f"{k.total_orders:,}",
        help="Distinct orders (one shipment per order). Semantic view metric total_orders.",
    )
    c2.metric(
        "Late-delivery rate",
        f"{k.late_delivery_rate:.1%}",
        help=f"Late ÷ eligible shipments ({k.late_shipments:,} of {k.eligible_shipments:,}); canceled excluded.",
    )
    c3.metric(
        "Avg shipping duration",
        f"{k.avg_shipping_days:.2f} days",
        help="Average actual shipping days, eligible shipments.",
    )
    c4.metric(
        "Indexed documents",
        f"{k.documents}",
        help=f"{k.chunks} searchable passages with page-level citations.",
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
