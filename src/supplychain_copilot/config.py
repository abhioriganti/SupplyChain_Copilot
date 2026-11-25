"""Environment-based configuration. No credentials are ever stored in code or in the repo."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_REQUIRED = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_PRIVATE_KEY_PATH",
)
# Snowflake unquoted identifiers: letters, digits, underscore, $; must not start with a digit.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_ACCOUNT = re.compile(r"^[A-Za-z0-9_.-]+$")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or unsafe."""


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    role: str
    warehouse: str
    database: str
    private_key_path: Path
    private_key_passphrase: str | None = field(default=None, repr=False)

    @property
    def account_url(self) -> str:
        """Base URL for Snowflake REST APIs (underscores are not valid in hostnames)."""
        return f"https://{self.account.lower().replace('_', '-')}.snowflakecomputing.com"

    def __repr__(self) -> str:  # keep secrets and key paths out of logs
        return (
            f"SnowflakeSettings(account={self.account!r}, user={self.user!r}, role={self.role!r}, "
            f"warehouse={self.warehouse!r}, database={self.database!r})"
        )


def load_settings(env_file: Path | None = None) -> SnowflakeSettings:
    """Load Snowflake settings from environment variables (optionally a local .env file)."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    missing = [name for name in _REQUIRED if not os.getenv(name, "").strip()]
    if missing:
        raise ConfigError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )

    env = {name: os.environ[name].strip() for name in _REQUIRED}

    if not _ACCOUNT.match(env["SNOWFLAKE_ACCOUNT"]):
        raise ConfigError("SNOWFLAKE_ACCOUNT contains unexpected characters.")
    for name in ("SNOWFLAKE_USER", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE"):
        if not _IDENTIFIER.match(env[name]):
            raise ConfigError(f"{name} must be a plain Snowflake identifier.")

    key_path = Path(env["SNOWFLAKE_PRIVATE_KEY_PATH"]).expanduser().resolve()
    if not key_path.is_file():
        raise ConfigError(f"Private key file not found at SNOWFLAKE_PRIVATE_KEY_PATH ({key_path}).")
    if key_path.is_relative_to(PROJECT_ROOT):
        raise ConfigError(
            "The private key must live outside the project folder so it can't be committed."
        )

    return SnowflakeSettings(
        account=env["SNOWFLAKE_ACCOUNT"].upper(),
        user=env["SNOWFLAKE_USER"].upper(),
        role=env["SNOWFLAKE_ROLE"].upper(),
        warehouse=env["SNOWFLAKE_WAREHOUSE"].upper(),
        database=env["SNOWFLAKE_DATABASE"].upper(),
        private_key_path=key_path,
        private_key_passphrase=os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None,
    )
