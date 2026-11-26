# Business terminology dictionary

**Domain:** Supply Chain Delivery Performance · **Source:** DataCo public sample (retail/e-commerce, 2015–2018); **not Worthington data**
**Semantic view:** `SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV`

This dictionary maps the words people use to the single governed object each one resolves to. Synonyms are registered in the semantic view, so Cortex Analyst resolves them the same way. Full formulas are in [metric_definitions.md](metric_definitions.md).

## Metrics

| Business term (and synonyms) | Governed metric | Meaning in one line |
|---|---|---|
| Orders, number of orders, unique orders, order count, total shipments | `orders.total_orders` | Distinct orders, all statuses. One order is one shipment. |
| Order lines, line items, order items count | `order_lines.order_line_count` | Products within orders. **Not** the number of orders. |
| Eligible shipments, delivered shipments, non-canceled shipments | `orders.eligible_shipments` | Shipments that weren't canceled. The denominator of every delivery rate. |
| Late shipments, late orders, late deliveries, delayed shipments | `orders.late_shipments` | Eligible shipments delivered after the scheduled days |
| On-time shipments, on time or early | `orders.on_time_shipments` | Eligible shipments delivered on schedule or early |
| Canceled shipments, cancelled orders | `orders.canceled_shipments` | Order status CANCELED or SUSPECTED_FRAUD. Excluded from rates. |
| **Late-delivery rate**, late rate, percent late, delay rate, late shipment rate | `orders.late_delivery_rate` | **late shipments ÷ eligible shipments** (a fraction from 0 to 1) |
| **On-time delivery rate**, OTD, on-time rate, on-time performance | `orders.on_time_delivery_rate` | on-time-or-early ÷ eligible shipments, which equals 1 − late rate |
| Average shipping duration, average shipping time, average days to ship | `orders.avg_actual_shipping_days` | Average actual days over eligible shipments |
| Average days late, average delay, average positive delay | `orders.avg_days_late` | Average days beyond schedule, over **late shipments only** |
| Revenue, net sales, sales, sales amount, turnover | `order_lines.total_revenue` | Net sales after discount, excluding canceled and fraud orders |
| Gross sales before discount | `order_lines.gross_sales_before_discount` | List-price sales. Use "revenue" for revenue. |
| Units, quantity sold | `order_lines.units_sold` | Units on revenue-eligible orders |
| Profit | `order_lines.total_profit` | Line profit on revenue-eligible orders (can be negative) |

## Dimensions

| Business term (and synonyms) | Governed dimension | Notes |
|---|---|---|
| Region, destination region, sales region | `regions.order_region` | 23 destination regions. Defined **only** on the region dimension, so there's one meaning. |
| Market, continent, territory | `regions.market` | Africa, Europe, LATAM, Pacific Asia, USCA |
| Shipping mode, shipping method, service level, shipping class | `orders.shipping_mode` | Standard, Second, First Class, Same Day |
| Scheduled shipping days | `orders.scheduled_shipping_days` | Fixed by mode: 0, 1, 2 or 4 |
| Delivery status, shipment status, delivery outcome | `orders.delivery_status` | Advance, On time, Late, Canceled |
| Order status | `orders.order_status` | Commercial status (COMPLETE, PENDING, …) |
| Month | `orders.order_month` | ⚠️ Markets rotate by month (see below) |
| Year, date | `orders.order_year`, `orders.order_date` | |
| Segment | `orders.customer_segment` | Consumer, Corporate, Home Office |
| Country, state, city | `orders.destination_country`, `orders.destination_state`, `orders.destination_city` | Destination, not customer address |
| Product, category, department | `products.product_name`, `products.category_name`, `products.department_name` | Retail products, not manufactured parts |

## Terms that are ambiguous, and how they're resolved

| Term | Possible meanings | Governed resolution |
|---|---|---|
| "Orders" vs "lines" | Order IDs, or rows in the line table | `total_orders` counts distinct orders; `order_line_count` counts lines. Counting rows as orders is wrong (180,519 vs 65,752). |
| "On time" | Exactly on schedule, or on schedule or early | **On schedule or early.** A strict "exactly on time" metric would need a separate, differently named metric. |
| "Late rate" denominator | All orders, or non-canceled shipments | **Non-canceled shipments.** Including canceled ones understates the rate by 2.49 pp. |
| "Average delay" | Average over all shipments (with zeros and negatives), or over late shipments only | **Late shipments only** (`avg_days_late`) |
| "Sales" / "revenue" | Gross or net; with or without canceled orders | **Net, excluding canceled and fraud orders** |
| "Region" | Destination region, customer region or market | **Destination `order_region`.** Market is a separate term. |
| "Late rate by category" | Share of lines late, or share of orders containing the category that were late | **Orders containing that category**, counted once per category (deduplicated). Category values **don't add up** to the total. |
| "Trend" / "month over month" | An operational change over time | ⚠️ 26 of 37 months contain a single market. Monthly changes mostly reflect market mix, so they're shown by month **and** market. |
| "Cause of delay", "supplier", "carrier" | — | **Not in the data.** The assistant must say so and must not infer causes. |
