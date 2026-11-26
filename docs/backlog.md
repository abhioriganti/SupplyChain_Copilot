# Backlog: known limitations and suggested improvements

This is a consolidated list from Phases 0–10, so the work can be picked up later. The details and evidence for each item are in `docs/project_progress.md`, `docs/architecture_decisions.md` and the phase reports.

## Current state (2026-11-26, Phase 10)

| Area | Status |
|---|---|
| Data | DataCo loaded through Bronze, Silver and Gold. 38 SQL tests; 521/521 values reconcile independently. |
| Semantic view | `SCC_DB.AI.SUPPLY_CHAIN_DELIVERY_SV`, 20 metrics, 24 dimensions. Matches Gold on 14/14 checks; Analyst passes 9/9 NL tests. |
| Documents | 152 chunks; 13 SQL tests pass; every word in every chunk verified to appear on its cited page |
| Search | `SCC_DB.AI.SUPPLIER_DOCS_SEARCH`: hit@1 96.7%, hit@5 100%, MRR 0.983 |
| Agent | `SCC_DB.AI.SUPPLY_CHAIN_COPILOT`, runs as the read-only `SCC_APP_SVC` user. Evaluation run 4: 37/37 after correcting the evaluator (35/37 on first scoring). |
| Cost | Account budget of 50 credits/month with email alerts; 25-credit warehouse monitor; agent ≈ 0.09 credits per question |
| App | Streamlit with streaming, session cache, citations, charts and feedback |
| Ops | Request log and monitoring view; CI with secret scan, Ruff and pytest |

**Before the demo:**
- Make sure the search service is RESUMED.
- Run each suggested question once so it's cached.
- The trial ends about 2026-12-25.

## Improvements (suggested, not done)

| # | Item | Why | Effort | Source |
|---|---|---|---|---|
| 1 | ~~Shorter answers~~ **done 2026-11-26** (p95 32 → 25 s). Still open: A/B test pinning `claude-sonnet-5-5` for orchestration | Total latency is still 13–25 s. Any model change needs a full eval re-run (about 3 credits). | S | Phase 7b, ADR-023, ADR-025 |
| 2 | ~~More semantic-view metrics and dimensions~~ **done 2026-11-26**: margin, discount, order value, customers, week, weekday | Missing metrics push the agent toward its own arithmetic or raw SQL | — | Phase 8, ADR-025 |
| 3 | Multi-turn evaluation (follow-ups, context drift) | Not covered by the 34 single-turn cases | M | Phase 8 |
| 4 | ~~Red-team document injection~~ **done 2026-11-26**: 7 attacks in a sandbox corpus; 6/6 resisted, poisoning rejected (`docs/redteam_findings.md`). Still open: adaptive/multi-turn attacks, other languages, many planted passages at once. | Was instruction-based and untested | — | Phases 6, 8, ADR-026 |
| 5 | Independent labelling or a second reviewer for the eval sets; repeat runs to measure variance | Labels are developer-written; runs are single samples | M | Phases 5, 8 |
| 6 | Optional LLM-as-judge groundedness score as a second signal | Phrase checks can miss correct wording (S7 run 1) | M | ADR-024 |
| 7 | ~~Budget for Cortex spend~~ **done 2026-11-26**: account budget, 50 credits/month, email alerts (alerts only, forecast-based) | Resource monitors cover warehouses only | — | ADR-005, ADR-025 |
| 8 | Host the UI (SiS container runtime or an internal host with SSO) | Local single-user app; the Agents API isn't supported on SiS warehouse runtime | L | ADR-002, ADR-022 |
| 9 | Per-user document access (separate search services or policy inheritance) | Cortex Search uses owner's rights; ACCESS_GROUP isn't a security boundary | M | ADR-009 |
| 10 | ~~Revoke CORTEX_USER and USE AI FUNCTIONS from PUBLIC~~ **done 2026-11-26**; verified with `SHOW GRANTS` and eval run 4 | Was granted to PUBLIC by default | — | Phase 0, ADR-025 |
| 11 | Orchestrated pipeline (Tasks or dbt) instead of a command sequence | Fine for a static source; production needs scheduling and lineage | M | Phase 2 |
| 13 | Anchor the incident audit-chain head outside the owner role (for example a periodic export of the latest hash to a separate account or WORM storage) | Hash v2 detects edits by anyone who doesn't recompute the chain; the owner role could recompute it | S | Phase 10 audit |
| 14 | A/B the orchestration model (`auto` vs `claude-sonnet-5-5`) on the 37-case suite | Latency is still p95 about 25 s | S | Phase 10 |
| 12 | ~~n8n supplier-incident workflow~~ **done 2026-11-26 (Phase 9)**: human approval, separation of duties, hash-chained append-only audit log (`docs/incident_workflow.md`). Still open: SSO identities, a live Reject/Timeout run. | Original "Feature F" | — | Project brief, ADR-027 |

## Known limitations (accepted; mention honestly in the interview)

**Data**
- DataCo is public retail/e-commerce sample data, not manufacturing or Worthington data.
- It contains no supplier, carrier or plant fields.
- **Market rotation:** 26 of 37 months contain only one market, so month-over-month trends mostly reflect market mix.
- First Class is late on 100% of shipments, a pattern built into the dataset.
- Revenue is booked (status-based), not recognised.

**Documents**
- Two pages are image-only (SQAM p.16 and p.39) and aren't extracted; there's no OCR.
- Financial tables in the annual report's MD&A are flattened, and two nested-header tables are marked low-confidence.
- The extraction rules are tuned to these three layouts.

**Agent**
- Routing and wording come from the model, so the tests check facts, not exact text.
- It can make small inferences from today's date (for example "Q1 2027").
- It occasionally makes small derived comparisons (for example "0.2 percentage points") or rounds slightly off ("~131K" for 131,667).

**Evaluation**
- 34 questions and 30 retrieval questions, written by the developer, with phrase-based fact checks.
- Each run is a single sample of a non-deterministic model.

**App**
- Answers take about 13–25 s in total (p50 / p95 in run 4).
- The 150-word limit occasionally leaves out a unit (H1 in run 4: "within 14" for "14 working days").
- Cosmetic: while an answer streams, the new message sits below the input until the page reruns.
- Local, single user, no SSO.

**Security**
- Least privilege now depends on the dedicated user `SCC_APP_SVC`, with `DEFAULT_SECONDARY_ROLES = ()`.
- The developer user `SCC_SVC` still holds the dev role; keep its key private.
