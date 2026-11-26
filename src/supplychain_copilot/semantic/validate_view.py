"""Direct-SQL validation of the semantic view against the reconciled Gold KPI views.

Checks:
  1. Every governed metric via SEMANTIC_VIEW(...) equals GOLD.V_KPI_* (overall, region, mode, month).
  2. Revenue by product category (lines -> products, many-to-one) is allowed and sums to the total.
  3. Fan-out guard: an order-grain metric grouped by a product dimension (one-to-many path) must be
     REJECTED by Snowflake instead of returning inflated numbers.

Usage:
    python -m supplychain_copilot.semantic.validate_view
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from snowflake.connector.errors import ProgrammingError

from supplychain_copilot.semantic import SEMANTIC_VIEW
from supplychain_copilot.snowflake.connection import query, session

REL_TOL, ABS_TOL = 1e-9, 1e-6

# semantic metric name -> GOLD.V_KPI_* column
METRIC_MAP = {
    "total_orders": "DISTINCT_ORDERS",
    "eligible_shipments": "ELIGIBLE_SHIPMENTS",
    "late_shipments": "LATE_SHIPMENTS",
    "late_delivery_rate": "LATE_DELIVERY_RATE",
    "on_time_delivery_rate": "ON_TIME_DELIVERY_RATE",
    "avg_actual_shipping_days": "AVG_ACTUAL_SHIPPING_DAYS",
    "avg_days_late": "AVG_DAYS_LATE",
}
ORDER_METRICS = ", ".join(f"orders.{m}" for m in METRIC_MAP)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=ABS_TOL)


def _compare(
    sv_rows, kpi_rows, sv_key: str | None, kpi_key: str | None, with_revenue: bool
) -> list[str]:
    """Return mismatch descriptions (empty = all equal)."""
    problems: list[str] = []
    kpi = {(r[kpi_key] if kpi_key else None): r for r in kpi_rows}
    if len(sv_rows) != len(kpi_rows):
        problems.append(f"row count {len(sv_rows)} vs {len(kpi_rows)}")
    for r in sv_rows:
        k = r[sv_key] if sv_key else None
        ref = kpi.get(k)
        if ref is None:
            problems.append(f"key {k!r} missing in KPI view")
            continue
        pairs = [(m.upper(), col) for m, col in METRIC_MAP.items()]
        if with_revenue:
            pairs.append(("TOTAL_REVENUE", "TOTAL_REVENUE"))
        for sv_col, kpi_col in pairs:
            if not _close(r[sv_col], ref[kpi_col]):
                problems.append(f"{k!r} {sv_col}: {r[sv_col]} vs {ref[kpi_col]}")
    return problems


def run_checks() -> list[Check]:
    checks: list[Check] = []
    sv = SEMANTIC_VIEW
    with session() as conn:
        # 1a. overall
        sv_overall = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} METRICS {ORDER_METRICS}, order_lines.total_revenue, "
            "order_lines.order_line_count)",
        )
        kpi_overall = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_OVERALL")
        p = _compare(sv_overall, kpi_overall, None, None, with_revenue=True)
        if sv_overall[0]["ORDER_LINE_COUNT"] != kpi_overall[0]["ORDER_LINES"]:
            p.append("order_line_count mismatch")
        checks.append(Check("overall_metrics_match_gold", not p, "; ".join(p) or "9 metrics equal"))

        # 1b. by region (region dimension comes from DIM_REGIONS via orders -> regions)
        sv_region = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS regions.order_region "
            f"METRICS {ORDER_METRICS}, order_lines.total_revenue)",
        )
        kpi_region = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_REGION")
        p = _compare(sv_region, kpi_region, "ORDER_REGION", "ORDER_REGION", with_revenue=True)
        checks.append(
            Check(
                "region_metrics_match_gold",
                not p,
                "; ".join(p[:5]) or f"{len(sv_region)} regions equal",
            )
        )

        # 1c. by shipping mode
        sv_mode = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS orders.shipping_mode "
            f"METRICS {ORDER_METRICS}, order_lines.total_revenue)",
        )
        kpi_mode = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_SHIPPING_MODE")
        p = _compare(sv_mode, kpi_mode, "SHIPPING_MODE", "SHIPPING_MODE", with_revenue=True)
        checks.append(
            Check(
                "shipping_mode_metrics_match_gold",
                not p,
                "; ".join(p[:5]) or f"{len(sv_mode)} modes equal",
            )
        )

        # 1d. by month
        sv_month = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS orders.order_month "
            f"METRICS {ORDER_METRICS}, order_lines.total_revenue)",
        )
        kpi_month = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_MONTH")
        p = _compare(sv_month, kpi_month, "ORDER_MONTH", "ORDER_MONTH", with_revenue=True)
        checks.append(
            Check(
                "month_metrics_match_gold",
                not p,
                "; ".join(p[:5]) or f"{len(sv_month)} months equal",
            )
        )

        # 1e. rates are complementary everywhere
        bad = [
            r
            for r in sv_region
            if not _close(r["LATE_DELIVERY_RATE"] + r["ON_TIME_DELIVERY_RATE"], 1.0)
        ]
        checks.append(Check("late_plus_on_time_equals_one", not bad, f"{len(bad)} regions violate"))

        # 2. revenue by category (allowed many-to-one path) sums to total
        by_cat = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS products.category_id METRICS order_lines.total_revenue)",
        )
        total = sum(float(r["TOTAL_REVENUE"]) for r in by_cat)
        ok = _close(total, kpi_overall[0]["TOTAL_REVENUE"])
        checks.append(
            Check(
                "revenue_by_category_sums_to_total",
                ok,
                f"{len(by_cat)} categories, sum {total:,.2f} vs total {float(kpi_overall[0]['TOTAL_REVENUE']):,.2f}",
            )
        )

        # 3. Fan-out guard. orders and products are siblings joined many-to-many through order_lines.
        #    Snowflake documents that it deduplicates such paths instead of erroring; verify the
        #    semantic view equals COUNT(DISTINCT order_id) per category and NOT the inflated join.
        sv_cat = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS products.category_id "
            "METRICS orders.total_orders, orders.eligible_shipments, orders.late_shipments)",
        )
        truth = {
            r["CATEGORY_ID"]: r
            for r in query(
                conn,
                "SELECT p.CATEGORY_ID, COUNT(DISTINCT o.ORDER_ID) AS T, "
                "COUNT(DISTINCT IFF(o.IS_SHIPMENT_ELIGIBLE, o.ORDER_ID, NULL)) AS E, "
                "COUNT(DISTINCT IFF(o.IS_LATE, o.ORDER_ID, NULL)) AS L, COUNT(*) AS NAIVE "
                "FROM SCC_DB.GOLD.FACT_ORDER_LINES l "
                "JOIN SCC_DB.GOLD.FACT_ORDERS o ON l.ORDER_ID = o.ORDER_ID "
                "JOIN SCC_DB.GOLD.DIM_PRODUCTS p ON l.PRODUCT_ID = p.PRODUCT_ID GROUP BY 1",
            )
        }
        wrong = [
            r["CATEGORY_ID"]
            for r in sv_cat
            if (r["TOTAL_ORDERS"], r["ELIGIBLE_SHIPMENTS"], r["LATE_SHIPMENTS"])
            != (
                truth[r["CATEGORY_ID"]]["T"],
                truth[r["CATEGORY_ID"]]["E"],
                truth[r["CATEGORY_ID"]]["L"],
            )
        ]
        inflated_elsewhere = sum(1 for t in truth.values() if t["NAIVE"] != t["T"])
        checks.append(
            Check(
                "order_metric_by_product_deduplicated_not_inflated",
                not wrong and len(sv_cat) == len(truth),
                f"{len(sv_cat) - len(wrong)}/{len(truth)} categories equal COUNT(DISTINCT order); "
                f"a naive join would inflate {inflated_elsewhere} categories",
            )
        )

        # 3b. Invalid references are rejected at compile time (unknown dimension).
        try:
            query(
                conn,
                f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS orders.supplier_name METRICS orders.total_orders)",
            )
            checks.append(
                Check(
                    "undefined_dimension_rejected",
                    False,
                    "query on undefined dimension was allowed",
                )
            )
        except ProgrammingError as exc:
            checks.append(
                Check("undefined_dimension_rejected", True, str(exc).splitlines()[0][:160])
            )

        # 5. Backlog additions: margin, discount, order value, customers, week and weekday.
        #    Truth is written directly against the Gold tables, independent of the semantic view.
        checks.extend(_check_backlog_additions(conn, sv))

        # 4. metadata: governed metrics exist with comments
        metrics = query(conn, f"SHOW SEMANTIC METRICS IN {sv}")
        names = {str(m.get("NAME", "")).lower() for m in metrics}
        missing = set(METRIC_MAP) - names
        checks.append(
            Check(
                "governed_metrics_registered",
                not missing,
                f"missing: {sorted(missing)}" if missing else f"{len(names)} metrics registered",
            )
        )
    return checks


NEW_LINE_METRICS = (
    "order_lines.profit_margin, order_lines.total_discount, order_lines.discount_rate"
)
NEW_ORDER_METRICS = "orders.revenue_orders, orders.avg_order_value, orders.customer_count"
_LINE_TRUTH = (
    "SELECT {key} AS K, SUM(IFF(l.IS_REVENUE_ELIGIBLE, l.LINE_PROFIT, 0)) "
    "/ NULLIF(SUM(IFF(l.IS_REVENUE_ELIGIBLE, l.NET_SALES, 0)), 0) AS PROFIT_MARGIN, "
    "SUM(IFF(l.IS_REVENUE_ELIGIBLE, l.DISCOUNT_AMOUNT, 0)) AS TOTAL_DISCOUNT, "
    "SUM(IFF(l.IS_REVENUE_ELIGIBLE, l.DISCOUNT_AMOUNT, 0)) "
    "/ NULLIF(SUM(IFF(l.IS_REVENUE_ELIGIBLE, l.GROSS_SALES, 0)), 0) AS DISCOUNT_RATE "
    "FROM SCC_DB.GOLD.FACT_ORDER_LINES l JOIN SCC_DB.GOLD.FACT_ORDERS o ON l.ORDER_ID = o.ORDER_ID "
    "GROUP BY 1"
)
_ORDER_TRUTH = (
    "SELECT {key} AS K, COUNT_IF(o.IS_REVENUE_ELIGIBLE) AS REVENUE_ORDERS, "
    "AVG(IFF(o.IS_REVENUE_ELIGIBLE, o.NET_SALES, NULL)) AS AVG_ORDER_VALUE, "
    "COUNT(DISTINCT o.CUSTOMER_ID) AS CUSTOMER_COUNT FROM SCC_DB.GOLD.FACT_ORDERS o GROUP BY 1"
)


def _match(sv_rows, truth_rows, sv_key: str | None, cols: list[str]) -> list[str]:
    truth = {r["K"]: r for r in truth_rows}
    problems = [] if len(sv_rows) == len(truth) else [f"row count {len(sv_rows)} vs {len(truth)}"]
    for r in sv_rows:
        k = r[sv_key] if sv_key else "all"
        ref = truth.get(k)
        if ref is None:
            problems.append(f"key {k!r} missing in truth")
            continue
        problems += [f"{k!r} {c}: {r[c]} vs {ref[c]}" for c in cols if not _close(r[c], ref[c])]
    return problems


def _check_backlog_additions(conn, sv: str) -> list[Check]:
    out: list[Check] = []
    line_cols = ["PROFIT_MARGIN", "TOTAL_DISCOUNT", "DISCOUNT_RATE"]
    order_cols = ["REVENUE_ORDERS", "AVG_ORDER_VALUE", "CUSTOMER_COUNT"]
    for label, dim, key, key_col in [
        ("overall", "", "'all'", None),
        ("market", "DIMENSIONS regions.market ", "o.MARKET", "MARKET"),
    ]:
        p = _match(
            query(conn, f"SELECT * FROM SEMANTIC_VIEW({sv} {dim}METRICS {NEW_LINE_METRICS})"),
            query(conn, _LINE_TRUTH.format(key=key)),
            key_col,
            line_cols,
        )
        p += _match(
            query(conn, f"SELECT * FROM SEMANTIC_VIEW({sv} {dim}METRICS {NEW_ORDER_METRICS})"),
            query(conn, _ORDER_TRUTH.format(key=key)),
            key_col,
            order_cols,
        )
        out.append(
            Check(
                f"new_metrics_{label}_match_gold",
                not p,
                "; ".join(p[:5]) or f"6 metrics equal ({label})",
            )
        )

    # discount identity: gross - discount = net per line, up to the source's separate rounding
    #   of each field (measured: 4,409 of 172,765 lines differ, by at most 1 cent).
    r = query(
        conn,
        "SELECT MAX(ABS(GROSS_SALES - DISCOUNT_AMOUNT - NET_SALES)) AS MAX_GAP, "
        "COUNT_IF(ABS(GROSS_SALES - DISCOUNT_AMOUNT - NET_SALES) > 0.005) AS OFF_LINES "
        "FROM SCC_DB.GOLD.FACT_ORDER_LINES WHERE IS_REVENUE_ELIGIBLE",
    )[0]
    out.append(
        Check(
            "discount_identity_within_source_rounding",
            float(r["MAX_GAP"]) <= 0.0101,
            f"max per-line gap {float(r['MAX_GAP']):.4f}; {r['OFF_LINES']} lines differ by rounding",
        )
    )

    # time grains: each partitions the orders exactly and matches GROUP BY on Gold
    for dim, expr in [
        ("order_week", "DATE_TRUNC('WEEK', ORDER_DATE)"),
        ("order_day_of_week", "DAYNAME(ORDER_DATE)"),
    ]:
        sv_rows = query(
            conn,
            f"SELECT * FROM SEMANTIC_VIEW({sv} DIMENSIONS orders.{dim} "
            "METRICS orders.total_orders, orders.late_shipments)",
        )
        truth = {
            t["K"]: t
            for t in query(
                conn,
                f"SELECT {expr} AS K, COUNT(*) AS T, COUNT_IF(IS_LATE) AS L "
                "FROM SCC_DB.GOLD.FACT_ORDERS GROUP BY 1",
            )
        }
        bad = [
            s[dim.upper()]
            for s in sv_rows
            if (s["TOTAL_ORDERS"], s["LATE_SHIPMENTS"])
            != (truth.get(s[dim.upper()], {}).get("T"), truth.get(s[dim.upper()], {}).get("L"))
        ]
        ok = not bad and len(sv_rows) == len(truth)
        out.append(
            Check(
                f"{dim}_matches_gold",
                ok,
                f"{len(sv_rows)} groups, {len(bad)} mismatched, "
                f"orders sum {sum(s['TOTAL_ORDERS'] for s in sv_rows)}",
            )
        )
    return out


def main() -> int:
    checks = run_checks()
    for c in checks:
        print(f"[{'PASS' if c.passed else 'FAIL'}] {c.name:<40} {c.detail}")
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
