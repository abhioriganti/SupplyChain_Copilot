-- =====================================================================================
-- SupplyChain Copilot - schemas. Run as SCC_DEV_ROLE (owner of SCC_DB):
--   .venv\Scripts\python scripts\run_sql_file.py sql\00_setup\02_schemas.sql
-- =====================================================================================

USE ROLE SCC_DEV_ROLE;
USE DATABASE SCC_DB;

CREATE SCHEMA IF NOT EXISTS BRONZE  COMMENT = 'Sanitised raw imports + lineage (DataCo public sample data)';
CREATE SCHEMA IF NOT EXISTS SILVER  COMMENT = 'Typed, deduplicated, validated records';
CREATE SCHEMA IF NOT EXISTS GOLD    COMMENT = 'Business-ready facts and dimensions';
CREATE SCHEMA IF NOT EXISTS DOCS    COMMENT = 'Public document chunks + metadata';
CREATE SCHEMA IF NOT EXISTS AI      COMMENT = 'Semantic view, Cortex Search service, Cortex Agent';
CREATE SCHEMA IF NOT EXISTS APP     COMMENT = 'App telemetry: query log, feedback';
CREATE SCHEMA IF NOT EXISTS SANDBOX COMMENT = 'Throwaway smoke-test objects';

SHOW SCHEMAS IN DATABASE SCC_DB;
