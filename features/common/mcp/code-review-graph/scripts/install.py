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


def find_uv() -> str | None:
    """Return the uv executable if it is on PATH."""
    return shutil.which("uv")


def verify_serves(exe: Path | str) -> bool:
    """Report whether `exe serve` can actually start the MCP server.

    The executable existing proves nothing: a co-installed mcp>=2 clobbers
    fastmcp and leaves the CLI working while `serve` dies on import.
    """
    try:
        with open(os.devnull, "rb") as devnull:
            res = subprocess.run(
                [str(exe), "serve"], stdin=devnull, capture_output=True,
                text=True, timeout=60, check=False,
            )
        return res.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


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


def ensure_pip(venv_py: Path) -> None:
    """Ensure pip is available in venv_py."""
    verify_pip = subprocess.run([str(venv_py), "-m", "pip", "--version"], capture_output=True, check=False)
    if verify_pip.returncode != 0:
        print(f"Bootstrapping pip in {venv_py} via ensurepip...")
        subprocess.run([str(venv_py), "-m", "ensurepip", "--default-pip"], capture_output=True, check=False)


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
        uv_exe = find_uv()

        # uv resolves the full dependency set in one pass; pip is the fallback.
        if uv_exe:
            print(f"Installing code-review-graph with uv into {venv_py.parent.parent}...")
            cmd = [uv_exe, "pip", "install", "--upgrade",
                   "--python", str(venv_py), "code-review-graph"]
        else:
            ensure_pip(venv_py)
            print(f"Installing code-review-graph using {venv_py}...")
            cmd = [str(venv_py), "-m", "pip", "install", "--upgrade", "code-review-graph"]

        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print(f"ERROR: install failed:\n{res.stderr}", file=sys.stderr)
            return 1

        crg_exe = get_venv_crg(target_dir / ".venv")
        if not crg_exe.exists():
            print("ERROR: Installation finished but no code-review-graph executable was produced.", file=sys.stderr)
            return 1

        if not verify_serves(crg_exe):
            print(
                f"ERROR: {crg_exe} was installed but cannot serve. code-review-graph "
                "requires mcp<2; if this environment also holds a package that pulls "
                "mcp>=2 (semantica, for one), fastmcp breaks and the MCP server will "
                "not connect. Give code-review-graph an environment of its own — "
                "`uv tool install code-review-graph`.",
                file=sys.stderr,
            )
            return 1

        print(f"SUCCESS: code-review-graph installed at {crg_exe} and verified to serve.")
        return 0

    except Exception as ex:  # pylint: disable=broad-exception-caught
        print(f"ERROR: Failed to install code-review-graph: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
