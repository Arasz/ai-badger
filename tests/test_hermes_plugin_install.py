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
from conftest import _test_write

PLUGIN_DIR_NAME = "ai-badger"
USER_PLUGIN_FILES = ("ai_badger_hooks.py", "learned_skills_sync.py", "debug_log.py")
SHARED_SKILL_FILES = (
    ("commit-reminder", "commit_reminder.py"),
    ("commit-reminder", "impact_estimator.py"),
    ("test-economy", "suite_economy.py"),
    ("ai-raccoon-memory", "memory_first_gate.py"),
    ("semantica-knowledge-graph", "export_semantica_graph.py"),
    ("git-work", "git_internals_guard.py"),
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

    scaf = make_scaffolder(config=_config(["hermes"]), skills=["task"], install=True)
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
        _test_write(plugin / name, "# stale copy\n", encoding="utf-8")

    scaf = make_scaffolder(config=_config(["hermes"]), skills=["task"], install=True)
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


def test_adjust_hooks_removes_stale_memory_grade_copies(
        tmp_path, load_script, root):
    """The removed memory-grade sibling must be deleted, not copied, from both destinations."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, target, home = _run_adjust(adjust_hooks, tmp_path, root)

    # Stale copies from the pre-removal install must not survive a re-run either.
    stale_dirs = (target / ".ai-badger" / "hooks", _plugin_dir(home))
    for dst_dir in stale_dirs:
        dst_dir.mkdir(parents=True, exist_ok=True)
        _test_write(dst_dir / "memory_grade.py", "# stale copy\n", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        adjust_hooks.adjust(_adjust_context(root, target, ["hermes"]))

    for dst_dir in stale_dirs:
        assert not (dst_dir / "memory_grade.py").exists(), \
            f"stale memory_grade.py survived at {dst_dir / 'memory_grade.py'}"


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


def test_shared_skill_files_matches_production_shipping_list(load_script):
    """Derive-or-delete: the test-side SHARED_SKILL_FILES must mirror the production tuple."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    assert set(SHARED_SKILL_FILES) == set(adjust_hooks.SHARED_SKILL_MODULES)


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
    assert set(manifest["hooks"]) == {
        "on_session_start", "pre_llm_call", "pre_tool_call", "post_tool_call",
        "on_session_end"}
    assert set(manifest["provides_hooks"]) == {
        "on_session_start", "pre_llm_call", "pre_tool_call", "post_tool_call",
        "on_session_end"}


def test_plugin_init_reexports_register(tmp_path, load_script, root):
    """__init__.py must expose the same register() as the copied ai_badger_hooks.py,
    so Hermes' _load_plugin (module.register(ctx)) wires the real hooks."""
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)
    plugin = _plugin_dir(home)

    init_path = plugin / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.ai_badger", init_path,
        submodule_search_locations=[str(plugin)])
    assert spec is not None and spec.loader is not None
    init_mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_plugins.ai_badger"] = init_mod
    spec.loader.exec_module(init_mod)

    assert callable(init_mod.register)

    class _FakeCtx:
        def __init__(self):
            self.hooks = []

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

    ctx = _FakeCtx()
    init_mod.register(ctx)
    assert [name for name, _ in ctx.hooks] == [
        "on_session_start", "pre_llm_call", "pre_tool_call",
        "pre_tool_call", "post_tool_call", "on_session_end"]  # P5 defer: notice alone on start
    # The registered callbacks are the copied module's functions, not stubs. Keyed by hook
    # name, not by position: pre_tool_call carries two arms and a third would shift indexes.
    by_hook = {}
    for name, callback in ctx.hooks:
        by_hook.setdefault(name, []).append(callback.__name__)
    assert by_hook["post_tool_call"] == ["post_tool_observer"]
    assert by_hook["pre_tool_call"] == ["pre_tool_call_memory_gate",
                                        "pre_tool_call_git_internals_guard"]


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
    _test_write(plugins / "ai_badger_hooks.py", "# legacy flat copy\n", encoding="utf-8")
    _test_write(plugins / "memory_grade.py", "# legacy flat copy\n", encoding="utf-8")
    legacy_manifest = plugins / ".ai-badger"
    legacy_manifest.mkdir()
    _test_write(legacy_manifest / "manifest.json", "{}", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=home):
        adjust_hooks.adjust(_adjust_context(root, target, ["hermes"]))

    assert [p.name for p in plugins.iterdir() if p.is_file()] == []
    assert not (plugins / ".ai-badger").exists()
    assert (_plugin_dir(home) / "ai_badger_hooks.py").is_file()


# ------------------------------------------------------- confining the user-scope install


def test_no_install_leaves_the_user_scope_untouched(tmp_path, load_script, root):
    """`--no-install` must reach the user scope, not just the skill install commands.

    The scaffold-freshness gate re-scaffolds a throwaway copy with `--no-install`; when that
    reached only `install_plugins`, every gate run overwrote the operator's real Hermes plugin
    and recorded the temp directory as its `frameworkRoot`.
    """
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    target = tmp_path / "proj"
    home = tmp_path / "home"
    home.mkdir()
    context = _adjust_context(root, target, ["hermes"])
    context["install"] = False

    with patch("pathlib.Path.home", return_value=home):
        result = adjust_hooks.adjust(context)

    assert not (home / ".hermes").exists()
    assert ".hermes" not in result["notes"]
    assert result["applied"] is True
    assert (target / ".ai-badger" / "hooks" / "ai_badger_hooks.py").is_file()


def test_the_plugin_install_follows_hermes_home(tmp_path, load_script, root, monkeypatch):
    """`$HERMES_HOME` names the Hermes home; the install must not hardcode `~/.hermes`."""
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("HERMES_HOME", str(elsewhere))
    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")

    _, _, home = _run_adjust(adjust_hooks, tmp_path, root)

    assert (elsewhere / "plugins" / PLUGIN_DIR_NAME / "ai_badger_hooks.py").is_file()
    assert not (home / ".hermes").exists()


def test_the_scaffolder_hands_no_install_through_to_the_user_scope(
        tmp_path, root, make_scaffolder):
    """End to end: the adjustment's no-op is only a fix if scaffold.py passes the flag."""
    assert root  # the fixture pins which framework the scaffolder reads
    home = tmp_path / "home"
    home.mkdir()

    scaf = make_scaffolder(config=_config(["hermes"]), skills=["task"], install=False)
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-26T00:00:00Z")

    assert not (home / ".hermes").exists(), sorted(
        str(p.relative_to(home)) for p in (home / ".hermes").rglob("*"))


def test_no_install_leaves_no_hermes_skill_links_behind(tmp_path, root, make_scaffolder):
    """The freshness gate scaffolds a temp copy; its links would outlive the temp dir.

    `--no-install` reached `install_plugins` but not `symlink_hermes_skills`, so every gate
    run left `~/.hermes/skills/<project>/` pointing at a deleted `scaffold-freshness-*` tree.
    """
    assert root
    home = tmp_path / "home"
    home.mkdir()

    scaf = make_scaffolder(config=_config(["hermes"]), skills=["task"], install=False)
    with patch("pathlib.Path.home", return_value=home):
        scaf.run(generated_at="2026-07-26T00:00:00Z")

    assert not (home / ".hermes" / "skills").exists()


def test_every_lazily_loaded_sibling_is_copied_beside_the_plugin(root, load_script):
    """A sibling module that is not in a copy list is silently never loaded.

    `_load_sibling_module` fails open by design: absent file, no error, returns None. That
    is right for an older scaffold, and lethal for a NEW module — the feature ships, the
    tests pass against the source tree, and the installed plugin never runs it. Exactly the
    "registered with no agent" shape this repo keeps hitting.

    So derive the expectation instead of trusting the lists: every filename
    `ai_badger_hooks.py` passes to `_load_sibling_module` must be copied into both the
    project hooks dir and the user plugin dir by some list in adjust_hooks.
    """
    import re

    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    source = (root / "features" / "common" / "hooks" / "ai_badger_hooks.py").read_text(
        encoding="utf-8")

    wanted = set(re.findall(r'_load_sibling_module\(\s*[^,]+,\s*"([^"]+\.py)"', source))
    assert wanted, "no sibling loads found — the regex stopped matching, not the code"

    # Scoped to ~/.hermes/plugins/ai-badger/, the copy Hermes demonstrably loads: it is the
    # directory plugin adjust_hooks installs and the one holding a live __init__.py. NOT
    # unioned with PROJECT_HOOKS — a union would pass a module that reaches .ai-badger/hooks/
    # and never reaches the plugin dir, which is the gap worth catching.
    #
    # The .ai-badger/hooks/ copy is deliberately narrower, not a second copy of this set:
    # follow_through.py and learned_skills_sync.py ship to the plugin dir only. Asserting
    # parity there would be asserting an equivalence the scaffolder does not claim.
    shipped = (set(adjust_hooks.USER_PLUGINS)
               | {name for _, name in adjust_hooks.SHARED_SKILL_MODULES}
               | set(adjust_hooks.RETRIEVAL_MODULES))

    missing = sorted(wanted - shipped)
    assert missing == [], (
        f"ai_badger_hooks lazily loads {missing}, which adjust_hooks never copies into "
        "~/.hermes/plugins/ai-badger/. The installed plugin would silently skip it.")
