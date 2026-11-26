# SupplyChain Copilot: app setup and demo guide

## Run locally (Windows PowerShell)

```powershell
cd "C:\Users\abhis\projects\SupplyChain Copilot"
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

## 5-to-7-minute demo script

1. **Framing (30 s):** read the disclaimer, then point at the KPIs: "These come live from the governed semantic view, the same definitions the agent uses."
2. **Structured (1 min):** click *"Which shipping mode has the best on-time performance?"* → Standard Class 60.2% (22,637 of 37,632). Open **Verified results and SQL**: `SEMANTIC_VIEW(... METRICS orders.on_time_delivery_rate ...)`. "The model chose a governed metric; it didn't write its own formula."
3. **Document (1 min):** click *"What are the supplier corrective-action deadlines?"* → 2 / 14 / 30 working days. Open the **Sources** link, which opens the PDF at page 29.
4. **Hybrid (1.5 min):** click the long hybrid suggestion → regions with rates and counts, plus cited procedures, and the explicit line that delays don't prove supplier-quality issues.
5. **Governance story (1.5 min):**
   - The semantic view prevents metric drift (a fan-out join inflates revenue 3.49×).
   - Least privilege had to be *tested*: secondary roles made the "read-only" role able to DELETE until the dedicated runtime user fixed it.
6. **Dashboard (30 s):** the monthly chart and its caption about market rotation, which shows the data was profiled before it was trusted.
7. **Close:** feedback goes to `APP.AGENT_FEEDBACK`. Production next steps are Phase 8.

**Timing:**
- Agent answers take about 15–35 s in total.
- Live progress appears within about 2–5 s and shows the steps and the actual search query.
- **Rehearse each suggested question once before presenting.** Repeats are then served instantly from the session cache, labelled "reused from earlier in this session".
- Use **🔄 Ask again live** if someone wants to see a fresh run.
- Start the hybrid question while you narrate, and have a backup recording or screenshots ready.

## Tests

```powershell
.venv\Scripts\pytest tests\test_ui.py      # 18 tests: modules + real page via streamlit AppTest (no Snowflake)
```
