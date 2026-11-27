"""Per-user document access probes (backlog #9, ADR-029).

Cortex Search runs with the service owner's rights, so a client-side `filter` (e.g. ACCESS_GROUP) is a
relevance tool, not a security boundary: any caller with USAGE on a service can omit it. Tiers are
therefore enforced by Snowflake RBAC on *separate services*:

  SCC_DOCS_PUBLIC_ROLE   -> PUBLIC_DISCLOSURES_SEARCH (10-K only)
  SCC_DOCS_SUPPLIER_ROLE -> PUBLIC_DISCLOSURES_SEARCH + SUPPLIER_DOCS_SEARCH (all three documents)

Each probe sends a real Cortex Search REST query as SCC_APP_SVC with a different X-Snowflake-Role header
(both tier roles are granted to that user; DEFAULT_SECONDARY_ROLES = () so only the header role applies).
Cost: a handful of Cortex Search queries (serving cost, no LLM tokens).

Run:  .venv\\Scripts\\python -m supplychain_copilot.evaluation.doc_tiers
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from supplychain_copilot.config import PROJECT_ROOT, load_app_settings
from supplychain_copilot.snowflake.rest import SnowflakeRestClient, SnowflakeRestError

PUBLIC_ROLE, SUPPLIER_ROLE, APP_ROLE = (
    "SCC_DOCS_PUBLIC_ROLE",
    "SCC_DOCS_SUPPLIER_ROLE",
    "SCC_APP_ROLE",
)
PUBLIC_SVC, SUPPLIER_SVC = "PUBLIC_DISCLOSURES_SEARCH", "SUPPLIER_DOCS_SEARCH"
PUBLIC_TYPES = {"annual_report_10k"}
SUPPLIER_TYPES = {"supplier_quality_manual", "supplier_code_of_conduct"}
COLUMNS = ["CHUNK_ID", "DOCUMENT_ID", "DOCUMENT_TYPE", "ACCESS_GROUP"]
# A question whose best answer lives in the supplier manual, so a leak would be visible.
SUPPLIER_QUESTION = "What must a supplier do when submitting PPAP or a corrective action request?"
OUT = PROJECT_ROOT / "data" / "processed" / "doc_tier_results.json"


def service_path(service: str) -> str:
    return f"/api/v2/databases/SCC_DB/schemas/AI/cortex-search-services/{service}:query"


@dataclass
class Probe:
    id: str
    role: str
    service: str
    expect: str  # "denied" | "public_only" | "includes_supplier"
    filter: dict[str, Any] | None = None
    description: str = ""


PROBES = [
    Probe(
        "T1",
        PUBLIC_ROLE,
        SUPPLIER_SVC,
        "denied",
        None,
        "public tier cannot query the supplier corpus at all",
    ),
    Probe(
        "T2",
        PUBLIC_ROLE,
        PUBLIC_SVC,
        "public_only",
        None,
        "public tier gets only 10-K passages, even for a supplier-manual question",
    ),
    Probe(
        "T3",
        SUPPLIER_ROLE,
        SUPPLIER_SVC,
        "includes_supplier",
        None,
        "supplier tier sees supplier-manual content",
    ),
    Probe(
        "T4",
        SUPPLIER_ROLE,
        PUBLIC_SVC,
        "public_only",
        None,
        "supplier tier can also use the public service (superset)",
    ),
    Probe(
        "T5",
        SUPPLIER_ROLE,
        SUPPLIER_SVC,
        "public_only",
        {"@eq": {"DOCUMENT_TYPE": "annual_report_10k"}},
        "a client filter narrows results ...",
    ),
    Probe(
        "T6",
        SUPPLIER_ROLE,
        SUPPLIER_SVC,
        "includes_supplier",
        None,
        "... but the same caller simply omits it: filters are not a boundary",
    ),
    Probe(
        "T7",
        APP_ROLE,
        PUBLIC_SVC,
        "denied",
        None,
        "the chat runtime role was not widened by the tier work",
    ),
]


def judge(expect: str, status: str, types: set[str]) -> bool:
    if expect == "denied":
        return status == "denied"
    if status != "ok" or not types:
        return False
    if expect == "public_only":
        return types <= PUBLIC_TYPES
    return bool(types & SUPPLIER_TYPES)


def run_probe(p: Probe, clients: dict[str, SnowflakeRestClient]) -> dict[str, Any]:
    body: dict[str, Any] = {"query": SUPPLIER_QUESTION, "columns": COLUMNS, "limit": 10}
    if p.filter:
        body["filter"] = p.filter
    try:
        rows = clients[p.role].post(service_path(p.service), body).get("results", [])
        status, types = "ok", {r["DOCUMENT_TYPE"] for r in rows}
        detail = f"{len(rows)} rows, types={sorted(types)}"
    except SnowflakeRestError as e:
        status, types, detail = "denied", set(), f"HTTP {e.status}: {e.body[:160]}"
    return {
        "id": p.id,
        "role": p.role,
        "service": p.service,
        "filter": p.filter,
        "expect": p.expect,
        "status": status,
        "document_types": sorted(types),
        "passed": judge(p.expect, status, types),
        "detail": detail,
        "description": p.description,
    }


def run() -> list[dict[str, Any]]:
    base = load_app_settings()
    clients = {
        r: SnowflakeRestClient(dataclasses.replace(base, role=r))
        for r in (PUBLIC_ROLE, SUPPLIER_ROLE, APP_ROLE)
    }
    return [run_probe(p, clients) for p in PROBES]


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    results = run()
    for r in results:
        print(
            f"[{'PASS' if r['passed'] else 'FAIL'}] {r['id']} {r['role']:<24} {r['service']:<27} "
            f"{r['detail']}"
        )
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    Path(OUT).write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = sum(r["passed"] for r in results)
    print(f"{passed}/{len(results)} tier probes passed; wrote {OUT.relative_to(PROJECT_ROOT)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
