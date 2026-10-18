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


SYNCED_ACCOUNT = "org-uuid_user-uuid"


def _synced(home: Path, layout: dict, manifest=None) -> Path:
    """A claude.ai-synced account dir: `{dir name: server command}` plus an optional manifest.

    Each dir gets a bare `.mcp.json` server map, the shape the synced browser-use plugin ships,
    and the `.meta.json` / `.in_use` siblings Claude Code writes beside it.
    """
    account = home / ".claude" / "plugins" / "synced" / SYNCED_ACCOUNT
    for directory, command in layout.items():
        _write(account / directory / ".mcp.json",
               {"browser-use": {"command": command, "args": ["--root", "${CLAUDE_PLUGIN_ROOT}"]}})
        _write(account / directory / ".claude-plugin" / "plugin.json",
               {"name": directory.split("~", 1)[0], "description": "synced"})
        (account / directory / ".in_use").mkdir(exist_ok=True)
        _write(account / f"{directory}.meta.json", {"marketplace_name": "knowledge-work-plugins"})
    if manifest is not None:
        _write(account / "manifest.json", {"lastUpdated": 1, "plugins": manifest})
    return account


def _entry(name: str, generation: int) -> dict:
    return {"pluginId": "plugin_x", "name": name, "version": "0013",
            "marketplaceName": "knowledge-work-plugins", "installationPreference": "available",
            "generation": generation}


def test_a_synced_plugin_resolves_from_its_manifest_generation_dir(sc, tmp_path):
    """`claude mcp list` prints `plugin:browser-use:browser-use` for a claude.ai-synced plugin."""
    home, target = _dirs(tmp_path)
    account = _synced(home, {"browser-use": "/bin/bare", "browser-use~g1": "/bin/g1",
                             "browser-use~g2": "/bin/g2"},
                      manifest=[_entry("browser-use", 1)])

    spec, reason = sc.lookup(sc.load(target, home), "plugin:browser-use:browser-use")

    root = str(account / "browser-use~g1")
    assert reason == "" and spec["command"] == "/bin/g1"
    assert spec["args"] == ["--root", root]
    assert spec["env"]["CLAUDE_PLUGIN_ROOT"] == root


def test_a_synced_plugin_without_a_manifest_entry_takes_its_highest_generation(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _synced(home, {"browser-use": "/bin/bare", "browser-use~g2": "/bin/g2",
                   "browser-use~g10": "/bin/g10"}, manifest=[_entry("other", 1)])

    spec, _ = sc.lookup(sc.load(target, home), "plugin:browser-use:browser-use")

    assert spec["command"] == "/bin/g10"


def test_a_synced_plugin_with_no_generation_dir_falls_back_to_the_bare_dir(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _synced(home, {"browser-use": "/bin/bare"})

    spec, _ = sc.lookup(sc.load(target, home), "plugin:browser-use:browser-use")

    assert spec["command"] == "/bin/bare"


def test_a_manifest_generation_whose_dir_is_missing_falls_back_to_the_highest(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _synced(home, {"browser-use~g2": "/bin/g2"}, manifest=[_entry("browser-use", 7)])

    spec, _ = sc.lookup(sc.load(target, home), "plugin:browser-use:browser-use")

    assert spec["command"] == "/bin/g2"


def test_an_installed_plugin_wins_over_a_synced_one_of_the_same_name(sc, tmp_path):
    home, target = _dirs(tmp_path)
    _synced(home, {"browser-use~g2": "/bin/synced"}, manifest=[_entry("browser-use", 2)])
    installed = tmp_path / "installed" / "browser-use"
    _write(installed / ".mcp.json", {"browser-use": _stdio("installed")})
    _plugin(home, "browser-use@some-market", installed)

    spec, _ = sc.lookup(sc.load(target, home), "plugin:browser-use:browser-use")

    assert spec["command"] == "/bin/installed"


def _uses_both_vars():
    return {"command": "${CLAUDE_PLUGIN_ROOT}/bin/serve",
            "args": ["--data", "${CLAUDE_PLUGIN_DATA}"],
            "env": {"STORE": "${CLAUDE_PLUGIN_DATA}/db"}}


def test_an_installed_plugin_gets_its_data_dir_expanded_and_in_env(sc, tmp_path):
    """Claude Code names an installed plugin's data dir `<plugin>-<marketplace>`."""
    home, target = _dirs(tmp_path)
    root = tmp_path / "plugins" / "graph"
    _write(root / ".mcp.json", {"graph": _uses_both_vars()})
    _plugin(home, "ai-badger@ai-badger", root)

    spec, _ = sc.lookup(sc.load(target, home), "plugin:ai-badger:graph")

    data = str(home / ".claude" / "plugins" / "data" / "ai-badger-ai-badger")
    assert spec["args"] == ["--data", data]
    assert spec["env"]["STORE"] == f"{data}/db"
    assert spec["env"]["CLAUDE_PLUGIN_DATA"] == data
    assert spec["env"]["CLAUDE_PLUGIN_ROOT"] == str(root)
    assert not (home / ".claude" / "plugins" / "data").exists()


def test_a_synced_plugin_data_dir_is_name_dash_synced(sc, tmp_path):
    home, target = _dirs(tmp_path)
    account = home / ".claude" / "plugins" / "synced" / SYNCED_ACCOUNT
    _write(account / "browser-use~g2" / ".mcp.json", {"browser-use": _uses_both_vars()})

    spec, _ = sc.lookup(sc.load(target, home), "plugin:browser-use:browser-use")

    data = str(home / ".claude" / "plugins" / "data" / "browser-use-synced")
    assert spec["args"] == ["--data", data]
    assert spec["env"]["CLAUDE_PLUGIN_DATA"] == data
    assert spec["env"]["CLAUDE_PLUGIN_ROOT"] == str(account / "browser-use~g2")


def test_a_plugin_config_env_wins_over_the_host_set_plugin_vars(sc, tmp_path):
    home, target = _dirs(tmp_path)
    root = tmp_path / "plugins" / "graph"
    _write(root / ".mcp.json", {"graph": {"command": "/bin/x", "env": {
        "CLAUDE_PLUGIN_DATA": "/custom/data", "CLAUDE_PLUGIN_ROOT": "/custom/root"}}})
    _plugin(home, "p@m", root)

    spec, _ = sc.lookup(sc.load(target, home), "plugin:p:graph")

    assert spec["env"]["CLAUDE_PLUGIN_DATA"] == "/custom/data"
    assert spec["env"]["CLAUDE_PLUGIN_ROOT"] == "/custom/root"


@pytest.mark.parametrize("hostile", ["../../../../../outside", "ABSOLUTE", "..", ".", "a/b", ""])
def test_a_manifest_name_that_is_not_a_plain_dir_name_is_skipped(sc, tmp_path, hostile):
    """The synced manifest is untrusted: a name must not lead outside the account dir."""
    home, target = _dirs(tmp_path)
    outside = tmp_path / "outside"
    _write(outside / ".mcp.json", {"evil": _stdio("evil")})
    _write(outside / "x~g1" / ".mcp.json", {"evil": _stdio("evil")})
    name = str(outside) if hostile == "ABSOLUTE" else hostile
    _synced(home, {"browser-use~g2": "/bin/g2"},
            manifest=[_entry(name, 1), _entry("browser-use", 2)])

    configs = sc.load(target, home)

    assert not [k for k, s in configs.specs.items() if s.get("command") == "/bin/evil"]
    assert sc.lookup(configs, "plugin:browser-use:browser-use")[0]["command"] == "/bin/g2"


@pytest.mark.parametrize("link", ["evil", "evil~g3"])
def test_a_synced_plugin_dir_symlinked_outside_the_account_is_skipped(sc, tmp_path, link):
    home, target = _dirs(tmp_path)
    outside = tmp_path / "outside"
    _write(outside / ".mcp.json", {"evil": _stdio("evil")})
    account = _synced(home, {"browser-use~g2": "/bin/g2"},
                      manifest=[_entry("evil", 3), _entry("browser-use", 2)])
    (account / link).symlink_to(outside, target_is_directory=True)

    configs = sc.load(target, home)

    assert sc.lookup(configs, "plugin:evil:evil")[0] is None
    assert sc.lookup(configs, "plugin:browser-use:browser-use")[0]["command"] == "/bin/g2"


@pytest.mark.parametrize("env", [["A=1"], "A=1", 3])
def test_a_plugin_server_with_a_non_map_env_still_resolves(sc, tmp_path, env):
    home, target = _dirs(tmp_path)
    root = tmp_path / "plugins" / "graph"
    _write(root / ".mcp.json", {"graph": {"command": "/bin/x", "env": env}})
    _plugin(home, "p@m", root)

    spec, _ = sc.lookup(sc.load(target, home), "plugin:p:graph")

    assert spec["env"]["CLAUDE_PLUGIN_ROOT"] == str(root)
