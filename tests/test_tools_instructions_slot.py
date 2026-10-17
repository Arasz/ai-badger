"""The `{{TOOLS_INSTRUCTIONS}}` slot carries each enabled catalog tool's `tool.md` (ADR-0039).

It sits beside `{{MCP_INSTRUCTIONS}}` in every agent template, renders a tool's block only when
`config.tools` names it, and leaves the documents byte-identical when nothing is enabled.
"""
from __future__ import annotations

import sys

import pytest

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"
SLOT = "{{TOOLS_INSTRUCTIONS}}"
RTK_MD = ("features", "common", "tools", "rtk", "tool.md")


def _config(tools=None) -> dict:
    config = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": ["claude", "hermes", "codex", "pi"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    if tools is not None:
        config["tools"] = tools
    return config


def _documents(make_scaffolder, tools=None) -> dict:
    """Scaffold once and return the four agent instruction files' text."""
    scaf = make_scaffolder(config=_config(tools), install=True)
    scaf.run(generated_at="2026-10-17T00:00:00Z")
    target = make_scaffolder.target
    paths = {
        "CLAUDE.md": target / ".ai-badger" / "CLAUDE.md",
        "HERMES.md": target / ".ai-badger" / "HERMES.md",
        "AGENTS.md": target / "AGENTS.md",
        "AGENTS.override.md": target / "AGENTS.override.md",
    }
    return {name: path.read_text(encoding="utf-8") for name, path in paths.items()}


def _rtk_block(root) -> str:
    return root.joinpath(*RTK_MD).read_text(encoding="utf-8").strip() + "\n\n"


# -- s5b-a1: the templates ----------------------------------------------------------------

def test_the_tools_slot_stands_alone_in_exactly_the_templates_carrying_the_mcp_slot(root):
    templates = sorted(root.glob("features/*/templates/*.tmpl"))
    mcp = {t for t in templates if "{{MCP_INSTRUCTIONS}}" in t.read_text(encoding="utf-8")}
    tools = {t for t in templates if SLOT in t.read_text(encoding="utf-8")}

    assert mcp, "no template carries the MCP slot"
    assert tools == mcp
    for tmpl in tools:
        text = tmpl.read_text(encoding="utf-8")
        assert f"\n{SLOT}\n" in text, tmpl
        assert text.count(SLOT) == 1, tmpl


@pytest.fixture(name="rendering")
def rendering_fixture(load_script, root):
    for entry in (str(root / SCRIPTS), str(root / "engine"), str(root / "tooling")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/template_rendering.py")


# -- s5b-a2: rendering --------------------------------------------------------------------

def test_an_enabled_tool_renders_its_block_in_every_agent_file(make_scaffolder, root):
    docs = _documents(make_scaffolder, tools={"rtk": {}})

    for name, text in docs.items():
        assert text.count("## Tools: rtk") == 1, name
        assert _rtk_block(root) in text, name
        assert "{{" not in text, name


def test_hooks_do_not_gate_the_block_only_the_config_key_does(make_scaffolder):
    docs = _documents(make_scaffolder, tools={"rtk": {"hooks": ["claude"]}})

    assert all("## Tools: rtk" in text for text in docs.values())


@pytest.mark.parametrize("tools", [None, {}])
def test_no_enabled_tool_renders_no_block_and_no_placeholder(make_scaffolder, tools):
    docs = _documents(make_scaffolder, tools=tools)

    for name, text in docs.items():
        assert "## Tools:" not in text, name
        assert "{{" not in text, name


def test_the_enabled_block_is_the_only_difference_from_the_disabled_render(
        make_scaffolder, root, tmp_path_factory):
    """Disabled adds no stray line: removing the block from the enabled render gives it back."""
    enabled = _documents(make_scaffolder, tools={"rtk": {}})
    disabled = _documents(make_scaffolder, tools=None)

    for name, text in enabled.items():
        assert text.replace(_rtk_block(root), "", 1) == disabled[name], name


def test_an_unknown_tool_name_renders_nothing(make_scaffolder):
    docs = _documents(make_scaffolder, tools={"no-such-tool": {}})

    assert all("## Tools:" not in text for text in docs.values())


def test_an_empty_tools_slot_takes_its_whole_line_with_it(rendering):
    """Absolute, not relative: the enabled/disabled comparison cannot see a stray line both share."""
    text = "a\n{{MCP_INSTRUCTIONS}}\n{{TOOLS_INSTRUCTIONS}}\n\nb\n"

    filled = rendering.fill_slots(text, {"MCP_INSTRUCTIONS": "M\n\n", "TOOLS_INSTRUCTIONS": ""})

    assert filled == "a\nM\n\n\n\nb\n"
    assert filled == rendering.fill_slots("a\n{{MCP_INSTRUCTIONS}}\n\nb\n",
                                          {"MCP_INSTRUCTIONS": "M\n\n"})


def test_a_filled_tools_slot_replaces_its_line_with_the_blocks(rendering):
    filled = rendering.fill_slots("a\n{{TOOLS_INSTRUCTIONS}}\n\nb\n",
                                  {"TOOLS_INSTRUCTIONS": "T\n\n"})

    assert filled == "a\nT\n\n\nb\n"
