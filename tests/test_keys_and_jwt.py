import base64
import hashlib

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from supplychain_copilot.config import SnowflakeSettings
from supplychain_copilot.snowflake.keys import (
    load_private_key,
    public_key_body,
    public_key_fingerprint,
)
from supplychain_copilot.snowflake.rest import build_jwt, jwt_account_identifier


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def key_file(tmp_path, rsa_key):
    path = tmp_path / "test_key.p8"
    path.write_bytes(
        rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def test_fingerprint_matches_openssl_recipe(rsa_key):
    # openssl rsa -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64
    der = rsa_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    expected = "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode()
    assert public_key_fingerprint(rsa_key) == expected


def test_public_key_body_is_single_line_without_delimiters(rsa_key):
    body = public_key_body(rsa_key)
    assert "\n" not in body and "BEGIN" not in body and "END" not in body
    assert len(body) > 300


def test_load_encrypted_key(tmp_path, rsa_key):
    path = tmp_path / "enc.p8"
    path.write_bytes(
        rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"pw"),
        )
    )
    assert public_key_fingerprint(load_private_key(path, "pw")) == public_key_fingerprint(rsa_key)


def test_account_identifier_formatting():
    assert jwt_account_identifier("myorg.myaccount") == "MYORG-MYACCOUNT"
    assert jwt_account_identifier("Myorg-Acct") == "MYORG-ACCT"


def test_jwt_claims(key_file, rsa_key):
    settings = SnowflakeSettings(
        account="MYORG-ACCT",
        user="SCC_SVC",
        role="SCC_DEV_ROLE",
        warehouse="SCC_WH",
        database="SCC_DB",
        private_key_path=key_file,
    )
    token = build_jwt(settings, now=1_700_000_000)
    claims = jwt.decode(
        token, rsa_key.public_key(), algorithms=["RS256"], options={"verify_exp": False}
    )

    assert claims["sub"] == "MYORG-ACCT.SCC_SVC"
    assert claims["iss"] == f"MYORG-ACCT.SCC_SVC.{public_key_fingerprint(rsa_key)}"
    assert claims["exp"] - claims["iat"] <= 3600
