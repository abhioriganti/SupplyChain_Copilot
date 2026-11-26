"""Phase 8 evaluation runner -> docs/evaluation_report.md (+ data/processed/eval_v2_results.json).

Runs eval/eval_set_v2.json against the live agent as the read-only runtime user and checks:
  per case : completed / expected error, required tools, required facts, SQL ground truth (computed now
             from GOLD views), forbidden patterns, expected citation page, SQL result reconciliation,
             data unchanged after write attempts
  every case: no write SQL, no credential/config leakage, no causal supplier claim
  flagged   : numbers not traceable to tool evidence (reported for review, not auto-failed)
Also: runtime privilege-boundary probe (no Cortex cost) and the SQL data-quality suites.
Every agent request is logged to SCC_DB.APP.AGENT_REQUEST_LOG with the eval run id and outcome.
INCURS CORTEX AGENT COST (~one run per case). Requires --yes.

Usage:
    python -m supplychain_copilot.evaluation.runner --yes [--only S1 H1 ...]
"""

from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from supplychain_copilot.agent.client import AgentAnswer, CopilotAgent
from supplychain_copilot.agent.evaluate import _rows_equal
from supplychain_copilot.config import PROJECT_ROOT, load_settings
from supplychain_copilot.documents.pipeline import CHUNKS_PARQUET
from supplychain_copilot.evaluation import checks
from supplychain_copilot.observability import build_log_record, log_request
from supplychain_copilot.snowflake.connection import app_session, query, session

EVAL_SET = PROJECT_ROOT / "eval" / "eval_set_v2.json"
REPORT = PROJECT_ROOT / "docs" / "evaluation_report.md"
RESULTS = PROJECT_ROOT / "data" / "processed" / "eval_v2_results.json"
PRIVILEGE_PROBES = [
    (
        "SELECT governed semantic view",
        "SELECT * FROM SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV METRICS orders.total_orders)",
        True,
    ),
    ("SELECT raw GOLD table", "SELECT COUNT(*) FROM SCC_DB.GOLD.FACT_ORDERS", False),
    ("SELECT BRONZE table", "SELECT COUNT(*) FROM SCC_DB.BRONZE.DATACO_ORDER_LINES", False),
    ("DELETE from GOLD", "DELETE FROM SCC_DB.GOLD.FACT_ORDERS WHERE 1=0", False),
    ("DROP TABLE", "DROP TABLE SCC_DB.GOLD.FACT_ORDERS", False),
    ("CREATE TABLE", "CREATE TABLE SCC_DB.AI.SHOULD_NOT_EXIST (A INT)", False),
    ("SELECT feedback log (insert-only)", "SELECT COUNT(*) FROM SCC_DB.APP.AGENT_FEEDBACK", False),
    ("USE ROLE developer", "USE ROLE SCC_DEV_ROLE", False),
]


@dataclass
class CaseResult:
    case: dict[str, Any]
    answer: AgentAnswer
    checks: dict[str, tuple[bool, str]] = field(default_factory=dict)
    ungrounded: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(ok for ok, _ in self.checks.values())


def _question(case: dict) -> str:
    return "x" * 2500 if case["question"] == "LONG_INPUT_2500" else case["question"]


def evaluate_case(
    case: dict, ans: AgentAnswer, truth: dict | None, chunks: pd.DataFrame, app_conn
) -> CaseResult:
    r = CaseResult(case, ans)
    if case.get("expect_error"):
        ok = bool(ans.error) and ans.error.startswith(case["expect_error"]) and not ans.tool_calls
        r.checks["expected_error"] = (ok, ans.error or "no error")
        return r
    r.checks["completed"] = (ans.ok, ans.error or ans.status or "")
    missing = [t for t in case.get("tools", []) if t not in ans.tools_used]
    r.checks["tools"] = (not missing, f"used {sorted(ans.tools_used)}; missing {missing}")
    if case.get("text_all"):
        miss = checks.missing_groups(ans.text, case["text_all"])
        r.checks["facts"] = (not miss, f"missing {miss}" if miss else "present")
    if case.get("truth_contains"):
        groups = checks.render_truth_groups(case["truth_contains"], truth or {})
        miss = checks.missing_groups(ans.text, groups)
        r.checks["ground_truth"] = (
            not miss,
            f"truth {truth}; missing {miss}" if miss else f"matches truth {truth}",
        )
    if case.get("text_none"):
        import re

        hits = [p for p in case["text_none"] if re.search(p, ans.text)]
        r.checks["forbidden"] = (not hits, f"matched {hits}" if hits else "none")
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
        ok = any(d == e["doc"] and s <= e["page"] <= t for e in case["cite"] for d, s, t in cited)
        r.checks["citation"] = (ok, f"{len(ans.citations)} citations; expected {case['cite']}")
    if case.get("reconcile_sql"):
        calls = [t for t in ans.tool_calls if t.sql and t.rows]
        bad = [
            t.sql[:80]
            for t in calls
            if not _rows_equal([list(x.values()) for x in query(app_conn, t.sql)], t.rows)
        ]
        r.checks["sql_reconciles"] = (
            bool(calls) and not bad,
            f"{len(calls)} result sets re-executed; mismatches {bad}",
        )
    w, lk, cz = checks.write_sql(ans), checks.leaks(ans), checks.causal_claims(ans)
    ug = checks.ungoverned_sql(ans)
    r.checks["governed_sql"] = (
        not ug,
        f"SQL bypassing the semantic view: {ug}" if ug else "all SQL via SEMANTIC_VIEW",
    )
    r.checks["no_write_sql"] = (not w, f"{w}" if w else "none")
    r.checks["no_leak"] = (not lk, f"{lk}" if lk else "none")
    r.checks["no_causal_claim"] = (not cz, f"{cz}" if cz else "none")
    r.ungrounded = checks.ungrounded_numbers(ans)
    return r


def privilege_boundary() -> list[tuple[str, bool, bool, str]]:
    out = []
    with app_session() as c:
        for label, sql, expected in PRIVILEGE_PROBES:
            try:
                query(c, sql)
                out.append((label, expected, True, "allowed"))
            except Exception as exc:  # noqa: BLE001 - denial is the expected outcome for most probes
                out.append((label, expected, False, str(exc).splitlines()[0][:90]))
    return out


def sql_suites() -> dict[str, tuple[int, int]]:
    from supplychain_copilot.warehouse.sql_tests import run_test_file

    res = {}
    for f in ("test_phase2_model.sql", "test_phase4_documents.sql"):
        rows = run_test_file(PROJECT_ROOT / "sql" / "tests" / f, run_id=f"eval-{uuid.uuid4()}")
        res[f] = (sum(1 for r in rows if r["FAILURES"] == 0), len(rows))
    return res


def run(only: list[str] | None = None) -> tuple[str, list[CaseResult]]:
    cases = json.loads(EVAL_SET.read_text(encoding="utf-8"))["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    run_id = f"eval-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    chunks = pd.read_parquet(CHUNKS_PARQUET)
    agent = CopilotAgent()
    results = []
    with session(load_settings()) as dev, app_session() as app:
        for case in cases:
            truth = query(dev, case["truth_sql"])[0] if case.get("truth_sql") else None
            before = (
                query(dev, "SELECT COUNT(*) N FROM SCC_DB.GOLD.FACT_ORDERS")[0]["N"]
                if case.get("check_orders_unchanged")
                else None
            )
            ans = agent.ask(_question(case))
            res = evaluate_case(case, ans, truth, chunks, app)
            if before is not None:
                after = query(dev, "SELECT COUNT(*) N FROM SCC_DB.GOLD.FACT_ORDERS")[0]["N"]
                res.checks["data_unchanged"] = (after == before, f"FACT_ORDERS {before} -> {after}")
            log_request(
                build_log_record(
                    ans,
                    "eval",
                    eval_run_id=run_id,
                    eval_case_id=case["id"],
                    eval_outcome="pass" if res.passed else "fail",
                )
            )
            results.append(res)
            fails = [k for k, (ok, _) in res.checks.items() if not ok]
            print(
                f"[{'PASS' if res.passed else 'FAIL'}] {case['id']:<3} {ans.latency_s:5.1f}s tools={sorted(ans.tools_used)} "
                f"{'fails=' + str(fails) if fails else ''} {'ungrounded=' + str(res.ungrounded) if res.ungrounded else ''}"
            )
    return run_id, results


def write_report(
    run_id: str, results: list[CaseResult], probes, suites, retrieval: dict | None
) -> None:
    by_cat: dict[str, list[CaseResult]] = {}
    for r in results:
        by_cat.setdefault(r.case["category"], []).append(r)
    failed_checks = Counter(k for r in results for k, (ok, _) in r.checks.items() if not ok)
    agent_runs = [r for r in results if not r.case.get("expect_error")]
    lat = sorted(r.answer.latency_s for r in agent_runs) or [0.0]
    out = [
        "# Phase 8: evaluation report\n",
        f"_Generated by `python -m supplychain_copilot.evaluation.runner --yes` · run `{run_id}` · "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Agent called as read-only `SCC_APP_SVC` / `SCC_APP_ROLE`. "
        "All figures below are counts from this run. Nothing is estimated or hand-entered._\n",
        f"## Summary: {sum(r.passed for r in results)} of {len(results)} cases passed\n",
        "| Category | Passed / total |",
        "|---|---|",
    ]
    for cat, rs in by_cat.items():
        out.append(f"| {cat} | {sum(r.passed for r in rs)} / {len(rs)} |")
    out += [
        f"\nCheck failures across all cases: {dict(failed_checks) or 'none'}.",
        f"Agent latency (non-streaming, {len(agent_runs)} runs): median {lat[len(lat) // 2]:.1f}s, max {lat[-1]:.1f}s.",
        f"Numbers flagged as not directly traceable to tool evidence: {sum(len(r.ungrounded) for r in results)} "
        f"across {sum(1 for r in results if r.ungrounded)} answers (reviewed in `docs/evaluation_findings.md`).\n",
        "## Per-case results\n",
        "| ID | Category | Result | Tools | Failed checks | Untraced numbers | Latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        fails = [k for k, (ok, _) in r.checks.items() if not ok]
        out.append(
            f"| {r.case['id']} | {r.case['category']} | {'✅' if r.passed else '❌'} | "
            f"{', '.join(sorted(r.answer.tools_used)) or '-'} | {', '.join(fails) or '-'} | "
            f"{', '.join(r.ungrounded) or '-'} | {r.answer.latency_s:.1f}s |"
        )
    out += [
        "\n## Security: runtime privilege boundary (live, no Cortex cost)\n",
        "| Probe as SCC_APP_SVC | Expected | Observed | Result |",
        "|---|---|---|---|",
    ]
    for label, expected, allowed, detail in probes:
        out.append(
            f"| {label} | {'allowed' if expected else 'denied'} | {'allowed' if allowed else 'denied'} "
            f"({detail[:60]}) | {'✅' if expected == allowed else '❌'} |"
        )
    out += ["\n## Data quality: SQL test suites\n"]
    for f, (p, n) in suites.items():
        out.append(f"- `{f}`: {p} of {n} pass")
    if retrieval:
        s = retrieval["summary"][retrieval["selected_config"]]
        ci = retrieval["citation_integrity"]
        out += [
            "\n## Retrieval (Cortex Search, from `docs/retrieval_eval_report.md`)\n",
            f"Configuration `{retrieval['selected_config']}`, {s['questions']} labelled questions: "
            f"doc@1 {s['doc@1']:.1%}, hit@1 {s['hit@1']:.1%}, hit@3 {s['hit@3']:.1%}, hit@5 {s['hit@5']:.1%}, "
            f"answer@5 {s['answer@5']:.1%}, MRR@5 {s['mrr@5']:.3f}; citation integrity {ci['checked'] - ci['mismatched']} "
            f"of {ci['checked']} passages.",
        ]
    out += ["\n## Case details\n"]
    for r in results:
        out.append(f"### {r.case['id']} ({r.case['category']}): {r.case['question'][:160]}\n")
        for k, (ok, d) in r.checks.items():
            out.append(f"- {'✅' if ok else '❌'} `{k}`: {d}")
        if r.ungrounded:
            out.append(f"- ⚠️ untraced numbers: {r.ungrounded}")
        for s in r.answer.sql_statements:
            out.append(f"\n```sql\n{s.strip()}\n```")
        if r.answer.citations:
            out.append("\nCitations: " + "; ".join(c.label for c in r.answer.citations))
        out.append("\n> " + (r.answer.text or "(no text)").replace("\n", "\n> ") + "\n")
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "cases": [
                    {
                        "id": r.case["id"],
                        "category": r.case["category"],
                        "passed": r.passed,
                        "checks": {k: {"ok": ok, "detail": d} for k, (ok, d) in r.checks.items()},
                        "ungrounded": r.ungrounded,
                        "latency_s": round(r.answer.latency_s, 2),
                        "tools": sorted(r.answer.tools_used),
                        "text": r.answer.text,
                    }
                    for r in results
                ],
                "privilege_probes": probes,
                "sql_suites": suites,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--yes", action="store_true", help="confirm Cortex Agent cost")
    p.add_argument("--only", nargs="*")
    args = p.parse_args()
    if not args.yes:
        print("Runs the Cortex Agent once per case (paid). Re-run with --yes.")
        return 2
    run_id, results = run(args.only)
    probes = privilege_boundary()
    suites = sql_suites()
    retr_path = PROJECT_ROOT / "data" / "processed" / "retrieval_eval_results.json"
    retrieval = json.loads(retr_path.read_text(encoding="utf-8")) if retr_path.exists() else None
    write_report(run_id, results, probes, suites, retrieval)
    print(
        f"\n{sum(r.passed for r in results)}/{len(results)} passed; privilege probes "
        f"{sum(e == a for _, e, a, _ in probes)}/{len(probes)} as expected; suites {suites}. Wrote {REPORT.relative_to(PROJECT_ROOT)}"
    )
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
