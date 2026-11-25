"""Load the sanitized Parquet into SCC_DB.BRONZE.DATACO_ORDER_LINES and audit the row counts.

Append-only: every run gets a new LOAD_ID; Silver selects the latest successful load. Re-loading
the same file is therefore safe and leaves a full history.

Usage:
    python -m supplychain_copilot.warehouse.load_bronze
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pandas as pd
from snowflake.connector.pandas_tools import write_pandas

from supplychain_copilot.ingestion.clean_orders import OUTPUT_PARQUET
from supplychain_copilot.ingestion.download_data import sha256_of
from supplychain_copilot.snowflake.connection import query, session

DATABASE, SCHEMA, TABLE = "SCC_DB", "BRONZE", "DATACO_ORDER_LINES"


class LoadError(RuntimeError):
    pass


def prepare_frame(df: pd.DataFrame, load_id: str, ingested_at: datetime) -> pd.DataFrame:
    out = df.copy()
    out["load_id"] = load_id
    out["ingested_at_utc"] = pd.Timestamp(ingested_at).tz_localize(None)
    out.columns = [c.upper() for c in out.columns]
    return out


def load(parquet_path=OUTPUT_PARQUET) -> dict:
    if not parquet_path.is_file():
        raise LoadError(f"{parquet_path} not found; run supplychain_copilot.ingestion.clean_orders")
    df = pd.read_parquet(parquet_path)
    rows_in_file = len(df)
    source_sha = df["source_sha256"].iloc[0]
    load_id = str(uuid.uuid4())
    started = datetime.now(UTC).replace(tzinfo=None)
    frame = prepare_frame(df, load_id, started)

    with session() as conn:
        ok, _chunks, rows_loaded, _ = write_pandas(
            conn,
            frame,
            table_name=TABLE,
            database=DATABASE,
            schema=SCHEMA,
            use_logical_type=True,
            quote_identifiers=True,
        )
        in_table = query(
            conn,
            f"SELECT COUNT(*) AS N FROM {DATABASE}.{SCHEMA}.{TABLE} WHERE LOAD_ID = %s",  # noqa: S608 - constant identifiers; values bound
            (load_id,),
        )[0]["N"]
        status = "SUCCESS" if ok and rows_loaded == rows_in_file == in_table else "FAILED"
        conn.cursor().execute(
            f"INSERT INTO {DATABASE}.{SCHEMA}.LOAD_AUDIT VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",  # noqa: S608 - constant identifiers; values bound
            (
                load_id,
                f"{DATABASE}.{SCHEMA}.{TABLE}",
                parquet_path.name,
                source_sha,
                rows_in_file,
                rows_loaded,
                in_table,
                status,
                started,
                datetime.now(UTC).replace(tzinfo=None),
            ),
        )
    result = {
        "load_id": load_id,
        "parquet_sha256": sha256_of(parquet_path),
        "rows_in_file": rows_in_file,
        "rows_loaded": rows_loaded,
        "rows_in_table": in_table,
        "status": status,
    }
    if status != "SUCCESS":
        raise LoadError(f"Row count mismatch: {result}")
    return result


def main() -> int:
    for k, v in load().items():
        print(f"{k:<16} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
