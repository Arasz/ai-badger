#!/usr/bin/env python3
"""Check and install dependencies declared in dependencies.json.

Reads features/common/dependencies.json from the framework root, matches entries
against the scaffolded feature set, ensures a Python venv exists when needed,
and installs packages. Reports what was installed, already present, or failed.

Usage:
  dependency_check.py --root <framework> --target <project> [--features f1,f2]

MECHANICAL ONLY — no LLM. The agent's role is to present the report and act
on installation instructions.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_dependencies(root: Path) -> List[Dict[str, Any]]:
    """Load dependencies.json from the framework root."""
    deps_path = root / "features" / "common" / "dependencies.json"
    if not deps_path.exists():
        return []
    data = json.loads(deps_path.read_text(encoding="utf-8"))
    return data.get("dependencies", [])


def _check_uv_available() -> bool:
    """Return True if uv is on PATH."""
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _ensure_venv(target: Path) -> Path:
    """Create .venv in target if it doesn't exist. Return the venv path."""
    venv_path = target / ".venv"
    if venv_path.exists():
        return venv_path
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_path)],
        check=True, capture_output=True, text=True,
    )
    return venv_path


def _install_python(
    dep: Dict[str, Any], venv_path: Path, uv_available: bool,
) -> List[str]:
    """Install Python packages for one dependency entry.

    Returns a list of error strings (empty on success).
    """
    errors: List[str] = []
    pkg = dep["package"]
    extras = dep.get("extras", "")
    spec = f"{pkg}{extras}"

    if uv_available:
        env = dict(os.environ)
        env["VIRTUAL_ENV"] = str(venv_path)
        pip_cmd = ["uv", "pip", "install", spec]
    else:
        pip_path = str(venv_path / "bin" / "pip")
        pip_cmd = [pip_path, "install", spec]

    try:
        result = subprocess.run(
            pip_cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            errors.append(f"{pkg}: pip install failed — {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        errors.append(f"{pkg}: pip install timed out (120s)")
    except FileNotFoundError:
        errors.append(f"{pkg}: pip not found at {pip_cmd[0]}")
    return errors


def _install_node(dep: Dict[str, Any]) -> List[str]:
    """Install Node packages for one dependency entry.

    Returns a list of error strings (empty on success).
    """
    errors: List[str] = []
    pkg = dep["package"]
    try:
        result = subprocess.run(
            ["npm", "install", "-g", pkg],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            errors.append(f"{pkg}: npm install failed — {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        errors.append(f"{pkg}: npm install timed out (120s)")
    except FileNotFoundError:
        errors.append(f"{pkg}: npm not found on PATH")
    return errors


def get_venv_python(target: Path) -> Optional[str]:
    """Return the venv python3 path if a .venv exists in target, else None."""
    venv_path = target / ".venv"
    if not venv_path.exists():
        return None
    return str(venv_path / "bin" / "python3")


def run_dependency_check(
    root: Path,
    target: Path,
    features: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Check and install all declared dependencies for the given features.

    Returns {"installed": [...], "already_present": [...], "errors": [...]}.
    """
    deps = _load_dependencies(root)
    if not deps:
        return {"installed": [], "already_present": [], "errors": []}

    installed: List[str] = []
    already_present: List[str] = []
    errors: List[str] = []

    # Filter to requested features
    active = [
        d for d in deps
        if features is None or d["feature"] in features
    ]

    # Check which Python deps need venv
    needs_venv = any(
        dep.get("venv") and dep["ecosystem"] == "python"
        for entry in active
        for dep in entry["dependencies"]
    )
    venv_path: Optional[Path] = None
    uv_available = False

    if needs_venv:
        venv_path = _ensure_venv(target)
        uv_available = _check_uv_available()

    for entry in active:
        for dep in entry["dependencies"]:
            eco = dep["ecosystem"]
            pkg = dep["package"]

            if eco == "python":
                if venv_path is None:
                    errors.append(f"{pkg}: venv required but not created")
                    continue
                dep_errors = _install_python(dep, venv_path, uv_available)
            elif eco == "node":
                dep_errors = _install_node(dep)
            else:
                dep_errors = [f"{pkg}: unknown ecosystem '{eco}'"]

            if dep_errors:
                errors.extend(dep_errors)
            else:
                installed.append(pkg)

    return {
        "installed": installed,
        "already_present": already_present,
        "errors": errors,
    }


def detect_new_deps(
    root: Path,
    scaffolded_features: List[str],
) -> List[Dict[str, Any]]:
    """Return dependency entries whose feature is not in scaffolded_features."""
    deps = _load_dependencies(root)
    return [d for d in deps if d["feature"] not in scaffolded_features]


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: check dependencies, install if missing, report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="framework repo root")
    parser.add_argument("--target", required=True, help="project root")
    parser.add_argument(
        "--features", default=None,
        help="comma-separated feature names to check (default: all)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    target = Path(args.target).resolve()
    features = (
        [f.strip() for f in args.features.split(",")]
        if args.features else None
    )

    result = run_dependency_check(root, target, features=features)

    if result["installed"]:
        print(f"installed: {', '.join(result['installed'])}")
    if result["errors"]:
        for err in result["errors"]:
            print(f"error: {err}", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
