"""Generate an RSA key pair for the Snowflake service user, stored OUTSIDE the repo.

Run this yourself (it creates a credential):
    .venv\\Scripts\\python scripts\\generate_keypair.py

- Private key: $env:USERPROFILE\\.snowflake\\keys\\scc_svc_rsa_key.p8 (never printed, never committed)
- Prints only the PUBLIC key (single line) and its fingerprint, which are safe to paste into Snowsight.
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from supplychain_copilot.snowflake.keys import public_key_body, public_key_fingerprint

DEFAULT_PATH = Path.home() / ".snowflake" / "keys" / "scc_svc_rsa_key.p8"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_PATH, help="private key path")
    parser.add_argument(
        "--passphrase", action="store_true", help="encrypt the private key (prompted)"
    )
    args = parser.parse_args()

    out: Path = args.out.expanduser().resolve()
    if out.exists():
        print(
            f"Refusing to overwrite existing key at {out}. Delete it first if you mean to rotate."
        )
        return 1

    encryption: serialization.KeySerializationEncryption = serialization.NoEncryption()
    if args.passphrase:
        pw = getpass.getpass("Passphrase for the private key: ")
        if not pw or pw != getpass.getpass("Repeat passphrase: "):
            print("Passphrases empty or did not match.")
            return 1
        encryption = serialization.BestAvailableEncryption(pw.encode())

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )
    )

    print(f"Private key written to: {out}")
    print("Keep it private. Put this path in .env as SNOWFLAKE_PRIVATE_KEY_PATH.\n")
    print(
        "PUBLIC key (paste into the setup SQL in Snowsight where it says <PUBLIC_KEY> / <APP_PUBLIC_KEY>):\n"
    )
    print(public_key_body(key))
    print(
        f"\nFingerprint (compare with DESC USER SCC_SVC -> RSA_PUBLIC_KEY_FP): {public_key_fingerprint(key)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
