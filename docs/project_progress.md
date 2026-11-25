# Project progress

**Interview:** 2026-12-08 · **Current phase:** 0, Environment setup and Snowflake feasibility · **Status:** local setup done, Snowflake steps waiting on the account owner

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

### Waiting on the account owner (not yet verified)
1. Generate the key pair: `scripts/generate_keypair.py`.
2. Run `sql/00_setup/01_account_setup.sql` in Snowsight as ACCOUNTADMIN.
3. Create `.env` from `.env.example`.

Then Claude runs:

4. `run_sql_file.py sql/00_setup/02_schemas.sql`
5. `check_snowflake.py`
6. `smoke_cortex.py --yes` (small Cortex cost)

### Cortex feasibility: per current docs, not yet tested on this account
| Capability | Docs say | Tested on account? |
|---|---|---|
| AI_COMPLETE | Native in us-west-2 (e.g. `llama3.1-8b`); frontier models via cross-region | ⏳ |
| Semantic views | `CREATE SEMANTIC VIEW`; some sub-features in preview | ⏳ |
| Cortex Analyst | Native in AWS us-west-2; REST `/api/v2/cortex/analyst/message` | ⏳ |
| Cortex Search | `CREATE CORTEX SEARCH SERVICE`; owner's-rights queries | ⏳ |
| Cortex Agents | `CREATE AGENT … FROM SPECIFICATION`; REST `…/agents/{name}:run`; not supported from SiS warehouse runtime | ⏳ |
| Trial restrictions | Not stated in the docs we read | ⏳ To be found by testing |

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
- None technical. Snowflake verification waits on the three account-owner steps above.

## Remaining phases (plan)
1. Data ingestion: profile DataCo, Bronze → Silver → Gold, reconciliation tests
2. Governed metrics and semantic view, Cortex Analyst
3. Document extraction, chunking, Cortex Search
4. Cortex Agent (hybrid), app role grants, guardrails
5. Streamlit UI, evaluation set, logging and feedback
6. Optional: n8n incident workflow
