# Project progress

**Interview:** 2026-12-08 · **Current phase:** 3, Snowflake semantic view · **Status:** ✅ **Phase 3 complete** (2026-11-25). Next is Phase 4.

## Phase 3: native semantic view and Cortex Analyst (2026-11-25)

### Completed and verified
| Item | Evidence |
|---|---|
| Semantic view | `SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV`: 4 logical tables, 3 relationships, 6 facts, 21 dimensions, **14 metrics**, synonyms, comments, `AI_SQL_GENERATION`, `AI_QUESTION_CATEGORIZATION`, **3 verified queries**. DDL syntax checked against current docs. |
| Direct-SQL validation | `semantic.validate_view`: **9 of 9 pass**. All governed metrics equal reconciled Gold (overall, 23 regions, 4 modes, 37 months). Revenue by category sums to the total. Undefined dimension rejected at compile time. |
| Fan-out behaviour | Order metrics grouped by product category (a many-to-many bridge) equal `COUNT(DISTINCT order)` in **51 of 51** categories. A naive join inflates 29. |
| Cortex Analyst (REST, `semantic_view`) | `semantic.nl_tests --yes`: **9 of 9 pass**. Generated SQL executed and matched ground truth for all 6 required questions plus revenue and Western Europe. The supplier question correctly got no SQL and an explanation instead. |
| Governance behaviour observed | All generated SQL references governed metrics via `SEMANTIC_VIEW(... METRICS ...)` and never recomputes them. The monthly question was grouped by month × market as instructed. Q2 used verified query `LATE_RATE_BY_REGION`. |
| pytest | **44 passed, 1 skipped** live (the skip is the paid Cortex test, run separately: 9/9). **40 passed, 5 skipped** in CI mode. Phase 2 SQL suite re-run: 38 of 38. `ruff` clean. |
| Docs | `docs/semantic_layer.md`, `docs/business_glossary.md`, `docs/semantic_test_report.md` (generated), ADR-017 |

### Limitations
- `AI_SQL_GENERATION` guides a model and isn't an enforced rule; the NL test suite is the check.
- Analyst NL tests cost Cortex credit, so they're opt-in (`SCC_RUN_CORTEX_TESTS=1`) and excluded from CI.
- Semantic view grants to `SCC_APP_ROLE` are deferred to Phase 4.

### Files (Phase 3)
`sql/40_semantic/01_supply_chain_delivery_sv.sql`, `src/supplychain_copilot/semantic/{__init__,analyst,validate_view,nl_tests}.py`, `tests/test_semantic.py`, `docs/{semantic_layer,business_glossary,semantic_test_report}.md`, updated `docs/{architecture_decisions,project_progress}.md`, `pyproject.toml`

## Phase 2: Snowflake Bronze, Silver and Gold (2026-11-25)

**Database:** existing `SCC_DB` (BRONZE, SILVER, GOLD, APP schemas from Phase 0), not a new `SUPPLYCHAIN_COPILOT` database. This reuses the approved roles, grants and warehouse.

### Build order (reproducible)
```powershell
.venv\Scripts\python scripts\run_sql_file.py sql\10_bronze\01_bronze_tables.sql
.venv\Scripts\python -m supplychain_copilot.warehouse.load_bronze
.venv\Scripts\python scripts\run_sql_file.py sql\20_silver\01_silver_order_lines.sql
.venv\Scripts\python scripts\run_sql_file.py sql\30_gold\01_gold_model.sql
.venv\Scripts\python scripts\run_sql_file.py sql\30_gold\02_kpi_views.sql
.venv\Scripts\python scripts\run_sql_tests.py sql\tests\test_phase2_model.sql
.venv\Scripts\python -m supplychain_copilot.warehouse.reconcile
```

### Completed and verified
| Item | Evidence |
|---|---|
| Bronze load | `write_pandas` → `BRONZE.DATACO_ORDER_LINES`. File rows = loaded rows = table rows = **180,519**, recorded in `BRONZE.LOAD_AUDIT`. Append-only with `LOAD_ID` and `INGESTED_AT_UTC`. |
| Bronze fidelity | Spot check against the Parquet: timestamp min/max, total net sales 33,054,402.38, 65,752 orders, 9,737 DQ flags, a sampled row, and accented text (`São Paulo`, `Ústí nad Labem`) all identical |
| Silver | `SILVER.ORDER_LINES` from the latest successful load; dedup by `ORDER_ITEM_ID` (0 removed, logged in `SILVER_BUILD_LOG`); derived date, month, delay and cancel flags; no imputation |
| Gold | `DIM_PRODUCTS` (118), `DIM_REGIONS` (23), `FACT_ORDERS` (65,752 = shipments), `FACT_ORDER_LINES` (180,519). Grain is stated in every table comment. PK/FK declared (informational) and tested. |
| KPI views | `V_KPI_OVERALL`, `V_KPI_BY_REGION`, `V_KPI_BY_SHIPPING_MODE`, `V_KPI_BY_MONTH` (the last includes `MARKETS_ACTIVE` and `MARKET_LIST`) |
| SQL tests | `sql/tests/test_phase2_model.sql`: **38 of 38 pass** (Bronze 2, Silver 8, Gold 27, governance 1). Results persisted to `APP.DQ_TEST_RESULTS`. |
| Independent reconciliation | pandas from the Parquet against the Snowflake views: **521 of 521 comparisons match** (overall, 23 regions, 4 modes, 37 months) |
| pytest | **39 passed** with live Snowflake tests on; 36 passed and 3 skipped without (as in CI). `ruff` clean. |

### Headline values (governed; DataCo public sample, not Worthington data)
Distinct orders **65,752** · order lines **180,519** · revenue **31,644,665.08** · eligible shipments **62,897** · late **36,048** · late rate **57.31%** · on-time rate **42.69%** · avg actual days **3.50** · avg days late **1.62**

### Key findings
1. **Shipping mode, not region, separates late from on-time:** First Class 100% late (always 2 days against 1 scheduled), Second Class 80%, Same Day 48%, Standard 40%. Region late rates span only 52.6–60.0%. This is descriptive, not causal.
2. **Fan-out risk is real:** summing order totals after a join to lines gives 3.49× the true revenue. The semantic view must encode the grains (Phase 3).
3. The line-grain late-rate error is small on this data (0.02 pp), but including canceled shipments in the denominator moves the rate by 2.49 pp.

### Decisions
ADR-014 (no FACT_SHIPMENTS), ADR-015 (revenue definition), ADR-016 (FLOAT rates).

### Limitations
- PK/FK constraints aren't enforced by Snowflake; integrity relies on the SQL test suite, which must run after every build.
- Revenue is booked (status-based), not recognised revenue; the source has no invoicing data.
- The build is a sequence of commands, not an orchestrated DAG. That's adequate for a single static source.

### Files (Phase 2)
`sql/10_bronze/01_bronze_tables.sql`, `sql/20_silver/01_silver_order_lines.sql`, `sql/30_gold/{01_gold_model,02_kpi_views}.sql`, `sql/tests/test_phase2_model.sql`, `src/supplychain_copilot/warehouse/{__init__,load_bronze,sql_tests,reconcile}.py`, `scripts/run_sql_tests.py`, `tests/test_warehouse.py`, `docs/{metric_definitions,reconciliation_report}.md`, updated `docs/{architecture_decisions,project_progress}.md`

## Phase 1: data acquisition, profiling and cleaning (2026-11-25)

### Completed and verified
| Task | Evidence |
|---|---|
| Acquisition | Manual Mendeley download, documented in `docs/data_sources.md`. `download_data.py` verifies all 5 files against SHA-256 values in `data/manifest.json` → all OK. |
| Encoding, columns, rows | cp1252 (UTF-8 decode fails; C1 bytes 0x8a/0x8e/0x92 present), CRLF, 53 columns, **180,519 rows** |
| Orders vs lines | **65,752 distinct orders**, 180,519 distinct order lines, 1–5 lines per order (mean 2.75), 20,652 customers, 118 products |
| Date range | Orders 2015-01-01 → 2018-01-31 (37 months). 100% of dates parse. No shipment precedes its order. |
| Duplicates | 0 exact duplicate rows, and 0 duplicates ignoring `Order Item Id` |
| Missing values | Product Description 100% and Order Zipcode 86.24% (both dropped); Customer Lname 8 and Customer Zipcode 3 (both dropped as PII). No other empty values. |
| Grain | All 16 order-level attributes are constant within every order → ADR-008 **accepted**. `Order Profit Per Order` is line-level (misnamed). Department is a product attribute. |
| Late / cancel semantics | `late_delivery_risk=1` ⇔ 'Late delivery'. For non-canceled lines, late ⇔ actual > scheduled days. 'Shipping canceled' ⇔ order_status CANCELED or SUSPECTED_FRAUD (7,754 lines, 2,855 orders). |
| Sensitive fields | Email, password, names, street, zip, customer geo and lat/long all dropped. Tests assert they are absent. |
| Cleaning | 32 kept columns renamed to snake_case and typed; whitespace normalised (distinct counts unchanged); lineage + `dq_ship_ts_mismatch` added; row count preserved |
| Validation | **26 error checks pass**, 4 warnings (known quirks): Same Day ship timestamps (9,737 lines), canceled-but-late days (4,423), negative profit (33,784), "Electronics" → 2 category ids |
| Export | `data/processed/dataco_order_lines.parquet` (7.6 MB) + `dataco_validation.json`, both gitignored |
| Docs | `docs/profiling_report.md` (generated from data), `docs/data_dictionary.md`, `docs/data_sources.md`, ADR-008 accepted, ADR-011 to ADR-013 added |
| Tests | `pytest` → **33 passed, 1 skipped**: 21 new ingestion tests (16 fixture-based, 5 on the real file). `ruff check .` → clean |

### Key findings for later phases
1. **Market rotation (ADR-011):** 26 of 37 months contain one market only, so monthly trends are confounded with market. The agent must caveat trend questions.
2. **Same Day timestamps** are always order + 12h. Durations come from `days_shipping_actual` only.
3. **Canceled shipments** must be excluded from delivery KPIs; 4,423 canceled lines show actual > scheduled days.
4. **Revenue choice** for Phase 2: `net_sales` (after discount) or `gross_sales`. Both identities are verified at 100%.
5. **No supplier or manufacturing fields exist.** The agent must not imply supplier attribution from this data.

### Not done / limitations
- Automated download wasn't implemented (Mendeley is a browser download page). It's a documented manual step with hash verification.
- ~~Phase 0 Cortex spend unmeasured~~. Measured below.

### Measured credit usage through end of Phase 1
`SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY`, `START_TIME >= 2026-11-25`, run by the account owner as ACCOUNTADMIN:

| Service type | Credits |
|---|---|
| WAREHOUSE_METERING | 0.2186 |
| AI_SERVICES | 0.2010 |
| CORTEX_AGENTS | 0.1065 |
| AI_FUNCTIONS | 0.0001 |
| PIPE, TELEMETRY_DATA_INGEST, AUTO_CLUSTERING | 0.0000 |
| **Sum of rows** | **0.5262** |

This covers both smoke-test runs, all connectivity checks and schema creation. The view lags by up to a few hours, so very recent activity may be missing. Whether `CORTEX_AGENTS` is also counted inside `AI_SERVICES` hasn't been verified, so the sum is an upper bound.

### Files (Phase 1)
`data/manifest.json`, `src/supplychain_copilot/ingestion/{__init__,schema,download_data,clean_orders,profile_data}.py`, `tests/test_ingestion.py`, `docs/{profiling_report,data_dictionary}.md`, updated `docs/{data_sources,architecture_decisions,project_progress}.md`

## Account facts (from Snowsight, 2026-11-25)
| Item | Value |
|---|---|
| Cloud / region | AWS `AWS_US_WEST_2` (Oregon) |
| Edition | Enterprise (trial, 30 days, $400 credit) |
| `CORTEX_ENABLED_CROSS_REGION` | `ANY_REGION` (no change needed) |
| Account identifier | kept in local `.env` only |

## Phase 0: environment and feasibility

### Completed and verified
| Task | Evidence |
|---|---|
| OS and tools checked | Windows 11 Pro 10.0.26300; Python 3.12.10; Git 2.49; VS Code; GitHub CLI logged in; Docker 27.5 installed (daemon not running, not needed yet) |
| Project gets its own git repo | `git init -b main` in the project folder. Previously the folder sat inside a git repo at the user's home directory, which is now kept separate. |
| venv (Python 3.12) and dependencies | `pip install -e ".[dev]"` succeeded; exact versions in `requirements.lock` |
| Required libraries import | `scripts/check_environment.py` → all PASS |
| Streamlit runs | `streamlit hello` headless → `/_stcore/health` returned `ok` |
| Lint | `ruff check .` → all checks passed; `ruff format --check .` → formatted |
| Unit tests | `pytest` → **12 passed, 1 skipped** (the live Snowflake test is skipped until `.env` exists) |
| No secrets staged | `git add --dry-run .` lists only source files. `data/raw/`, `.env` and `.venv` confirmed ignored. |
| Docs checked (2026-11-25) | Syntax and privileges for CREATE USER (TYPE=SERVICE), key-pair JWT, `USE AI FUNCTIONS`, semantic views, Analyst REST, Cortex Search, CREATE AGENT and `:run`, resource monitors |

### Account setup (done by the account owner, 2026-11-25)
1. Key pair generated with `scripts/generate_keypair.py`; private key stored outside the repo.
2. `sql/00_setup/01_account_setup.sql` run in Snowsight as ACCOUNTADMIN.
3. `.env` created locally (gitignored).

### Snowflake verification (run by Claude, 2026-11-25)
| Check | Result |
|---|---|
| `run_sql_file.py sql/00_setup/02_schemas.sql` as `SCC_SVC` / `SCC_DEV_ROLE` | ✅ 7 schemas created; key-pair auth works |
| `check_snowflake.py` | ✅ role `SCC_DEV_ROLE`, warehouse `SCC_WH` (X-Small, 60s), region `AWS_US_WEST_2`, Snowflake 10.42.104, all expected grants incl. `SNOWFLAKE.CORTEX_USER` and `USE AI FUNCTIONS` |
| `pytest -m snowflake` | ✅ 1 passed |
| Resource monitor attached to `SCC_WH` | ✅ `SCC_WH_MONITOR`, confirmed as ACCOUNTADMIN. The dev role sees `null` because it lacks visibility of the monitor. |

### Cortex feasibility: `smoke_cortex.py --yes`, tested on this account
| Capability | Result | Evidence |
|---|---|---|
| Semantic view (create + `SEMANTIC_VIEW()` query) | ✅ PASS | Results matched expected values exactly |
| Cortex Analyst REST (`semantic_view`) | ✅ PASS | Generated `SELECT * FROM SEMANTIC_VIEW(... DIMENSIONS region METRICS late_order_count)`, which executed correctly |
| AI_COMPLETE (`llama3.1-8b`, `claude-sonnet-4-5`) | ❌ BLOCKED | `399258: AI function ... is not available for trial accounts` |
| Cortex Search (create service) | ❌ BLOCKED | `399258: AI function EMBED_TEXT_768 is not available for trial accounts` |
| Cortex Agents: `CREATE AGENT` | ✅ object created | — |
| Cortex Agents: `:run` over REST (Analyst tool only) | ❌ BLOCKED | `HTTP 400, code 399504: Access denied for trial accounts` |
| Cleanup | ✅ all sandbox objects dropped | — |

**Root cause (Snowflake docs, [Trial accounts](https://docs.snowflake.com/en/user-guide/admin-trial-account)):** "AI features are disabled by default on self-service trial accounts. To enable them, add a credit card to the account." The same page says adding a card "doesn't upgrade the trial to a paid account or end the trial period", and that AI features consume the free credits.

**Resolution:** the account owner added a credit card (Admin → Billing → Payment method). The trial was **not** upgraded. A fallback stack was not adopted (ADR-001).

### Re-run after adding the card: `smoke_cortex.py --yes` (2026-11-25)
| Probe | Result |
|---|---|
| AI_COMPLETE `llama3.1-8b` (native) | ✅ PASS |
| AI_COMPLETE `claude-sonnet-4-5` (cross-region) | ✅ PASS |
| Semantic view | ✅ PASS (exact expected values) |
| Cortex Analyst REST | ✅ PASS (SQL executed, correct rows) |
| Cortex Search (create + `SEARCH_PREVIEW`) | ✅ PASS (correct top hit) |
| Cortex Agent REST, both tools, non-streaming | ✅ PASS. Answer: "2 late orders" in WEST; corrective action plan "within 30 days of a nonconformance". Both `orders_analyst` and `policy_search` appear in the response. |
| Cleanup | ✅ all sandbox objects dropped |

Observed response shape for agent `:run` (non-streaming): top-level keys `content, metadata, role, schema_version, sequence_number, status`. This will be used to build the typed client in Phase 4.

### Phase 0 acceptance criteria
| Criterion | Status |
|---|---|
| Python environment works | ✅ |
| Required libraries import | ✅ |
| Snowflake connectivity tested | ✅ |
| Cortex permissions and availability understood | ✅ verified by live probes |
| No credentials exposed | ✅ key outside repo, `.env` ignored, scan clean |

**Resource monitor:** ✅ confirmed by the account owner as ACCOUNTADMIN: `SCC_WH.resource_monitor = SCC_WH_MONITOR`. The dev role sees `null` only because it has no privileges on the monitor.
**Still open (minor):** measured smoke-test spend is pending, because `ACCOUNT_USAGE` lags by up to a few hours. It will be recorded at the start of Phase 1.

### Expected costs (to be measured, not estimated)
- Warehouse: X-Small at 1 credit/hour while running, 60-second auto-suspend, 25-credit monthly monitor.
- Cortex (Analyst messages, Agent tokens, Search index size and serving, AI_COMPLETE tokens): billed outside the resource monitor. After the smoke test, actual usage will be read from `SNOWFLAKE.ACCOUNT_USAGE` (that view lags by up to a few hours).

## Files created in Phase 0
`pyproject.toml`, `requirements.lock`, `.gitignore`, `.env.example`, `README.md`, `.github/workflows/ci.yml`,
`src/supplychain_copilot/{__init__,config}.py`, `src/supplychain_copilot/snowflake/{__init__,keys,connection,rest}.py`,
`scripts/{check_environment,check_snowflake,generate_keypair,run_sql_file,smoke_cortex}.py`,
`sql/00_setup/{01_account_setup,02_schemas}.sql`, `tests/{test_config,test_keys_and_jwt,test_snowflake_live}.py`,
`docs/{project_progress,architecture_decisions,data_sources}.md`

## Blockers
- **B-001 (resolved 2026-11-25):** The trial account disabled AI features (errors `399258` and `399504`). Resolved by adding a credit card. All probes now pass.

## Remaining phases (plan)
1. Data ingestion: profile DataCo, Bronze → Silver → Gold, reconciliation tests
2. Governed metrics and semantic view, Cortex Analyst
3. Document extraction, chunking, Cortex Search
4. Cortex Agent (hybrid), app role grants, guardrails
5. Streamlit UI, evaluation set, logging and feedback
6. Optional: n8n incident workflow
