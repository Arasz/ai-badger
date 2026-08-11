"""Tests for skills/den-refresh/scripts/refresh.py: framework-update orchestrator.

refresh.py wraps drift detection + re-scaffold into one script that pulls
framework updates into an already-scaffolded project. Tests cover:

- Up-to-date: no drift → reports clean, exits 0
- Drift detected → re-scaffolds with existing config, reports changes
- Preserves seed-once files across re-scaffold
- Error on missing config/manifest
- Error on invalid config
- Agent files (HERMES.md, CLAUDE.md) refreshed on re-scaffold
"""

from __future__ import annotations

import json
import shutil

from scaffold_helpers import _config
from conftest import _test_write


def _write_config(target, **overrides):
    """Write a minimal valid config.json to target/.ai-badger/."""
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.3.0",
        "project": {"name": "test-proj", "summary": "A test project", "domain": "testing"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    config.update(overrides)
    _test_write(aib / "config.json", json.dumps(config), encoding="utf-8")
    return config


def _write_manifest(target, entries, version="0.3.0"):
    """Write a manifest.json to target/.ai-badger/."""
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    manifest = {
        "$schema": "../schemas/manifest.schema.json",
        "frameworkVersion": version,
        "frameworkCommit": None,
        "frameworkDirty": False,
        "generatedAt": "2026-07-22T00:00:00Z",
        "agents": ["claude"],
        "skillScope": "default",
        "entries": entries,
    }
    _test_write(aib / "manifest.json", json.dumps(manifest), encoding="utf-8")
    return manifest


def _make_fw_file(fw, relpath, content="framework content v1\n"):
    """Create a framework feature file at relpath under fw."""
    p = fw / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    _test_write(p, content, encoding="utf-8")
    return p


def _write_fw_index(fw, version="0.3.0"):
    """Write a minimal index.json to a mock framework so the Scaffolder can read it."""
    index = {
        "$schema": "./schemas/index.schema.json",
        "frameworkVersion": version,
        "stacks": {
            "common": {
                "invariants": [
                    {"name": "tdd", "path": "features/common/invariants/tdd.md"},
                ],
                "templates": [
                    {"name": "CLAUDE.md.tmpl", "path": "features/common/templates/CLAUDE.md.tmpl"},
                    {"name": "HERMES.md.tmpl", "path": "features/common/templates/HERMES.md.tmpl"},
                    {"name": "state.json", "path": "features/common/templates/state.json"},
                ],
            },
            "dotnet": {
                "personas": [],
                "invariants": [],
                "instructions": [],
            },
        },
    }
    _test_write(fw / "index.json", json.dumps(index), encoding="utf-8")


# --------------------------------------------------------------------- up-to-date (no drift)
def test_refresh_reports_up_to_date_when_no_drift(tmp_path, load_script, root):
    """When the scaffolded project matches the framework, refresh reports up-to-date and
    exits 0."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    # Create a minimal mock framework with one invariant
    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    _test_write(fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n", encoding="utf-8")
    src = _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    _write_fw_index(fw)

    # We need badger_lib from the test framework, not the mock
    bl = load_script("engine/badger_lib.py")
    entry_hash = bl.sha256_file(src)

    proj = tmp_path / "proj"
    _write_config(proj, frameworkVersion="0.3.0")
    _write_manifest(proj, [{
        "feature": "invariants", "stack": "common", "name": "tdd",
        "source": "features/common/invariants/tdd.md",
        "target": ".ai-badger/invariants/tdd.md",
        "frameworkVersion": "0.3.0", "hash": entry_hash,
    }])

    # Also write the actual file in the project (so manifest hash matches)
    (proj / ".ai-badger" / "invariants").mkdir(parents=True)
    _test_write(proj / ".ai-badger" / "invariants" / "tdd.md", "- TDD is mandatory.\n", encoding="utf-8")

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0


# ------------------------------------------------------------------- drift → re-scaffold
def test_refresh_detects_drift_and_re_scaffolds(tmp_path, load_script, root, make_scaffolder):
    """When framework content differs from scaffold, refresh re-scaffolds and reports changes."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    # Minimal template so scaffold works
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    _test_write(fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n", encoding="utf-8")
    _test_write(fw / "features" / "common" / "templates" / "HERMES.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n", encoding="utf-8")

    src = _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v1).\n")
    _write_fw_index(fw)

    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")

    # Scaffold the project from the mock framework
    scaf = make_scaffolder(root=fw, target=proj, config=config, skills=[])
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # Verify initial content
    tdd_path = proj / ".ai-badger" / "invariants" / "tdd.md"
    assert tdd_path.exists()
    assert "v1" in tdd_path.read_text(encoding="utf-8")

    # Now modify the framework file (simulate an upstream update)
    _test_write(src, "- TDD is mandatory (v2 — updated upstream).\n", encoding="utf-8")

    # Run refresh
    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    # Project should now have the updated content
    updated = tdd_path.read_text(encoding="utf-8")
    assert "v2" in updated


# ---------------------------------------------------------------------- seed-once preservation
def test_refresh_preserves_seed_once_files(tmp_path, load_script, root, make_scaffolder):
    """Seed-once files (state.json) must survive a refresh re-scaffold."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    _test_write(fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n", encoding="utf-8")
    _test_write(fw / "features" / "common" / "templates" / "HERMES.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n", encoding="utf-8")
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    # Also need state.json template for seed-once
    (fw / "features" / "common" / "templates" / "state.json").parent.mkdir(parents=True, exist_ok=True)
    _test_write(fw / "features" / "common" / "templates" / "state.json", '{"tasks": [], "lastUpdated": null}\n', encoding="utf-8")
    _write_fw_index(fw)

    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")

    scaf = make_scaffolder(root=fw, target=proj, config=config, skills=[])
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # Mutate state.json (project-owned data)
    state_path = proj / ".ai-badger" / "state.json"
    mutated = {"tasks": [{"id": 1, "title": "my custom task"}], "lastUpdated": "2026-07-22"}
    _test_write(state_path, json.dumps(mutated), encoding="utf-8")

    # Modify a framework file to trigger drift
    src = fw / "features" / "common" / "invariants" / "tdd.md"
    _test_write(src, "- TDD is mandatory (updated).\n", encoding="utf-8")

    # Run refresh
    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    # State must survive
    assert json.loads(state_path.read_text(encoding="utf-8")) == mutated


# ------------------------------------------------------------------- prerequisite errors
def test_refresh_errors_when_no_config(tmp_path, load_script):
    """Refresh on a non-scaffolded dir must error with a clear message."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    proj = tmp_path / "proj"
    proj.mkdir()

    rc = refresh.main(["--target", str(proj), "--root", str(tmp_path / "fw")])

    assert rc == 2


def test_refresh_errors_when_no_manifest(tmp_path, load_script):
    """Config without manifest means the project was never fully scaffolded."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")

    proj = tmp_path / "proj"
    _write_config(proj)  # config exists, but no manifest

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 2


# --------------------------------------------------------------------- hermes agent refresh
def test_refresh_re_scaffolds_hermes_agent_files(tmp_path, load_script, root, make_scaffolder):
    """When a project has hermes as a detected agent, refresh must update HERMES.md."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    _test_write(fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n", encoding="utf-8")
    _test_write(fw / "features" / "common" / "templates" / "HERMES.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Hermes-specific guidance\n\nSkills: {{STACKS}}\n", encoding="utf-8")
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v1).\n")

    # hermes scaffolding.json + template symlink
    (fw / "features" / "hermes").mkdir(parents=True)
    _test_write(fw / "features" / "hermes" / "scaffolding.json", json.dumps({
        "agent": "hermes",
        "files": [{
            "source": "templates/HERMES.md.tmpl",
            "target": "HERMES.md",
            "managed": True,
            "template": True,
            "aibCopy": "HERMES.md",
            "alsoTarget": ".hermes.md",
        }],
    }), encoding="utf-8")
    (fw / "features" / "hermes" / "templates").mkdir(parents=True)
    # Copy the template instead of symlink (tmp_path symlinks can be tricky)
    _test_write(fw / "features" / "hermes" / "templates" / "HERMES.md.tmpl", (fw / "features" / "common" / "templates" / "HERMES.md.tmpl").read_text(encoding="utf-8"), encoding="utf-8")
    # Also add scaffolding schema
    shutil.copyfile(root / "schemas" / "scaffolding.schema.json",
                    fw / "schemas" / "scaffolding.schema.json")

    _write_fw_index(fw)

    proj = tmp_path / "proj"
    config = _write_config(proj,
                           frameworkVersion="0.3.0",
                           stacks=["dotnet"],
                           agents=["claude", "hermes"])

    scaf = make_scaffolder(root=fw, target=proj, config=config, skills=[])
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # HERMES.md should exist
    hermes_path = proj / "HERMES.md"
    assert hermes_path.exists()
    assert "Hermes-specific guidance" in hermes_path.read_text(encoding="utf-8")

    # Modify the HERMES.md template to simulate upstream change
    _test_write(fw / "features" / "common" / "templates" / "HERMES.md.tmpl", "# {{PROJECT_NAME}} (v2)\n\n{{PROJECT_SUMMARY}}\n\n## Hermes-specific guidance\n\nSkills: {{STACKS}}\n", encoding="utf-8")
    # Also update the hermes feature's copy of the template
    _test_write(fw / "features" / "hermes" / "templates" / "HERMES.md.tmpl", "# {{PROJECT_NAME}} (v2)\n\n{{PROJECT_SUMMARY}}\n\n## Hermes-specific guidance\n\nSkills: {{STACKS}}\n", encoding="utf-8")
    # Also modify an invariant to trigger drift detection
    src = fw / "features" / "common" / "invariants" / "tdd.md"
    _test_write(src, "- TDD is mandatory (v2).\n", encoding="utf-8")

    # Run refresh
    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    # HERMES.md should be updated
    updated = hermes_path.read_text(encoding="utf-8")
    assert "(v2)" in updated


# ------------------------------------------------- version-only drift
def test_refresh_re_scaffolds_and_advances_both_stamps_when_only_the_version_moved(
    tmp_path, load_script, root
):
    """A version bump alone is drift: it is rendered into every generated file (#110).

    config.frameworkVersion advances, and it advances because a re-scaffold rewrote the
    manifest — never ahead of it, which is what made a stale scaffold read as green."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")

    # Framework at v0.4.0 (version bumped, but same file content)
    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.4.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    _test_write(fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n", encoding="utf-8")
    src = _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    _write_fw_index(fw, version="0.4.0")

    entry_hash = bl.sha256_file(src)

    # Project scaffolded at v0.3.0 — same file content, no drift
    proj = tmp_path / "proj"
    _write_config(proj, frameworkVersion="0.3.0")
    _write_manifest(proj, [{
        "feature": "invariants", "stack": "common", "name": "tdd",
        "source": "features/common/invariants/tdd.md",
        "target": ".ai-badger/invariants/tdd.md",
        "frameworkVersion": "0.3.0", "hash": entry_hash,
    }], version="0.3.0")
    (proj / ".ai-badger" / "invariants").mkdir(parents=True)
    _test_write(proj / ".ai-badger" / "invariants" / "tdd.md", "- TDD is mandatory.\n", encoding="utf-8")

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    config = json.loads((proj / ".ai-badger" / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((proj / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    assert config["frameworkVersion"] == "0.4.0"
    assert manifest["frameworkVersion"] == config["frameworkVersion"], (
        "config must never certify a version the manifest and the generated files "
        "were not written by"
    )


# ------------------------------------------------- hermes namespace relink
def test_refresh_relinks_hermes_skills(tmp_path, load_script, root):
    """Refresh re-links the hermes namespace: new skills linked, stale links dropped,
    foreign entries preserved."""
    from unittest.mock import patch

    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    _test_write(fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n", encoding="utf-8")
    src = _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    _write_fw_index(fw)

    proj = tmp_path / "proj"
    _write_config(proj, frameworkVersion="0.3.0", agents=["claude", "hermes"])
    _write_manifest(proj, [{
        "feature": "invariants", "stack": "common", "name": "tdd",
        "source": "features/common/invariants/tdd.md",
        "target": ".ai-badger/invariants/tdd.md",
        "frameworkVersion": "0.3.0", "hash": bl.sha256_file(src),
    }])
    (proj / ".ai-badger" / "invariants").mkdir(parents=True)
    _test_write(proj / ".ai-badger" / "invariants" / "tdd.md", "- TDD is mandatory.\n", encoding="utf-8")
    added = proj / ".ai-badger" / "skills" / "added-skill"
    added.mkdir(parents=True)
    _test_write(added / "SKILL.md", "# added\n", encoding="utf-8")

    home = tmp_path / "hermes-home"
    namespace = home / ".hermes" / "skills" / "test-proj"
    namespace.mkdir(parents=True)
    stale = namespace / "gone-skill"
    stale.symlink_to("../../../../proj/.ai-badger/skills/gone-skill")
    foreign = namespace / "agent-skill-discovery"
    foreign.mkdir()
    _test_write(foreign / "SKILL.md", "# hermes-authored\n", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    assert (namespace / "added-skill").is_symlink()
    assert ((namespace / "added-skill").resolve() / "SKILL.md").exists()
    assert not stale.is_symlink()
    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == "# hermes-authored\n"


def test_backup_is_taken_even_when_the_transition_is_not_breaking(tmp_path, load_script, root):
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    aib.mkdir(parents=True)
    # Same version both sides: no boundary is crossed, whatever BREAKING_VERSIONS holds.
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    _test_write(aib / "config.json", json.dumps({"frameworkVersion": current}), encoding="utf-8")
    _test_write(aib / "state.json", '{"mine": true}\n', encoding="utf-8")

    result = refresh.check_breaking_and_backup(root, target)

    assert result["backupPath"]
    assert not result["isBreaking"]
    backup = target / ".ai-badger.bckp"
    assert (backup / "state.json").read_text(encoding="utf-8") == '{"mine": true}\n'


def test_the_backup_skips_a_nested_git_checkout(tmp_path, load_script, root):
    """A task worktree under .ai-badger/ is a whole second checkout; copying it is not a backup.

    The skip is about the nested `.git`, not about the directory's name — an ordinary sibling
    beside the checkout is still backed up.
    """
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    aib.mkdir(parents=True)
    current = (root / "VERSION").read_text(encoding="utf-8").strip()
    _test_write(aib / "config.json", json.dumps({"frameworkVersion": current}), encoding="utf-8")
    checkout = aib / "worktrees" / "issue-42"
    checkout.mkdir(parents=True)
    _test_write(checkout / ".git", "gitdir: /elsewhere/.git/worktrees/issue-42\n", encoding="utf-8")
    _test_write(checkout / "README.md", "a whole repo\n", encoding="utf-8")
    ordinary = aib / "worktrees" / "notes"
    ordinary.mkdir()
    _test_write(ordinary / "keep.md", "kept\n", encoding="utf-8")

    refresh.check_breaking_and_backup(root, target)

    backup = target / ".ai-badger.bckp"
    assert (backup / "config.json").exists()
    assert not (backup / "worktrees" / "issue-42").exists(), "the backup copied a git checkout"
    assert (backup / "worktrees" / "notes" / "keep.md").read_text(encoding="utf-8") == "kept\n"


# ------------------------------------------------- delivering a newly-added catalog skill
def _mock_fw_with_skills(fw, root, skill_names):
    """Build a mock framework whose common stack ships `skill_names` and one invariant."""
    fw.mkdir(exist_ok=True)
    _test_write(fw / "VERSION", "0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir(exist_ok=True)
    _test_write(fw / "schemas" / "config.schema.json", (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
    tdir = fw / "features" / "common" / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    _test_write(tdir / "CLAUDE.md.tmpl", "# {{PROJECT_NAME}}\n", encoding="utf-8")
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    for name in skill_names:
        sd = fw / "features" / "common" / "skills" / name
        sd.mkdir(parents=True, exist_ok=True)
        _test_write(sd / "SKILL.md", f"---\nname: {name}\nscope: default\n---\n# {name}\n", encoding="utf-8")
    index = {
        "$schema": "./schemas/index.schema.json",
        "frameworkVersion": "0.3.0",
        "stacks": {
            "common": {
                "invariants": [{"name": "tdd", "path": "features/common/invariants/tdd.md"}],
                "skills": [{"name": n, "path": f"features/common/skills/{n}"}
                           for n in skill_names],
                "templates": [{"name": "CLAUDE.md.tmpl",
                               "path": "features/common/templates/CLAUDE.md.tmpl"}],
            },
            "dotnet": {"personas": [], "invariants": [], "instructions": []},
        },
    }
    _test_write(fw / "index.json", json.dumps(index), encoding="utf-8")


def test_refresh_delivers_a_skill_added_to_the_catalog_after_the_project_was_scaffolded(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """The whole-fix regression: detection sees common, the report says so, and it lands."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    assert not (proj / ".ai-badger" / "skills" / "call-behaviorist").exists()

    # The framework ships a new common skill; the project's manifest knows nothing of it.
    _mock_fw_with_skills(fw, root, ["task", "call-behaviorist"])

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert (proj / ".ai-badger" / "skills" / "call-behaviorist" / "SKILL.md").exists()
    assert "call-behaviorist" in [i["name"] for i in report["drift"]["newItems"]]
    assert "call-behaviorist" in report["scaffold"]["refreshedSkills"]


def test_refresh_delivers_a_skill_the_framework_changed_after_the_project_was_scaffolded(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """End to end for #110: framework ahead → re-scaffold → the vendored copy matches it."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")

    upstream = fw / "features" / "common" / "skills" / "task" / "SKILL.md"
    _test_write(upstream, "# task\n\nupstream v2\n", encoding="utf-8")

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert "features/common/skills/task" in report["drift"]["changed"]
    assert report["reScaffolded"]
    vendored = proj / ".ai-badger" / "skills" / "task" / "SKILL.md"
    assert vendored.read_text(encoding="utf-8") == upstream.read_text(encoding="utf-8")


def test_refresh_reports_new_catalog_items_it_used_to_compute_and_discard(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """newItems gated the re-scaffold but never reached the operator."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")

    refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert report["drift"]["newItems"] == []


def test_refresh_keeps_scaffolding_skills_recorded_only_in_the_manifest(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """The union is manifest-first: a skill already installed must not be dropped."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task", "auto-wm"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task", "auto-wm"]).run(
                            generated_at="2026-07-22T00:00:00Z")
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v2).\n")

    refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert (proj / ".ai-badger" / "skills" / "auto-wm" / "SKILL.md").exists()
    assert "auto-wm" in report["scaffold"]["refreshedSkills"]


def test_refresh_does_not_report_per_file_extension_entries_as_refreshed_skills(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """Manifest skill entries include `<skill>/extensions/<file>` rows; those are not skills."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    ext = fw / "features" / "common" / "skills" / "task" / "extensions"
    ext.mkdir(parents=True)
    _test_write(ext / "dotnet.md", "# dotnet extension\n", encoding="utf-8")
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v2).\n")

    refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert all("/" not in name for name in report["scaffold"]["refreshedSkills"])


def test_refresh_does_not_deliver_a_skill_the_project_excluded(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """The union hands every default-scope skill over; the exclusion is what stops delivery."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task", "call-behaviorist"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0",
                           exclude={"skills": ["call-behaviorist"]})
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v2).\n")

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert not (proj / ".ai-badger" / "skills" / "call-behaviorist").exists()
    assert "call-behaviorist" not in report["scaffold"]["refreshedSkills"]
    assert "call-behaviorist" not in [i["name"] for i in report["drift"]["newItems"]]


# ------------------------------------------------------- competing framework copies (#109)
def _framework_tree(path, version):
    """A directory the framework-root predicate accepts, carrying a VERSION."""
    for name in ("schemas", "features", "engine"):
        (path / name).mkdir(parents=True, exist_ok=True)
    _test_write(path / "engine" / "badger_lib.py", "", encoding="utf-8")
    _test_write(path / "VERSION", version + "\n", encoding="utf-8")
    return path


def _scaffolded_project(tmp_path, root, make_scaffolder):
    """A mock framework and a project already scaffolded from it, with no drift between them."""
    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    return fw, proj


def _competing_home(tmp_path, monkeypatch, cache_version=None, plugin_version=None):
    """A `$HOME` holding ai-badger's own cache and/or Claude Code's plugin cache."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    made = {}
    if cache_version:
        made["cache"] = _framework_tree(home / ".ai-badger" / "framework", cache_version)
    if plugin_version:
        made["plugin"] = _framework_tree(
            home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger" / plugin_version,
            plugin_version)
    return made


def test_refresh_reports_a_competing_framework_cache_and_leaves_it_on_disk(
        tmp_path, load_script, root, monkeypatch, capsys, make_scaffolder):
    """Detect and report is the default: deleting from a home directory is not routine (#109)."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw, proj = _scaffolded_project(tmp_path, root, make_scaffolder)
    made = _competing_home(tmp_path, monkeypatch, cache_version="0.13.0")

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    cache_report = report["frameworkCopies"]["cache"]
    assert cache_report["status"] == "reported"
    assert cache_report["path"] == str(made["cache"]) and cache_report["version"] == "0.13.0"
    assert "--prune-cache" in cache_report["detail"]
    assert (made["cache"] / "VERSION").is_file()


def test_refresh_removes_the_cache_only_when_prune_cache_is_asked_for(
        tmp_path, load_script, root, monkeypatch, capsys, make_scaffolder):
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw, proj = _scaffolded_project(tmp_path, root, make_scaffolder)
    made = _competing_home(tmp_path, monkeypatch, cache_version="0.13.0")

    rc = refresh.main(["--target", str(proj), "--root", str(fw), "--prune-cache"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["frameworkCopies"]["cache"]["status"] == "removed"
    assert not made["cache"].exists()


def test_refresh_never_prunes_claude_codes_plugin_cache(
        tmp_path, load_script, root, monkeypatch, capsys, make_scaffolder):
    """ai-badger only ever reads that path; 76 MB of another tool's cache is not ours (#109)."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw, proj = _scaffolded_project(tmp_path, root, make_scaffolder)
    made = _competing_home(tmp_path, monkeypatch, cache_version="0.13.0",
                           plugin_version="0.36.2")

    refresh.main(["--target", str(proj), "--root", str(fw), "--prune-cache"])
    report = json.loads(capsys.readouterr().out)

    assert (made["plugin"] / "VERSION").is_file()
    competing = {c["path"]: c for c in report["frameworkCopies"]["competing"]}
    assert competing[str(made["plugin"])]["owner"] == "claude-code"
    assert competing[str(made["plugin"])]["prunable"] is False


def test_refresh_says_nothing_about_copies_when_only_one_tree_exists(
        tmp_path, load_script, root, monkeypatch, capsys, make_scaffolder):
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw, proj = _scaffolded_project(tmp_path, root, make_scaffolder)
    _competing_home(tmp_path, monkeypatch)

    refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert "frameworkCopies" not in report


def test_refresh_re_delivers_a_skill_whose_exclusion_was_removed(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """Un-excluding is deleting the line: the next refresh delivers the skill fresh."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task", "call-behaviorist"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0",
                           exclude={"skills": ["call-behaviorist"]})
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    _write_config(proj, frameworkVersion="0.3.0")

    refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert (proj / ".ai-badger" / "skills" / "call-behaviorist" / "SKILL.md").exists()
    assert "call-behaviorist" in report["scaffold"]["refreshedSkills"]


def test_a_project_without_hermes_gets_no_hermes_link_report(
        tmp_path, load_script, root, capsys, make_scaffolder):
    """The report names hermes links only when there are some (#129 return-shape change)."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

    fw = tmp_path / "fw"
    _mock_fw_with_skills(fw, root, ["task"])
    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")
    make_scaffolder(root=fw, target=proj, config=config, skills=["task"]).run(
        generated_at="2026-07-22T00:00:00Z")
    _mock_fw_with_skills(fw, root, ["task", "call-behaviorist"])

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert "call-behaviorist" in report["scaffold"]["refreshedSkills"]
    assert "hermesSkillLinks" not in report, (
        "a claude-only project has no hermes namespace, so the report must not carry the key"
    )


# ------------------------------------------------------- issue #128: a config edit is drift
# These tests scaffold from the real framework (the `root` fixture), the same way
# tests/test_config_exclude.py does, so the exclusion/rendering machinery under test is the
# real thing rather than a hand-built mock.
def _edit_config(target, **updates):
    """Patch target/.ai-badger/config.json in place — a hand edit, not a re-scaffold."""
    config_path = target / ".ai-badger" / "config.json"
    on_disk = json.loads(config_path.read_text(encoding="utf-8"))
    on_disk.update(updates)
    _test_write(config_path, json.dumps(on_disk), encoding="utf-8")
    return on_disk


def _only_config_changed(report):
    """Every drift signal that predates #128 must be quiet, or the assertion proves nothing."""
    assert report["drift"]["newItems"] == []
    assert report["drift"]["changed"] == []
    assert report["drift"]["removed"] == []
    assert report["drift"]["orphaned"] == []
    assert report["drift"]["versionChanged"] is None
    assert report["newStacks"] == []
    assert report["breakingChange"]["isBreaking"] is False


def test_refresh_applies_an_exclusion_added_after_the_last_refresh(
        load_script, root, make_scaffolder, capsys):
    """The issue's own reproduction: an exclusion added after the fact must be self-executing."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")
    assert (target / ".ai-badger" / "skills" / "call-behaviorist").is_dir()
    assert (target / ".claude" / "skills" / "call-behaviorist").is_symlink()

    _edit_config(target, exclude={"skills": ["call-behaviorist"]})

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    _only_config_changed(report)
    assert report["drift"]["configChanged"] is not None
    assert report["reScaffolded"] is True
    assert "call-behaviorist" not in report["scaffold"]["refreshedSkills"]
    assert not (target / ".claude" / "skills" / "call-behaviorist").exists()


def test_refresh_applies_an_invariant_exclusion_and_stops_rendering_it(
        load_script, root, make_scaffolder, capsys):
    """A declined invariant must disappear from disk and from the rendered CLAUDE.md."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")
    assert (target / ".ai-badger" / "invariants" / "tdd-mandatory.md").is_file()
    assert "TDD is mandatory" in (target / "CLAUDE.md").read_text(encoding="utf-8")

    _edit_config(target, exclude={"invariants": ["tdd-mandatory"]})

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    _only_config_changed(report)
    assert report["drift"]["configChanged"] is not None
    assert report["reScaffolded"] is True
    assert not (target / ".ai-badger" / "invariants" / "tdd-mandatory.md").exists()
    assert "TDD is mandatory" not in (target / "CLAUDE.md").read_text(encoding="utf-8")


def test_refresh_applies_a_commands_only_config_edit(load_script, root, make_scaffolder, capsys):
    """Not `exclude`-shaped: any config-only edit — here `commands` — must self-execute."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    target = make_scaffolder.target
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"], commands={"test": "pytest"})
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=config, skills=skills).run(generated_at="2026-07-28T00:00:00Z")
    assert "pytest -q" not in (target / "CLAUDE.md").read_text(encoding="utf-8")

    _edit_config(target, commands={"test": "pytest -q"})

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    _only_config_changed(report)
    assert report["drift"]["configChanged"] is not None
    assert report["reScaffolded"] is True
    assert "pytest -q" in (target / "CLAUDE.md").read_text(encoding="utf-8")


def test_refresh_does_not_re_scaffold_when_nothing_changed(load_script, root, make_scaffolder, capsys):
    """Anti-loop lock: an untouched project must report no drift, twice in a row."""
    bl = load_script("engine/badger_lib.py")
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    target = make_scaffolder.target
    # Every default-scope skill, so den-refresh's manifest-union-with-catalog-defaults
    # (#104) finds nothing new on its own — only the fix under test may cause drift here.
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    refresh.main(["--target", str(target), "--root", str(root)])
    first = json.loads(capsys.readouterr().out)
    refresh.main(["--target", str(target), "--root", str(root)])
    second = json.loads(capsys.readouterr().out)

    assert first["reScaffolded"] is False
    assert second["reScaffolded"] is False


def test_refresh_re_scaffolds_once_when_the_manifest_predates_the_config_hash(
        load_script, root, make_scaffolder, capsys):
    """Migration (§3): an absent configHash is drift exactly once, then self-limiting."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    manifest_path = target / ".ai-badger" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["configHash"]
    _test_write(manifest_path, json.dumps(manifest), encoding="utf-8")

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    first = json.loads(capsys.readouterr().out)
    assert rc == 0
    _only_config_changed(first)
    assert first["drift"]["configChanged"]["recorded"] is None
    assert first["reScaffolded"] is True

    refresh.main(["--target", str(target), "--root", str(root)])
    second = json.loads(capsys.readouterr().out)
    assert second["reScaffolded"] is False


def test_refresh_force_re_scaffolds_when_nothing_has_changed(load_script, root, make_scaffolder, capsys):
    """`--force` keeps the documented recovery path inside den-refresh."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    rc = refresh.main(["--target", str(target), "--root", str(root), "--force"])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    _only_config_changed(report)
    assert report["drift"]["configChanged"] is None
    assert report["forced"] is True
    # The observable: a re-scaffold actually ran. reScaffolded alone would pass even if
    # --force never reached the gate.
    assert "scaffold" in report
    assert report["reScaffolded"] is True


# ------------------------------------------------------- issue #134: the scaffold detects itself
def test_refresh_does_not_report_a_configured_agent_as_a_new_stack(
        load_script, root, make_scaffolder, capsys):
    """`config.agents` names a catalog stack too (#119); the caller must consult it, not just
    `config.stacks`, or a project that declared `claude` is told `claude` is new."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(stacks=["python"], agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["newStacks"] == []


def test_refresh_reports_no_drift_on_a_freshly_scaffolded_project(
        load_script, root, make_scaffolder, capsys):
    """The headline regression: a project fresh off the scaffold must not re-scaffold forever —
    its own output (CLAUDE.md, the framework's .mjs/.py scripts) must not self-detect."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(stacks=["python"], agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["newStacks"] == []
    assert report["reScaffolded"] is False


def test_refresh_stays_quiet_across_three_consecutive_refreshes(
        load_script, root, make_scaffolder, capsys):
    """Three refreshes in a row on an untouched project must all be quiet — the backup exists
    (so this proves the backup is ignored, not merely absent) and never forces re-scaffolding."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(stacks=["python"], agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    reports = []
    for _ in range(3):
        refresh.main(["--target", str(target), "--root", str(root)])
        reports.append(json.loads(capsys.readouterr().out))

    assert (target / ".ai-badger.bckp").is_dir()
    assert [r["reScaffolded"] for r in reports] == [False, False, False]
    assert [r["newStacks"] for r in reports] == [[], [], []]


def test_refresh_reports_a_hand_authored_stack_but_does_not_re_scaffold_for_it(
        load_script, root, make_scaffolder, capsys):
    """A genuine unconfigured stack is still reported — `newStacks` stays useful — but it must
    not force a re-scaffold: the re-scaffold would run the same config and deliver nothing new."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    bl = load_script("engine/badger_lib.py")
    target = make_scaffolder.target
    skills = bl.default_skills_in(root / "features" / "common" / "skills")
    make_scaffolder(config=_config(stacks=["python"], agents=["claude"]), skills=skills).run(
        generated_at="2026-07-28T00:00:00Z")

    _test_write(target / "tsconfig.json", "{}\n", encoding="utf-8")
    src = target / "src"
    src.mkdir()
    _test_write(src / "app.ts", "export {};\n", encoding="utf-8")

    rc = refresh.main(["--target", str(target), "--root", str(root)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert sorted(report["newStacks"]) == ["node", "ts"]
    assert report["reScaffolded"] is False
    assert report["drift"]["newItems"] == []
    assert report["drift"]["changed"] == []
    assert report["drift"]["removed"] == []
    assert report["drift"]["orphaned"] == []
    assert report["drift"]["versionChanged"] is None
    assert report["breakingChange"]["isBreaking"] is False


# -------------------------------------------------------------- skills nobody uses here (#172)
def _transcript_store(home, project, records):
    """A Claude Code transcript for `project` under a fake `$HOME`, holding `records`."""
    mangled = "".join(c if c.isalnum() else "-" for c in str(project))
    store = home / ".claude" / "projects" / mangled
    store.mkdir(parents=True, exist_ok=True)
    _test_write(store / "session.jsonl", "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return store


def _skill_invocation(skill, project):
    return {"type": "assistant", "timestamp": "2026-07-20T10:00:00.000Z", "cwd": str(project),
            "message": {"content": [{"type": "tool_use", "name": "Skill",
                                     "input": {"skill": skill}}]}}


def test_refresh_reports_which_delivered_skills_this_project_was_seen_using(
        tmp_path, load_script, root, monkeypatch, capsys, make_scaffolder):
    """The maintainer's own case: several skills scaffolded, one of them ever invoked."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw, proj = _scaffolded_project(tmp_path, root, make_scaffolder)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _transcript_store(home, proj, [_skill_invocation("task", proj)])

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    usage = report["skillUsage"]
    assert [e["skill"] for e in usage["used"]] == ["task"]
    assert usage["channels"]["invocation"] == "claude-transcripts"
    assert usage["limits"]


def test_refresh_recommends_nothing_when_no_channel_could_observe_a_skill(
        tmp_path, load_script, root, monkeypatch, capsys, make_scaffolder):
    """No transcript store and no audit records: say so, and propose no pruning."""
    refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")
    fw, proj = _scaffolded_project(tmp_path, root, make_scaffolder)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])
    report = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert report["skillUsage"]["unused"] == []
    assert report["skillUsage"]["hint"]
