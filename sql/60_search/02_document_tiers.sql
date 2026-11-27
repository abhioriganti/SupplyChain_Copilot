-- =====================================================================================
-- Backlog item 9: document tiers. Run as SCC_DEV_ROLE after sql/00_setup/04_document_tier_roles.sql:
--   python scripts/run_sql_file.py sql/60_search/02_document_tiers.sql
--
-- Why separate services: Cortex Search runs with the OWNER's rights, so a filter sent by the client
-- (ACCESS_GROUP, DOCUMENT_TYPE) only narrows results; it is not a security boundary (ADR-009). The
-- enforceable boundary is USAGE on a service. So each sensitivity tier gets its own service, and each
-- role is granted only the services for its tier. Here the tiers are simulated: all three documents
-- are public, and the 10-K plays the "public disclosures" tier.
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.AI;

CREATE OR REPLACE CORTEX SEARCH SERVICE PUBLIC_DISCLOSURES_SEARCH
  ON SEARCH_TEXT
  PRIMARY KEY (CHUNK_ID)
  ATTRIBUTES DOCUMENT_ID, DOCUMENT_TYPE, ACCESS_GROUP
  WAREHOUSE = SCC_WH
  TARGET_LAG = '1 day'
  EMBEDDING_MODEL = 'snowflake-arctic-embed-m-v1.5'
  COMMENT = 'Document tier "public disclosures": FY2026 annual report (10-K) chunks only.'
AS (
  SELECT
      CHUNK_ID, DOCUMENT_ID, DOCUMENT_TITLE, DOCUMENT_TYPE, SECTION_TITLE, PAGE_NUMBER, PAGE_END,
      ACCESS_GROUP, CHUNK_TEXT,
      DOCUMENT_TITLE || ' | ' || SECTION_TITLE || ' | PDF p. ' || PAGE_NUMBER
        || IFF(PAGE_END <> PAGE_NUMBER, '-' || PAGE_END, '')            AS CITATION_LABEL,
      DOCUMENT_TITLE || ' - ' || SECTION_TITLE || '\n' || CHUNK_TEXT     AS SEARCH_TEXT
  FROM SCC_DB.DOCS.DOCUMENT_CHUNKS
  WHERE DOCUMENT_TYPE = 'annual_report_10k'
);

-- Tier grants. Database and schema USAGE are needed to resolve the service name.
GRANT USAGE ON DATABASE SCC_DB TO ROLE SCC_DOCS_PUBLIC_ROLE;
GRANT USAGE ON SCHEMA SCC_DB.AI TO ROLE SCC_DOCS_PUBLIC_ROLE;
GRANT USAGE ON CORTEX SEARCH SERVICE PUBLIC_DISCLOSURES_SEARCH TO ROLE SCC_DOCS_PUBLIC_ROLE;

GRANT USAGE ON DATABASE SCC_DB TO ROLE SCC_DOCS_SUPPLIER_ROLE;
GRANT USAGE ON SCHEMA SCC_DB.AI TO ROLE SCC_DOCS_SUPPLIER_ROLE;
GRANT USAGE ON CORTEX SEARCH SERVICE SUPPLIER_DOCS_SEARCH TO ROLE SCC_DOCS_SUPPLIER_ROLE;
GRANT USAGE ON CORTEX SEARCH SERVICE PUBLIC_DISCLOSURES_SEARCH TO ROLE SCC_DOCS_SUPPLIER_ROLE;

-- Deliberately NOT granted: SUPPLIER_DOCS_SEARCH to SCC_DOCS_PUBLIC_ROLE. The probes check it's denied.
SHOW GRANTS TO ROLE SCC_DOCS_PUBLIC_ROLE;
