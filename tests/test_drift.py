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
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")
    plugin = _write_plugin(tmp_path, "0.2.0")

    notice = dn.scaffold_drift_notice(project, str(plugin))

    assert notice is not None
    assert "0.1.0" in notice and "0.2.0" in notice


def test_silent_when_versions_match(tmp_path, load_script):
    """A noisy hook gets ignored; silence on match is the whole point."""
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.2.0")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_no_manifest(tmp_path, load_script):
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "unscaffolded"
    project.mkdir()
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_plugin_root_unset(tmp_path, load_script):
    """Called with no plugin root at all is not drift."""
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.1.0")

    assert dn.scaffold_drift_notice(project, None) is None


def test_silent_when_manifest_is_malformed(tmp_path, load_script):
    """A broken manifest must never crash SessionStart."""
    dn = load_script("skills/task/scripts/drift_notice.py")
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
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("[1, 2, 3]", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_is_a_bare_scalar(tmp_path, load_script):
    """Same failure mode as the list case, for a bare JSON scalar."""
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("42", encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_manifest_missing_framework_version(tmp_path, load_script):
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(json.dumps({"agents": ["claude"]}), encoding="utf-8")
    plugin = _write_plugin(tmp_path, "0.2.0")

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_silent_when_plugin_has_no_version_file(tmp_path, load_script):
    dn = load_script("skills/task/scripts/drift_notice.py")
    project = tmp_path / "proj"
    _write_manifest(project, "0.2.0")
    plugin = tmp_path / "plugin"
    plugin.mkdir(parents=True)

    assert dn.scaffold_drift_notice(project, str(plugin)) is None


def test_session_start_hook_no_longer_owns_drift(load_script):
    """Regression guard for #24: the scaffolded hook must not keep a dead drift code path."""
    hook = load_script("skills/task/scripts/session_start_hook.py")

    assert not hasattr(hook, "scaffold_drift_notice")
    assert not hasattr(hook, "os")


def test_hook_main_emits_notice_when_versions_differ(tmp_path, root, load_script, monkeypatch,
                                                       capsys):
    """End-to-end through drift_notice_hook.main(): crafted stdin + CLAUDE_PROJECT_DIR, no
    plugin-root guessing needed since the script self-locates from its own real path."""
    hook = load_script("skills/task/scripts/drift_notice_hook.py")
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
    hook = load_script("skills/task/scripts/drift_notice_hook.py")
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
    hook = load_script("skills/task/scripts/drift_notice_hook.py")
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
    hook = load_script("skills/task/scripts/drift_notice_hook.py")
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
    hook = load_script("skills/task/scripts/drift_notice_hook.py")
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


def test_find_plugin_root_walks_ancestors_not_a_fixed_depth(tmp_path, load_script):
    """The regression test for the original bug class: a hardcoded `parents[N]` would
    misroot the moment the script's depth under the plugin root differs from the real repo's
    (`skills/task/scripts/`, depth 3). Build a fixture plugin tree several levels deeper and
    confirm the walk still finds it."""
    hook = load_script("skills/task/scripts/drift_notice_hook.py")

    plugin_root = tmp_path / "some" / "install" / "path" / "ai-badger"
    (plugin_root / "skills").mkdir(parents=True)
    (plugin_root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    deep_script_dir = plugin_root / "extra" / "nesting" / "that" / "does" / "not" / "exist" \
        / "in" / "the" / "real" / "repo"
    deep_script_dir.mkdir(parents=True)

    found = hook.find_plugin_root(deep_script_dir)

    assert found == plugin_root


def test_find_plugin_root_returns_none_when_no_ancestor_qualifies(tmp_path, load_script):
    hook = load_script("skills/task/scripts/drift_notice_hook.py")
    lonely = tmp_path / "no" / "version" / "or" / "skills" / "dir" / "here"
    lonely.mkdir(parents=True)

    assert hook.find_plugin_root(lonely) is None


def test_hooks_json_declares_session_start_pointing_at_a_script_that_exists(root):
    """The test that would have caught the original bug class: a hook pointing at a
    nonexistent script. Structural, not behavioral -- it does not run the hook."""
    hooks_path = root / "hooks" / "hooks.json"
    assert hooks_path.exists()

    data = json.loads(hooks_path.read_text(encoding="utf-8"))
    session_start = data["hooks"]["SessionStart"]
    assert session_start, "hooks.json declares no SessionStart entries"

    matcher = session_start[0].get("matcher", "")
    assert "startup" in matcher and "resume" in matcher

    command = session_start[0]["hooks"][0]["command"]
    match = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"]+)", command)
    assert match, f"could not find a ${{CLAUDE_PLUGIN_ROOT}}-relative path in: {command!r}"
    assert (root / match.group(1)).exists(), (
        f"hooks.json points at {match.group(1)!r}, which does not exist on disk"
    )


def _manifest_with_entry(target, source_rel, target_rel, entry_hash):
    """Write a manifest with one entry to `target/.ai-badger/manifest.json` and return the
    parsed dict, since `compare()` now takes an already-parsed manifest rather than a path."""
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    manifest = {
        "frameworkVersion": "0.2.0",
        "frameworkCommit": None,
        "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [{
            "feature": "invariants", "stack": "common", "name": "n",
            "source": source_rel, "target": target_rel,
            "frameworkVersion": "0.2.0", "hash": entry_hash,
        }],
    }
    (aib / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_compare_reports_changed_when_framework_source_differs(tmp_path, load_script):
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")
    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    src = fw / "features" / "common" / "invariants" / "x.md"
    src.write_text("original\n", encoding="utf-8")
    original_hash = bl.sha256_file(src)

    proj = tmp_path / "proj"
    manifest = _manifest_with_entry(proj, "features/common/invariants/x.md",
                                    ".ai-badger/invariants/x.md", original_hash)
    src.write_text("upstream changed\n", encoding="utf-8")

    result = drift.compare(fw, manifest)

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
    manifest = _manifest_with_entry(proj, "features/common/invariants/x.md",
                                    ".ai-badger/invariants/x.md", bl.sha256_file(src))

    result = drift.compare(fw, manifest)

    assert result["changed"] == []


def test_compare_reports_removed_when_source_gone(tmp_path, load_script):
    """A rename reads as removed — documented limitation, not a bug (ADR-0001 decision 5)."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    proj = tmp_path / "proj"
    manifest = _manifest_with_entry(proj, "features/common/invariants/gone.md",
                                    ".ai-badger/invariants/gone.md", "0" * 64)

    result = drift.compare(fw, manifest)

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
    manifest = _manifest_with_entry(proj, "skills/task", ".ai-badger/skills/task", "0" * 64)

    result = drift.compare(fw, manifest)

    assert "skills/task" in result["skipped"]
    assert "skills/task" not in result["changed"]


def test_compare_reports_removed_directory_entry_as_removed_not_skipped(tmp_path, load_script):
    """Deletion of a directory-valued entry's source is still detectable and must be
    reported as removed, not skipped."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    proj = tmp_path / "proj"
    manifest = _manifest_with_entry(proj, "skills/gone-skill", ".ai-badger/skills/gone-skill",
                                    "0" * 64)

    result = drift.compare(fw, manifest)

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
    manifest = _manifest_with_entry(proj, "features/common/invariants/x.md",
                                    ".ai-badger/invariants/x.md", original_hash)
    src.write_text("upstream changed\n", encoding="utf-8")

    result = drift.compare(fw, manifest)

    assert "features/common/invariants/x.md" in result["changed"]
    assert "features/common/invariants/x.md" not in result["skipped"]


def test_main_exits_zero_when_only_skipped_entries(tmp_path, load_script, capsys):
    """Skipped-only drift is informational, not actionable -- exit 0, not 1. The summary must
    be honest that skipped entries were never compared, not claim a clean "no drift"."""
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
    assert "no drift among the entries that could be compared" in out
    assert "1 skipped entry was not checked" in out
    assert "no drift — every scaffolded item matches" not in out


def test_main_prints_genuinely_clean_message_when_nothing_skipped(
        tmp_path, load_script, capsys):
    """The original unconditional "no drift" wording is still used verbatim when there is
    truly nothing to be dishonest about -- no changed/removed/skipped entries at all."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    proj = tmp_path / "proj"
    aib = proj / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(json.dumps({
        "frameworkVersion": "0.2.0", "frameworkCommit": None, "frameworkDirty": False,
        "agents": ["claude"], "entries": [],
    }), encoding="utf-8")

    rc = drift.main(["--root", str(fw), "--target", str(proj)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "no drift — every scaffolded item matches the framework's current content" in out


def test_main_returns_usage_error_on_corrupt_manifest(tmp_path, load_script, capsys):
    """A malformed manifest.json must produce a friendly exit-2 message, not a raw
    JSONDecodeError traceback."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    proj = tmp_path / "proj"
    aib = proj / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text("{not json", encoding="utf-8")

    rc = drift.main(["--root", str(fw), "--target", str(proj)])

    assert rc == 2
    out = capsys.readouterr().out
    assert "manifest.json" in out
    assert "Traceback" not in out


def test_compare_skips_entry_missing_source_or_hash_without_crashing(tmp_path, load_script):
    """A schema-invalid manifest entry (missing `source` or `hash`) must not raise KeyError.
    It is skipped and counted, not silently swallowed."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    manifest = {
        "frameworkVersion": "0.2.0", "frameworkCommit": None, "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [
            {"feature": "invariants", "stack": "common", "name": "no-source",
             "target": ".ai-badger/invariants/a.md", "frameworkVersion": "0.2.0",
             "hash": "0" * 64},
            {"feature": "invariants", "stack": "common", "name": "no-hash",
             "source": "features/common/invariants/b.md",
             "target": ".ai-badger/invariants/b.md", "frameworkVersion": "0.2.0"},
        ],
    }

    result = drift.compare(fw, manifest)

    assert result["changed"] == []
    assert result["removed"] == []
    assert result["skipped"] == []
    assert result["invalid"] == 2


def test_main_reports_invalid_entry_count_in_output(tmp_path, load_script, capsys):
    """The invalid-entry count must be visible in main()'s output, not swallowed."""
    drift = load_script("skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    proj = tmp_path / "proj"
    aib = proj / ".ai-badger"
    aib.mkdir(parents=True)
    (aib / "manifest.json").write_text(json.dumps({
        "frameworkVersion": "0.2.0", "frameworkCommit": None, "frameworkDirty": False,
        "agents": ["claude"],
        "entries": [{"feature": "invariants", "stack": "common", "name": "no-hash",
                     "source": "features/common/invariants/b.md",
                     "target": ".ai-badger/invariants/b.md", "frameworkVersion": "0.2.0"}],
    }), encoding="utf-8")

    rc = drift.main(["--root", str(fw), "--target", str(proj)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "1" in out and "invalid" in out
