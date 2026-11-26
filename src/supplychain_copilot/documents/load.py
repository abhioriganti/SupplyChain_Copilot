"""Load processed documents and chunks into SCC_DB.DOCS with a transactional replace.

Rows go to transient staging tables first; then DELETE + INSERT run in one transaction so readers
(and the Phase 5 Cortex Search service) never see a half-loaded table. The target table identity is
preserved, which keeps change tracking intact for Cortex Search refreshes.

Usage:
    python -m supplychain_copilot.documents.load
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pandas as pd
from snowflake.connector.pandas_tools import write_pandas

from supplychain_copilot.documents.pipeline import CHUNKS_PARQUET, DOCS_PARQUET
from supplychain_copilot.snowflake.connection import query, session

SCHEMA = "SCC_DB.DOCS"
TABLES = {"DOCUMENTS": DOCS_PARQUET, "DOCUMENT_CHUNKS": CHUNKS_PARQUET}


def _frame(path, load_id: str, ingested_at: datetime, columns: list[str]) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["ingested_at"] = pd.Timestamp(ingested_at)
    df["load_id"] = load_id
    df.columns = [c.upper() for c in df.columns]
    return df[columns]


def load() -> dict:
    load_id = str(uuid.uuid4())
    ingested_at = datetime.now(UTC).replace(tzinfo=None)
    counts: dict[str, int] = {}
    with session() as conn:
        cur = conn.cursor()
        frames = {}
        for table, path in TABLES.items():
            cols = [
                r["COLUMN_NAME"]
                for r in query(
                    conn,
                    "SELECT COLUMN_NAME FROM SCC_DB.INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = 'DOCS' AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                    (table,),
                )
            ]
            frames[table] = _frame(path, load_id, ingested_at, cols)
            cur.execute(
                f"CREATE OR REPLACE TRANSIENT TABLE {SCHEMA}.{table}_STAGE LIKE {SCHEMA}.{table}"
            )
            ok, _, n, _ = write_pandas(
                conn,
                frames[table],
                f"{table}_STAGE",
                database="SCC_DB",
                schema="DOCS",
                use_logical_type=True,
                quote_identifiers=True,
            )
            if not ok or n != len(frames[table]):
                raise RuntimeError(
                    f"staging load failed for {table}: {n} of {len(frames[table])} rows"
                )
        try:
            cur.execute("BEGIN")
            for table in ("DOCUMENT_CHUNKS", "DOCUMENTS"):  # child first
                cur.execute(f"DELETE FROM {SCHEMA}.{table}")
            for table in ("DOCUMENTS", "DOCUMENT_CHUNKS"):
                cur.execute(f"INSERT INTO {SCHEMA}.{table} SELECT * FROM {SCHEMA}.{table}_STAGE")
                counts[table] = cur.rowcount
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            for table in TABLES:
                cur.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table}_STAGE")
    return {
        "load_id": load_id,
        "ingested_at": str(ingested_at),
        **{f"rows_{k.lower()}": v for k, v in counts.items()},
    }


def verify_loaded() -> dict:
    """Compare Snowflake rows with the local parquet: ids, hashes, pages, and counts."""
    local = pd.read_parquet(CHUNKS_PARQUET).set_index("chunk_id")
    with session() as conn:
        rows = query(
            conn,
            f"SELECT CHUNK_ID, CONTENT_HASH, PAGE_NUMBER, PAGE_END, SECTION_TITLE FROM {SCHEMA}.DOCUMENT_CHUNKS",
        )
        docs = query(conn, f"SELECT DOCUMENT_ID, CHUNK_COUNT FROM {SCHEMA}.DOCUMENTS")
    remote = {r["CHUNK_ID"]: r for r in rows}
    mismatches = []
    if set(remote) != set(local.index):
        mismatches.append(f"chunk id sets differ: {len(set(remote) ^ set(local.index))} ids")
    for cid, r in remote.items():
        if cid in local.index:
            loc = local.loc[cid]
            if (r["CONTENT_HASH"], r["PAGE_NUMBER"], r["PAGE_END"], r["SECTION_TITLE"]) != (
                loc.content_hash,
                loc.page_number,
                loc.page_end,
                loc.section_title,
            ):
                mismatches.append(f"{cid}: metadata differs")
    by_doc = local.groupby("document_id").size().to_dict()
    for d in docs:
        if by_doc.get(d["DOCUMENT_ID"]) != d["CHUNK_COUNT"]:
            mismatches.append(
                f"{d['DOCUMENT_ID']}: CHUNK_COUNT {d['CHUNK_COUNT']} vs {by_doc.get(d['DOCUMENT_ID'])}"
            )
    return {
        "remote_chunks": len(remote),
        "local_chunks": len(local),
        "documents": len(docs),
        "mismatches": mismatches,
    }


def main() -> int:
    for k, v in load().items():
        print(f"{k:<22} {v}")
    v = verify_loaded()
    print(
        f"verify: {v['remote_chunks']} remote vs {v['local_chunks']} local chunks, {v['documents']} documents, "
        f"{len(v['mismatches'])} mismatches"
    )
    return 0 if not v["mismatches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
