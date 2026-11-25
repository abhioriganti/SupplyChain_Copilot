-- =====================================================================================
-- GOLD KPI views. Each metric follows docs/metric_definitions.md exactly.
-- Delivery metrics: grain = shipment = FACT_ORDERS row; denominator = eligible shipments.
-- Revenue: SUM(FACT_ORDERS.NET_SALES) WHERE IS_REVENUE_ELIGIBLE (reconciled to line level in tests).
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/30_gold/02_kpi_views.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.GOLD;

CREATE OR REPLACE VIEW V_KPI_OVERALL
COMMENT = 'One row: governed headline KPIs over the full DataCo period (public sample data).'
AS
SELECT
    COUNT(*)                                                         AS DISTINCT_ORDERS,
    (SELECT COUNT(*) FROM FACT_ORDER_LINES)                          AS ORDER_LINES,
    SUM(IFF(IS_REVENUE_ELIGIBLE, NET_SALES, 0))                      AS TOTAL_REVENUE,
    COUNT_IF(IS_SHIPMENT_ELIGIBLE)                                   AS ELIGIBLE_SHIPMENTS,
    COUNT_IF(IS_LATE)                                                AS LATE_SHIPMENTS,
    COUNT_IF(IS_ON_TIME_OR_EARLY)                                    AS ON_TIME_OR_EARLY_SHIPMENTS,
    COUNT_IF(IS_LATE)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0)    AS LATE_DELIVERY_RATE,
    COUNT_IF(IS_ON_TIME_OR_EARLY)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0) AS ON_TIME_DELIVERY_RATE,
    AVG(IFF(IS_SHIPMENT_ELIGIBLE, DAYS_SHIPPING_ACTUAL::FLOAT, NULL))       AS AVG_ACTUAL_SHIPPING_DAYS,
    AVG(DAYS_LATE::FLOAT)                                         AS AVG_DAYS_LATE,
    MIN(ORDER_DATE)                                                  AS PERIOD_START,
    MAX(ORDER_DATE)                                                  AS PERIOD_END
FROM FACT_ORDERS;

CREATE OR REPLACE VIEW V_KPI_BY_REGION
COMMENT = 'Delivery KPIs and revenue per destination region (full period). Grain: one row per ORDER_REGION.'
AS
SELECT
    MARKET,
    ORDER_REGION,
    COUNT(*)                                                         AS DISTINCT_ORDERS,
    COUNT_IF(IS_SHIPMENT_ELIGIBLE)                                   AS ELIGIBLE_SHIPMENTS,
    COUNT_IF(IS_LATE)                                                AS LATE_SHIPMENTS,
    COUNT_IF(IS_LATE)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0)    AS LATE_DELIVERY_RATE,
    COUNT_IF(IS_ON_TIME_OR_EARLY)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0) AS ON_TIME_DELIVERY_RATE,
    AVG(IFF(IS_SHIPMENT_ELIGIBLE, DAYS_SHIPPING_ACTUAL::FLOAT, NULL))       AS AVG_ACTUAL_SHIPPING_DAYS,
    AVG(DAYS_LATE::FLOAT)                                         AS AVG_DAYS_LATE,
    SUM(IFF(IS_REVENUE_ELIGIBLE, NET_SALES, 0))                      AS TOTAL_REVENUE
FROM FACT_ORDERS
GROUP BY MARKET, ORDER_REGION;

CREATE OR REPLACE VIEW V_KPI_BY_SHIPPING_MODE
COMMENT = 'Delivery KPIs per shipping mode (full period). Scheduled days are fixed per mode.'
AS
SELECT
    SHIPPING_MODE,
    MIN(DAYS_SHIPPING_SCHEDULED)                                     AS SCHEDULED_DAYS,
    COUNT(*)                                                         AS DISTINCT_ORDERS,
    COUNT_IF(IS_SHIPMENT_ELIGIBLE)                                   AS ELIGIBLE_SHIPMENTS,
    COUNT_IF(IS_LATE)                                                AS LATE_SHIPMENTS,
    COUNT_IF(IS_LATE)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0)    AS LATE_DELIVERY_RATE,
    COUNT_IF(IS_ON_TIME_OR_EARLY)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0) AS ON_TIME_DELIVERY_RATE,
    AVG(IFF(IS_SHIPMENT_ELIGIBLE, DAYS_SHIPPING_ACTUAL::FLOAT, NULL))       AS AVG_ACTUAL_SHIPPING_DAYS,
    AVG(DAYS_LATE::FLOAT)                                         AS AVG_DAYS_LATE,
    SUM(IFF(IS_REVENUE_ELIGIBLE, NET_SALES, 0))                      AS TOTAL_REVENUE
FROM FACT_ORDERS
GROUP BY SHIPPING_MODE;

CREATE OR REPLACE VIEW V_KPI_BY_MONTH
COMMENT = 'Monthly KPIs by order month. CAVEAT: markets rotate over time (ADR-011); MARKETS_ACTIVE/MARKET_LIST expose which markets each month contains. Do not read month-over-month changes as operational trends.'
AS
SELECT
    ORDER_MONTH,
    COUNT(DISTINCT MARKET)                                           AS MARKETS_ACTIVE,
    LISTAGG(DISTINCT MARKET, ', ') WITHIN GROUP (ORDER BY MARKET)    AS MARKET_LIST,
    COUNT(*)                                                         AS DISTINCT_ORDERS,
    COUNT_IF(IS_SHIPMENT_ELIGIBLE)                                   AS ELIGIBLE_SHIPMENTS,
    COUNT_IF(IS_LATE)                                                AS LATE_SHIPMENTS,
    COUNT_IF(IS_LATE)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0)    AS LATE_DELIVERY_RATE,
    COUNT_IF(IS_ON_TIME_OR_EARLY)::FLOAT / NULLIF(COUNT_IF(IS_SHIPMENT_ELIGIBLE), 0) AS ON_TIME_DELIVERY_RATE,
    AVG(IFF(IS_SHIPMENT_ELIGIBLE, DAYS_SHIPPING_ACTUAL::FLOAT, NULL))       AS AVG_ACTUAL_SHIPPING_DAYS,
    AVG(DAYS_LATE::FLOAT)                                         AS AVG_DAYS_LATE,
    SUM(IFF(IS_REVENUE_ELIGIBLE, NET_SALES, 0))                      AS TOTAL_REVENUE
FROM FACT_ORDERS
GROUP BY ORDER_MONTH;
