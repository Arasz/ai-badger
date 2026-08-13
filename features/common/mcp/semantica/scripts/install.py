#!/usr/bin/env python3
"""Installation script for semantica MCP server.

Discovers Python 3.10+, sets up a virtual environment (.venv) if needed,
and installs/upgrades semantica via pip.

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


def ensure_venv(target_dir: Path, py_exe: str) -> Path:
    """Ensure .venv exists in target_dir, creating it with py_exe if missing."""
    venv_dir = target_dir / ".venv"
    venv_py = get_venv_python(venv_dir)

    if not venv_py.exists():
        print(f"Creating Python virtual environment in {venv_dir} using {py_exe}...")
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(venv_dir)

    return venv_py


def ensure_pip(venv_py: Path) -> None:
    """Ensure pip is available in venv_py."""
    verify_pip = subprocess.run([str(venv_py), "-m", "pip", "--version"], capture_output=True, check=False)
    if verify_pip.returncode != 0:
        print(f"Bootstrapping pip in {venv_py} via ensurepip...")
        subprocess.run([str(venv_py), "-m", "ensurepip", "--default-pip"], capture_output=True, check=False)


def main(argv: list[str] | None = None) -> int:
    """Install semantica in target environment."""
    parser = argparse.ArgumentParser(description="Install semantica MCP server.")
    parser.add_argument("--target", default=".", help="Target project directory")
    args = parser.parse_args(argv)

    target_dir = Path(args.target).resolve()

    py_exe = find_suitable_python()
    if not py_exe:
        print("ERROR: Could not find Python >= 3.10 on system. Please install Python 3.10+.", file=sys.stderr)
        return 1

    try:
        venv_py = ensure_venv(target_dir, py_exe)
        ensure_pip(venv_py)
        print(f"Installing semantica using {venv_py}...")

        # Run pip install inside venv
        cmd = [str(venv_py), "-m", "pip", "install", "--upgrade", "semantica"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print(f"ERROR: pip install failed:\n{res.stderr}", file=sys.stderr)
            return 1

        # Verify semantica importability via venv python
        verify_res = subprocess.run([str(venv_py), "-c", "import semantica"], capture_output=True, check=False)
        if verify_res.returncode == 0:
            print("SUCCESS: semantica module installed in venv.")
            return 0

        print("ERROR: Installation finished but semantica could not be verified.", file=sys.stderr)
        return 1

    except Exception as ex:  # pylint: disable=broad-exception-caught
        print(f"ERROR: Failed to install semantica: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
