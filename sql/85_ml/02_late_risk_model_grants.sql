-- =====================================================================================
-- Let the app's runtime role CALL the late-delivery risk model, and nothing more (ADR-032).
-- Run as SCC_DEV_ROLE after `python -m supplychain_copilot.ml.late_risk --register --yes`:
--   .venv\Scripts\python scripts\run_sql_file.py sql\85_ml\02_late_risk_model_grants.sql
--
-- USAGE on a model allows warehouse inference without access to its internals (READ would add
-- metadata and file access). SCC_APP_ROLE gets no SELECT on V_LATE_RISK_FEATURES or GOLD: the app
-- sends the what-if values itself, so the model never exposes rows it was trained on.
-- =====================================================================================
USE ROLE SCC_DEV_ROLE;
GRANT USAGE ON SCHEMA SCC_DB.ML TO ROLE SCC_APP_ROLE;
GRANT USAGE ON MODEL SCC_DB.ML.LATE_DELIVERY_RISK TO ROLE SCC_APP_ROLE;
SHOW VERSIONS IN MODEL SCC_DB.ML.LATE_DELIVERY_RISK;
