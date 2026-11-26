"""Streaming agent client + per-session answer cache (CI-safe; no Snowflake, no Cortex cost)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from supplychain_copilot.agent.client import AgentAnswer, CopilotAgent, describe_tool_use
from supplychain_copilot.snowflake.rest import SnowflakeRestClient, SnowflakeRestError
from supplychain_copilot.ui.cache import AnswerCache, normalize

FIXTURE = Path(__file__).parent / "fixtures" / "agent_hybrid_response.json"
APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
FINAL = json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeStreamClient:
    def __init__(self, runs):
        self.runs = list(runs)
        self.calls = 0

    def post_stream(self, path, body):
        self.calls += 1
        run = self.runs.pop(0)
        if isinstance(run, Exception):
            raise run
        yield from run


GOOD_RUN = [
    ("response.status", {"message": "Planning the next steps", "status": "planning"}),
    (
        "response.tool_use",
        {"name": "supplier_documents", "input": {"query": "corrective action deadlines"}},
    ),
    ("response.tool_result.status", {"message": "Running supplier_documents"}),
    ("response.tool_use", {"name": "data_to_chart", "input": {}}),  # internal step: not shown
    ("response.text.delta", {"text": "Containment within "}),
    ("response.text.delta", {"text": "2 working days."}),
    ("response", FINAL),
    ("done", None),
]


def _stream_agent(runs):
    return CopilotAgent(client=FakeStreamClient(runs), backoff_s=0)


# ----------------------------------------------------------------------------- streaming client


def test_stream_yields_progress_text_then_one_final_answer():
    events = list(_stream_agent([GOOD_RUN]).ask_stream("q"))
    kinds = [e.kind for e in events]
    assert kinds[-1] == "final" and kinds.count("final") == 1
    assert (
        "".join(e.text for e in events if e.kind == "text") == "Containment within 2 working days."
    )
    msgs = [e.message for e in events if e.kind in ("status", "tool")]
    assert "Planning the next steps" in msgs and any(
        "corrective action deadlines" in m for m in msgs
    )
    assert not any("data_to_chart" in m for m in msgs)
    final = events[-1].answer
    assert (
        final.ok
        and final.tools_used == {"delivery_analytics", "supplier_documents"}
        and final.citations
    )


def test_stream_error_event_becomes_fallback():
    events = list(
        _stream_agent(
            [
                [
                    ("response.status", {"message": "x"}),
                    ("error", {"code": "399504", "message": "Error"}),
                ]
            ]
        ).ask_stream("q")
    )
    assert events[-1].kind == "final" and events[-1].answer.error.startswith("service")


def test_stream_ending_without_response_is_handled():
    events = list(
        _stream_agent([[("response.status", {"message": "x"}), ("done", None)]]).ask_stream("q")
    )
    assert events[-1].answer.error.startswith("empty")


def test_stream_retries_only_before_first_event():
    agent = _stream_agent([SnowflakeRestError(429, "busy"), GOOD_RUN])
    assert list(agent.ask_stream("q"))[-1].answer.ok


def test_stream_timeout_and_invalid_question():
    assert list(_stream_agent([requests.Timeout()]).ask_stream("q"))[-1].answer.error.startswith(
        "timeout"
    )
    assert list(_stream_agent([]).ask_stream(" "))[-1].answer.error.startswith("invalid")


def test_describe_tool_use():
    assert "Searching documents" in describe_tool_use(
        {"name": "supplier_documents", "input": {"query": "x"}}
    )
    assert "SQL" in describe_tool_use({"name": "system_execute_sql", "input": {"sql": "select 1"}})
    assert describe_tool_use({"name": "server_skill", "input": {}}) == ""


def test_rest_post_stream_decodes_utf8_without_charset(monkeypatch):
    """Regression: SSE responses carry no charset; '§' must not become 'Â§'."""
    raw = 'event: response.text.delta\ndata: {"text": "Manual, §7.2 – São Paulo"}\n\n'.encode()

    class Resp:
        status_code = 200
        text = ""
        encoding = "ISO-8859-1"  # what requests guesses for text/event-stream without a charset

        def iter_lines(self, decode_unicode=True):
            for line in raw.split(b"\n"):
                yield line.decode(self.encoding) if decode_unicode else line

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    client = SnowflakeRestClient.__new__(SnowflakeRestClient)
    client._settings = SimpleNamespace(account_url="https://x")
    client._timeout = 5
    client._auth_headers = lambda: {}
    events = list(client.post_stream("/p", {}))
    assert events == [("response.text.delta", {"text": "Manual, §7.2 – São Paulo"})]


def test_rest_post_stream_parses_sse(monkeypatch):
    lines = [
        "event: response.status",
        'data: {"message": "Planning"}',
        "",
        "event: done",
        "data: [DONE]",
    ]

    class Resp:
        status_code = 200
        text = ""

        def iter_lines(self, decode_unicode=True):
            yield from lines

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    client = SnowflakeRestClient.__new__(SnowflakeRestClient)
    client._settings = SimpleNamespace(account_url="https://x")
    client._timeout = 5
    client._auth_headers = lambda: {}
    assert list(client.post_stream("/p", {})) == [
        ("response.status", {"message": "Planning"}),
        ("done", None),
    ]


# ----------------------------------------------------------------------------- cache rules


def _ok(text="a"):
    return AgentAnswer("q", text, status="completed")


def test_normalize():
    assert normalize("  Which Regions?  ") == normalize("which regions") == "which regions"


def test_standalone_questions_are_cached_even_with_history():
    c = AnswerCache(standalone_questions={"Which regions have the highest late-delivery rates?"})
    assert c.put("which regions have the highest late-delivery rates", _ok(), has_history=True)
    assert (
        c.get("Which regions have the highest late-delivery rates?", has_history=True).text == "a"
    )


def test_follow_ups_with_history_are_never_cached():
    c = AnswerCache()
    assert not c.put("break that down by mode", _ok(), has_history=True)
    c.put("break that down by mode", _ok(), has_history=False)
    assert (
        c.get("break that down by mode", has_history=True) is None
    )  # context differs -> ask the agent


def test_failed_answers_are_not_cached_and_hits_are_copies():
    c = AnswerCache()
    assert not c.put(
        "q", AgentAnswer("q", "busy", status="error", error="rate_limited: x"), has_history=False
    )
    c.put("q", _ok(), has_history=False)
    hit = c.get("q", has_history=False)
    hit.text = "mutated"
    assert c.get("q", has_history=False).text == "a" and len(c) == 1
    c.clear()
    assert len(c) == 0


# ----------------------------------------------------------------------------- page behaviour


class CountingAgent:
    """Streaming-capable fake: counts live runs."""

    def __init__(self):
        self.calls = 0

    def ask_stream(self, question, history=None):
        self.calls += 1
        yield from CopilotAgent(client=FakeStreamClient([GOOD_RUN]), backoff_s=0).ask_stream(
            question, history
        )


def _app(agent):
    from tests.test_ui import FakeData

    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["services"] = SimpleNamespace(
        agent=agent,
        data=FakeData(),
        save_feedback=lambda r: "snowflake",
        log_request=lambda r: "test",
    )
    return at


def test_repeat_suggestion_is_served_from_cache_and_labelled():
    agent = CountingAgent()
    at = _app(agent)
    at.run()
    at.sidebar.button[0].click().run()
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert agent.calls == 1
    assert any("Reused from earlier in this session" in c.value for c in at.caption)


def test_ask_again_live_bypasses_cache():
    agent = CountingAgent()
    at = _app(agent)
    at.run()
    at.sidebar.button[0].click().run()
    at.sidebar.button[0].click().run()
    live = [b for b in at.button if b.label.startswith("🔄 Ask again live")]
    assert live, "live re-ask button missing on cached answer"
    live[0].click().run()
    assert agent.calls == 2


def test_clear_conversation_clears_cache():
    agent = CountingAgent()
    at = _app(agent)
    at.run()
    at.sidebar.button[0].click().run()
    clear = [b for b in at.sidebar.button if "Clear conversation" in b.label][0]
    clear.click().run()
    at.sidebar.button[0].click().run()
    assert agent.calls == 2


@pytest.mark.parametrize("q", ["What are the supplier corrective-action deadlines?"])
def test_streaming_answer_renders_final_block(q):
    at = _app(CountingAgent())
    at.run()
    at.chat_input[0].set_value(q).run()
    assert not at.exception
    assert any("Central Africa" in m.value for m in at.markdown)  # final parsed answer from fixture
