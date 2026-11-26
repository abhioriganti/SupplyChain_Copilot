-- =====================================================================================
-- Phase 4 document-table tests. ONE query; every row is a test; FAILURES must be 0.
-- Run:  python scripts/run_sql_tests.py sql/tests/test_phase4_documents.sql
-- =====================================================================================
WITH c AS (SELECT * FROM SCC_DB.DOCS.DOCUMENT_CHUNKS),
     d AS (SELECT * FROM SCC_DB.DOCS.DOCUMENTS)
SELECT 'chunk_id_unique' AS TEST_NAME, 'DOCS' AS LAYER, COUNT(*) - COUNT(DISTINCT CHUNK_ID) AS FAILURES, 'PK' AS DETAIL FROM c
UNION ALL SELECT 'document_id_unique', 'DOCS', COUNT(*) - COUNT(DISTINCT DOCUMENT_ID), 'PK' FROM d
UNION ALL SELECT 'three_documents_loaded', 'DOCS', ABS(COUNT(*) - 3), 'SQAM, SCOC, annual report' FROM d
UNION ALL SELECT 'every_chunk_has_document', 'DOCS', COUNT(*), 'FK chunks -> documents'
FROM c LEFT JOIN d ON c.DOCUMENT_ID = d.DOCUMENT_ID WHERE d.DOCUMENT_ID IS NULL
UNION ALL SELECT 'chunk_count_matches_documents', 'DOCS', COUNT(*), 'DOCUMENTS.CHUNK_COUNT = actual chunks'
FROM d LEFT JOIN (SELECT DOCUMENT_ID, COUNT(*) N FROM c GROUP BY 1) x ON d.DOCUMENT_ID = x.DOCUMENT_ID
WHERE COALESCE(x.N, 0) <> d.CHUNK_COUNT
UNION ALL SELECT 'content_hash_is_sha256_of_text', 'DOCS', COUNT_IF(CONTENT_HASH <> SHA2(CHUNK_TEXT, 256)),
       'hash recomputed in Snowflake equals stored hash' FROM c
UNION ALL SELECT 'pages_within_document', 'DOCS', COUNT(*), '1 <= PAGE_NUMBER <= PAGE_END <= PAGE_COUNT'
FROM c JOIN d ON c.DOCUMENT_ID = d.DOCUMENT_ID
WHERE c.PAGE_NUMBER < 1 OR c.PAGE_END < c.PAGE_NUMBER OR c.PAGE_END > d.PAGE_COUNT
UNION ALL SELECT 'required_metadata_present', 'DOCS',
       COUNT_IF(TRIM(CHUNK_TEXT) = '' OR TRIM(SECTION_TITLE) = '' OR SOURCE_URL NOT LIKE 'https://%'
             OR DOCUMENT_VERSION = '' OR PUBLICATION_DATE IS NULL OR INGESTED_AT IS NULL OR ACCESS_GROUP = ''),
       'non-empty text, section, https URL, version, dates, access group' FROM c
UNION ALL SELECT 'chunk_metadata_matches_document', 'DOCS', COUNT(*), 'title/url/version/date copied consistently'
FROM c JOIN d ON c.DOCUMENT_ID = d.DOCUMENT_ID
WHERE c.DOCUMENT_TITLE <> d.DOCUMENT_TITLE OR c.SOURCE_URL <> d.SOURCE_URL
   OR c.DOCUMENT_VERSION <> d.DOCUMENT_VERSION OR c.PUBLICATION_DATE <> d.PUBLICATION_DATE OR c.SOURCE_SHA256 <> d.SOURCE_SHA256
UNION ALL SELECT 'access_group_public_only', 'DOCS', COUNT_IF(ACCESS_GROUP <> 'public'), 'v1 corpus is public documents only' FROM c
UNION ALL SELECT 'token_estimate_within_limit', 'DOCS', COUNT_IF(TOKEN_ESTIMATE > 600), 'chunks <= 600 estimated tokens' FROM c
UNION ALL SELECT 'single_load_batch', 'DOCS', COUNT(DISTINCT LOAD_ID) - 1, 'transactional replace leaves one batch' FROM c
UNION ALL SELECT 'corrective_action_evidence_present', 'DOCS',
       IFF(COUNT_IF(CHUNK_TEXT ILIKE '%14 working days%' AND PAGE_NUMBER = 29) = 1, 0, 1),
       'key SQAM table (7.2 Corrective Action Responses) retrievable at PDF p.29' FROM c
;
