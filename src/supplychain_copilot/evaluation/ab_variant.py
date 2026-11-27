"""A/B test of the agent's orchestration model (backlog #14).

    python -m supplychain_copilot.evaluation.ab_variant setup      # sandbox agent, same spec, other model
    python -m supplychain_copilot.evaluation.runner --yes --variant sonnet
    python -m supplychain_copilot.evaluation.ab_variant teardown

The variant is generated from sql/70_agent/01_supply_chain_copilot_agent.sql by exact substitution:
only the agent name and `models: orchestration` change, so any difference in results comes from the
model. It runs as the same least-privilege runtime role.
"""

from __future__ import annotations

import argparse

from supplychain_copilot.config import load_settings
from supplychain_copilot.evaluation.redteam import AGENT_SQL, _replace_once, _statement
from supplychain_copilot.snowflake.connection import session

VARIANT_MODEL = "claude-sonnet-5-5"
VARIANT_AGENT = "SCC_DB.SANDBOX.SUPPLY_CHAIN_COPILOT_SONNET"
RUNTIME_ROLE = "SCC_APP_ROLE"


def variant_ddl(production_sql: str, model: str = VARIANT_MODEL) -> str:
    stmt = _statement(production_sql, "CREATE OR REPLACE AGENT", r"\$\$\s*;")
    stmt = _replace_once(stmt, "AGENT SUPPLY_CHAIN_COPILOT\n", f"AGENT {VARIANT_AGENT}\n")
    stmt = _replace_once(stmt, "  orchestration: auto\n", f"  orchestration: {model}\n")
    return stmt.rstrip().rstrip(";")


def setup() -> None:
    with session(load_settings()) as conn:
        cur = conn.cursor()
        cur.execute("USE ROLE SCC_DEV_ROLE")
        cur.execute(variant_ddl(AGENT_SQL.read_text(encoding="utf-8")))
        cur.execute(f"GRANT USAGE ON SCHEMA SCC_DB.SANDBOX TO ROLE {RUNTIME_ROLE}")
        cur.execute(f"GRANT USAGE ON AGENT {VARIANT_AGENT} TO ROLE {RUNTIME_ROLE}")
    print(
        f"Created {VARIANT_AGENT} (orchestration: {VARIANT_MODEL}); USAGE granted to {RUNTIME_ROLE}."
    )


def teardown() -> None:
    with session(load_settings()) as conn:
        cur = conn.cursor()
        cur.execute("USE ROLE SCC_DEV_ROLE")
        cur.execute(f"DROP AGENT IF EXISTS {VARIANT_AGENT}")
        cur.execute(f"REVOKE USAGE ON SCHEMA SCC_DB.SANDBOX FROM ROLE {RUNTIME_ROLE}")
    print(f"Dropped {VARIANT_AGENT}; revoked SANDBOX usage from {RUNTIME_ROLE}.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["setup", "teardown"])
    a = p.parse_args()
    setup() if a.command == "setup" else teardown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
