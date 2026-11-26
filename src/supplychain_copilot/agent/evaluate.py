"""Run the Phase 6 agent test cases and write docs/agent_test_report.md.

For each case: ask the agent (as SCC_APP_ROLE), then check
  * required tools were used (and no SQL for unsafe/unsupported cases where relevant)
  * answer text contains every required group (any listed alternative)
  * forbidden patterns are absent (causal claims, credentials, fabricated rates)
  * at least one citation points at an expected document page (citation chunk -> DOCS metadata)
  * every SQL result set the agent returned matches an independent re-execution as SCC_APP_ROLE
  * write attempts did not change data (FACT_ORDERS row count unchanged)
INCURS CORTEX AGENT COST (one agent run per case). Requires --yes.

Usage:
    python -m supplychain_copilot.agent.evaluate --yes
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from supplychain_copilot.agent import RUNTIME_ROLE
from supplychain_copilot.agent.client import AgentAnswer, CopilotAgent
from supplychain_copilot.config import PROJECT_ROOT, load_settings
from supplychain_copilot.documents.pipeline import CHUNKS_PARQUET
from supplychain_copilot.snowflake.connection import app_session, query, session

EVAL_SET = PROJECT_ROOT / "eval" / "agent_eval_set.json"
REPORT = PROJECT_ROOT / "docs" / "agent_test_report.md"
WRITE_SQL = re.compile(
    r"(?i)\b(insert|update|delete|merge|drop|truncate|alter|create|grant|revoke)\b"
)


@dataclass
class CaseResult:
    case: dict[str, Any]
    answer: AgentAnswer
    checks: dict[str, tuple[bool, str]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(ok for ok, _ in self.checks.values())


def _num(v: Any) -> Any:
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _rows_equal(a: list[list[Any]], b: list[list[Any]]) -> bool:
    if len(a) != len(b):
        return False
    norm = lambda rows: sorted([[_num(x) for x in r] for r in rows], key=str)  # noqa: E731
    for ra, rb in zip(norm(a), norm(b), strict=False):
        if len(ra) != len(rb):
            return False
        for x, y in zip(ra, rb, strict=False):
            if isinstance(x, float) and isinstance(y, float):
                if not math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9):
                    return False
            elif str(x) != str(y):
                return False
    return True


def check_case(
    case: dict, ans: AgentAnswer, chunks: pd.DataFrame, conn, orders_before: int | None
) -> CaseResult:
    r = CaseResult(case, ans)
    text = ans.text.lower()
    r.checks["completed"] = (ans.ok, ans.error or ans.status or "")
    missing_tools = [t for t in case.get("tools", []) if t not in ans.tools_used]
    r.checks["tools"] = (
        not missing_tools,
        f"used {sorted(ans.tools_used)}; missing {missing_tools}",
    )
    missing_text = [
        grp for grp in case.get("text_all", []) if not any(alt.lower() in text for alt in grp)
    ]
    r.checks["text_contains"] = (
        not missing_text,
        f"missing groups: {missing_text}" if missing_text else "all present",
    )
    hits = [p for p in case.get("text_none", []) if re.search(p, ans.text)]
    r.checks["forbidden_absent"] = (not hits, f"matched: {hits}" if hits else "none matched")
    if case.get("cite"):
        idx = chunks.set_index("chunk_id")
        cited = [
            (
                idx.loc[c.chunk_id].document_id,
                idx.loc[c.chunk_id].page_number,
                idx.loc[c.chunk_id].page_end,
            )
            for c in ans.citations
            if c.chunk_id in idx.index
        ]
        ok = any(
            doc == e["doc"] and start <= e["page"] <= end
            for e in case["cite"]
            for doc, start, end in cited
        )
        r.checks["citation"] = (
            ok,
            f"{len(ans.citations)} citations; expected one of {case['cite']}",
        )
    if case.get("reconcile_sql"):
        sql_calls = [t for t in ans.tool_calls if t.sql and t.rows]
        bad = []
        for t in sql_calls:
            mine = query(conn, t.sql)
            mine_rows = [list(row.values()) for row in mine]
            if not _rows_equal(mine_rows, t.rows):
                bad.append(t.sql[:80])
        r.checks["sql_reconciles"] = (
            bool(sql_calls) and not bad,
            f"{len(sql_calls)} result sets re-executed as {RUNTIME_ROLE}; mismatches {bad}",
        )
    if case.get("no_write_sql"):
        writes = [s for s in ans.sql_statements if WRITE_SQL.search(re.sub(r"--.*", "", s))]
        r.checks["no_write_sql"] = (
            not writes,
            f"write statements: {writes}" if writes else "no write SQL generated",
        )
    if case.get("check_orders_unchanged") and orders_before is not None:
        after = query(conn, "SELECT COUNT(*) AS N FROM SCC_DB.GOLD.FACT_ORDERS")[0]["N"]
        r.checks["data_unchanged"] = (
            after == orders_before,
            f"FACT_ORDERS rows {orders_before} -> {after}",
        )
    if ans.redacted:
        r.checks["no_redaction_needed"] = (
            False,
            "output contained a credential-like string and was redacted",
        )
    return r


def run(case_ids: list[str] | None = None) -> list[CaseResult]:
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))["cases"]
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
    chunks = pd.read_parquet(CHUNKS_PARQUET)
    agent = (
        CopilotAgent()
    )  # runtime user SCC_APP_SVC / SCC_APP_ROLE (fails closed if not configured)
    results = []
    # dev session only for the read-only FACT_ORDERS row-count check; SQL re-execution uses the app user.
    with session(load_settings()) as dev, app_session() as app:
        for case in cases:
            before = (
                query(dev, "SELECT COUNT(*) AS N FROM SCC_DB.GOLD.FACT_ORDERS")[0]["N"]
                if case.get("check_orders_unchanged")
                else None
            )
            ans = agent.ask(case["question"])
            res = check_case(case, ans, chunks, app, None)
            if before is not None:  # data check needs GOLD access -> dev role, read-only query
                after = query(dev, "SELECT COUNT(*) AS N FROM SCC_DB.GOLD.FACT_ORDERS")[0]["N"]
                res.checks["data_unchanged"] = (
                    after == before,
                    f"FACT_ORDERS rows {before} -> {after}",
                )
            results.append(res)
            print(
                f"[{'PASS' if res.passed else 'FAIL'}] {case['id']} {ans.latency_s:5.1f}s tools={sorted(ans.tools_used)} "
                + "; ".join(f"{k}={'ok' if ok else 'FAIL'}" for k, (ok, _) in res.checks.items())
            )
    return results


def write_report(results: list[CaseResult]) -> None:
    passed = sum(r.passed for r in results)
    lat = sorted(r.answer.latency_s for r in results)
    credits = [
        lim.get("usage")
        for r in results
        for lim in r.answer.usage.get("limits", [])
        if lim.get("name") == "trial_account_estimated_credits"
    ]
    out = [
        "# Phase 6: Cortex Agent test report\n",
        f"_Generated by `python -m supplychain_copilot.agent.evaluate --yes` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. "
        f"Agent `SCC_DB.AI.SUPPLY_CHAIN_COPILOT`, called as read-only role `{RUNTIME_ROLE}`._\n",
        f"**Result: {passed} of {len(results)} cases passed.** Latency (end-to-end, non-streaming): median "
        f"{lat[len(lat) // 2]:.1f}s, max {lat[-1]:.1f}s.",
        (
            f"Trial AI credit meter reported by the agent API: {credits[0]:.3f} before the first case and {credits[-1]:.3f} "
            "after the last (limit 20)."
            if credits
            else ""
        ),
        "\n| ID | Category | Tools used | Checks | Latency |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        checks = ", ".join(f"{k} {'✅' if ok else '❌'}" for k, (ok, _) in r.checks.items())
        out.append(
            f"| {r.case['id']} | {r.case['category']} | {', '.join(sorted(r.answer.tools_used)) or '-'} | {checks} | {r.answer.latency_s:.1f}s |"
        )
    for r in results:
        a = r.answer
        out += [
            f"\n## {r.case['id']} ({r.case['category']}): {r.case['question']}\n",
            f"**Verdict:** {'PASS' if r.passed else 'FAIL'}\n",
        ]
        for k, (ok, detail) in r.checks.items():
            out.append(f"- {'✅' if ok else '❌'} `{k}`: {detail}")
        if a.sql_statements:
            out.append("\n**SQL run by the agent** (governed semantic view):\n")
            for s in a.sql_statements:
                out.append(f"```sql\n{s.strip()}\n```")
        searches = [t.query for t in a.tool_calls if t.query]
        if searches:
            out.append("\n**Search queries issued:** " + "; ".join(f"`{q}`" for q in searches))
        if a.citations:
            out.append("\n**Citations:**\n" + "\n".join(f"- {c.label}" for c in a.citations))
        out.append("\n**Answer:**\n\n> " + a.text.replace("\n", "\n> "))
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--yes", action="store_true", help="confirm Cortex Agent cost (one run per case)"
    )
    p.add_argument("--only", nargs="*", help="case ids to run")
    args = p.parse_args()
    if not args.yes:
        print("Runs the Cortex Agent once per case (paid). Re-run with --yes.")
        return 2
    results = run(args.only)
    write_report(results)
    print(
        f"\n{sum(r.passed for r in results)}/{len(results)} passed. Wrote {REPORT.relative_to(PROJECT_ROOT)}"
    )
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
