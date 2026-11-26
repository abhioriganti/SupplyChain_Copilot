-- =====================================================================================
-- DOCS: public document provenance + retrieval chunks (Phase 4).
-- CHANGE_TRACKING is enabled because Cortex Search (Phase 5) refreshes from this table.
-- Loaded by: python -m supplychain_copilot.documents.load   (transactional replace)
-- Run as SCC_DEV_ROLE: python scripts/run_sql_file.py sql/50_documents/01_document_tables.sql
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.DOCS;

CREATE TABLE IF NOT EXISTS DOCUMENTS (
    DOCUMENT_ID                VARCHAR       NOT NULL,
    DOCUMENT_TITLE             VARCHAR       NOT NULL,
    DOCUMENT_TYPE              VARCHAR       NOT NULL,
    PUBLISHER                  VARCHAR       NOT NULL,
    SOURCE_URL                 VARCHAR       NOT NULL,
    DOCUMENT_VERSION           VARCHAR       NOT NULL,
    VERSION_EVIDENCE           VARCHAR       NOT NULL,
    PUBLICATION_DATE           DATE          NOT NULL,
    PUBLICATION_DATE_EVIDENCE  VARCHAR       NOT NULL,
    ACCESS_GROUP               VARCHAR       NOT NULL,
    SOURCE_FILE                VARCHAR       NOT NULL,
    SOURCE_SHA256              VARCHAR       NOT NULL,
    PAGE_COUNT                 NUMBER(38,0)  NOT NULL,
    PAGES_INCLUDED             NUMBER(38,0)  NOT NULL,
    PAGES_EXCLUDED_JSON        VARCHAR       NOT NULL,
    CHUNK_COUNT                NUMBER(38,0)  NOT NULL,
    PARSER_VERSION             VARCHAR       NOT NULL,
    INGESTED_AT                TIMESTAMP_NTZ NOT NULL,
    LOAD_ID                    VARCHAR       NOT NULL,
    CONSTRAINT PK_DOCUMENTS PRIMARY KEY (DOCUMENT_ID)
)
COMMENT = 'One row per public source document with provenance (URL, version and date evidence, file hash, page scope).';

CREATE TABLE IF NOT EXISTS DOCUMENT_CHUNKS (
    CHUNK_ID            VARCHAR       NOT NULL,
    DOCUMENT_ID         VARCHAR       NOT NULL,
    CHUNK_INDEX         NUMBER(38,0)  NOT NULL,
    DOCUMENT_TITLE      VARCHAR       NOT NULL,
    DOCUMENT_TYPE       VARCHAR       NOT NULL,
    SECTION_TITLE       VARCHAR       NOT NULL,
    PAGE_NUMBER         NUMBER(38,0)  NOT NULL,
    PAGE_END            NUMBER(38,0)  NOT NULL,
    PRINTED_PAGE_START  VARCHAR,
    PRINTED_PAGE_END    VARCHAR,
    CHUNK_TEXT          VARCHAR       NOT NULL,
    TOKEN_ESTIMATE      NUMBER(38,0)  NOT NULL,
    CONTAINS_TABLE      BOOLEAN       NOT NULL,
    OVERLAP_PREFIX      BOOLEAN       NOT NULL,
    EXTRACTION_FLAGS    VARCHAR,
    SOURCE_URL          VARCHAR       NOT NULL,
    DOCUMENT_VERSION    VARCHAR       NOT NULL,
    PUBLICATION_DATE    DATE          NOT NULL,
    INGESTED_AT         TIMESTAMP_NTZ NOT NULL,
    ACCESS_GROUP        VARCHAR       NOT NULL,
    CONTENT_HASH        VARCHAR       NOT NULL,
    SOURCE_SHA256       VARCHAR       NOT NULL,
    PARSER_VERSION      VARCHAR       NOT NULL,
    LOAD_ID             VARCHAR       NOT NULL,
    CONSTRAINT PK_DOCUMENT_CHUNKS PRIMARY KEY (CHUNK_ID),
    CONSTRAINT FK_CHUNKS_DOCUMENT FOREIGN KEY (DOCUMENT_ID) REFERENCES DOCUMENTS (DOCUMENT_ID)
)
CHANGE_TRACKING = TRUE
COMMENT = 'Heading-aware chunks of public documents. PAGE_NUMBER/PAGE_END are 1-based PDF pages (PRINTED_PAGE_* = page label printed on the page). CHUNK_TEXT is extracted source text only; CONTENT_HASH = SHA-256(CHUNK_TEXT).';
