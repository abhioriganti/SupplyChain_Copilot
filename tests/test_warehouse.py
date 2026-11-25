"""Phase 2 tests.

Unit tests (CI-safe) check the reconciliation logic on a tiny fixture. Live tests (marker
`snowflake`, opt-in via SCC_RUN_SNOWFLAKE_TESTS=1) run the SQL data-quality suite and the full
independent reconciliation against the real Snowflake model.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from supplychain_copilot.warehouse.load_bronze import prepare_frame
from supplychain_copilot.warehouse.reconcile import kpis, order_frame

ROOT = Path(__file__).resolve().parents[1]
live = pytest.mark.skipif(
    os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1", reason="set SCC_RUN_SNOWFLAKE_TESTS=1"
)


def _lines() -> pd.DataFrame:
    """3 orders, 6 lines: order 1 late (3 lines), order 2 on time (2 lines), order 3 canceled (1 line)."""
    rows = [
        # order_item_id, order_id, status, delivery_status, actual, scheduled, net_sales
        (1, 1, "COMPLETE", "Late delivery", 5, 2, 10.0),
        (2, 1, "COMPLETE", "Late delivery", 5, 2, 20.0),
        (3, 1, "COMPLETE", "Late delivery", 5, 2, 30.0),
        (4, 2, "CLOSED", "Shipping on time", 2, 2, 40.0),
        (5, 2, "CLOSED", "Shipping on time", 2, 2, 50.0),
        (6, 3, "CANCELED", "Shipping canceled", 6, 2, 60.0),
    ]
    df = pd.DataFrame(
        rows,
        columns=[
            "order_item_id",
            "order_id",
            "order_status",
            "delivery_status",
            "days_shipping_actual",
            "days_shipping_scheduled",
            "net_sales",
        ],
    )
    df["order_ts"] = pd.Timestamp("2016-05-01")
    return df


def test_kpis_use_order_grain_and_exclude_canceled():
    k = kpis(order_frame(_lines()))
    assert k["DISTINCT_ORDERS"] == 3  # not 6 lines
    assert k["ELIGIBLE_SHIPMENTS"] == 2  # canceled excluded
    assert k["LATE_SHIPMENTS"] == 1
    assert k["LATE_DELIVERY_RATE"] == pytest.approx(0.5)  # line grain would give 3/5
    assert k["ON_TIME_DELIVERY_RATE"] == pytest.approx(0.5)
    # only late shipments count; the canceled order's 4-day delay is ignored
    assert k["AVG_DAYS_LATE"] == pytest.approx(3.0)
    assert k["AVG_ACTUAL_SHIPPING_DAYS"] == pytest.approx(3.5)  # (5 + 2) / 2 eligible
    assert k["TOTAL_REVENUE"] == pytest.approx(150.0)  # 60 from canceled order excluded


def test_order_revenue_is_sum_of_lines_not_repeated():
    o = order_frame(_lines())
    assert o.set_index("order_id").loc[1, "net_sales"] == pytest.approx(60.0)
    assert o["net_sales"].sum() == pytest.approx(_lines()["net_sales"].sum())


def test_prepare_frame_adds_lineage_and_uppercases():
    df = pd.DataFrame({"order_item_id": [1], "net_sales": [1.0]})
    out = prepare_frame(df, str(uuid.uuid4()), datetime.now(UTC))
    assert list(out.columns) == ["ORDER_ITEM_ID", "NET_SALES", "LOAD_ID", "INGESTED_AT_UTC"]
    assert out["INGESTED_AT_UTC"].dt.tz is None


@pytest.mark.snowflake
@live
def test_sql_data_quality_suite_passes():
    from supplychain_copilot.warehouse.sql_tests import run_test_file

    results = run_test_file(
        ROOT / "sql/tests/test_phase2_model.sql", run_id=f"pytest-{uuid.uuid4()}"
    )
    failed = {r["TEST_NAME"]: r["FAILURES"] for r in results if r["FAILURES"] != 0}
    assert len(results) >= 30
    assert failed == {}


@pytest.mark.snowflake
@live
def test_independent_reconciliation_matches_snowflake():
    from supplychain_copilot.warehouse.reconcile import reconcile

    comps, pitfalls = reconcile()
    mismatches = [(c.scope, c.metric, c.expected, c.actual) for c in comps if not c.ok]
    assert mismatches == []
    assert pitfalls["orders_correct"] < pitfalls["orders_wrong_count_of_rows"]
    assert pitfalls["revenue_correct"] < pitfalls["revenue_wrong_order_totals_after_join_to_lines"]
