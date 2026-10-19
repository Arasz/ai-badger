"""Shared parent collection behavior through its public command line."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_a_child_without_its_own_identity_is_refused(tmp_path, root, raccoon_cli_fake, monkeypatch):
    """An identity the canonical lookup cannot resolve stops the enrollment before any write."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 19, "stdout": "",
                                 "stderr": "several projects are named 'dotnet-app'\n"})
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
    assert not (collection / ".ai-badger").exists(), "a refused enrollment writes nothing"


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


def test_an_unknown_name_is_minted_locally_and_not_registered(tmp_path, root, raccoon_cli_fake,
                                                               monkeypatch):
    """A name the bank does not know gets a local id; the bank is not written to by default."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 18, "stdout": "", "stderr": ""},
                            register={"exit": 0, "stdout": "registered\n", "stderr": ""})
    collection = tmp_path / "chosen collection"
    _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], None)
    _test_write(second / "App.csproj", "<Project />\n")

    result = _shared(root, "collect", "--target", str(collection),
                     "--repo", "python-app", "--repo", "dotnet-app")

    assert result.returncode == 0, result.stdout + result.stderr
    minted = (second / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip()
    assert minted and minted != "canonical-python"
    assert not [call for call in raccoon_cli_fake.calls() if "register" in call["argv"]], \
        "the default must not write to the operator's bank"


def test_registering_is_opt_in(tmp_path, root, raccoon_cli_fake, monkeypatch):
    """`--register` is the only way the shared scope writes to the bank."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 18, "stdout": "", "stderr": ""},
                            register={"exit": 0, "stdout": "registered\n", "stderr": ""})
    collection = tmp_path / "chosen collection"
    _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], None)
    _test_write(second / "App.csproj", "<Project />\n")

    result = _shared(root, "collect", "--target", str(collection), "--register",
                     "--repo", "python-app", "--repo", "dotnet-app")

    assert result.returncode == 0, result.stdout + result.stderr
    registered = [call for call in raccoon_cli_fake.calls() if "register" in call["argv"]]
    assert registered, "--register must reach the bank"
    assert (second / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip() in \
        registered[0]["argv"]


def test_the_mode_vocabulary_is_defined_once(tmp_path, root):
    """The modes are one vocabulary, written in three places that must agree."""
    import json as _json
    import re as _re

    lib = (root / "engine" / "badger_lib.py").read_text(encoding="utf-8")
    found = _re.search(r'profile\.get\("mode"\) not in \{([^}]*)\}', lib)
    assert found, "the refusal must name the modes it knows"
    refusal_modes = set(_re.findall(r'"([^"]+)"', found.group(1)))
    descriptor = _json.loads((root / "schemas" / "shared-scope.schema.json").read_text())
    manifest = _json.loads((root / "schemas" / "manifest.schema.json").read_text())
    descriptor_modes = set(descriptor["oneOf"][1]["properties"]["mode"]["enum"])
    manifest_modes = set(manifest["properties"]["sharedScope"]["properties"]["mode"]["enum"])

    assert refusal_modes == descriptor_modes == manifest_modes, \
        f"the mode vocabulary drifted: {refusal_modes} / {descriptor_modes} / {manifest_modes}"


def test_a_child_already_enrolled_in_another_collection_is_refused(tmp_path, root):
    """A child that arrives with another collection's descriptor is refused, not re-enrolled."""
    first = tmp_path / "first collection"
    second = tmp_path / "second collection"
    second.mkdir()
    child = _member(first, "python-app", ["python"], "canonical-python")
    _test_write(child / "pyproject.toml", "[project]\n")
    _success(_shared(root, "collect", "--target", str(first), "--repo", "python-app"))
    moved = second / "python-app"
    shutil.move(str(child), str(moved))

    result = _shared(root, "collect", "--target", str(second), "--repo", "python-app")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "already enrolled" in result.stderr
    assert not (second / ".ai-badger").exists(), "the second collection writes nothing"


def test_pruning_the_last_member_is_refused(tmp_path, root):
    """A collection keeps at least one member; the last one cannot be pruned."""
    collection = tmp_path / "chosen collection"
    only = _member(collection, "python-app", ["python"], "canonical-python")
    _test_write(only / "pyproject.toml", "[project]\n")
    _success(_shared(root, "collect", "--target", str(collection), "--repo", "python-app"))

    result = _shared(root, "prune", "--target", str(collection), "--repo", "python-app")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "last member" in result.stderr
    assert (only / ".ai-badger" / "shared-scope.json").is_file(), "the member stays enrolled"
    assert json.loads((collection / ".ai-badger" / "shared-scope.json").read_text())["members"] == \
        ["python-app"]


def test_only_identical_files_are_linked(tmp_path, root):
    """A parent file that is not the generated one is never linked into a child."""
    collection = tmp_path / "chosen collection"
    child = _member(collection, "python-app", ["python"], "canonical-python")
    _test_write(child / "pyproject.toml", "[project]\n")
    _success(_shared(root, "collect", "--target", str(collection), "--repo", "python-app"))
    parent_file = collection / ".ai-badger" / "instructions" / "python.instructions.md"
    _test_write(parent_file, "the collection's own instructions\n")

    result = _shared(root, "sync", "--target", str(child),
                     "--source", str(collection / ".ai-badger"))

    _success(result)
    own = child / ".ai-badger" / "instructions" / "python.instructions.md"
    assert not own.is_symlink(), "a file that is not identical must not be linked"
    assert own.read_text(encoding="utf-8") != "the collection's own instructions\n"


def test_the_ownership_ledger_records_no_machine_specific_paths(tmp_path, root):
    """The manifest is a committed file; it must not carry this machine's paths."""
    collection = tmp_path / "chosen collection"
    child = _member(collection, "python-app", ["python"], "canonical-python")
    _test_write(child / "pyproject.toml", "[project]\n")
    _success(_shared(root, "collect", "--target", str(collection), "--repo", "python-app"))
    manifest = json.loads((child / ".ai-badger" / "manifest.json").read_text())

    shared = manifest["sharedScope"]
    assert not Path(shared["source"]).is_absolute(), shared["source"]
    for entry in shared["links"]:
        assert not Path(entry["source"]).is_absolute(), entry["source"]
        assert not Path(entry["target"]).is_absolute(), entry["target"]


def test_collecting_and_syncing_twice_changes_nothing(tmp_path, root):
    """Repeated collect and repeated sync are each deterministic: the second run writes nothing."""
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    second = _member(collection, "dotnet-app", ["dotnet"], "canonical-dotnet")
    _test_write(first / "pyproject.toml", "[project]\n")
    _test_write(second / "App.csproj", "<Project />\n")
    args = ["--target", str(collection), "--repo", "python-app", "--repo", "dotnet-app"]
    _success(_shared(root, "collect", *args))
    source = collection / ".ai-badger"
    parent_after_collect = _snapshot(source)
    child_after_collect = _snapshot(first / ".ai-badger")
    sibling_after_collect = _snapshot(second / ".ai-badger")

    _success(_shared(root, "collect", *args))

    assert _snapshot(source) == parent_after_collect
    assert _snapshot(first / ".ai-badger") == child_after_collect
    assert _snapshot(second / ".ai-badger") == sibling_after_collect

    _success(_shared(root, "sync", "--target", str(first), "--source", str(source)))
    synced_child = _snapshot(first / ".ai-badger")
    synced_parent = _snapshot(source)
    _success(_shared(root, "sync", "--target", str(first), "--source", str(source)))

    assert _snapshot(first / ".ai-badger") == synced_child
    assert _snapshot(source) == synced_parent
    assert _snapshot(second / ".ai-badger") == sibling_after_collect


@pytest.mark.parametrize("case, expected", [
    ("escape", "must be relative to collection"),
    ("duplicate", "duplicate or overlapping"),
    ("not-a-repository", "not a repository root"),
    ("symlinked-scope", "must be a real directory"),
])
def test_unsafe_membership_is_refused_before_any_write(tmp_path, root, case, expected):
    """A member that escapes, overlaps, is not a repository, or borrows a scope is refused."""
    collection = tmp_path / "chosen collection"
    first = _member(collection, "python-app", ["python"], "canonical-python")
    _test_write(first / "pyproject.toml", "[project]\n")
    outside = tmp_path / "outside-app"
    outside.mkdir()
    subprocess.run(["git", "init", "-q", str(outside)], check=True, capture_output=True, text=True)
    _write_json(outside / ".ai-badger" / "config.json", _config(stacks=["python"]))
    _test_write(outside / ".ai-badger" / "project-id", "canonical-outside\n")

    if case == "escape":
        members = ["../outside-app"]
    elif case == "duplicate":
        members = ["python-app", "python-app"]
    elif case == "not-a-repository":
        plain = collection / "plain"
        plain.mkdir()
        members = ["plain"]
    else:
        linked = collection / "linked-app"
        linked.mkdir()
        subprocess.run(["git", "init", "-q", str(linked)], check=True, capture_output=True, text=True)
        (linked / ".ai-badger").symlink_to(first / ".ai-badger")
        members = ["linked-app"]

    result = _shared(root, "collect", "--target", str(collection), *sum(
        [["--repo", member] for member in members], []))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "shared scope refused" in result.stderr
    assert expected in result.stderr, "the refusal must name the reason, not fail downstream"
    assert not (collection / ".ai-badger" / "shared-scope.json").exists()
    assert json.loads((first / ".ai-badger" / "config.json").read_text())["stacks"] == ["python"]


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
    assert "sharedScope" not in json.loads(
        (second / ".ai-badger" / "manifest.json").read_text())

    refresh = subprocess.run([
        sys.executable,
        str(root / "features/common/skills/den-refresh/scripts/refresh.py"),
        "--root", str(root), "--target", str(second)], capture_output=True,
        text=True, timeout=120)

    assert refresh.returncode == 0, refresh.stdout + refresh.stderr
    assert (second / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip() == \
        "canonical-dotnet"


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
