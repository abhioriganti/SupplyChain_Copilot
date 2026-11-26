"""Phase 7 UI tests (CI-safe; no Snowflake, no Cortex cost).

* Pure modules: charts map the right columns, citations resolve to page links, feedback records are
  redacted and fall back to a local log, the data layer issues governed semantic-view queries.
* The real Streamlit page runs headlessly via streamlit.testing.AppTest with fake services injected
  through st.session_state, covering KPIs, chat (structured/document/hybrid answers), errors and charts.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from supplychain_copilot.agent.client import AgentAnswer, Citation, ToolCall, parse_response
from supplychain_copilot.ui import charts, feedback
from supplychain_copilot.ui.citations import build_sources, pdf_page_link
from supplychain_copilot.ui.data import DashboardData, Kpis

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
FIXTURE = Path(__file__).parent / "fixtures" / "agent_hybrid_response.json"

REGIONS = pd.DataFrame(
    {
        "MARKET": ["Africa", "USCA"],
        "ORDER_REGION": ["Central Africa", "Canada"],
        "LATE_DELIVERY_RATE": [0.6004, 0.5258],
        "ELIGIBLE_SHIPMENTS": [533, 291],
        "LATE_SHIPMENTS": [320, 153],
    }
)
MODES = pd.DataFrame(
    {
        "SHIPPING_MODE": ["First Class", "Standard Class"],
        "SCHEDULED_SHIPPING_DAYS": [1, 4],
        "ON_TIME_DELIVERY_RATE": [0.0, 0.6015],
        "LATE_DELIVERY_RATE": [1.0, 0.3985],
        "AVG_ACTUAL_SHIPPING_DAYS": [2.0, 3.99],
        "ELIGIBLE_SHIPMENTS": [9602, 37632],
    }
)
MONTHLY = pd.DataFrame(
    {
        "ORDER_MONTH": pd.to_datetime(["2015-01-01", "2015-06-01"]),
        "MARKET": ["LATAM", "Europe"],
        "LATE_DELIVERY_RATE": [0.57, 0.58],
        "ELIGIBLE_SHIPMENTS": [1700, 1650],
    }
)
DOCS = pd.DataFrame(
    {
        "DOCUMENT_ID": ["D"],
        "DOCUMENT_TITLE": ["Supplier Quality Assurance Manual"],
        "DOCUMENT_TYPE": ["m"],
        "DOCUMENT_VERSION": ["Rev. 2025-10-23"],
        "PUBLICATION_DATE": ["2025-10-23"],
        "SOURCE_URL": ["https://example.org/sqam.pdf"],
        "PAGES_INCLUDED": [39],
        "PAGE_COUNT": [41],
        "CHUNK_COUNT": [31],
    }
)
KPIS = Kpis(65752, 62897, 36048, 0.5731, 0.4269, 3.5015, 3, 152)


# ----------------------------------------------------------------------------- fakes


class FakeData:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def kpis(self):
        if self.fail:
            raise RuntimeError("connection refused: account=SECRET-ACCOUNT")
        return KPIS

    def late_by_region(self):
        return REGIONS

    def by_shipping_mode(self):
        return MODES

    def monthly_by_market(self):
        return MONTHLY

    def documents(self):
        return DOCS

    def chunk_metadata(self, ids):
        return pd.DataFrame(
            [
                {
                    "CHUNK_ID": ids[0],
                    "DOCUMENT_ID": "D",
                    "DOCUMENT_TITLE": "Supplier Quality Assurance Manual",
                    "SECTION_TITLE": "7.2 Corrective Action Responses",
                    "PAGE_NUMBER": 29,
                    "PAGE_END": 29,
                    "PRINTED_PAGE_START": "29",
                    "SOURCE_URL": "https://example.org/sqam.pdf",
                    "DOCUMENT_VERSION": "Rev. 2025-10-23",
                }
            ]
        )


class FakeAgent:
    def __init__(self, answer: AgentAnswer):
        self.answer = answer
        self.questions: list[str] = []

    def ask(self, question, history=None):
        self.questions.append(question)
        self.answer.question = question
        return self.answer


def _hybrid_answer() -> AgentAnswer:
    return parse_response("q", json.loads(FIXTURE.read_text(encoding="utf-8")), 12.3)


def _app(agent_answer: AgentAnswer | None = None, data=None, saved=None) -> AppTest:
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["services"] = SimpleNamespace(
        agent=FakeAgent(agent_answer or _hybrid_answer()),
        data=data or FakeData(),
        save_feedback=(lambda rec: saved.append(rec) or "snowflake")
        if saved is not None
        else (lambda rec: "snowflake"),
    )
    return at


# ----------------------------------------------------------------------------- pure modules


def test_region_chart_uses_governed_columns_and_all_regions():
    fig = charts.late_rate_by_region(REGIONS)
    xs = sorted(v for tr in fig.data for v in tr.x)
    assert xs == sorted(REGIONS.LATE_DELIVERY_RATE.tolist())
    assert {tr.name for tr in fig.data} == {"Africa", "USCA"}
    assert fig.layout.xaxis.tickformat == ".0%"


def test_mode_chart_orders_by_scheduled_days_and_shows_on_time_rate():
    fig = charts.shipping_mode_performance(MODES)
    assert list(fig.data[0].y) == [0.0, 0.6015]
    assert fig.data[0].x[0].startswith("First Class")


def test_monthly_chart_one_trace_per_market():
    assert {tr.name for tr in charts.monthly_late_rate(MONTHLY).data} == {"LATAM", "Europe"}


def test_monthly_chart_breaks_lines_where_market_is_absent():
    gap = pd.DataFrame(
        {
            "ORDER_MONTH": pd.to_datetime(["2015-01-01", "2015-02-01", "2015-03-01"]),
            "MARKET": ["LATAM", "Europe", "LATAM"],
            "LATE_DELIVERY_RATE": [0.57, 0.58, 0.56],
            "ELIGIBLE_SHIPMENTS": [1700, 1700, 1700],
        }
    )
    latam = next(tr for tr in charts.monthly_late_rate(gap).data if tr.name == "LATAM")
    ys = list(latam.y)
    assert len(ys) == 3 and pd.isna(ys[1]) and latam.connectgaps is False


def test_monthly_chart_hides_tiny_market_months():
    tiny = pd.concat(
        [
            MONTHLY,
            pd.DataFrame(
                {
                    "ORDER_MONTH": pd.to_datetime(["2015-05-01"]),
                    "MARKET": ["Africa"],
                    "LATE_DELIVERY_RATE": [0.2],
                    "ELIGIBLE_SHIPMENTS": [41],
                }
            ),
        ]
    )
    assert "Africa" not in {tr.name for tr in charts.monthly_late_rate(tiny).data}


def test_citations_prefer_metadata_and_link_to_page():
    srcs = build_sources(
        [Citation("WOR-X-abc", "Doc | Sec | PDF p. 29", "snippet")],
        FakeData().chunk_metadata(["WOR-X-abc"]),
    )
    assert srcs[0].url == "https://example.org/sqam.pdf#page=29" and srcs[0].pages == "PDF p. 29"
    assert pdf_page_link("", 3) == ""


def test_snippet_drops_search_column_prefix():
    from supplychain_copilot.ui.citations import clean_snippet

    raw = "Supplier Quality Assurance Manual - 7.2 Corrective Action Responses\n7.2 Corrective Action Responses The following"
    assert clean_snippet(raw, "Supplier Quality Assurance Manual").startswith(
        "7.2 Corrective Action Responses The"
    )
    assert clean_snippet("plain text", "Other Doc") == "plain text"


def test_citations_fall_back_to_agent_label():
    srcs = build_sources(
        [Citation("C1", "Supplier Code of Conduct | Labor and Human Rights | PDF p. 5-6", "")], None
    )
    assert (srcs[0].document_title, srcs[0].section, srcs[0].pages) == (
        "Supplier Code of Conduct",
        "Labor and Human Rights",
        "PDF p. 5-6",
    )


def test_feedback_record_is_redacted_and_validated():
    a = AgentAnswer("my password: hunter2", "answer", status="completed")
    rec = feedback.build_record(a, 1, "s")
    assert "hunter2" not in rec["QUESTION"] and rec["RATING"] == 1 and rec["APP_VERSION"]
    with pytest.raises(ValueError):
        feedback.build_record(a, 0, "s")


def test_feedback_falls_back_to_local_log(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "LOCAL_LOG", tmp_path / "fb.jsonl")

    @contextmanager
    def broken():
        raise RuntimeError("snowflake down")
        yield  # pragma: no cover

    rec = feedback.build_record(AgentAnswer("q", "a", status="completed"), -1, "s")
    assert feedback.save_feedback(rec, session_factory=broken) == "local"
    assert json.loads((tmp_path / "fb.jsonl").read_text().splitlines()[0])["RATING"] == -1


def test_data_layer_queries_semantic_view_only():
    seen: list[str] = []

    class Cur:
        def execute(self, sql, params=None):
            seen.append(sql)

    class Conn:
        def cursor(self, *a):
            return Cur()

    @contextmanager
    def fake_session():
        yield Conn()

    import supplychain_copilot.ui.data as data_mod

    orig = data_mod.query
    data_mod.query = lambda conn, sql, params=None: seen.append(sql) or []
    try:
        d = DashboardData(session_factory=fake_session)
        d.late_by_region(), d.by_shipping_mode(), d.monthly_by_market()
    finally:
        data_mod.query = orig
    assert seen and all("SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV" in s for s in seen)
    assert not any("GOLD." in s for s in seen)


# ----------------------------------------------------------------------------- the real page (AppTest)


def test_page_renders_header_disclaimer_and_live_kpis():
    at = _app()
    at.run()
    assert not at.exception
    assert at.title[0].value == "SupplyChain Copilot"
    assert any("not a Worthington Enterprises application" in i.value for i in at.info)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Unique orders"] == "65,752" and metrics["Late-delivery rate"] == "57.3%"
    assert metrics["Avg shipping duration"] == "3.50 days" and metrics["Indexed documents"] == "3"


def test_hybrid_question_shows_answer_sources_and_sql():
    at = _app()
    at.run()
    at.chat_input[0].set_value("Which regions have the highest delayed-shipment rates?").run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Central Africa" in text and "60.0%" in text
    assert "Supplier Quality Assurance Manual" in text and "PDF p. 29" in text  # citation panel
    assert any("SEMANTIC_VIEW" in c.value for c in at.code)  # SQL inspection
    assert len(at.session_state["messages"]) == 2


def test_suggested_question_button_asks_agent():
    at = _app()
    at.run()
    at.sidebar.button[0].click().run()
    assert at.session_state["services"].agent.questions == [
        "Which regions have the highest late-delivery rates?"
    ]


def test_agent_error_is_shown_gracefully():
    err = AgentAnswer(
        "q",
        "The assistant is busy right now. Please try again in a moment.",
        status="error",
        error="rate_limited: x",
    )
    at = _app(agent_answer=err)
    at.run()
    at.chat_input[0].set_value("anything").run()
    assert not at.exception
    assert any("busy right now" in e.value for e in at.error)


def test_dashboard_failure_shows_warning_without_details():
    at = _app(data=FakeData(fail=True))
    at.run()
    assert not at.exception
    warning = " ".join(w.value for w in at.warning)
    assert "Live metrics are unavailable" in warning and "SECRET-ACCOUNT" not in warning


def test_document_answer_without_sql_has_no_sql_panel():
    ans = AgentAnswer(
        "q",
        "Containment within 2 working days (SQAM §7.2, p. 29).",
        status="completed",
        citations=[Citation("C1", "Supplier Quality Assurance Manual | 7.2 | PDF p. 29", "...")],
        tool_calls=[
            ToolCall(
                tool="supplier_documents", step="supplier_documents:cortex_search", status="success"
            )
        ],
    )
    at = _app(agent_answer=ans)
    at.run()
    at.chat_input[0].set_value("What are the corrective-action deadlines?").run()
    assert not at.exception and not at.code
    assert any("PDF p. 29" in m.value for m in at.markdown)


def test_feedback_is_saved_once():
    saved: list = []
    at = _app(saved=saved)
    at.run()
    at.chat_input[0].set_value("q").run()
    fb = at.get("feedback")
    assert fb, "feedback widget not rendered"
    fb[0].set_value(1).run()
    assert len(saved) == 1 and saved[0]["RATING"] == 1
