"""Phase 5 retrieval tests.

Unit tests (CI-safe): eval-set integrity, relevance/evidence scoring, metric arithmetic, citations.
Live tests (SCC_RUN_SNOWFLAKE_TESTS=1): the Cortex Search service answers key questions with the right
passage and citation metadata. (The full evaluation runs via `python -m ...retrieval.evaluate`.)
"""

from __future__ import annotations

import os

import pytest

from supplychain_copilot.retrieval.evaluate import (
    QuestionResult,
    has_evidence,
    is_relevant,
    load_eval_set,
    score_question,
    summarize,
)
from supplychain_copilot.retrieval.search_client import Passage

DOCS = {"SQAM": "WOR-SQAM-2025-10-23", "SCOC": "WOR-SCOC-2025-06", "AR": "WOR-AR-FY2026"}


def _p(rank, doc, start, end, text="", section="S", printed=None):
    return Passage(
        rank, f"c{rank}", doc, "Title", section, start, end, printed, "https://x", "v1", text
    )


def test_eval_set_is_well_formed():
    ev = load_eval_set()
    ids = [q["id"] for q in ev["questions"]]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    for q in ev["questions"]:
        assert q["category"] in {"specific", "broad", "negative"}
        if q["category"] == "negative":
            assert q["relevant"] == []
        else:
            assert q["relevant"] and all(
                lab["doc"] in ev["documents"] and lab["pages"] for lab in q["relevant"]
            )
        if q["category"] == "specific":
            assert q["evidence"], q["id"]


def test_relevance_requires_document_and_page_overlap():
    labels = [{"doc": "SQAM", "pages": [29]}]
    assert is_relevant(_p(1, DOCS["SQAM"], 27, 29), labels, DOCS)
    assert not is_relevant(_p(1, DOCS["SQAM"], 30, 31), labels, DOCS)
    assert not is_relevant(_p(1, DOCS["SCOC"], 29, 29), labels, DOCS)


def test_evidence_match_is_case_insensitive():
    assert has_evidence(_p(1, "d", 1, 1, "Corrective ... 14 Working Days"), ["14 working days"])
    assert not has_evidence(_p(1, "d", 1, 1, "30 working days"), ["14 working days"])


def test_metrics_arithmetic():
    q = {
        "id": "R",
        "category": "specific",
        "question": "?",
        "relevant": [{"doc": "SQAM", "pages": [29]}],
        "evidence": ["14 working days"],
    }
    first = score_question(q, [_p(1, DOCS["SQAM"], 29, 29, "14 working days")], 100.0, DOCS)
    second = score_question(
        q, [_p(1, DOCS["SCOC"], 3, 3), _p(2, DOCS["SQAM"], 29, 29, "no")], 300.0, DOCS
    )
    neg = QuestionResult("N", "negative", "?", [], 200.0)
    s = summarize([first, second, neg])
    assert s["questions"] == 2
    assert s["hit@1"] == 0.5 and s["hit@3"] == 1.0
    assert s["answer@5"] == 0.5  # second question's relevant passage lacks the evidence phrase
    assert s["mrr@5"] == pytest.approx((1 + 0.5) / 2)
    assert s["doc@1"] == 0.5
    assert s["latency_p50_ms"] == 200.0  # negatives count toward latency


def test_citation_format_includes_printed_page_only_when_different():
    assert _p(1, "d", 28, 28, printed="8").citation.endswith("PDF p. 28 (printed p. 8)")
    assert _p(1, "d", 29, 29, printed="29").citation.endswith("PDF p. 29")
    assert _p(1, "d", 27, 29).citation.endswith("PDF p. 27-29")


live = pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)


@pytest.mark.snowflake
@live
@pytest.mark.parametrize(
    ("question", "doc", "page", "phrase"),
    [
        (
            "What are the supplier corrective-action deadlines?",
            "WOR-SQAM-2025-10-23",
            29,
            "14 working days",
        ),
        (
            "Does the supplier code of conduct prohibit child labor?",
            "WOR-SCOC-2025-06",
            5,
            "child labor",
        ),
        (
            "How could steel price volatility and tariffs affect the company?",
            "WOR-AR-FY2026",
            28,
            "steel prices",
        ),
    ],
)
def test_search_returns_correct_top_passage(question, doc, page, phrase):
    from supplychain_copilot.retrieval.search_client import DocumentSearch

    res = DocumentSearch().search(question, limit=3)
    top = res.passages[0]
    assert top.document_id == doc and top.page_number <= page <= top.page_end
    assert phrase.lower() in top.text.lower()
    assert (
        top.source_url.startswith("https://")
        and top.document_version
        and "reranker_score" in top.scores
    )


@pytest.mark.snowflake
@live
def test_document_filter_restricts_results():
    from supplychain_copilot.retrieval.search_client import DocumentSearch

    res = DocumentSearch().search(
        "supplier responsibilities", limit=5, document_ids=["WOR-SCOC-2025-06"]
    )
    assert res.passages and {p.document_id for p in res.passages} == {"WOR-SCOC-2025-06"}
