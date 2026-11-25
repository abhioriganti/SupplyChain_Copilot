"""Local environment validation (no Snowflake calls, no cost).

Usage:  .venv\\Scripts\\python scripts\\check_environment.py
Exit code 0 when every required check passes.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_IMPORTS = [
    "snowflake.connector",
    "dotenv",
    "cryptography",
    "jwt",
    "requests",
    "pandas",
    "pyarrow",
    "streamlit",
    "supplychain_copilot",
]


def _check(label: str, ok: bool, detail: str = "", required: bool = True) -> bool:
    mark = "PASS" if ok else ("FAIL" if required else "WARN")
    print(f"[{mark}] {label}" + (f" - {detail}" if detail else ""))
    return ok or not required


def _git_tracks_secrets() -> list[str]:
    """Return tracked/staged files that look like secrets (should always be empty)."""
    if not (ROOT / ".git").is_dir():
        return []
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--cached"],  # noqa: S607 - git resolved from PATH by design
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.splitlines()
    bad_suffixes = (".p8", ".pem", ".key", ".pub")
    return [f for f in out if f == ".env" or f.endswith(bad_suffixes)]


def main() -> int:
    results: list[bool] = []
    py_ok = sys.version_info >= (3, 11)
    results.append(_check("Python >= 3.11", py_ok, sys.version.split()[0]))
    in_venv = sys.prefix != sys.base_prefix
    results.append(_check("Running inside a virtual environment", in_venv, sys.prefix))

    for module in REQUIRED_IMPORTS:
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", "")
            results.append(_check(f"import {module}", True, str(version)))
        except ImportError as exc:
            results.append(_check(f"import {module}", False, str(exc)))

    results.append(_check("git on PATH", shutil.which("git") is not None))
    results.append(_check("Project git repo initialised", (ROOT / ".git").is_dir()))
    tracked = _git_tracks_secrets()
    results.append(_check("No secret files tracked by git", not tracked, ", ".join(tracked)))
    _check(".env present (needed for Snowflake checks)", (ROOT / ".env").is_file(), required=False)

    print()
    if all(results):
        print("Environment OK.")
        return 0
    print("Environment has failures (see FAIL lines).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
