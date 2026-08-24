#!/usr/bin/env python3
"""Prerequisite check script for semantica MCP server.

Checks if Python is >= 3.10 and semantica is executable on PATH,
in local .venv, or importable as semantica.

Exit code: 0 = ready, 1 = missing or incompatible environment.
"""
from __future__ import annotations

import importlib
import json
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


def _wrapper_script_path() -> Path | None:
    """Return the path to semantica_mcp_wrapper.py if it exists."""
    candidate = (
        Path(__file__).resolve().parent / "semantica_mcp_wrapper.py"
    )
    return candidate if candidate.is_file() else None


def _probe_wrapper_in_interpreter(interpreter: str) -> dict:
    """Run the wrapper's patched export_graph probe inside *interpreter*."""
    wrapper = _wrapper_script_path()
    if wrapper is None:
        raise FileNotFoundError("semantica_mcp_wrapper.py not found")
    snippet = (
        f"import sys; sys.path.insert(0, {str(wrapper.parent)!r}); "
        f"from semantica_mcp_wrapper import _patched_tool_export_graph; "
        f"import json; print(json.dumps(_patched_tool_export_graph({{'format': 'json'}})))"
    )
    res = subprocess.run(
        [interpreter, "-c", snippet], capture_output=True, text=True, timeout=15,
        check=False)
    if res.returncode != 0:
        raise RuntimeError(f"wrapper probe failed in {interpreter}: {res.stderr[:200]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def _interpreter_for_executable(exe: str) -> str | None:
    """The python interpreter beside *exe* (uv-tool / pipx / venv layout).

    A uv-tool or pipx install's `semantica` executable lives in its own venv,
    whose interpreter sits in the same bin directory; an ambient python cannot
    import semantica there, so the probe must shell out to this interpreter.
    None when the layout is unrecognised — warn nothing rather than misattribute.
    """
    bin_dir = Path(exe).resolve().parent
    for name in ("python", "python3", "python.exe"):
        candidate = bin_dir / name
        if candidate.is_file():
            return str(candidate)
    return None


def _probe_in_interpreter(interpreter: str) -> dict:
    """Run the export_graph probe inside *interpreter* (the resolved env)."""
    snippet = (
        "import json; from semantica import mcp_server; "
        "print(json.dumps(mcp_server._tool_export_graph({'format': 'json'})))"
    )
    res = subprocess.run(
        [interpreter, "-c", snippet], capture_output=True, text=True, timeout=10,
        check=False)
    if res.returncode != 0:
        raise RuntimeError(f"probe failed in {interpreter}: {res.stderr[:200]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def export_graph_works(exe: str | None = None) -> bool:
    """True when the installed semantica's export_graph json branch works.

    With *exe* (a resolved semantica executable), probe inside that install's
    own interpreter — the only env where semantica is importable for uv-tool /
    pipx installs. Without it, probe in-process (importable-venv path).

    If the native probe fails, try the wrapper script as a fallback.
    """
    try:
        if exe:
            interpreter = _interpreter_for_executable(exe)
            if interpreter is None:
                return True
            result = _probe_in_interpreter(interpreter)
        else:
            result = _probe_export_graph()
    except Exception:  # pylint: disable=broad-exception-caught
        # Import/setup failure inside the server module — not necessarily the
        # export bug; say nothing rather than misattribute.
        return True
    if isinstance(result, dict) and "error" not in result:
        return True
    # Native probe returned an error — try the wrapper fallback.
    try:
        if exe:
            interpreter = _interpreter_for_executable(exe)
            if interpreter is None:
                return False
            result = _probe_wrapper_in_interpreter(interpreter)
        else:
            wrapper = _wrapper_script_path()
            if wrapper is None:
                return False
            from semantica_mcp_wrapper import _patched_tool_export_graph  # pylint: disable=import-outside-toplevel
            result = _patched_tool_export_graph({"format": "json"})
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
                if not export_graph_works(exe=exe):
                    print(
                        "WARNING: the installed semantica's export_graph tool is broken "
                        "(upstream bug: JSONExporter.export() called without file_path; "
                        "fixed in a release after 0.6.6). No wrapper workaround found; "
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
                "fixed in a release after 0.6.6). No wrapper workaround found; "
                "auto-saved .semantica/ dumps are skipped until it is fixed.",
                file=sys.stderr,
            )
        return 0

    print("semantica is not installed or not in PATH / .venv", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
