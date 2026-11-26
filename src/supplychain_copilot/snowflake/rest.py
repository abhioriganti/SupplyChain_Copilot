"""Minimal client for Snowflake REST APIs (Cortex Analyst, Cortex Agents) with key-pair JWT auth.

JWT format per https://docs.snowflake.com/en/developer-guide/sql-api/authenticating :
  iss = <ACCOUNT>.<USER>.SHA256:<fingerprint>, sub = <ACCOUNT>.<USER>, upper-case, '.' -> '-' in account.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import jwt
import requests

from supplychain_copilot.config import SnowflakeSettings
from supplychain_copilot.snowflake.keys import load_private_key, public_key_fingerprint

JWT_LIFETIME_SECONDS = 55 * 60  # Snowflake caps JWTs at one hour


class SnowflakeRestError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Snowflake REST call failed with HTTP {status}: {body[:500]}")
        self.status = status
        self.body = body


def jwt_account_identifier(account: str) -> str:
    return account.upper().replace(".", "-")


def build_jwt(settings: SnowflakeSettings, now: int | None = None) -> str:
    private_key = load_private_key(settings.private_key_path, settings.private_key_passphrase)
    qualified_user = f"{jwt_account_identifier(settings.account)}.{settings.user.upper()}"
    issued = int(now if now is not None else time.time())
    payload = {
        "iss": f"{qualified_user}.{public_key_fingerprint(private_key)}",
        "sub": qualified_user,
        "iat": issued,
        "exp": issued + JWT_LIFETIME_SECONDS,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


class SnowflakeRestClient:
    def __init__(self, settings: SnowflakeSettings, timeout: float = 120.0):
        self._settings = settings
        self._timeout = timeout
        self._token: str | None = None
        self._token_expiry = 0.0

    def _auth_headers(self) -> dict[str, str]:
        if self._token is None or time.time() > self._token_expiry - 60:
            self._token = build_jwt(self._settings)
            self._token_expiry = time.time() + JWT_LIFETIME_SECONDS
        return {
            "Authorization": f"Bearer {self._token}",
            "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
            "X-Snowflake-Role": self._settings.role,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def post_stream(self, path: str, body: dict[str, Any]) -> Iterator[tuple[str, Any]]:
        """POST and yield Server-Sent Events as (event_name, parsed_data). `[DONE]` yields ('done', None)."""
        url = f"{self._settings.account_url}{path}"
        headers = {**self._auth_headers(), "Accept": "text/event-stream"}
        with requests.post(
            url, json=body, headers=headers, timeout=self._timeout, stream=True
        ) as resp:
            if resp.status_code != 200:
                raise SnowflakeRestError(resp.status_code, resp.text)
            # text/event-stream arrives without a charset, so requests would assume ISO-8859-1 and garble
            # UTF-8 text ('§' -> 'Â§'). SSE is UTF-8 by specification.
            resp.encoding = "utf-8"
            event = "message"
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        yield "done", None
                        continue
                    try:
                        yield event, json.loads(payload)
                    except ValueError:
                        yield event, payload

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.account_url}{path}"
        response = requests.post(
            url, json=body, headers=self._auth_headers(), timeout=self._timeout
        )
        if response.status_code != 200:
            raise SnowflakeRestError(response.status_code, response.text)
        return response.json()
