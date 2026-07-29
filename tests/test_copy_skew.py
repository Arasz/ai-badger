"""Shape D refuses to run plugin copies that are stale against the root they point at.

The copies in ~/.hermes/plugins/ are install-time snapshots; the framework root they resolve
keeps moving. Spec 002: warn on any difference, refuse when it crosses a BREAKING_VERSIONS
boundary, and never break the session either way.
"""
from __future__ import annotations

import json
from unittest.mock import patch

HOOKS = "features/common/hooks"
PLUGIN_FILES = ("ai_badger_hooks.py", "learned_skills_sync.py")


def _fake_root(path, version, breaking=()):
    """A framework root carrying just the two files the skew check reads."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "VERSION").write_text(version + "\n", encoding="utf-8")
    (path / "BREAKING_VERSIONS").write_text(
        "# comment\n" + "".join(f"{v}\n" for v in breaking), encoding="utf-8")
    return path


def _copies(path, recorded=None):
    """A ~/.hermes/plugins/-shaped directory with the installer's record beside it."""
    path.mkdir(parents=True, exist_ok=True)
    if recorded is not None:
        manifest = path / ".ai-badger" / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        record = {"frameworkRoot": "/somewhere"}
        if recorded:
            record["copiedFromVersion"] = recorded
        manifest.write_text(json.dumps(record), encoding="utf-8")
    return path


# --------------------------------------------------------------- the decision, for real
def test_equal_versions_are_silent(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.0", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.40.0")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


def test_a_difference_with_no_boundary_between_warns_but_runs(tmp_path, load_script):
    """A patch bump must not disable anyone's hooks."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.1", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.40.0")

    verdict, message = bl.copy_skew(copies, root)

    assert verdict == bl.COPY_SKEW_WARN
    assert "0.40.0" in message and "0.40.1" in message


def test_a_difference_across_a_breaking_boundary_refuses(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.0", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.30.0")

    verdict, message = bl.copy_skew(copies, root)

    assert verdict == bl.COPY_SKEW_REFUSE
    assert "0.30.0" in message and "0.40.0" in message


def test_a_downgrade_across_a_boundary_refuses_too(tmp_path, load_script):
    """Newer copies against an older engine is the same skew, running the other way."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.30.0", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.40.0")

    assert bl.copy_skew(copies, root)[0] == bl.COPY_SKEW_REFUSE


def test_a_record_written_before_this_change_is_not_skew(tmp_path, load_script):
    """Absence of the key is not evidence of staleness; every existing install must keep working."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.0", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


def test_no_record_at_all_is_not_skew(tmp_path, load_script):
    """Any deployment that is not Shape D has no record beside it and is not judged."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.0")
    copies = _copies(tmp_path / "plugins")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


def test_an_unreadable_version_is_not_skew(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    root = tmp_path / "fw"
    root.mkdir()
    copies = _copies(tmp_path / "plugins", recorded="0.30.0")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


def test_an_unparseable_record_is_not_skew(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.0")
    copies = tmp_path / "plugins"
    (copies / ".ai-badger").mkdir(parents=True)
    (copies / ".ai-badger" / "manifest.json").write_text("{not json", encoding="utf-8")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


def test_an_unparseable_version_string_is_not_skew(tmp_path, load_script):
    """A malformed version cannot be ordered, so it cannot be judged material."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "not-a-version", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.30.0")

    assert bl.copy_skew(copies, root)[0] == bl.COPY_SKEW_OK


# ------------------------------------------------------------------ the installer's record
def test_the_installer_records_the_version_the_copies_came_from(tmp_path, root, make_scaffolder):
    """AC-1: the record beside the copies names the checkout that wrote them."""
    home = tmp_path / "home"
    home.mkdir()

    scaf = make_scaffolder(config={
        "$schema": "./schemas/config.schema.json", "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"], "agents": ["hermes"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {}, "personaRouting": [], "skillScope": "default", "docs": {},
    }, skills=["task"])
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-29T00:00:00Z")

    record = json.loads(
        (home / ".hermes" / "plugins" / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))

    assert record["copiedFromVersion"] == (root / "VERSION").read_text(encoding="utf-8").strip()
    assert record["frameworkRoot"] == str(root.resolve())


# ----------------------------------------------------------------- what refusal looks like
def test_ai_badger_hooks_registers_nothing_when_the_copies_are_stale(load_script, capsys):
    """AC-2/AC-7: the plugin still loads, registers no callback, and says why on stderr."""
    hooks = load_script(f"{HOOKS}/ai_badger_hooks.py")
    registered = []

    class _Ctx:
        def register_hook(self, name, callback):
            registered.append(name)

    hooks.COPY_SKEW_REFUSAL = "copies are 0.30.0, framework is 0.40.0"
    try:
        hooks.register(_Ctx())
    finally:
        hooks.COPY_SKEW_REFUSAL = None

    assert registered == []
    assert "0.30.0" in capsys.readouterr().err


def test_ai_badger_hooks_registers_normally_when_there_is_no_skew(load_script):
    hooks = load_script(f"{HOOKS}/ai_badger_hooks.py")
    registered = []

    class _Ctx:
        def register_hook(self, name, callback):
            registered.append(name)

    hooks.register(_Ctx())

    assert registered == ["on_session_start", "pre_llm_call", "post_tool_call"]


def test_learned_skills_sync_refuses_to_sync_when_the_copies_are_stale(tmp_path, load_script):
    """AC-3: the entry point returns a refusal naming copy skew, and writes nothing."""
    sync = load_script(f"{HOOKS}/learned_skills_sync.py")
    project = tmp_path / "proj"
    (project / ".ai-badger").mkdir(parents=True)

    sync.COPY_SKEW_REFUSAL = "copies are 0.30.0, framework is 0.40.0"
    try:
        result = sync.sync_skill(project, tmp_path / "src", "probe", None,
                                 now="2026-07-29T00:00:00Z")
    finally:
        sync.COPY_SKEW_REFUSAL = None

    assert result["action"] == "refused"
    assert "0.30.0" in result["reason"]
    assert not (project / ".ai-badger" / "skills").exists()
