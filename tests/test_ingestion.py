"""Phase 1 ingestion tests.

Unit tests use tiny in-memory fixtures (run in CI). Tests marked `real_data` run against the actual
DataCo file and are skipped when it is absent (raw data is never committed).
"""

from __future__ import annotations

import pandas as pd
import pytest

from supplychain_copilot.ingestion import schema
from supplychain_copilot.ingestion.clean_orders import (
    OUTPUT_PARQUET,
    RAW_CSV,
    DataQualityError,
    normalize_text,
    read_raw,
    sanitize,
    validate,
)

SOURCE_COLUMNS = list(schema.KEEP) + list(schema.DROP)


def _row(**overrides: str) -> dict[str, str]:
    """One plausible source row as text (fixture only; values shaped like the real file)."""
    base = {c: "" for c in SOURCE_COLUMNS}
    base.update(
        {
            "Order Item Id": "1",
            "Order Id": "10",
            "Customer Id": "500",
            "Order Customer Id": "500",
            "Product Card Id": "1360",
            "Order Item Cardprod Id": "1360",
            "Type": "DEBIT",
            "Order Status": "COMPLETE",
            "order date (DateOrders)": "1/31/2018 22:56",
            "shipping date (DateOrders)": "2/3/2018 22:56",
            "Days for shipping (real)": "3",
            "Days for shipment (scheduled)": "4",
            "Delivery Status": "Advance shipping",
            "Late_delivery_risk": "0",
            "Shipping Mode": "Standard Class",
            "Customer Segment": "Consumer",
            "Market": "Pacific Asia",
            "Order Region": "Southeast Asia ",
            "Order Country": "Indonesia",
            "Order State": "Java Occidental",
            "Order City": "Bekasi",
            "Product Name": "Smart watch ",
            "Category Id": "73",
            "Product Category Id": "73",
            "Category Name": "Sporting Goods",
            "Department Id": "2",
            "Department Name": "Fitness",
            "Order Item Quantity": "1",
            "Order Item Product Price": "327.75",
            "Product Price": "327.75",
            "Sales": "327.75",
            "Order Item Discount": "13.10999966",
            "Order Item Discount Rate": "0.039999999",
            "Order Item Total": "314.6400146",
            "Sales per customer": "314.6400146",
            "Order Profit Per Order": "91.25",
            "Benefit per order": "91.25",
            "Order Item Profit Ratio": "0.289999992",
            "Customer Email": "XXXXXXXXX",
            "Customer Password": "XXXXXXXXX",
            "Customer Fname": "Test",
            "Customer Lname": "Person",
            "Customer Street": "1 Example St",
            "Customer Zipcode": "00000",
            "Product Status": "0",
        }
    )
    base.update(overrides)
    return base


def _clean(rows: list[dict[str, str]]) -> pd.DataFrame:
    return sanitize(pd.DataFrame(rows, columns=SOURCE_COLUMNS), "fixture.csv", "0" * 64)


def _failed(results, name: str) -> bool:
    return next(r for r in results if r.name == name).passed is False


# ----------------------------------------------------------------------------- schema contract


def test_every_source_column_is_kept_or_dropped_exactly_once():
    assert not set(schema.KEEP) & set(schema.DROP)
    assert len(SOURCE_COLUMNS) == 53


def test_pii_columns_are_all_dropped():
    assert schema.PII_COLUMNS <= set(schema.DROP)
    assert not schema.PII_COLUMNS & set(schema.KEEP)


def test_target_names_are_unique_snake_case():
    targets = [t for t, _, _ in schema.KEEP.values()]
    assert len(targets) == len(set(targets))
    assert all(t == t.lower() and " " not in t for t in targets)


# ----------------------------------------------------------------------------- sanitize


def test_sanitize_drops_pii_renames_and_types():
    out = _clean([_row()])
    assert "order_item_id" in out.columns and "Order Item Id" not in out.columns
    for col in ("Customer Email", "Customer Password", "Customer Fname", "customer_fname"):
        assert col not in out.columns
    assert out.loc[0, "order_ts"] == pd.Timestamp("2018-01-31 22:56")
    assert out.loc[0, "net_sales"] == pytest.approx(314.6400146)
    assert out.loc[0, "source_row_number"] == 1


def test_whitespace_normalised():
    s = normalize_text(pd.Series(["South of  USA ", " Toys ", "   "]))
    assert s.tolist()[:2] == ["South of USA", "Toys"]
    assert pd.isna(s.iloc[2])


def test_unparseable_number_fails_loudly_instead_of_dropping():
    with pytest.raises(DataQualityError, match="Sales"):
        _clean([_row(Sales="abc")])


def test_unparseable_date_fails_loudly():
    with pytest.raises(DataQualityError, match="order date"):
        _clean([_row(**{"order date (DateOrders)": "2018-31-01"})])


def test_read_raw_rejects_schema_change(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame([{"Unexpected": "x"}]).to_csv(p, index=False)
    with pytest.raises(DataQualityError, match="schema changed"):
        read_raw(p)


# ----------------------------------------------------------------------------- validate


def test_valid_fixture_passes_all_error_checks():
    out = _clean([_row(), _row(**{"Order Item Id": "2"})])
    errors = [r for r in validate(out, source_rows=2) if r.severity == "error" and not r.passed]
    assert errors == []


def test_duplicate_line_key_detected():
    out = _clean([_row(), _row()])
    assert _failed(validate(out, 2), "order_item_id_unique")


def test_row_count_change_detected():
    out = _clean([_row()])
    assert _failed(validate(out, 2), "row_count_preserved")


def test_inconsistent_order_attributes_detected():
    out = _clean([_row(), _row(**{"Order Item Id": "2", "Shipping Mode": "First Class"})])
    assert _failed(validate(out, 2), "order_attributes_consistent_across_lines")


def test_late_flag_inconsistency_detected():
    out = _clean([_row(Late_delivery_risk="1")])  # 'Advance shipping' but flagged late
    assert _failed(validate(out, 1), "late_flag_matches_delivery_status")


def test_net_sales_identity_violation_detected():
    out = _clean([_row(**{"Order Item Total": "300.00"})])
    assert _failed(validate(out, 1), "net_sales_eq_gross_minus_discount")


def test_unknown_category_value_detected():
    out = _clean([_row(**{"Delivery Status": "Lost"})])
    assert _failed(validate(out, 1), "delivery_status_allowed_values")


def test_same_day_timestamp_quirk_is_flagged_not_dropped():
    row = _row(
        **{
            "Shipping Mode": "Same Day",
            "Days for shipment (scheduled)": "0",
            "Days for shipping (real)": "0",
            "Delivery Status": "Shipping on time",
            "shipping date (DateOrders)": "2/1/2018 10:56",  # order + 12h
        }
    )
    out = _clean([row])
    assert len(out) == 1 and bool(out.loc[0, "dq_ship_ts_mismatch"]) is True
    warning = next(r for r in validate(out, 1) if r.name == "ship_ts_vs_actual_days_mismatch")
    assert warning.severity == "warning" and warning.failing_rows == 1


# ----------------------------------------------------------------------------- real data

real_data = pytest.mark.skipif(not RAW_CSV.is_file(), reason="raw DataCo file not present")


@pytest.fixture(scope="module")
def real():
    raw = read_raw(RAW_CSV)
    return raw, sanitize(raw, RAW_CSV.name, "test")


@real_data
def test_real_counts_and_grain(real):
    raw, clean = real
    assert len(raw) == len(clean) == 180_519
    assert clean["order_item_id"].is_unique
    assert clean["order_id"].nunique() == 65_752  # orders, not lines
    assert clean["order_id"].nunique() < len(clean)


@real_data
def test_real_data_passes_all_error_checks(real):
    raw, clean = real
    errors = [r.name for r in validate(clean, len(raw)) if r.severity == "error" and not r.passed]
    assert errors == []


@real_data
def test_real_whitespace_normalisation_does_not_merge_categories(real):
    raw, clean = real
    for src, tgt in [
        ("Order Region", "order_region"),
        ("Category Name", "category_name"),
        ("Product Name", "product_name"),
        ("Department Name", "department_name"),
    ]:
        assert raw[src].nunique() == clean[tgt].nunique(), src


@real_data
def test_real_order_level_totals_reconcile(real):
    """Totals are unchanged by sanitizing, and summing order lines never double counts."""
    raw, clean = real
    assert clean["net_sales"].sum() == pytest.approx(pd.to_numeric(raw["Order Item Total"]).sum())
    per_order = clean.groupby("order_id")["net_sales"].sum()
    assert per_order.sum() == pytest.approx(clean["net_sales"].sum())


@real_data
def test_processed_parquet_has_no_pii_if_present():
    if not OUTPUT_PARQUET.is_file():
        pytest.skip("run clean_orders first")
    cols = set(pd.read_parquet(OUTPUT_PARQUET).columns)
    assert not cols & schema.PII_COLUMNS
    assert not {"customer_email", "customer_password", "customer_fname", "customer_lname"} & cols
