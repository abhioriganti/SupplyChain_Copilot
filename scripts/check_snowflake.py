"""Snowflake connectivity and permission check. Read-only; uses a few seconds of X-Small warehouse.

Usage:  .venv\\Scripts\\python scripts\\check_snowflake.py
"""

from __future__ import annotations

from supplychain_copilot.config import ConfigError, load_settings
from supplychain_copilot.snowflake.connection import query, session

EXPECTED_SCHEMAS = {"BRONZE", "SILVER", "GOLD", "DOCS", "AI", "APP", "SANDBOX"}


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"[BLOCKED] {exc}")
        return 2

    failures = 0
    with session(settings) as conn:
        ctx = query(
            conn,
            "SELECT CURRENT_ORGANIZATION_NAME() AS ORG, CURRENT_ACCOUNT_NAME() AS ACCOUNT, "
            "CURRENT_REGION() AS REGION, CURRENT_USER() AS USER_NAME, CURRENT_ROLE() AS ROLE, "
            "CURRENT_WAREHOUSE() AS WAREHOUSE, CURRENT_DATABASE() AS DB, CURRENT_VERSION() AS VERSION",
        )[0]
        print("Session context:")
        for key, value in ctx.items():
            print(f"  {key:<10} {value}")

        if ctx["ROLE"] != settings.role:
            print(f"[FAIL] Expected role {settings.role}, got {ctx['ROLE']}")
            failures += 1

        wh = query(conn, f"SHOW WAREHOUSES LIKE '{settings.warehouse}'")
        if wh:
            w = wh[0]
            print(
                f"[PASS] Warehouse {w['NAME']}: size={w['SIZE']}, auto_suspend={w['AUTO_SUSPEND']}s, "
                f"state={w['STATE']}, resource_monitor={w.get('RESOURCE_MONITOR')}"
            )
        else:
            print(f"[FAIL] Warehouse {settings.warehouse} not visible to role {settings.role}")
            failures += 1

        one = query(conn, "SELECT 1 AS OK")[0]["OK"]
        print(f"[{'PASS' if one == 1 else 'FAIL'}] Warehouse executes queries")

        schemas = {r["NAME"] for r in query(conn, f"SHOW SCHEMAS IN DATABASE {settings.database}")}
        missing = EXPECTED_SCHEMAS - schemas
        if missing:
            print(f"[FAIL] Missing schemas in {settings.database}: {sorted(missing)}")
            failures += 1
        else:
            print(f"[PASS] Schemas present: {sorted(EXPECTED_SCHEMAS)}")

        grants = query(conn, f"SHOW GRANTS TO ROLE {settings.role}")
        print(f"Grants to {settings.role}:")
        for g in grants:
            print(f"  {g['PRIVILEGE']:<28} {g['GRANTED_ON']:<16} {g['NAME']}")
        names = {(g["PRIVILEGE"], g["NAME"]) for g in grants}
        has_cortex = any(n.endswith("CORTEX_USER") for _, n in names)
        print(f"[{'PASS' if has_cortex else 'FAIL'}] SNOWFLAKE.CORTEX_USER granted to role")
        failures += 0 if has_cortex else 1

        xr = query(conn, "SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT")
        if xr:
            print(f"[INFO] CORTEX_ENABLED_CROSS_REGION = {xr[0]['VALUE']}")

    print("\nSnowflake check " + ("OK." if failures == 0 else f"found {failures} failure(s)."))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
