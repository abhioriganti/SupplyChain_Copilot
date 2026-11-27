# SupplyChain Copilot: app setup and demo guide

## Run locally (Windows PowerShell)

```powershell
# from the project root
.venv\Scripts\streamlit run app\streamlit_app.py
```

Open http://localhost:8501.

**Prerequisites:**
- `.env` contains the **runtime user** (`SNOWFLAKE_APP_USER=SCC_APP_SVC`, `SNOWFLAKE_APP_PRIVATE_KEY_PATH=...`); see `.env.example` and `sql/70_agent/00c_app_service_user.sql`.
- The Cortex Search service is serving (`ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH RESUME SERVING;` if it was suspended).
- The warehouse resumes automatically.

If the runtime user isn't configured, the app fails closed: it shows a warning and never falls back to developer credentials.

## What's on the screen

| Area | Content | Source |
|---|---|---|
| Header | Title, subtitle, **disclaimer** (independent prototype; DataCo public sample data is not Worthington data; documents are public) | static |
| KPI row | Unique orders, late-delivery rate, average shipping duration, indexed documents | live: semantic view metrics plus `DOCS.DOCUMENTS` (cached 10 minutes) |
| 💬 Ask the Copilot | Chat with history, a "Thinking…" status, answers with tool badges and latency, **🔎 Verified results and SQL** (the result set the agent got plus its SQL, marked steward-verified where applicable), **📚 Sources** (document, section, PDF page linked to `#page=N`, version, snippet), agent-built charts, 👍/👎 | Cortex Agent called as `SCC_APP_SVC` / `SCC_APP_ROLE` |
| 📈 Delivery dashboard | Late rate by region (23); on-time rate by shipping mode; monthly late rate by market (gaps where a market is absent; market-months with <100 shipments hidden) | live: semantic view |
| 📚 Sources | The 3 public documents with version, date, pages indexed, passages and a PDF link | `DOCS.DOCUMENTS` |
| Sidebar | Suggested questions (including the required hybrid question), clear conversation, agent/role info | — |

## Security in the UI

- **Runtime identity:** `SCC_APP_SVC`, holding only `SCC_APP_ROLE` with no secondary roles.
  - Allowed: SELECT on the semantic view and document tables, USAGE on the search service and agent, INSERT on the feedback table.
  - Not allowed: raw-table reads, or any write other than feedback.
- **No secrets in the browser:** credentials load server-side from `.env`. `client.showErrorDetails = "none"` hides tracebacks, and errors show friendly text (tested: a failure message containing an account name isn't displayed).
- **Feedback** stores question, answer excerpt, rating, tools, citation count and latency, with credential patterns redacted. If Snowflake is unavailable it falls back to `logs/feedback.jsonl` (gitignored).

## Stopping and restarting (idle cost)

While idle, only the two Cortex Search services cost money (serving is billed per GB-month). The warehouse auto-suspends after 60 s.

- **Stop:** `.venv\Scripts\python scripts\run_sql_file.py sql\90_ops\01_suspend_when_idle.sql`, then `docker compose --env-file .env -f n8n/docker-compose.yml stop`.
- **Start:** `.venv\Scripts\python scripts\run_sql_file.py sql\90_ops\02_resume_for_demo.sql`, then start n8n, the callback API and Streamlit as in the README. In a test on 2026-11-27, both services answered within 2 s of resuming.

## Tests

```powershell
.venv\Scripts\pytest tests\test_ui.py      # 18 tests: modules + real page via streamlit AppTest (no Snowflake)
```
