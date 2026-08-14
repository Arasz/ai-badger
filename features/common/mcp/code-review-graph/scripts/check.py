#!/usr/bin/env python3
"""Prerequisite check script for code-review-graph MCP server.

Checks if Python is >= 3.10 and code-review-graph is executable on PATH,
in local .venv, or importable as code_review_graph.

Exit code: 0 = ready, 1 = missing or incompatible environment.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_python_version() -> bool:
    """Verify system or active Python interpreter is >= 3.10."""
    return sys.version_info >= (3, 10)


def find_crg_executable(target: Path | None = None) -> str | None:
    """Find code-review-graph executable on PATH or in target's local .venv."""
    # 1. Check PATH
    exe = shutil.which("code-review-graph")
    if exe:
        return exe

    # 2. Check local .venv under target (or cwd)
    base = target or Path.cwd()
    venv_dirs = [base / ".venv", base / "venv"]
    for venv in venv_dirs:
        unix_bin = venv / "bin" / "code-review-graph"
        win_bin = venv / "Scripts" / "code-review-graph.exe"
        if unix_bin.is_file() and os.access(unix_bin, os.X_OK):
            return str(unix_bin)
        if win_bin.is_file():
            return str(win_bin)

    return None


def can_serve(exe: str) -> bool:
    """Report whether `exe serve` can actually start the MCP server.

    `--version` stays green when a co-installed mcp>=2 clobbers fastmcp, so the
    only honest probe is the serve entrypoint itself: with stdin at EOF it exits
    0 when healthy and non-zero on the import failure.
    """
    try:
        with open(os.devnull, "rb") as devnull:
            res = subprocess.run(
                [exe, "serve"], stdin=devnull, capture_output=True,
                text=True, timeout=60, check=False,
            )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def can_import_crg() -> bool:
    """Check if code_review_graph is importable by current Python."""
    try:
        mod = importlib.import_module("code_review_graph")
        return hasattr(mod, "__version__") or True
    except ImportError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Run prerequisite check for code-review-graph."""
    target_dir = Path.cwd()
    if argv and len(argv) > 1 and argv[0] == "--target":
        target_dir = Path(argv[1]).resolve()

    if not check_python_version():
        print(f"python3 version {sys.version.split()[0]} is too old (requires Python 3.10+)", file=sys.stderr)
        return 1

    exe = find_crg_executable(target_dir)
    if exe:
        if can_serve(exe):
            print(f"code-review-graph ready: {exe}")
            return 0
        print(
            f"code-review-graph at {exe} is installed but cannot serve. Most often a "
            "co-installed mcp>=2 has broken fastmcp (code-review-graph requires mcp<2); "
            "reinstall it into an environment of its own.",
            file=sys.stderr,
        )
        return 1

    if can_import_crg():
        print("code-review-graph importable in Python environment")
        return 0

    print("code-review-graph is not installed or not in PATH / .venv", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
