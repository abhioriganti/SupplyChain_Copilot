"""Fail if any git-tracked file looks like it contains a secret (run locally and in CI).

Usage:  python scripts/check_secrets.py
Checks every tracked file for private keys, JWT/bearer tokens, PATs and credential assignments, and that
no key/env files are tracked at all. Known dummy strings in tests are allow-listed explicitly.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_FILES = re.compile(
    r"(^|/)(\.env|.*\.p8|.*\.pem|.*\.key|connections\.toml|secrets\.toml)$"
)
PATTERNS = {
    "private key block": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*\n\s*[A-Za-z0-9+/=]{40,}"
    ),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    "credential assignment": re.compile(
        r"(?i)\b(password|passphrase|private_key|secret|token)\s*[:=]\s*['\"][^'\"\s<>{}]{8,}['\"]"
    ),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "Slack webhook URL": re.compile(
        r"hooks\.slack\.com/(services|workflows|triggers)/[A-Za-z0-9/_-]{20,}"
    ),
    "Slack token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
}
ALLOW = {"hunter2"}  # dummy values used by redaction tests


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return [f for f in out.stdout.splitlines() if f]


def main() -> int:
    problems: list[str] = []
    for rel in tracked_files():
        if FORBIDDEN_FILES.search(rel) and not rel.endswith(".env.example"):
            problems.append(f"{rel}: secret-bearing file type is tracked")
            continue
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pat in PATTERNS.items():
            for m in pat.finditer(text):
                if not any(a in m.group(0) for a in ALLOW):
                    problems.append(f"{rel}: possible {name}")
    for p in problems:
        print(p)
    print("Secret scan: " + ("OK" if not problems else f"{len(problems)} problem(s)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
