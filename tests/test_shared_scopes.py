"""Shared parent collection behavior through its public command line."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import _test_write
from raccoon_cli_fake import raccoon_cli_fake  # noqa: F401  (fixture)
from scaffold_helpers import _config

SHARED_SCRIPT = "features/common/skills/welcome-ai-badger/scripts/shared_scope.py"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, json.dumps(value, indent=2) + "\n")


def _member(collection: Path, name: str, stacks: list[str], project_id: str | None) -> Path:
    target = collection / name
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(target)], check=True,
                   capture_output=True, text=True)
    _write_json(target / ".ai-badger" / "config.json", _config(stacks=stacks))
    if project_id is not None:
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


def test_a_child_without_its_own_identity_is_refused(tmp_path, root):
    """Enrollment must not invent an identity for a child that has none."""
    collection = tmp_path / "chosen collection"
    _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], None)
    _test_write(second / "App.csproj", "<Project />\n")
    before = _snapshot(second / ".ai-badger")

    result = _shared(root, "collect", "--target", str(collection),
                     "--repo", "python-app", "--repo", "dotnet-app")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "identity" in result.stderr
    assert not (second / ".ai-badger" / "project-id").exists()
    assert _snapshot(second / ".ai-badger") == before


def test_the_canonical_lookup_identity_is_reused(tmp_path, root, raccoon_cli_fake, monkeypatch):
    """The bank's own id for the child is written verbatim, never minted here."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 0, "stdout": "11111111-2222-3333-4444-555555555555\n",
                                 "stderr": ""})
    collection = tmp_path / "chosen collection"
    _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], None)
    _test_write(second / "App.csproj", "<Project />\n")

    result = _shared(root, "collect", "--target", str(collection),
                     "--repo", "python-app", "--repo", "dotnet-app")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (second / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip() == \
        "11111111-2222-3333-4444-555555555555"


def test_pruning_a_member_leaves_it_standalone(tmp_path, root):
    """A pruned member keeps its own identity, loses the links, and rejoins the ordinary flow."""
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], "canonical-dotnet")
    _test_write(first / "pyproject.toml", "[project]\n")
    _test_write(second / "App.csproj", "<Project />\n")
    _success(_shared(root, "collect", "--target", str(collection),
                     "--repo", "python-app", "--repo", "dotnet-app"))
    shared = second / ".ai-badger" / "instructions" / "csharp.instructions.md"
    assert shared.is_symlink(), "the union's instruction file must reach the member"

    result = _shared(root, "prune", "--target", str(collection), "--repo", "dotnet-app")

    _success(result)
    assert not shared.is_symlink(), "a pruned member keeps a private copy, not a link"
    assert shared.is_file()
    assert not (second / ".ai-badger" / "shared-scope.json").exists()
    assert (second / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip() == \
        "canonical-dotnet"
    members = json.loads((collection / ".ai-badger" / "shared-scope.json").read_text())["members"]
    assert members == ["python-app"]
    assert json.loads((collection / ".ai-badger" / "config.json").read_text())["stacks"] == ["python"]
    assert (first / ".ai-badger" / "shared-scope.json").is_file()
    assert json.loads((first / ".ai-badger" / "config.json").read_text())["stacks"] == ["python"]


def test_pruning_a_repository_that_is_not_a_member_is_refused(tmp_path, root):
    """Prune only ever removes an enrolled member."""
    collection = tmp_path / "chosen collection"
    _member(collection, "python-app", ["python"], "canonical-python")
    stranger = _member(collection, "dotnet-app", ["dotnet"], "canonical-dotnet")
    _test_write(stranger / "App.csproj", "<Project />\n")
    _success(_shared(root, "collect", "--target", str(collection), "--repo", "python-app"))

    result = _shared(root, "prune", "--target", str(collection), "--repo", "dotnet-app")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "not an enrolled member" in result.stderr
    assert json.loads((collection / ".ai-badger" / "shared-scope.json").read_text())["members"] == \
        ["python-app"]


def test_a_descriptor_with_an_unknown_field_is_refused(tmp_path, root):
    """The child's authored descriptor is a closed shape, not free-form JSON."""
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    _test_write(first / "pyproject.toml", "[project]\n")
    _success(_shared(root, "collect", "--target", str(collection), "--repo", "python-app"))
    descriptor_path = first / ".ai-badger" / "shared-scope.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["unexpected"] = True
    _write_json(descriptor_path, descriptor)

    result = _shared(root, "sync", "--target", str(first),
                     "--source", str(collection / ".ai-badger"))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "unexpected" in result.stderr


def test_removing_a_member_shrinks_the_union_and_keeps_the_child_recoverable(tmp_path, root):
    """A smaller membership must not strand the remaining child on a vanished parent file."""
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], "canonical-dotnet")
    _test_write(first / "pyproject.toml", "[project]\nname = 'python-app'\n")
    _test_write(second / "App.csproj", "<Project />\n")
    _success(_shared(root, "collect", "--target", str(collection),
                     "--repo", "python-app", "--repo", "dotnet-app"))
    shared = first / ".ai-badger" / "instructions" / "csharp.instructions.md"
    assert shared.is_symlink(), "the union's instruction file must reach the child"

    result = _shared(root, "collect", "--target", str(collection), "--repo", "python-app")

    _success(result)
    assert json.loads((collection / ".ai-badger" / "config.json").read_text())["stacks"] == ["python"]
    assert json.loads((first / ".ai-badger" / "config.json").read_text())["stacks"] == ["python"]
    assert not shared.is_symlink(), "a link to a vanished parent file must not survive"
    assert not shared.exists()
    links = json.loads((first / ".ai-badger" / "manifest.json").read_text())["sharedScope"]["links"]
    assert all("csharp" not in entry["path"] for entry in links)
    _success(_shared(root, "sync", "--target", str(first),
                     "--source", str(collection / ".ai-badger")))


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
