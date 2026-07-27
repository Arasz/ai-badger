"""Tier 1 drift check: scaffold version vs. plugin version (ADR-0001 decision 5, #24).

Tier 1 fires as the plugin-provided `drift_notice_hook.py` (registered via `hooks/hooks.json`),
not as anything on `session_start_hook.py` -- that script is a *scaffolded* copy, so
`$CLAUDE_PLUGIN_ROOT` is never set for it (see both scripts' module docstrings). The comparison
itself (`scaffold_drift_notice`) lives in the shared `drift_notice.py` module and is unit-tested
directly here; the hook tests below exercise `drift_notice_hook.main()` end-to-end.
"""
from __future__ import annotations

import io
import json
import re
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
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    plugin = _write_plugin(tmp_path, "0.2.0")

    notice = dn.scaffold_drift_notice(project, str(plugin))

    assert notice is not None
    assert "0.1.0" in notice and "0.2.0" in notice


def test_silent_when_versions_match(tmp_path, load_script):
    """A noisy hook gets ignored; silence on match is the whole point."""
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.2.0")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_no_manifest(tmp_path, load_script):
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "unscaffolded"
    project.mkdir()
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_plugin_root_unset(tmp_path, load_script):
    """Called with no plugin root at all is not drift."""
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")

    assert dn.scaffold_drift_notice(project, None) is None


def test_silent_when_manifest_is_malformed(tmp_path, load_script):
    """A broken manifest must never crash SessionStart."""
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("{not json", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_is_a_json_list(tmp_path, load_script):
    """A syntactically valid but non-object manifest (e.g. `[1, 2, 3]`) must never crash
    SessionStart -- `.get()` on a list raises AttributeError, which the original except
    tuple (OSError, ValueError) does not catch."""
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_is_a_bare_scalar(tmp_path, load_script):
    """Same failure mode as the list case, for a bare JSON scalar."""
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("42", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_missing_framework_version(tmp_path, load_script):
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(json.dumps({"agents": ["claude"]}), encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_plugin_has_no_version_file(tmp_path, load_script):
    dn = load_script("features/common/skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.2.0")
    plugin = tmp_path / "plugin"
    plugin.mkdir(parents=True)

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_session_start_hook_no_longer_owns_drift(load_script):
    """Regression guard for #24: the scaffolded hook must not keep a dead drift code path."""
    hook = load_script("features/common/skills/task/scripts/session_start_hook.py")

    assert not hasattr(hook, "scaffold_drift_notice")
    assert not hasattr(hook, "os")


def test_hook_main_emits_notice_when_versions_differ(tmp_path, root, load_script, monkeypatch,
                                                       capsys):
    """End-to-end through drift_notice_hook.main(): crafted stdin + CLAUDE_PROJECT_DIR, no
    plugin-root guessing needed since the script self-locates from its own real path."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))

    rc = hook.main()

    captured = capsys.readouterr().out
    assert rc == 0
    out = json.loads(captured)  # single valid JSON document -- fails to parse otherwise
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = out["hookSpecificOutput"]["additionalContext"]
    plugin_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert "0.1.0" in context and plugin_version in context


def test_hook_main_silent_when_versions_match(tmp_path, root, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    plugin_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    _write_manifest(project, plugin_version)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_main_silent_when_no_manifest(tmp_path, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "unscaffolded"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_main_silent_and_exit_zero_for_malformed_manifests(tmp_path, load_script,
                                                                  monkeypatch, capsys):
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    for label, content in (
        ("json-list", "[1, 2, 3]"),
        ("bare-scalar", "42"),
        ("unparseable", "{not json"),
    ):
        project = tmp_path / label
        aib = project / ".ai-badger"
        aib.mkdir(parents=True)
        (aib / "manifest.json").write_text(content, encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
            "session_id": "sid-1", "source": "startup", "cwd": str(project),
        })))

        rc = hook.main()

        assert rc == 0, label
        assert capsys.readouterr().out == "", label


def test_hook_main_falls_back_to_payload_cwd_when_project_dir_env_unset(
        tmp_path, root, load_script, monkeypatch, capsys):
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))

    rc = hook.main()

    captured = capsys.readouterr().out
    assert rc == 0
    out = json.loads(captured)
    plugin_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert "0.1.0" in out["hookSpecificOutput"]["additionalContext"]
    assert plugin_version in out["hookSpecificOutput"]["additionalContext"]


def test_the_hook_resolves_the_same_root_from_two_different_depths(load_script, root):
    """The regression test for the original bug class: a hardcoded `parents[N]` would misroot
    the moment the script's depth changes. The catalog copy sits at depth 5, the generated
    plugin copy at depth 3, and both must answer with the same framework root."""
    catalog = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    mirrored = load_script("skills/task/scripts/drift_notice_hook.py")

    assert catalog.FRAMEWORK_ROOT == root
    assert mirrored.FRAMEWORK_ROOT == root


def test_the_notice_is_silent_when_no_framework_root_resolves(load_script, monkeypatch, capsys):
    """No root means no version to compare: exit 0, print nothing, never crash."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    monkeypatch.setattr(hook, "FRAMEWORK_ROOT", None)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))

    assert hook.main() == 0
    assert capsys.readouterr().out == ""


def test_hooks_json_declares_session_start_pointing_at_a_script_that_exists(root):
    """The test that would have caught the original bug class: a hook pointing at a
    nonexistent script. Structural, not behavioral -- it does not run the hook."""
    hooks_path = root / "features" / "common" / "hooks" / "hooks.json"
    assert hooks_path.exists()

    data = json.loads(hooks_path.read_text(encoding="utf-8"))
    session_start = data["hooks"]["SessionStart"]
    assert session_start, "hooks.json declares no SessionStart entries"

    matcher = session_start[0].get("matcher", "")
    assert "startup" in matcher and "resume" in matcher

    command = session_start[0]["hooks"][0]["command"]
    match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"]+)", command)
    assert match, f"could not find a ${{CLAUDE_PLUGIN_ROOT}}-relative path in: {command!r}"
    # Check the script exists relative to the hooks directory (new location)
    assert (root / "features" / "common" / "hooks" / "drift_notice_hook.py").exists() or \
           (root / "features" / "common" / "skills" / "task" / "scripts" / "drift_notice_hook.py").exists(), (
        f"hooks.json points at {match.group(1)!r}, which does not exist on disk"
    )
