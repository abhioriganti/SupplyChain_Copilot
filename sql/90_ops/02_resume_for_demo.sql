-- Bring the Snowflake side back for a demo. Run the day before (serving can take a few minutes,
-- and returns HTTP 429 until it is ready). Run as SCC_DEV_ROLE:
--   .venv\Scripts\python scripts\run_sql_file.py sql\90_ops\02_resume_for_demo.sql
-- SCC_WH needs no command: it auto-resumes on the first query and auto-suspends after 60 s.
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH RESUME INDEXING;
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH RESUME SERVING;
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.PUBLIC_DISCLOSURES_SEARCH RESUME INDEXING;
ALTER CORTEX SEARCH SERVICE SCC_DB.AI.PUBLIC_DISCLOSURES_SEARCH RESUME SERVING;
SHOW CORTEX SEARCH SERVICES IN SCHEMA SCC_DB.AI;
