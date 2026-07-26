"""Tests for features/hermes/adjustments/adjust_hooks.py: user-scope plugin install.

Stage 4 of docs/design/hermes-learned-skills-sync-impl-plan.md. Hermes loads plugins only
from ~/.hermes/plugins/, so the scaffold must install there (research C5). Kept out of
test_scaffold.py, which is already at pylint's module-length limit.
"""
from __future__ import annotations

from unittest.mock import patch

PLUGIN_FILES = ("ai_badger_hooks.py", "learned_skills_sync.py")


def _config(agents) -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": agents,
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _adjust_context(root, target, agents) -> dict:
    return {
        "framework_root": root,
        "config": _config(agents),
        "feature_dir": root / "features" / "hermes" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": [],
        "index": {},
    }


def _framework_hook(root, name):
    return (root / "features" / "common" / "hooks" / name).read_text(encoding="utf-8")


def test_scaffold_installs_hermes_plugin_to_user_dir(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(["hermes"]),
                               skills=["task"], install=False)
    with patch("pathlib.Path.home", return_value=home):
        result = scaf.run(generated_at="2026-07-26T00:00:00Z")

    plugins = home / ".hermes" / "plugins"
    for name in PLUGIN_FILES:
        assert (plugins / name).read_text(encoding="utf-8") == _framework_hook(root, name)

    hook_notes = [n for n in result["notes"] if "hooks" in n and "hermes" in n]
    assert any(".hermes/plugins" in n for n in hook_notes), hook_notes
    assert not any("failed" in n.lower() for n in hook_notes), hook_notes


def test_scaffold_refreshes_stale_hermes_plugin(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    plugins = home / ".hermes" / "plugins"
    plugins.mkdir(parents=True)
    for name in PLUGIN_FILES:
        (plugins / name).write_text("# stale copy\n", encoding="utf-8")

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(["hermes"]),
                               skills=["task"], install=False)
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-26T00:00:00Z")

    for name in PLUGIN_FILES:
        assert (plugins / name).read_text(encoding="utf-8") == _framework_hook(root, name)


def test_scaffold_skips_hermes_plugin_when_hermes_not_an_agent(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(["claude"]),
                               skills=["task"], install=False)
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-26T00:00:00Z")

    assert not (home / ".hermes" / "plugins").exists()


def test_adjust_hooks_refuses_when_hermes_not_in_agents(tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        result = adjust_hooks.adjust(_adjust_context(root, target, ["claude"]))

    assert result["applied"] is False
    assert result["files"] == []
    assert not (home / ".hermes").exists()
    assert not (target / ".ai-badger" / "hooks").exists()


def test_adjust_hooks_reports_user_scope_install_in_notes(tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    home = tmp_path / "home"
    home.mkdir()

    with patch("pathlib.Path.home", return_value=home):
        result = adjust_hooks.adjust(_adjust_context(root, target, ["hermes"]))

    assert result["applied"] is True
    assert ".hermes/plugins" in result["notes"]
    for name in PLUGIN_FILES:
        assert name in result["notes"]
        assert (home / ".hermes" / "plugins" / name).is_file()
