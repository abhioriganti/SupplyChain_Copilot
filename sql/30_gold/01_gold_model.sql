-- =====================================================================================
-- GOLD: business-ready entities. Grain is stated in every table comment.
--   DIM_PRODUCTS      one row per PRODUCT_ID
--   DIM_REGIONS       one row per ORDER_REGION (each region belongs to exactly one MARKET)
--   FACT_ORDERS       one row per ORDER_ID  == one shipment per order (ADR-008). Delivery KPIs live here.
--   FACT_ORDER_LINES  one row per ORDER_ITEM_ID. Revenue/units live here.
-- No FACT_SHIPMENTS table: shipment grain == order grain in this source, so a second table with the
-- same grain would only create ambiguous join paths (ADR-014).
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/30_gold/01_gold_model.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.GOLD;

-- ---------------------------------------------------------------- dimensions
CREATE OR REPLACE TABLE DIM_PRODUCTS (
    PRODUCT_ID       NUMBER(38,0) NOT NULL,
    PRODUCT_NAME     VARCHAR      NOT NULL,
    CATEGORY_ID      NUMBER(38,0) NOT NULL,
    CATEGORY_NAME    VARCHAR      NOT NULL,
    DEPARTMENT_ID    NUMBER(38,0) NOT NULL,
    DEPARTMENT_NAME  VARCHAR      NOT NULL,
    CONSTRAINT PK_DIM_PRODUCTS PRIMARY KEY (PRODUCT_ID)
)
COMMENT = 'Grain: one row per PRODUCT_ID (118). Retail products from the DataCo public sample; not manufactured parts. CATEGORY_NAME is not unique (Electronics = ids 13 and 37); use CATEGORY_ID as key.'
AS
SELECT PRODUCT_ID, MIN(PRODUCT_NAME), MIN(CATEGORY_ID), MIN(CATEGORY_NAME), MIN(DEPARTMENT_ID), MIN(DEPARTMENT_NAME)
FROM SCC_DB.SILVER.ORDER_LINES
GROUP BY PRODUCT_ID;

CREATE OR REPLACE TABLE DIM_REGIONS (
    ORDER_REGION VARCHAR NOT NULL,
    MARKET       VARCHAR NOT NULL,
    CONSTRAINT PK_DIM_REGIONS PRIMARY KEY (ORDER_REGION)
)
COMMENT = 'Grain: one row per destination ORDER_REGION (23); each region maps to exactly one MARKET (5).'
AS
SELECT ORDER_REGION, MIN(MARKET)
FROM SCC_DB.SILVER.ORDER_LINES
GROUP BY ORDER_REGION;

-- ---------------------------------------------------------------- order (= shipment) fact
CREATE OR REPLACE TABLE FACT_ORDERS (
    ORDER_ID                 NUMBER(38,0) NOT NULL,
    CUSTOMER_ID              NUMBER(38,0) NOT NULL,
    CUSTOMER_SEGMENT         VARCHAR      NOT NULL,
    PAYMENT_TYPE             VARCHAR      NOT NULL,
    ORDER_STATUS             VARCHAR      NOT NULL,
    ORDER_TS                 TIMESTAMP_NTZ NOT NULL,
    ORDER_DATE               DATE         NOT NULL,
    ORDER_MONTH              DATE         NOT NULL,
    SHIPPING_TS              TIMESTAMP_NTZ NOT NULL,
    ORDER_REGION             VARCHAR      NOT NULL,
    MARKET                   VARCHAR      NOT NULL,
    ORDER_COUNTRY            VARCHAR      NOT NULL,
    ORDER_STATE              VARCHAR      NOT NULL,
    ORDER_CITY               VARCHAR      NOT NULL,
    SHIPPING_MODE            VARCHAR      NOT NULL,
    DELIVERY_STATUS          VARCHAR      NOT NULL,
    DAYS_SHIPPING_ACTUAL     NUMBER(38,0) NOT NULL,
    DAYS_SHIPPING_SCHEDULED  NUMBER(38,0) NOT NULL,
    SHIPPING_DELAY_DAYS      NUMBER(38,0) NOT NULL,
    IS_SHIPMENT_ELIGIBLE     BOOLEAN      NOT NULL,
    IS_LATE                  BOOLEAN      NOT NULL,
    IS_ON_TIME_OR_EARLY      BOOLEAN      NOT NULL,
    DAYS_LATE                NUMBER(38,0),
    IS_REVENUE_ELIGIBLE      BOOLEAN      NOT NULL,
    LINE_COUNT               NUMBER(38,0) NOT NULL,
    UNITS                    NUMBER(38,0) NOT NULL,
    GROSS_SALES              FLOAT        NOT NULL,
    DISCOUNT_AMOUNT          FLOAT        NOT NULL,
    NET_SALES                FLOAT        NOT NULL,
    PROFIT                   FLOAT        NOT NULL,
    DQ_SHIP_TS_MISMATCH      BOOLEAN      NOT NULL,
    CONSTRAINT PK_FACT_ORDERS PRIMARY KEY (ORDER_ID),
    CONSTRAINT FK_ORDERS_REGION FOREIGN KEY (ORDER_REGION) REFERENCES DIM_REGIONS (ORDER_REGION)
)
COMMENT = 'Grain: one row per ORDER_ID = one shipment (all shipping attributes verified constant across an order''s lines). Delivery KPIs must be computed here, never on order lines. Monthly trends are confounded by market rotation (ADR-011).'
AS
SELECT
    ORDER_ID,
    MIN(CUSTOMER_ID), MIN(CUSTOMER_SEGMENT), MIN(PAYMENT_TYPE), MIN(ORDER_STATUS),
    MIN(ORDER_TS), MIN(ORDER_DATE), MIN(ORDER_MONTH), MIN(SHIPPING_TS),
    MIN(ORDER_REGION), MIN(MARKET), MIN(ORDER_COUNTRY), MIN(ORDER_STATE), MIN(ORDER_CITY),
    MIN(SHIPPING_MODE), MIN(DELIVERY_STATUS),
    MIN(DAYS_SHIPPING_ACTUAL), MIN(DAYS_SHIPPING_SCHEDULED), MIN(SHIPPING_DELAY_DAYS),
    NOT BOOLOR_AGG(IS_CANCELED_SHIPMENT)                                            AS IS_SHIPMENT_ELIGIBLE,
    NOT BOOLOR_AGG(IS_CANCELED_SHIPMENT) AND MIN(DELIVERY_STATUS) = 'Late delivery' AS IS_LATE,
    NOT BOOLOR_AGG(IS_CANCELED_SHIPMENT) AND MIN(DELIVERY_STATUS) <> 'Late delivery' AS IS_ON_TIME_OR_EARLY,
    IFF(NOT BOOLOR_AGG(IS_CANCELED_SHIPMENT) AND MIN(DELIVERY_STATUS) = 'Late delivery',
        MIN(SHIPPING_DELAY_DAYS), NULL)                                             AS DAYS_LATE,
    NOT BOOLOR_AGG(IS_CANCELED_OR_FRAUD_ORDER)                                      AS IS_REVENUE_ELIGIBLE,
    COUNT(*), SUM(QUANTITY), SUM(GROSS_SALES), SUM(DISCOUNT_AMOUNT), SUM(NET_SALES), SUM(LINE_PROFIT),
    BOOLOR_AGG(DQ_SHIP_TS_MISMATCH)
FROM SCC_DB.SILVER.ORDER_LINES
GROUP BY ORDER_ID;

-- ---------------------------------------------------------------- order-line fact
CREATE OR REPLACE TABLE FACT_ORDER_LINES (
    ORDER_ITEM_ID        NUMBER(38,0) NOT NULL,
    ORDER_ID             NUMBER(38,0) NOT NULL,
    PRODUCT_ID           NUMBER(38,0) NOT NULL,
    QUANTITY             NUMBER(38,0) NOT NULL,
    UNIT_PRICE           FLOAT        NOT NULL,
    GROSS_SALES          FLOAT        NOT NULL,
    DISCOUNT_AMOUNT      FLOAT        NOT NULL,
    DISCOUNT_RATE        FLOAT        NOT NULL,
    NET_SALES            FLOAT        NOT NULL,
    LINE_PROFIT          FLOAT        NOT NULL,
    PROFIT_RATIO         FLOAT        NOT NULL,
    IS_REVENUE_ELIGIBLE  BOOLEAN      NOT NULL,
    CONSTRAINT PK_FACT_ORDER_LINES PRIMARY KEY (ORDER_ITEM_ID),
    CONSTRAINT FK_LINES_ORDER FOREIGN KEY (ORDER_ID) REFERENCES FACT_ORDERS (ORDER_ID),
    CONSTRAINT FK_LINES_PRODUCT FOREIGN KEY (PRODUCT_ID) REFERENCES DIM_PRODUCTS (PRODUCT_ID)
)
COMMENT = 'Grain: one row per ORDER_ITEM_ID. Revenue = SUM(NET_SALES) WHERE IS_REVENUE_ELIGIBLE. Join to FACT_ORDERS (many-to-one) for region/market/date; never aggregate FACT_ORDERS measures after this join.'
AS
SELECT ORDER_ITEM_ID, ORDER_ID, PRODUCT_ID, QUANTITY, UNIT_PRICE, GROSS_SALES, DISCOUNT_AMOUNT,
       DISCOUNT_RATE, NET_SALES, LINE_PROFIT, PROFIT_RATIO, NOT IS_CANCELED_OR_FRAUD_ORDER
FROM SCC_DB.SILVER.ORDER_LINES;
