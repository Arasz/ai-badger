"""Shared parent collection behavior through its public command line."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import _test_write
from scaffold_helpers import _config

SHARED_SCRIPT = "features/common/skills/welcome-ai-badger/scripts/shared_scope.py"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, json.dumps(value, indent=2) + "\n")


def _member(collection: Path, name: str, stacks: list[str], project_id: str) -> Path:
    target = collection / name
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(target)], check=True,
                   capture_output=True, text=True)
    _write_json(target / ".ai-badger" / "config.json", _config(stacks=stacks))
    _test_write(target / ".ai-badger" / "project-id", project_id + "\n")
    return target


def _shared(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / SHARED_SCRIPT), *args,
                           "--root", str(root)], capture_output=True, text=True,
                          timeout=60)


def _success(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_parent_stacks_are_union_of_explicit_members(tmp_path, root):
    """Collect both selected stacks while excluding an unlisted neighboring repository."""
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], "canonical-dotnet")
    unlisted = _member(collection, "unlisted", ["react", "ts", "node"], "canonical-other")
    _test_write(first / "pyproject.toml", "[project]\nname = 'python-app'\n")
    _test_write(second / "App.csproj", "<Project />\n")
    _write_json(unlisted / "package.json", {"dependencies": {"react": "18.0.0"}})
    identities = {path: (path / ".ai-badger" / "project-id").read_bytes()
                  for path in (first, second, unlisted)}

    result = _shared(root, "collect", "--target", str(collection),
                     "--repo", "python-app", "--repo", "dotnet-app")

    _success(result)
    config = json.loads((collection / ".ai-badger" / "config.json").read_text())
    assert set(config["stacks"]) == {"python", "dotnet"}
    assert len(config["stacks"]) == 2
    assert (collection / ".ai-badger" / "instructions" / "python.instructions.md").is_file()
    assert (collection / ".ai-badger" / "instructions" / "csharp.instructions.md").is_file()
    assert not (collection / ".ai-badger" / "instructions" / "react.instructions.md").exists()
    for path, identity in identities.items():
        assert (path / ".ai-badger" / "project-id").read_bytes() == identity
