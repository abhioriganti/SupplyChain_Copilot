-- =====================================================================================
-- BRONZE: sanitized DataCo order lines as loaded (append-only, one batch per LOAD_ID).
-- Source: data/processed/dataco_order_lines.parquet (Phase 1; PII already removed).
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/10_bronze/01_bronze_tables.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.BRONZE;

CREATE TABLE IF NOT EXISTS DATACO_ORDER_LINES (
    ORDER_ITEM_ID            NUMBER(38,0),
    ORDER_ID                 NUMBER(38,0),
    CUSTOMER_ID              NUMBER(38,0),
    PRODUCT_ID               NUMBER(38,0),
    PAYMENT_TYPE             VARCHAR,
    ORDER_STATUS             VARCHAR,
    ORDER_TS                 TIMESTAMP_NTZ,
    SHIPPING_TS              TIMESTAMP_NTZ,
    DAYS_SHIPPING_ACTUAL     NUMBER(38,0),
    DAYS_SHIPPING_SCHEDULED  NUMBER(38,0),
    DELIVERY_STATUS          VARCHAR,
    LATE_DELIVERY_RISK       NUMBER(38,0),
    SHIPPING_MODE            VARCHAR,
    CUSTOMER_SEGMENT         VARCHAR,
    MARKET                   VARCHAR,
    ORDER_REGION             VARCHAR,
    ORDER_COUNTRY            VARCHAR,
    ORDER_STATE              VARCHAR,
    ORDER_CITY               VARCHAR,
    PRODUCT_NAME             VARCHAR,
    CATEGORY_ID              NUMBER(38,0),
    CATEGORY_NAME            VARCHAR,
    DEPARTMENT_ID            NUMBER(38,0),
    DEPARTMENT_NAME          VARCHAR,
    QUANTITY                 NUMBER(38,0),
    UNIT_PRICE               FLOAT,
    GROSS_SALES              FLOAT,
    DISCOUNT_AMOUNT          FLOAT,
    DISCOUNT_RATE            FLOAT,
    NET_SALES                FLOAT,
    LINE_PROFIT              FLOAT,
    PROFIT_RATIO             FLOAT,
    DQ_SHIP_TS_MISMATCH      BOOLEAN,
    SOURCE_FILE              VARCHAR,
    SOURCE_ROW_NUMBER        NUMBER(38,0),
    SOURCE_SHA256            VARCHAR,
    CLEANED_AT_UTC           TIMESTAMP_NTZ,
    LOAD_ID                  VARCHAR       NOT NULL,
    INGESTED_AT_UTC          TIMESTAMP_NTZ NOT NULL
)
COMMENT = 'DataCo public sample order lines, sanitized (no PII). Append-only; one batch per LOAD_ID. NOT Worthington data.';

CREATE TABLE IF NOT EXISTS LOAD_AUDIT (
    LOAD_ID          VARCHAR       NOT NULL,
    TARGET_TABLE     VARCHAR       NOT NULL,
    SOURCE_FILE      VARCHAR       NOT NULL,
    SOURCE_SHA256    VARCHAR       NOT NULL,
    ROWS_IN_FILE     NUMBER(38,0)  NOT NULL,
    ROWS_LOADED      NUMBER(38,0)  NOT NULL,
    ROWS_IN_TABLE    NUMBER(38,0)  NOT NULL,
    STATUS           VARCHAR       NOT NULL,
    STARTED_AT_UTC   TIMESTAMP_NTZ NOT NULL,
    FINISHED_AT_UTC  TIMESTAMP_NTZ NOT NULL
)
COMMENT = 'One row per Bronze load: file vs loaded vs table row counts.';
