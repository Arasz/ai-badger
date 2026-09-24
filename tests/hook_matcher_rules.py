"""How each host decides whether a hook `matcher` covers a tool name, as its docs state it.

Claude Code — https://code.claude.com/docs/en/hooks.md, "Matcher patterns": a matcher of
"Only letters, digits, `_`, `-`, spaces, `,`, and `|`" is an "Exact string, or list of exact
strings separated by `|` or `,`"; one that "Contains any other character" is a "JavaScript
regular expression, unanchored". MCP tools are named `mcp__<server>__<tool>`.

Copilot CLI (camelCase events) — GitHub Copilot hooks reference: the matcher is a regex
"compiled as ^(?:PATTERN)$" that "must match the entire tool name"; MCP tools are named
`<serverName>-<toolName>`.
"""
from __future__ import annotations

import re
from typing import Optional

_CLAUDE_EXACT = re.compile(r"[A-Za-z0-9_\-, |]*")


def claude_is_exact(matcher: Optional[str]) -> bool:
    """True when Claude Code compares this matcher as exact names rather than as a regex."""
    return matcher not in (None, "", "*") and _CLAUDE_EXACT.fullmatch(matcher) is not None


def claude_matches(matcher: Optional[str], tool: str) -> bool:
    """True when Claude Code fires a hook with this matcher for `tool`."""
    if matcher in (None, "", "*"):
        return True
    if claude_is_exact(matcher):
        return tool in {part.strip() for part in re.split(r"[|,]", matcher)}
    return re.search(matcher, tool) is not None


def copilot_matches(matcher: Optional[str], tool: str) -> bool:
    """True when Copilot CLI fires a hook with this matcher for `tool`."""
    if not matcher:
        return True
    return re.fullmatch(f"(?:{matcher})", tool) is not None
