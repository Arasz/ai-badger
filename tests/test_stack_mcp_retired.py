"""A re-scaffold removes an MCP entry it wrote for a server the catalog has retired (ADR-0049).

Every case runs on a synthetic framework root in ``tmp_path`` whose catalog retires a server
named ``ghost``; the real catalog is never read here. The run is the scaffold's own MCP sequence
(``scaffold.py`` ``run``: ``.mcp.json``, the user proposal, ``.github/mcp.json``,
``.pi/mcp.json``). Seeds are written by hand per destination, not rendered by the code under test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import _test_write as _raw_write

pytestmark = pytest.mark.retired_prune

ARGS = ["--data", "${HOME}/.ghost"]
ENV = {"GHOST_QUIET": "1"}
GHOST = {"name": "ghost", "command": "ghost-mcp", "args": ARGS, "env": ENV, "declare": True}
GHOST_PY = {"name": "ghost", "command": "python3 -m ghost.server", "declare": True}
CURRENT = {"name": "current", "command": "current-mcp", "declare": True}
MINE = {"command": "mine-mcp", "args": ["--port", "9"]}
ALL_AGENTS = ["claude", "copilot", "pi"]

DESTS = [".mcp.json", ".github/mcp.json", ".pi/mcp.json"]
DEST_IDS = ["mcp", "github", "pi"]
# What each destination's writer adds beside the launch: the Copilot tools allowlist on the two
# shared files, pi's exposure default on its own.
DECORATION = {".mcp.json": {"tools": ["*"]}, ".github/mcp.json": {"tools": ["*"]},
              ".pi/mcp.json": {"exposure": "direct"}}


def _test_write(path: Path, text: str) -> None:
    """``conftest._test_write`` behind a parent ``mkdir``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _raw_write(path, text)


def _seed_of(launch: dict, dest: str) -> dict:
    """The entry *dest*'s writer records for *launch*, decorations included."""
    return dict(launch, **DECORATION[dest])


GHOST_LAUNCH = {"command": "ghost-mcp", "args": ARGS, "env": ENV}
GHOST_PY_LAUNCH = {"command": "python3", "args": ["-m", "ghost.server"]}
CURRENT_LAUNCH = {"command": "current-mcp"}


def _framework(tmp_path: Path, common_servers=(CURRENT,), common_retired=(GHOST,),
               other=None) -> Path:
    """A framework root holding only an index and the stack-mcp.json files the case needs."""
    root = tmp_path / "fw"
    _test_write(root / "index.json",
                json.dumps({"frameworkVersion": "0.1.0", "stacks": {}}))
    _test_write(root / "features" / "common" / "stack-mcp.json", json.dumps(
        {"servers": list(common_servers), "retired": list(common_retired)}, indent=2))
    if other is not None:
        _test_write(root / "features" / "other" / "stack-mcp.json", json.dumps(other, indent=2))
    return root


def _config(agents, stacks=("python",)) -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": list(stacks),
        "agents": list(agents),
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


@pytest.fixture(name="env")
def _env(monkeypatch, tmp_path):
    """A redirected HOME and the deterministic availability override; returns the home."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AI_BADGER_MCP_AVAILABILITY", "all")
    return home


def _scaffold_mcp(make_scaffolder, root: Path, agents, stacks=("python",)) -> list:
    """Run the scaffold's MCP sequence once and return the run's notes."""
    scaf = make_scaffolder(root=root, config=_config(agents, stacks))
    scaf.mcp.generate_mcp_json()
    project, user = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.propose_claude_mcp_user(user)
    scaf.mcp.generate_copilot_mcp_json(project)
    scaf.mcp.generate_pi_mcp_json()
    return list(scaf.notes)


def _write(target: Path, dest: str, section: dict, **top) -> None:
    _test_write(target / dest, json.dumps(dict(top, mcpServers=section), indent=2) + "\n")


def _section(target: Path, dest: str) -> dict:
    return json.loads((target / dest).read_text(encoding="utf-8"))["mcpServers"]


def _ghost_removals(notes) -> list:
    return [n for n in notes if "ghost" in n and "removed" in n]


# -- B1-B2: an exact copy of a retired launch is removed ---------------------------------------

@pytest.mark.parametrize("dest", DESTS, ids=DEST_IDS)
def test_a_retired_entry_is_removed(dest, tmp_path, env, make_scaffolder):
    """The entry equal to the retired render goes; the user's server and other keys stay."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest), "mine": dict(MINE)},
           inputs=[{"id": "token"}])

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    data = json.loads((target / dest).read_text(encoding="utf-8"))
    assert "ghost" not in data["mcpServers"], f"{dest} still holds the retired entry"
    assert data["mcpServers"]["mine"] == MINE
    assert data["inputs"] == [{"id": "token"}]
    assert data["mcpServers"]["current"] == _seed_of(CURRENT_LAUNCH, dest)


@pytest.mark.parametrize("dest,command", [
    (".mcp.json", "${HOME}/.local/bin/ghost-mcp"),
    (".pi/mcp.json", "~/.dotnet/tools/ghost-mcp"),
], ids=["mcp-HOME", "pi-tilde"])
def test_a_home_spelled_retired_entry_is_removed(dest, command, tmp_path, env, make_scaffolder):
    """A run that found the executable in a user tool dir recorded its home spelling."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _write(target, dest, {"ghost": _seed_of(dict(GHOST_LAUNCH, command=command), dest),
                          "mine": dict(MINE)})

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    section = _section(target, dest)
    assert "ghost" not in section, f"{dest} still holds the {command} spelling"
    assert section["mine"] == MINE


# -- B3-B5, B9: what the prune must leave alone -------------------------------------------------

@pytest.mark.parametrize("dest", DESTS, ids=DEST_IDS)
def test_a_hand_edited_retired_entry_is_kept(dest, tmp_path, env, make_scaffolder):
    """A changed launch field is the user's way to keep the server: the entry stays as written."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    edited = _seed_of(dict(GHOST_LAUNCH, args=["--data", "/srv/ghost"]), dest)
    _write(target, dest, {"ghost": edited})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    assert _section(target, dest)["ghost"] == edited
    assert _ghost_removals(notes) == []
    kept = [n for n in notes if "'ghost'" in n and n.startswith(f"{dest}:") and "kept" in n]
    assert len(kept) == 1, f"one kept note for {dest}, got {kept}"
    assert "retired" in kept[0] and "hand edit" in kept[0]
    assert "executable" not in kept[0], "the kept note reuses the unavailable wording"


@pytest.mark.parametrize("dest", DESTS, ids=DEST_IDS)
def test_other_servers_are_untouched(dest, tmp_path, env, make_scaffolder):
    """Beside a retired entry, a user's server and a current catalog server come out equal."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    current = _seed_of(CURRENT_LAUNCH, dest)
    _write(target, dest, {"mine": dict(MINE), "ghost": _seed_of(GHOST_LAUNCH, dest),
                          "current": current})

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    section = _section(target, dest)
    assert json.dumps(section["mine"]) == json.dumps(MINE)
    assert json.dumps(section["current"]) == json.dumps(current)


def test_a_name_still_declared_elsewhere_is_not_retired(tmp_path, env, make_scaffolder):
    """A name another active stack still declares, with the very launch retired, is current."""
    root = _framework(tmp_path, other={"servers": [dict(GHOST)]})
    target = make_scaffolder.target
    _write(target, ".mcp.json", {"ghost": _seed_of(GHOST_LAUNCH, ".mcp.json")})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS, stacks=["other"])

    assert _section(target, ".mcp.json")["ghost"] == _seed_of(GHOST_LAUNCH, ".mcp.json")
    assert _ghost_removals(notes) == []


def test_same_executable_other_args_is_kept(tmp_path, env, make_scaffolder):
    """Retired as `python3 -m ghost.server`; a user's `python3 -m mytool` under the name stays."""
    root = _framework(tmp_path, common_retired=[GHOST_PY])
    target = make_scaffolder.target
    mine = _seed_of({"command": "python3", "args": ["-m", "mytool"]}, ".mcp.json")
    _write(target, ".mcp.json", {"ghost": mine})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    assert _section(target, ".mcp.json")["ghost"] == mine
    assert _ghost_removals(notes) == []


# -- B6-B8: which retired declarations count ----------------------------------------------------

def test_a_retired_server_of_an_inactive_stack_is_removed(tmp_path, env, make_scaffolder):
    """The retired set is the whole catalog's, not only the configured stacks'."""
    root = _framework(tmp_path, common_retired=[], other={"servers": [], "retired": [GHOST]})
    target = make_scaffolder.target
    _write(target, ".mcp.json", {"ghost": _seed_of(GHOST_LAUNCH, ".mcp.json"),
                                 "mine": dict(MINE)})

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS, stacks=["python"])

    section = _section(target, ".mcp.json")
    assert "ghost" not in section, "a stack outside config.stacks retired it"
    assert section["mine"] == MINE


@pytest.mark.parametrize("launch", [GHOST_LAUNCH, GHOST_PY_LAUNCH], ids=["launch1", "launch2"])
def test_every_retired_launch_of_a_name_is_removed(launch, tmp_path, env, make_scaffolder):
    """A name retired with two launches: a consumer holding either one is cleaned."""
    root = _framework(tmp_path, common_retired=[GHOST, GHOST_PY])
    target = make_scaffolder.target
    _write(target, ".mcp.json", {"ghost": _seed_of(launch, ".mcp.json"), "mine": dict(MINE)})

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    section = _section(target, ".mcp.json")
    assert "ghost" not in section, f"launch {launch} survived"
    assert section["mine"] == MINE


@pytest.mark.parametrize("dest,decoration", [
    (".mcp.json", {"tools": ["ghost_query"]}),
    (".github/mcp.json", {"exposure": "direct"}),
    (".pi/mcp.json", {"enabled": False}),
], ids=DEST_IDS)
def test_a_decorated_retired_entry_is_removed(dest, decoration, tmp_path, env, make_scaffolder):
    """Identity is the launch (command, args, env, cwd); a decoration does not shield it."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _write(target, dest, {"ghost": dict(_seed_of(GHOST_LAUNCH, dest), **decoration)})

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    assert "ghost" not in _section(target, dest), f"{decoration} shielded the entry"


# -- B10: the retired render is silent ----------------------------------------------------------

def test_retired_render_writes_no_launch_notes(tmp_path, monkeypatch, make_scaffolder):
    """A tombstone is rendered only to compare: no 'fail to start' or override note for it."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AI_BADGER_MCP_AVAILABILITY", raising=False)
    ghost = dict(GHOST, agentOverrides={"pi": {"env": {"GHOST_QUIET": "0"}}})
    root = _framework(tmp_path, common_retired=[ghost])
    target = make_scaffolder.target
    for dest in DESTS:
        _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest)})

    notes = _scaffold_mcp(make_scaffolder, root, ["claude"])

    loud = [n for n in notes if "ghost" in n
            and ("fail to start" in n or "without agent overrides" in n)]
    assert loud == []


# -- B11-B13: a retired entry opens a file's gate -----------------------------------------------

def _deselected(dest, tmp_path, make_scaffolder):
    """Seed *dest* with the retired entry and a user's server; run with Claude alone."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest), "mine": dict(MINE)})
    _scaffold_mcp(make_scaffolder, root, ["claude"])
    return _section(target, dest)


def test_a_deselected_copilot_file_is_still_cleaned(tmp_path, env, make_scaffolder):
    """Copilot is not configured: the file it would read is cleaned, and nothing is added."""
    section = _deselected(".github/mcp.json", tmp_path, make_scaffolder)
    assert "ghost" not in section, ".github/mcp.json kept the retired entry"
    assert section["mine"] == MINE
    assert "current" not in section


def test_a_deselected_pi_file_is_still_cleaned(tmp_path, env, make_scaffolder):
    """pi is not configured: .pi/mcp.json is cleaned, and nothing is added."""
    section = _deselected(".pi/mcp.json", tmp_path, make_scaffolder)
    assert "ghost" not in section, ".pi/mcp.json kept the retired entry"
    assert section["mine"] == MINE
    assert "current" not in section


def test_a_file_with_no_declared_server_is_cleaned(tmp_path, env, make_scaffolder):
    """No server declared and none declined: the retired entry alone opens the file."""
    root = _framework(tmp_path, common_servers=[])
    target = make_scaffolder.target
    _write(target, ".mcp.json", {"ghost": _seed_of(GHOST_LAUNCH, ".mcp.json"),
                                 "mine": dict(MINE)})

    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    section = _section(target, ".mcp.json")
    assert "ghost" not in section, "no declared server, so the file was never opened"
    assert section == {"mine": MINE}


# -- B14-B16: notes -----------------------------------------------------------------------------

@pytest.mark.parametrize("dest", DESTS, ids=DEST_IDS)
def test_the_removal_note_says_how_to_keep_the_entry(dest, tmp_path, env, make_scaffolder):
    """The note names the server and file, and says a changed launch field keeps the entry."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest)})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    said = [n for n in notes if "ghost" in n and dest in n and "retired" in n]
    assert len(said) == 1, f"one removal note for {dest}, got {said}"
    text = said[0].lower()
    assert "exact" in text
    for field in ("command", "args", "env", "cwd"):
        assert field in text, f"the keep-it rule does not name {field}"


def test_hermes_note_when_a_retired_entry_is_removed(tmp_path, env, make_scaffolder):
    """Every file removes the entry: still one note names mcp_servers.ghost; ~/.hermes untouched."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    for dest in DESTS:
        _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest)})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS + ["hermes"])

    assert [dest for dest in DESTS if "ghost" in _section(target, dest)] == []

    hermes = [n for n in notes if "mcp_servers.ghost" in n]
    assert len(hermes) == 1, f"one Hermes note, got {hermes}"
    assert "~/.hermes/config.yaml" in hermes[0]
    assert not (env / ".hermes").exists()


@pytest.mark.parametrize("agents,seeded", [
    (["claude"], True),
    (["claude", "hermes"], False),
], ids=["no-hermes", "nothing-removed"])
def test_no_hermes_note_without_hermes_or_without_a_removal(agents, seeded, tmp_path, env,
                                                            make_scaffolder):
    """The Hermes note needs both: hermes configured and an entry removed."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    section = {"mine": dict(MINE)}
    if seeded:
        section["ghost"] = _seed_of(GHOST_LAUNCH, ".mcp.json")
    _write(target, ".mcp.json", section)

    notes = _scaffold_mcp(make_scaffolder, root, agents)

    assert [n for n in notes if "mcp_servers.ghost" in n or ".hermes" in n] == []


# -- B17-B19: preservation pins -----------------------------------------------------------------

def _snapshot(target: Path) -> dict:
    return {path.relative_to(target).as_posix(): path.read_bytes()
            for path in sorted(target.rglob("*")) if path.is_file()}


def test_a_second_run_changes_nothing(tmp_path, env, make_scaffolder):
    """Once cleaned, a refresh writes no byte, no backup and no ghost note."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    for dest in DESTS:
        _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest), "mine": dict(MINE)})
    _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)
    before = _snapshot(target)

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    after = _snapshot(target)
    assert sorted(after) == sorted(before), "the second run added or removed a file"
    assert [rel for rel in DESTS if after[rel] != before[rel]] == []
    assert [n for n in notes if "ghost" in n] == []


def test_an_unreadable_file_is_left_alone(tmp_path, env, make_scaffolder):
    """.mcp.json that is not JSON is refused whole, whatever it mentions."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    broken = '{"mcpServers": {"ghost": {"command": "ghost-mcp",\n'
    _test_write(target / ".mcp.json", broken)

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    assert (target / ".mcp.json").read_text(encoding="utf-8") == broken
    assert [n for n in notes if "refused to overwrite" in n and ".mcp.json" in n]


def test_retired_servers_are_never_declared(tmp_path, env, make_scaffolder):
    """A retired declaration never reaches the declared set."""
    root = _framework(tmp_path)
    scaf = make_scaffolder(root=root, config=_config(ALL_AGENTS))

    catalog = [srv["name"] for srv in scaf.mcp.collect_catalog_mcp_servers()]
    project = scaf.mcp.project_server_names()

    assert "current" in catalog and "current" in project
    assert "ghost" not in catalog and "ghost" not in project


# -- review fixes: a broken catalog or target never prunes on partial data -----------------------

@pytest.mark.parametrize("text", ['{"servers": [', "[]"], ids=["not-json", "not-object"])
def test_an_unreadable_catalog_file_skips_the_prune(text, tmp_path, env, make_scaffolder):
    """One unreadable stack-mcp.json: nothing is pruned, and one note names the file."""
    root = _framework(tmp_path)
    _test_write(root / "features" / "other" / "stack-mcp.json", text)
    target = make_scaffolder.target
    seeded = _seed_of(GHOST_LAUNCH, ".mcp.json")
    _write(target, ".mcp.json", {"ghost": seeded})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    assert _section(target, ".mcp.json")["ghost"] == seeded, "pruned on partial catalog data"
    said = [n for n in notes if "features/other/stack-mcp.json" in n
            and "unreadable — retired prune skipped" in n]
    assert said, "no note names the unreadable catalog file"


@pytest.mark.parametrize("item", ["ghost", {"command": "ghost-mcp"}], ids=["not-dict", "no-name"])
def test_a_malformed_retired_item_is_skipped_with_a_note(item, tmp_path, env, make_scaffolder):
    """A retired item that is not a named object is skipped; the well-formed one still prunes."""
    root = _framework(tmp_path, other={"servers": [], "retired": [item]})
    target = make_scaffolder.target
    _write(target, ".mcp.json", {"ghost": _seed_of(GHOST_LAUNCH, ".mcp.json"),
                                 "mine": dict(MINE)})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    section = _section(target, ".mcp.json")
    assert "ghost" not in section and section["mine"] == MINE
    said = [n for n in notes if "features/other/stack-mcp.json" in n and "retired" in n]
    assert said, "no note names the file with the malformed retired item"


@pytest.mark.parametrize("other", [
    "[]", json.dumps({"servers": [], "retired": ["ghost"]}),
], ids=["unreadable", "malformed"])
def test_the_retired_set_is_read_once_per_run(other, tmp_path, env, make_scaffolder):
    """The retired set is collected once per run, so a catalog note never repeats."""
    root = _framework(tmp_path)
    _test_write(root / "features" / "other" / "stack-mcp.json", other)
    target = make_scaffolder.target
    for dest in DESTS:
        _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest)})

    notes = _scaffold_mcp(make_scaffolder, root, ALL_AGENTS)

    said = [n for n in notes if "features/other/stack-mcp.json" in n]
    assert len(said) == 1, f"the catalog note repeated: {said}"


@pytest.mark.parametrize("text", ['{"mcpServers": {"ghost": {', '{"mcpServers": []}'],
                         ids=["not-json", "not-mapping"])
def test_an_unreadable_unread_file_is_refused_with_a_note(text, tmp_path, env, make_scaffolder):
    """.github/mcp.json no agent reads, and unusable: left as found, and the refusal is named."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _test_write(target / ".github" / "mcp.json", text)

    notes = _scaffold_mcp(make_scaffolder, root, ["claude"])

    assert (target / ".github" / "mcp.json").read_text(encoding="utf-8") == text
    assert [n for n in notes if "refused to overwrite" in n and ".github/mcp.json" in n]


@pytest.mark.parametrize("dest", [".github/mcp.json", ".pi/mcp.json"], ids=["github", "pi"])
def test_a_prune_only_write_is_recorded(dest, tmp_path, env, make_scaffolder):
    """A file cleaned for an unconfigured agent is recorded for the manifest like any write."""
    root = _framework(tmp_path)
    target = make_scaffolder.target
    _write(target, dest, {"ghost": _seed_of(GHOST_LAUNCH, dest), "mine": dict(MINE)})
    scaf = make_scaffolder(root=root, config=_config(["claude"]))
    scaf.mcp.generate_mcp_json()
    project, _ = scaf.mcp.split_servers_by_scope(scaf.mcp.declared_servers())
    scaf.mcp.generate_copilot_mcp_json(project)
    scaf.mcp.generate_pi_mcp_json()

    assert "ghost" not in _section(target, dest)
    assert [r["path"] for r in scaf.generated_config.all_records([])
            if r["path"] == dest] == [dest]
