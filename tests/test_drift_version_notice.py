"""Tier 1 drift check: scaffold version vs. plugin version (ADR-0001 decision 5, #24).

Tier 1 fires as the plugin-provided `drift_notice_hook.py` (registered via `hooks/hooks.json`),
not as anything on `session_start_hook.py` -- that script is a *scaffolded* copy, so
`$CLAUDE_PLUGIN_ROOT` is never set for it (see both scripts' module docstrings). The comparison
itself (`scaffold_drift_notice`) lives in the shared `drift_notice.py` module and is unit-tested
directly here; the hook tests below exercise `drift_notice_hook.main()` end-to-end.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import sys
from pathlib import Path


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


def _make_root(path, version):
    """A directory the framework-root predicate accepts, carrying a VERSION."""
    for name in ("schemas", "features", "engine"):
        (path / name).mkdir(parents=True, exist_ok=True)
    (path / "engine" / "badger_lib.py").write_text("", encoding="utf-8")
    (path / "VERSION").write_text(version + "\n", encoding="utf-8")
    return path


def _competing_home(tmp_path, monkeypatch, cache_version=None, plugin_versions=()):
    """A `$HOME` holding the trees that compete with the running framework (#109)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    made = {}
    if cache_version:
        made["cache"] = _make_root(home / ".ai-badger" / "framework", cache_version)
    made["plugins"] = [
        _make_root(home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger" / v, v)
        for v in plugin_versions
    ]
    return made


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


def test_the_no_drift_record_names_the_project(tmp_path, root, load_script, monkeypatch):
    """A skip is evidence the hook ran; unattributed it lands in every project's report."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, (root / "VERSION").read_text(encoding="utf-8").strip())
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    calls = []

    class FakeDebugLog:
        def log_event(self, component, event, **fields):
            calls.append((event, fields))

    monkeypatch.setattr(hook, "debug_log", FakeDebugLog())
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))

    hook.main()

    assert calls == [("skip", {"reason": "no_drift", "project": str(project)})]


def test_a_record_stays_unattributed_when_no_root_can_be_found(load_script, monkeypatch):
    """Naming a project the hook could not determine would be a guess, not attribution."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    calls = []

    class FakeDebugLog:
        def log_event(self, component, event, **fields):
            calls.append((event, fields))

    monkeypatch.setattr(hook, "debug_log", FakeDebugLog())
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "sid-1"})))

    hook.main()

    assert calls == [("skip", {"reason": "no_root", "project": None})]


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


def test_the_notice_is_silent_when_no_framework_root_resolves(root, tmp_path, monkeypatch,
                                                              capsys):
    """A copy stranded with no framework above it and an empty home: exit 0, print nothing."""
    home = tmp_path / "home"
    stranded = tmp_path / "plugins" / "drift_notice_hook.py"
    stranded.parent.mkdir(parents=True)
    home.mkdir()
    shutil.copy2(root / "features/common/skills/task/scripts/drift_notice_hook.py", stranded)
    monkeypatch.delenv("AI_BADGER", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(tmp_path)

    spec = importlib.util.spec_from_file_location("aib_stranded_notice", stranded)
    hook = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = hook
    spec.loader.exec_module(hook)

    assert hook.FRAMEWORK_ROOT is None, "the fixture is not rootless; the test proves nothing"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
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


def test_debug_logging_records_fire_when_drift_detected(tmp_path, root, load_script, monkeypatch):
    """Debug log fires when drift notice is emitted."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    calls = []

    class FakeDebugLog:
        def log_event(self, component, event, **fields):
            calls.append((component, event, fields))

    monkeypatch.setattr(hook, "debug_log", FakeDebugLog())
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))
    hook.main()

    events = {e: (c, f) for c, e, f in calls}
    assert "fire" in events
    assert events["fire"][0] == "drift_notice_hook"


def test_debug_logging_is_noop_when_unavailable(tmp_path, root, load_script, monkeypatch):
    """Hook runs normally when debug_log is None."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(hook, "debug_log", None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "sid-1", "source": "startup", "cwd": str(project),
    })))

    rc = hook.main()
    assert rc == 0


# ------------------------------------------------------- competing framework copies (#109)
def test_the_notice_names_every_tree_that_claims_to_be_ai_badger(
        tmp_path, root, load_script, monkeypatch, capsys):
    """Two contradictory notices read as a versioning bug; naming the trees says "two installs"."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    made = _competing_home(tmp_path, monkeypatch, cache_version="0.13.0",
                           plugin_versions=("0.36.2",))
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project)})))

    rc = hook.main()

    assert rc == 0
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "was scaffolded by 0.1.0" in context
    for named in (made["cache"], "0.13.0", made["plugins"][0], "0.36.2", root):
        assert str(named) in context, named
    assert "den-refresh --prune-cache" in context
    assert "Claude Code" in context


def test_the_notice_appears_for_an_idle_cache_even_when_the_scaffold_matches(
        tmp_path, root, load_script, monkeypatch, capsys):
    """The 0.13.0 copy that sat through 23 releases produced no drift of its own (#109)."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    made = _competing_home(tmp_path, monkeypatch, cache_version="0.13.0")
    project = tmp_path / "proj"
    _write_manifest(project, (root / "VERSION").read_text(encoding="utf-8").strip())
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project)})))

    rc = hook.main()

    assert rc == 0
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "was scaffolded by" not in context
    assert str(made["cache"]) in context and "0.13.0" in context


def test_the_hook_stays_silent_when_only_claude_codes_plugin_cache_holds_extra_versions(
        tmp_path, root, load_script, monkeypatch, capsys):
    """Claude Code keeps every version it installed; nagging about its cache is not our place."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    _competing_home(tmp_path, monkeypatch, plugin_versions=("0.36.0", "0.36.2"))
    project = tmp_path / "proj"
    _write_manifest(project, (root / "VERSION").read_text(encoding="utf-8").strip())
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project)})))

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_the_drift_notice_survives_a_copy_scan_that_fails(
        tmp_path, load_script, monkeypatch, capsys):
    """A hook degrades to silence on the part that broke, never on the whole session."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project)})))

    class Exploding:
        """A copy scanner that fails the way a permission error would."""

        @staticmethod
        def discover(**_kwargs):
            raise OSError("no")

    monkeypatch.setattr(hook, "framework_copies", Exploding())
    rc = hook.main()

    assert rc == 0
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "was scaffolded by 0.1.0" in context


def test_the_hook_is_silent_when_the_framework_ships_no_copy_scanner(
        tmp_path, root, load_script, monkeypatch, capsys):
    """A resolved root predating this module still emits its drift notice, and nothing else."""
    hook = load_script("features/common/skills/task/scripts/drift_notice_hook.py")
    _competing_home(tmp_path, monkeypatch, cache_version="0.13.0")
    project = tmp_path / "proj"
    _write_manifest(project, (root / "VERSION").read_text(encoding="utf-8").strip())
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(project)})))
    monkeypatch.setattr(hook, "framework_copies", None)

    rc = hook.main()

    assert rc == 0
    assert capsys.readouterr().out == ""
