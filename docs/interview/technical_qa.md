# Technical Q&A preparation

Answer in the shape **claim → why → evidence from the project → honest limit**. Each answer below is about 30–45 seconds spoken. "Built" means it exists in this repo; "would" means it's a design proposal I haven't implemented.

---

### 1. Why Snowflake Cortex?
**Claim:** keep the AI next to the governed data, behind one access model.
- The data, the semantic layer, retrieval, the agent and role-based access are all in Snowflake, so there's no second vector database, no copied data, and no separate permission system to keep in sync.
- **Evidence:** the agent runs as a least-privilege role; the same `GRANT`s govern SQL, search and the agent; the request log and budget are in the same account.
- **Tradeoff:** less model choice and control than a hand-built stack, plus vendor lock-in, and some features are preview. I checked every feature against current docs and recorded the decisions in ADRs.

### 2. Why semantic views?
**Claim:** one definition per metric, enforced where the SQL is generated.
- Without one, an LLM writes plausible SQL that quietly differs from finance's definition. With one, Analyst can only use `late_delivery_rate` as defined: late ÷ *eligible* shipments, canceled excluded.
- **Evidence:** the view matches independently computed Gold figures on 14 of 14 checks.
  - My evaluation caught Analyst bypassing the view once, for a quarterly question when there was no quarter dimension. The read-only role denied the query, I added the dimension, and every evaluation now asserts "all SQL via SEMANTIC_VIEW".
  - I also added a governed `profit_margin` after the agent computed margins itself in run 1.

### 3. Why not embed all the structured data?
**Claim:** embeddings retrieve *similar text*; KPIs need *exact aggregates*.
- "Late-delivery rate by region" is a GROUP BY over 65,752 orders. Similarity search over rows can't sum, filter or deduplicate correctly, and it would be wrong in ways that are hard to see.
- So I use SQL for numbers and vectors only for prose (ADR-010). The hybrid agent combines the two, rather than forcing one tool to do both.

### 4. How did you prevent double-counting?
**Claim:** grain discipline in the model, verified with tests.
- `FACT_ORDERS` has one row per order, which is one shipment, and delivery metrics live there. Revenue lives on `FACT_ORDER_LINES`.
- When an order-level metric is grouped by product (a many-to-many path), Snowflake's semantic view deduplicates instead of fanning out. A naive join would inflate revenue **3.49×**.
- **Evidence:** a test checks that the per-category order counts equal `COUNT(DISTINCT order_id)`; 521 of 521 KPI values re-derived from raw data; 38 SQL data-quality tests.

### 5. How is retrieval evaluated?
- **Set:** 30 labelled questions with the expected document and page.
- **Metrics:** hit@1 **96.7%**, hit@5 100%, MRR 0.983.
- **Configuration compared:** keyword-only 73% and vector-only 93% at hit@1, so I chose hybrid with the reranker.
- **Citation integrity, two separate checks:**
  - At extraction, every word of every chunk appears on its cited page.
  - At retrieval, 660 of 660 returned passages matched their stored document, section and page range.
- **End to end,** the agent evaluation checks the *cited page*, not just the wording.
- **Limit:** I wrote the labels myself; I'd have a quality engineer label the next set.

### 6. How are hallucinations handled?
Layered, because no single control is enough:
1. **Grounding instructions:**
   - numbers only from tools, as returned
   - no self-computed margins or forecasts
   - cite or say "not found"
   - never imply causes the data can't show
2. **Constrained tools:** Analyst is limited to the semantic view, and search returns real passages with pages.
3. **Detection in evaluation:**
   - numbers are compared against SQL ground truth
   - untraceable numbers are flagged for human review
   - every case is checked for causal claims and leaks
4. **Visible evidence:** SQL, results and citations sit under every answer, so a user can check them.

- **Evidence:** run 1 found the agent summing figures and inventing a forecast range. The instructions and checks were fixed, and runs 3 and 5 were clean.
- **Limit:** each run is a single sample, and the fact checks are phrase-based.

### 7. How would you secure the system?
**Built:**
- A dedicated runtime user with secondary roles disabled. I found a real privilege leak through secondary roles and fixed it (ADR-021).
- The role can't read raw tables or modify business data, and only INSERTs into three log tables. 13 privilege probes run on every evaluation.
- Key-pair auth with keys outside the repo, and a CI secret scan (full history clean).
- Cortex revoked from PUBLIC.
- A red-team of injected instructions inside documents: 6 of 6 resisted.

**Would:**
- SSO in front of the app
- secrets in a vault
- network policies
- audit-log anchoring outside the owner role

### 8. How would you implement document-level permissions?
- **The key fact:** Cortex Search runs with the *owner's* rights. A filter the client sends (such as `ACCESS_GROUP`) is a convenience, **not** a security boundary (ADR-009).
- **So, by enforcement:**
  - one search service per sensitivity tier (public, supplier-confidential, internal)
  - each granted to the matching role
  - the agent per role, or a routing layer, only sees the services that role may use
- Alternatively, policy inheritance if its coverage of the agent's query path is confirmed. I'd test it the way I tested the semantic-view bypass, with a probe that *should* be denied.

### 9. How would you handle data freshness?
- **Today** the sources are static, so it's a scripted load with lineage per load (ADR: orchestrated pipeline deferred).
- **Production:**
  - incremental loads into Bronze from the ERP and pipeline tools you already run
  - Snowflake Streams and Tasks, or dbt, for Silver and Gold
  - the search service's `TARGET_LAG`, already set to 1 day, refreshes changed chunks incrementally
- **Show freshness to users:** a "data as of" timestamp on the KPI cards, plus a data-quality gate that blocks publishing if row counts or reconciliation fail. That gate is the same idea as my 38 SQL tests.

### 10. How would you control costs?
**Built:**
- X-Small warehouse with 60 s auto-suspend
- 25-credit resource monitor (hard stop)
- an account budget alert at 50 credits a month, which covers Cortex
- a session answer cache
- shorter answers, which cut output tokens 19% and p95 latency from 32 to 25 s

**Measured:** about **0.09 credits per agent question**, and about 3 credits for a 37-case evaluation.

**Would:**
- a per-team budget tagged by user group
- cache governed answers across sessions for common questions
- route simple metric questions straight to Analyst without the orchestration model

### 11. How would you support enterprise-scale use?
- **Hosting:** move off local Streamlit to Streamlit in Snowflake or an internal host with SSO.
- **Behind a gateway:** per-user identity passed through, so row and document policies apply per person.
- **Scale and limits:** the warehouse scales separately; concurrency and rate limits; the request log feeding a monitoring dashboard with alerting on error rate and p95.
- **Evaluation as a release gate:** every change to the semantic view or agent instructions re-runs the suite. I already did that: every fix in this project was retested.
- **Honest limit:** I haven't load-tested it.

### 12. How would you integrate with JDE, SharePoint or Microsoft Teams?
*(Design proposals, not built.)*
- **JDE (ERP):** extract order, supplier and receipt tables through the existing integration pipelines into Bronze, then model supplier-level facts in Gold. That would finally allow the question this dataset can't answer: on-time rate *by supplier*.
- **SharePoint:** sync approved supplier documents to a stage, run the same extraction with provenance and hashes, and map SharePoint permissions to search-service tiers (question 8).
- **Teams:** a bot that calls the same agent endpoint as the app, with the user's identity, plus approval cards for the incident workflow.
  - My n8n workflow already has the human-approval and audit pattern, with Slack notifications. Teams would replace Slack, and the approver identity would come from Entra ID instead of a typed name.

### 13. How could the system support real supply-chain decisions?
**Claim:** start with one decision, measure it, then expand. Don't start with a chatbot for everything.
- **Example:** daily expediting. "Which open orders are at risk of being late, and what does the supplier agreement require?"
  - The metrics half needs real open-order and supplier data.
  - The procedures half is what I built today.
- **Keep the human in the loop for actions:** the Copilot drafts, and a named person approves, logged. That's the incident workflow I built.
- **Measure value:** time-to-answer before and after, how often answers are corrected (the feedback buttons), and adoption.
- **Be clear about what the data can't do:** this dataset can't attribute delays to suppliers, and the agent says so rather than guessing. That honesty is a feature for decision-making.

---

## Likely follow-ups (one line each)
- **"What was hardest?"** Making the evaluation trustworthy. Half of the early failures were my *checks* being wrong, so every failure gets classified as a real defect or an evaluator error before fixing anything.
- **"What would you do differently?"** Write the evaluation set with a business owner on day one, and design per-user document access from the start.
- **"What did your own audit find?"** The audit hash didn't cover who approved, and "read-only" was overstated for a role that writes to logs. Both are fixed, and the hash fix is proven with a rolled-back tampering test.
- **"Is it production-ready?"** No. It's a working, tested prototype on public data. The production steps are SSO, real sources, scheduled refresh, per-user permissions and load testing.
