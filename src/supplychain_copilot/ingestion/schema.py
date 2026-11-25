"""Source-to-sanitized column contract for DataCo. Single source of truth for keep/rename/drop.

Every one of the 53 source columns appears exactly once: either in KEEP (renamed + typed) or in DROP
(with a reason). Tests enforce this, so a schema change in the source fails loudly.
"""

from __future__ import annotations

from typing import Literal

SOURCE_ENCODING = "cp1252"  # verified: bytes 0x8a/0x8e/0x92 present (C1 range, cp1252-only glyphs)
SOURCE_DATETIME_FORMAT = "%m/%d/%Y %H:%M"

ColType = Literal["int", "float", "str", "datetime"]
Grain = Literal["order", "line", "product"]

# source column -> (target name, type, grain the attribute belongs to)
KEEP: dict[str, tuple[str, ColType, Grain]] = {
    # keys
    "Order Item Id": ("order_item_id", "int", "line"),
    "Order Id": ("order_id", "int", "order"),
    "Customer Id": (
        "customer_id",
        "int",
        "order",
    ),  # dataset surrogate key; no direct identifiers kept
    "Product Card Id": ("product_id", "int", "product"),
    # order / shipment attributes (verified constant across an order's lines)
    "Type": ("payment_type", "str", "order"),
    "Order Status": ("order_status", "str", "order"),
    "order date (DateOrders)": ("order_ts", "datetime", "order"),
    "shipping date (DateOrders)": ("shipping_ts", "datetime", "order"),
    "Days for shipping (real)": ("days_shipping_actual", "int", "order"),
    "Days for shipment (scheduled)": ("days_shipping_scheduled", "int", "order"),
    "Delivery Status": ("delivery_status", "str", "order"),
    "Late_delivery_risk": ("late_delivery_risk", "int", "order"),
    "Shipping Mode": ("shipping_mode", "str", "order"),
    "Customer Segment": ("customer_segment", "str", "order"),
    "Market": ("market", "str", "order"),
    "Order Region": ("order_region", "str", "order"),
    "Order Country": ("order_country", "str", "order"),
    "Order State": ("order_state", "str", "order"),
    "Order City": ("order_city", "str", "order"),
    # product attributes (verified constant per product)
    "Product Name": ("product_name", "str", "product"),
    "Category Id": ("category_id", "int", "product"),
    "Category Name": ("category_name", "str", "product"),
    "Department Id": ("department_id", "int", "product"),
    "Department Name": ("department_name", "str", "product"),
    # line measures
    "Order Item Quantity": ("quantity", "int", "line"),
    "Order Item Product Price": ("unit_price", "float", "line"),
    "Sales": ("gross_sales", "float", "line"),
    "Order Item Discount": ("discount_amount", "float", "line"),
    "Order Item Discount Rate": ("discount_rate", "float", "line"),
    "Order Item Total": ("net_sales", "float", "line"),
    "Order Profit Per Order": (
        "line_profit",
        "float",
        "line",
    ),  # misnamed in source: varies per line
    "Order Item Profit Ratio": ("profit_ratio", "float", "line"),
}

DROP: dict[str, str] = {
    "Customer Email": "PII field (masked 'XXXXXXXXX' in source); not needed",
    "Customer Password": "credential field (masked in source); never retained",
    "Customer Fname": "PII: personal name",
    "Customer Lname": "PII: personal name",
    "Customer Street": "PII: street address",
    "Customer Zipcode": "PII: postal code",
    "Customer City": "customer/store location detail; not needed for delivery analytics",
    "Customer State": "customer/store location detail; not needed",
    "Customer Country": "customer/store location detail; not needed",
    "Latitude": "precise store/customer coordinates; not needed",
    "Longitude": "precise store/customer coordinates; not needed",
    "Order Customer Id": "exact duplicate of Customer Id (verified on all rows)",
    "Order Item Cardprod Id": "exact duplicate of Product Card Id (verified on all rows)",
    "Product Category Id": "exact duplicate of Category Id (verified on all rows)",
    "Product Price": "exact duplicate of Order Item Product Price (verified on all rows)",
    "Sales per customer": "exact duplicate of Order Item Total (verified; misleading name)",
    "Benefit per order": "exact duplicate of Order Profit Per Order (verified; misleading name)",
    "Product Description": "100% empty in source",
    "Product Image": "image URL; not needed",
    "Product Status": "single constant value (0) in source",
    "Order Zipcode": "~86% empty in source; not needed",
}

# Columns that must never appear in sanitized output.
PII_COLUMNS = {
    "Customer Email",
    "Customer Password",
    "Customer Fname",
    "Customer Lname",
    "Customer Street",
    "Customer Zipcode",
}

ORDER_LEVEL_COLUMNS = [t for _, (t, _, g) in KEEP.items() if g == "order" and t != "order_id"]
PRODUCT_LEVEL_COLUMNS = [t for _, (t, _, g) in KEEP.items() if g == "product" and t != "product_id"]

ALLOWED_VALUES: dict[str, set[str]] = {
    "delivery_status": {
        "Advance shipping",
        "Late delivery",
        "Shipping canceled",
        "Shipping on time",
    },
    "shipping_mode": {"Standard Class", "First Class", "Second Class", "Same Day"},
    "order_status": {
        "COMPLETE",
        "PENDING",
        "CLOSED",
        "PENDING_PAYMENT",
        "CANCELED",
        "PROCESSING",
        "SUSPECTED_FRAUD",
        "ON_HOLD",
        "PAYMENT_REVIEW",
    },
    "market": {"Africa", "Europe", "LATAM", "Pacific Asia", "USCA"},
    "customer_segment": {"Consumer", "Corporate", "Home Office"},
    "payment_type": {"DEBIT", "TRANSFER", "PAYMENT", "CASH"},
}

CANCELED_DELIVERY_STATUS = "Shipping canceled"
LATE_DELIVERY_STATUS = "Late delivery"
