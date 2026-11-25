# Architecture decisions

Short records of decisions that matter. Each one covers: context, the decision, alternatives considered, and tradeoffs. Status is one of *Accepted*, *Proposed* (waiting on evidence) or *Superseded*.

---

## ADR-001: Snowflake Cortex is the primary platform; the fallback is documented only
**Status:** Accepted (2026-11-25)
**Context:** The target team builds on Snowflake: Cortex Agents, Search, Analyst and semantic views.
**Decision:** Every AI capability runs on Snowflake Cortex. The DuckDB/FAISS/Python-router fallback stays a written plan. It is used only if a Cortex feature is proven unavailable, and it is never presented as Snowflake-native.
**Alternatives:** LangChain/LangGraph with an external vector DB and an external LLM.
**Tradeoffs:** Ties the project to one vendor and to Snowflake's billing. In return we get governance (RBAC, lineage) in one place, and the project matches the team's actual stack.

**Update (2026-11-25):** The smoke test showed that the self-service trial blocks AI functions, Cortex Search embeddings and Agent runs (`399258` and `399504`), while semantic views and Cortex Analyst work. Snowflake docs say adding a credit card enables AI features without ending the trial. Decision: unblock via the payment method, keep Cortex as the platform, and do **not** switch to the fallback.

## ADR-002: The app runs locally and calls Cortex Agents over REST
**Status:** Accepted
**Context:** Snowflake docs (checked 2026-11-25) say the Agents API is not supported from Streamlit in Snowflake on warehouse runtime.
**Decision:** Streamlit runs locally and calls the named agent's `:run` REST endpoint through a typed Python client (`supplychain_copilot.snowflake.rest`). There is no FastAPI layer.
**Alternatives:**
- Streamlit in Snowflake on container runtime: more setup, and the runtime model is newer.
- A FastAPI backend: an extra service with no benefit for a single-user demo.
**Tradeoffs:** The app isn't hosted in Snowflake. In production this would move to SiS container runtime or an internal web host behind SSO.

## ADR-003: A key-pair SERVICE user, not a password
**Status:** Accepted
**Decision:** Scripts and the app authenticate as `SCC_SVC` (`TYPE = SERVICE`, so it has no password and cannot log in interactively), using an RSA key pair.
- The private key lives in `%USERPROFILE%\.snowflake\keys\`, outside the repo; `config.py` refuses any key path inside the repo.
- The same key signs the JWTs for the REST API.
**Alternatives:**
- Password plus MFA: can't be automated and is a secret that tends to leak.
- A programmatic access token (PAT): simpler to set up, but it's a bearer token that can leak.
- OAuth: the right choice for production SSO, but too heavy here.
**Tradeoffs:** By default the key is unencrypted on disk, protected only by the user profile; `--passphrase` is available. In production it would sit in a secrets manager and be rotated with `RSA_PUBLIC_KEY_2`.

## ADR-004: Two roles, for building and for running
**Status:** Accepted. The runtime grants arrive in a later phase.
**Decision:**
- `SCC_DEV_ROLE` owns `SCC_DB` and builds everything.
- `SCC_APP_ROLE` is the runtime role. It will get only USAGE on the agent, the search service, the semantic view and the warehouse, plus SELECT on GOLD.
- `SCC_APP_ROLE` is granted to `SCC_DEV_ROLE` so we can test as the app.
**Why:** Cortex Analyst generates SQL. The real defence against harmful SQL is that the runtime role has no write privileges at all, so even a manipulated query can't change data.
**Tradeoffs:** Every new object needs an explicit grant to the app role.

## ADR-005: Cost controls
**Status:** Accepted
**Decision:**
- One X-Small warehouse (`SCC_WH`) with 60-second auto-suspend and a 15-minute statement timeout.
- A resource monitor `SCC_WH_MONITOR`: 25 credits a month, notify at 50% and 80%, suspend at 100%.
- Paid Cortex scripts need an explicit `--yes` flag.
- Cortex Search uses a long `TARGET_LAG`.
**Known gap:** Snowflake docs say resource monitors cover **warehouses only**, not Cortex or other serverless spend. Cortex usage will be tracked through `SNOWFLAKE.ACCOUNT_USAGE` metering views. A Snowflake Budget is an option if spending becomes a concern.

## ADR-006: Named agent object (`CREATE AGENT`) instead of passing the agent configuration on each REST call
**Status:** Accepted
**Why:**
- The specification is versioned in SQL in the repo.
- Access is governed by grants (USAGE on the agent).
- The agent is visible in Snowsight and Snowflake Intelligence.
- The client doesn't need to know which tools exist.
**Tradeoffs:** Changing the agent means redeploying with `CREATE OR REPLACE`.

## ADR-007: Text extraction with PyMuPDF instead of AI_PARSE_DOCUMENT
**Status:** Accepted
**Why:** Extraction is deterministic, gives exact page numbers for citations, costs no credits, and is easy to test locally. Snowflake still does the indexing and retrieval through Cortex Search.
**Tradeoffs:**
- PyMuPDF has an AGPL licence, which is fine for a portfolio project but would need review for commercial use.
- Scanned PDFs would need OCR, but our three documents contain real text.

## ADR-008: Shipments modelled at order grain
**Status:** Accepted (2026-11-25, confirmed by the Phase 1 profile)
**Context:** DataCo has one row per order line (180,519 lines, 65,752 orders) and no shipment ID.
**Evidence:** 0 of 65,752 orders have differing values across their lines for any shipping attribute: dates, actual and scheduled days, delivery status, late flag, shipping mode and destination. The pipeline enforces this as an error-level check (`order_attributes_consistent_across_lines`), so a future source change would fail loudly.
**Decision:** One shipment per order. Delivery KPIs are computed over distinct orders and never over lines. A line-level late rate would weight a 5-line order 5× and is wrong.
**Tradeoffs:** Split shipments can't be represented, but the source has no such information.

## ADR-011: Time trends are confounded by market rotation
**Status:** Accepted (design constraint)
**Evidence:** 26 of 37 months contain orders from a single market, and the dataset cycles LATAM → Europe → Pacific Asia → USCA → mixed → LATAM → Europe → Pacific Asia. See profiling_report §8.
**Decision:** No rows are altered or removed. The semantic layer will document it, and the agent's instructions will require a caveat on any month-over-month question: the trend reflects market composition. Comparisons across regions or markets over the full period remain valid.
**Why it matters:** An assistant that reported "late deliveries improved in July 2016" would be reporting a change in the data's market mix, not a real operational change. Catching this during profiling is the point of profiling before modelling.

## ADR-012: Python sanitises; Snowflake SQL owns metric logic
**Status:** Accepted
**Decision:** The Python pipeline only:
- verifies the source hash
- drops PII and duplicate columns
- renames and types the columns
- normalises whitespace
- adds lineage and DQ flags
- validates
It changes neither row count nor values. Eligibility, late rate, revenue choice and grain derivation (Silver and Gold) live in versioned Snowflake SQL and the semantic view.
**Alternatives:** Build the orders and products tables in pandas.
**Why not:** It would create two places where the business logic is defined, and those would drift apart. Governed metrics should have one home.
**Tradeoffs:** The SQL layer must re-establish the grain, but the Phase 1 checks already prove that it's safe.

## ADR-014: No separate FACT_SHIPMENTS; FACT_ORDERS is the shipment fact
**Status:** Accepted (2026-11-25)
**Context:** The suggested model listed FACT_ORDERS, FACT_ORDER_LINES and FACT_SHIPMENTS.
**Decision:** Shipment grain is identical to order grain in this source: there is one shipment per order, and that was tested. A FACT_SHIPMENTS table would duplicate FACT_ORDERS row for row. In a semantic layer, two tables at the same grain create two join paths and two places to define "late rate", which is exactly the inconsistency a governed layer exists to prevent. The shipment attributes and flags therefore live on FACT_ORDERS.
**When to revisit:** A source with split shipments or carrier events would need a real FACT_SHIPMENTS at its own grain.

## ADR-015: Governed revenue = net sales of non-canceled, non-fraud orders
**Status:** Accepted (2026-11-25; the user agreed to `net_sales` before Phase 2)
**Decision:** `TOTAL_REVENUE = SUM(NET_SALES) WHERE ORDER_STATUS NOT IN ('CANCELED','SUSPECTED_FRAUD')`, where `NET_SALES` is after discount.
**Alternatives:**
- Gross sales, before discount, which overstates realised sales.
- All statuses, which counts canceled and fraud orders.
- Completed or closed orders only, which would drop pending, processing and on-hold orders that are booked.
**Tradeoffs:** It's a booking view of revenue, not recognised revenue, and the source has no invoicing data. The alternatives stay derivable from the facts for anyone who needs them.

## ADR-016: KPI rates are computed as FLOAT
**Status:** Accepted
**Context:** Snowflake integer division and `AVG` over integers return `NUMBER` with 6 decimal places (e.g. `0.573127`).
**Decision:** Cast to FLOAT inside the views so governed values aren't silently rounded. Rounding happens at presentation.

## ADR-013: Parse failures abort; source quirks are flagged
**Status:** Accepted
**Decision:**
- Any unparseable number or date, an unknown category value, a duplicate key or a broken identity **aborts** the run with a message naming the failing column. Nothing is silently coerced or dropped.
- Known, explained quirks are kept and flagged as warnings: Same Day timestamps, canceled-but-late lines, negative profit, and a category name that isn't unique.

## ADR-009: Document access control in Cortex Search
**Status:** Accepted (design constraint)
**Context:** Snowflake docs (checked 2026-11-25) say Cortex Search runs with the **owner's rights**. Row access and masking policies on the source table are **not** applied when querying, unless the service is created with `INHERIT_DATA_GOVERNANCE_POLICIES = TRUE`, and that setting is enforced only for specific SQL functions.
**Decision:** All v1 documents are public, so `ACCESS_GROUP = 'public'`. The enforced boundary is USAGE on the search service, held per role. An `ACCESS_GROUP` filter sent by the client is **not** treated as a security control.
**Production path:** separate services per sensitivity tier, or policy inheritance, after checking that it covers the agent's query path.

## ADR-010: Use SQL over a semantic view for metrics, not embeddings
**Status:** Accepted
**Why:**
- KPIs such as late-delivery rate are exact aggregates over hundreds of thousands of rows. Vector retrieval returns *similar text*, not *correct numbers*.
- The semantic view fixes each metric's numerator, denominator, filters and join paths once.
- Cortex Analyst generates SQL against those definitions, and the SQL is shown to the user so they can audit it.
- Embeddings are used only where similarity is the right tool: policy and document text.
