-- =====================================================================================
-- Cortex Search service over public supplier / corporate document chunks (Phase 5).
-- Syntax checked against docs.snowflake.com (create-cortex-search, query-cortex-search-service),
-- 2026-11-25.
--
-- Design:
--   * SEARCH_TEXT = document title + section path + chunk text, so every chunk carries its context
--     into both the keyword and the vector index (retrieval is hybrid + semantic rerank by default).
--   * Default embedding model snowflake-arctic-embed-m-v1.5 (English, 512-token window); chunks are
--     sized to <= ~600 estimated tokens. Keyword matching always uses the full text.
--   * PRIMARY KEY (CHUNK_ID) enables efficient incremental refresh; DOCUMENT_CHUNKS has
--     CHANGE_TRACKING = TRUE and is loaded by a transactional replace (no CREATE OR REPLACE), so the
--     table identity and change tracking survive reloads.
--   * TARGET_LAG 1 day on the X-Small SCC_WH: documents change rarely; a refresh with no changes
--     costs no warehouse credits. Serving is billed per GB-month while the service is running.
--   * Not created with AUTO_SUSPEND (preview; resume returns HTTP 429 until ready). To stop serving
--     cost when not in use:  ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH SUSPEND SERVING;
--                    resume: ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH RESUME SERVING;
--
-- Access: Cortex Search runs with OWNER'S rights; any role with USAGE on the service can read all
-- indexed rows (ADR-009). ACCESS_GROUP is exposed as an attribute but is NOT a security boundary.
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/60_search/01_doc_search_service.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.AI;

-- CREATE OR REPLACE re-embeds all rows (cheap at 152 chunks); use it only when the definition changes.
CREATE OR REPLACE CORTEX SEARCH SERVICE SUPPLIER_DOCS_SEARCH
  ON SEARCH_TEXT
  PRIMARY KEY (CHUNK_ID)
  ATTRIBUTES DOCUMENT_ID, DOCUMENT_TYPE, ACCESS_GROUP
  WAREHOUSE = SCC_WH
  TARGET_LAG = '1 day'
  EMBEDDING_MODEL = 'snowflake-arctic-embed-m-v1.5'
  COMMENT = 'Public supplier quality manual, supplier code of conduct and FY2026 annual report (10-K) chunks. Public documents only.'
AS (
  SELECT
      CHUNK_ID,
      DOCUMENT_ID,
      DOCUMENT_TITLE,
      DOCUMENT_TYPE,
      SECTION_TITLE,
      PAGE_NUMBER,
      PAGE_END,
      PRINTED_PAGE_START,
      PRINTED_PAGE_END,
      SOURCE_URL,
      DOCUMENT_VERSION,
      TO_VARCHAR(PUBLICATION_DATE, 'YYYY-MM-DD')                    AS PUBLICATION_DATE,
      ACCESS_GROUP,
      CONTAINS_TABLE,
      CHUNK_TEXT,
      -- Human-readable citation used by the Cortex Agent (title_column) and the UI.
      DOCUMENT_TITLE || ' | ' || SECTION_TITLE || ' | PDF p. ' || PAGE_NUMBER
        || IFF(PAGE_END <> PAGE_NUMBER, '-' || PAGE_END, '')
        || IFF(PRINTED_PAGE_START IS NOT NULL AND PRINTED_PAGE_START <> TO_VARCHAR(PAGE_NUMBER),
               ' (printed p. ' || PRINTED_PAGE_START || ')', '')                AS CITATION_LABEL,
      DOCUMENT_TITLE || ' - ' || SECTION_TITLE || '\n' || CHUNK_TEXT AS SEARCH_TEXT
  FROM SCC_DB.DOCS.DOCUMENT_CHUNKS
);

-- CREATE OR REPLACE drops grants; re-apply the runtime role's access.
GRANT USAGE ON CORTEX SEARCH SERVICE SUPPLIER_DOCS_SEARCH TO ROLE SCC_APP_ROLE;

DESCRIBE CORTEX SEARCH SERVICE SUPPLIER_DOCS_SEARCH;
