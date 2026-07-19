"""Tier 1 drift check: scaffold version vs installed plugin version (ADR-0001 decision 5)."""
from __future__ import annotations

import io
import json
import subprocess
import sys


def _write_manifest(target, version):
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "manifest.json").write_text(json.dumps({
        "frameworkVersion": version,
        "frameworkCommit": None,
        "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [],
    }), encoding="utf-8")


def _write_plugin(tmp_path, version):
    plugin = tmp_path / "plugin"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "VERSION").write_text(version + "\n", encoding="utf-8")
    return plugin


def test_notice_when_scaffold_and_plugin_versions_differ(tmp_path, load_script):
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    plugin = _write_plugin(tmp_path, "0.2.0")

    notice = hook.scaffold_drift_notice(project, str(plugin))

    assert notice is not None
    assert "0.1.0" in notice and "0.2.0" in notice


def test_silent_when_versions_match(tmp_path, load_script):
    """A noisy hook gets ignored; silence on match is the whole point."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.2.0")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_no_manifest(tmp_path, load_script):
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "unscaffolded"
    project.mkdir()
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_plugin_root_unset(tmp_path, load_script):
    """Running from a repo checkout rather than an installed plugin is not drift."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")

    assert hook.scaffold_drift_notice(project, None) is None


def test_silent_when_manifest_is_malformed(tmp_path, load_script):
    """A broken manifest must never crash SessionStart."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("{not json", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_is_a_json_list(tmp_path, load_script):
    """A syntactically valid but non-object manifest (e.g. `[1, 2, 3]`) must never crash
    SessionStart -- `.get()` on a list raises AttributeError, which the original except
    tuple (OSError, ValueError) does not catch."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_is_a_bare_scalar(tmp_path, load_script):
    """Same failure mode as the list case, for a bare JSON scalar."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("42", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_missing_framework_version(tmp_path, load_script):
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(json.dumps({"agents": ["claude"]}), encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_plugin_has_no_version_file(tmp_path, load_script):
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.2.0")
    plugin = tmp_path / "plugin"
    plugin.mkdir(parents=True)

    assert hook.scaffold_drift_notice(project, str(plugin)) is None


def _patch_project(hook, monkeypatch, project):
    """Reuses the same lib-path patching approach as tests/test_session_start_hook.py's
    `session_start` fixture, so the tracker_lib file I/O in `main()` stays confined to
    `tmp_path` here too."""
    data_dir = project / ".ai-badger" / "task-tracking"
    monkeypatch.setattr(hook.lib, "PROJECT_ROOT", project)
    monkeypatch.setattr(hook.lib, "DATA_DIR", data_dir)
    monkeypatch.setattr(hook.lib, "EXECUTED_TASKS", data_dir / "executed-tasks.json")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(hook.lib, "save_current_session", lambda *a, **k: None)


def test_drift_and_resume_notices_appear_together(tmp_path, load_script, monkeypatch, capsys):
    """The important regression: drift detection and the unfinished-task resume nudge must
    merge into a single hookSpecificOutput payload, not clobber each other."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    _patch_project(hook, monkeypatch, project)

    _write_manifest(project, "0.1.0")
    plugin = _write_plugin(tmp_path, "0.2.0")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin))

    hook.lib.save_json(hook.lib.EXECUTED_TASKS, {"tasks": [
        {"taskId": "T01", "state": "IN_PROGRESS"},
    ]})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "resume",
    })))

    rc = hook.main()

    captured = capsys.readouterr().out
    assert rc == 0
    out = json.loads(captured)  # single valid JSON document -- fails to parse otherwise
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "0.1.0" in context and "0.2.0" in context
    assert "T01" in context


def test_main_silent_when_versions_match_and_no_resume(tmp_path, load_script, monkeypatch, capsys):
    """Stdout is the hook's protocol channel: no unconditional output is allowed."""
    hook = load_script("skills/task/scripts/session_start_hook.py")
    project = tmp_path / "proj"
    _patch_project(hook, monkeypatch, project)

    _write_manifest(project, "0.2.0")
    plugin = _write_plugin(tmp_path, "0.2.0")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin))

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup",
    })))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""
