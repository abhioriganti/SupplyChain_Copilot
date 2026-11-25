-- =====================================================================================
-- SupplyChain Copilot - one-time account setup
-- Run ONCE in Snowsight as ACCOUNTADMIN. Idempotent (IF NOT EXISTS) except where noted.
--
-- Before running: replace <PUBLIC_KEY> below with the single-line public key printed by
--   scripts/generate_keypair.py   (edit it in Snowsight only; do not save the key into this file)
--
-- Creates:
--   SCC_DEV_ROLE   build role: owns SCC_DB, uses SCC_WH, can call Cortex
--   SCC_APP_ROLE   runtime role for the app (read-only grants are added in a later phase)
--   SCC_WH         X-Small warehouse, 60s auto-suspend, guarded by a resource monitor
--   SCC_DB         project database (owned by SCC_DEV_ROLE)
--   SCC_SVC        SERVICE-type user (key-pair only, no password) used by local scripts/app
-- Docs checked 2026-11-25: create-user, key-pair-auth, aisql-privileges-and-access,
--   create-resource-monitor.
-- =====================================================================================

USE ROLE ACCOUNTADMIN;

-- ---------- Roles ----------
CREATE ROLE IF NOT EXISTS SCC_DEV_ROLE COMMENT = 'SupplyChain Copilot: build/dev role';
CREATE ROLE IF NOT EXISTS SCC_APP_ROLE COMMENT = 'SupplyChain Copilot: read-only runtime role';
GRANT ROLE SCC_APP_ROLE TO ROLE SCC_DEV_ROLE;   -- dev can test as the app role
GRANT ROLE SCC_DEV_ROLE TO ROLE SYSADMIN;       -- keep standard role hierarchy

-- ---------- Warehouse + cost guard ----------
CREATE WAREHOUSE IF NOT EXISTS SCC_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  STATEMENT_TIMEOUT_IN_SECONDS = 900
  COMMENT = 'SupplyChain Copilot: X-Small, auto-suspend 60s';

-- Resource monitors cover WAREHOUSE credits only, not Cortex/serverless (per Snowflake docs).
CREATE RESOURCE MONITOR IF NOT EXISTS SCC_WH_MONITOR
  WITH CREDIT_QUOTA = 25
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 50 PERCENT DO NOTIFY
           ON 80 PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND
           ON 110 PERCENT DO SUSPEND_IMMEDIATE;
ALTER WAREHOUSE SCC_WH SET RESOURCE_MONITOR = SCC_WH_MONITOR;

GRANT USAGE, OPERATE, MONITOR ON WAREHOUSE SCC_WH TO ROLE SCC_DEV_ROLE;
GRANT USAGE ON WAREHOUSE SCC_WH TO ROLE SCC_APP_ROLE;

-- ---------- Database (schemas are created by SCC_DEV_ROLE in 02_schemas.sql) ----------
CREATE DATABASE IF NOT EXISTS SCC_DB COMMENT = 'SupplyChain Copilot (public/sample data only)';
GRANT OWNERSHIP ON DATABASE SCC_DB TO ROLE SCC_DEV_ROLE COPY CURRENT GRANTS;

-- ---------- Cortex access ----------
-- Both are granted to PUBLIC by default; grant explicitly so we don't depend on PUBLIC.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_DEV_ROLE;
GRANT USE AI FUNCTIONS ON ACCOUNT TO ROLE SCC_DEV_ROLE;

-- ---------- Service user (key-pair only) ----------
CREATE USER IF NOT EXISTS SCC_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = SCC_DEV_ROLE
  DEFAULT_WAREHOUSE = SCC_WH
  DEFAULT_NAMESPACE = SCC_DB
  RSA_PUBLIC_KEY = '<PUBLIC_KEY>'
  COMMENT = 'SupplyChain Copilot local scripts and app (key-pair auth)';
GRANT ROLE SCC_DEV_ROLE TO USER SCC_SVC;

-- Let the human admin user (whoever runs this script) use the dev role in Snowsight too.
SET SCC_ADMIN_USER = CURRENT_USER();
GRANT ROLE SCC_DEV_ROLE TO USER IDENTIFIER($SCC_ADMIN_USER);

-- ---------- Verify ----------
SHOW GRANTS TO ROLE SCC_DEV_ROLE;
DESC USER SCC_SVC ->> SELECT "property", "value" FROM $1 WHERE "property" IN ('TYPE', 'RSA_PUBLIC_KEY_FP', 'DEFAULT_ROLE');
