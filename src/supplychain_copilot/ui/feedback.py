"""Thumbs up/down feedback: stored in SCC_DB.APP.AGENT_FEEDBACK (INSERT-only grant), with a local
JSONL fallback (logs/, gitignored) so a Snowflake hiccup never breaks the UI."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from supplychain_copilot.agent.client import AgentAnswer, redact
from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.snowflake.connection import app_session
from supplychain_copilot.ui import APP_VERSION

LOCAL_LOG = PROJECT_ROOT / "logs" / "feedback.jsonl"
COLUMNS = [
    "FEEDBACK_ID",
    "CREATED_AT_UTC",
    "SESSION_ID",
    "QUESTION",
    "ANSWER_EXCERPT",
    "RATING",
    "COMMENT",
    "TOOLS_USED",
    "CITATION_COUNT",
    "LATENCY_S",
    "AGENT_STATUS",
    "APP_VERSION",
]


def build_record(
    answer: AgentAnswer, rating: int, session_id: str, comment: str | None = None
) -> dict[str, Any]:
    if rating not in (1, -1):
        raise ValueError("rating must be 1 or -1")
    excerpt, _ = redact(answer.text[:500])
    question, _ = redact(answer.question[:2000])
    note, _ = redact((comment or "")[:1000])
    return {
        "FEEDBACK_ID": str(uuid.uuid4()),
        "CREATED_AT_UTC": datetime.now(UTC).replace(tzinfo=None),
        "SESSION_ID": session_id,
        "QUESTION": question,
        "ANSWER_EXCERPT": excerpt,
        "RATING": rating,
        "COMMENT": note or None,
        "TOOLS_USED": ",".join(sorted(answer.tools_used)),
        "CITATION_COUNT": len(answer.citations),
        "LATENCY_S": round(answer.latency_s, 2),
        "AGENT_STATUS": answer.status,
        "APP_VERSION": APP_VERSION,
    }


def save_feedback(
    record: dict[str, Any], session_factory: Callable[[], AbstractContextManager] = app_session
) -> str:
    """Returns 'snowflake' or 'local' depending on where the record was stored."""
    try:
        with session_factory() as conn:
            conn.cursor().execute(
                f"INSERT INTO SCC_DB.APP.AGENT_FEEDBACK ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))})",
                tuple(record[c] for c in COLUMNS),
            )
        return "snowflake"
    except Exception:  # noqa: BLE001 - feedback must never break the app
        LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOCAL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**record, "CREATED_AT_UTC": str(record["CREATED_AT_UTC"])}) + "\n")
        return "local"
