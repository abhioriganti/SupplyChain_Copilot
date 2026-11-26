"""SQL connections via the Snowflake Python connector using key-pair auth."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import snowflake.connector
from cryptography.hazmat.primitives import serialization
from snowflake.connector import SnowflakeConnection

from supplychain_copilot.config import SnowflakeSettings, load_settings
from supplychain_copilot.snowflake.keys import load_private_key


def connect(settings: SnowflakeSettings | None = None, **overrides: Any) -> SnowflakeConnection:
    """Open a connection. Caller is responsible for closing it (prefer ``session()``)."""
    settings = settings or load_settings()
    private_key = load_private_key(settings.private_key_path, settings.private_key_passphrase)
    der_key = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    params: dict[str, Any] = {
        "account": settings.account,
        "user": settings.user,
        "role": settings.role,
        "warehouse": settings.warehouse,
        "database": settings.database,
        "private_key": der_key,
        "application": "SupplyChainCopilot",
        "client_session_keep_alive": False,
    }
    params.update(overrides)
    return snowflake.connector.connect(**params)


@contextmanager
def session(
    settings: SnowflakeSettings | None = None, **overrides: Any
) -> Iterator[SnowflakeConnection]:
    """Context-managed connection that is always closed."""
    conn = connect(settings, **overrides)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def app_session() -> Iterator[SnowflakeConnection]:
    """Runtime-user session (SCC_APP_SVC / SCC_APP_ROLE) with secondary roles explicitly disabled,
    so only the read-only role's privileges apply (defense in depth on top of the user's defaults)."""
    from supplychain_copilot.config import load_app_settings

    conn = connect(load_app_settings())
    try:
        conn.cursor().execute("USE SECONDARY ROLES NONE")
        yield conn
    finally:
        conn.close()


def query(conn: SnowflakeConnection, sql: str, params: Any = None) -> list[dict[str, Any]]:
    """Run a query and return rows as dicts keyed by upper-cased column name."""
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(sql, params)
        return [{k.upper(): v for k, v in row.items()} for row in cur.fetchall()]
