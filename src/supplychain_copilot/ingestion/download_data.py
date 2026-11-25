"""Obtain and verify raw source files.

Mendeley Data serves DataCo through a browser download page, so acquisition is a documented manual step
(no scraping). This module verifies that local copies exist and match the SHA-256 hashes in
``data/manifest.json``, so every run provably uses the same source bytes.

Usage:
    python -m supplychain_copilot.ingestion.download_data           # verify all files
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from supplychain_copilot.config import PROJECT_ROOT

MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.json"

MANUAL_STEPS = """\
Manual download (browser):
  1. Open https://data.mendeley.com/datasets/8gx2fvg2k6/5  (licence: CC BY 4.0)
  2. Download DataCoSupplyChainDataset.csv and DescriptionDataCoSupplyChain.csv
     (skip tokenized_access_logs.csv).
  3. Save both into data/raw/dataco/ without renaming.
  4. Documents: open each URL listed under "documents" in data/manifest.json and save into
     data/raw/documents/ without renaming.
  5. Re-run this script to verify hashes."""


@dataclass(frozen=True)
class FileCheck:
    name: str
    path: Path
    exists: bool
    sha256_ok: bool
    expected_sha256: str
    actual_sha256: str | None


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_sources(manifest: dict | None = None, root: Path = PROJECT_ROOT) -> list[FileCheck]:
    manifest = manifest or load_manifest()
    checks: list[FileCheck] = []
    for group in manifest.values():
        for name, meta in group["files"].items():
            path = root / meta["path"]
            actual = sha256_of(path) if path.is_file() else None
            checks.append(
                FileCheck(
                    name=name,
                    path=path,
                    exists=actual is not None,
                    sha256_ok=actual == meta["sha256"],
                    expected_sha256=meta["sha256"],
                    actual_sha256=actual,
                )
            )
    return checks


def main() -> int:
    checks = verify_sources()
    for c in checks:
        status = "OK" if c.sha256_ok else ("HASH MISMATCH" if c.exists else "MISSING")
        print(f"[{status:<13}] {c.name}")
    if all(c.sha256_ok for c in checks):
        print("All source files present and verified.")
        return 0
    print("\n" + MANUAL_STEPS)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
