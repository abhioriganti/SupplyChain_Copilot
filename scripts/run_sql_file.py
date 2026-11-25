"""Execute a versioned .sql file against Snowflake as the configured role.

Usage:  .venv\\Scripts\\python scripts\\run_sql_file.py sql\\00_setup\\02_schemas.sql
"""

from __future__ import annotations

import argparse
from pathlib import Path

from supplychain_copilot.snowflake.connection import session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_file", type=Path)
    args = parser.parse_args()

    sql_text = args.sql_file.read_text(encoding="utf-8")
    with session() as conn:
        for cursor in conn.execute_string(sql_text, remove_comments=True):
            first_row = cursor.fetchone()
            summary = first_row[0] if first_row else ""
            print(f"OK  {cursor.query.strip().splitlines()[0][:80]}  ->  {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
