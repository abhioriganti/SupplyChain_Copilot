"""Late-delivery risk model (ADR-032): leak-free features, honest baselines, Snowflake Model Registry.

Pipeline:
1. Read order-time features from ``SCC_DB.ML.V_LATE_RISK_FEATURES`` (no post-shipment columns).
2. Train scikit-learn models locally (65k rows; training in Snowflake would add cost, not value)
   and compare them with a shipping-mode lookup baseline, on a random and a time-based holdout.
3. Ablation: the best model without SHIPPING_MODE, to show where the signal comes from.
4. Optionally log the chosen pipeline to the Snowflake Model Registry and check that SQL inference
   (``MODEL(...)!PREDICT_PROBA``) matches local predictions.

    python -m supplychain_copilot.ml.late_risk                 # train + evaluate + report (warehouse only)
    python -m supplychain_copilot.ml.late_risk --register --yes  # also log to the registry + parity check

Costs: a few seconds of the X-Small warehouse to read the view, register and run the parity query.
No Cortex/AI calls.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.ml.spec import (
    CATEGORICAL,
    FEATURES,
    FLOAT,
    INTEGER,
    MODEL_DB,
    MODEL_FQN,
    MODEL_NAME,
    MODEL_SCHEMA,
    POSITIVE_KEY,
)

FEATURE_VIEW = "SCC_DB.ML.V_LATE_RISK_FEATURES"
LABEL = "IS_LATE"
# Known only after shipping, or derived from the label. Must never be a feature (tested).
LEAKY = {
    "DAYS_SHIPPING_ACTUAL",
    "SHIPPING_TS",
    "SHIPPING_DELAY_DAYS",
    "DELIVERY_STATUS",
    "DAYS_LATE",
    "IS_ON_TIME_OR_EARLY",
    "IS_LATE",
    "ORDER_STATUS",
    "DQ_SHIP_TS_MISMATCH",
}
SEED = 42
# Prefer the simpler model unless the more complex one is clearly better on ROC AUC.
SIMPLER_WITHIN_AUC = 0.005

PROCESSED = PROJECT_ROOT / "data" / "processed"
RESULTS = PROCESSED / "late_risk_results.json"
REPORT = PROJECT_ROOT / "docs" / "late_risk_model_report.md"


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------
def load_features(conn) -> pd.DataFrame:
    from supplychain_copilot.snowflake.connection import query

    cols = ", ".join(["ORDER_ID", "ORDER_DATE", *FEATURES, LABEL])
    rows = query(conn, f"SELECT {cols} FROM {FEATURE_VIEW} ORDER BY ORDER_ID")  # noqa: S608 constants
    return prepare(pd.DataFrame(rows))


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Fix dtypes so the registry signature is stable (strings, int64, float64)."""
    out = df.copy()
    for c in CATEGORICAL:
        out[c] = out[c].astype(str)
    for c in INTEGER:
        out[c] = out[c].astype("int64")
    for c in FLOAT:
        out[c] = out[c].astype("float64")
    out[LABEL] = out[LABEL].astype("int64")
    out["ORDER_DATE"] = pd.to_datetime(out["ORDER_DATE"])
    return out


def split(df: pd.DataFrame, how: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """'random': stratified 80/20. 'time': the latest 20% of orders by date as the holdout.
    The time split also shifts the market mix (market rotation, ADR-011), so it is a harder test."""
    if how == "random":
        return train_test_split(df, test_size=0.2, random_state=SEED, stratify=df[LABEL])
    if how == "time":
        ordered = df.sort_values(["ORDER_DATE", "ORDER_ID"])
        cut = int(len(ordered) * 0.8)
        return ordered.iloc[:cut], ordered.iloc[cut:]
    raise ValueError(how)


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------
class ModeBaseline:
    """Predicts the training late rate of the order's shipping mode (a lookup table)."""

    def fit(self, X: pd.DataFrame, y: pd.Series) -> ModeBaseline:
        self.rates_ = y.groupby(X["SHIPPING_MODE"].values).mean().to_dict()
        self.prior_ = float(y.mean())
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = X["SHIPPING_MODE"].map(self.rates_).fillna(self.prior_).to_numpy(dtype=float)
        return np.column_stack([1 - p, p])


class ModeCutoffBaseline(ModeBaseline):
    """Shipping-mode lookup, with Same Day split at a 12:00 order cut-off. Found by the
    permutation-importance check (2026-11-27): Same Day orders placed before noon are never late,
    from noon on always late. Two rules; if a model can't beat this, it has learned nothing else."""

    @staticmethod
    def _key(X: pd.DataFrame) -> pd.Series:
        mode = X["SHIPPING_MODE"].astype(str)
        half = np.where(X["ORDER_HOUR"].to_numpy() < 12, " before 12:00", " from 12:00")
        return mode.where(mode != "Same Day", mode + half)

    def fit(self, X: pd.DataFrame, y: pd.Series) -> ModeCutoffBaseline:
        self.rates_ = y.groupby(self._key(X).values).mean().to_dict()
        self.prior_ = float(y.mean())
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = self._key(X).map(self.rates_).fillna(self.prior_).to_numpy(dtype=float)
        return np.column_stack([1 - p, p])


def _encoder(features: list[str], scale: bool) -> ColumnTransformer:
    cats = [c for c in CATEGORICAL if c in features]
    nums = [c for c in INTEGER + FLOAT if c in features]
    parts: list[tuple[str, Any, list[str]]] = [
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cats)
    ]
    if nums:
        parts.append(("num", StandardScaler() if scale else "passthrough", nums))
    return ColumnTransformer(parts)


def build_models(features: list[str] | None = None) -> dict[str, Any]:
    features = features or FEATURES
    return {
        "logistic_regression": Pipeline(
            [
                ("prep", _encoder(features, scale=True)),
                ("clf", LogisticRegression(max_iter=2000, random_state=SEED)),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                ("prep", _encoder(features, scale=False)),
                (
                    "clf",
                    HistGradientBoostingClassifier(
                        max_iter=200, learning_rate=0.05, random_state=SEED
                    ),
                ),
            ]
        ),
    }


def metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "log_loss": round(float(log_loss(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "accuracy": round(float(accuracy_score(y, p >= 0.5)), 4),
    }


@dataclass
class SplitResult:
    split: str
    n_train: int
    n_test: int
    test_late_rate: float
    scores: dict[str, dict[str, float]]


def evaluate_split(df: pd.DataFrame, how: str) -> tuple[SplitResult, dict[str, Any]]:
    train, test = split(df, how)
    ytr, yte = train[LABEL], test[LABEL].to_numpy()
    fitted: dict[str, Any] = {}
    scores: dict[str, dict[str, float]] = {}

    prior = np.full(len(test), float(ytr.mean()))
    scores["overall_rate (no features)"] = metrics(yte, prior)

    base = ModeBaseline().fit(train[FEATURES], ytr)
    scores["shipping_mode_baseline"] = metrics(yte, base.predict_proba(test[FEATURES])[:, 1])
    fitted["shipping_mode_baseline"] = base
    rule = ModeCutoffBaseline().fit(train[FEATURES], ytr)
    scores["mode_plus_same_day_cutoff_rule"] = metrics(
        yte, rule.predict_proba(test[FEATURES])[:, 1]
    )
    fitted["mode_plus_same_day_cutoff_rule"] = rule

    for name, model in build_models().items():
        model.fit(train[FEATURES], ytr)
        scores[name] = metrics(yte, model.predict_proba(test[FEATURES])[:, 1])
        fitted[name] = model

    # Ablation: where does the signal come from?
    no_mode = [f for f in FEATURES if f != "SHIPPING_MODE"]
    abl = build_models(no_mode)["gradient_boosting"].fit(train[no_mode], ytr)
    scores["gradient_boosting_without_shipping_mode"] = metrics(
        yte, abl.predict_proba(test[no_mode])[:, 1]
    )

    res = SplitResult(how, len(train), len(test), round(float(yte.mean()), 4), scores)
    return res, fitted


def choose(scores: dict[str, dict[str, float]]) -> str:
    """The simpler model (logistic regression) unless gradient boosting is clearly better."""
    lr, gb = scores["logistic_regression"]["roc_auc"], scores["gradient_boosting"]["roc_auc"]
    return "gradient_boosting" if gb - lr > SIMPLER_WITHIN_AUC else "logistic_regression"


def lift_over_baseline(
    scores: dict[str, dict[str, float]], name: str, baseline: str = "shipping_mode_baseline"
) -> float:
    return round(scores[name]["roc_auc"] - scores[baseline]["roc_auc"], 4)


RULE = "mode_plus_same_day_cutoff_rule"


# ---------------------------------------------------------------------------------------------
# Registry (Snowflake ML), imported lazily so the CI suite does not need snowflake-ml-python
# ---------------------------------------------------------------------------------------------
def snowpark_session():
    from cryptography.hazmat.primitives import serialization
    from snowflake.snowpark import Session

    from supplychain_copilot.config import load_settings
    from supplychain_copilot.snowflake.keys import load_private_key

    s = load_settings()
    key = load_private_key(s.private_key_path, s.private_key_passphrase).private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return Session.builder.configs(
        {
            "account": s.account,
            "user": s.user,
            "role": s.role,
            "warehouse": s.warehouse,
            "database": MODEL_DB,
            "schema": MODEL_SCHEMA,
            "private_key": key,
        }
    ).create()


def register(model, sample: pd.DataFrame, version: str, model_metrics: dict, comment: str):
    import sklearn
    from snowflake.ml.model import task
    from snowflake.ml.registry import Registry

    sp = snowpark_session()
    try:
        reg = Registry(session=sp, database_name=MODEL_DB, schema_name=MODEL_SCHEMA)
        mv = reg.log_model(
            model,
            model_name=MODEL_NAME,
            version_name=version,
            conda_dependencies=[f"scikit-learn=={sklearn.__version__}"],
            sample_input_data=sample[FEATURES],
            target_platforms=["WAREHOUSE"],
            task=task.Task.TABULAR_BINARY_CLASSIFICATION,
            metrics=model_metrics,
            comment=comment,
        )
        return mv.version_name
    finally:
        sp.close()


def sql_inference_sql(version: str, source: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", version):
        raise ValueError("version must be a plain identifier")
    args = ", ".join(FEATURES)
    return (
        f"SELECT ORDER_ID, MODEL({MODEL_FQN}, {version})!PREDICT_PROBA({args}) AS P "  # noqa: S608
        f"FROM {source}"
    )


def parse_proba(value: Any) -> float:
    """PREDICT_PROBA returns an OBJECT ({output_feature_0, output_feature_1}); take P(late)."""
    obj = json.loads(value) if isinstance(value, str) else dict(value)
    return float(obj[POSITIVE_KEY])


def parity_check(conn, model, df: pd.DataFrame, version: str, n: int = 200) -> dict[str, Any]:
    from supplychain_copilot.snowflake.connection import query

    ids = df.sort_values("ORDER_ID")["ORDER_ID"].head(n).tolist()
    source = f"(SELECT * FROM {FEATURE_VIEW} WHERE ORDER_ID <= {int(max(ids))})"  # noqa: S608 constant + int
    rows = query(conn, sql_inference_sql(version, source))
    remote = {int(r["ORDER_ID"]): parse_proba(r["P"]) for r in rows}
    local_df = df[df["ORDER_ID"].isin(remote)]
    local = dict(
        zip(local_df["ORDER_ID"], model.predict_proba(local_df[FEATURES])[:, 1], strict=True)
    )
    diffs = [abs(remote[i] - float(local[i])) for i in remote]
    sample_obj = rows[0]["P"] if rows else None
    return {
        "rows": len(diffs),
        "max_abs_diff": round(max(diffs), 8) if diffs else None,
        "sample_output": json.loads(sample_obj) if isinstance(sample_obj, str) else sample_obj,
    }


# ---------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------
def render(results: dict[str, Any]) -> str:
    lines = [
        "# Late-delivery risk model report (generated)",
        "",
        f"Generated by `python -m supplychain_copilot.ml.late_risk` at {results['generated_at']}. "
        "Data: DataCo public sample (retail/e-commerce), eligible shipments only. "
        "Features are known when the order is placed; post-shipment columns are excluded.",
        "",
        f"**Features:** {', '.join(FEATURES)}",
        "",
    ]
    for s in results["splits"]:
        lines += [
            f"## Holdout: {s['split']} ({s['n_train']:,} train / {s['n_test']:,} test, "
            f"test late rate {s['test_late_rate']:.1%})",
            "",
            "| Model | ROC AUC | Log loss | Brier | Accuracy |",
            "|---|---|---|---|---|",
        ]
        for name, m in s["scores"].items():
            lines.append(
                f"| {name} | {m['roc_auc']:.4f} | {m['log_loss']:.4f} | {m['brier']:.4f} | "
                f"{m['accuracy']:.4f} |"
            )
        lines.append("")
    c = results["chosen"]
    lines += [
        "## Chosen model",
        f"- `{c['name']}` (rule: the simpler model unless the other is more than "
        f"{SIMPLER_WITHIN_AUC} ROC AUC better on the random holdout)",
        f"- ROC AUC lift over the shipping-mode baseline: random {c['lift_random']:+.4f}, "
        f"time {c['lift_time']:+.4f}",
        f"- ROC AUC lift over the two-rule baseline (mode + Same Day 12:00 cut-off): random "
        f"{c['lift_vs_rule_random']:+.4f}, time {c['lift_vs_rule_time']:+.4f}",
        "",
    ]
    if results.get("registry"):
        r = results["registry"]
        lines += [
            "## Snowflake Model Registry",
            f"- Logged as `{MODEL_FQN}` version `{r['version']}` (target platform WAREHOUSE)",
            f"- SQL inference parity: {r['parity']['rows']} rows, max |SQL − local| = "
            f"{r['parity']['max_abs_diff']}",
            "",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--register", action="store_true", help="log the chosen model to the registry")
    p.add_argument("--version", default="V1", help="registry version name")
    p.add_argument("--yes", action="store_true", help="confirm warehouse use for registration")
    args = p.parse_args(argv)
    if args.register and not args.yes:
        p.error("--register needs --yes (uses the warehouse)")

    from supplychain_copilot.snowflake.connection import session

    with session() as conn:
        df = load_features(conn)
    print(f"loaded {len(df):,} rows, late rate {df[LABEL].mean():.3f}")

    split_results, fitted_random = [], {}
    for how in ("random", "time"):
        res, fitted = evaluate_split(df, how)
        split_results.append(res.__dict__)
        if how == "random":
            fitted_random = fitted
        for name, m in res.scores.items():
            print(f"[{how}] {name:45s} AUC {m['roc_auc']:.4f}  logloss {m['log_loss']:.4f}")

    random_scores, time_scores = split_results[0]["scores"], split_results[1]["scores"]
    name = choose(random_scores)
    results: dict[str, Any] = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": len(df),
        "features": FEATURES,
        "splits": split_results,
        "chosen": {
            "name": name,
            "lift_random": lift_over_baseline(random_scores, name),
            "lift_time": lift_over_baseline(time_scores, name),
            "lift_vs_rule_random": lift_over_baseline(random_scores, name, RULE),
            "lift_vs_rule_time": lift_over_baseline(time_scores, name, RULE),
        },
    }

    if args.register:
        model = fitted_random[name]
        m = random_scores[name]
        comment = (
            f"{name}; DataCo public sample; random-holdout ROC AUC {m['roc_auc']}, "
            f"lift over shipping-mode baseline {results['chosen']['lift_random']:+.4f} (ADR-032)"
        )
        version = register(model, df.head(500), args.version, {"random_holdout": m}, comment)
        with session() as conn:
            parity = parity_check(conn, model, df, version)
        results["registry"] = {"model": MODEL_FQN, "version": version, "parity": parity}
        print(f"registered {MODEL_FQN} {version}; parity {parity}")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    REPORT.write_text(render(results), encoding="utf-8")
    print(f"chosen {name}; wrote {REPORT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
