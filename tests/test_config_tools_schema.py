"""`config.tools`: which catalog tools a project opts into, and for which agents' hooks."""
from __future__ import annotations

import pytest

from scaffold_helpers import _config


def _errors(bl, root, config):
    return bl.validate(config, bl.load_json(root / "schemas" / "config.schema.json"))


def _with_tools(tools):
    config = _config(agents=["claude", "pi"])
    config["tools"] = tools
    return config


def test_a_config_without_tools_is_valid(root, load_script):
    bl = load_script("engine/badger_lib.py")
    config = _config(agents=["claude"])

    assert "tools" not in config
    assert _errors(bl, root, config) == []


def test_a_config_opting_shim_into_two_agents_hooks_is_valid(root, load_script):
    bl = load_script("engine/badger_lib.py")

    assert _errors(bl, root, _with_tools({"shim": {"hooks": ["claude", "pi"]}})) == []


def test_every_agent_may_be_named_once_and_hooks_may_be_empty(root, load_script):
    bl = load_script("engine/badger_lib.py")
    every = ["claude", "codex", "copilot", "pi", "hermes"]

    assert _errors(bl, root, _with_tools({"shim": {"hooks": every}, "other-tool": {}})) == []


@pytest.mark.parametrize("tools", [
    pytest.param({"shim": {"hooks": ["claude", "cursor"]}}, id="unknown-agent"),
    pytest.param({"shim": {"hooks": ["claude", "claude"]}}, id="duplicate-hook"),
    pytest.param({"shim": {"hooks": ["claude"], "install": True}}, id="extra-per-tool-key"),
    pytest.param({"SHIM": {"hooks": ["claude"]}}, id="non-slug-uppercase"),
    pytest.param({"shim tool": {"hooks": ["claude"]}}, id="non-slug-space"),
    pytest.param({"-shim": {"hooks": ["claude"]}}, id="non-slug-leading-dash"),
    pytest.param({"shim": {"hooks": {"claude": True}}}, id="hooks-not-a-list"),
    pytest.param({"shim": ["claude"]}, id="tool-not-an-object"),
])
def test_config_tools_refuses(root, load_script, tools):
    bl = load_script("engine/badger_lib.py")

    assert _errors(bl, root, _with_tools(tools))
