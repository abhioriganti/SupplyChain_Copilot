"""Dashboard card: what-if late-delivery risk from the registered model (ADR-032)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from supplychain_copilot.ml.spec import MODEL_FQN, PAYMENT_TYPES, SEGMENTS, SERVING_VERSION

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def mode_average(modes: pd.DataFrame, mode: str) -> float | None:
    row = modes[modes["SHIPPING_MODE"] == mode]
    return None if row.empty else float(row["LATE_DELIVERY_RATE"].iloc[0])


def location_options(regions: pd.DataFrame) -> list[tuple[str, str]]:
    pairs = regions[["MARKET", "ORDER_REGION"]].drop_duplicates()
    return sorted(pairs.itertuples(index=False, name=None))


def build_inputs(mode, market, region, segment, payment, weekday, hour, month, lines, units, value):
    return {
        "SHIPPING_MODE": mode,
        "MARKET": market,
        "ORDER_REGION": region,
        "CUSTOMER_SEGMENT": segment,
        "PAYMENT_TYPE": payment,
        "ORDER_DOW": WEEKDAYS.index(weekday) + 1,  # ISO weekday, as in the feature view
        "ORDER_HOUR": int(hour),
        "ORDER_MONTH": MONTHS.index(month) + 1,
        "LINE_COUNT": int(lines),
        "UNITS": int(units),
        "NET_SALES": float(value),
    }


def risk_card(data, regions: pd.DataFrame, modes: pd.DataFrame) -> None:
    st.markdown("#### 🔮 Late-delivery risk (predictive model)")
    st.caption(
        f"What-if prediction from `{MODEL_FQN}` version {SERVING_VERSION} in the Snowflake Model "
        "Registry, run in the warehouse as the app's least-privilege role. Uses only what is known "
        "when the order is placed. DataCo sample data, not Worthington data."
    )
    # One picker for market and region, so only real (market, region) pairs can be chosen.
    places = location_options(regions)
    with st.form("risk_form", border=False):
        c1, c2, c3 = st.columns(3)
        mode = c1.selectbox("Shipping mode", list(modes["SHIPPING_MODE"]), key="risk_mode")
        market, region = c2.selectbox(
            "Market · region", places, format_func=lambda p: f"{p[0]} · {p[1]}", key="risk_place"
        )
        segment = c3.selectbox("Customer segment", SEGMENTS, key="risk_segment")
        c4, c5, c6, c7 = st.columns([1, 2, 1, 1])
        payment = c4.selectbox("Payment type", PAYMENT_TYPES, key="risk_payment")
        hour = c5.slider("Order hour", 0, 23, 10, key="risk_hour")
        weekday = c6.selectbox("Weekday", WEEKDAYS, key="risk_weekday")
        month = c7.selectbox("Month", MONTHS, index=5, key="risk_month")
        c9, c10, c11 = st.columns(3)
        lines = c9.number_input("Order lines", 1, 10, 2, key="risk_lines")
        units = c10.number_input("Units", 1, 50, 4, key="risk_units")
        value = c11.number_input("Order value ($)", 1.0, 5000.0, 250.0, key="risk_value")
        submitted = st.form_submit_button("Predict late-delivery risk")

    if submitted:
        inputs = build_inputs(
            mode, market, region, segment, payment, weekday, hour, month, lines, units, value
        )
        try:
            st.session_state.risk_result = (inputs, data.late_risk(inputs))
        except Exception:
            st.session_state.risk_result = (inputs, None)

    result = st.session_state.get("risk_result")
    if result:
        inputs, p = result
        if p is None:
            st.warning(
                "The prediction model is unavailable right now. The charts above still work."
            )
        else:
            avg = mode_average(modes, inputs["SHIPPING_MODE"])
            a, b = st.columns(2)
            a.metric("Predicted late-delivery risk", f"{p:.0%}")
            if avg is not None:
                b.metric(f"{inputs['SHIPPING_MODE']}: governed late rate", f"{avg:.0%}")
    st.caption(
        "⚠️ What the model learned (see docs/late_risk_model_report.md): in this dataset lateness "
        "depends on the shipping mode, plus a 12:00 cut-off for Same Day orders. Market, region, "
        "segment, payment, weekday, month and order size barely change the prediction. The model "
        "matches a two-rule lookup; it does not explain why shipments are late."
    )
