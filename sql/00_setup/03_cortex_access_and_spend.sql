-- =====================================================================================
-- Backlog items 7 and 10: check Cortex spend, and stop granting Cortex to every role via PUBLIC.
-- Run in Snowsight as ACCOUNTADMIN, one section at a time (only ACCOUNTADMIN can manage
-- USE AI FUNCTIONS, and the project roles cannot read SNOWFLAKE.ACCOUNT_USAGE).
-- Syntax from docs.snowflake.com, read 2026-11-26:
--   user-guide/snowflake-cortex/aisql-privileges-and-access, .../opting-out,
--   .../cortex-agents-setup, .../cortex-analyst, sql-reference/account-usage/metering_daily_history,
--   .../cortex_agent_usage_history, user-guide/budgets
-- =====================================================================================
USE ROLE ACCOUNTADMIN;

-- -------------------------------------------------------------------------------------
-- A. Spend so far (read-only). ACCOUNT_USAGE lags: up to 3 h for METERING_DAILY_HISTORY and
--    up to 1 h for CORTEX_AGENT_USAGE_HISTORY, so the last few hours may be missing.
-- -------------------------------------------------------------------------------------
SELECT SERVICE_TYPE,
       ROUND(SUM(CREDITS_USED), 3)   AS CREDITS_USED,
       ROUND(SUM(CREDITS_BILLED), 3) AS CREDITS_BILLED
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE USAGE_DATE >= '2026-11-25'
GROUP BY 1
ORDER BY 2 DESC;

SELECT USER_NAME, AGENT_NAME, COUNT(*) AS REQUESTS, ROUND(SUM(TOKEN_CREDITS), 3) AS TOKEN_CREDITS
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
GROUP BY 1, 2
ORDER BY 4 DESC;

-- -------------------------------------------------------------------------------------
-- B. Make the project roles' Cortex access explicit (both statements are idempotent and were
--    already run in 01_account_setup.sql / 00c_app_service_user.sql), then revoke from PUBLIC.
--    Docs: Analyst, Search and Agents need SNOWFLAKE.CORTEX_USER (or the narrower
--    CORTEX_ANALYST_USER / CORTEX_AGENT_USER); USE AI FUNCTIONS governs AI functions such as
--    AI_COMPLETE. SCC_APP_ROLE is deliberately NOT given USE AI FUNCTIONS: the app never calls
--    AI functions directly, and the docs do not list it for agents. The eval re-run confirms it.
-- -------------------------------------------------------------------------------------
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_DEV_ROLE;
GRANT USE AI FUNCTIONS ON ACCOUNT TO ROLE SCC_DEV_ROLE;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_APP_ROLE;

REVOKE DATABASE ROLE SNOWFLAKE.CORTEX_USER FROM ROLE PUBLIC;
REVOKE USE AI FUNCTIONS ON ACCOUNT FROM ROLE PUBLIC;

-- Verify: neither line should appear for PUBLIC; both project roles still hold CORTEX_USER.
SHOW GRANTS TO ROLE PUBLIC;
SHOW GRANTS TO ROLE SCC_APP_ROLE;
SHOW GRANTS TO ROLE SCC_DEV_ROLE;

-- Docs: revoking from PUBLIC "does not prevent ACCOUNTADMIN from using these features".
-- Whether ACCOUNTADMIN keeps USE AI FUNCTIONS is not documented; if Snowsight AI features stop
-- working for you as ACCOUNTADMIN, run:
--   GRANT USE AI FUNCTIONS ON ACCOUNT TO ROLE ACCOUNTADMIN;

-- -------------------------------------------------------------------------------------
-- Rollback (restores the Snowflake defaults):
--   GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE PUBLIC;
--   GRANT USE AI FUNCTIONS ON ACCOUNT TO ROLE PUBLIC;
-- -------------------------------------------------------------------------------------

-- -------------------------------------------------------------------------------------
-- C. Spend alert: activate the ACCOUNT budget in Snowsight (Admin > Cost management > Budgets).
--    It covers the whole account, including Cortex Agents (AI_SERVICES), Analyst, Search and the
--    warehouse, so no object has to be attached. Set a monthly credit limit and a verified email.
--    Per the docs the limit is for alerting only: it notifies, it does not stop spend. The
--    warehouse also keeps its 25-credit resource monitor, which does suspend it.
-- -------------------------------------------------------------------------------------
