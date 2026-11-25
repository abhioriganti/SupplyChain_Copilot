# SupplyChain Copilot

**An enterprise AI agent for supply-chain analytics and supplier knowledge retrieval, built on Snowflake Cortex.**

> Independent portfolio project. It uses only **public** data: the DataCo retail/e-commerce sample dataset (CC BY 4.0) and publicly published supplier and annual-report documents. It is not a Worthington Enterprises product and contains no company-internal data. See [docs/data_sources.md](docs/data_sources.md).

## What it does (target)
- **Governed analytics:** natural-language questions → Cortex Analyst → SQL over a Snowflake **semantic view**, so every KPI has a single definition.
- **Document Q&A:** Cortex Search over public supplier-quality, code-of-conduct and annual-report PDFs, with page-level citations.
- **Hybrid agent:** a Cortex Agent picks one tool or both, and keeps measured data separate from policy guidance.
- **Trust:** least-privilege roles, a read-only runtime role, visible SQL, evaluation tests.

## Architecture
```
DataCo CSV → Python ingest → BRONZE → SILVER → GOLD → Semantic View → Cortex Analyst ┐
Public PDFs → PyMuPDF → heading-aware chunks → DOCS table → Cortex Search ───────────┤→ Cortex Agent → Streamlit
```
Design decisions: [docs/architecture_decisions.md](docs/architecture_decisions.md) · Progress: [docs/project_progress.md](docs/project_progress.md)

## Setup (Windows PowerShell)
```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python scripts\check_environment.py
```
Snowflake access uses key-pair auth with a service user. The private key stays outside the repo. See `sql/00_setup/01_account_setup.sql` and `.env.example`.

## Tests
```powershell
.venv\Scripts\ruff check .
.venv\Scripts\pytest                     # unit tests, no Snowflake needed
$env:SCC_RUN_SNOWFLAKE_TESTS="1"; .venv\Scripts\pytest -m snowflake   # live tests
```
