"""SupplyChain Copilot: Streamlit UI.

Run:  .venv\\Scripts\\streamlit run app\\streamlit_app.py
Uses the runtime user SCC_APP_SVC (read-only SCC_APP_ROLE) from .env; nothing secret reaches the browser.
This file only composes UI; data access, agent calls, charts and feedback live in supplychain_copilot.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import streamlit as st

from supplychain_copilot.agent.client import AgentAnswer, CopilotAgent
from supplychain_copilot.incidents.service import IncidentService, copilot_drafter
from supplychain_copilot.incidents.store import SnowflakeIncidentStore
from supplychain_copilot.observability import build_log_record, log_request
from supplychain_copilot.ui import charts, components, risk
from supplychain_copilot.ui import incidents as incidents_ui
from supplychain_copilot.ui.cache import AnswerCache
from supplychain_copilot.ui.citations import build_sources
from supplychain_copilot.ui.data import DashboardData
from supplychain_copilot.ui.feedback import build_record, save_feedback

SUGGESTED = [
    "Which regions have the highest late-delivery rates?",
    "What are the supplier corrective-action deadlines?",
    "Which regions have the highest delayed-shipment rates in the sample data, and what supplier-quality "
    "procedures would apply if a quality issue were separately confirmed?",
    "Which shipping mode has the best on-time performance?",
    "What supply-chain risks does the annual report describe?",
]
CHART_CONFIG = {"displayModeBar": False}  # cleaner charts for a business audience
HISTORY_TURNS = 3  # prior Q&A pairs sent to the agent for follow-up questions
CACHED_NOTE = "♻️ Reused from earlier in this session (no new agent call). Use “Ask again live” for a fresh run."

st.set_page_config(page_title="SupplyChain Copilot", page_icon="📦", layout="wide")


# ----------------------------------------------------------------------------- services (injectable for tests)


def services() -> SimpleNamespace:
    if "services" not in st.session_state:
        agent = CopilotAgent()
        st.session_state.services = SimpleNamespace(
            agent=agent,
            data=DashboardData(),
            save_feedback=save_feedback,
            log_request=log_request,
            incidents=IncidentService(SnowflakeIncidentStore(), drafter=copilot_drafter(agent)),
        )
    return st.session_state.services


@st.cache_data(ttl=600, show_spinner=False)
def load_dashboard(_data) -> dict:
    return {
        "kpis": _data.kpis(),
        "regions": _data.late_by_region(),
        "modes": _data.by_shipping_mode(),
        "monthly": _data.monthly_by_market(),
        "documents": _data.documents(),
    }


def init_state() -> None:
    st.session_state.setdefault(
        "messages", []
    )  # [{"role": "user"|"assistant", "text": str, "answer": AgentAnswer?}]
    st.session_state.setdefault("session_id", str(uuid.uuid4()))
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("pending_live", False)
    st.session_state.setdefault("answer_cache", AnswerCache(standalone_questions=set(SUGGESTED)))


def history_for_agent() -> list[dict]:
    msgs = [
        m
        for m in st.session_state.messages
        if m["role"] in ("user", "assistant") and not m.get("error")
    ]
    recent = msgs[-2 * HISTORY_TURNS :]
    return [{"role": m["role"], "content": [{"type": "text", "text": m["text"]}]} for m in recent]


def run_agent_streaming(agent, question: str, history: list[dict]) -> AgentAnswer:
    """Show live progress (planning, tool calls with the actual search query, SQL execution) and stream
    the answer text as it arrives. Falls back to a blocking call for agents without ask_stream."""
    t0 = time.perf_counter()
    status = st.status("Planning the next steps…", expanded=True)
    text_area = st.empty()
    if not hasattr(agent, "ask_stream"):
        answer = agent.ask(question, history=history)
    else:
        answer, buffer, shown = None, "", set()
        for ev in agent.ask_stream(question, history=history):
            if ev.kind in ("status", "tool") and ev.message and ev.message not in shown:
                shown.add(ev.message)
                status.update(label=f"{ev.message}…  ({time.perf_counter() - t0:.0f}s)")
                if ev.kind == "tool":
                    status.write(ev.message)
            elif ev.kind == "text":
                buffer += ev.text
                text_area.markdown(buffer + " ▌")
            elif ev.kind == "final":
                answer = ev.answer
        if answer is None:  # defensive: the client always yields a final event
            answer = AgentAnswer(
                question,
                "The assistant returned no answer.",
                status="error",
                error="empty: no final event",
            )
    text_area.empty()
    status.update(
        label=f"Done in {time.perf_counter() - t0:.1f}s"
        if answer.ok
        else "The assistant ran into a problem",
        state="complete" if answer.ok else "error",
        expanded=False,
    )
    return answer


def ask(question: str, force_live: bool = False) -> None:
    svc = services()
    history = history_for_agent()
    has_history = bool(history)
    cache: AnswerCache = st.session_state.answer_cache
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    cached = None if force_live else cache.get(question, has_history)
    with st.chat_message("assistant"):
        if cached is not None:
            answer = cached
        else:
            answer = run_agent_streaming(svc.agent, question, history)
            cache.put(question, answer, has_history)
        sources = build_sources(answer.citations, _chunk_meta(answer))
        components.answer_block(answer, sources, note=CACHED_NOTE if cached is not None else None)
    svc.log_request(
        build_log_record(answer, "app", st.session_state.session_id, cached=cached is not None)
    )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "text": answer.text,
            "answer": answer,
            "sources": sources,
            "error": bool(answer.error),
            "cached": cached is not None,
            "question": question,
        }
    )


def _chunk_meta(answer: AgentAnswer):
    if not answer.citations:
        return None
    try:
        return services().data.chunk_metadata([c.chunk_id for c in answer.citations])
    except Exception:  # noqa: BLE001 - citations still render from the agent's own labels
        return None


def feedback_widget(i: int, msg: dict) -> None:
    if msg.get("error"):
        return
    rating = st.feedback("thumbs", key=f"fb_{i}")
    if rating is not None and not msg.get("feedback_saved"):
        where = services().save_feedback(
            build_record(msg["answer"], 1 if rating == 1 else -1, st.session_state.session_id)
        )
        msg["feedback_saved"] = where
        st.toast("Thanks, feedback saved" + (" (local log)" if where == "local" else ""), icon="✅")


# ----------------------------------------------------------------------------- page

init_state()

dashboard = None
try:
    dashboard = load_dashboard(services().data)
except Exception:  # noqa: BLE001 - shown as a friendly warning below, never a stack trace
    dashboard = None
components.header(live=dashboard is not None)
if dashboard is not None:
    components.kpi_row(dashboard["kpis"])
else:
    st.warning(
        "Live metrics are unavailable right now (Snowflake connection or permissions). "
        "Check the app's .env settings for the runtime user and that the warehouse is running.",
        icon="⚠️",
    )

with st.sidebar:
    st.markdown('<div class="scc-side-h">Try a question</div>', unsafe_allow_html=True)
    for q in SUGGESTED:
        if st.button(q, key=f"sugg_{hash(q)}", width="stretch"):
            st.session_state.pending = q
    if st.button("🧹 Clear conversation", width="stretch"):
        st.session_state.messages = []
        st.session_state.answer_cache.clear()
        st.rerun()
    st.divider()
    components.system_status(dashboard["kpis"] if dashboard else None)
    st.caption("Agent `SCC_DB.AI.SUPPLY_CHAIN_COPILOT` · Cortex Analyst + Cortex Search")

tab_chat, tab_dash, tab_sources, tab_incidents = st.tabs(
    ["💬 Ask the Copilot", "📈 Delivery dashboard", "📚 Sources", "🚨 Incidents (simulated)"]
)

with tab_chat:
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                components.answer_block(
                    msg["answer"],
                    msg.get("sources", []),
                    note=CACHED_NOTE if msg.get("cached") else None,
                )
                if msg.get("cached") and st.button("🔄 Ask again live", key=f"live_{i}"):
                    st.session_state.pending = msg["question"]
                    st.session_state.pending_live = True
                    st.rerun()
                feedback_widget(i, msg)
            else:
                st.markdown(msg["text"])
    if not st.session_state.messages:
        picked = components.welcome()
        if picked:
            st.session_state.pending = picked
    question = st.chat_input("Ask about delivery metrics or supplier procedures…")
    pending, st.session_state.pending = st.session_state.pending, None
    live, st.session_state.pending_live = st.session_state.pending_live, False
    if question or pending:
        ask(question or pending, force_live=live and not question)
        st.rerun()

with tab_dash:
    if dashboard is None:
        st.info("Charts appear when live metrics are available.")
    else:
        with st.container(border=True, key="card_regions"):
            st.plotly_chart(
                charts.late_rate_by_region(dashboard["regions"]),
                width="stretch",
                config=CHART_CONFIG,
            )
            st.caption(
                "Region late rates fall in a narrow band; small regions (e.g. Central Africa, 533 "
                "eligible shipments) shouldn't be over-interpreted."
            )
        c1, c2 = st.columns(2)
        with c1, st.container(border=True, key="card_modes"):
            st.plotly_chart(
                charts.shipping_mode_performance(dashboard["modes"]),
                width="stretch",
                config=CHART_CONFIG,
            )
            st.caption(
                "Shipping mode separates late from on-time far more than region does (descriptive, "
                "not causal)."
            )
        with c2, st.container(border=True, key="card_monthly"):
            st.plotly_chart(
                charts.monthly_late_rate(dashboard["monthly"]), width="stretch", config=CHART_CONFIG
            )
            st.caption(
                "⚠️ Different markets appear in different months, so month-over-month changes mostly "
                "reflect market mix, not operational change. Gaps mean the market is absent; "
                "market-months with fewer than 100 eligible shipments are hidden."
            )
        if hasattr(services().data, "late_risk"):
            with st.container(border=True, key="card_risk"):
                risk.risk_card(services().data, dashboard["regions"], dashboard["modes"])

with tab_sources, st.container(border=True, key="card_sources"):
    st.markdown("#### Indexed public documents")
    if dashboard is not None:
        components.sources_table(dashboard["documents"])
    st.caption(
        "Citations link to the public PDF at the cited page. Passages are pinned by SHA-256, and every "
        "word is verified to appear on its cited page (see docs/document_extraction_report.md)."
    )

with tab_incidents:
    incident_service = getattr(services(), "incidents", None)  # optional (Phase 9)
    if incident_service is None:
        st.info("The simulated incident workflow isn't configured in this session.")
    else:
        incidents_ui.render(incident_service)
