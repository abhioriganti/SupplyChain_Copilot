"""Phase 0 Cortex feasibility probes. INCURS SMALL CORTEX + WAREHOUSE COSTS - requires --yes.

Creates tiny objects in <DB>.SANDBOX, exercises each Cortex capability once, then drops everything
(unless --keep). Each probe reports PASS/FAIL independently so one blocker doesn't hide the rest.

  1. AI_COMPLETE  (llama3.1-8b, native in AWS us-west-2; plus one frontier model via cross-region)
  2. Semantic view create + SEMANTIC_VIEW() query
  3. Cortex Analyst REST (semantic_view) -> generated SQL executed read-only
  4. Cortex Search service create + SEARCH_PREVIEW query
  5. Cortex Agent (CREATE AGENT, both tools) run over REST, non-streaming

Usage:  .venv\\Scripts\\python scripts\\smoke_cortex.py --yes
"""

from __future__ import annotations

import argparse
import json
import traceback
from collections.abc import Callable
from typing import Any

from snowflake.connector import SnowflakeConnection

from supplychain_copilot.config import SnowflakeSettings, load_settings
from supplychain_copilot.snowflake.connection import query, session
from supplychain_copilot.snowflake.rest import SnowflakeRestClient

SCHEMA = "SANDBOX"
FRONTIER_MODEL = "claude-sonnet-4-5"


class Probe:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def run(self, name: str, fn: Callable[[], str]) -> bool:
        print(f"\n--- {name}")
        try:
            detail = fn()
            self.results.append((name, True, detail))
            print(f"[PASS] {detail}")
            return True
        except Exception as exc:  # noqa: BLE001 - we want to report every failure and continue
            msg = f"{type(exc).__name__}: {str(exc)[:400]}"
            self.results.append((name, False, msg))
            print(f"[FAIL] {msg}")
            traceback.print_exc(limit=1)
            return False


def fq(settings: SnowflakeSettings, name: str) -> str:
    return f"{settings.database}.{SCHEMA}.{name}"


def probe_ai_complete(conn: SnowflakeConnection, model: str) -> str:
    row = query(
        conn,
        "SELECT AI_COMPLETE(model => %s, prompt => 'Reply with the single word OK.', "
        "model_parameters => {'max_tokens': 5}) AS R",
        (model,),
    )[0]
    return f"{model} responded: {str(row['R']).strip()[:40]!r}"


def setup_sandbox_data(conn: SnowflakeConnection, s: SnowflakeSettings) -> None:
    cur = conn.cursor()
    cur.execute(
        f"CREATE OR REPLACE TABLE {fq(s, 'SMOKE_ORDERS')} "
        "(ORDER_ID NUMBER, REGION STRING, IS_LATE NUMBER(1))"
    )
    cur.execute(
        f"INSERT INTO {fq(s, 'SMOKE_ORDERS')} VALUES "
        "(1,'WEST',1),(2,'WEST',0),(3,'WEST',1),(4,'EAST',0),(5,'EAST',0)"
    )
    cur.execute(f"CREATE OR REPLACE TABLE {fq(s, 'SMOKE_DOCS')} (DOC_ID STRING, CHUNK_TEXT STRING)")
    cur.execute(
        f"INSERT INTO {fq(s, 'SMOKE_DOCS')} VALUES "
        "('DOC-1','Suppliers must submit a corrective action plan within 30 days of a nonconformance.'),"
        "('DOC-2','All shipments must include a packing list and certificate of conformance.')"
    )


def probe_semantic_view(conn: SnowflakeConnection, s: SnowflakeSettings) -> str:
    cur = conn.cursor()
    cur.execute(
        f"""CREATE OR REPLACE SEMANTIC VIEW {fq(s, "SMOKE_SV")}
  TABLES ( orders AS {fq(s, "SMOKE_ORDERS")} PRIMARY KEY (ORDER_ID) )
  DIMENSIONS ( orders.region AS orders.REGION )
  METRICS (
    orders.order_count AS COUNT(orders.ORDER_ID),
    orders.late_order_count AS SUM(orders.IS_LATE)
  )
  COMMENT = 'Phase 0 smoke test - safe to drop'"""
    )
    rows = query(
        conn,
        f"SELECT * FROM SEMANTIC_VIEW({fq(s, 'SMOKE_SV')} "
        "METRICS orders.order_count, orders.late_order_count DIMENSIONS orders.region) ORDER BY 1",
    )
    got = {r["REGION"]: (int(r["ORDER_COUNT"]), int(r["LATE_ORDER_COUNT"])) for r in rows}
    expected = {"EAST": (2, 0), "WEST": (3, 2)}
    if got != expected:
        raise AssertionError(f"semantic view returned {got}, expected {expected}")
    return f"semantic view created and queried; results match expected {expected}"


def probe_analyst(
    conn: SnowflakeConnection, rest: SnowflakeRestClient, s: SnowflakeSettings
) -> str:
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "How many late orders per region?"}],
            }
        ],
        "semantic_view": fq(s, "SMOKE_SV"),
    }
    resp = rest.post("/api/v2/cortex/analyst/message", body)
    sql = next(
        (c.get("statement") for c in resp["message"]["content"] if c.get("type") == "sql"), None
    )
    if not sql:
        raise AssertionError(f"no SQL in Analyst response: {json.dumps(resp)[:400]}")
    print(f"Analyst SQL:\n{sql}")
    rows = query(conn, sql)  # executed with the same role; read-only sandbox data
    print(f"Rows: {rows}")
    return f"Analyst generated SQL that executed and returned {len(rows)} row(s)"


def probe_search(conn: SnowflakeConnection, s: SnowflakeSettings) -> str:
    conn.cursor().execute(
        f"""CREATE OR REPLACE CORTEX SEARCH SERVICE {fq(s, "SMOKE_SEARCH")}
  ON CHUNK_TEXT
  ATTRIBUTES DOC_ID
  WAREHOUSE = {s.warehouse}
  TARGET_LAG = '1 day'
  AS (SELECT DOC_ID, CHUNK_TEXT FROM {fq(s, "SMOKE_DOCS")})"""
    )
    args = json.dumps(
        {"query": "deadline for corrective action", "columns": ["DOC_ID", "CHUNK_TEXT"], "limit": 1}
    )
    row = query(
        conn,
        f"SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{fq(s, 'SMOKE_SEARCH')}', "
        f"'{args}'))['results'] AS RESULTS",
    )[0]
    results = json.loads(row["RESULTS"])
    top = results[0]["DOC_ID"] if results else None
    if top != "DOC-1":
        raise AssertionError(f"expected DOC-1 as top hit, got {results}")
    return "search service created; top hit for 'corrective action deadline' is DOC-1"


def build_agent_spec(s: SnowflakeSettings, include_search: bool) -> str:
    """Minimal agent spec; the search tool is optional so Analyst-only orchestration can be tested."""
    tools = """
  - tool_spec:
      type: cortex_analyst_text_to_sql
      name: orders_analyst
      description: "Counts of sample orders and late orders by region.\""""
    resources = f"""
  orders_analyst:
    semantic_view: "{fq(s, "SMOKE_SV")}"
    execution_environment:
      type: warehouse
      warehouse: "{s.warehouse}\""""
    if include_search:
        tools += """
  - tool_spec:
      type: cortex_search
      name: policy_search
      description: "Searches sample supplier policy text.\""""
        resources += f"""
  policy_search:
    search_service: "{fq(s, "SMOKE_SEARCH")}"
    max_results: 2"""
    return f"""
models:
  orchestration: auto
instructions:
  response: "Answer briefly. Use the analyst tool for numbers and the search tool for policy text."
tools:{tools}
tool_resources:{resources}
"""


def _collect(obj: Any, key: str, out: list[Any]) -> list[Any]:
    """Recursively collect values for a key in a nested JSON response."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            _collect(v, key, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect(item, key, out)
    return out


def probe_agent(
    conn: SnowflakeConnection,
    rest: SnowflakeRestClient,
    s: SnowflakeSettings,
    include_search: bool = True,
) -> str:
    spec = build_agent_spec(s, include_search)
    conn.cursor().execute(
        f"CREATE OR REPLACE AGENT {fq(s, 'SMOKE_AGENT')} "
        f"COMMENT = 'Phase 0 smoke test - safe to drop' FROM SPECIFICATION $${spec}$$"
    )
    question = "How many late orders are in the WEST region?"
    if include_search:
        question += " And what is the deadline for a corrective action plan?"
    resp = rest.post(
        f"/api/v2/databases/{s.database}/schemas/{SCHEMA}/agents/SMOKE_AGENT:run",
        {
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
            "stream": False,
        },
    )
    tools_used = sorted(
        {str(n) for n in _collect(resp, "name", []) if n in {"orders_analyst", "policy_search"}}
    )
    texts = [t for t in _collect(resp, "text", []) if isinstance(t, str)]
    answer = texts[-1] if texts else ""
    print(f"Top-level response keys: {list(resp)[:10]}")
    print(f"Agent answer: {answer[:600]}")
    if not answer:
        raise AssertionError(f"no text in agent response: {json.dumps(resp)[:600]}")
    return f"agent ran over REST; tools referenced in response: {tools_used or 'none detected'}"


def cleanup(conn: SnowflakeConnection, s: SnowflakeSettings) -> None:
    cur = conn.cursor()
    for stmt in (
        f"DROP AGENT IF EXISTS {fq(s, 'SMOKE_AGENT')}",
        f"DROP CORTEX SEARCH SERVICE IF EXISTS {fq(s, 'SMOKE_SEARCH')}",
        f"DROP SEMANTIC VIEW IF EXISTS {fq(s, 'SMOKE_SV')}",
        f"DROP TABLE IF EXISTS {fq(s, 'SMOKE_ORDERS')}",
        f"DROP TABLE IF EXISTS {fq(s, 'SMOKE_DOCS')}",
    ):
        try:
            cur.execute(stmt)
            print(f"cleanup OK: {stmt}")
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup FAILED: {stmt}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="confirm you accept small Cortex costs")
    parser.add_argument("--keep", action="store_true", help="keep sandbox objects for inspection")
    parser.add_argument(
        "--skip-complete", action="store_true", help="skip AI_COMPLETE probes (already known)"
    )
    args = parser.parse_args()
    if not args.yes:
        print(
            "This script calls paid Cortex services (small amounts). Re-run with --yes to proceed."
        )
        return 2

    s = load_settings()
    rest = SnowflakeRestClient(s)
    probe = Probe()
    with session(s, schema=SCHEMA) as conn:
        try:
            if not args.skip_complete:
                probe.run(
                    "AI_COMPLETE (native model)", lambda: probe_ai_complete(conn, "llama3.1-8b")
                )
                probe.run(
                    "AI_COMPLETE (frontier, cross-region)",
                    lambda: probe_ai_complete(conn, FRONTIER_MODEL),
                )
            setup_sandbox_data(conn, s)
            sv_ok = probe.run("Semantic view", lambda: probe_semantic_view(conn, s))
            if sv_ok:
                probe.run("Cortex Analyst REST", lambda: probe_analyst(conn, rest, s))
            search_ok = probe.run("Cortex Search", lambda: probe_search(conn, s))
            if sv_ok and search_ok:
                probe.run("Cortex Agent REST (both tools)", lambda: probe_agent(conn, rest, s))
            elif sv_ok:
                probe.run(
                    "Cortex Agent REST (Analyst tool only)",
                    lambda: probe_agent(conn, rest, s, include_search=False),
                )
        finally:
            if not args.keep:
                print("\n--- cleanup")
                cleanup(conn, s)

    print("\n=== SUMMARY")
    for name, ok, detail in probe.results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return 0 if all(ok for _, ok, _ in probe.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
