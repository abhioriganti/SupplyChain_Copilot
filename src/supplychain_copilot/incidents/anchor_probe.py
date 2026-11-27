"""Tamper probe for the audit-chain anchors (backlog #13, ADR-030).

Shows that the in-database chain check alone can be defeated by the owner role, and that the anchor
kept outside that role catches it:

  1. The app writes a SIMULATED two-event test incident (CREATED, DRAFTED) as SCC_APP_ROLE.
  2. Its head is anchored via SCC_AUDIT_DB.ANCHOR.ANCHOR_CHAIN_HEADS (owner's rights, SCC_AUDIT_ROLE).
  3. As the owner (SCC_DEV_ROLE), seq 1 is edited and *every hash is recomputed*, the realistic attack.
     Expected: V_INCIDENT_CHAIN_CHECK still says CHAIN_OK; V_ANCHOR_CHECK says ANCHOR_OK = FALSE.
  4. The owner tries to write to the anchors directly. Expected: denied.
  5. The original rows are restored (always, in `finally`). Expected: both checks OK again.

The test incident stays in the log (append-only history) and is labelled as a probe.
Cost: a few warehouse queries; no Cortex.

Run:  .venv\\Scripts\\python -m supplychain_copilot.incidents.anchor_probe
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from supplychain_copilot.config import PROJECT_ROOT
from supplychain_copilot.incidents import model
from supplychain_copilot.incidents.store import ANCHOR_CHECK_SQL, SnowflakeIncidentStore

OUT = PROJECT_ROOT / "data" / "processed" / "anchor_probe_results.json"
ANCHOR_PROC = "CALL SCC_AUDIT_DB.ANCHOR.ANCHOR_CHAIN_HEADS('probe')"
CHAIN_SQL = "SELECT CHAIN_OK FROM SCC_DB.APP.V_INCIDENT_CHAIN_CHECK WHERE INCIDENT_ID = %s"
DETAILS = {
    "title": "Audit-anchor tamper probe (simulated test record)",
    "supplier": "Sample Supplier",
    "part": "n/a",
    "severity": "low",
    "description": "Created by evaluation tooling to test that anchored audit history cannot be "
    "rewritten unnoticed. Not a real incident.",
}


def rewrite_history(history: list[model.Event], seq: int, new_details: dict) -> list[model.Event]:
    """What a malicious owner would do: change one event and recompute every later hash and link,
    so the chain is internally consistent again."""
    out, prev = [], model.GENESIS
    for e in history:
        if e.seq == seq:
            payload = model.canonical(
                {**new_details, "event_type": e.event_type, "simulated": True}
            )
            e = replace(e, payload=payload, details=json.loads(payload))
        e = replace(e, prev_hash=prev)
        e = replace(e, event_hash=model.event_hash(prev, e))
        out.append(e)
        prev = e.event_hash
    return out


def _write_rows(conn, events: list[model.Event]) -> None:
    cur = conn.cursor()
    for e in events:
        cur.execute(
            "UPDATE SCC_DB.APP.INCIDENT_AUDIT_LOG SET PAYLOAD = %s, PREV_HASH = %s, EVENT_HASH = %s "
            "WHERE EVENT_ID = %s",
            (e.payload, e.prev_hash, e.event_hash, e.event_id),
        )


def _state(conn, incident_id: str) -> dict[str, Any]:
    from supplychain_copilot.snowflake.connection import query

    chain = query(conn, CHAIN_SQL, (incident_id,))
    anchor = query(conn, ANCHOR_CHECK_SQL + " WHERE INCIDENT_ID = %s", (incident_id,))
    return {
        "chain_ok": bool(chain and chain[0]["CHAIN_OK"]),
        "anchor_ok": bool(anchor and anchor[0]["ANCHOR_OK"]),
        "mismatched": int(anchor[0]["MISMATCHED"]) if anchor else None,
    }


def run() -> dict[str, Any]:
    from supplychain_copilot.snowflake.connection import query, session

    app_store = SnowflakeIncidentStore()  # the real writer: SCC_APP_ROLE, INSERT only
    created = model.build_event([], model.CREATED, "anchor_probe", "system", DETAILS)
    app_store.append(created)
    drafted = model.build_event(
        [created], model.DRAFTED, "supply_chain_copilot", "agent", {"draft": "probe draft"}
    )
    app_store.append(drafted)
    iid = created.incident_id
    original = app_store.history(iid)
    steps: dict[str, Any] = {"incident_id": iid}

    with session() as dev:
        steps["anchored"] = query(dev, ANCHOR_PROC)
        steps["before"] = _state(dev, iid)
        try:
            forged = rewrite_history(original, 1, {**DETAILS, "severity": "critical"})
            assert not model.verify_chain(forged)  # internally consistent forgery
            _write_rows(dev, forged)
            steps["after_rewrite"] = _state(dev, iid)
            try:
                dev.cursor().execute(
                    "UPDATE SCC_AUDIT_DB.ANCHOR.CHAIN_ANCHORS SET HEAD_HASH = %s WHERE INCIDENT_ID = %s",
                    (forged[-1].event_hash, iid),
                )
                steps["owner_edit_anchor"] = "ALLOWED"
            except Exception as exc:  # noqa: BLE001 - denial is the expected outcome
                steps["owner_edit_anchor"] = f"denied: {str(exc)[:120]}"
        finally:
            _write_rows(dev, original)
        steps["after_restore"] = _state(dev, iid)

    steps["passed"] = (
        steps["before"] == {"chain_ok": True, "anchor_ok": True, "mismatched": 0}
        and steps["after_rewrite"]["chain_ok"]  # the chain check alone is fooled ...
        and not steps["after_rewrite"]["anchor_ok"]  # ... the anchor is not
        and steps["owner_edit_anchor"].startswith("denied")
        and steps["after_restore"] == steps["before"]
    )
    return steps


def main() -> int:
    steps = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(steps, indent=2, default=str), encoding="utf-8")
    for k in ("before", "after_rewrite", "owner_edit_anchor", "after_restore"):
        print(f"{k:<18} {steps[k]}")
    print(f"{'PASS' if steps['passed'] else 'FAIL'}; wrote {OUT.relative_to(PROJECT_ROOT)}")
    return 0 if steps["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
