-- =====================================================================================
-- Backlog #13 / ADR-030: anchor the incident audit-chain heads OUTSIDE the owner role.
-- Run as ACCOUNTADMIN in Snowsight (one script; it switches to SCC_AUDIT_ROLE for the objects).
--
-- Threat: SCC_DEV_ROLE owns SCC_DB.APP.INCIDENT_AUDIT_LOG, so it could UPDATE a row and recompute
-- every later hash; V_INCIDENT_CHAIN_CHECK would still say CHAIN_OK. The defence is a record of each
-- incident's latest (SEQ, EVENT_HASH) kept where that role cannot write: a separate database owned
-- by SCC_AUDIT_ROLE, which is granted to ACCOUNTADMIN only (not to SCC_DEV_ROLE, SYSADMIN or any
-- service user). Because every hash covers the previous one, anchoring the head protects all earlier
-- rows: editing any anchored row changes the head hash, and V_ANCHOR_CHECK reports the mismatch.
--
-- Cost: a daily serverless task (XSMALL) running one small INSERT ... SELECT.
-- Rollback (as ACCOUNTADMIN):
--   ALTER TASK SCC_AUDIT_DB.ANCHOR.ANCHOR_DAILY SUSPEND;  DROP DATABASE SCC_AUDIT_DB;
--   DROP ROLE SCC_AUDIT_ROLE;
-- =====================================================================================
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS SCC_AUDIT_ROLE
    COMMENT = 'Owns the incident audit-chain anchors (ADR-030). Granted to ACCOUNTADMIN only.';
GRANT ROLE SCC_AUDIT_ROLE TO ROLE ACCOUNTADMIN;

GRANT CREATE DATABASE ON ACCOUNT TO ROLE SCC_AUDIT_ROLE;
GRANT EXECUTE TASK ON ACCOUNT TO ROLE SCC_AUDIT_ROLE;          -- run tasks it owns
GRANT EXECUTE MANAGED TASK ON ACCOUNT TO ROLE SCC_AUDIT_ROLE;  -- serverless tasks
GRANT USAGE ON WAREHOUSE SCC_WH TO ROLE SCC_AUDIT_ROLE;        -- the setup CALL below

-- Read-only access to the log it anchors (granted via ACCOUNTADMIN's MANAGE GRANTS).
GRANT USAGE ON DATABASE SCC_DB TO ROLE SCC_AUDIT_ROLE;
GRANT USAGE ON SCHEMA SCC_DB.APP TO ROLE SCC_AUDIT_ROLE;
GRANT SELECT ON TABLE SCC_DB.APP.INCIDENT_AUDIT_LOG TO ROLE SCC_AUDIT_ROLE;

USE ROLE SCC_AUDIT_ROLE;
USE WAREHOUSE SCC_WH;

CREATE DATABASE IF NOT EXISTS SCC_AUDIT_DB
    COMMENT = 'Audit-chain anchors, owned by SCC_AUDIT_ROLE (outside the SCC_DB owner role).';
CREATE SCHEMA IF NOT EXISTS SCC_AUDIT_DB.ANCHOR;
USE SCHEMA SCC_AUDIT_DB.ANCHOR;

CREATE TABLE IF NOT EXISTS CHAIN_ANCHORS (
    ANCHORED_AT_UTC  TIMESTAMP_NTZ NOT NULL,
    INCIDENT_ID      VARCHAR       NOT NULL,
    HEAD_SEQ         NUMBER(38,0)  NOT NULL,
    HEAD_HASH        VARCHAR       NOT NULL,
    SOURCE           VARCHAR       NOT NULL   -- 'task' | 'setup' | 'probe' | 'manual'
)
COMMENT = 'Each incident''s latest (SEQ, EVENT_HASH) as observed at ANCHORED_AT_UTC. Insert-only by the procedure.';

-- Owner's rights: callers granted USAGE can add anchors but cannot change or delete existing ones.
-- Only heads not already anchored are inserted, so repeated calls are idempotent.
CREATE OR REPLACE PROCEDURE ANCHOR_CHAIN_HEADS(P_SOURCE VARCHAR)
RETURNS NUMBER
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
    t TIMESTAMP_NTZ DEFAULT SYSDATE();
    n NUMBER DEFAULT 0;
BEGIN
    INSERT INTO SCC_AUDIT_DB.ANCHOR.CHAIN_ANCHORS (ANCHORED_AT_UTC, INCIDENT_ID, HEAD_SEQ, HEAD_HASH, SOURCE)
    SELECT :t, h.INCIDENT_ID, h.SEQ, h.EVENT_HASH, :P_SOURCE
    FROM (
        SELECT INCIDENT_ID, SEQ, EVENT_HASH
        FROM SCC_DB.APP.INCIDENT_AUDIT_LOG
        QUALIFY ROW_NUMBER() OVER (PARTITION BY INCIDENT_ID ORDER BY SEQ DESC) = 1
    ) h
    WHERE NOT EXISTS (
        SELECT 1 FROM SCC_AUDIT_DB.ANCHOR.CHAIN_ANCHORS a
        WHERE a.INCIDENT_ID = h.INCIDENT_ID AND a.HEAD_SEQ = h.SEQ AND a.HEAD_HASH = h.EVENT_HASH
    );
    SELECT COUNT(*) INTO :n FROM SCC_AUDIT_DB.ANCHOR.CHAIN_ANCHORS WHERE ANCHORED_AT_UTC = :t;
    RETURN n;
END;
$$;

-- Compares every anchor with the log as it is now. MISSING = the anchored row is gone;
-- MISMATCHED = the row exists but its hash changed (history was rewritten).
CREATE OR REPLACE VIEW V_ANCHOR_CHECK
COMMENT = 'Per incident: ANCHOR_OK = FALSE means anchored history was rewritten or removed.'
AS
SELECT a.INCIDENT_ID,
       COUNT(*)                                          AS ANCHORS,
       MAX(a.HEAD_SEQ)                                   AS LATEST_ANCHORED_SEQ,
       MAX(a.ANCHORED_AT_UTC)                            AS LAST_ANCHORED_AT_UTC,
       COUNT_IF(l.EVENT_ID IS NULL)                      AS MISSING,
       COUNT_IF(l.EVENT_HASH <> a.HEAD_HASH)             AS MISMATCHED,
       (MISSING = 0 AND MISMATCHED = 0)                  AS ANCHOR_OK
FROM SCC_AUDIT_DB.ANCHOR.CHAIN_ANCHORS a
LEFT JOIN SCC_DB.APP.INCIDENT_AUDIT_LOG l
       ON l.INCIDENT_ID = a.INCIDENT_ID AND l.SEQ = a.HEAD_SEQ
GROUP BY a.INCIDENT_ID;

-- Daily serverless anchoring (created suspended; resumed below by its owner).
CREATE TASK IF NOT EXISTS ANCHOR_DAILY
    SCHEDULE = 'USING CRON 0 6 * * * UTC'
    USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
    COMMENT = 'Anchors incident audit-chain heads daily (ADR-030).'
AS
    CALL SCC_AUDIT_DB.ANCHOR.ANCHOR_CHAIN_HEADS('task');
ALTER TASK ANCHOR_DAILY RESUME;

-- Readers: the dev role (verification, on-demand anchoring) and the app role (show status).
-- Neither gets INSERT, UPDATE, DELETE or OWNERSHIP on anything in SCC_AUDIT_DB.
GRANT USAGE ON DATABASE SCC_AUDIT_DB TO ROLE SCC_DEV_ROLE;
GRANT USAGE ON SCHEMA SCC_AUDIT_DB.ANCHOR TO ROLE SCC_DEV_ROLE;
GRANT SELECT ON VIEW V_ANCHOR_CHECK TO ROLE SCC_DEV_ROLE;
GRANT USAGE ON PROCEDURE ANCHOR_CHAIN_HEADS(VARCHAR) TO ROLE SCC_DEV_ROLE;
GRANT USAGE ON DATABASE SCC_AUDIT_DB TO ROLE SCC_APP_ROLE;
GRANT USAGE ON SCHEMA SCC_AUDIT_DB.ANCHOR TO ROLE SCC_APP_ROLE;
GRANT SELECT ON VIEW V_ANCHOR_CHECK TO ROLE SCC_APP_ROLE;

-- First anchor now, then show the result.
CALL ANCHOR_CHAIN_HEADS('setup');
SELECT * FROM V_ANCHOR_CHECK ORDER BY INCIDENT_ID;
SHOW GRANTS TO ROLE SCC_AUDIT_ROLE;
