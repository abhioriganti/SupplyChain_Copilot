"""Incidents tab (Phase 9, SIMULATED): open -> Copilot draft -> n8n human approval -> audit trail."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from supplychain_copilot.incidents import model
from supplychain_copilot.incidents.model import IncidentInput
from supplychain_copilot.incidents.service import IncidentService, WorkflowUnavailable

BANNER = (
    "🧪 **Simulated workflow for demonstration.** Incidents are practice records; no email is sent "
    "and no supplier is contacted. An approval only records a simulated corrective-action request."
)
STATUS_ICON = {
    model.CREATED: "🆕",
    model.DRAFTED: "📝",
    model.SUBMITTED: "⏳",
    model.APPROVED: "✅",
    model.REJECTED: "⛔",
    model.TIMED_OUT: "⌛",
    model.ACTION_SIMULATED: "📨",
    model.ERROR: "⚠️",
}
RETRYABLE = {model.CREATED, model.DRAFTED, model.ERROR}


def _submit(service: IncidentService, incident_id: str) -> None:
    try:
        service.submit(incident_id)
        st.success(
            f"{incident_id} sent to the approval workflow. The approval link appears below once "
            "n8n registers it (refresh in a few seconds)."
        )
    except WorkflowUnavailable:
        st.error(
            "The approval workflow didn't accept the incident. Is n8n running "
            "(`docker compose -f n8n\\docker-compose.yml up -d`) and the workflow published? "
            "The incident is saved; use **Retry submission** below."
        )


def new_incident_form(service: IncidentService) -> None:
    with st.form("new_incident", clear_on_submit=False):
        c1, c2, c3 = st.columns([2, 1, 1])
        title = c1.text_input(
            "Title",
            max_chars=model.LIMITS["title"],
            placeholder="Burrs on valve housings at receiving inspection",
        )
        supplier = c2.text_input(
            "Supplier (simulated)",
            value="Supplier A (simulated)",
            max_chars=model.LIMITS["supplier"],
        )
        part = c3.text_input("Part", max_chars=model.LIMITS["part"], placeholder="VH-100")
        description = st.text_area(
            "What was found",
            max_chars=model.LIMITS["description"],
            placeholder="Receiving inspection found burrs on 40 of 500 housings.",
        )
        c4, c5 = st.columns(2)
        severity = c4.selectbox("Severity", model.SEVERITIES, index=2)
        requester = c5.text_input("Your name (requester)", max_chars=model.LIMITS["requester"])
        go = st.form_submit_button("Open incident and request approval", type="primary")
    if not go:
        return
    try:
        event = service.open(IncidentInput(title, supplier, part, description, severity, requester))
    except model.InvalidInput as exc:
        st.error(str(exc))
        return
    with st.spinner(
        "Copilot is drafting the applicable procedures from the Supplier Quality Manual…"
    ):
        drafted = service.draft(event.incident_id)
    if drafted.event_type == model.ERROR:
        st.warning(
            "The Copilot draft failed; the incident continues without it (recorded in the audit log)."
        )
    _submit(service, event.incident_id)


def incident_list(service: IncidentService) -> str | None:
    rows = service.store.statuses()
    if not rows:
        st.info("No incidents yet.")
        return None
    chain = {r["INCIDENT_ID"]: r["CHAIN_OK"] for r in service.store.chain_check()}
    df = pd.DataFrame(rows)
    df["STATUS"] = df["STATUS"].map(lambda s: f"{STATUS_ICON.get(s, '')} {s}")
    df["AUDIT CHAIN"] = df["INCIDENT_ID"].map(
        lambda i: "✅ intact" if chain.get(i) else "❌ broken"
    )
    cols = [
        c
        for c in (
            "INCIDENT_ID",
            "TITLE",
            "SEVERITY",
            "STATUS",
            "REQUESTER",
            "DECIDED_BY",
            "APPROVAL_URL",
            "AUDIT CHAIN",
        )
        if c in df.columns
    ]
    st.dataframe(
        df[cols],
        hide_index=True,
        width="stretch",
        column_config={"APPROVAL_URL": st.column_config.LinkColumn("Approval form (n8n)")},
    )
    return st.selectbox("Show audit trail for", df["INCIDENT_ID"].tolist())


def audit_trail(service: IncidentService, incident_id: str) -> None:
    history = service.store.history(incident_id)
    problems = model.verify_chain(history)
    if problems:
        st.error("Audit chain check failed: " + "; ".join(problems))
    else:
        st.caption(
            f"🔗 {len(history)} events; SHA-256 chain verified in the app and in Snowflake "
            "(`APP.V_INCIDENT_CHAIN_CHECK`)."
        )
    for e in history:
        shown = {
            k: v for k, v in e.details.items() if k not in ("event_type", "simulated", "draft")
        }
        with st.expander(
            f"{e.seq}. {STATUS_ICON.get(e.event_type, '')} {e.event_type} · "
            f"{e.actor} ({e.actor_type}) · {e.created_at_utc:%Y-%m-%d %H:%M} UTC",
            expanded=e.event_type == model.DRAFTED,
        ):
            if "draft" in e.details:
                st.markdown(e.details["draft"])
            if shown:
                st.json(shown)
            st.caption(f"hash {e.event_hash[:16]}… ← prev {e.prev_hash[:16]}…")
    if model.status_of(history) in RETRYABLE and st.button(
        "🔁 Retry submission", key=f"retry_{incident_id}"
    ):
        _submit(service, incident_id)


def render(service: IncidentService) -> None:
    st.markdown(BANNER)
    st.subheader("Report a supplier-quality incident")
    new_incident_form(service)
    st.divider()
    head, refresh = st.columns([4, 1])
    head.subheader("Incidents")
    refresh.button("🔄 Refresh", width="stretch")
    selected = incident_list(service)
    if selected:
        audit_trail(service, selected)
    st.caption(
        "Separation of duties: the approver named on the n8n form must differ from the requester "
        "(enforced by the incident API). Names are self-declared in this demo; production would use "
        "SSO identities."
    )
