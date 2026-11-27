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
| 1 | ~~Shorter answers~~ **done 2026-11-26** (p95 32 → 25 s). Still open: see #14 (model A/B) | Total latency is still 13–25 s. Any model change needs a full eval re-run (about 3 credits). | S | Phase 7b, ADR-023, ADR-025 |
| 2 | ~~More semantic-view metrics and dimensions~~ **done 2026-11-26**: margin, discount, order value, customers, week, weekday | Missing metrics push the agent toward its own arithmetic or raw SQL | — | Phase 8, ADR-025 |
| 3 | ~~Multi-turn evaluation~~ **done 2026-11-26/27**: 6 two-turn conversations (12/12), plus 5- and 6-turn conversations and a lost-context case at the 3-pair window (12/12 after two documented relabels): the agent restates context, and asks when it is truly gone. Still open: conversations beyond 6 turns, repeat samples. | Was not covered by the single-turn cases | — | Phase 8 |
| 4 | ~~Red-team document injection~~ **done 2026-11-26**: 7 attacks in a sandbox corpus; 6/6 resisted, poisoning rejected (`docs/redteam_findings.md`). Still open: adaptive/multi-turn attacks, other languages, many planted passages at once. | Was instruction-based and untested | — | Phases 6, 8, ADR-026 |
| 5 | Independent labelling or a second reviewer for the eval sets; ~~repeat runs~~ **repeat runs done 2026-11-27**: 3 runs × 37 cases, routing identical, 36/37 cases passed every run, 108/108 after one evaluator correction (`docs/variance_report.md`). Still open: an independent second reviewer for the labels. | Labels are developer-written | M | Phases 5, 8 |
| 6 | ~~LLM-as-judge groundedness score~~ **done 2026-11-27**: `openai-gpt-5.4` judges answers against their evidence; caught 27/27 planted errors; on clean answers 16 flags in 37 (4 real minor wording issues, 12 false alarms), so it's a triage signal, not a gate (ADR-031). Still open: structured tables for the judge, subtler planted errors, agreement with a human reviewer. | Phrase checks can miss correct wording and can't see paraphrase errors | — | ADR-024, ADR-031 |
| 7 | ~~Budget for Cortex spend~~ **done 2026-11-26**: account budget, 50 credits/month, email alerts (alerts only, forecast-based) | Resource monitors cover warehouses only | — | ADR-005, ADR-025 |
| 8 | Host the UI (SiS container runtime or an internal host with SSO) | Local single-user app; the Agents API isn't supported on SiS warehouse runtime | L | ADR-002, ADR-022 |
| 9 | ~~Per-user document access~~ **done 2026-11-26**: two tier roles, a 10-K-only public service, 7 of 7 RBAC probes (public tier denied the supplier corpus; a client filter shown not to be a boundary). Still open: routing chat users to a per-tier agent (needs SSO, #8); policy inheritance untested. | Cortex Search uses owner's rights; ACCESS_GROUP isn't a security boundary | — | ADR-009, ADR-029 |
| 10 | ~~Revoke CORTEX_USER and USE AI FUNCTIONS from PUBLIC~~ **done 2026-11-26**; verified with `SHOW GRANTS` and eval run 4 | Was granted to PUBLIC by default | — | Phase 0, ADR-025 |
| 11 | Orchestrated pipeline (Tasks or dbt) instead of a command sequence | Fine for a static source; production needs scheduling and lineage | M | Phase 2 |
| 12 | ~~n8n supplier-incident workflow~~ **done 2026-11-26 (Phase 9)**: human approval, separation of duties, hash-chained append-only audit log (`docs/incident_workflow.md`). Live Reject and Timeout runs done 2026-11-27 (the timeout via a 2-minute test copy). Still open: SSO identities. | Original "Feature F" | — | Project brief, ADR-027 |
| 13 | ~~Anchor the audit-chain head outside the owner role~~ **done 2026-11-27**: `SCC_AUDIT_ROLE` owns `SCC_AUDIT_DB`; a daily serverless task anchors each incident's head; a probe showed a rehashed forgery fooling the chain check but caught by `V_ANCHOR_CHECK`, with owner writes to the anchors denied (ADR-030). Still open: an off-account or WORM copy of the anchors (ACCOUNTADMIN could alter them). | Hash v2 alone can't detect an owner who recomputes the chain | — | Phase 10 audit, ADR-030 |
| 14 | ~~A/B the orchestration model~~ **done 2026-11-26**: claude-sonnet-5-5 was 35–40% faster but passed 25/37 (11 semantic-view bypasses, all denied); `auto` kept (ADR-028) | Latency stays p95 about 25 s; re-test new models with `runner --variant` | — | Phase 10 |

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
