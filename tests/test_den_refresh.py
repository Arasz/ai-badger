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
        "pluginScope": "default",
        "docs": {},
    }
    config.update(overrides)
    (aib / "config.json").write_text(json.dumps(config), encoding="utf-8")
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
        "pluginScope": "default",
        "entries": entries,
    }
    (aib / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _make_fw_file(fw, relpath, content="framework content v1\n"):
    """Create a framework feature file at relpath under fw."""
    p = fw / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
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
    (fw / "index.json").write_text(json.dumps(index), encoding="utf-8")


# --------------------------------------------------------------------- up-to-date (no drift)
def test_refresh_reports_up_to_date_when_no_drift(tmp_path, load_script, root):
    """When the scaffolded project matches the framework, refresh reports up-to-date and
    exits 0."""
    refresh = load_script("skills/den-refresh/scripts/refresh.py")
    # Create a minimal mock framework with one invariant
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    (fw / "schemas" / "config.schema.json").write_text(
        (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    (fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n",
        encoding="utf-8",
    )
    src = _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    _write_fw_index(fw)

    # We need badger_lib from the test framework, not the mock
    bl = load_script("scripts/badger_lib.py")
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
    (proj / ".ai-badger" / "invariants" / "tdd.md").write_text("- TDD is mandatory.\n", encoding="utf-8")

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0


# ------------------------------------------------------------------- drift → re-scaffold
def test_refresh_detects_drift_and_re_scaffolds(tmp_path, load_script, root):
    """When framework content differs from scaffold, refresh re-scaffolds and reports changes."""
    refresh = load_script("skills/den-refresh/scripts/refresh.py")
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")
    bl = load_script("scripts/badger_lib.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    (fw / "schemas" / "config.schema.json").write_text(
        (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Minimal template so scaffold works
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    (fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n",
        encoding="utf-8",
    )
    (fw / "features" / "common" / "templates" / "HERMES.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n",
        encoding="utf-8",
    )

    src = _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v1).\n")
    _write_fw_index(fw)

    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")

    # Scaffold the project from the mock framework
    scaf = scaffold.Scaffolder(root=fw, target=proj, config=config,
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # Verify initial content
    tdd_path = proj / ".ai-badger" / "invariants" / "tdd.md"
    assert tdd_path.exists()
    assert "v1" in tdd_path.read_text(encoding="utf-8")

    # Now modify the framework file (simulate an upstream update)
    src.write_text("- TDD is mandatory (v2 — updated upstream).\n", encoding="utf-8")

    # Run refresh
    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    # Project should now have the updated content
    updated = tdd_path.read_text(encoding="utf-8")
    assert "v2" in updated


# ---------------------------------------------------------------------- seed-once preservation
def test_refresh_preserves_seed_once_files(tmp_path, load_script, root):
    """Seed-once files (state.json) must survive a refresh re-scaffold."""
    refresh = load_script("skills/den-refresh/scripts/refresh.py")
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    (fw / "schemas" / "config.schema.json").write_text(
        (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    (fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n",
        encoding="utf-8",
    )
    (fw / "features" / "common" / "templates" / "HERMES.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n",
        encoding="utf-8",
    )
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory.\n")
    # Also need state.json template for seed-once
    (fw / "features" / "common" / "templates" / "state.json").parent.mkdir(parents=True, exist_ok=True)
    (fw / "features" / "common" / "templates" / "state.json").write_text(
        '{"tasks": [], "lastUpdated": null}\n', encoding="utf-8",
    )
    _write_fw_index(fw)

    proj = tmp_path / "proj"
    config = _write_config(proj, frameworkVersion="0.3.0")

    scaf = scaffold.Scaffolder(root=fw, target=proj, config=config,
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # Mutate state.json (project-owned data)
    state_path = proj / ".ai-badger" / "state.json"
    mutated = {"tasks": [{"id": 1, "title": "my custom task"}], "lastUpdated": "2026-07-22"}
    state_path.write_text(json.dumps(mutated), encoding="utf-8")

    # Modify a framework file to trigger drift
    src = fw / "features" / "common" / "invariants" / "tdd.md"
    src.write_text("- TDD is mandatory (updated).\n", encoding="utf-8")

    # Run refresh
    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    # State must survive
    assert json.loads(state_path.read_text(encoding="utf-8")) == mutated


# ------------------------------------------------------------------- prerequisite errors
def test_refresh_errors_when_no_config(tmp_path, load_script):
    """Refresh on a non-scaffolded dir must error with a clear message."""
    refresh = load_script("skills/den-refresh/scripts/refresh.py")
    proj = tmp_path / "proj"
    proj.mkdir()

    rc = refresh.main(["--target", str(proj), "--root", str(tmp_path / "fw")])

    assert rc == 2


def test_refresh_errors_when_no_manifest(tmp_path, load_script):
    """Config without manifest means the project was never fully scaffolded."""
    refresh = load_script("skills/den-refresh/scripts/refresh.py")
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.3.0\n", encoding="utf-8")

    proj = tmp_path / "proj"
    _write_config(proj)  # config exists, but no manifest

    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 2


# --------------------------------------------------------------------- hermes agent refresh
def test_refresh_re_scaffolds_hermes_agent_files(tmp_path, load_script, root):
    """When a project has hermes as a detected agent, refresh must update HERMES.md."""
    refresh = load_script("skills/den-refresh/scripts/refresh.py")
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")

    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "VERSION").write_text("0.3.0\n", encoding="utf-8")
    (fw / "schemas").mkdir()
    (fw / "schemas" / "config.schema.json").write_text(
        (root / "schemas" / "config.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    (fw / "features" / "common" / "templates" / "CLAUDE.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Invariants\n\n{{INVARIANTS}}\n",
        encoding="utf-8",
    )
    (fw / "features" / "common" / "templates" / "HERMES.md.tmpl").write_text(
        "# {{PROJECT_NAME}}\n\n{{PROJECT_SUMMARY}}\n\n## Hermes-specific guidance\n\nSkills: {{STACKS}}\n",
        encoding="utf-8",
    )
    _make_fw_file(fw, "features/common/invariants/tdd.md", "- TDD is mandatory (v1).\n")
    _write_fw_index(fw)

    proj = tmp_path / "proj"
    config = _write_config(proj,
                           frameworkVersion="0.3.0",
                           stacks=["dotnet"],
                           agents=["claude", "hermes"])

    scaf = scaffold.Scaffolder(root=fw, target=proj, config=config,
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-22T00:00:00Z")

    # HERMES.md should exist
    hermes_path = proj / "HERMES.md"
    assert hermes_path.exists()
    assert "Hermes-specific guidance" in hermes_path.read_text(encoding="utf-8")

    # Modify the HERMES.md template to simulate upstream change
    (fw / "features" / "common" / "templates" / "HERMES.md.tmpl").write_text(
        "# {{PROJECT_NAME}} (v2)\n\n{{PROJECT_SUMMARY}}\n\n## Hermes-specific guidance\n\nSkills: {{STACKS}}\n",
        encoding="utf-8",
    )
    # Also modify an invariant to trigger drift detection
    src = fw / "features" / "common" / "invariants" / "tdd.md"
    src.write_text("- TDD is mandatory (v2).\n", encoding="utf-8")

    # Run refresh
    rc = refresh.main(["--target", str(proj), "--root", str(fw)])

    assert rc == 0
    # HERMES.md should be updated
    updated = hermes_path.read_text(encoding="utf-8")
    assert "(v2)" in updated
