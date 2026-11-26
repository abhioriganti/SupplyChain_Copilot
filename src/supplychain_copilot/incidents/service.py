"""Incident workflow service: open, draft (Copilot), submit to n8n, record workflow callbacks.

Every state change goes through build_event (state machine + separation of duties + hash chain)
and is appended to the store. Nothing here sends email or contacts a supplier: an approved
incident only records ACTION_SIMULATED.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import requests

from supplychain_copilot.incidents import model
from supplychain_copilot.incidents.model import Event, IncidentInput
from supplychain_copilot.incidents.store import APPEND_LOCK, IncidentStore

DEFAULT_WEBHOOK = "http://localhost:5678/webhook/scc-supplier-incident"
TOKEN_HEADER = "X-SCC-Workflow-Token"  # noqa: S105 - header name; the value comes from .env
DRAFT_PROMPT = (
    "A SIMULATED supplier-quality incident was reported for practice. Title: {title}. "
    "Part: {part}. Severity: {severity}. Description: {description}. "
    "Using only Worthington's public Supplier Quality Assurance Manual, list the procedure steps "
    "and deadlines that would apply if this non-conformance is confirmed, with section and PDF "
    "page citations. Do not assume or state a cause, and do not use delivery statistics."
)


class WorkflowUnavailable(RuntimeError):
    pass


def plain_text(markdown: str) -> str:
    """n8n form descriptions are plain text: drop bold/italic/heading/code markers, keep bullets."""
    import re

    text = re.sub(r"(\*\*|__|`)", "", markdown)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    return re.sub(r"(?m)^(\s*)[*-]\s+", r"\1• ", text)


def workflow_token() -> str:
    token = os.getenv("SCC_WORKFLOW_TOKEN", "")
    if len(token) < 24:
        raise RuntimeError("SCC_WORKFLOW_TOKEN is missing or shorter than 24 characters (.env)")
    return token


class IncidentService:
    def __init__(
        self,
        store: IncidentStore,
        drafter: Callable[[dict[str, str]], dict[str, Any]] | None = None,
        post: Callable[..., Any] | None = None,
        webhook_url: str | None = None,
    ):
        self.store = store
        self._drafter = drafter
        self._post = post or requests.post
        self._webhook = webhook_url or os.getenv("SCC_N8N_WEBHOOK_URL", DEFAULT_WEBHOOK)

    def _append(
        self, incident_id: str | None, event_type: str, actor: str, actor_type: str, details: dict
    ) -> Event:
        with APPEND_LOCK:
            history = self.store.history(incident_id) if incident_id else []
            if incident_id and not history:
                raise model.IncidentError(f"unknown incident {incident_id}")
            event = model.build_event(history, event_type, actor, actor_type, details)
            self.store.append(event)
            return event

    # ------------------------------------------------------------------ requester side (Streamlit)
    def open(self, incident: IncidentInput) -> Event:
        fields = incident.cleaned()
        requester = fields.pop("requester")
        return self._append(None, model.CREATED, requester, "human", fields)

    def draft(self, incident_id: str) -> Event:
        """Ask the Copilot for the applicable procedures. Failure is recorded, never raised."""
        created = self.store.history(incident_id)[0]
        try:
            if self._drafter is None:
                raise RuntimeError("no drafter configured")
            result = self._drafter(created.details)
            return self._append(incident_id, model.DRAFTED, "supply_chain_copilot", "agent", result)
        except Exception as exc:  # noqa: BLE001 - recorded as an ERROR event
            return self._append(
                incident_id,
                model.ERROR,
                "supply_chain_copilot",
                "agent",
                {"stage": "draft", "error": type(exc).__name__},
            )

    def submit(self, incident_id: str) -> dict[str, Any]:
        """Start the n8n approval workflow. n8n records SUBMITTED_FOR_APPROVAL itself, via the API."""
        history = self.store.history(incident_id)
        if model.SUBMITTED not in model.TRANSITIONS.get(model.status_of(history), set()):
            raise model.TransitionError(
                f"cannot submit an incident that is {model.status_of(history)}"
            )
        created = history[0]
        drafted = next((e for e in reversed(history) if e.event_type == model.DRAFTED), None)
        body = {
            "incident_id": incident_id,
            "title": created.details.get("title"),
            "supplier": created.details.get("supplier"),
            "part": created.details.get("part"),
            "severity": created.details.get("severity"),
            "requester": created.actor,
            "draft_excerpt": plain_text(drafted.details.get("draft", ""))[:1500] if drafted else "",
            "simulated": True,
        }
        try:
            resp = self._post(
                self._webhook, json=body, headers={TOKEN_HEADER: workflow_token()}, timeout=15
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - n8n down/misconfigured is recorded, not raised
            self._append(
                incident_id,
                model.ERROR,
                "supply_chain_copilot",
                "system",
                {"stage": "submit", "error": type(exc).__name__},
            )
            raise WorkflowUnavailable(
                "The approval workflow (n8n) did not accept the incident."
            ) from exc
        return {"incident_id": incident_id, "workflow": "accepted"}

    # ------------------------------------------------------------------ workflow side (n8n -> API)
    def record_workflow_event(
        self, incident_id: str, event_type: str, actor: str, details: dict[str, Any]
    ) -> Event:
        if event_type not in model.WORKFLOW_EVENTS:
            raise model.TransitionError(f"{event_type} cannot be recorded by the workflow")
        actor_type = "human" if event_type in model.DECISIONS else "workflow"
        return self._append(incident_id, event_type, actor, actor_type, details)


def copilot_drafter(agent: Any | None = None) -> Callable[[dict[str, str]], dict[str, Any]]:
    """Drafts the applicable procedures with the production Copilot (one paid agent call)."""

    def draft(fields: dict[str, str]) -> dict[str, Any]:
        from supplychain_copilot.agent.client import CopilotAgent

        a = (agent or CopilotAgent()).ask(
            DRAFT_PROMPT.format(
                **{k: fields.get(k, "") for k in ("title", "part", "severity", "description")}
            )
        )
        if not a.ok:
            raise RuntimeError(a.error or "agent error")
        return {
            "draft": a.text[:3000],
            "citations": [c.label for c in a.citations][:8],
            "tools": sorted(a.tools_used),
        }

    return draft
