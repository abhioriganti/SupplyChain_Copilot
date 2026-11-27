"""Multi-turn evaluation (backlog item 3): follow-ups, pronouns, topic switches, late injection.

    python -m supplychain_copilot.evaluation.multiturn --yes        # paid: one agent call per turn

Each conversation is replayed turn by turn with the app's history format (agent text answers, last
three pairs). Every turn is scored with the single-turn checks (evaluation.runner.evaluate_case).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from supplychain_copilot.agent.client import AgentAnswer, CopilotAgent
from supplychain_copilot.config import PROJECT_ROOT, load_settings
from supplychain_copilot.documents.pipeline import CHUNKS_PARQUET
from supplychain_copilot.evaluation.runner import CaseResult, evaluate_case
from supplychain_copilot.observability import build_log_record, log_request
from supplychain_copilot.snowflake.connection import app_session, query, session

SET = PROJECT_ROOT / "eval" / "multiturn_set.json"
RESULTS = PROJECT_ROOT / "data" / "processed" / "multiturn_results.json"
REPORT = PROJECT_ROOT / "docs" / "multiturn_report.md"
HISTORY_TURNS = 3  # same as app/streamlit_app.py


def history_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def next_history(history: list[dict], question: str, answer: AgentAnswer) -> list[dict]:
    """Append the turn the way the app does: errors are not added; keep the last 3 pairs."""
    if answer.error:
        return history
    out = history + [history_message("user", question), history_message("assistant", answer.text)]
    return out[-2 * HISTORY_TURNS :]


def scripted_history(conv: dict) -> list[dict]:
    pairs = conv.get("scripted_history", [])[-HISTORY_TURNS:]
    return [
        m for q, a in pairs for m in (history_message("user", q), history_message("assistant", a))
    ]


def load() -> list[dict]:
    return json.loads(SET.read_text(encoding="utf-8"))["conversations"]


def run(only: list[str] | None = None) -> tuple[str, list[tuple[dict, int, CaseResult]]]:
    run_id = f"mt-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    chunks = pd.read_parquet(CHUNKS_PARQUET)
    agent = CopilotAgent()
    out: list[tuple[dict, int, CaseResult]] = []
    with session(load_settings()) as dev, app_session() as app:
        for conv in (c for c in load() if not only or c["id"] in only):
            # Optional scripted prior turns: the exact history the app would send at that point.
            history = scripted_history(conv)
            for i, turn in enumerate(conv["turns"], start=1):
                case = {**turn, "id": f"{conv['id']}.{i}", "category": "multi_turn"}
                truth = query(dev, turn["truth_sql"])[0] if turn.get("truth_sql") else None
                ans = agent.ask(turn["question"], history)
                res = evaluate_case(case, ans, truth, chunks, app)
                log_request(
                    build_log_record(
                        ans,
                        "eval",
                        eval_run_id=run_id,
                        eval_case_id=case["id"],
                        eval_outcome="pass" if res.passed else "fail",
                    )
                )
                fails = [k for k, (ok, _) in res.checks.items() if not ok]
                print(
                    f"[{'PASS' if res.passed else 'FAIL'}] {case['id']:<5} {ans.latency_s:5.1f}s "
                    f"tools={sorted(ans.tools_used)} {'fails=' + str(fails) if fails else ''}"
                )
                out.append((conv, i, res))
                history = next_history(history, turn["question"], ans)
    return run_id, out


def write(run_id: str, results: list[tuple[dict, int, CaseResult]], suffix: str = "") -> None:
    """`suffix` keeps a partial run (--only) from overwriting the full report."""
    results_path = RESULTS.with_name(RESULTS.stem + suffix + RESULTS.suffix)
    report_path = REPORT.with_name(REPORT.stem + suffix + REPORT.suffix)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "turns": [
                    {
                        "id": r.case["id"],
                        "pattern": c["pattern"],
                        "question": r.case["question"],
                        "passed": r.passed,
                        "checks": {k: {"ok": ok, "detail": d} for k, (ok, d) in r.checks.items()},
                        "latency_s": round(r.answer.latency_s, 1),
                        "text": r.answer.text,
                    }
                    for c, _, r in results
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    convs = {}
    for c, _, r in results:
        convs.setdefault(c["id"], (c, []))[1].append(r)
    passed_turns = sum(r.passed for _, _, r in results)
    passed_convs = sum(all(r.passed for r in rs) for _, rs in convs.values())
    lines = [
        "# Multi-turn evaluation report (generated)",
        "",
        f"Run `{run_id}` against the production agent as the least-privilege runtime user. "
        f"**{passed_convs} of {len(convs)} conversations** fully passed; "
        f"**{passed_turns} of {len(results)} turns** passed. Review: `docs/evaluation_findings.md`.",
        "",
        "| Conversation | Pattern | Turn | Question | Result | Failed checks |",
        "|---|---|---|---|---|---|",
    ]
    for c, i, r in results:
        fails = "; ".join(f"{k}: {d}" for k, (ok, d) in r.checks.items() if not ok) or "-"
        lines.append(
            f"| {c['id']} | {c['pattern']} | {i} | {r.case['question']} | "
            f"{'✅ pass' if r.passed else '❌ fail'} | {fails[:220]} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"{passed_convs}/{len(convs)} conversations, {passed_turns}/{len(results)} turns passed; "
        f"wrote {report_path.relative_to(PROJECT_ROOT)}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--yes", action="store_true", help="confirm paid agent calls")
    p.add_argument("--only", nargs="*", help="conversation ids; writes *_<ids>.json/md")
    args = p.parse_args()
    if not args.yes:
        print("Runs the Cortex Agent once per turn (paid, about 0.09 credits each). Add --yes.")
        return 2
    run_id, results = run(args.only)
    write(run_id, results, "_" + "_".join(args.only).lower() if args.only else "")
    return 0 if all(r.passed for _, _, r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
