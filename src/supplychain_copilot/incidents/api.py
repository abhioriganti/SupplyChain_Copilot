"""Callback API for the n8n approval workflow (Phase 9).

    .venv\\Scripts\\python -m supplychain_copilot.incidents.api        # http://127.0.0.1:8077

n8n (in Docker) reaches it at http://host.docker.internal:8077. Every request except /health must
carry the shared secret in X-SCC-Workflow-Token (from .env; compared in constant time). The API can
only append workflow events; it cannot read incident text or change history.

HTTP mapping: 401 bad token, 404 unknown incident, 409 invalid transition or separation-of-duties
violation, 422 invalid body.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from supplychain_copilot.incidents import model
from supplychain_copilot.incidents.service import IncidentService, workflow_token


class WorkflowEvent(BaseModel):
    event_type: str = Field(pattern=r"^[A-Z_]{4,40}$")
    actor: str = Field(min_length=1, max_length=80)
    details: dict[str, Any] = Field(default_factory=dict)


def create_app(service: IncidentService, token: str | None = None) -> FastAPI:
    app = FastAPI(title="SupplyChain Copilot incident callbacks", docs_url=None, redoc_url=None)
    expected = token or workflow_token()

    def check_token(x_scc_workflow_token: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_scc_workflow_token.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="invalid workflow token")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/incidents/{incident_id}/events", dependencies=[Depends(check_token)])
    def record(incident_id: str, body: WorkflowEvent) -> dict[str, Any]:
        details = {k: str(v)[:500] for k, v in body.details.items()}  # bounded, flat
        try:
            event = service.record_workflow_event(incident_id, body.event_type, body.actor, details)
        except (model.TransitionError, model.SeparationOfDutiesError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except model.IncidentError as exc:
            status = 404 if "unknown incident" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return {"incident_id": event.incident_id, "seq": event.seq, "event_type": event.event_type}

    return app


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    from supplychain_copilot.config import PROJECT_ROOT
    from supplychain_copilot.incidents.store import SnowflakeIncidentStore

    load_dotenv(PROJECT_ROOT / ".env")
    app = create_app(IncidentService(SnowflakeIncidentStore()))
    # Loopback only: Docker Desktop forwards host.docker.internal to the host's localhost.
    host = os.getenv("SCC_INCIDENT_API_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=int(os.getenv("SCC_INCIDENT_API_PORT", "8077")))


if __name__ == "__main__":
    main()
