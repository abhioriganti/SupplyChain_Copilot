"""Execute SQL test files (one query -> rows of TEST_NAME, LAYER, FAILURES, DETAIL) and persist results."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supplychain_copilot.snowflake.connection import query, session

RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS SCC_DB.APP.DQ_TEST_RESULTS (
    RUN_ID VARCHAR, RUN_AT_UTC TIMESTAMP_NTZ, TEST_FILE VARCHAR, TEST_NAME VARCHAR,
    LAYER VARCHAR, FAILURES NUMBER, PASSED BOOLEAN, DETAIL VARCHAR
)
"""


def run_test_file(path: Path, run_id: str, persist: bool = True) -> list[dict[str, Any]]:
    sql = path.read_text(encoding="utf-8").strip().rstrip(";")
    with session() as conn:
        rows = query(conn, sql)
        if persist:
            cur = conn.cursor()
            cur.execute(RESULTS_DDL)
            run_at = datetime.now(UTC).replace(tzinfo=None)
            cur.executemany(
                "INSERT INTO SCC_DB.APP.DQ_TEST_RESULTS (RUN_ID, RUN_AT_UTC, TEST_FILE, TEST_NAME, "
                "LAYER, FAILURES, PASSED, DETAIL) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        run_id,
                        run_at,
                        path.name,
                        r["TEST_NAME"],
                        r["LAYER"],
                        int(r["FAILURES"]),
                        int(r["FAILURES"]) == 0,
                        r["DETAIL"],
                    )
                    for r in rows
                ],
            )
    for r in rows:
        r["FAILURES"] = int(r["FAILURES"])
    return rows
