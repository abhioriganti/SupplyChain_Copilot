-- =====================================================================================
-- Explicit Cortex grants for the runtime role. Run ONCE in Snowsight as ACCOUNTADMIN.
-- (CORTEX_USER is also granted to PUBLIC by default; this removes the dependency on PUBLIC.)
-- =====================================================================================
USE ROLE ACCOUNTADMIN;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_APP_ROLE;
SHOW GRANTS TO ROLE SCC_APP_ROLE;
