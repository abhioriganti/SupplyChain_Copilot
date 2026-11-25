"""Sanitize and validate DataCo order lines -> data/processed/dataco_order_lines.parquet.

Grain of the output: one row per order line (``order_item_id``), same as the source. No rows are
dropped: problems either fail the run (errors) or are flagged in ``dq_*`` columns and in the
validation report (warnings). Metric logic (eligibility, late rate, ...) is deliberately NOT applied
here; it belongs to the governed Silver/Gold + semantic layer in Snowflake (Phase 2).

Usage:
    python -m supplychain_copilot.ingestion.clean_orders
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.ingestion import schema
from supplychain_copilot.ingestion.download_data import load_manifest, sha256_of

RAW_CSV = PROJECT_ROOT / "data" / "raw" / "dataco" / "DataCoSupplyChainDataset.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_PARQUET = PROCESSED_DIR / "dataco_order_lines.parquet"
VALIDATION_JSON = PROCESSED_DIR / "dataco_validation.json"

MONEY_TOLERANCE = 0.011  # source values are float32-rounded (e.g. 314.6400146)
_WHITESPACE = re.compile(r"\s+")


class DataQualityError(RuntimeError):
    """Raised when an error-severity validation check fails."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: str  # "error" | "warning"
    passed: bool
    failing_rows: int
    detail: str


# ----------------------------------------------------------------------------- read


def read_raw(path: Path = RAW_CSV) -> pd.DataFrame:
    """Read the source CSV as text exactly as stored (no type inference, empty -> '')."""
    df = pd.read_csv(path, encoding=schema.SOURCE_ENCODING, dtype=str, keep_default_na=False)
    expected = set(schema.KEEP) | set(schema.DROP)
    missing, unexpected = expected - set(df.columns), set(df.columns) - expected
    if missing or unexpected:
        raise DataQualityError(
            f"Source schema changed. Missing: {sorted(missing)}; unexpected: {sorted(unexpected)}"
        )
    return df


# ----------------------------------------------------------------------------- sanitize


def normalize_text(s: pd.Series) -> pd.Series:
    """Trim and collapse internal whitespace ('South of  USA ' -> 'South of USA'). Empty -> NA."""
    out = s.str.replace(_WHITESPACE, " ", regex=True).str.strip()
    return out.mask(out == "", pd.NA)


def _convert(s: pd.Series, col_type: schema.ColType, name: str) -> pd.Series:
    if col_type == "str":
        return normalize_text(s).astype("string")
    if col_type == "datetime":
        parsed = pd.to_datetime(s, format=schema.SOURCE_DATETIME_FORMAT, errors="coerce")
    else:
        parsed = pd.to_numeric(s.str.strip(), errors="coerce")
    bad = parsed.isna() & (s.str.strip() != "")
    if bad.any():
        raise DataQualityError(
            f"{name}: {int(bad.sum())} value(s) failed {col_type} parsing, "
            f"e.g. {s[bad].head(3).tolist()}"
        )
    if col_type == "int":
        if (parsed.dropna() % 1 != 0).any():
            raise DataQualityError(f"{name}: non-integer values in an integer column")
        return parsed.astype("Int64")
    return parsed.astype("float64") if col_type == "float" else parsed


def sanitize(raw: pd.DataFrame, source_file: str, source_sha256: str) -> pd.DataFrame:
    """Keep business columns, rename to snake_case, type them, add lineage + DQ flags."""
    out = pd.DataFrame(index=raw.index)
    for src, (target, col_type, _grain) in schema.KEEP.items():
        out[target] = _convert(raw[src], col_type, src)

    delta_days = (out["shipping_ts"] - out["order_ts"]).dt.total_seconds() / 86400
    out["dq_ship_ts_mismatch"] = (delta_days != out["days_shipping_actual"]).astype(bool)

    out["source_file"] = source_file
    out["source_row_number"] = np.arange(1, len(raw) + 1, dtype="int64")  # 1-based data row
    out["source_sha256"] = source_sha256
    out["cleaned_at_utc"] = pd.Timestamp(datetime.now(UTC)).tz_localize(None)
    return out.reset_index(drop=True)


# ----------------------------------------------------------------------------- validate


def _check(name: str, severity: str, failing: pd.Series | int, detail: str) -> CheckResult:
    n = int(failing.sum()) if isinstance(failing, pd.Series) else int(failing)
    return CheckResult(name, severity, n == 0, n, detail)


def validate(df: pd.DataFrame, source_rows: int) -> list[CheckResult]:
    r: list[CheckResult] = []
    r.append(
        _check(
            "row_count_preserved",
            "error",
            abs(len(df) - source_rows),
            f"{len(df)} output rows vs {source_rows} source rows",
        )
    )
    r.append(
        _check(
            "no_pii_columns",
            "error",
            len([c for c in df.columns if c in schema.PII_COLUMNS]),
            "sanitized output contains no PII source columns",
        )
    )
    r.append(_check("order_item_id_unique", "error", df["order_item_id"].duplicated(), "line key"))
    for key in ("order_item_id", "order_id", "product_id", "customer_id"):
        r.append(_check(f"{key}_not_null", "error", df[key].isna(), "key must be present"))
    r.append(
        _check(
            "dates_present",
            "error",
            df["order_ts"].isna() | df["shipping_ts"].isna(),
            "both parsed",
        )
    )
    r.append(
        _check(
            "ship_not_before_order", "error", df["shipping_ts"] < df["order_ts"], "causal ordering"
        )
    )
    for col, allowed in schema.ALLOWED_VALUES.items():
        r.append(
            _check(
                f"{col}_allowed_values", "error", ~df[col].isin(allowed), f"in {sorted(allowed)}"
            )
        )
    r.append(_check("quantity_positive", "error", df["quantity"] < 1, "quantity >= 1"))
    r.append(_check("unit_price_positive", "error", df["unit_price"] <= 0, "unit_price > 0"))
    r.append(
        _check(
            "discount_rate_range",
            "error",
            (df["discount_rate"] < 0) | (df["discount_rate"] > 1),
            "0 <= discount_rate <= 1",
        )
    )
    r.append(
        _check(
            "gross_sales_eq_price_x_qty",
            "error",
            (df["gross_sales"] - df["unit_price"] * df["quantity"]).abs() > MONEY_TOLERANCE,
            f"|gross_sales - unit_price*quantity| <= {MONEY_TOLERANCE}",
        )
    )
    r.append(
        _check(
            "net_sales_eq_gross_minus_discount",
            "error",
            (df["net_sales"] - (df["gross_sales"] - df["discount_amount"])).abs() > MONEY_TOLERANCE,
            f"|net_sales - (gross_sales - discount_amount)| <= {MONEY_TOLERANCE}",
        )
    )
    r.append(
        _check(
            "days_non_negative",
            "error",
            (df["days_shipping_actual"] < 0) | (df["days_shipping_scheduled"] < 0),
            "shipping days >= 0",
        )
    )

    # Order-level attributes must be identical on every line of an order (justifies order grain).
    nunique = df.groupby("order_id")[schema.ORDER_LEVEL_COLUMNS].nunique(dropna=False)
    inconsistent = (nunique > 1).any(axis=1)
    r.append(
        _check(
            "order_attributes_consistent_across_lines",
            "error",
            int(inconsistent.sum()),
            f"orders whose order-level fields differ across lines "
            f"(checked: {', '.join(schema.ORDER_LEVEL_COLUMNS)})",
        )
    )
    pnunique = df.groupby("product_id")[schema.PRODUCT_LEVEL_COLUMNS].nunique(dropna=False)
    r.append(
        _check(
            "product_attributes_consistent",
            "error",
            int((pnunique > 1).any(axis=1).sum()),
            "products whose name/category/department differ across lines",
        )
    )
    r.append(
        _check(
            "late_flag_matches_delivery_status",
            "error",
            (df["late_delivery_risk"] == 1)
            != (df["delivery_status"] == schema.LATE_DELIVERY_STATUS),
            "late_delivery_risk = 1 exactly when delivery_status = 'Late delivery'",
        )
    )
    not_canceled = df["delivery_status"] != schema.CANCELED_DELIVERY_STATUS
    late_by_days = df["days_shipping_actual"] > df["days_shipping_scheduled"]
    r.append(
        _check(
            "late_flag_matches_days_for_non_canceled",
            "error",
            not_canceled & ((df["late_delivery_risk"] == 1) != late_by_days),
            "for non-canceled lines: late_delivery_risk = (actual days > scheduled days)",
        )
    )
    canceled_status = df["order_status"].isin(["CANCELED", "SUSPECTED_FRAUD"])
    r.append(
        _check(
            "canceled_shipping_iff_canceled_or_fraud_order",
            "error",
            canceled_status != ~not_canceled,
            "delivery_status 'Shipping canceled' exactly when order_status in "
            "(CANCELED, SUSPECTED_FRAUD)",
        )
    )

    # Warnings: real source quirks, kept and flagged (never silently dropped).
    r.append(
        _check(
            "ship_ts_vs_actual_days_mismatch",
            "warning",
            df["dq_ship_ts_mismatch"],
            "shipping_ts - order_ts != days_shipping_actual. Observed only for 'Same Day' shipments, "
            "whose shipping_ts is always order_ts + 12h. Flagged in dq_ship_ts_mismatch; "
            "days_shipping_actual is treated as authoritative",
        )
    )
    r.append(
        _check(
            "canceled_lines_with_late_days",
            "warning",
            ~not_canceled & late_by_days,
            "canceled shipments whose actual days exceed scheduled days; to be excluded from "
            "delivery KPIs by the eligibility rule (Phase 2)",
        )
    )
    r.append(
        _check(
            "negative_line_profit",
            "warning",
            df["line_profit"] < 0,
            "loss-making lines; legitimate business values, retained",
        )
    )
    names = df.groupby("category_name")["category_id"].nunique()
    r.append(
        _check(
            "category_name_maps_to_multiple_ids",
            "warning",
            int((names > 1).sum()),
            f"category names with >1 category_id: {names[names > 1].index.tolist()}; "
            "category_id is the key, name is not unique",
        )
    )
    return r


# ----------------------------------------------------------------------------- run


def run(raw_csv: Path = RAW_CSV, output: Path = OUTPUT_PARQUET) -> list[CheckResult]:
    manifest = load_manifest()["dataco"]["files"]["DataCoSupplyChainDataset.csv"]
    actual_sha = sha256_of(raw_csv)
    if actual_sha != manifest["sha256"]:
        raise DataQualityError(f"{raw_csv.name} hash {actual_sha} does not match the manifest")

    raw = read_raw(raw_csv)
    clean = sanitize(raw, source_file=raw_csv.name, source_sha256=actual_sha)
    results = validate(clean, source_rows=len(raw))

    output.parent.mkdir(parents=True, exist_ok=True)
    errors = [c for c in results if c.severity == "error" and not c.passed]
    VALIDATION_JSON.write_text(
        json.dumps(
            {
                "source_file": raw_csv.name,
                "source_sha256": actual_sha,
                "rows": len(clean),
                "columns": list(clean.columns),
                "checks": [asdict(c) for c in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if errors:
        raise DataQualityError("Validation failed: " + "; ".join(c.name for c in errors))
    clean.to_parquet(output, index=False)
    return results


def main() -> int:
    results = run()
    for c in results:
        mark = "PASS" if c.passed else ("WARN" if c.severity == "warning" else "FAIL")
        print(f"[{mark}] {c.name:<48} failing_rows={c.failing_rows}")
    print(f"\nWrote {OUTPUT_PARQUET.relative_to(PROJECT_ROOT)} and {VALIDATION_JSON.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
