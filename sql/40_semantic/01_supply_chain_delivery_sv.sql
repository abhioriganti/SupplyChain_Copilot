-- =====================================================================================
-- Semantic view: Supply Chain Delivery Performance (DataCo public sample data).
-- Single governed home for every metric definition used by Cortex Analyst and the agent.
-- Definitions match docs/metric_definitions.md and GOLD.V_KPI_* (reconciled in Phase 3 tests).
-- Syntax checked against docs.snowflake.com (create-semantic-view, views-semantic/sql), 2026-11-25.
-- Run as SCC_DEV_ROLE:
--   python scripts/run_sql_file.py sql/40_semantic/01_supply_chain_delivery_sv.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.AI;

CREATE OR REPLACE SEMANTIC VIEW SUPPLY_CHAIN_DELIVERY_SV

  TABLES (
    orders AS SCC_DB.GOLD.FACT_ORDERS
      PRIMARY KEY (ORDER_ID)
      WITH SYNONYMS = ('shipments', 'customer orders')
      COMMENT = 'One row per order. Each order ships as exactly one shipment, so this is also the shipment table. All delivery metrics are computed here.',
    order_lines AS SCC_DB.GOLD.FACT_ORDER_LINES
      PRIMARY KEY (ORDER_ITEM_ID)
      WITH SYNONYMS = ('order items', 'line items')
      COMMENT = 'One row per order line (product within an order). Revenue and units are computed here.',
    products AS SCC_DB.GOLD.DIM_PRODUCTS
      PRIMARY KEY (PRODUCT_ID)
      WITH SYNONYMS = ('items', 'catalog')
      COMMENT = 'Retail products in the DataCo sample (not manufactured parts).',
    regions AS SCC_DB.GOLD.DIM_REGIONS
      PRIMARY KEY (ORDER_REGION)
      WITH SYNONYMS = ('destinations', 'geographies')
      COMMENT = 'Destination regions; each region belongs to exactly one market.'
  )

  RELATIONSHIPS (
    order_lines_to_orders   AS order_lines (ORDER_ID)   REFERENCES orders,
    order_lines_to_products AS order_lines (PRODUCT_ID) REFERENCES products,
    orders_to_regions       AS orders (ORDER_REGION)    REFERENCES regions
  )

  FACTS (
    orders.actual_shipping_days AS DAYS_SHIPPING_ACTUAL
      WITH SYNONYMS = ('days to ship', 'shipping duration', 'delivery time')
      COMMENT = 'Actual shipping days for the shipment (whole days).',
    orders.scheduled_shipping_days_fact AS DAYS_SHIPPING_SCHEDULED
      COMMENT = 'Scheduled shipping days (fixed by shipping mode: Same Day 0, First Class 1, Second Class 2, Standard Class 4).',
    orders.shipping_delay_days AS SHIPPING_DELAY_DAYS
      COMMENT = 'Actual minus scheduled days. Negative means early.',
    orders.days_late AS DAYS_LATE
      COMMENT = 'Days beyond schedule for late shipments only; NULL for on-time, early or canceled shipments.',
    order_lines.line_net_sales AS NET_SALES
      COMMENT = 'Line sales after discount.',
    order_lines.line_quantity AS QUANTITY
      COMMENT = 'Units on the order line.'
  )

  DIMENSIONS (
    orders.order_id AS ORDER_ID
      COMMENT = 'Order identifier.',
    orders.order_date AS ORDER_DATE
      WITH SYNONYMS = ('date', 'purchase date')
      COMMENT = 'Date the order was placed (2015-01-01 to 2018-01-31).',
    orders.order_month AS ORDER_MONTH
      WITH SYNONYMS = ('month')
      COMMENT = 'First day of the order month. Markets rotate over time in this dataset, so month-over-month changes mostly reflect which market is present.',
    orders.order_quarter AS DATE_TRUNC('QUARTER', ORDER_DATE)
      WITH SYNONYMS = ('quarter', 'fiscal quarter', 'calendar quarter')
      COMMENT = 'First day of the order quarter. Added in Phase 8: without it, quarterly questions made Analyst fall back to raw-table SQL, which the read-only runtime role correctly denied.',
    orders.order_week AS DATE_TRUNC('WEEK', ORDER_DATE)
      WITH SYNONYMS = ('week', 'weekly', 'order week')
      COMMENT = 'First day of the order week (Monday under the default WEEK_START = 0). Added in the backlog pass so weekly questions stay on the governed view.',
    orders.order_day_of_week AS DAYNAME(ORDER_DATE)
      WITH SYNONYMS = ('weekday', 'day of week', 'day of the week')
      COMMENT = 'Three-letter weekday the order was placed (Mon to Sun).',
    orders.order_year AS YEAR(ORDER_DATE)
      WITH SYNONYMS = ('year')
      COMMENT = 'Calendar year of the order.',
    orders.shipping_mode AS SHIPPING_MODE
      WITH SYNONYMS = ('shipping method', 'ship mode', 'service level', 'shipping class')
      COMMENT = 'Shipping service level: Standard Class, Second Class, First Class, Same Day.',
    orders.scheduled_shipping_days AS DAYS_SHIPPING_SCHEDULED
      COMMENT = 'Scheduled days for the shipping mode.',
    orders.delivery_status AS DELIVERY_STATUS
      WITH SYNONYMS = ('shipment status', 'delivery outcome')
      COMMENT = 'Advance shipping, Shipping on time, Late delivery, Shipping canceled.',
    orders.order_status AS ORDER_STATUS
      COMMENT = 'Commercial order status, e.g. COMPLETE, PENDING, CANCELED, SUSPECTED_FRAUD.',
    orders.customer_segment AS CUSTOMER_SEGMENT
      WITH SYNONYMS = ('segment')
      COMMENT = 'Consumer, Corporate, Home Office.',
    orders.payment_type AS PAYMENT_TYPE
      COMMENT = 'DEBIT, TRANSFER, PAYMENT, CASH.',
    orders.destination_country AS ORDER_COUNTRY
      WITH SYNONYMS = ('country')
      COMMENT = 'Destination country of the order (Spanish-language names in the source).',
    orders.destination_state AS ORDER_STATE
      WITH SYNONYMS = ('state', 'province')
      COMMENT = 'Destination state or province.',
    orders.destination_city AS ORDER_CITY
      WITH SYNONYMS = ('city')
      COMMENT = 'Destination city.',
    orders.is_late AS IS_LATE
      COMMENT = 'TRUE when an eligible shipment was delivered late. Canceled shipments are FALSE.',
    orders.is_shipment_eligible AS IS_SHIPMENT_ELIGIBLE
      COMMENT = 'FALSE for canceled shipments, which are excluded from delivery metrics.',
    regions.order_region AS ORDER_REGION
      WITH SYNONYMS = ('region', 'destination region', 'sales region')
      COMMENT = 'Destination region (23), e.g. Western Europe, Central America, South Asia.',
    regions.market AS MARKET
      WITH SYNONYMS = ('market region', 'continent', 'territory')
      COMMENT = 'Destination market: Africa, Europe, LATAM, Pacific Asia, USCA.',
    products.product_name AS PRODUCT_NAME
      WITH SYNONYMS = ('product')
      COMMENT = 'Product name.',
    products.category_name AS CATEGORY_NAME
      WITH SYNONYMS = ('product category', 'category')
      COMMENT = 'Product category name. Not unique: Electronics exists under two category ids.',
    products.category_id AS CATEGORY_ID
      COMMENT = 'Product category key.',
    products.department_name AS DEPARTMENT_NAME
      WITH SYNONYMS = ('department')
      COMMENT = 'Store department of the product.'
  )

  METRICS (
    -- ---- order / shipment grain (delivery performance)
    orders.total_orders AS COUNT(orders.ORDER_ID)
      WITH SYNONYMS = ('number of orders', 'order count', 'unique orders', 'distinct orders', 'total shipments')
      COMMENT = 'Distinct orders (= shipments), all statuses. Never count order lines as orders.',
    orders.eligible_shipments AS SUM(IFF(orders.IS_SHIPMENT_ELIGIBLE, 1, 0))
      WITH SYNONYMS = ('delivered shipments', 'non-canceled shipments')
      COMMENT = 'Shipments that were not canceled. Denominator of every delivery rate.',
    orders.late_shipments AS SUM(IFF(orders.IS_LATE, 1, 0))
      WITH SYNONYMS = ('late orders', 'late deliveries', 'delayed shipments')
      COMMENT = 'Eligible shipments delivered after the scheduled number of days.',
    orders.on_time_shipments AS SUM(IFF(orders.IS_ON_TIME_OR_EARLY, 1, 0))
      WITH SYNONYMS = ('on-time deliveries', 'on time or early shipments')
      COMMENT = 'Eligible shipments delivered on schedule or early.',
    orders.canceled_shipments AS SUM(IFF(orders.IS_SHIPMENT_ELIGIBLE, 0, 1))
      WITH SYNONYMS = ('cancelled shipments', 'canceled orders')
      COMMENT = 'Shipments canceled (order status CANCELED or SUSPECTED_FRAUD). Excluded from delivery rates.',
    orders.late_delivery_rate AS orders.late_shipments::FLOAT / NULLIF(orders.eligible_shipments, 0)
      WITH SYNONYMS = ('late rate', 'late delivery percentage', 'percent late', 'delay rate', 'late shipment rate', 'delayed shipment rate')
      COMMENT = 'GOVERNED: late_shipments / eligible_shipments, per shipment, canceled excluded. Fraction between 0 and 1.',
    orders.on_time_delivery_rate AS orders.on_time_shipments::FLOAT / NULLIF(orders.eligible_shipments, 0)
      WITH SYNONYMS = ('on-time rate', 'on time performance', 'OTD', 'on-time delivery percentage')
      COMMENT = 'GOVERNED: on_time_shipments / eligible_shipments (on time includes early). Always 1 - late_delivery_rate.',
    orders.avg_actual_shipping_days AS AVG(IFF(orders.IS_SHIPMENT_ELIGIBLE, orders.DAYS_SHIPPING_ACTUAL::FLOAT, NULL))
      WITH SYNONYMS = ('average shipping duration', 'average shipping time', 'average days to ship', 'average delivery time')
      COMMENT = 'Average actual shipping days over eligible (non-canceled) shipments.',
    orders.avg_days_late AS AVG(orders.DAYS_LATE::FLOAT)
      WITH SYNONYMS = ('average delay', 'average days late', 'average positive delay')
      COMMENT = 'Average days beyond schedule, over late shipments only.',
    orders.revenue_orders AS SUM(IFF(orders.IS_REVENUE_ELIGIBLE, 1, 0))
      WITH SYNONYMS = ('revenue-eligible orders', 'billable orders')
      COMMENT = 'Orders that count toward revenue (excludes CANCELED and SUSPECTED_FRAUD). Denominator of avg_order_value.',
    orders.avg_order_value AS AVG(IFF(orders.IS_REVENUE_ELIGIBLE, orders.NET_SALES, NULL))
      WITH SYNONYMS = ('AOV', 'average order value', 'average order size', 'revenue per order')
      COMMENT = 'GOVERNED: average net sales per revenue-eligible order. Grouped by product, category or department it averages the full value of orders containing that item, not the item share.',
    orders.customer_count AS COUNT(DISTINCT orders.CUSTOMER_ID)
      WITH SYNONYMS = ('number of customers', 'unique customers', 'distinct customers', 'customers')
      COMMENT = 'Distinct pseudonymous customer ids placing orders (all statuses). Count only; no customer details exist.',

    -- ---- order-line grain (revenue)
    order_lines.order_line_count AS COUNT(order_lines.ORDER_ITEM_ID)
      WITH SYNONYMS = ('number of order lines', 'line count', 'order items count')
      COMMENT = 'Order lines (products within orders). Not the number of orders.',
    order_lines.total_revenue AS SUM(IFF(order_lines.IS_REVENUE_ELIGIBLE, order_lines.NET_SALES, 0))
      WITH SYNONYMS = ('revenue', 'net sales', 'sales', 'sales amount', 'turnover')
      COMMENT = 'GOVERNED: net sales after discount, excluding CANCELED and SUSPECTED_FRAUD orders. Currency as stored in the source.',
    order_lines.units_sold AS SUM(IFF(order_lines.IS_REVENUE_ELIGIBLE, order_lines.QUANTITY, 0))
      WITH SYNONYMS = ('units', 'quantity sold')
      COMMENT = 'Units on revenue-eligible orders.',
    order_lines.gross_sales_before_discount AS SUM(IFF(order_lines.IS_REVENUE_ELIGIBLE, order_lines.GROSS_SALES, 0))
      COMMENT = 'List-price sales before discount on revenue-eligible orders. Use total_revenue for revenue.',
    order_lines.total_profit AS SUM(IFF(order_lines.IS_REVENUE_ELIGIBLE, order_lines.LINE_PROFIT, 0))
      WITH SYNONYMS = ('profit')
      COMMENT = 'Line profit on revenue-eligible orders (can be negative).',
    order_lines.profit_margin AS order_lines.total_profit / NULLIF(order_lines.total_revenue, 0)
      WITH SYNONYMS = ('margin', 'profit margin', 'profitability', 'margin percentage')
      COMMENT = 'GOVERNED: total_profit / total_revenue on revenue-eligible orders. Fraction between 0 and 1 (can be negative).',
    order_lines.total_discount AS SUM(IFF(order_lines.IS_REVENUE_ELIGIBLE, order_lines.DISCOUNT_AMOUNT, 0))
      WITH SYNONYMS = ('discounts', 'discount amount', 'total discounts given')
      COMMENT = 'Discount given on revenue-eligible orders, summed from the source discount field. Gross sales minus total_revenue differs by about 44 in total because the source rounds each field separately (at most 1 cent per line).',
    order_lines.discount_rate AS order_lines.total_discount / NULLIF(order_lines.gross_sales_before_discount, 0)
      WITH SYNONYMS = ('average discount', 'discount percentage', 'effective discount rate')
      COMMENT = 'GOVERNED: total_discount / gross_sales_before_discount. Fraction between 0 and 1.'
  )

  COMMENT = 'Supply Chain Delivery Performance - governed semantic layer over the DataCo PUBLIC SAMPLE dataset (retail/e-commerce, 2015-2018). Not Worthington data.'

  AI_SQL_GENERATION 'The data is the public DataCo sample dataset (retail and e-commerce orders, January 2015 to January 2018). It is not company data. Always use the defined metrics (total_orders, eligible_shipments, late_shipments, late_delivery_rate, on_time_delivery_rate, avg_actual_shipping_days, avg_days_late, total_revenue, total_profit, profit_margin, total_discount, discount_rate, avg_order_value, customer_count, order_line_count) instead of recomputing them from columns. For margin or profitability questions use profit_margin; never divide total_profit by total_revenue yourself. Use order_week for weekly questions and order_quarter for quarterly ones. Delivery metrics are per shipment, where one order equals one shipment, and canceled shipments are excluded. Count orders with total_orders, never by counting order lines. Use regions.order_region for region and regions.market for market. When results are grouped by month, also include market, because the dataset contains different markets in different months. When an order-level metric is grouped by product, category or department, each order is counted once in every category it contains, so the category values do not add up to the overall total. Return rates as fractions between 0 and 1. Order ranked results explicitly.'

  AI_QUESTION_CATEGORIZATION 'If a question asks about suppliers, supplier quality, plants, manufacturing, carriers, inventory, or the cause of delays, explain that this dataset contains no such fields and offer the closest available delivery metric. If a question asks for customer names, emails, or addresses, explain that personal data was removed.'

  AI_VERIFIED_QUERIES (
    late_rate_by_region AS (
      QUESTION 'Which regions have the highest late-delivery rate?'
      ONBOARDING_QUESTION TRUE
      VERIFIED_BY '(STEWARD = supplychain_copilot_maintainer)'
      SQL 'SELECT * FROM SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV DIMENSIONS regions.market, regions.order_region METRICS orders.late_delivery_rate, orders.eligible_shipments, orders.late_shipments) ORDER BY late_delivery_rate DESC'
    ),
    on_time_by_shipping_mode AS (
      QUESTION 'What is the on-time delivery rate by shipping mode?'
      ONBOARDING_QUESTION TRUE
      VERIFIED_BY '(STEWARD = supplychain_copilot_maintainer)'
      SQL 'SELECT * FROM SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV DIMENSIONS orders.shipping_mode, orders.scheduled_shipping_days METRICS orders.on_time_delivery_rate, orders.late_delivery_rate, orders.avg_actual_shipping_days, orders.eligible_shipments) ORDER BY on_time_delivery_rate DESC'
    ),
    headline_delivery_kpis AS (
      QUESTION 'What are the overall delivery KPIs?'
      ONBOARDING_QUESTION TRUE
      VERIFIED_BY '(STEWARD = supplychain_copilot_maintainer)'
      SQL 'SELECT * FROM SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV METRICS orders.total_orders, orders.eligible_shipments, orders.late_shipments, orders.late_delivery_rate, orders.on_time_delivery_rate, orders.avg_actual_shipping_days, orders.avg_days_late, order_lines.total_revenue)'
    ),
    profit_margin_by_market AS (
      QUESTION 'What is the profit margin by market?'
      VERIFIED_BY '(STEWARD = supplychain_copilot_maintainer)'
      SQL 'SELECT * FROM SEMANTIC_VIEW(SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV DIMENSIONS regions.market METRICS order_lines.profit_margin, order_lines.total_profit, order_lines.total_revenue) ORDER BY profit_margin DESC'
    )
  );

-- CREATE OR REPLACE drops grants: re-grant the read-only runtime role (Phase 6/8).
GRANT SELECT ON SEMANTIC VIEW SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV TO ROLE SCC_APP_ROLE;
