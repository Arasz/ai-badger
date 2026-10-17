#!/usr/bin/env python3
"""Prerequisite check for the rtk tool: rtk-ai's `rtk` >= 1.0.1 on PATH.

Exit code: 0 = ready, 1 = absent, too old, or a different program named rtk.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys

FLOOR = (1, 0, 1)
VERSION_LINE = re.compile(r"^rtk (\d+)\.(\d+)\.(\d+)")


def read_version(exe: str) -> tuple[int, int, int] | None:
    """Return the version `exe --version` reports, or None when it is not rtk-ai's rtk."""
    try:
        result = subprocess.run(
            [exe, "--version"], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=10, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    match = VERSION_LINE.match(result.stdout.strip())
    if not match:
        return None
    return (int(match[1]), int(match[2]), int(match[3]))


def main() -> int:
    """Report whether a usable rtk is on PATH."""
    floor = ".".join(map(str, FLOOR))
    exe = shutil.which("rtk")
    if not exe:
        print(f"rtk is not on PATH (requires rtk-ai rtk >= {floor})", file=sys.stderr)
        return 1

    version = read_version(exe)
    if version is None:
        print(
            f"{exe} is not rtk-ai's rtk: `rtk --version` did not print `rtk <version>`. "
            "crates.io `rtk` is a different crate (Rust Type Kit).",
            file=sys.stderr,
        )
        return 1
    if version < FLOOR:
        found = ".".join(map(str, version))
        print(f"rtk {found} at {exe} is older than {floor}", file=sys.stderr)
        return 1

    print(f"rtk {'.'.join(map(str, version))} ready: {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
