"""The late-delivery risk model's contract, shared by training and the app (no ML imports here)."""

from __future__ import annotations

MODEL_DB, MODEL_SCHEMA, MODEL_NAME = "SCC_DB", "ML", "LATE_DELIVERY_RISK"
MODEL_FQN = f"{MODEL_DB}.{MODEL_SCHEMA}.{MODEL_NAME}"
SERVING_VERSION = "V1"

CATEGORICAL = ["SHIPPING_MODE", "MARKET", "ORDER_REGION", "CUSTOMER_SEGMENT", "PAYMENT_TYPE"]
INTEGER = ["ORDER_DOW", "ORDER_HOUR", "ORDER_MONTH", "LINE_COUNT", "UNITS"]
FLOAT = ["NET_SALES"]
# Order matters: SQL inference passes the features positionally in this order.
FEATURES = CATEGORICAL + INTEGER + FLOAT

SEGMENTS = ["Consumer", "Corporate", "Home Office"]
PAYMENT_TYPES = ["CASH", "DEBIT", "PAYMENT", "TRANSFER"]
# PREDICT_PROBA returns an OBJECT; this key holds P(late). Confirmed live on 2026-11-27.
POSITIVE_KEY = "output_feature_1"


def predict_sql(version: str = SERVING_VERSION) -> str:
    """One-row what-if inference with bound values (one %s per feature)."""
    placeholders = ", ".join(["%s"] * len(FEATURES))
    return f"SELECT MODEL({MODEL_FQN}, {version})!PREDICT_PROBA({placeholders}) AS P"
