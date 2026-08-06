"""Tests for features/hermes/adjustments/adjust_hooks.py: user-scope plugin install.

Hermes loads plugins only from ~/.hermes/plugins/<name>/ as DIRECTORY plugins
(plugin.yaml + __init__.py with register(ctx), opt-in via plugins.enabled) — flat
.py drops are invisible to the loader. These tests pin the directory shape.
Kept out of test_scaffold.py, which is already at pylint's module-length limit.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR_NAME = "ai-badger"
USER_PLUGIN_FILES = ("ai_badger_hooks.py", "learned_skills_sync.py")
SHARED_SKILL_FILES = (
    ("commit-reminder", "commit_reminder.py"),
    ("commit-reminder", "impact_estimator.py"),
    ("ai-raccoon-memory", "memory_grade.py"),
)
RETRIEVAL_FILES = ("tokenizer.py", "bm25.py", "mcp_matcher.py")


def _skill_script(root, skill, name):
    return (root / "features" / "common" / "skills" / skill / "scripts"
            / name).read_text(encoding="utf-8")


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


def _plugin_dir(home) -> "Path":
    return home / ".hermes" / "plugins" / PLUGIN_DIR_NAME


def _run_adjust(adjust_hooks, tmp_path, root, agents=("hermes",)):
    target = tmp_path / "proj"
    home = tmp_path / "home"
    home.mkdir()
    with patch("pathlib.Path.home", return_value=home):
        result = adjust_hooks.adjust(_adjust_context(root, target, list(agents)))
    return result, target, home


def test_scaffold_installs_hermes_plugin_as_directory_plugin(tmp_path, root, make_scaffolder):
    home = tmp_path / "home"
    home.mkdir()

    scaf = make_scaffolder(config=_config(["hermes"]), skills=["task"])
    with patch("pathlib.Path.home", return_value=home):
        result = scaf.run(generated_at="2026-07-26T00:00:00Z")

    plugins = home / ".hermes" / "plugins"
    plugin = _plugin_dir(home)
    assert plugin.is_dir()
    for name in USER_PLUGIN_FILES:
        assert (plugin / name).read_text(encoding="utf-8") == _framework_hook(root, name)
    for name in ("plugin.yaml", "__init__.py"):
        assert (plugin / name).is_file()
    # No flat .py drops directly in ~/.hermes/plugins/ — those are invisible to Hermes.
    assert [p.name for p in plugins.iterdir() if p.is_file()] == []

    hook_notes = [n for n in result["notes"] if "hooks" in n and "hermes" in n]
    assert any(".hermes/plugins/ai-badger" in n for n in hook_notes), hook_notes
    assert not any("failed" in n.lower() for n in hook_notes), hook_notes


def test_scaffold_refreshes_stale_hermes_plugin(tmp_path, root, make_scaffolder):
    home = tmp_path / "home"
    plugin = _plugin_dir(home)
    plugin.mkdir(parents=True)
    for name in USER_PLUGIN_FILES:
        (plugin / name).write_text("# stale copy\n", encoding="utf-8")

    scaf = make_scaffolder(config=_config(["hermes"]), skills=["task"])
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-26T00:00:00Z")

    for name in USER_PLUGIN_FILES:
        assert (plugin / name).read_text(encoding="utf-8") == _framework_hook(root, name)


def test_scaffold_skips_hermes_plugin_when_hermes_not_an_agent(tmp_path, make_scaffolder):
    home = tmp_path / "home"
    home.mkdir()

    scaf = make_scaffolder(config=_config(["claude"]), skills=["task"])
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-26T00:00:00Z")

    assert not (home / ".hermes" / "plugins").exists()


def test_adjust_hooks_refuses_when_hermes_not_in_agents(tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    result, _, home = _run_adjust(adjust_hooks, tmp_path, root, agents=("claude",))

    assert result["applied"] is False
    assert result["files"] == []
    assert not (home / ".hermes").exists()
    assert not (tmp_path / "proj" / ".ai-badger" / "hooks").exists()


def test_adjust_hooks_reports_user_scope_install_in_notes(tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    result, _, home = _run_adjust(adjust_hooks, tmp_path, root)

    assert result["applied"] is True
    assert ".hermes/plugins/ai-badger" in result["notes"]
    for name in USER_PLUGIN_FILES:
        assert name in result["notes"]
        assert (_plugin_dir(home) / name).is_file()


def test_adjust_hooks_copies_shared_skill_modules_to_project_hooks_dir(
        tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    result, target, _ = _run_adjust(adjust_hooks, tmp_path, root)

    for skill, name in SHARED_SKILL_FILES:
        dst = target / ".ai-badger" / "hooks" / name
        assert dst.read_text(encoding="utf-8") == _skill_script(root, skill, name)


def test_adjust_hooks_copies_memory_grade_to_project_and_plugin_dirs(
        tmp_path, load_script, root):
    """The memory-grade sibling must land beside ai_badger_hooks.py in both destinations."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, target, home = _run_adjust(adjust_hooks, tmp_path, root)

    for dst in (target / ".ai-badger" / "hooks" / "memory_grade.py",
                _plugin_dir(home) / "memory_grade.py"):
        assert dst.read_text(encoding="utf-8") == _skill_script(
            root, "ai-raccoon-memory", "memory_grade.py")


def test_adjust_hooks_copies_shared_skill_modules_into_plugin_dir(
        tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)

    for skill, name in SHARED_SKILL_FILES:
        dst = _plugin_dir(home) / name
        assert dst.read_text(encoding="utf-8") == _skill_script(root, skill, name)


def test_adjust_hooks_still_copies_project_hooks_alongside_shared_skill_modules(
        tmp_path, load_script, root):
    """Generalizing the copy loop must not regress the pre-existing PROJECT_HOOKS copy."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    result, target, _ = _run_adjust(adjust_hooks, tmp_path, root)

    for name in adjust_hooks.PROJECT_HOOKS:
        dst = target / ".ai-badger" / "hooks" / name
        assert dst.read_text(encoding="utf-8") == _framework_hook(root, name)
    assert {name for _, name in SHARED_SKILL_FILES}.issubset({
        f.rsplit("/", 1)[-1] for f in result["files"]
    })


def _retrieval_module(root, name):
    return (root / "features" / "common" / "retrieval" / name).read_text(encoding="utf-8")


def test_adjust_hooks_copies_retrieval_modules_to_project_hooks_dir(
        tmp_path, load_script, root):
    """The BM25 matcher (docs/adr/0012) must land beside ai_badger_hooks.py's own copy."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, target, _ = _run_adjust(adjust_hooks, tmp_path, root)

    for name in RETRIEVAL_FILES:
        dst = target / ".ai-badger" / "hooks" / name
        assert dst.read_text(encoding="utf-8") == _retrieval_module(root, name)


def test_adjust_hooks_copies_retrieval_modules_into_plugin_dir(
        tmp_path, load_script, root):
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)

    for name in RETRIEVAL_FILES:
        dst = _plugin_dir(home) / name
        assert dst.read_text(encoding="utf-8") == _retrieval_module(root, name)


def test_plugin_yaml_declares_the_registered_hooks(tmp_path, load_script, root):
    """The manifest must declare every hook register() registers, so Hermes' loader
    sees the same surface the module wires."""
    import yaml

    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)

    manifest = yaml.safe_load((_plugin_dir(home) / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "ai-badger"
    assert set(manifest["hooks"]) == {"on_session_start", "pre_llm_call", "post_tool_call"}
    assert set(manifest["provides_hooks"]) == {
        "on_session_start", "pre_llm_call", "post_tool_call"}


def test_plugin_init_reexports_register(tmp_path, load_script, root):
    """__init__.py must expose the same register() as the copied ai_badger_hooks.py,
    so Hermes' _load_plugin (module.register(ctx)) wires the real hooks."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)
    plugin = _plugin_dir(home)

    hooks_mod = load_script(str(plugin / "ai_badger_hooks.py"))
    init_path = plugin / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.ai_badger", init_path,
        submodule_search_locations=[str(plugin)])
    assert spec is not None and spec.loader is not None
    init_mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_plugins.ai_badger"] = init_mod
    spec.loader.exec_module(init_mod)

    assert init_mod.register is hooks_mod.register

    class _FakeCtx:
        def __init__(self):
            self.hooks = []

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

    ctx = _FakeCtx()
    init_mod.register(ctx)
    assert [name for name, _ in ctx.hooks] == [
        "on_session_start", "pre_llm_call", "post_tool_call"]


def test_manifest_recorded_inside_plugin_dir(tmp_path, load_script, root):
    """copy_skew reads copies_dir/.ai-badger/manifest.json — the installer record must
    sit inside the plugin dir, or stale-copy protection silently no-ops."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)

    record = json.loads(
        (_plugin_dir(home) / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    assert record["frameworkRoot"] == str(root.resolve())
    assert record["copiedFromVersion"] == (root / "VERSION").read_text(
        encoding="utf-8").strip()


def test_legacy_flat_copies_are_removed(tmp_path, load_script, root):
    """Previous ai-badger versions dropped flat .py files and the manifest directly
    under ~/.hermes/plugins/. After the directory-shape install those are dead files;
    the adjust must remove them so the loader scans a clean user scope."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    home = tmp_path / "home"
    plugins = home / ".hermes" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "ai_badger_hooks.py").write_text("# legacy flat copy\n", encoding="utf-8")
    (plugins / "memory_grade.py").write_text("# legacy flat copy\n", encoding="utf-8")
    legacy_manifest = plugins / ".ai-badger"
    legacy_manifest.mkdir()
    (legacy_manifest / "manifest.json").write_text("{}", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        adjust_hooks.adjust(_adjust_context(root, target, ["hermes"]))

    assert [p.name for p in plugins.iterdir() if p.is_file()] == []
    assert not (plugins / ".ai-badger").exists()
    assert (_plugin_dir(home) / "ai_badger_hooks.py").is_file()
