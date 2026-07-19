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


def _manifest_with_entry(target, source_rel, target_rel, entry_hash):
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "manifest.json").write_text(json.dumps({
        "frameworkVersion": "0.2.0",
        "frameworkCommit": None,
        "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [{
            "feature": "invariants", "stack": "common", "name": "n",
            "source": source_rel, "target": target_rel,
            "frameworkVersion": "0.2.0", "hash": entry_hash,
        }],
    }), encoding="utf-8")


def test_compare_reports_changed_when_framework_source_differs(tmp_path, load_script):
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")
    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    src = fw / "features" / "common" / "invariants" / "x.md"
    src.write_text("original\n", encoding="utf-8")
    original_hash = bl.sha256_file(src)

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "features/common/invariants/x.md",
                         ".ai-badger/invariants/x.md", original_hash)
    src.write_text("upstream changed\n", encoding="utf-8")

    result = drift.compare(fw, proj)

    assert "features/common/invariants/x.md" in result["changed"]
    assert result["removed"] == []


def test_compare_silent_when_source_unchanged(tmp_path, load_script):
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")
    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    src = fw / "features" / "common" / "invariants" / "x.md"
    src.write_text("stable\n", encoding="utf-8")

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "features/common/invariants/x.md",
                         ".ai-badger/invariants/x.md", bl.sha256_file(src))

    result = drift.compare(fw, proj)

    assert result["changed"] == []


def test_compare_reports_removed_when_source_gone(tmp_path, load_script):
    """A rename reads as removed — documented limitation, not a bug (ADR-0001 decision 5)."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "features/common/invariants/gone.md",
                         ".ai-badger/invariants/gone.md", "0" * 64)

    result = drift.compare(fw, proj)

    assert "features/common/invariants/gone.md" in result["removed"]


def test_compare_reports_directory_entry_as_skipped_not_changed(tmp_path, load_script):
    """Directory entries can't be compared (recorded hash covers the scaffolded copy, which
    strips tests/evals and embeds extensions -- structurally different from the source tree).
    They must be surfaced as skipped, not silently dropped and not flagged as changed."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    skill_dir = fw / "skills" / "task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content\n", encoding="utf-8")

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "skills/task", ".ai-badger/skills/task", "0" * 64)

    result = drift.compare(fw, proj)

    assert "skills/task" in result["skipped"]
    assert "skills/task" not in result["changed"]


def test_compare_reports_removed_directory_entry_as_removed_not_skipped(tmp_path, load_script):
    """Deletion of a directory-valued entry's source is still detectable and must be
    reported as removed, not skipped."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "skills/gone-skill", ".ai-badger/skills/gone-skill", "0" * 64)

    result = drift.compare(fw, proj)

    assert "skills/gone-skill" in result["removed"]
    assert "skills/gone-skill" not in result["skipped"]


def test_compare_changed_file_entry_does_not_appear_in_skipped(tmp_path, load_script):
    """File entries are unaffected by the directory-skip path."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")
    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    src = fw / "features" / "common" / "invariants" / "x.md"
    src.write_text("original\n", encoding="utf-8")
    original_hash = bl.sha256_file(src)

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "features/common/invariants/x.md",
                         ".ai-badger/invariants/x.md", original_hash)
    src.write_text("upstream changed\n", encoding="utf-8")

    result = drift.compare(fw, proj)

    assert "features/common/invariants/x.md" in result["changed"]
    assert "features/common/invariants/x.md" not in result["skipped"]


def test_main_exits_zero_when_only_skipped_entries(tmp_path, load_script, monkeypatch, capsys):
    """Skipped-only drift is informational, not actionable -- exit 0, not 1."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    skill_dir = fw / "skills" / "task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content\n", encoding="utf-8")
    (fw / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    proj = tmp_path / "proj"
    _manifest_with_entry(proj, "skills/task", ".ai-badger/skills/task", "0" * 64)

    rc = drift.main(["--root", str(fw), "--target", str(proj)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "skills/task" in out
