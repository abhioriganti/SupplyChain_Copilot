"""Dashboard data, read as the runtime user (SCC_APP_SVC / SCC_APP_ROLE).

Every delivery number comes from the governed semantic view, the same definitions the agent uses.
The runtime role cannot read raw Gold tables, so the dashboard can't drift from the semantic layer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass

import pandas as pd

from supplychain_copilot.semantic import SEMANTIC_VIEW
from supplychain_copilot.snowflake.connection import app_session, query

SV = SEMANTIC_VIEW


@dataclass(frozen=True)
class Kpis:
    total_orders: int
    eligible_shipments: int
    late_shipments: int
    late_delivery_rate: float
    on_time_delivery_rate: float
    avg_shipping_days: float
    documents: int
    chunks: int


class DashboardData:
    """Read-only queries for the KPI tiles, charts and sources panel."""

    def __init__(self, session_factory: Callable[[], AbstractContextManager] = app_session):
        self._session = session_factory

    def _df(self, sql: str, params: tuple | None = None) -> pd.DataFrame:
        with self._session() as conn:
            return pd.DataFrame(query(conn, sql, params))

    def kpis(self) -> Kpis:
        with self._session() as conn:
            m = query(
                conn,
                f"SELECT * FROM SEMANTIC_VIEW({SV} METRICS orders.total_orders, orders.eligible_shipments, "
                "orders.late_shipments, orders.late_delivery_rate, orders.on_time_delivery_rate, "
                "orders.avg_actual_shipping_days)",
            )[0]
            d = query(
                conn,
                "SELECT COUNT(*) AS DOCS, COALESCE(SUM(CHUNK_COUNT), 0) AS CHUNKS FROM SCC_DB.DOCS.DOCUMENTS",
            )[0]
        return Kpis(
            total_orders=int(m["TOTAL_ORDERS"]),
            eligible_shipments=int(m["ELIGIBLE_SHIPMENTS"]),
            late_shipments=int(m["LATE_SHIPMENTS"]),
            late_delivery_rate=float(m["LATE_DELIVERY_RATE"]),
            on_time_delivery_rate=float(m["ON_TIME_DELIVERY_RATE"]),
            avg_shipping_days=float(m["AVG_ACTUAL_SHIPPING_DAYS"]),
            documents=int(d["DOCS"]),
            chunks=int(d["CHUNKS"]),
        )

    def late_by_region(self) -> pd.DataFrame:
        return self._df(
            f"SELECT * FROM SEMANTIC_VIEW({SV} DIMENSIONS regions.market, regions.order_region "
            "METRICS orders.late_delivery_rate, orders.eligible_shipments, orders.late_shipments) "
            "ORDER BY late_delivery_rate DESC"
        )

    def by_shipping_mode(self) -> pd.DataFrame:
        return self._df(
            f"SELECT * FROM SEMANTIC_VIEW({SV} DIMENSIONS orders.shipping_mode, orders.scheduled_shipping_days "
            "METRICS orders.on_time_delivery_rate, orders.late_delivery_rate, orders.avg_actual_shipping_days, "
            "orders.eligible_shipments) ORDER BY scheduled_shipping_days"
        )

    def monthly_by_market(self) -> pd.DataFrame:
        df = self._df(
            f"SELECT * FROM SEMANTIC_VIEW({SV} DIMENSIONS orders.order_month, regions.market "
            "METRICS orders.late_delivery_rate, orders.eligible_shipments) ORDER BY order_month, market"
        )
        if not df.empty:
            df["ORDER_MONTH"] = pd.to_datetime(df["ORDER_MONTH"])
        return df

    def late_risk(self, inputs: dict) -> float:
        """P(late) from the registered model (ADR-032), called as the runtime role. Values are
        bound parameters; the role has USAGE on the model only, not on its training data."""
        import json

        from supplychain_copilot.ml.spec import FEATURES, POSITIVE_KEY, predict_sql

        values = tuple(inputs[f] for f in FEATURES)
        with self._session() as conn:
            raw = query(conn, predict_sql(), values)[0]["P"]
        obj = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return float(obj[POSITIVE_KEY])

    def documents(self) -> pd.DataFrame:
        return self._df(
            "SELECT DOCUMENT_ID, DOCUMENT_TITLE, DOCUMENT_TYPE, DOCUMENT_VERSION, PUBLICATION_DATE, SOURCE_URL, "
            "PAGES_INCLUDED, PAGE_COUNT, CHUNK_COUNT FROM SCC_DB.DOCS.DOCUMENTS ORDER BY DOCUMENT_TITLE"
        )

    def chunk_metadata(self, chunk_ids: list[str]) -> pd.DataFrame:
        ids = list(dict.fromkeys(c for c in chunk_ids if c))[:50]
        if not ids:
            return pd.DataFrame()
        placeholders = ", ".join(["%s"] * len(ids))
        return self._df(
            "SELECT CHUNK_ID, DOCUMENT_ID, DOCUMENT_TITLE, SECTION_TITLE, PAGE_NUMBER, PAGE_END, PRINTED_PAGE_START, "
            f"SOURCE_URL, DOCUMENT_VERSION FROM SCC_DB.DOCS.DOCUMENT_CHUNKS WHERE CHUNK_ID IN ({placeholders})",
            tuple(ids),
        )


def iter_rows(df: pd.DataFrame) -> Iterator[dict]:
    yield from df.to_dict(orient="records")
