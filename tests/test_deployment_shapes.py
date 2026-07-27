"""Framework-root resolution in the four deployment shapes ai-badger ships into (ADR-0007).

Shapes are built under `tmp_path` with `HOME` pointed at an empty tree: against a real home
the broken shapes pass for the wrong reason, via a stale `~/.ai-badger/framework` cache.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scaffold_helpers import _config

ROOT = Path(__file__).resolve().parents[1]

# A framework tree: everything the four root predicates and a scaffold run read.
_FRAMEWORK_TREE = ("features", "schemas", "scripts", "hooks", ".claude-plugin",
                   "VERSION", "index.json", "BREAKING_VERSIONS")

# Every entry point that must resolve a framework root before it can do anything, keyed by
# name and given as a path relative to a framework root.
ENTRY_POINTS = {
    "detect": "features/common/skills/welcome-ai-badger/scripts/detect.py",
    "scaffold": "features/common/skills/welcome-ai-badger/scripts/scaffold.py",
    "drift": "features/common/skills/welcome-ai-badger/scripts/drift.py",
    "refresh": "features/common/skills/den-refresh/scripts/refresh.py",
    "detect_additions": "features/common/skills/feed-badger/scripts/detect_additions.py",
    "open_pr": "features/common/skills/feed-badger/scripts/open_pr.py",
    "drift_notice_hook": "features/common/skills/task/scripts/drift_notice_hook.py",
    "mcp_index": "features/common/skills/mcp-index/scripts/mcp_index.py",
    "ai_badger_hooks": "features/common/hooks/ai_badger_hooks.py",
    "learned_skills_sync": "features/common/hooks/learned_skills_sync.py",
}

# Where the scaffold shape puts each entry point; a name absent here is not scaffolded.
SCAFFOLD_PATHS = {
    "detect": ".ai-badger/skills/welcome-ai-badger/scripts/detect.py",
    "scaffold": ".ai-badger/skills/welcome-ai-badger/scripts/scaffold.py",
    "drift": ".ai-badger/skills/welcome-ai-badger/scripts/drift.py",
    "refresh": ".ai-badger/skills/den-refresh/scripts/refresh.py",
    "detect_additions": ".ai-badger/skills/feed-badger/scripts/detect_additions.py",
    "open_pr": ".ai-badger/skills/feed-badger/scripts/open_pr.py",
    "drift_notice_hook": ".ai-badger/skills/task/scripts/drift_notice_hook.py",
    "mcp_index": ".ai-badger/skills/mcp-index/scripts/mcp_index.py",
    "ai_badger_hooks": ".ai-badger/hooks/ai_badger_hooks.py",
}

# `features/hermes/adjustments/adjust_hooks.py` copies exactly these two into ~/.hermes/plugins/.
HERMES_PLUGINS = ("ai_badger_hooks", "learned_skills_sync")

# Entry points whose CLI must be reachable: argparse cannot run if the shim raised at import.
CLI_HELP = ("detect", "scaffold", "drift", "refresh", "detect_additions", "open_pr",
            "learned_skills_sync")

SHAPES = ("checkout", "scaffold", "plugin-cache", "hermes-plugins")

# Imports the module the way its deployment does, then reports the root it resolved.
_PROBE = '''
import importlib.util, json, sys
from pathlib import Path

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("aib_probe_" + path.stem, path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
root = getattr(mod, "FRAMEWORK_ROOT", "__missing__")
print("AIB_ROOT=" + json.dumps(None if root is None else str(root)))
'''


def _copy_framework(dest: Path) -> Path:
    """Copy the framework tree to `dest` — what a checkout and a plugin cache both are."""
    dest.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in _FRAMEWORK_TREE:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=ignore)
        elif src.is_file():
            shutil.copy2(src, dest / name)
    return dest


def _env(home: Path) -> dict:
    """A process environment with an empty home and no `$AI_BADGER` escape hatch."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("AI_BADGER", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _write_config(path: Path) -> Path:
    cfg = _config(stacks=["python"], agents=["claude", "hermes"])
    cfg["frameworkVersion"] = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def shapes(tmp_path_factory) -> dict:
    """Build all four deployment shapes once, under one empty home."""
    base = tmp_path_factory.mktemp("deployment-shapes")
    home = base / "home"
    home.mkdir()

    checkout = _copy_framework(base / "checkout")
    version = (checkout / "VERSION").read_text(encoding="utf-8").strip()
    cache = _copy_framework(
        home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger" / version)

    consumer = base / "consumer"
    consumer.mkdir()
    config = _write_config(base / "config.json")
    proc = subprocess.run(
        [sys.executable, str(checkout / ENTRY_POINTS["scaffold"]),
         "--config", str(config), "--target", str(consumer), "--root", str(checkout),
         "--no-install"],
        capture_output=True, text=True, cwd=str(consumer), env=_env(home), check=False)
    assert proc.returncode == 0, f"scaffold run failed:\n{proc.stdout}\n{proc.stderr}"

    return {"home": home, "checkout": checkout, "cache": cache, "consumer": consumer,
            "hermes": home / ".hermes" / "plugins"}


def _entry_path(shapes: dict, shape: str, name: str) -> Path:
    """On-disk location of entry point `name` in `shape`, or skip if the shape has no copy."""
    if shape == "checkout":
        return shapes["checkout"] / ENTRY_POINTS[name]
    if shape == "plugin-cache":
        return shapes["cache"] / ENTRY_POINTS[name]
    if shape == "scaffold":
        if name not in SCAFFOLD_PATHS:
            pytest.skip(f"{name} is not scaffolded into .ai-badger/")
        return shapes["consumer"] / SCAFFOLD_PATHS[name]
    if name not in HERMES_PLUGINS:
        pytest.skip(f"{name} is not installed into ~/.hermes/plugins/")
    return shapes["hermes"] / Path(ENTRY_POINTS[name]).name


def _cwd_for(shapes: dict, shape: str) -> Path:
    """A hermes plugin only ever runs inside a project; the others run where they live."""
    return shapes["consumer"] if shape in ("scaffold", "hermes-plugins") else shapes["checkout"]


def _probe_root(shapes: dict, shape: str, path: Path, tmp_path: Path):
    """Import `path` in a fresh interpreter and return (process, reported root)."""
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(probe), str(path)],
                          capture_output=True, text=True, cwd=str(_cwd_for(shapes, shape)),
                          env=_env(shapes["home"]), check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("AIB_ROOT=")]
    reported = json.loads(lines[-1][len("AIB_ROOT="):]) if lines else "__missing__"
    return proc, reported


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_every_entry_point_resolves_the_root_in_all_four_shapes(shapes, name, shape, tmp_path):
    """Each entry point imports and reports a real framework root in each deployment shape."""
    path = _entry_path(shapes, shape, name)
    assert path.is_file(), f"{name} missing from the {shape} shape at {path}"

    proc, reported = _probe_root(shapes, shape, path, tmp_path)
    assert proc.returncode == 0, f"{name} failed to import in the {shape} shape:\n{proc.stderr}"
    assert reported != "__missing__", f"{name} exposes no FRAMEWORK_ROOT in the {shape} shape"
    assert reported is not None, f"{name} resolved no framework root in the {shape} shape"

    resolved = Path(reported)
    assert (resolved / "schemas").is_dir() and (resolved / "features").is_dir(), (
        f"{name} resolved {resolved} in the {shape} shape, which is not a framework root")


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("name", sorted(CLI_HELP))
def test_every_cli_entry_point_reaches_argparse_in_all_four_shapes(shapes, name, shape):
    """`--help` proves argparse is reachable: a shim that raises at import never gets there."""
    path = _entry_path(shapes, shape, name)
    proc = subprocess.run([sys.executable, str(path), "--help"],
                          capture_output=True, text=True, cwd=str(_cwd_for(shapes, shape)),
                          env=_env(shapes["home"]), check=False)
    assert proc.returncode == 0, (
        f"{name} --help failed in the {shape} shape:\n{proc.stdout}\n{proc.stderr}")
    assert "usage:" in proc.stdout


def test_hermes_drift_notice_has_a_version_to_compare(shapes, tmp_path):
    """ai_badger_hooks must reach a VERSION from ~/.hermes/plugins/ (ADR-0001 Tier 1)."""
    path = shapes["hermes"] / "ai_badger_hooks.py"
    proc, reported = _probe_root(shapes, "hermes-plugins", path, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert reported not in (None, "__missing__")
    assert (Path(reported) / "VERSION").is_file()
