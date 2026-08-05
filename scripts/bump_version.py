#!/usr/bin/env python3
"""Bump Let Me Work version in lockstep. Usage: python scripts/bump_version.py 0.1.0-beta.2"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# SemVer core + optional -prerelease (no build metadata)
VER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?$"
)


def win_file_version(ver: str) -> str:
    """Inno VersionInfoVersion needs up to 4 numeric parts (e.g. 0.1.0.2 for beta.2)."""
    core, _, pre = ver.partition("-")
    parts = [int(x) for x in core.split(".")]
    while len(parts) < 3:
        parts.append(0)
    fourth = 0
    if pre:
        m = re.search(r"(\d+)$", pre)
        if m:
            fourth = int(m.group(1))
    return f"{parts[0]}.{parts[1]}.{parts[2]}.{fourth}"


def replace_file(path: Path, pattern: str, repl: str, flags: int = 0) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise SystemExit(f"bump failed in {path}: pattern matched {n} times")
    path.write_text(new, encoding="utf-8", newline="\n")


def main() -> None:
    if len(sys.argv) != 2 or not VER_RE.match(sys.argv[1]):
        raise SystemExit(__doc__.strip())
    ver = sys.argv[1]
    win = win_file_version(ver)

    replace_file(
        ROOT / "user_data.py",
        r'APP_VERSION = "[^"]*"',
        f'APP_VERSION = "{ver}"',
    )
    replace_file(
        ROOT / "pyproject.toml",
        r'^version = "[^"]*"',
        f'version = "{ver}"',
        flags=re.M,
    )
    replace_file(
        ROOT / "frontend" / "package.json",
        r'"version": "[^"]*"',
        f'"version": "{ver}"',
    )
    replace_file(
        ROOT / "packaging" / "LetMeWork.iss",
        r'#define MyAppVersion "[^"]*"',
        f'#define MyAppVersion "{ver}"',
    )
    replace_file(
        ROOT / "packaging" / "LetMeWork.iss",
        r"VersionInfoVersion=\S+",
        f"VersionInfoVersion={win}",
    )
    print(f"Bumped to {ver} (VersionInfoVersion={win})")
    print("Next: update CHANGELOG.md, then commit / tag / build / gh release (see RELEASE.md)")


if __name__ == "__main__":
    main()
