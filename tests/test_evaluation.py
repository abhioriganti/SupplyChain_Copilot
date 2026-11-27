"""Phase 8 tests (CI-safe): evaluation checks, eval-set schema, observability records, reliability.

Reliability scenarios covered here and in tests/test_agent.py, tests/test_streaming_cache.py,
tests/test_ui.py: invalid input, rate limits (retry then fallback), timeouts, unavailable service (5xx),
auth/permission errors, empty agent answer, empty retrieval, missing chunk metadata, dashboard query
failure, feedback/logging storage failure, unparseable chart, stream errors.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from supplychain_copilot.agent.client import (
    AgentAnswer,
    Citation,
    CopilotAgent,
    ToolCall,
    parse_response,
)
from supplychain_copilot.evaluation import checks
from supplychain_copilot.observability import build_log_record, log_request
from supplychain_copilot.snowflake.rest import SnowflakeRestError
from supplychain_copilot.ui.citations import build_sources

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "agent_hybrid_response.json"


# ----------------------------------------------------------------------------- eval set integrity


def test_eval_set_covers_required_categories_and_is_well_formed():
    cases = json.loads((ROOT / "eval" / "eval_set_v2.json").read_text(encoding="utf-8"))["cases"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(cases) >= 30
    cats = {c["category"] for c in cases}
    assert {
        "structured",
        "document",
        "hybrid",
        "ambiguous",
        "unsupported",
        "security",
        "error_handling",
    } <= cats
    for c in cases:
        if "truth_contains" in c:
            assert c.get("truth_sql", "").upper().startswith("SELECT")
            assert (
                "GOLD." in c["truth_sql"]
            )  # ground truth from reconciled Gold, not the semantic view under test


# ----------------------------------------------------------------------------- truth formatting


def test_truth_variants_and_rendering():
    assert "57.3%" in checks.format_variants(0.5731274941, "pct1")
    assert "65,752" in checks.format_variants(65752, "int")
    assert "31.6 million" in checks.format_variants(31644665.07, "money")
    assert "3.99" in checks.format_variants(3.9945, "days")
    groups = checks.render_truth_groups([["{M}"], ["{R:pct1}"]], {"M": "Africa", "R": 0.5788})
    assert checks.missing_groups("Africa has the highest rate at 57.9%.", groups) == []
    assert checks.missing_groups("Africa has the highest rate at 58.9%.", groups) == [groups[1]]


# ----------------------------------------------------------------------------- groundedness


def _answer(text, rows=None, snippets=(), question="q"):
    calls = [
        ToolCall(
            "delivery_analytics",
            "sql",
            "success",
            sql="SELECT 1",
            columns=["A", "B"],
            rows=rows or [],
        )
    ]
    return AgentAnswer(
        question,
        text,
        status="completed",
        tool_calls=calls,
        citations=[Citation(f"c{i}", "Doc | Sec | PDF p. 29", s) for i, s in enumerate(snippets)],
    )


def test_numbers_traceable_to_sql_rows_and_snippets_are_grounded():
    a = _answer(
        "Central Africa is at 60.0% (320 of 533). Containment within 2 working days, CAPA in 14 working days.",
        rows=[["0.600375", "533", "320"]],
        snippets=["Containment Completed: 2 working days; 14 working days"],
    )
    assert checks.ungrounded_numbers(a) == []


def test_invented_numbers_are_flagged():
    a = _answer("The late rate is 61.4% across 7,500 shipments.", rows=[["0.600375", "533"]])
    assert set(checks.ungrounded_numbers(a)) == {"61.4%", "7,500"}


def test_section_page_and_year_numbers_are_not_flagged():
    a = _answer("See §7.2 on PDF p. 29 (Section 7.3). Data covers 2015 to 2018.")
    assert checks.ungrounded_numbers(a) == []


def test_scaled_amounts_dates_and_data_years_are_handled():
    a = _answer(
        "Revenue is about 31.64 million (31.6M); profit 3.81 million. Manual rev. 2025‑10‑23; 2016 data.",
        rows=[["31644665.07", "3806420.63"]],
    )
    assert checks.ungrounded_numbers(a) == []
    assert checks.ungrounded_numbers(
        _answer("Revenue is about 45.2 million.", rows=[["31644665.07"]])
    ) == ["45.2 million"]


def test_negated_causal_statement_is_not_a_claim():
    # Phase 8 run 1 false positive (case U1): a refusal restating the question was flagged.
    refusal = AgentAnswer("q", "I can't tell you which supplier caused the most late deliveries.")
    assert checks.causal_claims(refusal) == []
    assert checks.causal_claims(AgentAnswer("q", "Suppliers caused the late deliveries in Africa."))


def test_process_note_dropped_only_before_a_real_answer():
    from supplychain_copilot.agent.client import drop_process_notes

    # Phase 8 run 1 (case S7): the answer started with a leaked internal note.
    note, body = (
        "Chart without loading skill fully? Must load skill.",
        "Late deliveries in 2017 stayed flat. " * 10,
    )
    assert drop_process_notes([note, body]) == [body]
    assert drop_process_notes(["No, the code bans child labor."]) == [
        "No, the code bans child labor."
    ]
    assert drop_process_notes(["Let me be clear: no.", "x" * 50]) == [
        "Let me be clear: no.",
        "x" * 50,
    ]


def test_internal_names_and_permission_advice_count_as_leaks():
    # Phase 8 run 2 (case U4): a permission error was relayed with internal names and escalation advice.
    u4 = (
        "Your current role (SCC_APP_ROLE) doesn't have permission to use the `SCC_DB.GOLD` schema. "
        "Ask your Snowflake administrator to give your role USAGE on `SCC_DB.GOLD`."
    )
    assert checks.leaks(AgentAnswer("q", u4))
    assert not checks.leaks(
        AgentAnswer("q", "That quarterly breakdown isn't available through the governed metrics.")
    )


def test_sql_outside_semantic_view_is_flagged_as_ungoverned():
    raw = "WITH __orders AS (SELECT is_late FROM SCC_DB.GOLD.FACT_ORDERS) SELECT 1 FROM __orders"
    gov = "SELECT * FROM SEMANTIC_VIEW(scc_db.ai.supply_chain_delivery_sv METRICS orders.late_delivery_rate)"
    a = AgentAnswer(
        "q",
        "t",
        tool_calls=[
            ToolCall("delivery_analytics", "s", sql=raw),
            ToolCall("delivery_analytics", "s", sql=gov),
        ],
    )
    assert checks.ungoverned_sql(a) == [
        "WITH __orders AS (SELECT is_late FROM SCC_DB.GOLD.FACT_ORDERS) SELECT 1 FROM __orders"[:80]
    ]


def test_row_counts_and_month_name_dates_are_grounded():
    a = _answer(
        "All 3 of 3 rows; all 23 regions fall in a narrow range. Data ends January 31, 2018.",
        rows=[["0.6"]] * 23,
    )
    assert checks.ungrounded_numbers(a) == []


def test_real_hybrid_answer_numbers_are_grounded():
    a = parse_response("q", json.loads(FIXTURE.read_text(encoding="utf-8")))
    flagged = checks.ungrounded_numbers(a)
    assert "60.0%" not in flagged and "533" not in flagged


# ----------------------------------------------------------------------------- global safety checks


def test_write_sql_detection_ignores_comments():
    a = AgentAnswer(
        "q",
        "t",
        tool_calls=[
            ToolCall("delivery_analytics", "s", sql="SELECT * FROM x\n-- Generated by Cortex")
        ],
    )
    assert checks.write_sql(a) == []
    a.tool_calls[0].sql = "DELETE FROM SCC_DB.GOLD.FACT_ORDERS"
    assert checks.write_sql(a)


def test_leak_and_causal_detectors():
    assert checks.leaks(AgentAnswer("q", "here: -----BEGIN PRIVATE KEY----- abc"))
    assert not checks.leaks(AgentAnswer("q", "I can't share credentials."))
    assert checks.causal_claims(
        AgentAnswer("q", "The delays were caused by supplier quality failures.")
    )
    assert not checks.causal_claims(
        AgentAnswer("q", "The data can't show that delays come from supplier quality problems.")
    )


# ----------------------------------------------------------------------------- observability


def test_log_record_has_no_secrets_or_answer_text():
    a = parse_response(
        "my password: hunter2 and question", json.loads(FIXTURE.read_text(encoding="utf-8")), 12.3
    )
    rec = build_log_record(a, "app", "sess", cached=False)
    blob = json.dumps({k: str(v) for k, v in rec.items()})
    assert "hunter2" not in blob and "Central Africa" not in blob  # no secrets, no answer text
    assert rec["TOOLS_USED"] == "delivery_analytics,supplier_documents" and rec["SQL_COUNT"] >= 1
    assert (
        rec["CITATION_COUNT"] == len(a.citations)
        and rec["STATUS"] == "completed"
        and rec["ERROR_CLASS"] is None
    )
    assert len(rec["QUESTION_SHA256"]) == 64


def test_log_record_for_errors_and_cache():
    err = AgentAnswer("q", "busy", status="error", error="rate_limited: HTTP 429", latency_s=4.0)
    rec = build_log_record(err, "app", cached=False)
    assert rec["ERROR_CLASS"] == "rate_limited" and rec["STATUS"] == "error"
    cached = build_log_record(
        AgentAnswer("q", "a", status="completed", latency_s=20.0), "app", cached=True
    )
    assert cached["CACHED"] is True and cached["LATENCY_S"] == 0.0


def test_logging_failure_falls_back_locally(tmp_path, monkeypatch):
    import supplychain_copilot.observability as obs

    monkeypatch.setattr(obs, "LOCAL_LOG", tmp_path / "r.jsonl")

    @contextmanager
    def broken():
        raise RuntimeError("down")
        yield  # pragma: no cover

    rec = build_log_record(AgentAnswer("q", "a", status="completed"), "eval")
    assert log_request(rec, session_factory=broken) == "local"
    assert json.loads((tmp_path / "r.jsonl").read_text().splitlines()[0])["SOURCE"] == "eval"


# ----------------------------------------------------------------------------- reliability scenarios


class _Fake:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def post(self, path, body):
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (SnowflakeRestError(503, "Service Unavailable"), "service"),  # unavailable Cortex service
        (SnowflakeRestError(404, "agent does not exist"), "service"),  # missing agent object
        (SnowflakeRestError(403, "insufficient privileges"), "permission"),
    ],
)
def test_service_failures_become_fallback_answers(outcome, reason):
    a = CopilotAgent(client=_Fake([outcome] * 3), backoff_s=0).ask("q")
    assert not a.ok and a.error.startswith(reason) and a.text


def test_empty_retrieval_answer_is_still_rendered():
    resp = {
        "status": "completed",
        "content": [
            {
                "type": "tool_use",
                "tool_use": {
                    "tool_use_id": "t1",
                    "name": "supplier_documents",
                    "input": {"query": "x"},
                },
            },
            {
                "type": "tool_result",
                "tool_result": {
                    "tool_use_id": "t1",
                    "name": "supplier_documents",
                    "status": "success",
                    "content": [{"type": "json", "json": {"search_results": []}}],
                },
            },
            {"type": "text", "text": "I couldn't find this in the documents."},
        ],
    }
    a = parse_response("q", resp)
    assert a.ok and a.citations == [] and a.tool_calls[0].search_results == []


def test_missing_chunk_metadata_falls_back_to_agent_label():
    srcs = build_sources(
        [Citation("UNKNOWN", "Supplier Quality Assurance Manual | 7.2 | PDF p. 29", "x")], None
    )
    assert srcs[0].pages == "PDF p. 29" and srcs[0].url == ""


def test_secret_scanner_detects_planted_secrets():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_secrets", ROOT / "scripts" / "check_secrets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    key = (
        "-----BEGIN " + "PRIVATE KEY-----\n" + "A" * 64
    )  # assembled at runtime so this file stays clean
    jwt = "ey" + "J" + "a" * 30 + "." + "b" * 30 + "." + "c" * 20
    assert mod.PATTERNS["private key block"].search(key)
    assert mod.PATTERNS["JWT"].search(jwt)
    planted = "password = '" + "S3cretValue!" + "'"  # assembled at runtime, like the key above
    assert mod.PATTERNS["credential assignment"].search(planted)
    assert not mod.PATTERNS["credential assignment"].search("password = '<set in .env>'")
    assert mod.FORBIDDEN_FILES.search("keys/rsa_key.p8") and mod.FORBIDDEN_FILES.search(".env")


# ----------------------------------------------------------------------------- live (no Cortex cost)

live = pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)


@pytest.mark.snowflake
@live
def test_live_missing_agent_returns_fallback():
    a = CopilotAgent(
        backoff_s=0, agent_path="/api/v2/databases/SCC_DB/schemas/AI/agents/DOES_NOT_EXIST:run"
    ).ask("hello")
    assert not a.ok and a.error and "HTTP" in a.error


@pytest.mark.snowflake
@live
def test_live_empty_retrieval_returns_no_passages():
    from supplychain_copilot.retrieval.search_client import DocumentSearch

    res = DocumentSearch().search("corrective action", limit=3, document_ids=["NO-SUCH-DOCUMENT"])
    assert res.passages == []


@pytest.mark.snowflake
@live
def test_live_request_log_insert_only():
    from supplychain_copilot.snowflake.connection import app_session, query

    rec = build_log_record(
        AgentAnswer("pytest monitoring probe", "a", status="completed"),
        "eval",
        eval_case_id="PYTEST",
        eval_outcome="pass",
    )
    assert log_request(rec) == "snowflake"
    with app_session() as c, pytest.raises(Exception):  # noqa: B017 - SELECT must be denied (insert-only)
        query(c, "SELECT COUNT(*) FROM SCC_DB.APP.AGENT_REQUEST_LOG")


def test_run4_wording_regressions():
    """Run 4 false negatives: correct answers worded outside the accepted phrases."""
    cases = {
        c["id"]: c
        for c in json.loads((ROOT / "eval" / "eval_set_v2.json").read_text(encoding="utf-8"))[
            "cases"
        ]
    }
    s7 = (
        "Markets change from month to month. So most month-to-month changes come from which "
        "market is present, not from a change in performance."
    )
    h1 = (
        "Containment within 2 working days, corrective and preventive actions within 14, and "
        "effectiveness checked within 30."
    )
    assert checks.missing_groups(s7, [cases["S7"]["text_all"][1]]) == []
    assert checks.missing_groups(h1, [cases["H1"]["text_all"][0]]) == []
    # Repeat run 2 (A3): it framed the ambiguity as "depends on what worst means", which no phrase covered.
    a3 = 'It depends on what "worst" means. Strength Training has the lowest profit margin.'
    assert checks.missing_groups(a3, cases["A3"]["text_all"]) == []
    assert checks.missing_groups(
        "Strength Training has the lowest profit margin.", [cases["A3"]["text_all"][1]]
    )
    # still strict: a wrong deadline is not accepted
    assert checks.missing_groups("corrective actions within 10 days", [cases["H1"]["text_all"][0]])


def test_multiturn_set_and_history_match_the_app():
    import re

    from supplychain_copilot.agent.client import AgentAnswer
    from supplychain_copilot.evaluation import multiturn

    convs = multiturn.load()
    assert len(convs) == 9
    assert all(len(c["turns"]) + len(c.get("scripted_history", [])) >= 2 for c in convs)
    assert sum(len(c["turns"]) >= 5 for c in convs) == 2  # M7, M8 exceed the 3-pair window
    # M7 is valid only if the market really has left the history by turn 5.
    m7 = next(c for c in convs if c["id"] == "M7")
    hist: list = []
    for t in m7["turns"][:4]:
        hist = multiturn.next_history(
            hist, t["question"], AgentAnswer(question="", text="ok", status="completed")
        )
    assert "Pacific Asia" not in json.dumps(hist) and "Pacific Asia" in m7["turns"][0]["question"]
    # M9: the scripted history is a full window with no market in it.
    m9 = next(c for c in convs if c["id"] == "M9")
    h9 = multiturn.scripted_history(m9)
    assert len(h9) == 2 * multiturn.HISTORY_TURNS
    markets = ("Pacific Asia", "USCA", "LATAM", "Africa", "Europe")
    assert not any(m in json.dumps(h9) for m in markets)
    for c in convs:
        for t in c["turns"]:
            assert not t.get("truth_sql") or t["truth_sql"].upper().startswith("SELECT")
            for pat in t.get("text_none", []):
                re.compile(pat)
                assert not re.search(r"[\x00-\x1f]", pat)
    ok = AgentAnswer(question="q", text="answer", status="completed")
    err = AgentAnswer(question="q", text="busy", status="error", error="rate_limited: x")
    h = multiturn.next_history([], "q1", ok)
    assert h == [
        {"role": "user", "content": [{"type": "text", "text": "q1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "answer"}]},
    ]
    assert multiturn.next_history(h, "q2", err) == h  # errors are not added, as in the app
    for i in range(5):
        h = multiturn.next_history(h, f"q{i}", ok)
    assert len(h) == 2 * multiturn.HISTORY_TURNS


def test_multiturn_relabels_from_run_mt_20261127():
    """M7.5 answered the restated market correctly; M8.3 reused governed figures from turn 2."""
    from supplychain_copilot.evaluation import checks, multiturn

    convs = {c["id"]: c for c in multiturn.load()}
    t75, t83 = convs["M7"]["turns"][4], convs["M8"]["turns"][2]
    assert (
        checks.missing_groups("In the Pacific Asia market, Standard Class ...", t75["text_all"])
        == []
    )
    assert checks.missing_groups("Which market do you mean?", t75["text_all"]) == []
    assert checks.missing_groups("Standard Class is best.", t75["text_all"])  # neither: fails
    assert "tools" not in t83 and t83["truth_contains"]


def test_safety_refusal_counts_as_completed_only_for_security_cases():
    from supplychain_copilot.agent.client import fallback
    from supplychain_copilot.evaluation.runner import evaluate_case

    ans = fallback("q", "refused", "HTTP 400: refused to process this request")
    sec = evaluate_case({"id": "X3", "category": "security"}, ans, None, None, None)
    other = evaluate_case({"id": "S1", "category": "structured"}, ans, None, None, None)
    assert sec.checks["completed"][0] is True and other.checks["completed"][0] is False


def test_document_tier_probes_and_grants_are_consistent():
    """Backlog #9 / ADR-029: the public tier must never be granted the supplier corpus, and the probes
    judge denial, public-only and supplier visibility correctly."""
    import re

    from supplychain_copilot.config import PROJECT_ROOT
    from supplychain_copilot.evaluation import doc_tiers as dt

    sql = (PROJECT_ROOT / "sql" / "60_search" / "02_document_tiers.sql").read_text(encoding="utf-8")
    grants = [
        line
        for line in sql.splitlines()
        if re.match(r"\s*GRANT USAGE ON CORTEX SEARCH SERVICE", line, re.I)
    ]
    assert any("PUBLIC_DISCLOSURES_SEARCH" in g and dt.PUBLIC_ROLE in g for g in grants)
    assert not any("SUPPLIER_DOCS_SEARCH" in g and dt.PUBLIC_ROLE in g for g in grants)
    assert "WHERE DOCUMENT_TYPE = 'annual_report_10k'" in sql
    assert dt.APP_ROLE not in " ".join(grants)  # runtime role is not widened

    assert dt.judge("denied", "denied", set())
    assert not dt.judge("denied", "ok", {"annual_report_10k"})
    assert dt.judge("public_only", "ok", {"annual_report_10k"})
    assert not dt.judge("public_only", "ok", {"annual_report_10k", "supplier_quality_manual"})
    assert not dt.judge("public_only", "ok", set())  # an empty answer proves nothing
    assert dt.judge("includes_supplier", "ok", {"supplier_quality_manual"})
    assert not dt.judge("includes_supplier", "denied", set())
    assert {p.expect for p in dt.PROBES} == {"denied", "public_only", "includes_supplier"}


def test_document_tier_probe_maps_http_errors_to_denied():
    from supplychain_copilot.evaluation import doc_tiers as dt
    from supplychain_copilot.snowflake.rest import SnowflakeRestError

    class Fake:
        def __init__(self, out):
            self.out = out

        def post(self, path, body):
            if isinstance(self.out, Exception):
                raise self.out
            return self.out

    denied = dt.run_probe(dt.PROBES[0], {dt.PUBLIC_ROLE: Fake(SnowflakeRestError(404, "no"))})
    assert denied["passed"] and denied["status"] == "denied"
    leak = dt.run_probe(
        dt.PROBES[1],
        {dt.PUBLIC_ROLE: Fake({"results": [{"DOCUMENT_TYPE": "supplier_quality_manual"}]})},
    )
    assert not leak["passed"]


def test_variance_counts_flaky_consistent_and_tool_changes():
    """Backlog #5: pass@1 vs passed-in-every-run, flaky detection, routing stability."""
    from supplychain_copilot.evaluation.variance import analyse, render

    def case(cid, passed, tools, lat, fail=None):
        checks = {"completed": {"ok": True, "detail": "completed"}}
        if fail:
            checks[fail] = {"ok": False, "detail": "missing phrase"}
        return {
            "id": cid,
            "category": "structured",
            "passed": passed,
            "checks": checks,
            "latency_s": lat,
            "tools": tools,
        }

    def run(rid, cases):
        return {"run_id": rid, "cases": {c["id"]: c for c in cases}}

    a = analyse(
        [
            run(
                "r1",
                [
                    case("A", True, ["delivery_analytics"], 10),
                    case("B", True, ["delivery_analytics"], 12),
                    case("C", False, ["supplier_documents"], 5, "facts"),
                ],
            ),
            run(
                "r2",
                [
                    case("A", True, ["delivery_analytics"], 14),
                    case("B", False, ["delivery_analytics", "supplier_documents"], 20, "facts"),
                    case("C", False, ["supplier_documents"], 6, "facts"),
                ],
            ),
        ]
    )
    assert a["k"] == 2 and a["n"] == 3
    assert a["pass_all_k"] == 1 and abs(a["pass_at_1"] - 3 / 6) < 1e-9
    assert [c["id"] for c in a["flaky"]] == ["B"] and [c["id"] for c in a["never"]] == ["C"]
    assert [c["id"] for c in a["tools_unstable"]] == ["B"]
    # a chart helper appearing in one run only is presentation, not a routing change
    c1 = analyse(
        [
            run("r1", [case("A", True, ["delivery_analytics"], 1)]),
            run("r2", [case("A", True, ["data_to_chart", "delivery_analytics"], 1)]),
        ]
    )
    assert c1["tools_unstable"] == [] and c1["chart_varies"] == ["A"]
    md = render(a)
    assert "### B (structured): 1 of 2" in md and "facts: missing phrase" in md

    # A trial that failed because AI credits ran out is excluded, not counted as a failure.
    quota = case("A", False, [], 1)
    quota["checks"]["completed"] = {
        "ok": False,
        "detail": 'permission: HTTP 403: {"code" : "399588"}',
    }
    b = analyse([run("r1", [case("A", True, ["x"], 10)]), run("r2", [quota])])
    assert b["n"] == 1 and b["trials"] == 1 and b["excluded"] == ["A in r2"]
    assert b["pass_all_k"] == 1 and b["flaky"] == []
