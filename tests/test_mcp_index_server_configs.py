"""server_configs.py: where Claude Code keeps each MCP server's command or URL.

`claude mcp list` prints names only (`<name>`, `plugin:<p>:<s>`, `claude.ai <Name>`), so
`--discover` reads the same files Claude Code reads: the project `.mcp.json`, `~/.claude.json`
(user scope and the project's local scope), and every installed plugin's `.mcp.json` or
`plugin.json`. Each test builds those files under a tmp HOME and a tmp target.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

MODULE = "features/common/skills/mcp-index/scripts/server_configs.py"


@pytest.fixture(name="sc")
def _sc(load_script):
    return load_script(MODULE)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


def _dirs(tmp_path):
    home, target = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    target.mkdir()
    return home, target


def _stdio(tag):
    return {"command": f"/bin/{tag}", "args": [tag]}


def _approve_all(target: Path):
    _write(target / ".claude" / "settings.local.json", {"enableAllProjectMcpServers": True})


def test_project_mcp_json_entries_resolve(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(target / ".mcp.json", {"mcpServers": {"semantica": _stdio("project")}})
    _approve_all(target)

    spec, reason = sc.lookup(sc.load(target, home), "semantica")

    assert spec["command"] == "/bin/project" and reason == ""


def test_user_scope_entries_resolve(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(home / ".claude.json", {"mcpServers": {"rider": {"type": "http",
                                                           "url": "http://127.0.0.1:1/x"}}})

    spec, _ = sc.lookup(sc.load(target, home), "rider")

    assert spec["url"] == "http://127.0.0.1:1/x"


def test_local_scope_outranks_project_which_outranks_user(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(home / ".claude.json", {
        "mcpServers": {"a": _stdio("user"), "b": _stdio("user")},
        "projects": {str(target): {"mcpServers": {"a": _stdio("local")}}},
    })
    _write(target / ".mcp.json", {"mcpServers": {"a": _stdio("project"),
                                                 "b": _stdio("project")}})
    _approve_all(target)
    configs = sc.load(target, home)

    assert sc.lookup(configs, "a")[0]["command"] == "/bin/local"
    assert sc.lookup(configs, "b")[0]["command"] == "/bin/project"


def test_the_nearest_project_entry_above_the_target_supplies_local_scope(sc, tmp_path):
    """A worktree under the repo has no projects[] entry of its own; its nearest parent does."""
    home, target = _dirs(tmp_path)
    worktree = target / ".ai-badger" / "worktrees" / "lane"
    worktree.mkdir(parents=True)
    _write(home / ".claude.json", {"projects": {
        str(tmp_path): {"mcpServers": {"a": _stdio("far")}},
        str(target): {"mcpServers": {"a": _stdio("near")}},
        str(tmp_path / "repo-other"): {"mcpServers": {"a": _stdio("sibling")}},
    }})

    assert sc.lookup(sc.load(worktree, home), "a")[0]["command"] == "/bin/near"


def test_disabled_project_servers_are_not_run(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(target / ".mcp.json", {"mcpServers": {"off": _stdio("p"), "on": _stdio("p")}})
    _write(home / ".claude.json", {"projects": {str(target): {
        "disabledMcpjsonServers": ["off"]}}})
    _approve_all(target)
    configs = sc.load(target, home)

    assert sc.lookup(configs, "off")[0] is None
    assert sc.lookup(configs, "on")[0] is not None


def test_a_non_empty_enabled_list_admits_only_its_project_servers(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(target / ".mcp.json", {"mcpServers": {"x": _stdio("p"), "y": _stdio("p")}})
    _write(home / ".claude.json", {"projects": {str(target): {
        "enabledMcpjsonServers": ["x"]}}})
    configs = sc.load(target, home)

    assert sc.lookup(configs, "x")[0] is not None
    assert sc.lookup(configs, "y")[0] is None


def _plugin(home: Path, key: str, root: Path):
    _write(home / ".claude" / "plugins" / "installed_plugins.json",
           {"version": 2, "plugins": {key: [{"scope": "user", "installPath": str(root)}]}})


@pytest.mark.parametrize("wrapped", [True, False])
def test_plugin_mcp_json_wrapped_or_bare_with_plugin_root_expanded(sc, tmp_path, wrapped):
    home, target = _dirs(tmp_path)
    root = tmp_path / "plugins" / "graph"
    servers = {"code-review-graph": {"command": "${CLAUDE_PLUGIN_ROOT}/bin/serve",
                                     "args": ["--root", "${CLAUDE_PLUGIN_ROOT}"]}}
    _write(root / ".mcp.json", {"mcpServers": servers} if wrapped else servers)
    _plugin(home, "ai-badger@some-market", root)

    spec, _ = sc.lookup(sc.load(target, home), "plugin:ai-badger:code-review-graph")

    assert spec["command"] == f"{root}/bin/serve"
    assert spec["args"] == ["--root", str(root)]
    assert spec["env"]["CLAUDE_PLUGIN_ROOT"] == str(root)


def test_plugin_json_inline_and_path_mcp_servers(sc, tmp_path):
    home, target = _dirs(tmp_path)
    inline_root, path_root = tmp_path / "p1", tmp_path / "p2"
    _write(inline_root / ".claude-plugin" / "plugin.json",
           {"name": "one", "mcpServers": {"s1": _stdio("inline")}})
    _write(path_root / ".claude-plugin" / "plugin.json",
           {"name": "two", "mcpServers": "./servers.json"})
    _write(path_root / "servers.json", {"mcpServers": {"s2": _stdio("pathed")}})
    _write(home / ".claude" / "plugins" / "installed_plugins.json", {"plugins": {
        "one@m": [{"installPath": str(inline_root)}],
        "two@m": [{"installPath": str(path_root)}]}})
    configs = sc.load(target, home)

    assert sc.lookup(configs, "plugin:one:s1")[0]["command"] == "/bin/inline"
    assert sc.lookup(configs, "plugin:two:s2")[0]["command"] == "/bin/pathed"


def test_claude_ai_connectors_are_host_managed(sc, tmp_path):
    home, target = _dirs(tmp_path)

    spec, reason = sc.lookup(sc.load(target, home), "claude.ai Gmail")

    assert spec is None and reason == sc.HOST_MANAGED


def test_unknown_names_and_unreadable_files_are_no_config(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(home / ".claude.json", "{not json")
    _write(target / ".mcp.json", "[]")

    spec, reason = sc.lookup(sc.load(target, home), "nowhere")

    assert spec is None and reason == sc.NO_CONFIG


def test_an_unapproved_project_server_is_not_run(sc, tmp_path):
    """Claude Code runs a repo's .mcp.json command only once the user approved it; so do we."""
    home, target = _dirs(tmp_path)
    _write(target / ".mcp.json", {"mcpServers": {"repo": _stdio("p")}})

    spec, reason = sc.lookup(sc.load(target, home), "repo")

    assert spec is None and reason == sc.NOT_APPROVED


@pytest.mark.parametrize("where, setting", [
    (".claude/settings.json", {"enabledMcpjsonServers": ["repo"]}),
    (".claude/settings.local.json", {"enableAllProjectMcpServers": True}),
    ("HOME/.claude/settings.json", {"enableAllProjectMcpServers": True}),
    ("HOME/.claude.json", None),
])
def test_approval_comes_from_any_settings_file_claude_code_reads(sc, tmp_path, where, setting):
    home, target = _dirs(tmp_path)
    _write(target / ".mcp.json", {"mcpServers": {"repo": _stdio("p")}})
    if setting is None:
        _write(home / ".claude.json", {"projects": {str(target): {
            "enableAllProjectMcpServers": True}}})
    elif where.startswith("HOME/"):
        _write(home / where[5:], setting)
    else:
        _write(target / where, setting)

    assert sc.lookup(sc.load(target, home), "repo")[0] is not None


def test_a_disabled_project_server_stays_off_even_when_all_are_enabled(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _write(target / ".mcp.json", {"mcpServers": {"repo": _stdio("p")}})
    _write(target / ".claude" / "settings.local.json",
           {"enableAllProjectMcpServers": True, "disabledMcpjsonServers": ["repo"]})

    assert sc.lookup(sc.load(target, home), "repo")[0] is None
