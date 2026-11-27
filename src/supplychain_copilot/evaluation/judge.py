"""LLM-as-judge groundedness score: a second signal beside the phrase and SQL checks (backlog #6).

The phrase checks are precise but brittle (S7 run 1, A3 repeat 2 were correct answers scored as
failures). The judge reads the question, the evidence the agent actually received (SQL result rows,
retrieved passages) and the answer, and lists any factual claim the evidence does not support.

Design choices (ADR-031):
  * A judge from a different vendor than the agent's orchestration model (openai-gpt-5.4 vs
    claude-opus-5-5), so it is not grading its own family's output.
  * Structured output (AI_COMPLETE response_format JSON schema), temperature 0.
  * Calibrated before it is trusted: real answers are perturbed (a changed number, an invented
    clause); the judge must flag the perturbations and pass the originals.
  * A second signal only: a judge flag is reviewed by a person, it never overrides the SQL checks.

Inputs: data/processed/eval_v2_results_<label>.json written by `runner --yes --repeat <label>`
(includes an `evidence` list per case). Run as the dev role (AI_COMPLETE, a few cents per call):

  .venv\\Scripts\\python -m supplychain_copilot.evaluation.judge judge1 --yes
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from supplychain_copilot.config import PROJECT_ROOT

JUDGE_MODEL = "openai-gpt-5.4"
PROCESSED = PROJECT_ROOT / "data" / "processed"
REPORT = PROJECT_ROOT / "docs" / "judge_report.md"
# v1 used 40 rows, which hid A3's answer row (judge run 1); 200 covers every eval result set.
MAX_ROWS, MAX_PASSAGES, MAX_PASSAGE_CHARS = 200, 8, 1800
VERDICTS = ["grounded", "partially_grounded", "ungrounded", "no_factual_claims"]

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "unsupported_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["claim", "reason"],
                "additionalProperties": False,
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "unsupported_claims", "rationale"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You are auditing an AI assistant's answer for groundedness.
Compare every factual claim in ANSWER with EVIDENCE (the SQL result rows and document passages the
assistant actually received for this question).

Count as SUPPORTED:
- values that appear in the evidence, or follow from it by correct arithmetic or rounding
  (for example a percentage computed from two counts in the evidence)
- document statements that the passages state, even if paraphrased
- statements that restate SYSTEM CONTEXT: the assistant's own instructions, its tool descriptions
  and the governed metric and table definitions (data source and scope, metric definitions,
  counting rules, what the data does not contain, which documents exist, app input limits)
- refusals, offers to help, clarifying questions, and generic safety advice inside a refusal

Count as UNSUPPORTED:
- any number, name, deadline, section or page number that contradicts or is absent from the evidence
- causes or explanations the evidence does not state
- document requirements not stated in the passages

Verdicts: grounded = no unsupported claims; partially_grounded = minor unsupported detail while the
main answer is supported; ungrounded = a main claim is unsupported or contradicted;
no_factual_claims = a refusal or clarifying question with nothing to check.
List each unsupported claim briefly. Be strict about numbers and document requirements."""


def evidence_of(answer: Any) -> list[str]:
    """What the agent actually saw: SQL result rows and retrieved passages (bounded)."""
    out: list[str] = []
    for t in answer.tool_calls:
        if t.rows:
            rows = "\n".join(" | ".join(str(v) for v in r) for r in t.rows[:MAX_ROWS])
            more = f"\n... {len(t.rows) - MAX_ROWS} more rows" if len(t.rows) > MAX_ROWS else ""
            out.append(f"SQL result\ncolumns: {' | '.join(t.columns)}\n{rows}{more}")
        for p in t.search_results[:MAX_PASSAGES]:
            out.append(
                f"Passage from {p.get('doc_title', '')}:\n{str(p.get('text', ''))[:MAX_PASSAGE_CHARS]}"
            )
    return out


def system_context() -> str:
    """The context the assistant itself was given, read from the deployed definitions (not written
    for the judge): agent instructions and tool descriptions, semantic-view comments, input limit.
    Judge run 1 lacked this and flagged standard framing as unsupported on 26 of 37 answers."""
    import re as _re

    from supplychain_copilot.agent.client import MAX_QUESTION_CHARS

    agent = (PROJECT_ROOT / "sql" / "70_agent" / "01_supply_chain_copilot_agent.sql").read_text(
        encoding="utf-8"
    )
    instr = agent[agent.index("instructions:") : agent.index("  sample_questions:")]
    tools = agent[agent.index("tools:") : agent.index("tool_resources:")]
    sv = (PROJECT_ROOT / "sql" / "40_semantic" / "01_supply_chain_delivery_sv.sql").read_text(
        encoding="utf-8"
    )
    comments = [c.replace("''", "'") for c in _re.findall(r"COMMENT\s*=\s*'((?:[^']|'')*)'", sv)]
    return (
        f"Assistant instructions:\n{instr}\nTool descriptions:\n{tools}\n"
        "Governed metric and table definitions:\n- " + "\n- ".join(comments) + "\n"
        f"App limit: questions are limited to {MAX_QUESTION_CHARS} characters.\n"
    )


def build_prompt(question: str, evidence: list[str], answer: str, context: str = "") -> str:
    ev = "\n\n---\n\n".join(evidence) if evidence else "(no tool evidence: nothing was retrieved)"
    ctx = f"\n\nSYSTEM CONTEXT:\n{context}" if context else ""
    return f"{INSTRUCTIONS}{ctx}\n\nQUESTION:\n{question}\n\nEVIDENCE:\n{ev}\n\nANSWER:\n{answer}"


def judge(
    conn, question: str, evidence: list[str], answer: str, context: str = ""
) -> dict[str, Any]:
    from supplychain_copilot.snowflake.connection import query

    sql = (
        "SELECT AI_COMPLETE(model => %s, prompt => %s, "
        "model_parameters => {'temperature': 0, 'max_tokens': 1500}, "
        "response_format => PARSE_JSON(%s)) AS R"
    )
    fmt = json.dumps({"type": "json", "schema": SCHEMA})
    prompt = build_prompt(question, evidence, answer, context)
    raw = query(conn, sql, (JUDGE_MODEL, prompt, fmt))[0]["R"]
    out = json.loads(raw) if isinstance(raw, str) else raw
    if out.get("verdict") not in VERDICTS:
        raise ValueError(f"judge returned no valid verdict: {str(out)[:200]}")
    return out


# ----------------------------------------------------------------------------- calibration

_PCT = re.compile(r"(?<![\d.])(\d{1,2}\.\d)%")
FAKE_CLAUSE = (
    " Suppliers must also pay a $5,000 penalty for every corrective action closed late "
    "(Supplier Quality Assurance Manual, §7.5, PDF p. 33)."
)


def perturb_number(text: str) -> str | None:
    """Shift the first one-decimal percentage by 7.3 points: a plausible-looking wrong figure."""
    m = _PCT.search(text)
    if not m:
        return None
    v = float(m.group(1))
    new = f"{(v + 7.3) if v < 90 else (v - 7.3):.1f}%"
    return text[: m.start()] + new + text[m.end() :]


def perturb_clause(text: str) -> str:
    """Insert a fabricated document requirement after the first sentence."""
    i = text.find(". ")
    i = i + 1 if i != -1 else len(text)
    return text[:i] + FAKE_CLAUSE + text[i:]


def calibration_items(cases: list[dict]) -> list[dict]:
    """Originals plus perturbed copies. Number edits only where the original used SQL evidence;
    clause insertions only where it used passages (so the fake can be checked against them)."""
    items = []
    for c in cases:
        if not c.get("passed") or not c.get("text"):
            continue
        ev = c.get("evidence", [])
        items.append({**c, "variant": "original", "expect_flag": False})
        has_sql = any(e.startswith("SQL result") for e in ev)
        has_docs = any(e.startswith("Passage from") for e in ev)
        if has_sql and (t := perturb_number(c["text"])):
            items.append({**c, "variant": "wrong_number", "text": t, "expect_flag": True})
        if has_docs:
            items.append(
                {
                    **c,
                    "variant": "invented_clause",
                    "text": perturb_clause(c["text"]),
                    "expect_flag": True,
                }
            )
    return items


def flagged(result: dict) -> bool:
    return result["verdict"] in ("ungrounded", "partially_grounded")


def summarise(items: list[dict]) -> dict[str, Any]:
    orig = [i for i in items if i["variant"] == "original"]
    pert = [i for i in items if i["expect_flag"]]
    by = {}
    for v in ("wrong_number", "invented_clause"):
        xs = [i for i in pert if i["variant"] == v]
        by[v] = (sum(flagged(i["judge"]) for i in xs), len(xs))
    return {
        "originals": len(orig),
        "originals_flagged": [i["id"] for i in orig if flagged(i["judge"])],
        "perturbed_caught": sum(flagged(i["judge"]) for i in pert),
        "perturbed": len(pert),
        "by_variant": by,
        "verdicts": {v: sum(i["judge"]["verdict"] == v for i in orig) for v in VERDICTS},
    }


def render(label: str, s: dict, items: list[dict]) -> str:
    lines = [
        "# LLM-as-judge groundedness (generated)",
        "",
        f"Answers from `eval_v2_results_{label}.json`, judged by `{JUDGE_MODEL}` against the evidence "
        "each answer received. Review: `docs/evaluation_findings.md`, ADR-031.",
        "",
        "## Calibration (planted errors)",
        "",
        "| Planted error | Caught |",
        "|---|---|",
    ]
    for v, (caught, n) in s["by_variant"].items():
        lines.append(f"| {v.replace('_', ' ')} | {caught} / {n} |")
    lines += [
        "",
        f"## Verdicts on the {s['originals']} unmodified answers",
        "",
        "| Verdict | Count |",
        "|---|---|",
    ]
    lines += [f"| {v} | {n} |" for v, n in s["verdicts"].items()]
    lines += ["", "## Flags on unmodified answers (reviewed in the findings)", ""]
    flagged_orig = [i for i in items if i["variant"] == "original" and flagged(i["judge"])]
    if not flagged_orig:
        lines.append("None.")
    for i in flagged_orig:
        lines.append(f"### {i['id']}: {i['judge']['verdict']}")
        lines += [f"- *{u['claim']}*: {u['reason']}" for u in i["judge"]["unsupported_claims"]]
        lines.append("")
    missed = [i for i in items if i["expect_flag"] and not flagged(i["judge"])]
    lines += ["", "## Planted errors the judge missed", ""]
    lines += [f"- {i['id']} ({i['variant']})" for i in missed] or ["None."]
    return "\n".join(lines) + "\n"


def main() -> int:
    from supplychain_copilot.snowflake.connection import session

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("label", help="repeat-run label with evidence (eval_v2_results_<label>.json)")
    p.add_argument("--yes", action="store_true", help="confirm AI_COMPLETE cost")
    p.add_argument("--no-context", action="store_true", help="v1 behaviour: no system context")
    p.add_argument("--tag", default="", help="suffix for the output files")
    args = p.parse_args()
    if not args.yes:
        print("Calls AI_COMPLETE once per item (paid, cents each). Add --yes.")
        return 2
    data = json.loads(
        (PROCESSED / f"eval_v2_results_{args.label}.json").read_text(encoding="utf-8")
    )
    cases = [c for c in data["cases"] if "evidence" in c]
    if not cases:
        raise SystemExit("no evidence in that run; re-run `runner --yes --repeat LABEL`")
    items = calibration_items(cases)
    context = "" if args.no_context else system_context()
    with session() as conn:
        for i in items:
            i["judge"] = judge(conn, i["question"], i["evidence"], i["text"], context)
            mark = "FLAG" if flagged(i["judge"]) else "ok  "
            exp = "expected" if flagged(i["judge"]) == i["expect_flag"] else "UNEXPECTED"
            print(f"[{mark}] {i['id']:<4} {i['variant']:<16} {i['judge']['verdict']:<20} {exp}")
    s = summarise(items)
    out = PROCESSED / f"judge_results_{args.label}{args.tag}.json"
    out.write_text(
        json.dumps({"summary": s, "items": items}, indent=2, default=str), encoding="utf-8"
    )
    report = REPORT.with_name(REPORT.stem + args.tag + REPORT.suffix)
    report.write_text(render(args.label, s, items), encoding="utf-8")
    print(
        f"perturbations caught {s['perturbed_caught']}/{s['perturbed']}; originals flagged "
        f"{len(s['originals_flagged'])}/{s['originals']}; wrote {report.relative_to(PROJECT_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
