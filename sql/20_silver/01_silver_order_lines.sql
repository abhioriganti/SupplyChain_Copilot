-- =====================================================================================
-- SILVER.ORDER_LINES: one row per order line from the LATEST successful Bronze load.
--   * deduplication: one row per ORDER_ITEM_ID (first source row wins; Phase 1 found 0 dups)
--   * types already enforced in Bronze DDL; dates derived here
--   * validated shipping calculations (delay = actual - scheduled; flags from delivery status)
--   * null handling: no imputation. Required columns are asserted NOT NULL by sql/tests.
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/20_silver/01_silver_order_lines.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.SILVER;

CREATE OR REPLACE TABLE ORDER_LINES
COMMENT = 'DataCo order lines (public sample, not Worthington data). Grain: one row per ORDER_ITEM_ID. Latest successful Bronze load only.'
AS
WITH latest_load AS (
    SELECT LOAD_ID
    FROM SCC_DB.BRONZE.LOAD_AUDIT
    WHERE STATUS = 'SUCCESS' AND TARGET_TABLE = 'SCC_DB.BRONZE.DATACO_ORDER_LINES'
    QUALIFY ROW_NUMBER() OVER (ORDER BY FINISHED_AT_UTC DESC) = 1
)
SELECT
    b.ORDER_ITEM_ID,
    b.ORDER_ID,
    b.CUSTOMER_ID,
    b.PRODUCT_ID,
    b.PAYMENT_TYPE,
    b.ORDER_STATUS,
    b.ORDER_TS,
    TO_DATE(b.ORDER_TS)                                       AS ORDER_DATE,
    DATE_TRUNC('MONTH', b.ORDER_TS)::DATE                     AS ORDER_MONTH,
    b.SHIPPING_TS,
    b.DAYS_SHIPPING_ACTUAL,
    b.DAYS_SHIPPING_SCHEDULED,
    b.DAYS_SHIPPING_ACTUAL - b.DAYS_SHIPPING_SCHEDULED        AS SHIPPING_DELAY_DAYS,
    b.DELIVERY_STATUS,
    b.LATE_DELIVERY_RISK,
    (b.DELIVERY_STATUS = 'Shipping canceled')                 AS IS_CANCELED_SHIPMENT,
    (b.ORDER_STATUS IN ('CANCELED', 'SUSPECTED_FRAUD'))       AS IS_CANCELED_OR_FRAUD_ORDER,
    b.SHIPPING_MODE,
    b.CUSTOMER_SEGMENT,
    b.MARKET,
    b.ORDER_REGION,
    b.ORDER_COUNTRY,
    b.ORDER_STATE,
    b.ORDER_CITY,
    b.PRODUCT_NAME,
    b.CATEGORY_ID,
    b.CATEGORY_NAME,
    b.DEPARTMENT_ID,
    b.DEPARTMENT_NAME,
    b.QUANTITY,
    b.UNIT_PRICE,
    b.GROSS_SALES,
    b.DISCOUNT_AMOUNT,
    b.DISCOUNT_RATE,
    b.NET_SALES,
    b.LINE_PROFIT,
    b.PROFIT_RATIO,
    b.DQ_SHIP_TS_MISMATCH,
    b.SOURCE_FILE,
    b.SOURCE_ROW_NUMBER,
    b.SOURCE_SHA256,
    b.LOAD_ID,
    b.INGESTED_AT_UTC
FROM SCC_DB.BRONZE.DATACO_ORDER_LINES b
JOIN latest_load l ON b.LOAD_ID = l.LOAD_ID
QUALIFY ROW_NUMBER() OVER (PARTITION BY b.ORDER_ITEM_ID ORDER BY b.SOURCE_ROW_NUMBER) = 1;

-- Record how many rows deduplication removed for this load (expected 0; kept for monitoring).
CREATE TABLE IF NOT EXISTS SILVER_BUILD_LOG (
    BUILT_AT_UTC TIMESTAMP_NTZ, LOAD_ID VARCHAR, BRONZE_ROWS NUMBER, SILVER_ROWS NUMBER, DUPLICATES_REMOVED NUMBER
);
INSERT INTO SILVER_BUILD_LOG
SELECT
    SYSDATE(),
    s.LOAD_ID,
    (SELECT COUNT(*) FROM SCC_DB.BRONZE.DATACO_ORDER_LINES WHERE LOAD_ID = s.LOAD_ID),
    COUNT(*),
    (SELECT COUNT(*) FROM SCC_DB.BRONZE.DATACO_ORDER_LINES WHERE LOAD_ID = s.LOAD_ID) - COUNT(*)
FROM ORDER_LINES s
GROUP BY s.LOAD_ID;
