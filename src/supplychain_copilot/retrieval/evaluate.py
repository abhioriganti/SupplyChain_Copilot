"""Measure Cortex Search retrieval quality on eval/retrieval_eval_set.json.

Metrics per retrieval configuration (k = 5):
  doc@1          top passage comes from a labelled document
  hit@k          a passage within the top k is RELEVANT (labelled document AND page overlap)
  answer@k       a passage within the top k is relevant AND contains an evidence phrase
  MRR@5          mean reciprocal rank of the first relevant passage
  section@1      top passage's section shares a page with the labels (= hit@1, reported per category)
  citation_ok    every returned passage's PAGE_NUMBER/PAGE_END/SECTION matches DOCS.DOCUMENT_CHUNKS
  latency        client-side REST round trip, p50 / p95 (ms)
Negative questions report the top reranker score so a "no good evidence" threshold can be chosen.

Usage:
    python -m supplychain_copilot.retrieval.evaluate
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.documents.pipeline import CHUNKS_PARQUET
from supplychain_copilot.retrieval.search_client import CONFIGS, DocumentSearch, Passage

EVAL_SET = PROJECT_ROOT / "eval" / "retrieval_eval_set.json"
REPORT = PROJECT_ROOT / "docs" / "retrieval_eval_report.md"
RESULTS_JSON = PROJECT_ROOT / "data" / "processed" / "retrieval_eval_results.json"
K = 5


@dataclass
class QuestionResult:
    qid: str
    category: str
    question: str
    passages: list[Passage]
    latency_ms: float
    relevant_ranks: list[int] = field(default_factory=list)
    answer_ranks: list[int] = field(default_factory=list)
    doc_at_1: bool = False


def load_eval_set(path: Path = EVAL_SET) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_relevant(p: Passage, labels: list[dict], docs: dict[str, str]) -> bool:
    return any(
        p.document_id == docs[lab["doc"]]
        and any(p.page_number <= pg <= p.page_end for pg in lab["pages"])
        for lab in labels
    )


def has_evidence(p: Passage, evidence: list[str]) -> bool:
    return not evidence or any(e.lower() in p.text.lower() for e in evidence)


def score_question(
    q: dict, passages: list[Passage], latency: float, docs: dict[str, str]
) -> QuestionResult:
    r = QuestionResult(q["id"], q["category"], q["question"], passages, latency)
    labelled_docs = {docs[lab["doc"]] for lab in q["relevant"]}
    r.doc_at_1 = bool(passages) and passages[0].document_id in labelled_docs
    for p in passages:
        if is_relevant(p, q["relevant"], docs):
            r.relevant_ranks.append(p.rank)
            if has_evidence(p, q["evidence"]):
                r.answer_ranks.append(p.rank)
    return r


def summarize(results: list[QuestionResult]) -> dict:
    pos = [r for r in results if r.category != "negative"]
    lat = sorted(r.latency_ms for r in results)

    def rate(cond) -> float:
        return sum(1 for r in pos if cond(r)) / len(pos) if pos else 0.0

    return {
        "questions": len(pos),
        "doc@1": rate(lambda r: r.doc_at_1),
        "hit@1": rate(lambda r: 1 in r.relevant_ranks),
        "hit@3": rate(lambda r: any(x <= 3 for x in r.relevant_ranks)),
        "hit@5": rate(lambda r: bool(r.relevant_ranks)),
        "answer@1": rate(lambda r: 1 in r.answer_ranks),
        "answer@5": rate(lambda r: bool(r.answer_ranks)),
        "mrr@5": sum(1 / min(r.relevant_ranks) for r in pos if r.relevant_ranks) / len(pos)
        if pos
        else 0.0,
        "latency_p50_ms": statistics.median(lat),
        "latency_p95_ms": lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))],
    }


def verify_citations(results_by_config: dict[str, list[QuestionResult]]) -> tuple[int, int]:
    """Every returned passage's page range and section must match the loaded chunk record."""
    truth = pd.read_parquet(CHUNKS_PARQUET).set_index("chunk_id")
    checked = bad = 0
    for results in results_by_config.values():
        for r in results:
            for p in r.passages:
                checked += 1
                t = truth.loc[p.chunk_id] if p.chunk_id in truth.index else None
                if t is None or (t.page_number, t.page_end, t.section_title, t.document_id) != (
                    p.page_number,
                    p.page_end,
                    p.section_title,
                    p.document_id,
                ):
                    bad += 1
    return checked, bad


def run() -> tuple[dict[str, list[QuestionResult]], dict[str, dict]]:
    ev = load_eval_set()
    docs = ev["documents"]
    search = DocumentSearch()
    search.search("warm-up query", limit=1)  # first call includes token/connection setup
    by_config: dict[str, list[QuestionResult]] = {}
    for name, cfg in CONFIGS.items():
        by_config[name] = []
        for q in ev["questions"]:
            res = search.search(q["question"], limit=K, scoring_config=cfg)
            by_config[name].append(score_question(q, res.passages, res.latency_ms, docs))
    return by_config, {name: summarize(rs) for name, rs in by_config.items()}


def write_report(by_config: dict[str, list[QuestionResult]], summary: dict[str, dict]) -> None:
    checked, bad = verify_citations(by_config)
    best = max(
        summary, key=lambda n: (summary[n]["hit@1"], summary[n]["answer@5"], summary[n]["mrr@5"])
    )
    default = by_config["hybrid_rerank"]
    out = [
        "# Phase 5: retrieval evaluation report\n",
        f"_Generated by `python -m supplychain_copilot.retrieval.evaluate` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC "
        "against `SCC_DB.AI.SUPPLIER_DOCS_SEARCH` (Cortex Search, arctic-embed-m-v1.5, 152 chunks)._\n",
        f"Eval set: `eval/retrieval_eval_set.json`, with {summary[best]['questions']} answerable questions (specific and broad) "
        "plus 3 unanswerable ones. Labels (document + PDF pages + evidence phrases) were checked to exist in the "
        "corpus before retrieval was run. k = 5.\n",
        "## Configuration comparison\n",
        "| Config | doc@1 | hit@1 | hit@3 | hit@5 | answer@1 | answer@5 | MRR@5 | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in summary.items():
        out.append(
            f"| {'**' + name + '**' if name == best else name} | {s['doc@1']:.0%} | {s['hit@1']:.0%} | {s['hit@3']:.0%} | "
            f"{s['hit@5']:.0%} | {s['answer@1']:.0%} | {s['answer@5']:.0%} | {s['mrr@5']:.3f} | "
            f"{s['latency_p50_ms']:.0f} | {s['latency_p95_ms']:.0f} |"
        )
    out += [
        "\n- **hit@k:** a top-k passage comes from a labelled document **and** its page range overlaps the labelled pages.",
        "- **answer@k:** that passage also contains a labelled evidence phrase (e.g. '14 working days').",
        "- **Latency:** client-side REST round trip from this machine, including JWT auth and network.",
        f"- **Citation integrity:** {checked - bad} of {checked} returned passages have the same document, section and "
        "page range as the loaded `DOCS.DOCUMENT_CHUNKS` record.\n",
        f"Selected configuration for the agent: **{best}**.\n",
        "## Per-question results (default service configuration: hybrid + rerank)\n",
        "| ID | Category | Question | First relevant rank | Answer-bearing rank | Top-1 citation | Top-1 reranker |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in default:
        top = r.passages[0] if r.passages else None
        rr = top.scores.get("reranker_score") if top else None
        rr_text = f"{rr:.2f}" if rr is not None else "-"
        out.append(
            f"| {r.qid} | {r.category} | {r.question} | {min(r.relevant_ranks) if r.relevant_ranks else '-'} | "
            f"{min(r.answer_ranks) if r.answer_ranks else '-'} | {top.citation if top else '-'} | {rr_text} |"
        )
    pos_scores = [
        r.passages[0].scores.get("reranker_score")
        for r in default
        if r.category != "negative" and r.passages
    ]
    hit_scores = [
        r.passages[0].scores.get("reranker_score") for r in default if 1 in r.relevant_ranks
    ]
    neg_scores = [
        r.passages[0].scores.get("reranker_score")
        for r in default
        if r.category == "negative" and r.passages
    ]
    out += [
        "\n## Can the reranker score flag 'no good evidence'?\n",
        f"- Top-1 reranker score, answerable questions: min {min(pos_scores):.2f}, median {statistics.median(pos_scores):.2f}.",
        f"- Top-1 reranker score where top-1 was relevant: min {min(hit_scores):.2f}.",
        f"- Top-1 reranker score, unanswerable questions: {', '.join(f'{s:.2f}' for s in neg_scores)} (max {max(neg_scores):.2f}).",
        "- These scores are unbounded and model-specific, and there are only 3 negative questions. Any threshold must "
        "be validated on more data before it is trusted; Phase 6 uses it only as a **signal** for the agent to say "
        "evidence is weak, not as a hard filter.",
        "- The final result order blends keyword, vector and reranker signals, so it isn't sorted by reranker score "
        "alone (see R06 below).\n",
        "## Misses and partial hits (default config)\n",
    ]
    misses = [
        r
        for r in default
        if r.category != "negative" and (1 not in r.relevant_ranks or not r.answer_ranks)
    ]
    if not misses:
        out.append(
            "None: every answerable question had a relevant, answer-bearing passage at rank 1."
        )
    for r in misses:
        out.append(f"### {r.qid}. {r.question}")
        out.append(
            f"First relevant rank: {min(r.relevant_ranks) if r.relevant_ranks else 'none in top 5'}; "
            f"answer-bearing rank: {min(r.answer_ranks) if r.answer_ranks else 'none in top 5'}.\n"
        )
        for p in r.passages[:3]:
            out.append(
                f"- #{p.rank} {p.citation} (reranker {p.scores.get('reranker_score', float('nan')):.2f})"
            )
        out.append("")
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON.write_text(
        json.dumps(
            {
                "summary": summary,
                "citation_integrity": {"checked": checked, "mismatched": bad},
                "selected_config": best,
                "per_question": {
                    name: [
                        {
                            "id": r.qid,
                            "relevant_ranks": r.relevant_ranks,
                            "answer_ranks": r.answer_ranks,
                            "latency_ms": round(r.latency_ms, 1),
                            "top_chunk": r.passages[0].chunk_id if r.passages else None,
                        }
                        for r in rs
                    ]
                    for name, rs in by_config.items()
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    by_config, summary = run()
    write_report(by_config, summary)
    for name, s in summary.items():
        print(
            f"{name:<18} "
            + " ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in s.items())
        )
    print(f"Wrote {REPORT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
