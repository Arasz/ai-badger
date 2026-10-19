"""Shared parent collection behavior through its public command line."""
from __future__ import annotations

import json
import os
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


def _snapshot(tree: Path) -> dict[str, tuple[str, bytes | str]]:
    """Observe content and raw link targets without traversing directory symlinks."""
    if tree.is_symlink():
        return {".": ("link", os.readlink(tree))}
    snapshot = {}
    for base, directories, files in os.walk(tree, followlinks=False):
        for name in directories + files:
            path = Path(base) / name
            relative = path.relative_to(tree).as_posix()
            if path.is_symlink():
                snapshot[relative] = ("link", os.readlink(path))
            elif path.is_file():
                snapshot[relative] = ("file", path.read_bytes())
            else:
                snapshot[relative] = ("directory", "")
    return snapshot


def _collected_pair(tmp_path: Path, root: Path,
                    parent_config: dict | None = None) -> tuple[Path, Path, Path]:
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], "canonical-dotnet")
    _test_write(first / "pyproject.toml", "[project]\nname = 'python-app'\n")
    _test_write(second / "App.csproj", "<Project />\n")
    args = ["collect", "--target", str(collection),
            "--repo", "python-app", "--repo", "dotnet-app"]
    if parent_config is not None:
        path = tmp_path / "parent-config.json"
        _write_json(path, parent_config)
        args.extend(["--config", str(path)])
    _success(_shared(root, *args))
    return collection / ".ai-badger", first, second


def test_sync_inherits_parent_objects_and_replaces_child_lists(tmp_path, root):
    """Local commands merge, list filters replace, and the selected child stays isolated."""
    parent_config = _config(stacks=["python", "dotnet"], commands={
        "build": "parent-build", "lint": "parent-lint", "test": "parent-test"})
    parent_config["exclude"] = {"skills": ["task", "design-tests"]}
    parent_config["docs"] = {"architecture": "docs/architecture.md"}
    source, child, sibling = _collected_pair(tmp_path, root, parent_config)
    descriptor_path = child / ".ai-badger" / "shared-scope.json"
    assert descriptor_path.is_file(), "collect must persist authored child overrides separately"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["overrides"]["commands"] = {"test": "child-test"}
    descriptor["overrides"]["exclude"] = {"skills": ["task"]}
    _write_json(descriptor_path, descriptor)
    parent_before, sibling_before = _snapshot(source), _snapshot(sibling)
    child_id = (child / ".ai-badger" / "project-id").read_bytes()

    result = _shared(root, "sync", "--target", str(child), "--source", str(source))

    _success(result)
    config = json.loads((child / ".ai-badger" / "config.json").read_text())
    assert config["commands"] == {
        "build": "parent-build", "lint": "parent-lint", "test": "child-test"}
    assert config["exclude"]["skills"] == ["task"]
    assert config["docs"]["architecture"] == "docs/architecture.md"
    assert config["stacks"] == ["python"]
    assert (child / ".ai-badger" / "instructions" / "python.instructions.md").is_file()
    assert not (child / ".ai-badger" / "instructions" / "csharp.instructions.md").exists()
    assert (child / ".ai-badger" / "skills" / "design-tests" / "SKILL.md").is_file()
    assert (child / ".ai-badger" / "project-id").read_bytes() == child_id
    assert _snapshot(source) == parent_before
    assert _snapshot(sibling) == sibling_before
