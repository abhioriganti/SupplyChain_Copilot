"""Late-delivery risk model (ADR-032): leakage guards, baselines, SQL contract and the app card.
CI-safe: synthetic data, no Snowflake, no snowflake-ml-python."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from supplychain_copilot.ml import late_risk as L
from supplychain_copilot.ml import spec
from supplychain_copilot.ui import risk
from supplychain_copilot.ui.data import DashboardData
from tests.test_ui import FakeData, _app

ROOT = Path(__file__).resolve().parents[1]
VIEW_SQL = (ROOT / "sql" / "85_ml" / "01_late_risk_features.sql").read_text(encoding="utf-8")


def _view_select() -> str:
    return VIEW_SQL[VIEW_SQL.index("AS\nSELECT") : VIEW_SQL.index("FROM SCC_DB.GOLD.FACT_ORDERS")]


def _synthetic(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    """Same rules as DataCo: lateness set by shipping mode, plus the Same Day 12:00 cut-off."""
    rng = np.random.default_rng(seed)
    modes = rng.choice(["First Class", "Second Class", "Standard Class", "Same Day"], n)
    hour = rng.integers(0, 24, n)
    p = np.select(
        [modes == "First Class", modes == "Second Class", modes == "Standard Class"],
        [1.0, 0.8, 0.4],
        np.where(hour >= 12, 1.0, 0.0),
    )
    df = pd.DataFrame(
        {
            "ORDER_ID": np.arange(n),
            "ORDER_DATE": pd.date_range("2015-01-01", periods=n, freq="h").date,
            "SHIPPING_MODE": modes,
            "MARKET": rng.choice(["Europe", "LATAM"], n),
            "ORDER_REGION": rng.choice(["Western Europe", "South America"], n),
            "CUSTOMER_SEGMENT": rng.choice(spec.SEGMENTS, n),
            "PAYMENT_TYPE": rng.choice(spec.PAYMENT_TYPES, n),
            "ORDER_DOW": rng.integers(1, 8, n),
            "ORDER_HOUR": hour,
            "ORDER_MONTH": rng.integers(1, 13, n),
            "LINE_COUNT": rng.integers(1, 6, n),
            "UNITS": rng.integers(1, 10, n),
            "NET_SALES": rng.uniform(10, 1000, n),
            "IS_LATE": (rng.uniform(size=n) < p).astype(int),
        }
    )
    return L.prepare(df)


# ----------------------------------------------------------------------------- leakage guards


def test_no_post_shipment_column_is_a_feature():
    assert not set(spec.FEATURES) & L.LEAKY
    assert "DAYS_SHIPPING_SCHEDULED" not in spec.FEATURES  # a copy of SHIPPING_MODE


def test_feature_view_selects_exactly_the_features_and_no_leaky_column():
    select = _view_select()
    selected = set(re.findall(r"\bAS ([A-Z_]+)\b", select)) | {
        c for c in spec.FEATURES if re.search(rf"^\s+{c},?\s*(--.*)?$", select, re.M)
    }
    assert set(spec.FEATURES) <= selected
    for col in L.LEAKY - {"IS_LATE"}:
        assert not re.search(rf"\b{col}\b", select), col
    assert "WHERE IS_SHIPMENT_ELIGIBLE" in VIEW_SQL


def test_app_role_gets_usage_on_the_model_but_no_read_on_training_data():
    grants = (ROOT / "sql" / "85_ml" / "02_late_risk_model_grants.sql").read_text(encoding="utf-8")
    assert "GRANT USAGE ON MODEL SCC_DB.ML.LATE_DELIVERY_RISK TO ROLE SCC_APP_ROLE" in grants
    assert not re.search(r"^GRANT SELECT", grants, re.M)
    assert not re.search(r"^GRANT READ", grants, re.M)


# ----------------------------------------------------------------------------- models


def test_baselines_learn_the_two_rules():
    df = _synthetic()
    X, y = df[spec.FEATURES], df[L.LABEL]
    mode = L.ModeBaseline().fit(X, y)
    assert mode.rates_["First Class"] == 1.0
    rule = L.ModeCutoffBaseline().fit(X, y)
    assert rule.rates_["Same Day before 12:00"] == 0.0
    assert rule.rates_["Same Day from 12:00"] == 1.0
    p = rule.predict_proba(X)[:, 1]
    assert p.shape == (len(df),) and ((p >= 0) & (p <= 1)).all()


def test_evaluate_split_reports_baselines_models_and_ablation():
    res, fitted = L.evaluate_split(_synthetic(), "random")
    names = set(res.scores)
    assert {
        "overall_rate (no features)",
        "shipping_mode_baseline",
        L.RULE,
        "logistic_regression",
        "gradient_boosting",
        "gradient_boosting_without_shipping_mode",
    } <= names
    s = res.scores
    assert s["overall_rate (no features)"]["roc_auc"] == 0.5
    assert s[L.RULE]["roc_auc"] > s["shipping_mode_baseline"]["roc_auc"]
    assert (
        s["gradient_boosting_without_shipping_mode"]["roc_auc"] < s["gradient_boosting"]["roc_auc"]
    )
    assert "gradient_boosting" in fitted


def test_time_split_holds_out_the_latest_orders():
    df = _synthetic()
    train, test = L.split(df, "time")
    assert train["ORDER_DATE"].max() <= test["ORDER_DATE"].min()
    assert len(test) == len(df) - int(len(df) * 0.8)


def test_choose_prefers_the_simpler_model_unless_clearly_better():
    def scores(lr, gb):
        return {"logistic_regression": {"roc_auc": lr}, "gradient_boosting": {"roc_auc": gb}}

    assert L.choose(scores(0.740, 0.744)) == "logistic_regression"
    assert L.choose(scores(0.740, 0.768)) == "gradient_boosting"


# ----------------------------------------------------------------------------- SQL contract


def test_predict_sql_binds_one_value_per_feature():
    sql = spec.predict_sql()
    assert sql.count("%s") == len(spec.FEATURES)
    assert "MODEL(SCC_DB.ML.LATE_DELIVERY_RISK, V1)!PREDICT_PROBA(" in sql


def test_batch_inference_rejects_a_non_identifier_version():
    assert "!PREDICT_PROBA(SHIPPING_MODE, MARKET" in L.sql_inference_sql("V1", "T")
    with pytest.raises(ValueError):
        L.sql_inference_sql("V1); DROP TABLE X; --", "T")


def test_parse_proba_reads_the_positive_class():
    assert L.parse_proba('{"output_feature_0": 0.25, "output_feature_1": 0.75}') == 0.75
    assert L.parse_proba({"output_feature_0": 0.9, "output_feature_1": 0.1}) == 0.1


def test_data_layer_calls_the_model_with_bound_values():
    calls = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            calls.append((sql, params))

        def fetchall(self):
            return [{"P": '{"output_feature_0": 0.6, "output_feature_1": 0.4}'}]

    class Conn:
        def cursor(self, *a):
            return Cur()

    @contextmanager
    def fake_session():
        yield Conn()

    inputs = risk.build_inputs(
        "Standard Class",
        "Europe",
        "Western Europe",
        "Consumer",
        "DEBIT",
        "Wed",
        9,
        "Jun",
        2,
        4,
        250,
    )
    p = DashboardData(fake_session).late_risk(inputs)
    assert p == 0.4
    sql, params = calls[0]
    assert "PREDICT_PROBA" in sql and "Standard Class" not in sql
    assert params[0] == "Standard Class" and params[spec.FEATURES.index("ORDER_DOW")] == 3


# ----------------------------------------------------------------------------- app card


class FakeRiskData(FakeData):
    def __init__(self, p=0.42, fail=False):
        super().__init__()
        self.p, self.risk_fail, self.inputs = p, fail, None

    def late_risk(self, inputs):
        self.inputs = inputs
        if self.risk_fail:
            raise RuntimeError("model down: account=SECRET-ACCOUNT")
        return self.p


def _predict(data) -> object:
    at = _app(data=data)
    at.run()
    next(b for b in at.button if "Predict late-delivery risk" in b.label).click().run()
    return at


def test_risk_card_shows_prediction_and_governed_rate():
    data = FakeRiskData(p=0.42)
    at = _predict(data)
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["Predicted late-delivery risk"] == "42%"
    assert values["First Class: governed late rate"] == "100%"
    assert data.inputs["SHIPPING_MODE"] == "First Class" and data.inputs["ORDER_HOUR"] == 10
    captions = " ".join(c.value for c in at.caption)
    assert "12:00 cut-off" in captions and "not Worthington" in captions


def test_location_options_only_offer_real_market_region_pairs():
    from tests.test_ui import REGIONS

    assert risk.location_options(REGIONS) == [("Africa", "Central Africa"), ("USCA", "Canada")]
    data = FakeRiskData()
    _predict(data)
    assert (data.inputs["MARKET"], data.inputs["ORDER_REGION"]) == ("Africa", "Central Africa")


def test_repeat_prediction_with_same_inputs_is_reused():
    calls = []

    class Counting(FakeRiskData):
        def late_risk(self, inputs):
            calls.append(inputs)
            return 0.3

    at = _predict(Counting())
    next(b for b in at.button if "Predict late-delivery risk" in b.label).click().run()
    assert len(calls) == 1
    assert {m.label: m.value for m in at.metric}["Predicted late-delivery risk"] == "30%"


def test_risk_card_failure_is_friendly():
    at = _predict(FakeRiskData(fail=True))
    assert not at.exception
    warning = " ".join(w.value for w in at.warning)
    assert "prediction model is unavailable" in warning and "SECRET-ACCOUNT" not in warning


def test_risk_card_hidden_when_data_layer_has_no_model():
    at = _app(data=FakeData())
    at.run()
    assert not any("Predict late-delivery risk" in b.label for b in at.button)
