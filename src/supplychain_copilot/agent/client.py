"""Python client for the SupplyChain Copilot Cortex Agent.

* Calls the named agent over REST (`.../agents/SUPPLY_CHAIN_COPILOT:run`, non-streaming) as the
  read-only runtime role SCC_APP_ROLE, so any SQL the agent runs cannot write data.
* Parses the response into an inspectable structure: answer text, citations (chunk id + label),
  tool calls (semantic-view SQL with its result set; search results), tables, suggestions, usage.
* Guardrails: input validation, bounded retries for transient HTTP errors, a meaningful fallback
  answer instead of an exception, and redaction of anything that looks like a credential.

Response shape (observed on this account, 2026-11-26, consistent with docs.snowflake.com
cortex-agents-run): {role, content[], metadata{usage, ...}, status}; content items are
{"type": t, t: {...}} for thinking / tool_use / tool_result / table / suggested_queries, and
{"type": "text", "text": str, "annotations": [...]} for answer text.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from supplychain_copilot.agent import RUNTIME_ROLE
from supplychain_copilot.config import SnowflakeSettings, load_app_settings
from supplychain_copilot.snowflake.rest import SnowflakeRestClient, SnowflakeRestError

AGENT_PATH = "/api/v2/databases/SCC_DB/schemas/AI/agents/SUPPLY_CHAIN_COPILOT:run"
MAX_QUESTION_CHARS = 2000
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
TOOL_ALIASES = {"system_execute_sql": "delivery_analytics"}  # SQL step of the Analyst tool
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(password|passphrase|private_key|secret)\s*[:=]\s*\S+"),
]


@dataclass
class Citation:
    chunk_id: str
    label: str
    snippet: str


@dataclass
class ToolCall:
    tool: str  # delivery_analytics | supplier_documents
    step: str  # raw tool name/type from the response
    status: str | None = None
    query: str | None = None  # search query sent by the agent
    sql: str | None = None
    verified_query_used: bool | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    search_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentAnswer:
    question: str
    text: str
    citations: list[Citation] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)
    status: str | None = None
    latency_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    warnings: list[Any] = field(default_factory=list)
    error: str | None = None
    redacted: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == "completed"

    @property
    def tools_used(self) -> set[str]:
        return {t.tool for t in self.tool_calls if t.status in (None, "success")}

    @property
    def sql_statements(self) -> list[str]:
        return [t.sql for t in self.tool_calls if t.sql]


class InvalidQuestion(ValueError):
    pass


def validate_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise InvalidQuestion("Please enter a question.")
    if len(q) > MAX_QUESTION_CHARS:
        raise InvalidQuestion(f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    return q


def redact(text: str) -> tuple[str, bool]:
    changed = False
    for pat in _SECRET_PATTERNS:
        text, n = pat.subn("[redacted]", text)
        changed = changed or n > 0
    return text, changed


def parse_response(question: str, resp: dict[str, Any], latency_s: float = 0.0) -> AgentAnswer:
    texts: list[str] = []
    citations: list[Citation] = []
    calls: dict[str, ToolCall] = {}
    ordered: list[ToolCall] = []
    suggestions: list[str] = []
    for item in resp.get("content", []):
        kind = item.get("type")
        if kind == "text":
            if item.get("text", "").strip():
                texts.append(item["text"].strip())
            for a in item.get("annotations", []) or []:
                citations.append(
                    Citation(
                        a.get("doc_id", ""), a.get("doc_title", ""), (a.get("text") or "")[:500]
                    )
                )
        elif kind == "tool_use":
            tu = item["tool_use"]
            name = TOOL_ALIASES.get(tu.get("name"), tu.get("name"))
            call = ToolCall(tool=name, step=f"{tu.get('name')}:{tu.get('type')}")
            inp = tu.get("input") or {}
            call.query = inp.get("query")
            call.sql = inp.get("sql")
            calls[tu.get("tool_use_id", str(len(calls)))] = call
            ordered.append(call)
        elif kind == "tool_result":
            tr = item["tool_result"]
            call = calls.get(tr.get("tool_use_id"))
            if call is None:
                call = ToolCall(
                    tool=TOOL_ALIASES.get(tr.get("name"), tr.get("name")), step=str(tr.get("name"))
                )
                ordered.append(call)
            call.status = tr.get("status")
            for c in tr.get("content", []) or []:
                j = c.get("json") or {}
                if "sql" in j:
                    call.sql = j["sql"]
                    call.verified_query_used = j.get("verified_query_used")
                if "result_set" in j:
                    meta = j["result_set"].get("resultSetMetaData", {})
                    call.columns = [col["name"] for col in meta.get("rowType", [])]
                    call.rows = j["result_set"].get("data", [])
                if "search_results" in j:
                    call.search_results = j["search_results"]
        elif kind == "suggested_queries":
            suggestions = [
                s.get("query", "") for s in item.get("suggested_queries", []) if s.get("query")
            ]
    text, redacted = redact("\n\n".join(texts))
    seen: set[str] = set()
    unique_citations = [c for c in citations if not (c.chunk_id in seen or seen.add(c.chunk_id))]
    meta = resp.get("metadata", {}) or {}
    return AgentAnswer(
        question=question,
        text=text,
        citations=unique_citations,
        tool_calls=ordered,
        suggested_queries=suggestions,
        status=resp.get("status"),
        latency_s=latency_s,
        usage=meta.get("usage", {}),
        warnings=resp.get("warnings") or [],
        redacted=redacted,
        raw=resp,
    )


def fallback(question: str, reason: str, detail: str, latency_s: float = 0.0) -> AgentAnswer:
    messages = {
        "invalid": detail,
        "rate_limited": "The assistant is busy right now. Please try again in a moment.",
        "auth": "The assistant couldn't authenticate to Snowflake. Check the app's connection settings.",
        "permission": "The assistant's role doesn't have access to a required tool or object.",
        "timeout": "The request took too long and was stopped. Try a narrower question.",
        "service": "The assistant hit a service error. Please try again; if it persists, check Snowflake status.",
        "empty": "The assistant returned no answer for this question. Try rephrasing it.",
    }
    return AgentAnswer(
        question=question,
        text=messages.get(reason, messages["service"]),
        status="error",
        latency_s=latency_s,
        error=f"{reason}: {detail}",
    )


class CopilotAgent:
    def __init__(
        self,
        settings: SnowflakeSettings | None = None,
        client: Any | None = None,
        timeout_s: float = 180.0,
        max_retries: int = 2,
        backoff_s: float = 2.0,
    ):
        """Defaults to the dedicated runtime user (SCC_APP_SVC, role SCC_APP_ROLE). Fails closed with
        ConfigError if that user isn't configured, rather than using developer credentials."""
        if client is None:
            settings = settings or load_app_settings()
            if settings.role != RUNTIME_ROLE:
                raise ValueError(f"The agent must run as {RUNTIME_ROLE}, not {settings.role}.")
            client = SnowflakeRestClient(settings, timeout=timeout_s)
        self._client = client
        self._max_retries = max_retries
        self._backoff_s = backoff_s

    def ask(self, question: str, history: list[dict[str, Any]] | None = None) -> AgentAnswer:
        try:
            q = validate_question(question)
        except InvalidQuestion as exc:
            return fallback(question, "invalid", str(exc))
        messages = list(history or []) + [
            {"role": "user", "content": [{"type": "text", "text": q}]}
        ]
        start = time.perf_counter()
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.post(AGENT_PATH, {"messages": messages, "stream": False})
            except SnowflakeRestError as exc:
                elapsed = time.perf_counter() - start
                if exc.status in RETRYABLE_STATUS and attempt < self._max_retries:
                    time.sleep(self._backoff_s * (2**attempt))
                    continue
                reason = {401: "auth", 403: "permission", 429: "rate_limited"}.get(
                    exc.status, "service"
                )
                if "399504" in exc.body or "not accessible" in exc.body.lower():
                    reason = "permission" if exc.status != 429 else reason
                return fallback(q, reason, f"HTTP {exc.status}: {exc.body[:300]}", elapsed)
            except requests.Timeout:
                return fallback(q, "timeout", "client timeout", time.perf_counter() - start)
            except requests.RequestException as exc:
                if attempt < self._max_retries:
                    time.sleep(self._backoff_s * (2**attempt))
                    continue
                return fallback(
                    q, "service", f"{type(exc).__name__}: {exc}", time.perf_counter() - start
                )
            answer = parse_response(q, resp, time.perf_counter() - start)
            if not answer.text:
                return fallback(q, "empty", f"status={answer.status}", answer.latency_s)
            if answer.status not in (None, "completed"):
                answer.error = f"status: {answer.status}"
            return answer
        return fallback(q, "service", "retries exhausted", time.perf_counter() - start)


def main() -> int:  # python -m supplychain_copilot.agent.client "question"
    import sys

    q = " ".join(sys.argv[1:]) or "Which regions have the highest late-delivery rates?"
    a = CopilotAgent().ask(q)
    print(
        f"[{a.status}] {a.latency_s:.1f}s tools={sorted(a.tools_used)} error={a.error}\n\n{a.text}\n"
    )
    for c in a.citations:
        print(f"  cite: {c.label}  ({c.chunk_id})")
    for s in a.sql_statements:
        print(f"  sql: {s.strip()[:200]}")
    return 0 if a.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
