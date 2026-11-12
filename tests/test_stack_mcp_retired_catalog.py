"""Catalog tombstones for retired MCP servers (ADR-0049): the `retired` array in stack-mcp.json.

Rows A1-A6 of the retired-prune test design. The schema accepts `retired`; the real catalog holds
one tombstone per launch that a deleted server ever shipped; a history comparator proves that
claim and fails loudly on a shallow clone. A4 and A5 run the comparator on a synthetic repository
so that it is seen to fail, not only to pass.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.retired_prune

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "stack-mcp.schema.json"
CATALOG_GLOB = "features/*/stack-mcp.json"
GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                    "GIT_PREFIX", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")


def _git_env() -> dict:
    """The environment minus every variable that pins git to another repository."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_ENV}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env=_git_env(), check=check)


def _launch(declaration: dict) -> tuple:
    """The launch of a declaration: command, args and env. Scope and availability are not launch."""
    return (declaration["command"], tuple(declaration.get("args", ())),
            tuple(sorted(declaration.get("env", {}).items())))


def _servers_at(repo: Path, sha: str, path: str) -> dict:
    """name -> launch of the `servers` array at *sha*; empty when the file does not exist there."""
    shown = _git(repo, "show", f"{sha}:{path}", check=False)
    if shown.returncode != 0:
        return {}
    return {s["name"]: _launch(s) for s in json.loads(shown.stdout).get("servers", [])
            if "command" in s}


def deleted_launches(repo: Path, path: str) -> dict:
    """name -> every distinct launch it had in `servers`, for names that a commit deleted from it.

    A launch change or a scope change keeps the name in `servers`, so it is not a deletion.
    """
    shas = _git(repo, "log", "--reverse", "--format=%H", "--", path).stdout.split()
    ever: dict = {}
    previous: dict = {}
    deleted: set = set()
    for sha in shas:
        current = _servers_at(repo, sha, path)
        for name, launch in current.items():
            if launch not in ever.setdefault(name, []):
                ever[name].append(launch)
        deleted |= set(previous) - set(current)
        previous = current
    return {name: ever[name] for name in sorted(deleted) if name not in previous}


def history_paths(repo: Path) -> list:
    """Every catalog stack-mcp.json path that ever existed in the history of *repo*."""
    out = _git(repo, "log", "--name-only", "--format=", "--", CATALOG_GLOB).stdout
    return sorted({line for line in out.splitlines() if line})


def untombstoned_launches(repo: Path) -> list:
    """(path, name, launch) for each deleted launch with no equal item in that file's `retired`.

    Fails the test on a shallow clone: a shortened history hides deletions, so a pass proves nothing.
    """
    if _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        pytest.fail("shallow clone: the tombstone history check needs a full clone (fetch-depth: 0)")
    missing = []
    for path in history_paths(repo):
        file = repo / path
        retired = json.loads(file.read_text(encoding="utf-8")).get("retired", []) if file.exists() else []
        have = {_launch(item) for item in retired}
        for name, launches in deleted_launches(repo, path).items():
            missing += [(path, name, launch) for launch in launches if launch not in have]
    return missing


def _write_catalog(repo: Path, servers: list) -> None:
    target = repo / "features" / "common" / "stack-mcp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"servers": servers}), encoding="utf-8")


@pytest.fixture(name="ghost_repo")
def _ghost_repo(tmp_path: Path) -> Path:
    """Four commits: add `ghost`, change its launch, change its scope, delete it. `stay` never leaves."""
    repo = tmp_path / "ghost-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    stay = {"name": "stay", "command": "stay serve", "declare": True}
    steps = [
        [stay, {"name": "ghost", "command": "ghost serve", "declare": True}],
        [stay, {"name": "ghost", "command": "ghost serve --v2", "declare": True}],
        [stay, {"name": "ghost", "command": "ghost serve --v2", "declare": True, "scope": "user"}],
        [stay],
    ]
    for number, servers in enumerate(steps, start=1):
        _write_catalog(repo, servers)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"step {number}")
    return repo


def test_schema_accepts_retired_declarations():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    assert "retired" in props, "stack-mcp.schema.json has no `retired` array"
    assert props["retired"]["items"] == props["servers"]["items"], "both arrays share one item definition"
    assert "$ref" in props["servers"]["items"], "the shared item lives in $defs"
    validator = Draft202012Validator(schema)
    real = json.loads((ROOT / "features" / "common" / "stack-mcp.json").read_text(encoding="utf-8"))
    assert not list(validator.iter_errors(real)), "the real catalog file validates"
    tombstone = {"name": "ghost", "command": "ghost serve", "declare": True}
    assert not list(validator.iter_errors({"servers": [], "retired": [tombstone]}))
    assert list(validator.iter_errors({"servers": [], "retired": [{"command": "ghost serve"}]})), \
        "a retired item with no name is rejected"


def test_no_name_is_both_declared_and_retired():
    files = sorted(ROOT.glob(CATALOG_GLOB))
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    declared = {s["name"] for d in docs for s in d.get("servers", [])}
    retired = {s["name"] for d in docs for s in d.get("retired", [])}
    assert any(d.get("servers") for d in docs), "survivor check: at least one file declares servers"
    assert not declared & retired, f"declared and retired: {sorted(declared & retired)}"


def test_every_launch_deleted_from_servers_is_tombstoned():
    missing = untombstoned_launches(ROOT)
    assert not missing, f"launches deleted from `servers` with no `retired` item: {missing}"


def test_history_comparator_on_a_synthetic_repo(ghost_repo):
    found = deleted_launches(ghost_repo, "features/common/stack-mcp.json")
    assert set(found) == {"ghost"}, "only the deleted name is reported; `stay` and the scope move are not"
    assert found["ghost"] == [("ghost serve", (), ()), ("ghost serve --v2", (), ())]
    assert len(untombstoned_launches(ghost_repo)) == 2, "neither launch is tombstoned in the synthetic repo"


def test_history_check_fails_on_a_shallow_clone(ghost_repo, tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{ghost_repo}", str(clone)],
                   check=True, capture_output=True, env=_git_env())
    assert _git(clone, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    with pytest.raises(pytest.fail.Exception, match="shallow"):
        untombstoned_launches(clone)


def test_four_semantica_launches_are_retired():
    doc = json.loads((ROOT / "features" / "common" / "stack-mcp.json").read_text(encoding="utf-8"))
    assert "semantica" not in {s["name"] for s in doc["servers"]}, "semantica is no longer declared"
    retired = doc.get("retired", [])
    assert {s["name"] for s in retired} <= {"semantica"}, "only semantica is retired in this change"
    expected = {
        ("python3 -m semantica.mcp_server", (), ()),
        ("semantica mcp start", (), ()),
        ("semantica-mcp", (), ()),
        ("semantica-mcp", (), (("SEMANTICA_DISABLE_PROGRESS", "1"),)),
    }
    launches = [_launch(s) for s in retired]
    assert len(launches) == len(set(launches)) == 4, f"four distinct launches, got {launches}"
    assert set(launches) == expected
