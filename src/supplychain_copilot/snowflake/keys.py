"""RSA key helpers shared by the SQL connector and REST JWT auth."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def load_private_key(path: Path, passphrase: str | None = None) -> RSAPrivateKey:
    """Load a PEM-encoded PKCS#8 RSA private key."""
    key = serialization.load_pem_private_key(
        path.read_bytes(),
        password=passphrase.encode() if passphrase else None,
    )
    if not isinstance(key, RSAPrivateKey):
        raise ValueError("Snowflake key-pair auth requires an RSA private key.")
    return key


def public_key_fingerprint(private_key: RSAPrivateKey) -> str:
    """SHA-256 fingerprint of the DER public key, as Snowflake reports it (``SHA256:<base64>``)."""
    der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode()


def public_key_body(private_key: RSAPrivateKey) -> str:
    """Public key as a single line without PEM delimiters (the form ALTER USER expects)."""
    pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return "".join(line for line in pem.splitlines() if "PUBLIC KEY" not in line)
