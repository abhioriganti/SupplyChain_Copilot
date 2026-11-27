"""Builds the n8n workflow JSON for the SIMULATED supplier-incident approval (Phase 9).

    .venv\\Scripts\\python -m supplychain_copilot.incidents.n8n_workflow   # writes n8n/workflows/*.json

Node types and typeVersions are those of n8n 2.47.5 (the pinned image). The workflow holds no
secrets: the shared token and callback URL come from the container environment via $env.

Flow:
  Webhook -> token valid? -> record SUBMITTED_FOR_APPROVAL (with the form URL) -> Wait for form
    -> timed out?           -> record TIMED_OUT
    -> approver = requester -> record SUBMITTED_FOR_APPROVAL again (reason) -> back to the form
    -> approved?            -> record APPROVED -> record ACTION_SIMULATED (nothing is sent)
                            -> record REJECTED
"""

from __future__ import annotations

import json
import uuid

from supplychain_copilot.config import PROJECT_ROOT

WORKFLOW_FILE = PROJECT_ROOT / "n8n" / "workflows" / "supplier_incident_approval.json"
WEBHOOK_PATH = "scc-supplier-incident"
WORKFLOW_ID = "sccSupplierIncident1"  # fixed so re-imports update the same workflow
_NS = uuid.UUID("5d0c7f3e-9a41-4f3c-8a0e-2b7d6c1e9f10")
INCIDENT = "$('Incident submitted').item.json.body"


def _id(name: str) -> str:
    return str(uuid.uuid5(_NS, name))


def _if(name: str, expr: str, pos: tuple[int, int]) -> dict:
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": list(pos),
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                "conditions": [
                    {
                        "id": _id(name + "-c"),
                        "leftValue": "={{ " + expr + " }}",
                        "rightValue": "",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "looseTypeValidation": True,
            "options": {},
        },
    }


def _record(name: str, event_type: str, actor: str, details: str, pos: tuple[int, int]) -> dict:
    """HTTP callback to the incident API. actor/details are JS expressions."""
    body = (
        "={{ JSON.stringify({ event_type: '"
        + event_type
        + "', actor: "
        + actor
        + ", details: "
        + details
        + " }) }}"
    )
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": list(pos),
        "parameters": {
            "method": "POST",
            "url": "={{ $env.SCC_INCIDENT_API }}/incidents/{{ "
            + INCIDENT
            + ".incident_id }}/events",
            "sendHeaders": True,
            "specifyHeaders": "keypair",
            "headerParameters": {
                "parameters": [
                    {"name": "X-SCC-Workflow-Token", "value": "={{ $env.SCC_WORKFLOW_TOKEN }}"}
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body,
            "options": {},
        },
    }


def _slack(name: str, payload_js: str, pos: tuple[int, int]) -> dict:
    """POST to a Slack Incoming Webhook whose URL (the secret) comes from the container env.

    Best-effort: onError=continueRegularOutput, so a Slack outage never blocks the approval."""
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": list(pos),
        "onError": "continueRegularOutput",
        "parameters": {
            "method": "POST",
            "url": "={{ $env.SCC_SLACK_WEBHOOK_URL }}",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify(" + payload_js + ") }}",
            "options": {},
        },
    }


APPROVAL_NEEDED_JS = (
    "{ text: 'Approval needed: ' + INC.incident_id + ' ' + INC.title, blocks: ["
    "{ type: 'header', text: { type: 'plain_text', text: 'Approval needed: simulated supplier-quality incident' } },"
    "{ type: 'section', text: { type: 'mrkdwn', text: '*' + INC.incident_id + '*: ' + INC.title"
    " + '\\nSupplier: ' + INC.supplier + '  |  Part: ' + INC.part + '  |  Severity: *' + INC.severity + '*'"
    " + '\\nRequested by: ' + INC.requester"
    " + ($('Record: re-request approval').isExecuted ? '\\n:warning: Form re-opened: the approver must differ from the requester.' : '') } },"
    "{ type: 'section', text: { type: 'mrkdwn', text: '*Copilot draft* (verify against the cited pages):\\n'"
    " + (INC.draft_excerpt || '(no draft)').slice(0, 1500) } },"
    "{ type: 'actions', elements: [ { type: 'button', style: 'primary',"
    " text: { type: 'plain_text', text: 'Open approval form' }, url: $execution.resumeFormUrl } ] },"
    "{ type: 'context', elements: [ { type: 'mrkdwn', text: 'Simulated practice record: nothing is sent"
    " to the supplier. You cannot approve an incident you requested.' } ] } ] }"
).replace("INC.", INCIDENT + ".")

OUTCOME_JS = (
    "{ text: INC.incident_id + ': ' + $json.event_type, blocks: ["
    "{ type: 'section', text: { type: 'mrkdwn', text: ({"
    " ACTION_SIMULATED: ':white_check_mark: *Approved* by ' + ($('Human approval').item.json['Approver name'] || '')"
    " + ': corrective action request drafted for ' + INC.supplier + ' (SIMULATED: not sent)',"
    " REJECTED: ':no_entry: *Rejected* by ' + ($('Human approval').item.json['Approver name'] || ''),"
    " TIMED_OUT: ':hourglass: *Timed out*: no decision within 24 hours' }[$json.event_type]"
    " || $json.event_type) + '\\n*' + INC.incident_id + '*: ' + INC.title } } ] }"
).replace("INC.", INCIDENT + ".")


def build() -> dict:
    form_description = (
        "=SIMULATED supplier-quality incident (practice record; nothing will be sent).\n\n"
        "Incident: {{ " + INCIDENT + ".incident_id }}\n"
        "Title: {{ " + INCIDENT + ".title }}\n"
        "Supplier: {{ " + INCIDENT + ".supplier }} | Part: {{ " + INCIDENT + ".part }} | "
        "Severity: {{ " + INCIDENT + ".severity }}\n"
        "Requested by: {{ " + INCIDENT + ".requester }}\n\n"
        "Copilot draft of the applicable procedures (verify against the cited manual pages):\n"
        "{{ " + INCIDENT + ".draft_excerpt || '(no draft)' }}\n\n"
        "You cannot approve an incident you requested."
    )
    nodes = [
        {
            "id": _id("Incident submitted"),
            "name": "Incident submitted",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [0, 300],
            "webhookId": _id("webhook"),
            "parameters": {
                "httpMethod": "POST",
                "path": WEBHOOK_PATH,
                "authentication": "none",
                "responseMode": "onReceived",
                "options": {},
            },
        },
        _if(
            "Token valid?",
            "$json.headers['x-scc-workflow-token'] === $env.SCC_WORKFLOW_TOKEN",
            (220, 300),
        ),
        _record(
            "Record: awaiting approval",
            "SUBMITTED_FOR_APPROVAL",
            "'n8n'",
            "{ approval_url: $execution.resumeFormUrl }",
            (440, 300),
        ),
        {
            "id": _id("Human approval"),
            "name": "Human approval",
            "type": "n8n-nodes-base.wait",
            "typeVersion": 1.1,
            "position": [660, 300],
            "webhookId": _id("wait"),
            "parameters": {
                "resume": "form",
                "formTitle": "Approve simulated supplier-quality incident",
                "formDescription": form_description,
                "formFields": {
                    "values": [
                        {
                            "fieldLabel": "Decision",
                            "fieldType": "dropdown",
                            "fieldOptions": {
                                "values": [{"option": "Approve"}, {"option": "Reject"}]
                            },
                            "requiredField": True,
                        },
                        {"fieldLabel": "Approver name", "requiredField": True},
                        {"fieldLabel": "Comment", "fieldType": "textarea"},
                    ]
                },
                "limitWaitTime": True,
                "limitType": "afterTimeInterval",
                "resumeAmount": 24,
                "resumeUnit": "hours",
                "options": {},
            },
        },
        _if("Timed out?", "!$json.Decision", (880, 300)),
        _record(
            "Record: timed out",
            "TIMED_OUT",
            "'n8n'",
            "{ reason: 'no decision within 24 hours' }",
            (1100, 120),
        ),
        _if(
            "Approver is requester?",
            "($json['Approver name'] || '').trim().toLowerCase() === "
            "(" + INCIDENT + ".requester || '').trim().toLowerCase()",
            (1100, 400),
        ),
        _record(
            "Record: re-request approval",
            "SUBMITTED_FOR_APPROVAL",
            "'n8n'",
            "{ approval_url: $execution.resumeFormUrl, "
            "reason: 'approver must differ from requester' }",
            (1320, 560),
        ),
        _if("Approved?", "$json.Decision === 'Approve'", (1320, 300)),
        _record(
            "Record: approved",
            "APPROVED",
            "$json['Approver name']",
            "{ comment: $json.Comment || '' }",
            (1540, 200),
        ),
        _record(
            "Record: simulated action",
            "ACTION_SIMULATED",
            "'n8n'",
            "{ action: 'Corrective Action Request drafted for ' + "
            + INCIDENT
            + ".supplier + ' (SIMULATED: not sent)' }",
            (1760, 200),
        ),
        _record(
            "Record: rejected",
            "REJECTED",
            "$('Human approval').item.json['Approver name']",
            "{ comment: $('Human approval').item.json.Comment || '' }",
            (1540, 400),
        ),
        # ---- Slack notifications (optional: skipped when SCC_SLACK_WEBHOOK_URL is empty)
        _if("Slack configured?", "!!$env.SCC_SLACK_WEBHOOK_URL", (550, 520)),
        _slack("Notify Slack: approval needed", APPROVAL_NEEDED_JS, (660, 680)),
        _if("Slack configured? (outcome)", "!!$env.SCC_SLACK_WEBHOOK_URL", (1980, 300)),
        _slack("Notify Slack: outcome", OUTCOME_JS, (2200, 300)),
    ]

    def to(name: str) -> list[dict]:
        return [{"node": name, "type": "main", "index": 0}]

    connections = {
        "Incident submitted": {"main": [to("Token valid?")]},
        "Token valid?": {"main": [to("Record: awaiting approval"), []]},
        "Record: awaiting approval": {"main": [to("Slack configured?")]},
        "Slack configured?": {"main": [to("Notify Slack: approval needed"), to("Human approval")]},
        "Notify Slack: approval needed": {"main": [to("Human approval")]},
        "Human approval": {"main": [to("Timed out?")]},
        "Timed out?": {"main": [to("Record: timed out"), to("Approver is requester?")]},
        "Approver is requester?": {"main": [to("Record: re-request approval"), to("Approved?")]},
        "Record: re-request approval": {"main": [to("Slack configured?")]},
        "Approved?": {"main": [to("Record: approved"), to("Record: rejected")]},
        "Record: approved": {"main": [to("Record: simulated action")]},
        "Record: simulated action": {"main": [to("Slack configured? (outcome)")]},
        "Record: rejected": {"main": [to("Slack configured? (outcome)")]},
        "Record: timed out": {"main": [to("Slack configured? (outcome)")]},
        "Slack configured? (outcome)": {"main": [to("Notify Slack: outcome"), []]},
    }
    return {
        "id": WORKFLOW_ID,
        "name": "SCC: supplier-quality incident approval (simulated)",
        "active": False,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "pinData": {},
        "meta": {"templateCredsSetupCompleted": True},
    }


TIMEOUT_TEST_ID = "sccSupplierIncidentTimeoutTest"
TIMEOUT_TEST_PATH = WEBHOOK_PATH + "-timeout-test"


def timeout_test_variant(minutes: int = 2) -> dict:
    """A separate copy for exercising the TIMED_OUT path live without waiting 24 hours.

    Own workflow ID, webhook path and webhook IDs, so importing it never touches the production
    workflow; only the wait limit and the wording of the timeout reason differ (tested).
    Delete it from n8n after the run."""
    wf = json.loads(render())
    window = f"{minutes} minutes (timeout test)"
    for node in wf["nodes"]:
        if "webhookId" in node:
            node["webhookId"] = str(uuid.uuid5(_NS, "timeout-test:" + node["webhookId"]))
        params = node["parameters"]
        if node["name"] == "Incident submitted":
            params["path"] = TIMEOUT_TEST_PATH
        if node["name"] == "Human approval":
            params["resumeAmount"], params["resumeUnit"] = minutes, "minutes"
    wf = json.loads(
        json.dumps(wf, ensure_ascii=False).replace("within 24 hours", "within " + window)
    )
    wf["id"], wf["name"] = TIMEOUT_TEST_ID, "[TEST] " + wf["name"] + f" - {minutes}-minute timeout"
    return wf


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    import argparse
    from pathlib import Path

    p = argparse.ArgumentParser()
    p.add_argument("--timeout-test", type=Path, metavar="OUT", help="write the timeout-test copy")
    p.add_argument("--minutes", type=int, default=2)
    args = p.parse_args()
    if args.timeout_test:
        args.timeout_test.write_text(
            json.dumps(timeout_test_variant(args.minutes), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote timeout-test workflow ({args.minutes} min) to {args.timeout_test}")
        return
    WORKFLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKFLOW_FILE.write_text(render(), encoding="utf-8", newline="\n")
    print(f"Wrote {WORKFLOW_FILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
