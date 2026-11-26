"""Thin Cortex Analyst REST client bound to the governed semantic view."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from supplychain_copilot.config import SnowflakeSettings, load_settings
from supplychain_copilot.semantic import SEMANTIC_VIEW
from supplychain_copilot.snowflake.rest import SnowflakeRestClient

ANALYST_PATH = "/api/v2/cortex/analyst/message"


@dataclass
class AnalystResponse:
    text: str
    sql: str | None
    suggestions: list[str] = field(default_factory=list)
    request_id: str | None = None
    verified_query_used: Any = None
    warnings: list[Any] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def ask(
    question: str,
    settings: SnowflakeSettings | None = None,
    semantic_view: str = SEMANTIC_VIEW,
    client: SnowflakeRestClient | None = None,
) -> AnalystResponse:
    client = client or SnowflakeRestClient(settings or load_settings())
    resp = client.post(
        ANALYST_PATH,
        {
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
            "semantic_view": semantic_view,
        },
    )
    content = resp.get("message", {}).get("content", [])
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    sql_items = [c for c in content if c.get("type") == "sql"]
    suggestions = [
        s for c in content if c.get("type") == "suggestions" for s in c.get("suggestions", [])
    ]
    confidence = sql_items[0].get("confidence", {}) if sql_items else {}
    return AnalystResponse(
        text="\n".join(t for t in texts if t),
        sql=sql_items[0].get("statement") if sql_items else None,
        suggestions=suggestions,
        request_id=resp.get("request_id"),
        verified_query_used=(confidence or {}).get("verified_query_used"),
        warnings=resp.get("warnings", []),
        raw=resp,
    )
