-- =====================================================================================
-- Backlog item 9: per-user document access, enforced by WHICH search service a role may use.
-- Run in Snowsight as ACCOUNTADMIN (only creating roles and granting them to users needs it).
--
-- Two tier roles stand in for two kinds of user:
--   SCC_DOCS_PUBLIC_ROLE    may search public disclosures only (FY2026 10-K)
--   SCC_DOCS_SUPPLIER_ROLE  may search the supplier-quality corpus (manual, code of conduct, 10-K)
-- Both are granted to the existing runtime user SCC_APP_SVC so the probes can run as either role.
-- That user has DEFAULT_SECONDARY_ROLES = (), so only ONE role is active per session and the tiers
-- can't combine. Object grants (USAGE on database, schema, services) are made by SCC_DEV_ROLE in
-- sql/60_search/02_document_tiers.sql, because it owns those objects.
-- =====================================================================================
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS SCC_DOCS_PUBLIC_ROLE
  COMMENT = 'Document tier: public disclosures only (SCC_DB.AI.PUBLIC_DISCLOSURES_SEARCH).';
CREATE ROLE IF NOT EXISTS SCC_DOCS_SUPPLIER_ROLE
  COMMENT = 'Document tier: supplier-quality corpus (SCC_DB.AI.SUPPLIER_DOCS_SEARCH).';

-- Cortex Search needs SNOWFLAKE.CORTEX_USER (no longer granted to PUBLIC, ADR-025).
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_DOCS_PUBLIC_ROLE;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE SCC_DOCS_SUPPLIER_ROLE;

-- The runtime user can act as either tier (one at a time).
GRANT ROLE SCC_DOCS_PUBLIC_ROLE TO USER SCC_APP_SVC;
GRANT ROLE SCC_DOCS_SUPPLIER_ROLE TO USER SCC_APP_SVC;

SHOW GRANTS TO USER SCC_APP_SVC;

-- Rollback:
--   DROP ROLE IF EXISTS SCC_DOCS_PUBLIC_ROLE;
--   DROP ROLE IF EXISTS SCC_DOCS_SUPPLIER_ROLE;
