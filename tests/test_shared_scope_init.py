"""Parent-side collection initialization through its public command line."""
from __future__ import annotations

import json
import shutil
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


def _repo(path: Path) -> Path:
    """A git checkout, the only thing that makes a directory a candidate child."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True, text=True)
    return path


def _child(collection: Path, name: str) -> Path:
    return _repo(collection / name)


def _identity(path: Path, value: str) -> None:
    """Give a repository the identity it already has; the bytes must survive untouched."""
    (path / ".ai-badger").mkdir(parents=True, exist_ok=True)
    _test_write(path / ".ai-badger" / "project-id", value)


def _shared(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / SHARED_SCRIPT), *args,
                           "--root", str(root)], capture_output=True, text=True, timeout=120)


def _success(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _descriptor(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _config_of(path: Path) -> dict:
    return _descriptor(path / ".ai-badger" / "config.json")


def _snapshot(path: Path) -> dict:
    """The bytes of every file under a tree, so a second run can be compared with the first."""
    result: dict[str, bytes] = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            result[str(item.relative_to(path))] = b"->" + str(item.readlink()).encode()
        elif item.is_file():
            result[str(item.relative_to(path))] = item.read_bytes()
    return result


def test_init_enrolls_every_discovered_child_with_the_union_of_stacks(tmp_path, root):
    """One command over a directory of repositories: the parent carries the union, every
    child is enrolled, and every child is linked to the parent."""
    collection = tmp_path / "source"
    python_app = _child(collection, "python-app")
    dotnet_app = _child(collection, "dotnet-app")
    _test_write(python_app / "pyproject.toml", "[project]\n")
    _test_write(dotnet_app / "App.csproj", "<Project />\n")
    _identity(python_app, "canonical-python\n")
    _identity(dotnet_app, "canonical-dotnet\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    parent = _config_of(collection)
    assert set(parent["stacks"]) == {"python", "dotnet"}
    assert len(parent["stacks"]) == 2
    descriptor = _descriptor(collection / ".ai-badger" / "shared-scope.json")
    assert descriptor["mode"] == "collection"
    assert descriptor["members"] == ["dotnet-app", "python-app"]
    assert descriptor["memberStacks"] == {"dotnet-app": ["dotnet"], "python-app": ["python"]}
    parent_id = (collection / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip()
    assert parent_id
    for name in ("python-app", "dotnet-app"):
        child = collection / name
        assert set(_config_of(child)["stacks"]) == {"python", "dotnet"}
        child_descriptor = _descriptor(child / ".ai-badger" / "shared-scope.json")
        assert child_descriptor["mode"] == "inherit"
        assert Path(child_descriptor["source"]) == Path("..", ".ai-badger")
        assert child_descriptor["parentId"] == parent_id
        assert child_descriptor["localStacks"]


def test_the_parent_and_the_children_link_the_shared_instruction_files(tmp_path, root):
    """The union's instruction files live in the parent and reach the child as links."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    _identity(app, "canonical-python\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    shared = collection / "python-app" / ".ai-badger" / "instructions" / "python.instructions.md"
    assert shared.is_symlink(), "an identical instruction file is shared, not copied"
    assert shared.resolve() == (collection / ".ai-badger" / "instructions"
                                / "python.instructions.md").resolve()


def test_init_converts_an_already_scaffolded_child(tmp_path, root):
    """A child that already has ai-badger becomes a member: its own stacks stay its own,
    its own settings become its overrides, and its own identity survives."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _write_json(app / ".ai-badger" / "config.json", _config(stacks=["python"]))
    _identity(app, "canonical-python\n")
    _test_write(app / "pyproject.toml", "[project]\n")
    other = _child(collection, "dotnet-app")
    _test_write(other / "App.csproj", "<Project />\n")
    _identity(other, "canonical-dotnet\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    descriptor = _descriptor(app / ".ai-badger" / "shared-scope.json")
    assert descriptor["localStacks"] == ["python"], "the child's own stacks stay its own"
    assert descriptor["overrides"]["project"]["name"] == "probe", \
        "the child's own settings are its overrides, not the parent's"
    assert (app / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip() == \
        "canonical-python"
    assert set(_config_of(app)["stacks"]) == {"python", "dotnet"}, \
        "the converted child carries the union"
    assert _config_of(app)["project"]["name"] == "probe"


def test_init_keeps_every_existing_identity_byte_for_byte(tmp_path, root):
    """An identity the child already has is never rewritten."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    _identity(app, "canonical-python\n")
    _identity(collection, "canonical-collection\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    assert (app / ".ai-badger" / "project-id").read_bytes() == b"canonical-python\n"
    assert (collection / ".ai-badger" / "project-id").read_bytes() == b"canonical-collection\n"


def test_a_missing_identity_is_resolved_through_the_canonical_lookup(tmp_path, root,
                                                                    raccoon_cli_fake,
                                                                    monkeypatch):
    """A child with no identity of its own gets the bank's id for its name."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 0, "stdout": "11111111-2222-3333-4444-555555555555\n",
                                 "stderr": ""})
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    assert (app / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip() == \
        "11111111-2222-3333-4444-555555555555"


def test_the_bank_is_not_written_to_without_the_register_flag(tmp_path, root, raccoon_cli_fake,
                                                               monkeypatch):
    """The default enrolment never registers an identity with the operator's bank."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 18, "stdout": "", "stderr": ""},
                            register={"exit": 0, "stdout": "registered\n", "stderr": ""})
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    assert (app / ".ai-badger" / "project-id").read_text(encoding="utf-8").strip()
    assert not [call for call in raccoon_cli_fake.calls() if "register" in call["argv"]], \
        "the default must not write to the operator's bank"


def test_an_identity_the_lookup_cannot_be_trusted_stops_the_run_before_any_write(
        tmp_path, root, raccoon_cli_fake, monkeypatch):
    """An answer the canonical lookup cannot be trusted on refuses the whole enrolment."""
    monkeypatch.setenv("AI_BADGER_RACCOON_REGISTER", "1")
    raccoon_cli_fake.script(get={"exit": 19, "stdout": "",
                                 "stderr": "several projects are named 'python-app'\n"})
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    before = _snapshot(app)

    result = _shared(root, "init", "--target", str(collection))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "identity" in result.stderr
    assert not (collection / ".ai-badger").exists(), "a refused run writes nothing"
    assert _snapshot(app) == before


def test_a_child_enrolled_in_another_collection_is_refused(tmp_path, root):
    """A child that carries another collection's descriptor is refused, not re-enrolled."""
    first = tmp_path / "first collection"
    second = tmp_path / "second collection"
    second.mkdir()
    child = _child(first, "python-app")
    _test_write(child / "pyproject.toml", "[project]\n")
    _identity(child, "canonical-python\n")
    _success(_shared(root, "init", "--target", str(first)))
    moved = second / "python-app"
    shutil.move(str(child), str(moved))

    result = _shared(root, "init", "--target", str(second))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "already enrolled" in result.stderr
    assert not (second / ".ai-badger").exists(), "the second collection writes nothing"


def test_the_parent_keeps_its_own_identity_of_project(tmp_path, root):
    """A member's own name and settings never leak into the parent."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    _identity(app, "canonical-python\n")

    result = _shared(root, "init", "--target", str(collection))

    _success(result)
    assert _config_of(collection)["project"]["name"] == "source"
    assert _config_of(app)["project"]["name"] == "python-app"


def test_a_member_whose_own_settings_cannot_be_rendered_stops_the_run_before_any_write(
        tmp_path, root):
    """A member that carries an unusable setting refuses the run before the first write."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    _identity(app, "canonical-python\n")
    broken = _config(stacks=["python"])
    broken["skillScope"] = "nonsense"
    _write_json(app / ".ai-badger" / "config.json", broken)
    before = _snapshot(app)

    result = _shared(root, "init", "--target", str(collection))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "invalid shared config" in result.stderr
    assert not (collection / ".ai-badger").exists(), "a refused run writes nothing"
    assert _snapshot(app) == before


def test_a_dry_run_reports_the_plan_and_writes_nothing(tmp_path, root):
    """A dry run shows what the enrolment would do, and leaves the directory alone."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    _identity(app, "canonical-python\n")
    before = _snapshot(app)

    result = _shared(root, "init", "--target", str(collection), "--dry-run")

    _success(result)
    assert "python-app:python" in result.stdout
    assert "union python" in result.stdout
    assert not (collection / ".ai-badger").exists()
    assert _snapshot(app) == before


def test_discover_reports_the_index_and_writes_nothing(tmp_path, root):
    """The read-only report names the direct children, their stacks and the union."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    nested = _repo(collection / "group" / "nested-app")
    _test_write(nested / "App.csproj", "<Project />\n")
    (collection / "notes").mkdir()

    result = _shared(root, "discover", "--target", str(collection))

    _success(result)
    assert "member python-app:python" in result.stdout
    assert "union python" in result.stdout
    assert "nested-app" not in result.stdout, "discovery is one level deep"
    assert "notes" not in result.stdout
    assert not (collection / ".ai-badger").exists()
    assert not (app / ".ai-badger").exists()


def test_a_target_that_is_itself_a_member_is_refused(tmp_path, root):
    """A directory that is a member of another collection cannot become a collection."""
    first = tmp_path / "first collection"
    second = tmp_path / "second collection"
    second.mkdir()
    child = _child(first, "python-app")
    _test_write(child / "pyproject.toml", "[project]\n")
    _identity(child, "canonical-python\n")
    _success(_shared(root, "init", "--target", str(first)))
    moved = second / "python-app"
    shutil.move(str(child), str(moved))
    _repo(moved / "inner")

    result = _shared(root, "init", "--target", str(moved))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "shared-scope child" in result.stderr


def test_a_directory_without_repositories_is_refused(tmp_path, root):
    """There is nothing to enrol, and the refusal names the directory it looked in."""
    collection = tmp_path / "source"
    collection.mkdir()
    (collection / "notes").mkdir()

    result = _shared(root, "init", "--target", str(collection))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "no repository" in result.stderr
    assert not (collection / ".ai-badger").exists()


def test_initializing_twice_changes_nothing(tmp_path, root):
    """A second run over the same collection is deterministic: it writes the same bytes."""
    collection = tmp_path / "source"
    app = _child(collection, "python-app")
    _test_write(app / "pyproject.toml", "[project]\n")
    _identity(app, "canonical-python\n")
    _success(_shared(root, "init", "--target", str(collection)))
    parent_after = _snapshot(collection / ".ai-badger")
    child_after = _snapshot(app / ".ai-badger")

    _success(_shared(root, "init", "--target", str(collection)))

    assert _snapshot(collection / ".ai-badger") == parent_after
    assert _snapshot(app / ".ai-badger") == child_after
