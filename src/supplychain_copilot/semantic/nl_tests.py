"""Natural-language tests: Cortex Analyst (via the semantic view) vs validated ground truth.

For each question: call Cortex Analyst, execute the SQL it generates (read-only role), and check
the answer against ground truth from the reconciled GOLD.V_KPI_* views / FACT_ORDERS. Writes
docs/semantic_test_report.md. INCURS SMALL CORTEX COST (one Analyst message per question).

Usage:
    python -m supplychain_copilot.semantic.nl_tests --yes
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from supplychain_copilot.config import PROJECT_ROOT, load_settings
from supplychain_copilot.semantic.analyst import AnalystResponse, ask
from supplychain_copilot.snowflake.connection import query, session
from supplychain_copilot.snowflake.rest import SnowflakeRestClient

REPORT_PATH = PROJECT_ROOT / "docs" / "semantic_test_report.md"
REL_TOL = 1e-6


# ----------------------------------------------------------------------------- matching helpers


def _num(v: Any) -> float | None:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _close(a: float | None, b: float | None, scale: float = 1.0) -> bool:
    return (
        a is not None
        and b is not None
        and math.isclose(a, b * scale, rel_tol=REL_TOL, abs_tol=1e-6)
    )


def scalar_present(rows: list[dict], expected: float) -> tuple[bool, str]:
    """Some cell in the result equals the expected scalar."""
    for r in rows:
        for k, v in r.items():
            if _close(_num(v), expected):
                return True, f"found {k}={v}"
    return False, f"expected {expected} not found in {rows[:3]}"


def keyed_values_match(
    rows: list[dict], truth: dict[Any, float], top_key: Any | None = None, allow_pct: bool = True
) -> tuple[bool, str]:
    """Find a key column whose values are truth keys and a numeric column matching truth per key."""
    if not rows:
        return False, "no rows returned"
    cols = list(rows[0])
    norm = {str(k): v for k, v in truth.items()}
    key_col = next((c for c in cols if all(str(r[c]) in norm for r in rows)), None)
    if key_col is None:
        return False, f"no column with keys from ground truth among {cols}"
    for c in cols:
        if c == key_col:
            continue
        for scale in (1.0, 100.0) if allow_pct else (1.0,):
            if all(_close(_num(r[c]), norm[str(r[key_col])], scale) for r in rows):
                if top_key is not None and str(rows[0][key_col]) != str(top_key):
                    return (
                        False,
                        f"values match but first row is {rows[0][key_col]!r}, expected {top_key!r}",
                    )
                pct = " (returned as percent)" if scale == 100.0 else ""
                return True, f"{len(rows)} rows: {key_col} -> {c} match ground truth{pct}"
    return False, f"no numeric column matched ground truth for key {key_col}"


# ----------------------------------------------------------------------------- test cases


@dataclass
class Case:
    id: str
    question: str
    check: Callable[[list[dict], dict], tuple[bool, str]] | None
    expect_sql: bool = True
    note: str = ""


@dataclass
class Result:
    case: Case
    response: AnalystResponse | None
    rows: list[dict] = field(default_factory=list)
    passed: bool = False
    detail: str = ""


def ground_truth(conn) -> dict:
    t: dict[str, Any] = {}
    t["overall"] = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_OVERALL")[0]
    regions = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_REGION")
    t["region_late"] = {r["ORDER_REGION"]: r["LATE_DELIVERY_RATE"] for r in regions}
    t["region_late_top"] = max(regions, key=lambda r: r["LATE_DELIVERY_RATE"])["ORDER_REGION"]
    modes = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_SHIPPING_MODE")
    t["mode_avg_days"] = {r["SHIPPING_MODE"]: r["AVG_ACTUAL_SHIPPING_DAYS"] for r in modes}
    t["mode_on_time"] = {r["SHIPPING_MODE"]: r["ON_TIME_DELIVERY_RATE"] for r in modes}
    t["mode_on_time_top"] = max(modes, key=lambda r: r["ON_TIME_DELIVERY_RATE"])["SHIPPING_MODE"]
    months = query(conn, "SELECT * FROM SCC_DB.GOLD.V_KPI_BY_MONTH")
    t["month_late"] = {str(r["ORDER_MONTH"]): r["LATE_DELIVERY_RATE"] for r in months}
    mm = query(
        conn,
        "SELECT ORDER_MONTH, MARKET, COUNT_IF(IS_LATE)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE),0) AS R "
        "FROM SCC_DB.GOLD.FACT_ORDERS GROUP BY 1, 2",
    )
    t["month_market_late"] = {(str(r["ORDER_MONTH"]), r["MARKET"]): r["R"] for r in mm}
    t["western_europe_late"] = t["region_late"]["Western Europe"]
    return t


def check_monthly(rows: list[dict], t: dict) -> tuple[bool, str]:
    if not rows:
        return False, "no rows"
    cols = list(rows[0])
    month_col = next(
        (c for c in cols if all(str(r[c])[:10] in t["month_late"] for r in rows)), None
    )
    if month_col is None:
        return False, f"no month column in {cols}"
    market_col = next((c for c in cols if "MARKET" in c.upper()), None)
    for c in cols:
        if c in (month_col, market_col):
            continue
        for scale in (1.0, 100.0):
            if market_col:
                ok = all(
                    _close(
                        _num(r[c]),
                        t["month_market_late"].get((str(r[month_col])[:10], r[market_col])),
                        scale,
                    )
                    for r in rows
                )
            else:
                ok = all(
                    _close(_num(r[c]), t["month_late"][str(r[month_col])[:10]], scale) for r in rows
                )
            if ok:
                grouping = "month x market" if market_col else "month"
                return True, f"{len(rows)} rows grouped by {grouping}; {c} matches ground truth"
    return (
        False,
        f"no column matched monthly ground truth (month col {month_col}, market col {market_col})",
    )


CASES: list[Case] = [
    Case(
        "Q1",
        "How many unique orders are there?",
        lambda rows, t: scalar_present(rows, t["overall"]["DISTINCT_ORDERS"]),
    ),
    Case(
        "Q2",
        "Which regions have the highest late-delivery rate?",
        lambda rows, t: keyed_values_match(rows, t["region_late"], top_key=t["region_late_top"]),
    ),
    Case(
        "Q3",
        "What is the average shipping duration by shipping mode?",
        lambda rows, t: keyed_values_match(rows, t["mode_avg_days"], allow_pct=False),
    ),
    Case(
        "Q4",
        "Show monthly late-delivery trends.",
        check_monthly,
        note="Instructions ask Analyst to include market when grouping by month (market rotation).",
    ),
    Case(
        "Q5",
        "Which shipping mode has the best on-time performance?",
        lambda rows, t: keyed_values_match(rows, t["mode_on_time"], top_key=t["mode_on_time_top"]),
    ),
    Case(
        "Q6",
        "How many eligible shipments were late?",
        lambda rows, t: scalar_present(rows, t["overall"]["LATE_SHIPMENTS"]),
    ),
    Case(
        "Q7",
        "What is the total revenue?",
        lambda rows, t: scalar_present(rows, t["overall"]["TOTAL_REVENUE"]),
    ),
    Case(
        "Q8",
        "What is the late delivery rate for Western Europe?",
        lambda rows, t: (
            scalar_present(rows, t["western_europe_late"])
            if scalar_present(rows, t["western_europe_late"])[0]
            else scalar_present(rows, t["western_europe_late"] * 100)
        ),
    ),
    Case(
        "Q9",
        "Which supplier caused the most late deliveries?",
        None,
        expect_sql=False,
        note="Negative test: no supplier data exists; Analyst should not produce SQL.",
    ),
]


def run(cases: list[Case] = CASES) -> list[Result]:
    settings = load_settings()
    client = SnowflakeRestClient(settings)
    results: list[Result] = []
    with session(settings) as conn:
        truth = ground_truth(conn)
        for case in cases:
            res = Result(case, None)
            try:
                res.response = ask(case.question, client=client)
                if case.expect_sql:
                    if not res.response.sql:
                        res.detail = f"no SQL returned; text: {res.response.text[:200]}"
                    else:
                        res.rows = query(conn, res.response.sql)
                        res.passed, res.detail = case.check(res.rows, truth)
                else:
                    res.passed = res.response.sql is None
                    res.detail = (
                        "no SQL generated (correct)"
                        if res.passed
                        else "SQL was generated for an unanswerable question"
                    )
            except Exception as exc:  # noqa: BLE001 - record and continue
                res.detail = f"{type(exc).__name__}: {str(exc)[:300]}"
            results.append(res)
            print(
                f"[{'PASS' if res.passed else 'FAIL'}] {case.id} {case.question}  ->  {res.detail}"
            )
    return results


def _fmt(v: Any) -> str:
    f = _num(v)
    return f"{f:.6g}" if f is not None and not float(f).is_integer() else str(v)


def write_report(results: list[Result]) -> None:
    passed = sum(r.passed for r in results)
    out = [
        "# Phase 3: Cortex Analyst natural-language test report\n",
        f"_Generated by `python -m supplychain_copilot.semantic.nl_tests --yes` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC "
        "against `SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV`._\n",
        "Each question goes to Cortex Analyst (REST, `semantic_view`). The SQL it generates is executed, and the result "
        "is compared with ground truth from the reconciled `GOLD.V_KPI_*` views and `FACT_ORDERS` (Phase 2: 521 of 521 "
        "values reconciled independently). Rates may come back as fractions or percentages; both are accepted, and "
        "the report notes which.\n",
        f"**Result: {passed} of {len(results)} passed.**\n",
        "| # | Question | Verdict | Detail |",
        "|---|---|---|---|",
    ]
    for r in results:
        out.append(
            f"| {r.case.id} | {r.case.question} | {'✅' if r.passed else '❌'} | {r.detail.replace('|', '/')} |"
        )
    for r in results:
        out.append(f"\n## {r.case.id}. {r.case.question}\n")
        if r.case.note:
            out.append(f"_{r.case.note}_\n")
        if r.response is None:
            out.append(f"Error: {r.detail}\n")
            continue
        if r.response.text:
            out.append("**Analyst text:** " + r.response.text.replace("\n", " ")[:600] + "\n")
        if r.response.sql:
            out.append("**Generated SQL:**\n\n```sql\n" + r.response.sql.strip() + "\n```\n")
        if r.rows:
            cols = list(r.rows[0])
            out.append("**Result (first 8 rows):**\n")
            out.append("| " + " | ".join(cols) + " |")
            out.append("|" + "---|" * len(cols))
            for row in r.rows[:8]:
                out.append("| " + " | ".join(_fmt(row[c]) for c in cols) + " |")
            if len(r.rows) > 8:
                out.append(f"\n_{len(r.rows)} rows total._")
        out.append(f"\n**Verdict:** {'PASS' if r.passed else 'FAIL'}: {r.detail}  ")
        out.append(
            f"request_id `{r.response.request_id}` · verified query used: `{r.response.verified_query_used}`"
        )
    REPORT_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="confirm small Cortex Analyst cost")
    args = parser.parse_args()
    if not args.yes:
        print("Calls Cortex Analyst once per question (small cost). Re-run with --yes.")
        return 2
    results = run()
    write_report(results)
    print(
        f"\n{sum(r.passed for r in results)}/{len(results)} passed. Wrote {REPORT_PATH.relative_to(PROJECT_ROOT)}"
    )
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
