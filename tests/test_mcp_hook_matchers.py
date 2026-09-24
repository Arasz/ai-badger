"""Every hook meant for an MCP tool fires on the name each host actually delivers.

The matcher rules come from each host's docs (see hook_matcher_rules). pi's bridge is covered in
features/pi/tests/hook-bridge.test.ts; Hermes has no matcher and filters by name in its plugin.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hook_matcher_rules import claude_is_exact, claude_matches, copilot_matches

# (script, MCP server, MCP tool) — the hooks whose job is to run after an MCP tool call.
MCP_TARGETS = [
    ("memory_first_gate_post_hook.py", "ai-raccoon", "memory_search"),
    ("memory_grade_hook.py", "ai-raccoon", "memory_search"),
    ("semantica_export_autosave_hook.py", "semantica", "export_graph"),
]

CLAUDE_TOOLS = {"Agent", "Bash", "Edit", "Glob", "Grep", "MultiEdit", "NotebookEdit", "Read",
                "Write"}
# Another host's spelling of a read tool; an exact-match token Claude never delivers is inert there.
OTHER_HOST_TOOLS = {"ReadFile"}

CLAUDE_SHAPED = [
    "features/common/hooks/hooks.json",
    ".ai-badger/hooks/hooks.json",
    ".claude/settings.json",
]
COPILOT_HOOKS = ".github/hooks/ai-badger-hooks.json"


def _load(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _claude_fired(data: dict, event: str, tool: str) -> list:
    """Every command a Claude-shaped hooks mapping runs for `tool` on `event`."""
    return [h.get("command", "")
            for entry in data.get("hooks", {}).get(event, [])
            if claude_matches(entry.get("matcher"), tool)
            for h in entry.get("hooks", [])]


def _copilot_fired(data: dict, event: str, tool: str) -> list:
    return [h.get("bash", "") for h in data.get("hooks", {}).get(event, [])
            if copilot_matches(h.get("matcher"), tool)]


# ------------------------------------------------------------------ the rules themselves
def test_claude_rule_reproduces_the_documented_examples():
    assert claude_matches("Bash", "Bash")
    assert claude_matches("Edit|Write", "Write") and claude_matches("Edit, Write", "Edit")
    assert not claude_matches("Bash", "BashOutput")
    assert claude_matches("^Notebook", "NotebookEdit")
    assert claude_matches("Edit.*", "NotebookEdit")
    assert claude_matches("mcp__memory__.*", "mcp__memory__create_entities")
    assert not claude_matches("mcp__memory", "mcp__memory__create_entities")
    assert not claude_matches("memory_search", "mcp__ai-raccoon__memory_search")


def test_copilot_rule_is_a_whole_name_regex():
    assert copilot_matches("bash|Bash", "bash")
    assert not copilot_matches("bash", "bash2")
    assert not copilot_matches("memory_search", "ai-raccoon-memory_search")


# ------------------------------------------------------------------ Claude-shaped copies
@pytest.mark.parametrize("rel", CLAUDE_SHAPED)
@pytest.mark.parametrize("script,server,tool", MCP_TARGETS)
def test_claude_fires_the_hook_on_the_real_mcp_tool_name(root, rel, script, server, tool):
    """Claude delivers `mcp__<server>__<tool>`; a bare tool-name matcher is exact and never fires."""
    fired = _claude_fired(_load(root, rel), "PostToolUse", f"mcp__{server}__{tool}")
    assert any(script in command for command in fired), (rel, script)


@pytest.mark.parametrize("rel", CLAUDE_SHAPED)
@pytest.mark.parametrize("script,server,tool", MCP_TARGETS)
def test_claude_mcp_matcher_stays_on_its_tool(root, rel, script, server, tool):
    """A regex matcher is unanchored on Claude — it must not drift onto a longer tool name."""
    data = _load(root, rel)
    for other in (f"mcp__{server}__{tool}_extra", f"mcp__{server}__not_{tool}", "Bash"):
        fired = _claude_fired(data, "PostToolUse", other)
        assert not any(script in command for command in fired), (rel, other)


@pytest.mark.parametrize("rel", CLAUDE_SHAPED)
def test_memory_grade_hook_also_fires_on_read(root, rel):
    """memory_grade_hook is registered for two matchers; both must reach every copy."""
    fired = _claude_fired(_load(root, rel), "PostToolUse", "Read")
    assert any("memory_grade_hook.py" in command for command in fired), rel


def test_no_exact_matcher_names_a_tool_claude_never_delivers(root):
    """An exact-match token that is no Claude tool is an MCP name written bare: it matches nothing."""
    source = _load(root, "features/common/hooks/hooks.json")["hooks"]
    stray = []
    for event in ("PreToolUse", "PostToolUse"):
        for entry in source.get(event, []):
            matcher = entry.get("matcher") or ""
            if not claude_is_exact(matcher):
                continue
            stray += [(event, token.strip()) for token in re.split(r"[|,]", matcher)
                      if token.strip() not in CLAUDE_TOOLS | OTHER_HOST_TOOLS]
    assert stray == []


# ------------------------------------------------------------------ Copilot
@pytest.mark.parametrize("script,server,tool", MCP_TARGETS)
def test_copilot_fires_the_hook_on_the_real_mcp_tool_name(root, script, server, tool):
    """Copilot delivers `<server>-<tool>` and anchors the matcher to the whole name."""
    fired = _copilot_fired(_load(root, COPILOT_HOOKS), "postToolUse", f"{server}-{tool}")
    assert any(script in command for command in fired), script
