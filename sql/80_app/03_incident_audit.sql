-- =====================================================================================
-- Phase 9: supplier-quality incident workflow (SIMULATED) - append-only, hash-chained audit log.
-- Run as SCC_DEV_ROLE:  python scripts/run_sql_file.py sql/80_app/03_incident_audit.sql
--
-- Design (ADR-027):
--   * Event-sourced: every step is one row; an incident's status is its latest event. Nothing is
--     ever updated or deleted, so the runtime role gets INSERT on the table and SELECT on views only.
--   * Tamper-evident: EVENT_HASH = SHA-256(PREV_HASH || incident | seq | type | actor | actor type |
--     time | PAYLOAD), chained per incident (hash version 2; version 1 rows covered PAYLOAD only).
--     V_INCIDENT_CHAIN_CHECK recomputes the chain in SQL, independently of the Python writer.
--   * Simulated: incidents are practice records about sample data. No email or supplier contact
--     is ever sent; an approved action is recorded as ACTION_SIMULATED.
--   * Minimal data: free-text fields are length-limited and credential patterns are redacted
--     before insert (supplychain_copilot.incidents.model).
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
USE SCHEMA SCC_DB.APP;

CREATE TABLE IF NOT EXISTS INCIDENT_AUDIT_LOG (
    EVENT_ID         VARCHAR       NOT NULL,
    INCIDENT_ID      VARCHAR       NOT NULL,
    SEQ              NUMBER(38,0)  NOT NULL,   -- 1, 2, 3 ... per incident
    EVENT_TYPE       VARCHAR       NOT NULL,   -- CREATED | DRAFTED | SUBMITTED_FOR_APPROVAL | APPROVED | REJECTED | TIMED_OUT | ACTION_SIMULATED | ERROR
    ACTOR            VARCHAR       NOT NULL,   -- person name, 'supply_chain_copilot' or 'n8n'
    ACTOR_TYPE       VARCHAR       NOT NULL,   -- human | agent | workflow | system
    CREATED_AT_UTC   TIMESTAMP_NTZ NOT NULL,
    PAYLOAD          VARCHAR       NOT NULL,   -- canonical JSON (sorted keys) of the event details
    PREV_HASH        VARCHAR       NOT NULL,   -- EVENT_HASH of SEQ-1, or 64 zeros for SEQ 1
    EVENT_HASH       VARCHAR       NOT NULL,   -- SHA-256 hex; what it covers depends on HASH_VERSION
    SIMULATED        BOOLEAN       NOT NULL,
    HASH_VERSION     NUMBER(38,0)  DEFAULT 1,  -- 1: PREV_HASH||PAYLOAD; 2: also incident, seq, type, actor, actor type, time
    CONSTRAINT PK_INCIDENT_AUDIT_LOG PRIMARY KEY (EVENT_ID),
    CONSTRAINT UQ_INCIDENT_SEQ UNIQUE (INCIDENT_ID, SEQ)
)
COMMENT = 'Append-only, hash-chained audit log for SIMULATED supplier-quality incidents (Phase 9). Status = latest event.';

-- Phase 10 audit fix: hash version 2 also covers who acted, when and in what order. Rows written
-- before the fix keep HASH_VERSION = 1 and are verified by the v1 rule (history is not rewritten).
ALTER TABLE INCIDENT_AUDIT_LOG ADD COLUMN IF NOT EXISTS HASH_VERSION NUMBER(38,0) DEFAULT 1;

CREATE OR REPLACE VIEW V_INCIDENT_EVENTS
COMMENT = 'Incident audit events with the payload parsed.'
AS
SELECT EVENT_ID, INCIDENT_ID, SEQ, EVENT_TYPE, ACTOR, ACTOR_TYPE, CREATED_AT_UTC,
       PARSE_JSON(PAYLOAD) AS DETAILS, PAYLOAD, PREV_HASH, EVENT_HASH, SIMULATED,
       COALESCE(HASH_VERSION, 1) AS HASH_VERSION
FROM INCIDENT_AUDIT_LOG;

CREATE OR REPLACE VIEW V_INCIDENT_STATUS
COMMENT = 'One row per incident: current status (latest event), key fields, requester and decision.'
AS
WITH e AS (SELECT * FROM V_INCIDENT_EVENTS)
SELECT
    c.INCIDENT_ID,
    c.DETAILS:title::VARCHAR                 AS TITLE,
    c.DETAILS:supplier::VARCHAR              AS SUPPLIER,
    c.DETAILS:severity::VARCHAR              AS SEVERITY,
    c.ACTOR                                  AS REQUESTER,
    c.CREATED_AT_UTC                         AS OPENED_AT_UTC,
    l.EVENT_TYPE                             AS STATUS,
    l.CREATED_AT_UTC                         AS UPDATED_AT_UTC,
    d.EVENT_TYPE                             AS DECISION,
    d.ACTOR                                  AS DECIDED_BY,
    d.DETAILS:comment::VARCHAR               AS DECISION_COMMENT,
    s.DETAILS:approval_url::VARCHAR          AS APPROVAL_URL,
    l.SEQ                                    AS EVENT_COUNT
FROM e c
JOIN e l ON l.INCIDENT_ID = c.INCIDENT_ID
LEFT JOIN e d ON d.INCIDENT_ID = c.INCIDENT_ID AND d.EVENT_TYPE IN ('APPROVED', 'REJECTED', 'TIMED_OUT')
LEFT JOIN e s ON s.INCIDENT_ID = c.INCIDENT_ID AND s.EVENT_TYPE = 'SUBMITTED_FOR_APPROVAL'
WHERE c.SEQ = 1
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.INCIDENT_ID ORDER BY l.SEQ DESC, s.SEQ DESC NULLS LAST) = 1;

CREATE OR REPLACE VIEW V_INCIDENT_CHAIN_CHECK
COMMENT = 'Recomputes the SHA-256 chain per incident. CHAIN_OK = FALSE means a row was altered, removed or reordered.'
AS
WITH x AS (
    SELECT INCIDENT_ID, SEQ, PREV_HASH, EVENT_HASH, HASH_VERSION,
           IFF(COALESCE(HASH_VERSION, 1) = 1,
               SHA2(PREV_HASH || PAYLOAD, 256),
               SHA2(PREV_HASH || INCIDENT_ID || '|' || SEQ::VARCHAR || '|' || EVENT_TYPE || '|' || ACTOR
                    || '|' || ACTOR_TYPE || '|' || TO_VARCHAR(CREATED_AT_UTC, 'YYYY-MM-DD"T"HH24:MI:SS.FF6')
                    || '|' || PAYLOAD, 256)) = EVENT_HASH                                 AS HASH_OK,
           COALESCE(LAG(EVENT_HASH) OVER (PARTITION BY INCIDENT_ID ORDER BY SEQ), REPEAT('0', 64))
               = PREV_HASH                                                               AS LINK_OK,
           SEQ = ROW_NUMBER() OVER (PARTITION BY INCIDENT_ID ORDER BY SEQ)               AS SEQ_OK
    FROM INCIDENT_AUDIT_LOG
)
SELECT INCIDENT_ID, COUNT(*) AS EVENTS, MAX(COALESCE(HASH_VERSION, 1)) AS HASH_VERSION,
       COUNT_IF(NOT HASH_OK) AS BAD_HASHES, COUNT_IF(NOT LINK_OK) AS BAD_LINKS,
       COUNT_IF(NOT SEQ_OK) AS SEQ_GAPS,
       (BAD_HASHES = 0 AND BAD_LINKS = 0 AND SEQ_GAPS = 0) AS CHAIN_OK
FROM x
GROUP BY INCIDENT_ID;

-- Runtime role: append events, read through views. No UPDATE, DELETE or TRUNCATE.
GRANT INSERT ON TABLE INCIDENT_AUDIT_LOG TO ROLE SCC_APP_ROLE;
GRANT SELECT ON VIEW V_INCIDENT_EVENTS TO ROLE SCC_APP_ROLE;
GRANT SELECT ON VIEW V_INCIDENT_STATUS TO ROLE SCC_APP_ROLE;
GRANT SELECT ON VIEW V_INCIDENT_CHAIN_CHECK TO ROLE SCC_APP_ROLE;
