# Governed metric definitions

**Scope:** the DataCo public sample (retail/e-commerce, 2015-01-01 → 2018-01-31). **These are not Worthington metrics or data.**
**Implemented in:** `sql/30_gold/02_kpi_views.sql` (`SCC_DB.GOLD.V_KPI_*`). Phase 3 moves the same definitions into the Snowflake semantic view.
**Verified by:**
- `sql/tests/test_phase2_model.sql` (38 tests)
- independent pandas recomputation in `docs/reconciliation_report.md` (521 of 521 comparisons match)

## Entities and grain

| Entity | Grain | Rows | Notes |
|---|---|---|---|
| `GOLD.FACT_ORDERS` | one row per `ORDER_ID` = **one shipment** | 65,752 | All shipping attributes are constant across an order's lines (tested), so shipment grain equals order grain (ADR-008). **All delivery metrics use this table.** |
| `GOLD.FACT_ORDER_LINES` | one row per `ORDER_ITEM_ID` | 180,519 | Revenue and units. Many-to-one to `FACT_ORDERS` and `DIM_PRODUCTS`. |
| `GOLD.DIM_PRODUCTS` | one row per `PRODUCT_ID` | 118 | `CATEGORY_NAME` is not unique ("Electronics" = ids 13 and 37) |
| `GOLD.DIM_REGIONS` | one row per `ORDER_REGION` | 23 | Each region belongs to exactly one `MARKET` (5) |

**Valid relationships:**
- `FACT_ORDER_LINES.ORDER_ID → FACT_ORDERS.ORDER_ID`
- `FACT_ORDER_LINES.PRODUCT_ID → DIM_PRODUCTS.PRODUCT_ID`
- `FACT_ORDERS.ORDER_REGION → DIM_REGIONS.ORDER_REGION`

All are tested, because Snowflake doesn't enforce PK or FK constraints.

**Join rule:** you may aggregate line measures grouped by order attributes, which is a many-to-one join. **Never aggregate `FACT_ORDERS` measures after joining to lines**: that fan-out inflates revenue 3.49× on this data (see the reconciliation report).

## Shared flags (on `FACT_ORDERS`)

| Flag | Definition |
|---|---|
| `IS_SHIPMENT_ELIGIBLE` | `DELIVERY_STATUS <> 'Shipping canceled'`. A canceled shipment was never delivered, so it can be neither late nor on time. |
| `IS_LATE` | eligible **and** `DELIVERY_STATUS = 'Late delivery'`. On eligible shipments this is identical to `DAYS_SHIPPING_ACTUAL > DAYS_SHIPPING_SCHEDULED` (tested). |
| `IS_ON_TIME_OR_EARLY` | eligible **and not** late, i.e. 'Shipping on time' or 'Advance shipping' |
| `IS_REVENUE_ELIGIBLE` | `ORDER_STATUS NOT IN ('CANCELED','SUSPECTED_FRAUD')`. In this source the same 2,855 orders fail both eligibility rules (tested); they are kept as two flags because they mean different things. |
| `SHIPPING_DELAY_DAYS` | `DAYS_SHIPPING_ACTUAL − DAYS_SHIPPING_SCHEDULED` (whole days, can be negative) |
| `DAYS_LATE` | `SHIPPING_DELAY_DAYS` when `IS_LATE`, otherwise NULL |

Durations always come from the integer `DAYS_SHIPPING_*` fields, never from timestamps: Same Day timestamps are synthetic (order + 12h).

## Metrics

Every metric is listed with its grain, numerator, denominator, exclusions and null handling.

### 1. Distinct orders
- **Grain:** order. **Formula:** `COUNT(*)` on `FACT_ORDERS`, equal to `COUNT(DISTINCT ORDER_ID)` on lines.
- **Exclusions:** none; all statuses are counted.
- **Nulls:** `ORDER_ID` is never null (tested).
- **Value:** 65,752. ⚠️ Counting rows in a line table gives 180,519, which is wrong.

### 2. Order lines
- **Grain:** line. **Formula:** `COUNT(*)` on `FACT_ORDER_LINES`.
- **Exclusions:** none.
- **Value:** 180,519.

### 3. Total revenue
- **Grain:** line, or order totals that equal the sum of their lines (tested).
- **Formula:** `SUM(NET_SALES) WHERE IS_REVENUE_ELIGIBLE`, where `NET_SALES = GROSS_SALES − DISCOUNT_AMOUNT` (the source "Order Item Total"; identity verified on 100% of rows).
- **Exclusions:** orders with `ORDER_STATUS` CANCELED or SUSPECTED_FRAUD. Pending, processing and on-hold orders are **included** as booked sales.
- **Nulls:** none present (tested).
- **Value:** 31,644,665.08 (USD as stored in the source; the currency is not stated by the source).
- Not revenue: `GROSS_SALES` is before discount, and `LINE_PROFIT` is profit, not revenue. Including all statuses would give 33,054,402.38.

### 4. Eligible shipments
- **Grain:** shipment (order). **Formula:** `COUNT_IF(IS_SHIPMENT_ELIGIBLE)`.
- **Exclusions:** canceled shipments (2,855).
- **Value:** 62,897.

### 5. Late shipments
- **Grain:** shipment. **Formula:** `COUNT_IF(IS_LATE)`.
- **Value:** 36,048.

### 6. Late-delivery rate
- **Grain:** shipment.
- **Numerator:** late shipments. **Denominator:** eligible shipments.
- **Exclusions:** canceled shipments, which are removed from both numerator and denominator.
- **Nulls:** NULL when there are 0 eligible shipments (`NULLIF`).
- **Value:** 57.31%.

### 7. On-time delivery rate
- **Grain:** shipment.
- **Numerator:** on-time-or-early shipments. **Denominator:** eligible shipments.
- **Value:** 42.69%. Always `1 − late rate` (tested per region).
- "On time" includes early ("Advance shipping"). If a strict "exactly on schedule" rate is ever needed, it must be a separate, differently named metric.

### 8. Average actual shipping days
- **Grain:** shipment. **Formula:** `AVG(DAYS_SHIPPING_ACTUAL)` over eligible shipments.
- **Exclusions:** canceled shipments.
- **Nulls:** none present. NULL if no eligible shipments.
- **Value:** 3.5015 days.

### 9. Average days late
- **Grain:** shipment. **Formula:** `AVG(DAYS_LATE)`, i.e. average positive delay **over late shipments only**.
- On-time or early shipments are excluded, not counted as 0, and canceled shipments are excluded.
- **Value:** 1.6181 days.
- Not the same as the average delay over all eligible shipments, which would include zeros and negatives.

### 10. Regional delivery performance (`V_KPI_BY_REGION`)
- Metrics 1 and 3–9 grouped by `MARKET`, `ORDER_REGION` (destination), over the full period.
- Region late rates range only from 52.58% to 60.04%.
- Some regions are small (e.g. Central Africa has 533 eligible shipments), so differences of a few points should not be over-interpreted.

### 11. Shipping-mode performance (`V_KPI_BY_SHIPPING_MODE`)
- Metrics 1 and 3–9 grouped by `SHIPPING_MODE`. Scheduled days are fixed per mode (0/1/2/4).
- Observed late rate:

  | Mode | Late rate |
  |---|---|
  | First Class | 100% (always 2 actual days against 1 scheduled) |
  | Second Class | 79.99% |
  | Same Day | 48.37% |
  | Standard Class | 39.85% |

- Descriptively, mode separates late from on-time far more than region does. This is an association in the sample data, not a cause.

### 12. Monthly trends (`V_KPI_BY_MONTH`)
- Metrics grouped by `ORDER_MONTH` (from `ORDER_TS`), plus `MARKETS_ACTIVE` and `MARKET_LIST`.
- ⚠️ **26 of 37 months contain a single market** (ADR-011). Month-over-month changes mostly reflect which market is in the data, not operational change. Present monthly figures together with their market list, and prefer comparisons across regions or modes over the full period.

## Interpretation rules (for people and for the agent)

1. **No causal claims.** Delivery status records *that* a shipment was late, not *why*. The data has no supplier, carrier, plant or root-cause fields. Never attribute delays to suppliers, quality issues or any other cause from these metrics.
2. **Public sample, not company data.** Always describe figures as coming from the DataCo public sample dataset.
3. **Grain first.** Count orders as orders and lines as lines, and compute delivery metrics on shipments.
4. **State exclusions.** Canceled shipments are excluded from delivery KPIs; canceled and fraud orders are excluded from revenue.
5. **Caveat trends** using the market-rotation note above.
