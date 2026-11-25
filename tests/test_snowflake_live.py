"""Live Snowflake integration tests. Skipped unless SCC_RUN_SNOWFLAKE_TESTS=1 (never run in CI)."""

import os

import pytest

pytestmark = [
    pytest.mark.snowflake,
    pytest.mark.skipif(
        os.getenv("SCC_RUN_SNOWFLAKE_TESTS") != "1",
        reason="set SCC_RUN_SNOWFLAKE_TESTS=1 to run live Snowflake tests",
    ),
]


def test_connects_with_expected_role():
    from supplychain_copilot.config import load_settings
    from supplychain_copilot.snowflake.connection import query, session

    settings = load_settings()
    with session(settings) as conn:
        row = query(conn, "SELECT CURRENT_ROLE() AS ROLE, CURRENT_WAREHOUSE() AS WH")[0]
    assert row["ROLE"] == settings.role
    assert row["WH"] == settings.warehouse
