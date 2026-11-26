"""Phase 6 agent tests.

Unit tests (CI-safe): response parsing on a real (sanitized) agent response, error handling and
fallbacks with a fake REST client, input validation, credential redaction, fail-closed config.
Live tests (SCC_RUN_SNOWFLAKE_TESTS=1): the runtime user's privilege boundary (no Cortex cost).
The paid end-to-end agent cases run via `python -m supplychain_copilot.agent.evaluate --yes`
(or here with SCC_RUN_CORTEX_TESTS=1).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests

from supplychain_copilot.agent.client import (
    CopilotAgent,
    InvalidQuestion,
    parse_response,
    redact,
    validate_question,
)
from supplychain_copilot.config import ConfigError
from supplychain_copilot.snowflake.rest import SnowflakeRestError

FIXTURE = Path(__file__).parent / "fixtures" / "agent_hybrid_response.json"


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, path, body):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _agent(outcomes, **kw):
    return CopilotAgent(client=FakeClient(outcomes), backoff_s=0, **kw)


# ----------------------------------------------------------------------------- parsing


def test_parse_real_hybrid_response():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    a = parse_response("q", raw, 1.0)
    assert a.ok and a.tools_used == {"delivery_analytics", "supplier_documents"}
    assert any(
        "SEMANTIC_VIEW" in s for s in a.sql_statements
    )  # governed semantic view, not raw tables
    sql_call = next(t for t in a.tool_calls if t.rows)
    assert sql_call.columns[:3] == ["LATE_DELIVERY_RATE", "ELIGIBLE_SHIPMENTS", "LATE_SHIPMENTS"]
    assert len(sql_call.rows) == 23 and sql_call.verified_query_used is True
    assert a.citations and all(
        c.chunk_id.startswith("WOR-") and "PDF p." in c.label for c in a.citations
    )
    assert "60.0%" in a.text and "Central Africa" in a.text
    assert a.suggested_queries


def test_chart_spec_parsed_and_bad_chart_skipped():
    spec = '{"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "mark": "bar", "data": {"values": []}}'
    resp = {
        "status": "completed",
        "content": [
            {"type": "text", "text": "x"},
            {"type": "chart", "chart": {"chart_spec": spec}},
            {"type": "chart", "chart": {"chart_spec": "{not json"}},
        ],
    }
    a = parse_response("q", resp)
    assert len(a.charts) == 1 and a.charts[0]["mark"] == "bar"


def test_duplicate_citations_collapsed():
    item = {
        "type": "text",
        "text": "x",
        "annotations": [{"doc_id": "A", "doc_title": "t"}, {"doc_id": "A", "doc_title": "t"}],
    }
    a = parse_response("q", {"status": "completed", "content": [item]})
    assert [c.chunk_id for c in a.citations] == ["A"]


# ----------------------------------------------------------------------------- guardrails


def test_input_validation():
    with pytest.raises(InvalidQuestion):
        validate_question("   ")
    with pytest.raises(InvalidQuestion):
        validate_question("x" * 2001)
    a = _agent([]).ask("")
    assert a.error.startswith("invalid") and not a.ok


def test_credentials_are_redacted():
    text, changed = redact(
        "key -----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY----- and password: hunter2"
    )
    assert changed and "abc" not in text and "hunter2" not in text


def test_retries_transient_errors_then_succeeds():
    ok = {"status": "completed", "content": [{"type": "text", "text": "answer"}]}
    client = FakeClient(
        [SnowflakeRestError(429, "busy"), SnowflakeRestError(503, "unavailable"), ok]
    )
    a = CopilotAgent(client=client, backoff_s=0).ask("question")
    assert a.ok and a.text == "answer" and client.calls == 3


def test_rate_limit_exhausted_gives_fallback_not_exception():
    a = _agent([SnowflakeRestError(429, "busy")] * 3).ask("question")
    assert not a.ok and a.error.startswith("rate_limited") and "busy right now" in a.text


@pytest.mark.parametrize(
    ("status", "reason"), [(401, "auth"), (403, "permission"), (400, "service")]
)
def test_non_retryable_errors_map_to_meaningful_fallbacks(status, reason):
    a = _agent([SnowflakeRestError(status, "nope")]).ask("question")
    assert a.error.startswith(reason) and a.text


def test_timeout_and_empty_answer_fallbacks():
    assert _agent([requests.Timeout()]).ask("q").error.startswith("timeout")
    empty = {"status": "completed", "content": [{"type": "thinking", "thinking": {"text": "..."}}]}
    assert _agent([empty]).ask("q").error.startswith("empty")


def test_agent_fails_closed_without_app_user(monkeypatch, tmp_path):
    from supplychain_copilot import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "repo")
    key = tmp_path / "k.p8"
    key.write_text("dummy")
    for k, v in {
        "SNOWFLAKE_ACCOUNT": "a-b",
        "SNOWFLAKE_USER": "DEV",
        "SNOWFLAKE_ROLE": "SCC_DEV_ROLE",
        "SNOWFLAKE_WAREHOUSE": "W",
        "SNOWFLAKE_DATABASE": "D",
        "SNOWFLAKE_PRIVATE_KEY_PATH": str(key),
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SNOWFLAKE_APP_USER", raising=False)
    monkeypatch.delenv("SNOWFLAKE_APP_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(ConfigError, match="App runtime user not configured"):
        CopilotAgent()


# ----------------------------------------------------------------------------- live

live = pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)


@pytest.mark.snowflake
@live
def test_runtime_user_is_read_only_and_governed():
    from supplychain_copilot.snowflake.connection import app_session, query

    with app_session() as c:
        ctx = query(c, "SELECT CURRENT_USER() U, CURRENT_ROLE() R, CURRENT_SECONDARY_ROLES() S")[0]
        assert ctx["R"] == "SCC_APP_ROLE" and "SCC_DEV_ROLE" not in ctx["S"]
        assert (
            query(
                c,
                "SELECT * FROM SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV METRICS orders.total_orders)",
            )[0]["TOTAL_ORDERS"]
            == 65752
        )
        for sql in (
            "SELECT COUNT(*) FROM SCC_DB.GOLD.FACT_ORDERS",
            "SELECT COUNT(*) FROM SCC_DB.BRONZE.DATACO_ORDER_LINES",
            "DELETE FROM SCC_DB.GOLD.FACT_ORDERS WHERE 1=0",
            "CREATE TABLE SCC_DB.AI.SHOULD_NOT_EXIST (A INT)",
            "USE ROLE SCC_DEV_ROLE",
        ):
            with pytest.raises(Exception):  # noqa: B017 - any Snowflake access error is the expected outcome
                query(c, sql)


cortex = pytest.mark.skipif(
    os.getenv("SCC_RUN_CORTEX_TESTS") != "1", reason="set SCC_RUN_CORTEX_TESTS=1 (paid)"
)


@pytest.mark.snowflake
@cortex
def test_agent_cases_pass():
    from supplychain_copilot.agent.evaluate import run

    failed = [
        (r.case["id"], {k: d for k, (ok, d) in r.checks.items() if not ok})
        for r in run()
        if not r.passed
    ]
    assert failed == []
