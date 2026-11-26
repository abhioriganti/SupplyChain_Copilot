-- =====================================================================================
-- Dedicated runtime service user for the app/agent. Run ONCE in Snowsight as ACCOUNTADMIN.
--
-- Why: Snowflake activates the user's *secondary roles* by default (DEFAULT_SECONDARY_ROLES = ALL).
-- Phase 6 testing showed that a session using SCC_APP_ROLE as primary role, opened by SCC_SVC (which
-- also holds SCC_DEV_ROLE), could still read GOLD/BRONZE tables and run DELETE via the secondary role.
-- Least privilege therefore needs a user that holds ONLY SCC_APP_ROLE, with secondary roles disabled.
--
-- Before running: generate a separate key pair for this user:
--   .venv\Scripts\python scripts\generate_keypair.py --out $env:USERPROFILE\.snowflake\keys\scc_app_svc_rsa_key.p8
-- and replace <APP_PUBLIC_KEY> below in Snowsight (do not save the key into this file).
-- =====================================================================================
USE ROLE ACCOUNTADMIN;

CREATE USER IF NOT EXISTS SCC_APP_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = SCC_APP_ROLE
  DEFAULT_SECONDARY_ROLES = ()
  DEFAULT_WAREHOUSE = SCC_WH
  RSA_PUBLIC_KEY = '<APP_PUBLIC_KEY>'
  COMMENT = 'SupplyChain Copilot app/agent runtime: holds only SCC_APP_ROLE (least privilege: no raw-data access, insert-only app logs), no secondary roles';

GRANT ROLE SCC_APP_ROLE TO USER SCC_APP_SVC;
-- Explicit Cortex access for the runtime role (revoked from PUBLIC in 00_setup/03, ADR-025).
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_APP_ROLE;

-- Verify: only SCC_APP_ROLE (+ PUBLIC) is granted, and secondary roles are disabled.
SHOW GRANTS TO USER SCC_APP_SVC;
DESC USER SCC_APP_SVC ->> SELECT "property", "value" FROM $1
  WHERE "property" IN ('TYPE', 'DEFAULT_ROLE', 'DEFAULT_SECONDARY_ROLES', 'RSA_PUBLIC_KEY_FP');
