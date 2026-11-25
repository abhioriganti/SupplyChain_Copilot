# Data dictionary: sanitized DataCo order lines

**File:** `data/processed/dataco_order_lines.parquet` (gitignored; regenerate with `python -m supplychain_copilot.ingestion.clean_orders`)
**Grain:** one row per **order line** (`order_item_id`). 180,519 rows, covering 65,752 orders.
**Source:** DataCo Smart Supply Chain v5 (public retail/e-commerce sample, CC BY 4.0, cp1252 CSV). Not Worthington data.
**Contract:** [`src/supplychain_copilot/ingestion/schema.py`](../src/supplychain_copilot/ingestion/schema.py) lists all 53 source columns exactly once, as kept or dropped. Tests enforce this.

The *Grain* column says which entity an attribute belongs to, as verified in [profiling_report.md](profiling_report.md) §4:
- **order:** identical on every line of the order.
- **product:** identical for every line of the product.
- **line:** varies per line.

Text values are trimmed and internal whitespace is collapsed. That changes no distinct counts.

## Keys

| Column | Type | Grain | Source column | Description |
|---|---|---|---|---|
| `order_item_id` | int | line | Order Item Id | Unique order-line key (1…180,519) |
| `order_id` | int | order | Order Id | Order key. 65,752 distinct, with gaps in the ID range. **Count distinct `order_id` to count orders.** |
| `customer_id` | int | order | Customer Id | Dataset surrogate customer key. No names, email, street or zip are retained with it. |
| `product_id` | int | product | Product Card Id | Product key (118 products) |

## Order and shipment attributes (order grain)

| Column | Type | Source column | Description and notes |
|---|---|---|---|
| `payment_type` | str | Type | DEBIT, TRANSFER, PAYMENT, CASH |
| `order_status` | str | Order Status | 9 values. CANCELED and SUSPECTED_FRAUD occur exactly when delivery_status is 'Shipping canceled'. |
| `order_ts` | timestamp | order date (DateOrders) | Order timestamp, 2015-01-01 → 2018-01-31. Source format `M/D/YYYY H:MM`, no timezone given. |
| `shipping_ts` | timestamp | shipping date (DateOrders) | Ship timestamp. **For Same Day orders it is always order_ts + 12h**, so don't derive durations from it. |
| `days_shipping_actual` | int | Days for shipping (real) | Actual shipping days (0–6). **Authoritative duration.** |
| `days_shipping_scheduled` | int | Days for shipment (scheduled) | Scheduled days. Fully determined by shipping mode: Same Day 0, First 1, Second 2, Standard 4. |
| `delivery_status` | str | Delivery Status | Advance shipping, Shipping on time, Late delivery, Shipping canceled |
| `late_delivery_risk` | int (0/1) | Late_delivery_risk | Source flag. Despite the name it is **not a prediction**: it equals 1 exactly when delivery_status = 'Late delivery'. |
| `shipping_mode` | str | Shipping Mode | Standard Class, Second Class, First Class, Same Day |
| `customer_segment` | str | Customer Segment | Consumer, Corporate, Home Office |
| `market` | str | Market | Africa, Europe, LATAM, Pacific Asia, USCA. **Rotates over time**: 26 of 37 months have a single market. |
| `order_region` | str | Order Region | 23 destination regions. Each region belongs to exactly one market. |
| `order_country` | str | Order Country | Destination country (164), with Spanish-language names in the source, e.g. "República Dominicana" |
| `order_state` | str | Order State | Destination state or province |
| `order_city` | str | Order City | Destination city |

## Product attributes (product grain)

| Column | Type | Source column | Description and notes |
|---|---|---|---|
| `product_name` | str | Product Name | 118 products. These are retail goods (e.g. "Smart watch"), not manufactured parts. |
| `category_id` | int | Category Id | Category key (51) |
| `category_name` | str | Category Name | 50 names. **"Electronics" maps to ids 13 and 37**, so use `category_id` as the key. |
| `department_id` | int | Department Id | Department key (11). It is a product attribute, so one order can span several departments. |
| `department_name` | str | Department Name | Department name |

## Line measures (line grain)

| Column | Type | Source column | Definition (verified identity) |
|---|---|---|---|
| `quantity` | int | Order Item Quantity | Units (1–5) |
| `unit_price` | float | Order Item Product Price | List price per unit before discount |
| `gross_sales` | float | Sales | `unit_price × quantity` (100% of rows) |
| `discount_amount` | float | Order Item Discount | Discount value |
| `discount_rate` | float | Order Item Discount Rate | 0–0.25. Stored rounded, so ≈ discount/gross on 94.44% of rows. Don't recompute amounts from it. |
| `net_sales` | float | Order Item Total | `gross_sales − discount_amount` (100% of rows). Candidate **revenue** measure. Final definition in Phase 2. |
| `line_profit` | float | Order Profit Per Order | **Line-level profit**: the source name is misleading because it varies per line. 33,784 negative (loss-making) lines are retained. |
| `profit_ratio` | float | Order Item Profit Ratio | Stored rounded (−2.75…0.5) |

Money values keep source precision (float32 artefacts such as `314.6400146`). Rounding is applied at presentation, not in storage.

## Data-quality and lineage columns

| Column | Type | Description |
|---|---|---|
| `dq_ship_ts_mismatch` | bool | True when `shipping_ts − order_ts ≠ days_shipping_actual`. True for all 9,737 Same Day lines and no others. |
| `source_file` | str | Source filename |
| `source_row_number` | int | 1-based data row number in the source CSV |
| `source_sha256` | str | SHA-256 of the source file (matches `data/manifest.json`) |
| `cleaned_at_utc` | timestamp | When the sanitizing run happened |

## Dropped source columns

| Source column | Reason |
|---|---|
| Customer Email, Customer Password | Masked in the source (`XXXXXXXXX`). A credential and contact field: never retained. |
| Customer Fname, Customer Lname, Customer Street, Customer Zipcode | PII |
| Customer City, Customer State, Customer Country, Latitude, Longitude | Customer or store location detail. Not needed for delivery analytics. |
| Order Customer Id, Order Item Cardprod Id, Product Category Id, Product Price | Exact duplicates of retained columns (verified on all rows) |
| Sales per customer, Benefit per order | Exact duplicates of Order Item Total and Order Profit Per Order (verified). Their names are misleading. |
| Product Description | 100% empty |
| Product Image | URL, not needed |
| Product Status | A single constant value (0) |
| Order Zipcode | 86.24% empty |

## What this dataset does *not* contain

- **Supplier identifiers, suppliers, plants, production or manufacturing attributes:** none. They are not fabricated, and the agent must say so when asked.
- **Shipment IDs or carrier data:** none. A shipment is defined as one per order, justified by order-level consistency (ADR-008).
- **Timezones:** not given. Timestamps are stored as naive local values.
