"""Phase 3 tests.

Unit tests (CI-safe): answer-matching helpers used to grade Cortex Analyst output.
Live (SCC_RUN_SNOWFLAKE_TESTS=1): semantic view vs Gold, fan-out/dedup behaviour.
Live + paid (SCC_RUN_CORTEX_TESTS=1): Cortex Analyst natural-language questions vs ground truth.
"""

from __future__ import annotations

import os

import pytest

from supplychain_copilot.semantic.nl_tests import keyed_values_match, scalar_present

live = pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)
cortex = pytest.mark.skipif(
    os.getenv("SCC_RUN_CORTEX_TESTS") != "1", reason="set SCC_RUN_CORTEX_TESTS=1 (paid)"
)

TRUTH = {"Central Africa": 0.6004, "Western Europe": 0.5840, "Region C": 0.5258}  # fixture values


def test_scalar_present_finds_value():
    assert scalar_present([{"TOTAL_ORDERS": 65752}], 65752)[0]
    assert not scalar_present([{"TOTAL_ORDERS": 180519}], 65752)[0]


def test_keyed_match_accepts_fraction_and_percent():
    rows = [{"ORDER_REGION": k, "RATE": v} for k, v in TRUTH.items()]
    assert keyed_values_match(rows, TRUTH, top_key="Central Africa")[0]
    pct = [{"ORDER_REGION": k, "RATE": v * 100} for k, v in TRUTH.items()]
    ok, detail = keyed_values_match(pct, TRUTH)
    assert ok and "percent" in detail


def test_keyed_match_rejects_wrong_values_and_wrong_ranking():
    wrong = [{"ORDER_REGION": k, "RATE": v + 0.01} for k, v in TRUTH.items()]
    assert not keyed_values_match(wrong, TRUTH)[0]
    misordered = [{"ORDER_REGION": k, "RATE": v} for k, v in reversed(list(TRUTH.items()))]
    assert not keyed_values_match(misordered, TRUTH, top_key="Central Africa")[0]


def test_keyed_match_rejects_percent_when_not_allowed():
    rows = [{"MODE": "Standard Class", "AVG": 399.46}]
    assert not keyed_values_match(rows, {"Standard Class": 3.9946}, allow_pct=False)[0]


@pytest.mark.snowflake
@live
def test_semantic_view_matches_gold_and_prevents_inflation():
    from supplychain_copilot.semantic.validate_view import run_checks

    failed = [(c.name, c.detail) for c in run_checks() if not c.passed]
    assert failed == []


@pytest.mark.snowflake
@cortex
def test_cortex_analyst_answers_match_ground_truth():
    from supplychain_copilot.semantic.nl_tests import run

    failed = [(r.case.id, r.detail) for r in run() if not r.passed]
    assert failed == []
