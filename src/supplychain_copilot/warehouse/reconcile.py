"""Independent reconciliation: recompute every Gold KPI in pandas from the Phase 1 Parquet (no
Snowflake logic reused) and compare with the Snowflake KPI views. Writes docs/reconciliation_report.md.

Also computes the two classic *wrong* answers (line-grain late rate; order revenue re-summed after a
join to lines) to show what the grain rules prevent.

Usage:
    python -m supplychain_copilot.warehouse.reconcile
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.ingestion.clean_orders import OUTPUT_PARQUET
from supplychain_copilot.snowflake.connection import query, session

REPORT_PATH = PROJECT_ROOT / "docs" / "reconciliation_report.md"
REL_TOL, ABS_TOL = 1e-9, 1e-6
CANCELED = "Shipping canceled"
LATE = "Late delivery"
FRAUD_OR_CANCELED = {"CANCELED", "SUSPECTED_FRAUD"}


@dataclass
class Comparison:
    scope: str
    metric: str
    expected: float
    actual: float

    @property
    def ok(self) -> bool:
        if self.expected is None or self.actual is None:
            return self.expected is None and self.actual is None
        return math.isclose(
            float(self.expected), float(self.actual), rel_tol=REL_TOL, abs_tol=ABS_TOL
        )


# ----------------------------------------------------------------------------- pandas side


def order_frame(lines: pd.DataFrame) -> pd.DataFrame:
    """One row per order, built independently: order attributes from the first line, sums of lines."""
    first = lines.sort_values("order_item_id").drop_duplicates("order_id")
    sums = lines.groupby("order_id").agg(
        net_sales=("net_sales", "sum"), line_count=("order_item_id", "size")
    )
    o = first.drop(columns=["net_sales"]).merge(sums, on="order_id")
    o["eligible"] = o["delivery_status"] != CANCELED
    o["late"] = o["eligible"] & (o["delivery_status"] == LATE)
    o["on_time"] = o["eligible"] & ~o["late"]
    o["delay"] = o["days_shipping_actual"].astype(float) - o["days_shipping_scheduled"].astype(
        float
    )
    o["revenue_eligible"] = ~o["order_status"].isin(FRAUD_OR_CANCELED)
    o["order_month"] = o["order_ts"].dt.to_period("M").dt.to_timestamp().dt.date
    return o


def kpis(o: pd.DataFrame) -> dict[str, float]:
    elig = o[o["eligible"]]
    return {
        "DISTINCT_ORDERS": len(o),
        "ELIGIBLE_SHIPMENTS": int(o["eligible"].sum()),
        "LATE_SHIPMENTS": int(o["late"].sum()),
        "LATE_DELIVERY_RATE": o["late"].sum() / len(elig) if len(elig) else None,
        "ON_TIME_DELIVERY_RATE": o["on_time"].sum() / len(elig) if len(elig) else None,
        "AVG_ACTUAL_SHIPPING_DAYS": elig["days_shipping_actual"].astype(float).mean()
        if len(elig)
        else None,
        "AVG_DAYS_LATE": o.loc[o["late"], "delay"].mean() if o["late"].any() else None,
        "TOTAL_REVENUE": o.loc[o["revenue_eligible"], "net_sales"].sum(),
    }


# ----------------------------------------------------------------------------- compare


def _compare_grouped(
    scope: str, o: pd.DataFrame, key: str, sf_rows: list[dict], sf_key: str
) -> list[Comparison]:
    out: list[Comparison] = []
    sf = {r[sf_key]: r for r in sf_rows}
    groups = dict(tuple(o.groupby(key)))
    if set(map(str, sf)) != set(map(str, groups)):
        out.append(Comparison(scope, "group keys match", 1, 0))
    for k, g in groups.items():
        row = sf.get(k)
        for m, v in kpis(g).items():
            out.append(Comparison(f"{scope}={k}", m, v, None if row is None else row[m]))
    return out


def reconcile() -> tuple[list[Comparison], dict]:
    lines = pd.read_parquet(OUTPUT_PARQUET)
    o = order_frame(lines)
    with session() as conn:
        overall = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_OVERALL")[0]
        by_region = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_REGION")
        by_mode = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_SHIPPING_MODE")
        by_month = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_MONTH")
        naive_join_rev = query(
            conn,
            "SELECT SUM(IFF(o.IS_REVENUE_ELIGIBLE, o.NET_SALES, 0)) AS R FROM SCC_DB.GOLD.FACT_ORDERS o "
            "JOIN SCC_DB.GOLD.FACT_ORDER_LINES l ON o.ORDER_ID = l.ORDER_ID",
        )[0]["R"]

    comps = [Comparison("overall", m, v, overall[m]) for m, v in kpis(o).items()]
    comps.append(Comparison("overall", "ORDER_LINES", len(lines), overall["ORDER_LINES"]))
    comps += _compare_grouped("region", o, "order_region", by_region, "ORDER_REGION")
    comps += _compare_grouped("shipping_mode", o, "shipping_mode", by_mode, "SHIPPING_MODE")
    comps += _compare_grouped("month", o, "order_month", by_month, "ORDER_MONTH")

    # What the grain rules prevent (computed, not asserted equal).
    not_canceled_lines = lines[lines["delivery_status"] != CANCELED]
    pitfalls = {
        "late_rate_correct_order_grain": kpis(o)["LATE_DELIVERY_RATE"],
        "late_rate_wrong_line_grain": (not_canceled_lines["delivery_status"] == LATE).mean(),
        "late_rate_wrong_including_canceled": o["late"].sum() / len(o),
        "revenue_correct": kpis(o)["TOTAL_REVENUE"],
        "revenue_wrong_order_totals_after_join_to_lines": float(naive_join_rev),
        "revenue_wrong_including_canceled_and_fraud": o["net_sales"].sum(),
        "orders_correct": len(o),
        "orders_wrong_count_of_rows": len(lines),
    }
    return comps, pitfalls


def write_report(comps: list[Comparison], pitfalls: dict) -> None:
    failed = [c for c in comps if not c.ok]
    scopes = pd.Series([c.scope.split("=")[0] for c in comps]).value_counts().to_dict()
    lines = [
        "# Phase 2 reconciliation report\n",
        f"_Generated by `python -m supplychain_copilot.warehouse.reconcile` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC._\n",
        "The **expected** values are recomputed in pandas from `data/processed/dataco_order_lines.parquet` "
        "(Phase 1 output), using only the written definitions in `docs/metric_definitions.md`. No "
        "Snowflake SQL is reused. The **actual** values come from the Snowflake `GOLD.V_KPI_*` views. "
        f"Counts must match exactly; other values must match within rel {REL_TOL} / abs {ABS_TOL}.\n",
        f"**Result: {len(comps) - len(failed)} of {len(comps)} comparisons match** "
        f"(by scope: {scopes}).\n",
    ]
    if failed:
        lines.append("## Mismatches\n\n| Scope | Metric | Expected | Actual |\n|---|---|---|---|")
        lines += [f"| {c.scope} | {c.metric} | {c.expected} | {c.actual} |" for c in failed]
    lines.append(
        "\n## Headline KPIs (overall)\n\n| Metric | Expected (pandas) | Actual (Snowflake) | Match |\n|---|---|---|---|"
    )
    for c in comps:
        if c.scope == "overall":
            lines.append(f"| {c.metric} | {c.expected} | {c.actual} | {'✅' if c.ok else '❌'} |")
    p = pitfalls
    lines += [
        "\n## What the grain and exclusion rules prevent\n",
        "Computed on the same data to show the size of the errors the governed definitions avoid:\n",
        "| Question | Correct (governed) | Common wrong answer | Why it's wrong |",
        "|---|---|---|---|",
        f"| Late-delivery rate | {p['late_rate_correct_order_grain']:.4%} | {p['late_rate_wrong_line_grain']:.4%} (rows = lines) | Multi-line orders weighted by line count |",
        f"| Late-delivery rate | {p['late_rate_correct_order_grain']:.4%} | {p['late_rate_wrong_including_canceled']:.4%} (canceled in denominator) | Canceled shipments were never delivered |",
        f"| Total revenue | {p['revenue_correct']:,.2f} | {p['revenue_wrong_order_totals_after_join_to_lines']:,.2f} (order totals summed after joining to lines) | Fan-out: each order total repeated once per line |",
        f"| Total revenue | {p['revenue_correct']:,.2f} | {p['revenue_wrong_including_canceled_and_fraud']:,.2f} (all statuses) | Includes canceled and suspected-fraud orders |",
        f"| Number of orders | {p['orders_correct']:,} | {p['orders_wrong_count_of_rows']:,} (row count) | Counts order lines |",
        "",
        f"Honest sizing: in this dataset the line-grain late-rate error is small "
        f"({abs(p['late_rate_correct_order_grain'] - p['late_rate_wrong_line_grain']) * 100:.2f} "
        "percentage points), because lateness doesn't correlate with order size here. On data where "
        "it does, the error can be large, and the grain rule costs nothing. The denominator error "
        f"({abs(p['late_rate_correct_order_grain'] - p['late_rate_wrong_including_canceled']) * 100:.2f} pp) "
        f"and the fan-out error "
        f"({p['revenue_wrong_order_totals_after_join_to_lines'] / p['revenue_correct']:.2f}× revenue) are material.\n",
        "Delivery status describes *whether* a shipment was late, not *why*. None of these figures "
        "supports a causal explanation for delays (e.g. supplier fault).",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    comps, pitfalls = reconcile()
    write_report(comps, pitfalls)
    failed = [c for c in comps if not c.ok]
    print(f"{len(comps) - len(failed)}/{len(comps)} comparisons match")
    for c in failed[:20]:
        print(f"  MISMATCH {c.scope} {c.metric}: expected={c.expected} actual={c.actual}")
    for k, v in pitfalls.items():
        print(f"  {k:<50} {v}")
    print(f"Wrote {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
