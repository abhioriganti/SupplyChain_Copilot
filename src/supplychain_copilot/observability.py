"""Request logging for monitoring (Phase 8).

One row per agent request into SCC_DB.APP.AGENT_REQUEST_LOG (INSERT-only grant for the runtime role),
with a local JSONL fallback (logs/, gitignored) so logging can never break the app or an eval run.
What is NOT logged: credentials, answer text, SQL result rows, document text. Questions are truncated
to 300 characters with credential patterns redacted, and hashed for grouping.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from supplychain_copilot.agent.client import AgentAnswer, redact
from supplychain_copilot.config import PROJECT_ROOT

LOCAL_LOG = PROJECT_ROOT / "logs" / "requests.jsonl"
APP_VERSION = "0.8.0"
COLUMNS = [
    "REQUEST_ID",
    "CREATED_AT_UTC",
    "SOURCE",
    "SESSION_ID",
    "QUESTION_SHA256",
    "QUESTION_REDACTED",
    "STATUS",
    "ERROR_CLASS",
    "TOOLS_USED",
    "SQL_COUNT",
    "VERIFIED_QUERY_USED",
    "CITATION_COUNT",
    "LATENCY_S",
    "CACHED",
    "ORCHESTRATION_MODEL",
    "INPUT_TOKENS",
    "OUTPUT_TOKENS",
    "EVAL_RUN_ID",
    "EVAL_CASE_ID",
    "EVAL_OUTCOME",
    "APP_VERSION",
]


def _tokens(usage: dict[str, Any]) -> tuple[int | None, int | None]:
    entries = usage.get("tokens_consumed") or []
    if not entries:
        return None, None
    inp = sum(int((e.get("input_tokens") or {}).get("total", 0)) for e in entries)
    out = sum(int((e.get("output_tokens") or {}).get("total", 0)) for e in entries)
    return inp, out


def build_log_record(
    answer: AgentAnswer,
    source: str,
    session_id: str | None = None,
    cached: bool = False,
    eval_run_id: str | None = None,
    eval_case_id: str | None = None,
    eval_outcome: str | None = None,
) -> dict[str, Any]:
    question = answer.question or ""
    redacted, _ = redact(question[:300])
    inp, out = _tokens(answer.usage or {})
    meta = (answer.raw or {}).get("metadata", {}) or {}
    return {
        "REQUEST_ID": str(uuid.uuid4()),
        "CREATED_AT_UTC": datetime.now(UTC).replace(tzinfo=None),
        "SOURCE": source,
        "SESSION_ID": session_id,
        "QUESTION_SHA256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "QUESTION_REDACTED": redacted,
        "STATUS": answer.status or ("error" if answer.error else None),
        "ERROR_CLASS": answer.error.split(":", 1)[0] if answer.error else None,
        "TOOLS_USED": ",".join(sorted(answer.tools_used)) or None,
        "SQL_COUNT": len(answer.sql_statements),
        "VERIFIED_QUERY_USED": any(t.verified_query_used for t in answer.tool_calls)
        if answer.tool_calls
        else None,
        "CITATION_COUNT": len(answer.citations),
        "LATENCY_S": round(float(answer.latency_s), 2) if not cached else 0.0,
        "CACHED": cached,
        "ORCHESTRATION_MODEL": meta.get("orchestration_model"),
        "INPUT_TOKENS": None if cached else inp,
        "OUTPUT_TOKENS": None if cached else out,
        "EVAL_RUN_ID": eval_run_id,
        "EVAL_CASE_ID": eval_case_id,
        "EVAL_OUTCOME": eval_outcome,
        "APP_VERSION": APP_VERSION,
    }


def log_request(
    record: dict[str, Any], session_factory: Callable[[], AbstractContextManager] | None = None
) -> str:
    """Insert the record; returns 'snowflake' or 'local'. Never raises."""
    try:
        if session_factory is None:
            from supplychain_copilot.snowflake.connection import app_session as session_factory
        with session_factory() as conn:
            conn.cursor().execute(
                f"INSERT INTO SCC_DB.APP.AGENT_REQUEST_LOG ({', '.join(COLUMNS)}) "
                f"VALUES ({', '.join(['%s'] * len(COLUMNS))})",
                tuple(record.get(c) for c in COLUMNS),
            )
        return "snowflake"
    except Exception:  # noqa: BLE001 - monitoring must never break the caller
        try:
            LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOCAL_LOG.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps({**record, "CREATED_AT_UTC": str(record["CREATED_AT_UTC"])}) + "\n"
                )
        except OSError:
            pass
        return "local"
