"""Supplier-quality incident model (Phase 9, SIMULATED): events, state machine, hash chain.

Pure logic, no I/O. The hash is SHA-256(prev_hash || payload) over canonical JSON, identical to
the recomputation in SCC_DB.APP.V_INCIDENT_CHAIN_CHECK, so tampering is detectable in SQL.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from supplychain_copilot.agent.client import redact

GENESIS = "0" * 64
SEVERITIES = ("low", "medium", "high", "critical")
LIMITS = {"title": 120, "supplier": 80, "part": 80, "description": 2000, "requester": 80}

CREATED = "CREATED"
DRAFTED = "DRAFTED"
SUBMITTED = "SUBMITTED_FOR_APPROVAL"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
TIMED_OUT = "TIMED_OUT"
ACTION_SIMULATED = "ACTION_SIMULATED"
ERROR = "ERROR"

# Allowed next events by current status. Terminal states allow nothing.
TRANSITIONS: dict[str | None, set[str]] = {
    None: {CREATED},
    CREATED: {DRAFTED, SUBMITTED, ERROR},
    DRAFTED: {SUBMITTED, ERROR},
    ERROR: {DRAFTED, SUBMITTED, ERROR},
    # SUBMITTED -> SUBMITTED: the workflow re-opens the approval form, e.g. after the requester tried
    # to approve their own incident (n8n checks first; the API enforces it regardless).
    SUBMITTED: {SUBMITTED, APPROVED, REJECTED, TIMED_OUT},
    APPROVED: {ACTION_SIMULATED},
    REJECTED: set(),
    TIMED_OUT: set(),
    ACTION_SIMULATED: set(),
}
DECISIONS = {APPROVED, REJECTED}
WORKFLOW_EVENTS = {SUBMITTED, APPROVED, REJECTED, TIMED_OUT, ACTION_SIMULATED}


class IncidentError(ValueError):
    """Base class; the API maps these to HTTP 4xx."""


class InvalidInput(IncidentError):
    pass


class TransitionError(IncidentError):
    pass


class SeparationOfDutiesError(IncidentError):
    pass


@dataclass(frozen=True)
class IncidentInput:
    title: str
    supplier: str
    part: str
    description: str
    severity: str
    requester: str

    def cleaned(self) -> dict[str, str]:
        """Trim, length-check and redact credential-like text. Raises InvalidInput."""
        out: dict[str, str] = {}
        for name, limit in LIMITS.items():
            value = " ".join(str(getattr(self, name) or "").split())
            if name in ("title", "requester", "description") and not value:
                raise InvalidInput(f"{name} is required")
            if len(value) > limit:
                raise InvalidInput(f"{name} is longer than {limit} characters")
            out[name], _ = redact(value)
        severity = (self.severity or "").strip().lower()
        if severity not in SEVERITIES:
            raise InvalidInput(f"severity must be one of {', '.join(SEVERITIES)}")
        out["severity"] = severity
        return out


@dataclass(frozen=True)
class Event:
    event_id: str
    incident_id: str
    seq: int
    event_type: str
    actor: str
    actor_type: str
    created_at_utc: datetime
    payload: str
    prev_hash: str
    event_hash: str
    simulated: bool = True
    details: dict[str, Any] = field(default_factory=dict, compare=False)


def canonical(details: dict[str, Any]) -> str:
    return json.dumps(details, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain_hash(prev_hash: str, payload: str) -> str:
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


def status_of(history: list[Event]) -> str | None:
    return history[-1].event_type if history else None


def requester_of(history: list[Event]) -> str | None:
    return history[0].actor if history else None


def _same_person(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def build_event(
    history: list[Event],
    event_type: str,
    actor: str,
    actor_type: str,
    details: dict[str, Any],
    incident_id: str | None = None,
    now: datetime | None = None,
) -> Event:
    """Validate the transition and return the next chained event (not yet stored)."""
    status = status_of(history)
    if event_type not in TRANSITIONS.get(status, set()):
        raise TransitionError(f"{event_type} is not allowed when the incident is {status or 'new'}")
    actor = " ".join((actor or "").split())
    if not actor:
        raise InvalidInput("actor is required")
    if event_type in DECISIONS:
        if actor_type != "human":
            raise SeparationOfDutiesError("approve and reject decisions must be made by a person")
        if _same_person(actor, requester_of(history) or ""):
            raise SeparationOfDutiesError(
                "the approver must be a different person from the requester"
            )
    if history:
        incident_id = history[0].incident_id
    incident_id = incident_id or f"INC-{uuid.uuid4().hex[:10].upper()}"
    payload = canonical({**details, "event_type": event_type, "simulated": True})
    prev = history[-1].event_hash if history else GENESIS
    return Event(
        event_id=str(uuid.uuid4()),
        incident_id=incident_id,
        seq=len(history) + 1,
        event_type=event_type,
        actor=actor,
        actor_type=actor_type,
        created_at_utc=(now or datetime.now(UTC)).replace(tzinfo=None),
        payload=payload,
        prev_hash=prev,
        event_hash=chain_hash(prev, payload),
        details=json.loads(payload),
    )


def verify_chain(history: list[Event]) -> list[str]:
    """Python twin of V_INCIDENT_CHAIN_CHECK. Returns problems (empty = intact)."""
    problems, prev = [], GENESIS
    for i, e in enumerate(history, start=1):
        if e.seq != i:
            problems.append(f"seq {e.seq} at position {i}")
        if e.prev_hash != prev:
            problems.append(f"seq {e.seq}: broken link")
        if chain_hash(e.prev_hash, e.payload) != e.event_hash:
            problems.append(f"seq {e.seq}: payload does not match hash")
        prev = e.event_hash
    return problems
