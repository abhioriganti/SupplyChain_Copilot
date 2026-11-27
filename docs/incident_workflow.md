# Phase 9: human-in-the-loop supplier-incident workflow (simulated)

This is Feature F from the project brief: *"a simulated supplier-quality incident workflow using n8n, including human approval and an audit log."* Design decisions are in ADR-027.

> **Simulated.** Incidents are practice records about made-up parts. No email is sent and no supplier is contacted. An approved incident only records `ACTION_SIMULATED`.

## Flow
```
Streamlit "Incidents" tab                       n8n 2.47.5 (Docker, 127.0.0.1:5678)
  1. open incident ── CREATED ──────────┐
  2. Copilot drafts procedures ─ DRAFTED │ (Cortex Agent, SQAM citations)
  3. submit ───── POST webhook + token ──┼──► token valid? ──no──► stop (nothing recorded)
                                         │        │yes
                                         │        ▼
        incident API (127.0.0.1:8077) ◄──┼── SUBMITTED_FOR_APPROVAL (+ signed form URL)
        token check, state machine,      │        ▼
        separation of duties             │   Wait: approval form (24 h limit)
                                         │        ├─ timeout ─────────► TIMED_OUT
                                         │        ├─ approver = requester ► SUBMITTED_FOR_APPROVAL (reason), form re-opens
                                         │        ├─ Reject ──────────► REJECTED
                                         │        └─ Approve ─────────► APPROVED ► ACTION_SIMULATED
                                         ▼
        SCC_DB.APP.INCIDENT_AUDIT_LOG  (append-only, SHA-256 chained)
```

## Controls
| Control | How it's enforced | Tested by |
|---|---|---|
| A human decides | Only `human` actors can approve or reject; the n8n form is the only decision path | `test_incidents.py` |
| Separation of duties | The approver must differ from the requester (case- and space-insensitive). n8n checks first and re-opens the form; the **API enforces it regardless** (HTTP 409). | Unit and API tests; live run |
| Valid sequence only | State machine: no decision before submission; rejected, timed-out and actioned incidents are final; the workflow can't write requester or agent events | Parametrised tests |
| Append-only log | The runtime role holds INSERT on the table and SELECT on views only. UPDATE, DELETE, TRUNCATE and direct table reads are denied. | Privilege probes 13/13 (5 new) |
| Tamper evidence | `EVENT_HASH = SHA-256(PREV_HASH ‖ PAYLOAD)` per incident. `V_INCIDENT_CHAIN_CHECK` recomputes it **in SQL**, and the app recomputes it in Python. | Unit test (edited and removed events detected); live test (Snowflake `SHA2` = Python) |
| Authenticated callbacks | Shared secret in `X-SCC-Workflow-Token` from `.env`, never in the workflow JSON; compared in constant time; checked by both n8n and the API | API tests; live wrong-token request produced 0 callbacks |
| No exposure | n8n and the API bind to 127.0.0.1. The container reaches the API through `host.docker.internal`. | Live reachability check |
| Failure is recorded | A failed draft or an unreachable n8n becomes an `ERROR` event; the incident is kept and can be resubmitted | Unit and UI tests |
| Bounded input | Length limits, a severity enum, credential redaction, and callback details truncated to 500 characters | Unit and API tests |

## Audit fix: the hash now covers who acted (Phase 10)
**Problem:** an independent review before the interview found that hash version 1 covered only `PAYLOAD` (the event details). `ACTOR`, `ACTOR_TYPE`, `SEQ`, `INCIDENT_ID` and `CREATED_AT_UTC` were stored beside it but not hashed. So a privileged `UPDATE` of *who approved* would have left `CHAIN_OK = TRUE`.

**Fix:** hash version 2 is `SHA-256(PREV_HASH ‖ incident | seq | type | actor | actor type | time | PAYLOAD)`, and `V_INCIDENT_CHAIN_CHECK` recomputes it from the columns in SQL. Rows written before the fix keep `HASH_VERSION = 1` and are checked by the v1 rule. Re-hashing them would mean rewriting the history the log exists to protect, so they stay as they are.

**Proof (2026-11-26):**
1. Inside a transaction, the developer role ran `UPDATE … SET ACTOR = 'Impostor'` on a v2 decision row.
2. `CHAIN_OK` became FALSE (`BAD_HASHES = 1`).
3. After `ROLLBACK` it was TRUE again.
4. The live test confirmed that Snowflake's `TO_VARCHAR(…, 'YYYY-MM-DD"T"HH24:MI:SS.FF6')` matches Python byte for byte.
5. Five v1 incidents and one v2 incident all verify.

**Anchors (ADR-030):** the owner role could recompute every hash after editing, so each incident's latest `(SEQ, EVENT_HASH)` is also recorded in `SCC_AUDIT_DB`. That database is owned by `SCC_AUDIT_ROLE`, which only ACCOUNTADMIN holds. A daily serverless task and an owner's-rights procedure keep it current; `V_ANCHOR_CHECK` compares it with the log, and the Incidents tab shows it in the **ANCHOR** column.

**Tamper probe** (`incidents/anchor_probe.py`):
- an owner-role edit with every hash recomputed left `CHAIN_OK = TRUE` but set `ANCHOR_OK = FALSE`
- the owner role's attempt to edit the anchors was denied
- after restoring the rows, both checks are OK again

**What it still doesn't do:**
- protect events newer than the last anchor (up to a day)
- guard against ACCOUNTADMIN, who could alter the anchors; production would also copy them to a separate account or WORM storage

## Slack notifications (optional)
The approver doesn't have to watch n8n: when an approval is needed, the workflow posts to a Slack channel.

| When | Message |
|---|---|
| Approval needed (and again if the form is re-opened after a self-approval attempt) | Incident, supplier, part, severity, requester, the Copilot draft, and an **Open approval form** button |
| Decision recorded | ✅ Approved by … (corrective action request drafted, SIMULATED: not sent) · ⛔ Rejected by … · ⌛ Timed out |

**Design:**
- **Slack Incoming Webhook, not an n8n Slack credential.** The webhook URL is the only secret. It lives in `.env` (gitignored) as `SCC_SLACK_WEBHOOK_URL` and reaches n8n through the container environment, exactly like the workflow token. The workflow JSON holds `$env.SCC_SLACK_WEBHOOK_URL`, and n8n stores no Slack credential.
- **Optional and best-effort.** An IF node skips Slack when the URL is empty. The Slack nodes use `onError: continueRegularOutput`, so a Slack outage never blocks an approval, and the audit log is unaffected either way.
- **The approval itself is unchanged.** The message links to the same n8n form, so the named approver, separation of duties and the audit trail work exactly as tested above. Anyone in the channel can open the form; the API still rejects the requester.
- **Leak protection.** `scripts/check_secrets.py` (CI) now flags Slack webhook URLs and `xox…` tokens. The app's bot and app tokens are not used.

**Setup:**
1. In Slack's developer site (api.slack.com/apps), create an app from **Pick features** in your workspace.
2. Under **Incoming Webhooks**, add a webhook for a channel.
3. Put the URL in `.env`.
4. Run `docker compose --env-file .env -f n8n/docker-compose.yml up -d`, then re-import, publish and restart (see **Run it**).

**Live check (`INC-59911657E7`):** the Slack message arrived with the form button. The approver approved from it, and the trail was CREATED → DRAFTED → SUBMITTED → APPROVED (by a person other than the requester) → ACTION_SIMULATED, with the SQL chain check intact (5 events). The form link points to `localhost:5678`, so it opens only on the machine running n8n. A shared deployment would need n8n behind an HTTPS hostname and SSO.

## Live end-to-end run (2026-11-26, incident `INC-9BB8473DFE`)
| # | Event | Actor | Detail |
|---|---|---|---|
| 1 | CREATED | requester (human) | "Burrs on valve housings at receiving inspection", Supplier A (simulated), severity high |
| 2 | DRAFTED | supply_chain_copilot (agent) | Cited SQAM §7.1 (pp. 27–29), §7.2 (p. 29) and §7.4 (pp. 30–31): 48 h protection and acknowledgement, 2 / 14 / 30 working days; no cause assumed |
| 3 | SUBMITTED_FOR_APPROVAL | n8n | Signed, single-execution form URL |
| 4 | SUBMITTED_FOR_APPROVAL | n8n | **The requester tried to approve their own incident:** "approver must differ from requester"; the form re-opened |
| 5 | APPROVED | a different person (human) | |
| 6 | ACTION_SIMULATED | n8n | "Corrective Action Request drafted for Supplier A (simulated) (SIMULATED: not sent)" |

`V_INCIDENT_CHAIN_CHECK` reported 6 events, 0 bad hashes, 0 bad links, 0 sequence gaps, and `CHAIN_OK = TRUE`. The API received exactly 4 authenticated callbacks. A request with a wrong token started the workflow but produced no callback.

## Live Reject and Timeout runs (2026-11-27)
Two simulated test incidents, both requested by "Test Requester", with no Copilot draft (no Cortex cost):

| Incident | Path | Trail | Notes |
|---|---|---|---|
| `INC-CC2E445F15` | Production workflow, decided by a person in the n8n form | CREATED → SUBMITTED_FOR_APPROVAL → **REJECTED** by "Test Approver" (human), comment recorded | |
| `INC-5EDDD7548E` | `[TEST]` copy with a **2-minute** wait (`n8n_workflow.timeout_test_variant`) | CREATED → SUBMITTED_FOR_APPROVAL → **TIMED_OUT** (n8n, workflow) | Reason recorded: "no decision within 2 minutes (timeout test)" |

**Checks after the runs:**
- `V_INCIDENT_CHAIN_CHECK` reports `CHAIN_OK` for both, as does the Python twin.
- Both heads were anchored and `V_ANCHOR_CHECK` matched (ADR-030). All incidents' chains and anchors were OK afterwards.
- The API logged exactly 4 authenticated callbacks.
- A late `APPROVED` sent to each incident was refused with **409** ("not allowed when the incident is REJECTED" / "TIMED_OUT"), so final states hold live.

**Setup for the timeout copy:**
- Generated with `python -m supplychain_copilot.incidents.n8n_workflow --timeout-test OUT --minutes 2`.
- Imported with `docker cp` plus `n8n import:workflow`, then published.
- Unpublished after the run. The n8n CLI has no delete command, so remove it in the n8n UI if wanted.

## Run it
```powershell
docker compose --env-file .env -f n8n/docker-compose.yml up -d          # first start pulls n8nio/n8n:2.47.5
# first time only: open http://localhost:5678 and create the local owner account, then:
docker exec -u node scc-n8n n8n import:workflow --input=/workflows/supplier_incident_approval.json
docker exec -u node scc-n8n n8n publish:workflow --id=sccSupplierIncident1
docker restart scc-n8n                                                     # registers the production webhook
.venv\Scripts\python -m supplychain_copilot.incidents.api                  # callback API, keep running
.venv\Scripts\streamlit run app\streamlit_app.py                           # Incidents tab
```
`SCC_WORKFLOW_TOKEN` must be set in `.env` (see `.env.example`). After changing the workflow, regenerate it with `python -m supplychain_copilot.incidents.n8n_workflow`; a test checks the committed JSON matches. Stop everything with `docker compose -f n8n/docker-compose.yml down`. The data stays in the `n8n_n8n-data` volume.

## Limitations (honest)
- **Identities are self-declared.** Requester and approver names are typed in, so separation of duties compares names, not authenticated users. Production would take both from SSO (for example the n8n form behind an identity-aware proxy, and Streamlit on an SSO host). Backlog item 8.
- **Single writer.** Snowflake doesn't enforce PRIMARY KEY or UNIQUE on standard tables, so appends are serialised with a process lock. A second concurrent writer could create a duplicate sequence number, which the SQL chain check would flag. Production would use a single service, or a stream and task with a sequencer.
- **The 24-hour timeout was tested live with a 2-minute copy**, not by waiting a day. The copy differs only in the wait limit, the reason wording, and its own ID and webhook path, and a test checks that.
- **A wrong token is dropped silently.** The webhook answers "Workflow was started" (respond-immediately mode), so a caller with a bad token sees success while nothing is recorded. The incident simply stays `DRAFTED` and can be resubmitted.
- **Test incidents are kept.** The live pytest writes one incident marked "(automated test)". The log is append-only for the runtime role by design, so test incidents are not deleted.
- The editor opens on n8n's "AI Assistant" welcome page by default. Choose **Set up later in Settings**, or open `/home/workflows`. The Assistant would send workflow content to n8n's cloud, so it isn't enabled.
- The n8n log shows "Failed to start Python task runner… Python 3 is missing". This is harmless here, because the workflow has no Python Code nodes.
- Telemetry is left off; the editor needs a local owner account (n8n 2.x has no supported way to disable login).
