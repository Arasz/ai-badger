#!/usr/bin/env python3
"""Prerequisite check script for semantica MCP server.

Checks if Python is >= 3.10 and semantica is executable on PATH,
in local .venv, or importable as semantica.

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


def find_semantica_executable(target: Path | None = None) -> str | None:
    """Find semantica executable or module in target's local .venv or PATH."""
    # 1. Check PATH
    exe = shutil.which("semantica")
    if exe:
        return exe

    # 2. Check local .venv under target (or cwd)
    base = target or Path.cwd()
    venv_dirs = [base / ".venv", base / "venv"]
    for venv in venv_dirs:
        unix_bin = venv / "bin" / "semantica"
        win_bin = venv / "Scripts" / "semantica.exe"
        if unix_bin.is_file() and os.access(unix_bin, os.X_OK):
            return str(unix_bin)
        if win_bin.is_file():
            return str(win_bin)

    return None


def can_import_semantica() -> bool:
    """Check if semantica module is importable by current Python."""
    try:
        mod = importlib.import_module("semantica")
        return hasattr(mod, "__version__") or True
    except ImportError:
        return False


def _probe_export_graph() -> dict:
    """Call the installed MCP server's export_graph handler directly.

    Deterministic probe for the upstream 0.6.5/0.6.6 breakage: the json branch
    calls JSONExporter().export(graph) with no file_path and returns
    {"error": ...}. A fixed version returns {"format": ..., "data": ...}.
    Returns the handler's dict; raises on import/setup failure.
    """
    server = importlib.import_module("semantica.mcp_server")
    return server._tool_export_graph({"format": "json"})


def export_graph_works() -> bool:
    """True when the installed semantica's export_graph json branch works."""
    try:
        result = _probe_export_graph()
    except Exception:  # pylint: disable=broad-exception-caught
        return False
    return isinstance(result, dict) and "error" not in result


def main(argv: list[str] | None = None) -> int:
    """Run prerequisite check for semantica."""
    target_dir = Path.cwd()
    if argv and len(argv) > 1 and argv[0] == "--target":
        target_dir = Path(argv[1]).resolve()

    if not check_python_version():
        print(f"python3 version {sys.version.split()[0]} is too old (requires Python 3.10+)", file=sys.stderr)
        return 1

    exe = find_semantica_executable(target_dir)
    if exe:
        try:
            res = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0:
                print(f"semantica ready: {res.stdout.strip() or exe}")
                if not export_graph_works():
                    print(
                        "WARNING: the installed semantica's export_graph tool is broken "
                        "(upstream bug: JSONExporter.export() called without file_path; "
                        "fixed in a release after 0.6.6). The graph tools still work; "
                        "auto-saved .semantica/ dumps are skipped until it is fixed.",
                        file=sys.stderr,
                    )
                return 0
        except (subprocess.SubprocessError, OSError):
            pass

    if can_import_semantica():
        print("semantica module importable in Python environment")
        if not export_graph_works():
            print(
                "WARNING: the installed semantica's export_graph tool is broken "
                "(upstream bug: JSONExporter.export() called without file_path; "
                "fixed in a release after 0.6.6). The graph tools still work; "
                "auto-saved .semantica/ dumps are skipped until it is fixed.",
                file=sys.stderr,
            )
        return 0

    print("semantica is not installed or not in PATH / .venv", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
