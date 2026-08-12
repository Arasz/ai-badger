#!/usr/bin/env python3
"""Installation script for code-review-graph MCP server.

Discovers Python 3.10+, sets up a virtual environment (.venv) if needed,
and installs/upgrades code-review-graph via pip.

Usage: python3 install.py [--target <dir>]
Exit code: 0 = success, 1 = failure.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


def find_suitable_python() -> str | None:
    """Find a Python 3.10+ interpreter on the system."""
    if sys.version_info >= (3, 10):
        return sys.executable

    candidates = [
        "/opt/homebrew/bin/python3.14",
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3.10",
        "/usr/local/bin/python3.12",
        "/usr/local/bin/python3.11",
        "python3.12",
        "python3.11",
        "python3.10",
        "python3",
    ]

    for candidate in candidates:
        exe = shutil.which(candidate) if not Path(candidate).is_absolute() else candidate
        if not exe or not Path(exe).exists():
            continue
        try:
            res = subprocess.run(
                [exe, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                capture_output=True, text=True, timeout=5, check=False
            )
            if res.returncode == 0:
                parts = res.stdout.strip().split(".")
                if len(parts) >= 2 and (int(parts[0]), int(parts[1])) >= (3, 10):
                    return exe
        except (subprocess.SubprocessError, ValueError, OSError):
            continue

    return None


def get_venv_python(venv_dir: Path) -> Path:
    """Return path to python binary inside venv_dir."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def get_venv_crg(venv_dir: Path) -> Path:
    """Return path to code-review-graph executable inside venv_dir."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "code-review-graph.exe"
    return venv_dir / "bin" / "code-review-graph"


def ensure_venv(target_dir: Path, py_exe: str) -> Path:
    """Ensure .venv exists in target_dir, creating it with py_exe if missing."""
    venv_dir = target_dir / ".venv"
    venv_py = get_venv_python(venv_dir)

    if not venv_py.exists():
        print(f"Creating Python virtual environment in {venv_dir} using {py_exe}...")
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(venv_dir)

    return venv_py


def main(argv: list[str] | None = None) -> int:
    """Install code-review-graph in target environment."""
    parser = argparse.ArgumentParser(description="Install code-review-graph MCP server.")
    parser.add_argument("--target", default=".", help="Target project directory")
    args = parser.parse_args(argv)

    target_dir = Path(args.target).resolve()

    py_exe = find_suitable_python()
    if not py_exe:
        print("ERROR: Could not find Python >= 3.10 on system. Please install Python 3.10+.", file=sys.stderr)
        return 1

    try:
        venv_py = ensure_venv(target_dir, py_exe)
        print(f"Installing code-review-graph using {venv_py}...")

        # Run pip install inside venv
        cmd = [str(venv_py), "-m", "pip", "install", "--upgrade", "code-review-graph"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print(f"ERROR: pip install failed:\n{res.stderr}", file=sys.stderr)
            return 1

        crg_exe = get_venv_crg(target_dir / ".venv")
        if crg_exe.exists():
            print(f"SUCCESS: code-review-graph installed at {crg_exe}")
            return 0

        # Fallback check via venv python -m code_review_graph
        verify_res = subprocess.run([str(venv_py), "-c", "import code_review_graph"], capture_output=True, check=False)
        if verify_res.returncode == 0:
            print("SUCCESS: code-review-graph module installed in venv.")
            return 0

        print("ERROR: Installation finished but code-review-graph could not be verified.", file=sys.stderr)
        return 1

    except Exception as ex:  # pylint: disable=broad-exception-caught
        print(f"ERROR: Failed to install code-review-graph: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
