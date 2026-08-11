"""Shape D refuses to run plugin copies that are stale against the root they point at.

The copies in ~/.hermes/plugins/ are install-time snapshots; the framework root they resolve
keeps moving. Spec 002: warn on any difference, refuse when it crosses a BREAKING_VERSIONS
boundary, and never break the session either way.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from unittest.mock import patch

import pytest
from conftest import _test_write

HOOKS = "features/common/hooks"
PLUGIN_FILES = ("ai_badger_hooks.py", "learned_skills_sync.py")


def _fake_root(path, version, breaking=()):
    """A framework root carrying just the two files the skew check reads."""
    path.mkdir(parents=True, exist_ok=True)
    _test_write(path / "VERSION", version + "\n", encoding="utf-8")
    _test_write(path / "BREAKING_VERSIONS", "# comment\n" + "".join(f"{v}\n" for v in breaking), encoding="utf-8")
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
        _test_write(manifest, json.dumps(record), encoding="utf-8")
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
    """Newer copies against an older engine is the same skew, running the other way.

    The root here still lists the boundary; see the next test for when it cannot.
    """
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.30.0", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.40.0")

    assert bl.copy_skew(copies, root)[0] == bl.COPY_SKEW_REFUSE


def test_a_downgrade_to_a_root_that_predates_the_boundary_can_only_warn(tmp_path, load_script):
    """The known limit of the rule: BREAKING_VERSIONS is read from the root we actually have.

    A tree rolled back past a boundary does not list that boundary — it was added later — so the
    same version pair warns here and refuses on an up-to-date root. Pinned so the asymmetry is a
    recorded limitation rather than a surprise.
    """
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.36.0", breaking=[])
    copies = _copies(tmp_path / "plugins", recorded="0.40.0")

    assert bl.copy_skew(copies, root)[0] == bl.COPY_SKEW_WARN


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
    _test_write(copies / ".ai-badger" / "manifest.json", "{not json", encoding="utf-8")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


def test_an_unparseable_version_string_is_not_skew(tmp_path, load_script):
    """A malformed version cannot be ordered, so it cannot be judged material."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "not-a-version", breaking=["0.37.0"])
    copies = _copies(tmp_path / "plugins", recorded="0.30.0")

    assert bl.copy_skew(copies, root)[0] == bl.COPY_SKEW_OK


# ------------------------------------------------------------------ the installer's record
def test_the_installer_records_the_version_the_copies_came_from(tmp_path, root, make_scaffolder):
    """AC-1: the record beside the copies names the checkout that wrote them.

    `install=True` is explicit because `make_scaffolder` defaults to `False`, and that flag
    now suppresses the user-scope install outright — there would be no record to read.
    """
    home = tmp_path / "home"
    home.mkdir()

    scaf = make_scaffolder(config={
        "$schema": "./schemas/config.schema.json", "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"], "agents": ["hermes"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {}, "personaRouting": [], "skillScope": "default", "docs": {},
    }, skills=["task"], install=True)
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-29T00:00:00Z")

    record = json.loads(
        (home / ".hermes" / "plugins" / "ai-badger" / ".ai-badger" / "manifest.json")
        .read_text(encoding="utf-8"))

    assert record["copiedFromVersion"] == (root / "VERSION").read_text(encoding="utf-8").strip()
    assert record["frameworkRoot"] == str(root.resolve())


def test_a_non_string_recorded_version_is_not_skew(tmp_path, load_script):
    """Only the installer writes this record, but a corrupted value must not reach the parser."""
    bl = load_script("engine/badger_lib.py")
    root = _fake_root(tmp_path / "fw", "0.40.0", breaking=["0.37.0"])
    copies = tmp_path / "plugins"
    (copies / ".ai-badger").mkdir(parents=True)
    _test_write(copies / ".ai-badger" / "manifest.json", json.dumps({"frameworkRoot": "/x", "copiedFromVersion": 123}), encoding="utf-8")

    assert bl.copy_skew(copies, root) == (bl.COPY_SKEW_OK, None)


# ------------------------------------------------- the modules detect skew beside themselves
def _shape_d(monkeypatch, module, tmp_path, recorded, current, breaking=("0.37.0",)):
    """Point a loaded plugin module at a fake ~/.hermes/plugins/ and a fake framework root."""
    copies = _copies(tmp_path / "plugins", recorded=recorded)
    root = _fake_root(tmp_path / "fw", current, breaking=breaking)
    monkeypatch.setattr(module, "__file__", str(copies / "plugin.py"))
    monkeypatch.setattr(module, "FRAMEWORK_ROOT", root)
    return copies, root


@pytest.mark.parametrize("name", PLUGIN_FILES)
def test_the_module_finds_the_record_beside_itself_and_refuses(
        name, tmp_path, monkeypatch, load_script):
    """Pins the directory the check looks in: the copies' own, not the framework's."""
    module = load_script(f"{HOOKS}/{name}")
    _shape_d(monkeypatch, module, tmp_path, recorded="0.30.0", current="0.40.0")

    assert "0.30.0" in module._copy_skew_refusal()


@pytest.mark.parametrize("name", PLUGIN_FILES)
def test_the_module_warns_on_stderr_but_runs_for_a_non_material_difference(
        name, tmp_path, monkeypatch, load_script, capsys):
    module = load_script(f"{HOOKS}/{name}")
    _shape_d(monkeypatch, module, tmp_path, recorded="0.40.0", current="0.40.1")

    assert module._copy_skew_refusal() is None
    assert "0.40.1" in capsys.readouterr().err


@pytest.mark.parametrize("name", PLUGIN_FILES)
def test_the_module_says_nothing_when_the_versions_agree(
        name, tmp_path, monkeypatch, load_script, capsys):
    module = load_script(f"{HOOKS}/{name}")
    _shape_d(monkeypatch, module, tmp_path, recorded="0.40.0", current="0.40.0")

    assert module._copy_skew_refusal() is None
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("name", PLUGIN_FILES)
def test_a_framework_too_old_to_know_the_check_does_not_break_the_import(
        name, tmp_path, monkeypatch, load_script):
    """copy_skew is new; copies newer than the root they resolve must still import (AC-7)."""
    module = load_script(f"{HOOKS}/{name}")
    _shape_d(monkeypatch, module, tmp_path, recorded="0.30.0", current="0.40.0")

    class _OldEngine:  # a badger_lib from before copy_skew existed
        pass

    monkeypatch.setitem(sys.modules, "badger_lib", _OldEngine())
    if getattr(module, "bl", None) is not None:
        monkeypatch.setattr(module, "bl", _OldEngine())

    assert module._copy_skew_refusal() is None


# ------------------------------------------------------- a real Shape D import, end to end
def _shape_d_install(tmp_path, root, name, recorded, current, breaking=("0.37.0",)):
    """Copy one plugin module into a plugins/ dir whose record points at a fake framework."""
    fw = _fake_root(tmp_path / "fw", current, breaking=breaking)
    for sub in ("schemas", "features"):
        (fw / sub).mkdir(exist_ok=True)
    (fw / "engine").mkdir(exist_ok=True)
    for engine_file in ("badger_lib.py", "unsafe_literals.py"):
        shutil.copy2(root / "engine" / engine_file, fw / "engine" / engine_file)

    copies = tmp_path / "plugins"
    copies.mkdir(exist_ok=True)
    shutil.copy2(root / HOOKS / name, copies / name)
    manifest = copies / ".ai-badger" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    _test_write(manifest, json.dumps(
        {"frameworkRoot": str(fw), "copiedFromVersion": recorded}), encoding="utf-8")
    return copies / name


def _import_isolated(path, label):
    spec = importlib.util.spec_from_file_location(label, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[label] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(label, None)
    return module


@pytest.mark.parametrize("name", PLUGIN_FILES)
def test_a_shape_d_import_records_its_own_refusal(name, tmp_path, root, monkeypatch):
    """The wiring, not just the check: importing stale copies leaves COPY_SKEW_REFUSAL set."""
    monkeypatch.delenv("AI_BADGER", raising=False)
    installed = _shape_d_install(tmp_path, root, name, recorded="0.30.0", current="0.40.0")

    module = _import_isolated(installed, f"shape_d_stale_{name}")

    assert module.COPY_SKEW_REFUSAL and "0.30.0" in module.COPY_SKEW_REFUSAL


@pytest.mark.parametrize("name", PLUGIN_FILES)
def test_a_shape_d_import_of_current_copies_refuses_nothing(name, tmp_path, root, monkeypatch):
    monkeypatch.delenv("AI_BADGER", raising=False)
    installed = _shape_d_install(tmp_path, root, name, recorded="0.40.0", current="0.40.0")

    module = _import_isolated(installed, f"shape_d_current_{name}")

    assert module.COPY_SKEW_REFUSAL is None


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

    assert registered == ["on_session_start", "pre_llm_call", "pre_tool_call",
                          "post_tool_call"]


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
