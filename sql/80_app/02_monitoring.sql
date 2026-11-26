-- =====================================================================================
-- Phase 8 observability: one row per agent request (app and evaluation runs).
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/80_app/02_monitoring.sql
--
-- Logged: ids, timestamps, source, tools, status, latency, error class, citation/SQL counts,
-- model and token usage, cache flag, evaluation case/outcome. The question is stored truncated
-- with credential patterns redacted, plus a SHA-256 for grouping. No credentials, no answer text,
-- no customer data (the dataset has none after Phase 1 sanitization).
-- The runtime role gets INSERT only; reading the log is a developer/operator activity.
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;

CREATE TABLE IF NOT EXISTS SCC_DB.APP.AGENT_REQUEST_LOG (
    REQUEST_ID           VARCHAR       NOT NULL,
    CREATED_AT_UTC       TIMESTAMP_NTZ NOT NULL,
    SOURCE               VARCHAR       NOT NULL,   -- app | eval
    SESSION_ID           VARCHAR,
    QUESTION_SHA256      VARCHAR       NOT NULL,
    QUESTION_REDACTED    VARCHAR,                  -- first 300 chars, credential patterns redacted
    STATUS               VARCHAR,                  -- completed | error | ...
    ERROR_CLASS          VARCHAR,                  -- invalid | rate_limited | auth | permission | timeout | service | empty
    TOOLS_USED           VARCHAR,
    SQL_COUNT            NUMBER(38,0),
    VERIFIED_QUERY_USED  BOOLEAN,
    CITATION_COUNT       NUMBER(38,0),
    LATENCY_S            FLOAT,
    CACHED               BOOLEAN,
    ORCHESTRATION_MODEL  VARCHAR,
    INPUT_TOKENS         NUMBER(38,0),
    OUTPUT_TOKENS        NUMBER(38,0),
    EVAL_RUN_ID          VARCHAR,
    EVAL_CASE_ID         VARCHAR,
    EVAL_OUTCOME         VARCHAR,                  -- pass | fail | null for app traffic
    APP_VERSION          VARCHAR,
    CONSTRAINT PK_AGENT_REQUEST_LOG PRIMARY KEY (REQUEST_ID)
)
COMMENT = 'SupplyChain Copilot request log (no secrets, no answer text, redacted/truncated questions).';

GRANT INSERT ON TABLE SCC_DB.APP.AGENT_REQUEST_LOG TO ROLE SCC_APP_ROLE;

CREATE OR REPLACE VIEW SCC_DB.APP.V_AGENT_MONITORING_DAILY
COMMENT = 'Daily request volume, error rate, latency percentiles, tool mix and eval outcomes.'
AS
SELECT
    DATE_TRUNC('DAY', CREATED_AT_UTC)::DATE                                   AS DAY,
    SOURCE,
    COUNT(*)                                                                  AS REQUESTS,
    COUNT_IF(STATUS <> 'completed')                                           AS ERRORS,
    COUNT_IF(STATUS <> 'completed')::FLOAT / NULLIF(COUNT(*), 0)              AS ERROR_RATE,
    COUNT_IF(CACHED)                                                          AS CACHED_REQUESTS,
    APPROX_PERCENTILE(IFF(CACHED, NULL, LATENCY_S), 0.5)                      AS LATENCY_P50_S,
    APPROX_PERCENTILE(IFF(CACHED, NULL, LATENCY_S), 0.95)                     AS LATENCY_P95_S,
    COUNT_IF(TOOLS_USED ILIKE '%delivery_analytics%')                         AS USED_ANALYST,
    COUNT_IF(TOOLS_USED ILIKE '%supplier_documents%')                         AS USED_SEARCH,
    COUNT_IF(EVAL_OUTCOME = 'pass')                                           AS EVAL_PASS,
    COUNT_IF(EVAL_OUTCOME = 'fail')                                           AS EVAL_FAIL,
    SUM(INPUT_TOKENS)                                                         AS INPUT_TOKENS,
    SUM(OUTPUT_TOKENS)                                                        AS OUTPUT_TOKENS
FROM SCC_DB.APP.AGENT_REQUEST_LOG
GROUP BY 1, 2;
