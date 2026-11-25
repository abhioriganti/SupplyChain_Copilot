-- =====================================================================================
-- Phase 2 data-quality tests. ONE query; every row is a test; FAILURES must be 0.
-- Snowflake does not enforce PRIMARY KEY / FOREIGN KEY constraints, so they are tested here.
-- Run:  python scripts/run_sql_tests.py sql/tests/test_phase2_model.sql
-- =====================================================================================
WITH
bronze_latest AS (
    SELECT b.* FROM SCC_DB.BRONZE.DATACO_ORDER_LINES b
    WHERE b.LOAD_ID = (SELECT LOAD_ID FROM SCC_DB.BRONZE.LOAD_AUDIT WHERE STATUS = 'SUCCESS'
                       QUALIFY ROW_NUMBER() OVER (ORDER BY FINISHED_AT_UTC DESC) = 1)
),
s  AS (SELECT * FROM SCC_DB.SILVER.ORDER_LINES),
o  AS (SELECT * FROM SCC_DB.GOLD.FACT_ORDERS),
l  AS (SELECT * FROM SCC_DB.GOLD.FACT_ORDER_LINES),
p  AS (SELECT * FROM SCC_DB.GOLD.DIM_PRODUCTS),
r  AS (SELECT * FROM SCC_DB.GOLD.DIM_REGIONS)

-- ---------------- Bronze
SELECT 'bronze_load_audit_counts_match' AS TEST_NAME, 'BRONZE' AS LAYER,
       COUNT_IF(NOT (ROWS_IN_FILE = ROWS_LOADED AND ROWS_LOADED = ROWS_IN_TABLE)) AS FAILURES,
       'every audited load: file rows = loaded rows = table rows' AS DETAIL
FROM SCC_DB.BRONZE.LOAD_AUDIT WHERE STATUS = 'SUCCESS'
UNION ALL
SELECT 'bronze_latest_load_rowcount', 'BRONZE', ABS(COUNT(*) - 180519), 'latest load has 180,519 rows (Phase 1 count)' FROM bronze_latest

-- ---------------- Silver
UNION ALL SELECT 'silver_rowcount_equals_bronze_latest', 'SILVER',
       ABS((SELECT COUNT(*) FROM s) - (SELECT COUNT(*) FROM bronze_latest)), 'no rows lost or added'
UNION ALL SELECT 'silver_order_item_id_unique', 'SILVER', COUNT(*) - COUNT(DISTINCT ORDER_ITEM_ID), 'dedup worked' FROM s
UNION ALL SELECT 'silver_required_not_null', 'SILVER',
       COUNT_IF(ORDER_ITEM_ID IS NULL OR ORDER_ID IS NULL OR PRODUCT_ID IS NULL OR ORDER_TS IS NULL OR SHIPPING_TS IS NULL
             OR DAYS_SHIPPING_ACTUAL IS NULL OR DAYS_SHIPPING_SCHEDULED IS NULL OR DELIVERY_STATUS IS NULL
             OR SHIPPING_MODE IS NULL OR ORDER_REGION IS NULL OR MARKET IS NULL OR NET_SALES IS NULL OR QUANTITY IS NULL),
       'keys, dates, shipping fields, region, measures are never null' FROM s
UNION ALL SELECT 'silver_delay_equals_actual_minus_scheduled', 'SILVER',
       COUNT_IF(SHIPPING_DELAY_DAYS <> DAYS_SHIPPING_ACTUAL - DAYS_SHIPPING_SCHEDULED), 'derived delay' FROM s
UNION ALL SELECT 'silver_late_flag_vs_status', 'SILVER',
       COUNT_IF((LATE_DELIVERY_RISK = 1) <> (DELIVERY_STATUS = 'Late delivery')), 'flag = status' FROM s
UNION ALL SELECT 'silver_canceled_shipment_iff_canceled_or_fraud', 'SILVER',
       COUNT_IF(IS_CANCELED_SHIPMENT <> IS_CANCELED_OR_FRAUD_ORDER), 'two cancellation definitions coincide' FROM s
UNION ALL SELECT 'silver_order_month_matches_ts', 'SILVER',
       COUNT_IF(ORDER_MONTH <> DATE_TRUNC('MONTH', ORDER_TS)::DATE OR ORDER_DATE <> TO_DATE(ORDER_TS)), 'date derivations' FROM s
UNION ALL SELECT 'silver_order_attributes_constant_within_order', 'SILVER', COUNT(*),
       'orders with >1 distinct value for any shipping/order attribute (justifies order-grain shipments)'
FROM (SELECT ORDER_ID FROM s GROUP BY ORDER_ID
      HAVING COUNT(DISTINCT ORDER_TS) > 1 OR COUNT(DISTINCT SHIPPING_TS) > 1 OR COUNT(DISTINCT DAYS_SHIPPING_ACTUAL) > 1
          OR COUNT(DISTINCT DAYS_SHIPPING_SCHEDULED) > 1 OR COUNT(DISTINCT DELIVERY_STATUS) > 1 OR COUNT(DISTINCT SHIPPING_MODE) > 1
          OR COUNT(DISTINCT ORDER_STATUS) > 1 OR COUNT(DISTINCT ORDER_REGION) > 1 OR COUNT(DISTINCT CUSTOMER_ID) > 1
          OR COUNT(DISTINCT ORDER_CITY) > 1 OR COUNT(DISTINCT ORDER_COUNTRY) > 1)

-- ---------------- Gold: keys and relationships (constraints are not enforced by Snowflake)
UNION ALL SELECT 'dim_products_pk_unique', 'GOLD', COUNT(*) - COUNT(DISTINCT PRODUCT_ID), 'PK' FROM p
UNION ALL SELECT 'dim_regions_pk_unique', 'GOLD', COUNT(*) - COUNT(DISTINCT ORDER_REGION), 'PK' FROM r
UNION ALL SELECT 'dim_regions_one_market_per_region', 'GOLD', COUNT(*), 'regions mapped to >1 market in Silver'
FROM (SELECT ORDER_REGION FROM s GROUP BY ORDER_REGION HAVING COUNT(DISTINCT MARKET) > 1)
UNION ALL SELECT 'dim_products_attributes_constant', 'GOLD', COUNT(*), 'products with >1 name/category/department in Silver'
FROM (SELECT PRODUCT_ID FROM s GROUP BY PRODUCT_ID
      HAVING COUNT(DISTINCT PRODUCT_NAME) > 1 OR COUNT(DISTINCT CATEGORY_ID) > 1 OR COUNT(DISTINCT DEPARTMENT_ID) > 1)
UNION ALL SELECT 'fact_orders_pk_unique', 'GOLD', COUNT(*) - COUNT(DISTINCT ORDER_ID), 'PK' FROM o
UNION ALL SELECT 'fact_orders_count_equals_distinct_silver_orders', 'GOLD',
       ABS((SELECT COUNT(*) FROM o) - (SELECT COUNT(DISTINCT ORDER_ID) FROM s)), 'one row per order, none lost'
UNION ALL SELECT 'fact_order_lines_pk_unique', 'GOLD', COUNT(*) - COUNT(DISTINCT ORDER_ITEM_ID), 'PK' FROM l
UNION ALL SELECT 'fact_order_lines_count_equals_silver', 'GOLD',
       ABS((SELECT COUNT(*) FROM l) - (SELECT COUNT(*) FROM s)), 'no line duplication or loss'
UNION ALL SELECT 'fk_lines_to_orders', 'GOLD', COUNT(*), 'lines whose ORDER_ID is missing from FACT_ORDERS'
FROM l LEFT JOIN o ON l.ORDER_ID = o.ORDER_ID WHERE o.ORDER_ID IS NULL
UNION ALL SELECT 'fk_lines_to_products', 'GOLD', COUNT(*), 'lines whose PRODUCT_ID is missing from DIM_PRODUCTS'
FROM l LEFT JOIN p ON l.PRODUCT_ID = p.PRODUCT_ID WHERE p.PRODUCT_ID IS NULL
UNION ALL SELECT 'fk_orders_to_regions', 'GOLD', COUNT(*), 'orders whose region is missing from DIM_REGIONS'
FROM o LEFT JOIN r ON o.ORDER_REGION = r.ORDER_REGION WHERE r.ORDER_REGION IS NULL
UNION ALL SELECT 'orders_market_matches_region_dim', 'GOLD', COUNT(*), 'FACT_ORDERS.MARKET agrees with DIM_REGIONS'
FROM o JOIN r ON o.ORDER_REGION = r.ORDER_REGION WHERE o.MARKET <> r.MARKET
UNION ALL SELECT 'orders_without_lines', 'GOLD', COUNT(*), 'every order has at least one line'
FROM o LEFT JOIN l ON o.ORDER_ID = l.ORDER_ID WHERE l.ORDER_ID IS NULL

-- ---------------- Gold: no double counting between grains
UNION ALL SELECT 'line_count_sums_to_lines', 'GOLD', ABS((SELECT SUM(LINE_COUNT) FROM o) - (SELECT COUNT(*) FROM l)),
       'SUM(FACT_ORDERS.LINE_COUNT) = COUNT(FACT_ORDER_LINES)'
UNION ALL SELECT 'per_order_line_count_matches', 'GOLD', COUNT(*), 'orders whose LINE_COUNT differs from actual lines'
FROM o JOIN (SELECT ORDER_ID, COUNT(*) N FROM l GROUP BY ORDER_ID) x ON o.ORDER_ID = x.ORDER_ID WHERE o.LINE_COUNT <> x.N
UNION ALL SELECT 'revenue_orders_equals_lines', 'GOLD',
       IFF(ABS((SELECT SUM(IFF(IS_REVENUE_ELIGIBLE, NET_SALES, 0)) FROM o)
             - (SELECT SUM(IFF(IS_REVENUE_ELIGIBLE, NET_SALES, 0)) FROM l)) <= 0.01, 0, 1),
       'eligible revenue identical at order and line grain (|diff| <= 0.01)'
UNION ALL SELECT 'net_sales_total_equals_bronze', 'GOLD',
       IFF(ABS((SELECT SUM(NET_SALES) FROM l) - (SELECT SUM(NET_SALES) FROM bronze_latest)) <= 0.01, 0, 1),
       'all-status net sales unchanged from Bronze'
UNION ALL SELECT 'revenue_eligibility_consistent_across_grains', 'GOLD', COUNT(*), 'line flag = order flag'
FROM l JOIN o ON l.ORDER_ID = o.ORDER_ID WHERE l.IS_REVENUE_ELIGIBLE <> o.IS_REVENUE_ELIGIBLE

-- ---------------- Gold: metric logic
UNION ALL SELECT 'late_implies_eligible', 'GOLD', COUNT_IF(IS_LATE AND NOT IS_SHIPMENT_ELIGIBLE), 'late only counted for eligible shipments' FROM o
UNION ALL SELECT 'eligible_partitions_late_and_on_time', 'GOLD',
       COUNT_IF(IS_SHIPMENT_ELIGIBLE <> (IS_LATE OR IS_ON_TIME_OR_EARLY) OR (IS_LATE AND IS_ON_TIME_OR_EARLY)),
       'every eligible shipment is exactly one of late / on-time-or-early; canceled is neither' FROM o
UNION ALL SELECT 'late_iff_actual_gt_scheduled_for_eligible', 'GOLD',
       COUNT_IF(IS_SHIPMENT_ELIGIBLE AND IS_LATE <> (DAYS_SHIPPING_ACTUAL > DAYS_SHIPPING_SCHEDULED)),
       'status-based and day-based lateness agree on eligible shipments' FROM o
UNION ALL SELECT 'days_late_positive_and_only_when_late', 'GOLD',
       COUNT_IF((IS_LATE AND (DAYS_LATE IS NULL OR DAYS_LATE <= 0)) OR (NOT IS_LATE AND DAYS_LATE IS NOT NULL)),
       'DAYS_LATE > 0 when late, NULL otherwise' FROM o
UNION ALL SELECT 'shipment_eligibility_equals_revenue_eligibility', 'GOLD',
       COUNT_IF(IS_SHIPMENT_ELIGIBLE <> IS_REVENUE_ELIGIBLE), 'both exclude the same canceled/fraud orders (documented coincidence in this source)' FROM o
UNION ALL SELECT 'kpi_rates_sum_to_one', 'GOLD',
       COUNT_IF(ABS(LATE_DELIVERY_RATE + ON_TIME_DELIVERY_RATE - 1) > 1e-9), 'late + on-time = 1 per region'
FROM SCC_DB.GOLD.V_KPI_BY_REGION
UNION ALL SELECT 'kpi_region_orders_sum_to_total', 'GOLD',
       ABS((SELECT SUM(DISTINCT_ORDERS) FROM SCC_DB.GOLD.V_KPI_BY_REGION) - (SELECT COUNT(*) FROM o)),
       'region breakdown covers every order exactly once'
UNION ALL SELECT 'kpi_month_orders_sum_to_total', 'GOLD',
       ABS((SELECT SUM(DISTINCT_ORDERS) FROM SCC_DB.GOLD.V_KPI_BY_MONTH) - (SELECT COUNT(*) FROM o)),
       'month breakdown covers every order exactly once'
UNION ALL SELECT 'kpi_mode_orders_sum_to_total', 'GOLD',
       ABS((SELECT SUM(DISTINCT_ORDERS) FROM SCC_DB.GOLD.V_KPI_BY_SHIPPING_MODE) - (SELECT COUNT(*) FROM o)),
       'shipping-mode breakdown covers every order exactly once'

-- ---------------- Governance
UNION ALL SELECT 'no_pii_columns_in_project_tables', 'ALL', COUNT(*),
       'no column named like email/password/fname/lname/street/zipcode/latitude/longitude'
FROM SCC_DB.INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA IN ('BRONZE', 'SILVER', 'GOLD')
  AND REGEXP_LIKE(COLUMN_NAME, '.*(EMAIL|PASSWORD|FNAME|LNAME|STREET|ZIPCODE|LATITUDE|LONGITUDE).*')
;
