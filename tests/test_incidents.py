"""Phase 9 incident workflow: state machine, separation of duties, hash chain, service, API."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from supplychain_copilot.incidents import model
from supplychain_copilot.incidents.api import create_app
from supplychain_copilot.incidents.model import IncidentInput
from supplychain_copilot.incidents.service import TOKEN_HEADER, IncidentService, WorkflowUnavailable
from supplychain_copilot.incidents.store import InMemoryStore

TOKEN = "t" * 32
ROOT = Path(__file__).resolve().parents[1]


def _input(**kw) -> IncidentInput:
    base = {
        "title": "Burrs on valve housings",
        "supplier": "Supplier A (simulated)",
        "part": "VH-100",
        "description": "Receiving inspection found burrs on 40 of 500 housings.",
        "severity": "High",
        "requester": "Alex Requester",
    }
    return IncidentInput(**{**base, **kw})


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("SCC_WORKFLOW_TOKEN", TOKEN)
    calls = []

    def post(url, json, headers, timeout):
        calls.append((url, json, headers))
        return FakeResponse()

    s = IncidentService(
        InMemoryStore(),
        drafter=lambda f: {
            "draft": "Protect receiving plants within 48 hours (SQAM 7.1, p. 27).",
            "citations": ["SQAM | 7.1 | PDF p. 27"],
        },
        post=post,
        webhook_url="http://n8n.test/webhook/x",
    )
    s.calls = calls
    return s


def _approved_flow(s: IncidentService) -> str:
    inc = s.open(_input()).incident_id
    s.draft(inc)
    s.submit(inc)
    s.record_workflow_event(inc, model.SUBMITTED, "n8n", {"approval_url": "http://n8n/form/1"})
    s.record_workflow_event(inc, model.APPROVED, "Sam Approver", {"comment": "Issue a CAR"})
    s.record_workflow_event(inc, model.ACTION_SIMULATED, "n8n", {"action": "CAR drafted, not sent"})
    return inc


def test_happy_path_is_chained_and_ends_in_simulated_action(svc):
    inc = _approved_flow(svc)
    h = svc.store.history(inc)
    assert [e.event_type for e in h] == [
        "CREATED",
        "DRAFTED",
        "SUBMITTED_FOR_APPROVAL",
        "APPROVED",
        "ACTION_SIMULATED",
    ]
    assert model.verify_chain(h) == []
    assert all(e.simulated and e.details["simulated"] for e in h)
    assert h[0].actor == "Alex Requester" and h[3].actor_type == "human"
    url, body, headers = svc.calls[0]
    assert (
        headers[TOKEN_HEADER] == TOKEN and body["simulated"] and "48 hours" in body["draft_excerpt"]
    )


def test_requester_cannot_approve_own_incident(svc):
    inc = svc.open(_input()).incident_id
    svc.submit(inc)
    svc.record_workflow_event(inc, model.SUBMITTED, "n8n", {})
    with pytest.raises(model.SeparationOfDutiesError):
        svc.record_workflow_event(inc, model.APPROVED, "  alex   REQUESTER ", {})
    assert model.status_of(svc.store.history(inc)) == model.SUBMITTED


@pytest.mark.parametrize(
    "steps, bad",
    [
        ([], model.APPROVED),  # no decision before submission
        ([model.SUBMITTED, model.REJECTED], model.ACTION_SIMULATED),  # rejected stays rejected
        ([model.SUBMITTED, model.TIMED_OUT], model.APPROVED),  # timeout is terminal
        ([model.SUBMITTED, model.APPROVED, model.ACTION_SIMULATED], model.APPROVED),
    ],
)
def test_invalid_transitions_are_refused(svc, steps, bad):
    inc = svc.open(_input()).incident_id
    for step in steps:
        actor = "Sam Approver" if step in model.DECISIONS else "n8n"
        svc.record_workflow_event(inc, step, actor, {})
    with pytest.raises(model.TransitionError):
        svc.record_workflow_event(inc, bad, "Sam Approver", {})


def test_workflow_cannot_record_requester_or_agent_events(svc):
    inc = svc.open(_input()).incident_id
    for t in (model.CREATED, model.DRAFTED, model.ERROR):
        with pytest.raises(model.TransitionError):
            svc.record_workflow_event(inc, t, "n8n", {})


def test_tampering_is_detected():
    from dataclasses import replace

    s = IncidentService(InMemoryStore())
    inc = s.open(_input()).incident_id
    s.record_workflow_event(inc, model.SUBMITTED, "n8n", {})
    s.record_workflow_event(inc, model.REJECTED, "Sam Approver", {"comment": "not a defect"})
    h = s.store.history(inc)
    edited = replace(h[2], payload=h[2].payload.replace("REJECTED", "APPROVED"))
    assert model.verify_chain([h[0], h[1], edited])  # payload no longer matches its hash
    assert model.verify_chain([h[0], h[2]])  # a removed event breaks the link and sequence


def test_input_validation_and_redaction():
    with pytest.raises(model.InvalidInput):
        _input(severity="urgent").cleaned()
    with pytest.raises(model.InvalidInput):
        _input(title="   ").cleaned()
    with pytest.raises(model.InvalidInput):
        _input(description="x" * 2001).cleaned()
    cleaned = _input(description="Found burrs. password: hunter2 was on the label").cleaned()
    assert "hunter2" not in cleaned["description"] and cleaned["severity"] == "high"


def test_draft_failure_and_unreachable_workflow_are_recorded_not_lost(monkeypatch):
    monkeypatch.setenv("SCC_WORKFLOW_TOKEN", TOKEN)

    def boom(*a, **k):
        raise ConnectionError("n8n down")

    def bad_draft(fields):
        raise RuntimeError("agent unavailable")

    s = IncidentService(InMemoryStore(), drafter=bad_draft, post=boom)
    inc = s.open(_input()).incident_id
    assert s.draft(inc).event_type == model.ERROR
    with pytest.raises(WorkflowUnavailable):
        s.submit(inc)
    h = s.store.history(inc)
    assert [e.event_type for e in h] == ["CREATED", "ERROR", "ERROR"]
    assert h[2].details == {
        "stage": "submit",
        "error": "ConnectionError",
        "event_type": "ERROR",
        "simulated": True,
    }


def test_submit_requires_token(monkeypatch):
    monkeypatch.delenv("SCC_WORKFLOW_TOKEN", raising=False)
    s = IncidentService(InMemoryStore(), post=lambda *a, **k: FakeResponse())
    inc = s.open(_input()).incident_id
    with pytest.raises(WorkflowUnavailable):
        s.submit(inc)  # missing token is recorded as an ERROR, not sent without auth


# ----------------------------------------------------------------------------- API


@pytest.fixture
def api(svc):
    return TestClient(create_app(svc, token=TOKEN)), svc


def test_api_rejects_missing_or_wrong_token(api):
    client, svc = api
    inc = svc.open(_input()).incident_id
    body = {"event_type": "SUBMITTED_FOR_APPROVAL", "actor": "n8n", "details": {}}
    assert client.post(f"/incidents/{inc}/events", json=body).status_code == 401
    r = client.post(f"/incidents/{inc}/events", json=body, headers={TOKEN_HEADER: "wrong"})
    assert r.status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_api_records_decision_and_maps_errors(api):
    client, svc = api
    h = {TOKEN_HEADER: TOKEN}
    inc = svc.open(_input()).incident_id
    ok = client.post(
        f"/incidents/{inc}/events",
        json={
            "event_type": "SUBMITTED_FOR_APPROVAL",
            "actor": "n8n",
            "details": {"approval_url": "http://n8n/form/1"},
        },
        headers=h,
    )
    assert ok.status_code == 200 and ok.json()["seq"] == 2
    own = client.post(
        f"/incidents/{inc}/events",
        json={"event_type": "APPROVED", "actor": "Alex Requester", "details": {}},
        headers=h,
    )
    assert own.status_code == 409 and "different person" in own.json()["detail"]
    unknown = client.post(
        "/incidents/INC-NOPE/events",
        json={"event_type": "SUBMITTED_FOR_APPROVAL", "actor": "n8n"},
        headers=h,
    )
    assert unknown.status_code == 404
    bad = client.post(f"/incidents/{inc}/events", json={"event_type": "x", "actor": ""}, headers=h)
    assert bad.status_code == 422
    rejected = client.post(
        f"/incidents/{inc}/events",
        json={"event_type": "REJECTED", "actor": "Sam Approver", "details": {"comment": "x" * 900}},
        headers=h,
    )
    assert rejected.status_code == 200
    assert len(svc.store.history(inc)[-1].details["comment"]) == 500  # bounded


@pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)
@pytest.mark.snowflake
def test_live_snowflake_chain_matches_sql_check(monkeypatch):
    """Writes one simulated incident as the runtime role and checks the SQL chain recomputation."""
    from supplychain_copilot.incidents.store import SnowflakeIncidentStore

    s = IncidentService(SnowflakeIncidentStore())
    inc = s.open(_input(title="Live test incident (automated test)")).incident_id
    s.record_workflow_event(inc, model.SUBMITTED, "n8n", {"approval_url": "test"})
    s.record_workflow_event(inc, model.REJECTED, "Test Approver", {"comment": "automated test"})
    assert model.verify_chain(s.store.history(inc)) == []
    row = next(r for r in s.store.chain_check() if r["INCIDENT_ID"] == inc)
    assert row["CHAIN_OK"] is True and row["EVENTS"] == 3
    status = next(r for r in s.store.statuses() if r["INCIDENT_ID"] == inc)
    assert status["STATUS"] == "REJECTED" and status["DECIDED_BY"] == "Test Approver"


# ----------------------------------------------------------------------------- n8n workflow file


def test_committed_workflow_matches_builder_and_holds_no_secrets():
    from supplychain_copilot.incidents import n8n_workflow as wf

    text = wf.WORKFLOW_FILE.read_text(encoding="utf-8")
    assert text == wf.render(), "run: python -m supplychain_copilot.incidents.n8n_workflow"
    assert "$env.SCC_WORKFLOW_TOKEN" in text
    token = os.getenv("SCC_WORKFLOW_TOKEN")
    if token:
        assert token not in text
    assert "credentials" not in text and "password" not in text.lower()


def test_workflow_graph_covers_every_outcome():
    from supplychain_copilot.incidents import n8n_workflow as wf

    w = wf.build()
    names = {n["name"] for n in w["nodes"]}
    bodies = " ".join(n["parameters"].get("jsonBody", "") for n in w["nodes"])
    for event in (
        "SUBMITTED_FOR_APPROVAL",
        "TIMED_OUT",
        "APPROVED",
        "REJECTED",
        "ACTION_SIMULATED",
    ):
        assert f"event_type: '{event}'" in bodies
    for src, out in w["connections"].items():
        assert src in names
        for branch in out["main"]:
            assert all(c["node"] in names for c in branch)
    wait = next(n for n in w["nodes"] if n["type"] == "n8n-nodes-base.wait")
    assert wait["parameters"]["resume"] == "form" and wait["parameters"]["limitWaitTime"]
    # self-approval loops back to the form (via the optional Slack notification) instead of ending
    c = w["connections"]
    assert c["Record: re-request approval"]["main"][0][0]["node"] == "Slack configured?"
    assert {b[0]["node"] for b in c["Slack configured?"]["main"]} >= {"Human approval"}
    assert c["Notify Slack: approval needed"]["main"][0][0]["node"] == "Human approval"


def test_form_excerpt_is_plain_text():
    from supplychain_copilot.incidents.service import plain_text

    md = "**Steps under Section 7.1 (PDF p. 27)**\n- Confirm **within 48 hours**.\n## Deadlines\n* `2` days"
    assert (
        plain_text(md)
        == "Steps under Section 7.1 (PDF p. 27)\n• Confirm within 48 hours.\nDeadlines\n• 2 days"
    )


def test_slack_notifications_are_optional_best_effort_and_secret_free():
    from supplychain_copilot.incidents import n8n_workflow as wf

    w = wf.build()
    nodes = {n["name"]: n for n in w["nodes"]}
    for name in ("Notify Slack: approval needed", "Notify Slack: outcome"):
        n = nodes[name]
        assert n["parameters"]["url"] == "={{ $env.SCC_SLACK_WEBHOOK_URL }}"
        assert n["onError"] == "continueRegularOutput"  # Slack down never blocks the approval
    c = w["connections"]
    # both the first request and a re-opened form notify, then wait; unconfigured skips Slack
    assert c["Record: awaiting approval"]["main"][0][0]["node"] == "Slack configured?"
    assert c["Record: re-request approval"]["main"][0][0]["node"] == "Slack configured?"
    assert [b[0]["node"] for b in c["Slack configured?"]["main"]] == [
        "Notify Slack: approval needed",
        "Human approval",
    ]
    for outcome in ("Record: simulated action", "Record: rejected", "Record: timed out"):
        assert c[outcome]["main"][0][0]["node"] == "Slack configured? (outcome)"
    body = nodes["Notify Slack: approval needed"]["parameters"]["jsonBody"]
    assert "$execution.resumeFormUrl" in body and "hooks.slack.com" not in wf.render()


def test_secret_scanner_detects_slack_webhooks_and_tokens():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_secrets", ROOT / "scripts" / "check_secrets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hook = "https://hooks.slack" + ".com/services/T0000/B0000/" + "x" * 24  # assembled at runtime
    assert mod.PATTERNS["Slack webhook URL"].search(hook)
    assert mod.PATTERNS["Slack token"].search("xox" + "b-123456789012-abcdef")
    assert not mod.PATTERNS["Slack webhook URL"].search("SCC_SLACK_WEBHOOK_URL=")


def test_hash_v2_covers_actor_time_and_order_and_v1_rows_still_verify():
    """Phase 10 audit: v1 hashed only the payload, so editing ACTOR (who approved) went undetected."""
    from dataclasses import replace
    from datetime import timedelta

    s = IncidentService(InMemoryStore())
    inc = s.open(_input()).incident_id
    s.record_workflow_event(inc, model.SUBMITTED, "n8n", {})
    s.record_workflow_event(inc, model.APPROVED, "Sam Approver", {"comment": "ok"})
    h = s.store.history(inc)
    assert all(e.hash_version == 2 for e in h) and model.verify_chain(h) == []
    for tampered in (
        replace(h[2], actor="Someone Else"),
        replace(h[2], actor_type="workflow"),
        replace(h[2], created_at_utc=h[2].created_at_utc + timedelta(seconds=1)),
        replace(h[2], event_type="REJECTED"),
    ):
        assert model.verify_chain([h[0], h[1], tampered]), tampered
    # a v1 row (payload-only hash, as written in Phase 9) still verifies by its own rule
    v1 = replace(h[0], hash_version=1, event_hash=model.chain_hash(model.GENESIS, h[0].payload))
    assert model.verify_chain([v1]) == []
    assert not model.verify_chain([replace(v1, actor="Someone Else")])  # v1 limitation, documented
