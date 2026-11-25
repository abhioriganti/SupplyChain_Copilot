"""Run SQL data-quality test files and record results in SCC_DB.APP.DQ_TEST_RESULTS.

Each test file is ONE query returning rows of (TEST_NAME, LAYER, FAILURES, DETAIL). A test passes
when FAILURES = 0. Exit code 1 if any test fails.

Usage:  .venv\\Scripts\\python scripts\\run_sql_tests.py sql\\tests\\test_phase2_model.sql
"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from supplychain_copilot.warehouse.sql_tests import run_test_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    run_id = str(uuid.uuid4())
    failed = 0
    for path in args.files:
        print(f"=== {path}")
        for t in run_test_file(path, run_id=run_id):
            ok = t["FAILURES"] == 0
            failed += 0 if ok else 1
            print(
                f"[{'PASS' if ok else 'FAIL'}] {t['LAYER']:<6} {t['TEST_NAME']:<52} failures={t['FAILURES']}"
            )
    print(f"\nrun_id={run_id}  ->  {'ALL PASSED' if failed == 0 else f'{failed} FAILED'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
