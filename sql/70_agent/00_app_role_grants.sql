-- =====================================================================================
-- Least-privilege runtime role for the app/agent (Phase 6). Run as SCC_DEV_ROLE (owner of SCC_DB objects):
--   python scripts/run_sql_file.py sql/70_agent/00_app_role_grants.sql
--
-- SCC_APP_ROLE can ONLY: use the warehouse, query the governed semantic view, query the Cortex Search
-- service, and run the agent. It has no SELECT on Bronze/Silver/Gold tables, cannot modify any
-- business data, and owns nothing. Analyst-generated SQL therefore cannot change data even if a
-- prompt tries to make it, and cannot read raw layers that bypass the governed definitions.
-- Its only writes are INSERT-only on three app log tables, granted later: APP.AGENT_FEEDBACK
-- (80_app/01), APP.AGENT_REQUEST_LOG (80_app/02) and APP.INCIDENT_AUDIT_LOG (80_app/03).
-- Cortex access: explicit SNOWFLAKE.CORTEX_USER grant (00b/00c); revoked from PUBLIC in
-- sql/00_setup/03_cortex_access_and_spend.sql (ADR-025).
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;

GRANT USAGE ON DATABASE SCC_DB TO ROLE SCC_APP_ROLE;
GRANT USAGE ON SCHEMA SCC_DB.AI TO ROLE SCC_APP_ROLE;

-- Governed semantic layer (querying a semantic view needs SELECT on the view, not on base tables)
GRANT SELECT ON SEMANTIC VIEW SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV TO ROLE SCC_APP_ROLE;

-- Document retrieval (runs with owner's rights; app role sees only what the service indexes)
GRANT USAGE ON CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH TO ROLE SCC_APP_ROLE;

-- Feedback/telemetry tables are added in a later phase with INSERT-only grants on APP schema.
