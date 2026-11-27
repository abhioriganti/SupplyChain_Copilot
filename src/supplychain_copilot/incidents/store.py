"""Incident event stores: Snowflake (runtime role: INSERT on the table, SELECT on views) and in-memory.

Snowflake does not enforce PRIMARY KEY / UNIQUE on standard tables, so appends are serialised with a
process lock and every append re-reads the incident's history first. The SQL chain check
(V_INCIDENT_CHAIN_CHECK) detects any gap or duplicate a second writer could still cause.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol

from supplychain_copilot.incidents.model import Event

COLUMNS = (
    "EVENT_ID, INCIDENT_ID, SEQ, EVENT_TYPE, ACTOR, ACTOR_TYPE, CREATED_AT_UTC, PAYLOAD, "
    "PREV_HASH, EVENT_HASH, SIMULATED, HASH_VERSION"
)


class IncidentStore(Protocol):
    def history(self, incident_id: str) -> list[Event]: ...

    def append(self, event: Event) -> None: ...

    def statuses(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def chain_check(self) -> list[dict[str, Any]]: ...

    def anchor_check(self) -> list[dict[str, Any]]: ...


ANCHOR_CHECK_SQL = "SELECT * FROM SCC_AUDIT_DB.ANCHOR.V_ANCHOR_CHECK"


class InMemoryStore:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def history(self, incident_id: str) -> list[Event]:
        return sorted((e for e in self.events if e.incident_id == incident_id), key=lambda e: e.seq)

    def append(self, event: Event) -> None:
        self.events.append(event)

    def statuses(self, limit: int = 50) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(e.incident_id for e in reversed(self.events)))[:limit]
        out = []
        for i in ids:
            h = self.history(i)
            out.append(
                {
                    "INCIDENT_ID": i,
                    "TITLE": h[0].details.get("title"),
                    "REQUESTER": h[0].actor,
                    "STATUS": h[-1].event_type,
                    "EVENT_COUNT": len(h),
                }
            )
        return out

    def chain_check(self) -> list[dict[str, Any]]:
        from supplychain_copilot.incidents.model import verify_chain

        ids = dict.fromkeys(e.incident_id for e in self.events)
        return [{"INCIDENT_ID": i, "CHAIN_OK": not verify_chain(self.history(i))} for i in ids]

    def anchor_check(self) -> list[dict[str, Any]]:
        return []  # anchors live in Snowflake (SCC_AUDIT_DB, ADR-030)


class SnowflakeIncidentStore:
    def __init__(self, session_factory: Callable[[], AbstractContextManager] | None = None):
        if session_factory is None:
            from supplychain_copilot.snowflake.connection import app_session as session_factory
        self._session = session_factory

    def history(self, incident_id: str) -> list[Event]:
        from supplychain_copilot.snowflake.connection import query

        with self._session() as conn:
            rows = query(
                conn,
                f"SELECT {COLUMNS} FROM SCC_DB.APP.V_INCIDENT_EVENTS "  # noqa: S608 - constant columns; value bound
                "WHERE INCIDENT_ID = %s ORDER BY SEQ",
                (incident_id,),
            )
        return [_event_from_row(r) for r in rows]

    def append(self, event: Event) -> None:
        with self._session() as conn:
            conn.cursor().execute(
                f"INSERT INTO SCC_DB.APP.INCIDENT_AUDIT_LOG ({COLUMNS}) "  # noqa: S608 - constant columns; values bound
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    event.event_id,
                    event.incident_id,
                    event.seq,
                    event.event_type,
                    event.actor,
                    event.actor_type,
                    event.created_at_utc,
                    event.payload,
                    event.prev_hash,
                    event.event_hash,
                    event.simulated,
                    event.hash_version,
                ),
            )

    def statuses(self, limit: int = 50) -> list[dict[str, Any]]:
        from supplychain_copilot.snowflake.connection import query

        with self._session() as conn:
            return query(
                conn,
                "SELECT * FROM SCC_DB.APP.V_INCIDENT_STATUS ORDER BY OPENED_AT_UTC DESC LIMIT %s",
                (int(limit),),
            )

    def chain_check(self) -> list[dict[str, Any]]:
        from supplychain_copilot.snowflake.connection import query

        with self._session() as conn:
            return query(conn, "SELECT * FROM SCC_DB.APP.V_INCIDENT_CHAIN_CHECK")

    def anchor_check(self) -> list[dict[str, Any]]:
        """Anchors kept outside the owner role (ADR-030). Empty if the anchor database isn't set up
        or isn't readable, so the incident list still works; the UI then shows 'not anchored'."""
        from supplychain_copilot.snowflake.connection import query

        try:
            with self._session() as conn:
                return query(conn, ANCHOR_CHECK_SQL)
        except Exception:  # noqa: BLE001 - optional control; absence is shown, not fatal
            return []


def _event_from_row(r: dict[str, Any]) -> Event:
    import json

    return Event(
        event_id=r["EVENT_ID"],
        incident_id=r["INCIDENT_ID"],
        seq=int(r["SEQ"]),
        event_type=r["EVENT_TYPE"],
        actor=r["ACTOR"],
        actor_type=r["ACTOR_TYPE"],
        created_at_utc=r["CREATED_AT_UTC"],
        payload=r["PAYLOAD"],
        prev_hash=r["PREV_HASH"],
        event_hash=r["EVENT_HASH"],
        simulated=bool(r["SIMULATED"]),
        details=json.loads(r["PAYLOAD"]),
        hash_version=int(r.get("HASH_VERSION") or 1),
    )


APPEND_LOCK = threading.Lock()
