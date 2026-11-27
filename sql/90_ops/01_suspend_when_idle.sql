-- Stop idle Snowflake spend between work sessions (see docs/app_guide.md).
-- Run as SCC_DEV_ROLE (owner of the search services):
--   .venv\Scripts\python scripts\run_sql_file.py sql\90_ops\01_suspend_when_idle.sql
-- Reverse with sql\90_ops\02_resume_for_demo.sql. Nothing is deleted.
--
-- What costs money while idle, and what this does about it:
--   * Cortex Search serving is billed per GB-month while serving is ACTIVE -> SUSPEND SERVING.
--   * Indexing refresh (TARGET_LAG 1 day) can wake SCC_WH                  -> SUSPEND INDEXING.
--   * SCC_WH auto-suspends after 60 s (ALTER ... SUSPEND errors if it is already suspended).
--   * Agent, semantic view, tables: no idle compute (storage only, a few MB).
--   * SCC_AUDIT_DB.ANCHOR.ANCHOR_DAILY (serverless, seconds a day) is left running on purpose so the
--     audit anchors stay continuous; it is owned by SCC_AUDIT_ROLE, not this role.
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH SUSPEND SERVING;
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH SUSPEND INDEXING;
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.PUBLIC_DISCLOSURES_SEARCH SUSPEND SERVING;
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.PUBLIC_DISCLOSURES_SEARCH SUSPEND INDEXING;
SHOW CORTEX SEARCH SERVICES IN SCHEMA SCC_DB.AI;
