# Backup plan and pre-demo checklist

## Pre-demo checklist (morning of 2026-12-08)
1. **One app server only.** Close every old terminal running Streamlit, then start a single server:
   ```powershell
   .venv\Scripts\streamlit run app\streamlit_app.py
   ```
   It must be on **http://localhost:8501**. If it reports another port, an old server is still running. On 2026-11-26 a stale server from before a code change was still holding port 8501, serving the old UI.
2. **Snowflake is up:** the app bar shows **● Live** (not "⚠️ Offline") and the KPI cards show 65,752 / 57.3% / 3.50 days / 3.
3. **The search service is serving:** in Snowsight, `SHOW CORTEX SEARCH SERVICES IN SCHEMA SCC_DB.AI;` should show `serving_state = ACTIVE`. If it's suspended, run `ALTER CORTEX SEARCH SERVICE SCC_DB.AI.SUPPLIER_DOCS_SEARCH RESUME SERVING;` and allow a few minutes.
4. **Warm the cache in the same browser tab you'll present from:** click each of the three welcome cards once. The cache is per browser session, so refreshing the tab clears it. During the demo the answers return instantly, labelled "Reused from earlier in this session". If asked, say so honestly: *"I pre-ran these to save time; 'Ask again live' re-runs it."*
5. **Optional, for the Incidents tab:** run `docker compose --env-file .env -f n8n/docker-compose.yml up -d`, then `.venv\Scripts\python -m supplychain_copilot.incidents.api` in a second terminal.
6. **Have open in other tabs:** the README on GitHub (diagram), this file, and `docs/images/` (screenshots).
7. **Credits:** the Snowsight balance and the account budget (50 credits a month). The demo uses roughly 0.5 credits.
8. **Trial ends about 2026-12-25.** No action needed before the interview.

## Verified outputs (queried directly in Snowflake, 2026-11-26)
These are the numbers the demo questions should produce. If the live agent is unavailable, show these together with the SQL.

| Question | Verified answer | Source query |
|---|---|---|
| Headline KPIs | 65,752 orders · 62,897 eligible shipments · 36,048 late · **late rate 57.3%** · on-time 42.7% · avg 3.50 days · revenue 31.6M · margin 12.0% | `SEMANTIC_VIEW(... METRICS orders.total_orders, orders.late_delivery_rate, …)` |
| Highest late-delivery regions | **Central Africa 60.0%** (320/533) · East Africa 59.1% (348/589) · South of USA 58.8% (753/1,280) · West Asia 58.5% (1,132/1,935) · Western Europe 58.4% (5,585/9,563) | `SEMANTIC_VIEW(... DIMENSIONS regions.order_region METRICS orders.late_delivery_rate …) ORDER BY late_delivery_rate DESC` |
| On-time by shipping mode | Standard Class 60.2% · Same Day 51.6% · Second Class 20.0% · **First Class 0.0%** (late on 100% of 9,602 shipments, a pattern built into the dataset) | `… DIMENSIONS orders.shipping_mode …` |
| Corrective-action deadlines | Containment **2 working days**, corrective and preventive actions **14**, effectiveness **30** (SQAM §7.2, PDF p. 29); protect receiving plants and acknowledge within **48 hours** (§7.1, pp. 27–29) | `DOCS.DOCUMENT_CHUNKS`, section 7.2, page 29 |
| Why the semantic view matters | A naive lines × orders join inflates revenue **3.49×** | Direct Gold query vs `SEMANTIC_VIEW` |
| Data caveat | **26 of 37** months contain a single market | `GOLD.V_KPI_BY_MONTH` |

## Evaluation summary (for a slide or a verbal answer)
- **Final run (run 5): 37 of 37** on first scoring. Privilege probes 13 of 13; SQL suites 38 of 38 and 13 of 13; every SQL statement via the semantic view.
- **History:**
  - Run 1, 30/33: real defects found. The agent did its own arithmetic and once leaked a process note; there were also evaluator errors.
  - Runs 2–4: fixes, and a missing quarter dimension that caused a semantic-view bypass, blocked by least privilege.
- **Retrieval:** hit@1 96.7%, hit@5 100%.
- **Red-team:** 6 of 6 injected-instruction attacks resisted.
- **Latency:** p50 13.7 s and p95 24.9 s. About 0.09 credits per question.

## Screenshots
In `docs/images/`, all taken from the live app on 2026-11-26:
- `app_home.png`: app bar, notice, KPI cards, welcome cards, system status
- `app_hybrid_answer.png`: the main hybrid question, with both tool chips, the stated definition, no causal claim and three SQAM citations
- `app_dashboard.png`: late-delivery rate by region, coloured by market
- `app_incidents.png`: the simulated incident form (the status table is left out because it shows approver names)

## Recording a backup video
No screen recorder was available in the build environment, so record one yourself the day before:
- **Windows Snipping Tool → Record** (or Win + Shift + R) records a region with system audio off by default.
- Follow `demo_script.md` once, end to end, in about 6 minutes.
- Keep the file **local**. If you upload it anywhere, check that no `.env`, Snowsight secrets or Slack URLs are visible on screen.

## Offline walkthrough (no network or Snowflake)
Use the README (diagram and screenshots) and this file, and narrate:
1. **Problem (30 s):** numbers in the warehouse, procedures in PDFs, inconsistent definitions. Show `app_home.png`.
2. **Architecture (45 s):** walk the Mermaid diagram left to right: ingest, Bronze/Silver/Gold, semantic view and Analyst, PDFs and Search, the agent, Streamlit, and the controls box.
3. **Governed metric (60 s):** show the verified-outputs table above. "The late rate is defined once: late over eligible, canceled excluded. The naive join inflates revenue 3.49×; the view doesn't, and a test proves it."
4. **Cited answer (60 s):** show `app_hybrid_answer.png`. Point at the two tool chips, the definition, the "can't tell you whether any delay was caused by supplier quality" sentence, and the §7.1, §7.2 and §1.2 citations with pages.
5. **Safeguard (45 s):** the least-privilege role and the 13 probes; the red-team table in `docs/redteam_findings.md`; the audit-chain tampering proof in `docs/incident_workflow.md`.
6. **Evaluation (30 s):** the summary above, including that the first run *failed* three cases and what that taught.
7. **Production path (30 s):** SSO, real ERP and document sources, per-tier search services, scheduled refresh, an evaluation-gated release, then a pilot on one decision.
