"""Drift comparison: `drift.compare()` and `drift.main()` over a scaffolded manifest.

Tier 1 (scaffold version vs. plugin version) lives in test_drift_version_notice.py; catalog
additions live in test_drift_new_items.py.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from scaffold_helpers import _config

# Enough of a framework to scaffold from and safe to mutate — the shared checkout is not.
_FRAMEWORK_TREE = ("features", "schemas", "engine", "tooling", "hooks", "skills",
                   ".claude-plugin", "VERSION", "index.json", "BREAKING_VERSIONS")


def _copy_framework(source: Path, dest: Path) -> Path:
    """Copy the framework tree to `dest` so a test may move it ahead of a scaffolded project."""
    dest.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in _FRAMEWORK_TREE:
        src = source / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=ignore)
        elif src.is_file():
            shutil.copy2(src, dest / name)
    return dest


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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    proj = tmp_path / "proj"
    manifest = _manifest_with_entry(proj, "features/common/invariants/gone.md",
                                    ".ai-badger/invariants/gone.md", "0" * 64)

    result = drift.compare(fw, manifest)

    assert "features/common/invariants/gone.md" in result["removed"]


def test_compare_reports_directory_entry_as_skipped_not_changed(tmp_path, load_script):
    """Directory entries with matching content hash are not flagged as changed."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw = tmp_path / "fw"
    skill_dir = fw / "features" / "common" / "skills" / "task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content\n", encoding="utf-8")

    # Compute the correct hash
    fingerprint = bl.dir_content_hash(skill_dir)

    manifest = {
        "entries": [{
            "feature": "skills", "stack": "common", "name": "task",
            "source": "features/common/skills/task",
            "target": ".ai-badger/skills/task",
            "hash": fingerprint["content_hash"],
            "dirMeta": {
                "file_count": fingerprint["file_count"],
                "dir_count": fingerprint["dir_count"],
            },
        }],
    }

    result = drift.compare(fw, manifest)

    assert "features/common/skills/task" not in result["changed"]
    assert "features/common/skills/task" not in result.get("skipped", [])


def test_compare_reports_removed_directory_entry_as_removed_not_skipped(tmp_path, load_script):
    """Deletion of a directory-valued entry's source is still detectable and must be
    reported as removed, not skipped."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
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
    """Skipped-only drift is informational, not actionable -- exit 0, not 1."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw = tmp_path / "fw"
    skill_dir = fw / "features" / "common" / "skills" / "task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content\n", encoding="utf-8")
    (fw / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    # Compute correct hash
    fingerprint = bl.dir_content_hash(skill_dir)

    proj = tmp_path / "proj"
    manifest = {
        "$schema": "../schemas/manifest.schema.json",
        "frameworkVersion": "0.2.0",
        "frameworkCommit": None,
        "frameworkDirty": False,
        "generatedAt": None,
        "agents": ["claude"],
        "skillScope": "default",
        "entries": [{
            "feature": "skills", "stack": "common", "name": "task",
            "source": "features/common/skills/task",
            "target": ".ai-badger/skills/task",
            "frameworkVersion": "0.2.0",
            "hash": fingerprint["content_hash"],
            "dirMeta": {
                "file_count": fingerprint["file_count"],
                "dir_count": fingerprint["dir_count"],
            },
        }],
    }
    (proj / ".ai-badger").mkdir(parents=True)
    (proj / ".ai-badger" / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    rc = drift.main(["--root", str(fw), "--target", str(proj)])

    assert rc == 0
    out = capsys.readouterr().out
    # With matching hashes, directory entries are "no drift" — not skipped
    assert "no drift" in out


def test_main_prints_genuinely_clean_message_when_nothing_skipped(
        tmp_path, load_script, capsys):
    """The original unconditional "no drift" wording is still used verbatim when there is
    truly nothing to be dishonest about -- no changed/removed/skipped entries at all."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
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
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
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


# --------------------------------------------------------- directory hash comparison
def test_compare_detects_changed_dir_by_hash(tmp_path, load_script):
    """A directory entry with different content should be reported as changed."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    fw = tmp_path / "fw"
    skill_dir = fw / "features" / "common" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("v2 content\n")

    # Manifest has a different hash
    manifest = {
        "entries": [{
            "feature": "skills", "stack": "common", "name": "my-skill",
            "source": "features/common/skills/my-skill",
            "target": ".ai-badger/skills/my-skill",
            "hash": "different-hash",
            "dirMeta": {"file_count": 1, "dir_count": 0},
        }],
    }

    result = drift.compare(fw, manifest)
    assert "features/common/skills/my-skill" in result["changed"]


def test_compare_passes_unchanged_dir(tmp_path, load_script):
    """A directory entry with same content should not be reported as changed."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")

    fw = tmp_path / "fw"
    skill_dir = fw / "features" / "common" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("content\n")

    # Compute the expected hash
    fingerprint = bl.dir_content_hash(skill_dir)

    manifest = {
        "entries": [{
            "feature": "skills", "stack": "common", "name": "my-skill",
            "source": "features/common/skills/my-skill",
            "target": ".ai-badger/skills/my-skill",
            "hash": fingerprint["content_hash"],
            "dirMeta": {
                "file_count": fingerprint["file_count"],
                "dir_count": fingerprint["dir_count"],
            },
        }],
    }

    result = drift.compare(fw, manifest)
    assert "features/common/skills/my-skill" not in result["changed"]
    assert "features/common/skills/my-skill" not in result.get("skipped", [])


def test_an_extension_pruned_from_the_project_is_not_drift(tmp_path, load_script):
    """#60: extensions/ is config-gated, so a project that pruned one has not drifted.

    Both hashes exclude it — the source hash that answers the framework question (#110)
    and the target hash that answers the local one.
    """
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")

    fw = tmp_path / "fw"
    fw.mkdir()

    # Framework source: skill has an extensions/ dir with github
    skill_src = fw / "features" / "common" / "skills" / "task"
    (skill_src / "extensions" / "github").mkdir(parents=True)
    (skill_src / "scripts").mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("# task skill\n")
    (skill_src / "scripts" / "tracker.py").write_text("print('track')\n")
    (skill_src / "extensions" / "github" / "extension.md").write_text("# GitHub ext\n")

    # Scaffolded target: same skill but WITHOUT extensions (pruned by config)
    target = tmp_path / "proj"
    skill_tgt = target / ".ai-badger" / "skills" / "task"
    (skill_tgt / "scripts").mkdir(parents=True)
    (skill_tgt / "SKILL.md").write_text("# task skill\n")
    (skill_tgt / "scripts" / "tracker.py").write_text("print('track')\n")

    # Manifest records both hashes, as scaffold.record() does
    exclude = bl.SKILL_EXCLUDE_PATTERNS + ["extensions"]
    fingerprint = bl.dir_content_hash(skill_tgt, exclude=exclude)
    source_print = bl.dir_content_hash(skill_src, exclude=exclude)
    manifest = {
        "frameworkVersion": "0.3.0",
        "entries": [{
            "feature": "skills", "stack": "common", "name": "task",
            "source": "features/common/skills/task",
            "target": ".ai-badger/skills/task",
            "hash": fingerprint["content_hash"],
            "dirMeta": {
                "file_count": fingerprint["file_count"],
                "dir_count": fingerprint["dir_count"],
            },
            "sourceHash": source_print["content_hash"],
            "sourceMeta": {
                "file_count": source_print["file_count"],
                "dir_count": source_print["dir_count"],
            },
        }],
    }

    result = drift.compare(fw, manifest, target=target)

    assert "features/common/skills/task" not in result["changed"]
    assert "features/common/skills/task" not in result["locallyModified"]


def test_real_scaffold_with_retained_extensions_has_no_drift(load_script, root, make_scaffolder):
    """Round-trip guard: scaffold.record() and drift.compare() must hash alike.

    The other dir-entry tests hand-build their manifest, so they cannot catch the two sides
    diverging on which directory they hash or which patterns they exclude. This one scaffolds
    for real with every extension retained, which is the case where a mismatch shows up.
    """
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    target = make_scaffolder.target
    config = {
        "frameworkVersion": "0.1.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": ["dotnet", "hermes"],
        "agents": ["claude"],
        "sourceControl": {
            "platform": "github", "repoUrl": "https://github.com/o/r", "projectUrl": None,
        },
        "commands": {}, "personaRouting": [], "skillScope": "default", "docs": {},
    }
    make_scaffolder(config=config, skills=["task"]).run(generated_at="2026-07-19T00:00:00Z")

    kept = sorted(
        p.name for p in (target / ".ai-badger/skills/task/extensions").iterdir() if p.is_dir()
    )
    assert kept, "expected extensions to survive pruning for this to be a real test"

    manifest = json.loads((target / ".ai-badger/manifest.json").read_text())
    result = drift.compare(root, manifest, target=target)

    assert "features/common/skills/task" not in result["changed"]


def test_a_manifest_target_outside_the_project_is_not_hashed(tmp_path, load_script, root):
    """`Path("/a") / "/etc"` is `/etc`: an absolute manifest target must not steer the
    hasher out of the project (WP41b / security I1)."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    target = tmp_path / "proj"
    (target / ".ai-badger").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("not ours\n", encoding="utf-8")

    manifest = {
        "frameworkVersion": "0.1.0",
        "entries": [{
            "feature": "skills", "stack": "common", "name": "task",
            "source": "features/common/skills/task",
            "target": str(outside),
            "frameworkVersion": "0.1.0", "hash": "0" * 64,
        }],
    }

    result = drift.compare(root, manifest, target=target)

    assert str(outside) not in json.dumps(result)
    assert any("outside the project" in note for note in result.get("notes", []))


def test_freshly_scaffolded_project_reports_nothing_changed(load_script, root, make_scaffolder):
    """A project scaffolded from this framework and left untouched must report no drift."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    target = make_scaffolder.target

    result = make_scaffolder(config=_config(stacks=["python"], agents=["claude", "copilot"]),
                             skills=["task"]).run(generated_at="2026-07-19T00:00:00Z")

    assert any(e["feature"] == "adjustments" for e in result["manifest"]["entries"]), \
        "expected adjustment entries so this exercises the reported defect"

    compared = drift.compare(root, result["manifest"], target=target)

    assert compared["changed"] == []
    assert compared["locallyModified"] == []
    assert compared["skipped"] == []


def test_a_skill_changed_in_the_framework_is_reported_as_drift(
        tmp_path, load_script, root, make_scaffolder):
    """The question den-refresh exists to answer; the scaffolded copy cannot answer it."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = _copy_framework(root, tmp_path / "fw")
    target = make_scaffolder.target

    result = make_scaffolder(root=fw, config=_config(stacks=["python"]),
                             skills=["task"]).run(generated_at="2026-07-28T00:00:00Z")

    moved = fw / "features" / "common" / "skills" / "task" / "scripts" / "task_tracker.py"
    moved.write_text(moved.read_text(encoding="utf-8") + "# upstream moved on\n",
                     encoding="utf-8")

    compared = drift.compare(fw, result["manifest"], target=target)

    assert "features/common/skills/task" in compared["changed"]


def test_a_project_edit_to_its_own_copy_is_not_framework_drift(
        tmp_path, load_script, root, make_scaffolder):
    """Editing the vendored copy is a local modification, reported apart from framework drift."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = _copy_framework(root, tmp_path / "fw")
    target = make_scaffolder.target

    result = make_scaffolder(root=fw, config=_config(stacks=["python"]),
                             skills=["task"]).run(generated_at="2026-07-28T00:00:00Z")

    edited = target / ".ai-badger" / "skills" / "task" / "scripts" / "task_tracker.py"
    edited.write_text(edited.read_text(encoding="utf-8") + "# ours\n", encoding="utf-8")

    compared = drift.compare(fw, result["manifest"], target=target)

    assert compared["changed"] == []
    assert "features/common/skills/task" in compared["locallyModified"]


def test_a_version_only_difference_is_drift(tmp_path, load_script):
    """The version is rendered into manifest.json and every agent file, so it goes stale alone."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.4.0\n", encoding="utf-8")

    result = drift.compare(fw, {"frameworkVersion": "0.3.0", "entries": []})

    assert result["versionChanged"] == {"scaffolded": "0.3.0", "current": "0.4.0"}


def test_main_reports_drift_when_only_the_version_moved(tmp_path, load_script, capsys):
    """Exit 1, not 0: the rendered stamps are stale even with every entry byte-identical."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.4.0\n", encoding="utf-8")
    proj = tmp_path / "proj"
    (proj / ".ai-badger").mkdir(parents=True)
    (proj / ".ai-badger" / "manifest.json").write_text(json.dumps({
        "frameworkVersion": "0.3.0", "frameworkCommit": None, "frameworkDirty": False,
        "agents": ["claude"], "entries": [],
    }), encoding="utf-8")

    rc = drift.main(["--root", str(fw), "--target", str(proj)])

    assert rc == 1
    assert "0.3.0" in capsys.readouterr().out


def _write_project_config(target, config):
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "config.json").write_text(json.dumps(config), encoding="utf-8")


def test_a_config_edit_since_the_scaffold_is_drift(tmp_path, load_script):
    """Issue #128: the whole bug — a config-only edit must be reported as drift."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    proj = tmp_path / "proj"
    config = {"stacks": ["python"], "agents": ["claude"]}
    recorded = bl.config_hash(config)
    _write_project_config(proj, config)
    # the project declines an invariant after the scaffold was built
    config["exclude"] = {"invariants": ["tdd-mandatory"]}
    _write_project_config(proj, config)

    result = drift.compare(fw, {"entries": [], "configHash": recorded}, target=proj)

    assert result["configChanged"] == {"recorded": recorded, "current": bl.config_hash(config)}


def test_a_byte_identical_config_is_not_drift(tmp_path, load_script):
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    proj = tmp_path / "proj"
    config = {"stacks": ["python"], "agents": ["claude"]}
    _write_project_config(proj, config)

    result = drift.compare(fw, {"entries": [], "configHash": bl.config_hash(config)}, target=proj)

    assert result["configChanged"] is None


def test_a_reformatted_config_is_not_drift(tmp_path, load_script):
    """Whitespace/key-order churn must never read as a config edit."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    proj = tmp_path / "proj"
    config = {"stacks": ["python"], "agents": ["claude"]}
    recorded = bl.config_hash(config)
    aib = proj / ".ai-badger"
    aib.mkdir(parents=True)
    reformatted = dict(reversed(list(config.items())))
    (aib / "config.json").write_text(json.dumps(reformatted, indent=4), encoding="utf-8")

    result = drift.compare(fw, {"entries": [], "configHash": recorded}, target=proj)

    assert result["configChanged"] is None


def test_a_manifest_with_no_recorded_config_hash_reports_no_baseline(tmp_path, load_script):
    """Migration: a manifest written before 0.46.0 has no configHash to compare against."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    proj = tmp_path / "proj"
    config = {"stacks": ["python"], "agents": ["claude"]}
    _write_project_config(proj, config)

    result = drift.compare(fw, {"entries": []}, target=proj)

    assert result["configChanged"] == {"recorded": None, "current": bl.config_hash(config)}


def test_one_changed_source_is_reported_once_however_many_entries_share_it(
        tmp_path, load_script):
    """Adjustments record an entry per written file, all sharing one source script."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    (fw / "features" / "copilot" / "adjustments").mkdir(parents=True)
    (fw / "features" / "copilot" / "adjustments" / "adjust_skills.py").write_text(
        "upstream moved on\n", encoding="utf-8")
    source_rel = "features/copilot/adjustments/adjust_skills.py"
    manifest = {"entries": [
        {"feature": "adjustments", "stack": "copilot", "name": f"adjustments/s{i}",
         "source": source_rel, "target": f".github/skills/s{i}",
         "frameworkVersion": "0.1.0", "hash": "0" * 64}
        for i in range(3)
    ]}

    result = drift.compare(fw, manifest)

    assert result["changed"] == [source_rel]


# ── mcp-tools.yaml migration: reported, never converted (issue #145) ───────

def test_compare_notes_a_not_yet_migrated_legacy_mcp_index(tmp_path, load_script):
    """den-refresh reports the legacy file; it never writes mcp-tools.yaml/json itself —
    that file is project-owned, same precedent as a config edit being drift, not silence."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    proj = tmp_path / "proj"
    (proj / ".ai-badger").mkdir(parents=True)
    (proj / ".ai-badger" / "mcp-tools.yaml").write_text("sources: []\n", encoding="utf-8")

    result = drift.compare(fw, {"entries": []}, target=proj)

    assert any("mcp-tools.yaml" in note and "mcp-index migrate" in note
               for note in result["notes"])


def test_compare_is_silent_once_migrated_to_json(tmp_path, load_script):
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    proj = tmp_path / "proj"
    (proj / ".ai-badger").mkdir(parents=True)
    (proj / ".ai-badger" / "mcp-tools.json").write_text("{}", encoding="utf-8")

    result = drift.compare(fw, {"entries": []}, target=proj)

    assert not any("mcp-tools" in note for note in result["notes"])


def test_compare_is_silent_with_no_target_or_no_index_at_all(tmp_path, load_script):
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    fw = tmp_path / "fw"
    fw.mkdir()

    assert drift.compare(fw, {"entries": []})["notes"] == []

    proj = tmp_path / "proj"
    (proj / ".ai-badger").mkdir(parents=True)
    result = drift.compare(fw, {"entries": []}, target=proj)
    assert not any("mcp-tools" in note for note in result["notes"])


def _mcp_index_shaped(tmp_path, bl):
    """A skill scaffolded normally, then written into by an adjustment (issue #224).

    Returns (framework root, project root, manifest) with the manifest recorded exactly as
    `scaffold.record()` writes it: the skill's `hash` is taken before the adjustment runs.
    """
    fw = tmp_path / "fw"
    skill_src = fw / "features" / "common" / "skills" / "mcp-index"
    (skill_src / "scripts").mkdir(parents=True)
    (skill_src / "SKILL.md").write_text("# mcp-index\n", encoding="utf-8")
    (skill_src / "scripts" / "mcp_index.py").write_text("print('index')\n", encoding="utf-8")

    proj = tmp_path / "proj"
    skill_tgt = proj / ".ai-badger" / "skills" / "mcp-index"
    (skill_tgt / "scripts").mkdir(parents=True)
    (skill_tgt / "SKILL.md").write_text("# mcp-index\n", encoding="utf-8")
    (skill_tgt / "scripts" / "mcp_index.py").write_text("print('index')\n", encoding="utf-8")

    exclude = bl.SKILL_EXCLUDE_PATTERNS + ["extensions"]
    tgt_print = bl.dir_content_hash(skill_tgt, exclude=exclude)
    src_print = bl.dir_content_hash(skill_src, exclude=exclude)

    # Only now does adjust_retrieval.py copy a shared module in beside the skill's own.
    (skill_tgt / "scripts" / "bm25.py").write_text("# retrieval\n", encoding="utf-8")

    manifest = {
        "frameworkVersion": "0.53.1",
        "entries": [
            {
                "feature": "skills", "stack": "common", "name": "mcp-index",
                "source": "features/common/skills/mcp-index",
                "target": ".ai-badger/skills/mcp-index",
                "hash": tgt_print["content_hash"],
                "dirMeta": {"file_count": tgt_print["file_count"],
                            "dir_count": tgt_print["dir_count"]},
                "sourceHash": src_print["content_hash"],
                "sourceMeta": {"file_count": src_print["file_count"],
                               "dir_count": src_print["dir_count"]},
            },
            {
                "feature": "adjustments", "stack": "claude",
                "name": "adjustments/.ai-badger/skills/mcp-index/scripts/bm25.py",
                "source": "features/claude/adjustments/adjust_retrieval.py",
                "target": ".ai-badger/skills/mcp-index/scripts/bm25.py",
                "hash": "0" * 64,
            },
        ],
    }
    return fw, proj, manifest


def test_a_file_another_entry_owns_is_not_a_local_modification(tmp_path, load_script):
    """#224: an adjustment writes into a skill's directory; the skill itself is untouched."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw, proj, manifest = _mcp_index_shaped(tmp_path, bl)

    result = drift.compare(fw, manifest, target=proj)

    assert result["locallyModified"] == []
    assert result["changed"] == []


def test_editing_the_skill_itself_is_still_a_local_modification(tmp_path, load_script):
    """The exclusion is scoped to the adjustment's own path, not to the directory."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("engine/badger_lib.py")
    fw, proj, manifest = _mcp_index_shaped(tmp_path, bl)
    edited = proj / ".ai-badger" / "skills" / "mcp-index" / "scripts" / "mcp_index.py"
    edited.write_text("print('locally improved')\n", encoding="utf-8")

    result = drift.compare(fw, manifest, target=proj)

    assert result["locallyModified"] == ["features/common/skills/mcp-index"]
