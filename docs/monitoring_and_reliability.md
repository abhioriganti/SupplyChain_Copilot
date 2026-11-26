# Monitoring and reliability

## Request log

`SCC_DB.APP.AGENT_REQUEST_LOG` gets one row per agent request, written by the app (`source = 'app'`) and by evaluation runs (`source = 'eval'`).

| Logged | Not logged |
|---|---|
| request id, UTC timestamp, source, session id | credentials, keys, tokens |
| question SHA-256, plus the question truncated to 300 characters with credential patterns redacted | answer text |
| status, error class (invalid / rate_limited / auth / permission / timeout / service / empty) | SQL result rows, document text |
| tools used, SQL count, verified-query flag, citation count | customer data (none exists after Phase 1) |
| latency, cache flag, orchestration model, input/output tokens | |
| eval run id, case id, outcome | |

- **Write path:** `observability.log_request()` connects as `SCC_APP_SVC`, which has INSERT only (a SELECT is denied; tested live). If Snowflake is unavailable it falls back to `logs/requests.jsonl` (gitignored). Logging can't break the app or an eval run.
- **Read path:** operators use `SCC_DEV_ROLE`:

```sql
SELECT * FROM SCC_DB.APP.V_AGENT_MONITORING_DAILY ORDER BY DAY DESC;    -- volume, error rate, p50/p95, tool mix, eval outcomes, tokens
SELECT EVAL_CASE_ID, EVAL_OUTCOME, LATENCY_S, TOOLS_USED FROM SCC_DB.APP.AGENT_REQUEST_LOG
 WHERE EVAL_RUN_ID = '<run id>' ORDER BY CREATED_AT_UTC;
```

Feedback (👍/👎) goes to `APP.AGENT_FEEDBACK`, which is also INSERT-only for the runtime role.

## Reliability: failure handling

| Scenario | Behaviour | Test |
|---|---|---|
| Empty or over-long question | Rejected before any call, with a friendly message | `test_input_validation`, eval cases E1 and E2 |
| Rate limit (429) | Retries with backoff, then a "busy, try again" message | `test_retries_transient_errors_then_succeeds`, `test_rate_limit_exhausted_gives_fallback_not_exception` |
| Cortex unavailable (5xx) or missing agent (404) | Retries on 5xx, then a service-error message | `test_service_failures_become_fallback_answers`, live `test_live_missing_agent_returns_fallback` |
| Auth or permission failure | Specific message, no retry | `test_non_retryable_errors_map_to_meaningful_fallbacks` |
| Timeout | Timeout message ("try a narrower question") | `test_timeout_and_empty_answer_fallbacks`, `test_stream_timeout_and_invalid_question` |
| Agent returns no text, or the stream ends early | "No answer, try rephrasing" | `test_stream_ending_without_response_is_handled` |
| Stream error event | Service-error message | `test_stream_error_event_becomes_fallback` |
| Empty retrieval results | Answer still renders with no sources; the agent is instructed to say evidence wasn't found | `test_empty_retrieval_answer_is_still_rendered`, live `test_live_empty_retrieval_returns_no_passages` |
| Citation metadata missing | Falls back to the agent's citation label | `test_missing_chunk_metadata_falls_back_to_agent_label` |
| Dashboard query failure | Warning banner with no connection details; the chat still works | `test_dashboard_failure_shows_warning_without_details` |
| Feedback or log storage failure | Local JSONL fallback | `test_feedback_falls_back_to_local_log`, `test_logging_failure_falls_back_locally` |
| Unparseable agent chart | Skipped; the answer is unaffected | `test_chart_spec_parsed_and_bad_chart_skipped` |
| Runtime user not configured | Fails closed and never uses developer credentials | `test_agent_fails_closed_without_app_user` |

## Security protections (demonstrated)

- **Privilege boundary:** probed live on every evaluation run (see `docs/evaluation_report.md`). The runtime user can query only the governed semantic view, document tables, search service and agent. Raw tables, DELETE, DROP, CREATE, reading the logs and switching to the developer role are all denied.
- **Agent-level security cases** (prompt injection, credential requests, PII requests, confidential data, destructive SQL, unauthorised actions) are in `eval/eval_set_v2.json`, categories `security` and `unsupported`.
- **Every answer** is checked for write SQL, credential or configuration leakage, and causal supplier claims.
- **CI secret scan:** `scripts/check_secrets.py` fails the build if any tracked file contains a key, token or credential assignment, or if a key or `.env` file is tracked at all.
