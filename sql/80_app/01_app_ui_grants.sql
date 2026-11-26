-- =====================================================================================
-- Phase 7 UI support objects and least-privilege grants. Run as SCC_DEV_ROLE:
--   python scripts/run_sql_file.py sql/80_app/01_app_ui_grants.sql
--
-- SCC_APP_ROLE gains only:
--   * SELECT on public-document metadata (DOCS.DOCUMENTS, DOCS.DOCUMENT_CHUNKS) for the KPI tile and
--     the citations panel (same public content the search service already exposes)
--   * INSERT (not SELECT/UPDATE/DELETE) on APP.AGENT_FEEDBACK for thumbs up/down
-- It still cannot read Bronze/Silver/Gold tables; dashboard numbers come from the semantic view.
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;

CREATE TABLE IF NOT EXISTS SCC_DB.APP.AGENT_FEEDBACK (
    FEEDBACK_ID      VARCHAR       NOT NULL,
    CREATED_AT_UTC   TIMESTAMP_NTZ NOT NULL,
    SESSION_ID       VARCHAR       NOT NULL,
    QUESTION         VARCHAR       NOT NULL,
    ANSWER_EXCERPT   VARCHAR,
    RATING           NUMBER(1,0)   NOT NULL,   -- 1 = helpful, -1 = not helpful
    COMMENT          VARCHAR,
    TOOLS_USED       VARCHAR,
    CITATION_COUNT   NUMBER(38,0),
    LATENCY_S        FLOAT,
    AGENT_STATUS     VARCHAR,
    APP_VERSION      VARCHAR,
    CONSTRAINT PK_AGENT_FEEDBACK PRIMARY KEY (FEEDBACK_ID)
)
COMMENT = 'User feedback from the SupplyChain Copilot UI. No credentials or personal data are stored.';

GRANT USAGE ON SCHEMA SCC_DB.DOCS TO ROLE SCC_APP_ROLE;
GRANT SELECT ON TABLE SCC_DB.DOCS.DOCUMENTS TO ROLE SCC_APP_ROLE;
GRANT SELECT ON TABLE SCC_DB.DOCS.DOCUMENT_CHUNKS TO ROLE SCC_APP_ROLE;

GRANT USAGE ON SCHEMA SCC_DB.APP TO ROLE SCC_APP_ROLE;
GRANT INSERT ON TABLE SCC_DB.APP.AGENT_FEEDBACK TO ROLE SCC_APP_ROLE;
