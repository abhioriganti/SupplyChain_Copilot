# SupplyChain Copilot

**An enterprise AI agent for supply-chain analytics and supplier knowledge retrieval, built on Snowflake Cortex.**

> Independent portfolio project. It uses only **public** data: the DataCo retail/e-commerce sample dataset (CC BY 4.0) and publicly published supplier and annual-report documents. It is not a Worthington Enterprises product and contains no company-internal data. See [docs/data_sources.md](docs/data_sources.md).

## What it does
- **Governed analytics:** natural-language questions → Cortex Analyst → SQL over a Snowflake **semantic view**, so every KPI has a single definition. 521 of 521 values reconcile independently, the view matches Gold on 14 of 14 checks (including governed margin, discount and order value), and Analyst passes 9 of 9 NL tests.
- **Document Q&A:** Cortex Search over public supplier-quality, code-of-conduct and annual-report PDFs, with page-level citations. hit@1 is 97% and hit@5 is 100% on a labelled set, and every word in a chunk is verified to appear on its cited page.
- **Hybrid agent:** a Cortex Agent picks one tool or both, and keeps measured data separate from policy guidance. 12 of 12 agent test cases pass, including unsafe and unsupported questions.
- **Trust:** a dedicated read-only runtime user (secondary roles disabled), visible SQL, citations, evaluation suites and SQL data-quality tests.
- **App:** a Streamlit UI with live KPIs, streamed chat, verified results, a sources panel, charts and feedback.
- **Evaluated:** a 37-case suite (structured, document, hybrid, ambiguous, unsupported, security, error handling) with SQL ground truth.
  - Over four runs it went 30/33 → 34/34 → 37/37, fixing the real defects it found and correcting evaluator mistakes with regression tests.
  - Shorter answers cut p95 latency from 32 to 25 s.
  - See [docs/evaluation_findings.md](docs/evaluation_findings.md).
  - Every request is logged to a monitoring table.
- **Red-teamed:** 7 indirect prompt-injection attacks planted in a sandbox copy of the document corpus (instruction override, exfiltration, phishing, destructive SQL, a fake causal claim, hidden markup and a spoofed manual section). The production agent configuration resisted all 6 instruction attacks and rejected the spoof; see [docs/redteam_findings.md](docs/redteam_findings.md).
- **Cost and access:** Cortex is granted explicitly to the two project roles (revoked from PUBLIC). An account budget alerts on spend, and the warehouse has a resource monitor.

## Architecture
```
DataCo CSV → Python ingest → BRONZE → SILVER → GOLD → Semantic View → Cortex Analyst ┐
Public PDFs → PyMuPDF → heading-aware chunks → DOCS table → Cortex Search ───────────┤→ Cortex Agent → Streamlit
```
Design decisions: [docs/architecture_decisions.md](docs/architecture_decisions.md) · Agent routing and controls: [docs/agent_architecture.md](docs/agent_architecture.md) · Progress: [docs/project_progress.md](docs/project_progress.md)

## Setup (Windows PowerShell)
```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python scripts\check_environment.py
```
Snowflake access uses key-pair auth with two service users:
- `SCC_SVC` builds the warehouse objects.
- `SCC_APP_SVC` is the read-only runtime user for the app and agent.

Private keys stay outside the repo. See `sql/00_setup/01_account_setup.sql`, `sql/70_agent/00c_app_service_user.sql` and `.env.example`.

## Run the app
```powershell
.venv\Scripts\streamlit run app\streamlit_app.py
```
See [docs/app_guide.md](docs/app_guide.md) for what's on screen and a 5–7 minute demo script.

## Tests
```powershell
.venv\Scripts\ruff check .
.venv\Scripts\pytest                                                   # unit + UI tests, no Snowflake needed
$env:SCC_RUN_SNOWFLAKE_TESTS="1"; .venv\Scripts\pytest -m snowflake    # live Snowflake tests (no Cortex cost)
.venv\Scripts\python -m supplychain_copilot.agent.evaluate --yes       # paid: 12 agent cases
```
