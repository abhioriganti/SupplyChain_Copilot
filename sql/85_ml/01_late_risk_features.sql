-- =====================================================================================
-- Late-delivery risk model: schema and leak-free feature view (backlog: predictive model, ADR-032).
-- Run as SCC_DEV_ROLE (owner of SCC_DB):
--   .venv\Scripts\python scripts\run_sql_file.py sql\85_ml\01_late_risk_features.sql
--
-- One row per ELIGIBLE shipment (= order, ADR-008), with only what is known WHEN THE ORDER IS PLACED.
-- Deliberately excluded, because they are known only after shipping or encode the label:
--   DAYS_SHIPPING_ACTUAL, SHIPPING_TS, SHIPPING_DELAY_DAYS, DELIVERY_STATUS, DAYS_LATE,
--   IS_ON_TIME_OR_EARLY, ORDER_STATUS (a later status, e.g. COMPLETE / CLOSED), DQ_SHIP_TS_MISMATCH.
-- DAYS_SHIPPING_SCHEDULED is left out too: it is fixed by SHIPPING_MODE (First 1, Second 2,
-- Standard 4, Same Day 0), so it would only duplicate that feature.
-- Profiling (2026-11-27): within a shipping mode, the late rate barely moves with any of these
-- features; the model is expected to match a shipping-mode baseline, and the report says so.
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE DATABASE SCC_DB;

CREATE SCHEMA IF NOT EXISTS ML COMMENT = 'Predictive models: feature views and the Snowflake Model Registry';

CREATE OR REPLACE VIEW SCC_DB.ML.V_LATE_RISK_FEATURES
  COMMENT = 'Order-time features and IS_LATE label for eligible shipments (DataCo public sample). No post-shipment columns.'
AS
SELECT
    ORDER_ID,
    ORDER_DATE,                                  -- for the time-based holdout only, not a feature
    SHIPPING_MODE,
    MARKET,
    ORDER_REGION,
    CUSTOMER_SEGMENT,
    PAYMENT_TYPE,
    DAYOFWEEKISO(ORDER_TS)      AS ORDER_DOW,
    HOUR(ORDER_TS)              AS ORDER_HOUR,
    MONTH(ORDER_DATE)           AS ORDER_MONTH,
    LINE_COUNT,
    UNITS,
    NET_SALES,
    IFF(IS_LATE, 1, 0)          AS IS_LATE
FROM SCC_DB.GOLD.FACT_ORDERS
WHERE IS_SHIPMENT_ELIGIBLE;

SELECT COUNT(*) AS ROWS_, AVG(IS_LATE) AS LATE_RATE FROM SCC_DB.ML.V_LATE_RISK_FEATURES;
