"""Hermes plugin hooks for ai-badger framework integration.

Provides feature-parity with Claude Code hooks:
- on_session_start: drift notice (Tier 1, ADR-0001 decision 5)
- pre_llm_call: inject framework version context, usage hints, and MCP tool index recommendations
- post_tool_call: log tool usage for session tracking and index hit/miss metrics

Installation: copy/symlink this file to ~/.hermes/plugins/ai_badger_hooks.py
or include it in a Hermes plugin package with a register() entry point.

The plugin self-locates the ai-badger framework root by walking ancestor
directories (same pattern as _bootstrap_lib in the scaffold scripts),
NOT via a hardcoded path or environment variable.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("ai_badger_hooks")


# ---------------------------------------------------------------------------
# Framework root discovery (same ancestor-walk as scaffold/detect scripts)
# ---------------------------------------------------------------------------

def find_framework_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk ancestors from `start` for the ai-badger framework root.

    A framework root is the nearest ancestor containing both a `VERSION` file
    and a `schemas/` directory. Falls back to this file's own location.

    Deliberately NOT a fixed parents[N] — see ADR-0001 Context section for
    why hardcoded depth caused a real misrooting bug.
    """
    if start is None:
        start = Path(__file__).resolve()
    for anc in [start, *start.parents]:
        if (anc / "VERSION").is_file() and (anc / "schemas").is_dir():
            return anc
    return None


# ---------------------------------------------------------------------------
# Drift notice — equivalent to Claude's SessionStart drift_notice_hook.py
# ---------------------------------------------------------------------------

def _read_framework_version() -> Optional[str]:
    """Read the framework's VERSION file, or None on any error."""
    root = find_framework_root()
    if root is None:
        return None
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_scaffold_version(cwd: Optional[str]) -> Optional[str]:
    """Read the project's manifest.json frameworkVersion, or None."""
    if not cwd:
        return None
    manifest = Path(cwd) / ".ai-badger" / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data.get("frameworkVersion")
    except (OSError, ValueError):
        return None


def on_session_start_drift_notice(cwd: str = "", **_kwargs: Any) -> None:
    """Check for framework version drift on every session start.

    Silent on match, on an unscaffolded project, and on any read error.
    A hook that breaks session start or nags unconditionally defeats its purpose.
    """
    scaffold_ver = _read_scaffold_version(cwd)
    fw_version = _read_framework_version()
    if not scaffold_ver or not fw_version or scaffold_ver == fw_version:
        return
    logger.info(
        "ai-badger drift: scaffolded with %s, framework is %s. "
        "Run den-refresh to update.",
        scaffold_ver, fw_version,
    )


# ---------------------------------------------------------------------------
# MCP Tool Index integration
# ---------------------------------------------------------------------------

# Keyword → tag mapping for extracting domain tags from natural-language queries.
# Mirrors the heuristics in the Phase 0.2 spike (scripts/spike_mcp_match.py).
_KEYWORD_TAG_MAP: dict[str, list[str]] = {
    # Language keywords
    "c#": ["csharp"], ".net": ["dotnet", "csharp"], "dotnet": ["dotnet", "csharp"],
    "csharp": ["csharp"], "typescript": ["typescript"], "ts": ["typescript"],
    "sql": ["sql", "database"], "javascript": ["javascript"], "python": ["python"],

    # Action keywords
    "build": ["build", "dotnet"], "compile": ["build", "dotnet"],
    "run": ["run"], "execute": ["run"], "test": ["run"],
    "refactor": ["refactoring"], "rename": ["refactoring"],
    "format": ["refactoring"],
    "search": ["search"], "find": ["search"], "look for": ["search"],
    "grep": ["search"], "regex": ["search"],
    "read": ["read"], "show": ["read"], "display": ["read"],
    "write": ["write"], "create": ["write"], "make": ["write"],
    "edit": ["write"], "patch": ["write"], "replace": ["write"],

    # Domain keywords
    "database": ["database", "sql"], "db": ["database", "sql"],
    "table": ["database", "sql"], "schema": ["database", "sql"],
    "column": ["database", "sql"], "columns": ["database", "sql"],
    "query": ["database", "sql"], "connection": ["database", "sql"],
    "error": ["diagnostic"], "problem": ["diagnostic"], "warning": ["diagnostic"],
    "bug": ["diagnostic"], "debug": ["diagnostic"],
    "inspect": ["diagnostic"], "check": ["diagnostic"], "diagnostic": ["diagnostic"],
    "trace": ["tracing", "opentelemetry"], "span": ["tracing", "opentelemetry"],
    "log": ["tracing", "opentelemetry"], "opentelemetry": ["tracing", "opentelemetry"],
    "service": ["tracing", "opentelemetry"],
    "file": ["files"], "directory": ["files"], "folder": ["files"],
    "tree": ["files", "navigation"], "structure": ["files", "navigation"],
    "project": ["files", "dotnet"], "solution": ["dotnet", "csharp"],
    "class": ["semantic", "csharp"], "method": ["semantic", "csharp"],
    "symbol": ["semantic"], "reference": ["semantic"],
    "open": ["navigation"], "editor": ["navigation"], "tab": ["navigation"],
    "terminal": ["terminal"], "shell": ["terminal"], "command": ["terminal"],
}


def _load_mcp_index(cwd: Optional[str]) -> Optional[dict[str, Any]]:
    """Load .ai-badger/mcp-tools.yaml from the project, or None."""
    if not cwd:
        return None
    index_path = Path(cwd) / ".ai-badger" / "mcp-tools.yaml"
    if not index_path.exists():
        return None
    try:
        return yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _extract_query_tags(query: str) -> Counter[str]:
    """Extract tags from a natural-language query using keyword matching."""
    lower = query.lower()
    tags: Counter[str] = Counter()
    for keyword, tag_list in _KEYWORD_TAG_MAP.items():
        if keyword in lower:
            for tag in tag_list:
                tags[tag] += 1
    return tags


def _find_relevant_tools(
    query: str, index: dict[str, Any], top_n: int = 5
) -> list[tuple[str, float]]:
    """Rank all tools in the index by relevance to the query.

    Returns list of (full_tool_name, score) sorted by descending score.
    """
    query_tags = _extract_query_tags(query)
    if not query_tags:
        return []

    scored: list[tuple[str, float]] = []
    lower_query = query.lower()

    for server in index.get("sources", []):
        sname = server["name"]
        for tname, tool in server.get("tools", {}).items():
            # Skip removed tools
            if tool.get("status") == "removed":
                continue

            full_name = f"{sname}:{tname}"
            tool_tags = tool.get("tags", [])
            intent = tool.get("intent", "")

            score = 0.0

            # Tag intersection: weighted by keyword frequency
            for tag in tool_tags:
                score += query_tags.get(tag, 0) * 1.0

            # Intent word overlap: raw query words appearing in intent text
            query_words = set(lower_query.split())
            intent_lower = intent.lower()
            for word in query_words:
                if len(word) > 2 and word in intent_lower:
                    score += 0.4

            # Bonus for direct keyword→tag mapping
            for tag in tool_tags:
                if tag in query_tags:
                    score += 0.3

            if score > 0:
                scored.append((full_name, score))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


# ---------------------------------------------------------------------------
# Context enrichment — equivalent to Claude's UserPromptSubmit hook
# ---------------------------------------------------------------------------

def pre_llm_inject_context(cwd: str = "", message: str = "", **_kwargs: Any) -> Optional[Dict[str, str]]:
    """Inject ai-badger framework context into every LLM turn.

    Returns a context dict that Hermes prepends to the user message,
    or None to leave the prompt unchanged. This fires once per turn,
    before the tool-calling loop.

    What we inject:
    - Framework version info (so the agent knows which ai-badger features are available)
    - Drift notice if the project is behind
    - Hermes-specific usage hints (/usage, hermes insights, session_search)
    - MCP tool index recommendations (when .ai-badger/mcp-tools.yaml exists)
    """
    parts: list[str] = []

    # Framework version
    fw_version = _read_framework_version()
    if fw_version:
        scaffold_ver = _read_scaffold_version(cwd)
        if scaffold_ver and scaffold_ver != fw_version:
            parts.append(
                f"[ai-badger] Scaffolded with {scaffold_ver}, "
                f"framework is {fw_version}. Run den-refresh to update."
            )

    # Usage hints
    parts.append(
        "[Hermes] Use /usage for token consumption and model info. "
        "Use hermes insights --days 7 for weekly analytics. "
        "Use session_search to recall past decisions."
    )

    # MCP tool index recommendations
    if message and cwd:
        index = _load_mcp_index(cwd)
        if index:
            ranked = _find_relevant_tools(message, index, top_n=5)
            if ranked:
                tools_str = ", ".join(
                    f"{name} ({', '.join(tags_for_display(name, index))})"
                    for name, _ in ranked[:5]
                )
                # Keep under 300 chars to avoid prompt bloat
                hint = f"[ai-badger] Relevant MCP tools: {tools_str}"
                if len(hint) > 300:
                    # Truncate to top 3
                    tools_str_short = ", ".join(
                        f"{name}" for name, _ in ranked[:3]
                    )
                    hint = f"[ai-badger] Relevant MCP tools: {tools_str_short}"
                parts.append(hint)

    if not parts:
        return None
    return {"context": "\n".join(parts)}


def tags_for_display(tool_name: str, index: dict[str, Any]) -> list[str]:
    """Helper to look up tags for a tool in the index. Used in pre_llm_inject_context."""
    if ":" in tool_name:
        sname, tname = tool_name.split(":", 1)
        for server in index.get("sources", []):
            if server["name"] == sname:
                tool = server.get("tools", {}).get(tname, {})
                return tool.get("tags", [])
    return []


# ---------------------------------------------------------------------------
# Tool call observer — equivalent to Claude's PostToolUse hook
# ---------------------------------------------------------------------------

def post_tool_observer(tool_name: str = "", result: str = "",
                        duration_ms: int = 0, cwd: str = "", **_kwargs: Any) -> None:
    """Observe tool calls for debugging and metrics.

    Fires after every tool execution. Logs at DEBUG level so it doesn't flood
    the console. Enable by setting LOG_LEVEL=DEBUG on the ai_badger_hooks logger.
    """
    logger.debug(
        "tool=%s duration_ms=%d result_len=%d",
        tool_name, duration_ms, len(result) if result else 0,
    )

    # Log index hit/miss metrics if the index is available
    if cwd and tool_name:
        index = _load_mcp_index(cwd)
        if index:
            # Check if this tool exists in the index
            sname, _, tname = tool_name.partition(":") if ":" in tool_name else ("", "", tool_name)
            if not sname:
                sname = tool_name
            for server in index.get("sources", []):
                if server["name"] == sname:
                    known = tname in server.get("tools", {}) if tname else False
                    logger.debug("mcp_index_hit=%s tool=%s", known, tool_name)
                    break


# ---------------------------------------------------------------------------
# Plugin entry point — called by Hermes plugin loader
# ---------------------------------------------------------------------------

def register(ctx: Any) -> None:
    """Register all ai-badger hooks with the Hermes plugin system.

    The `ctx` object provides ctx.register_hook(name, callback).
    All callbacks accept **kwargs for forward compatibility — new
    parameters added in future Hermes versions won't break this plugin.
    """
    ctx.register_hook("on_session_start", on_session_start_drift_notice)
    ctx.register_hook("pre_llm_call", pre_llm_inject_context)
    ctx.register_hook("post_tool_call", post_tool_observer)
    logger.info("ai-badger hooks registered: on_session_start, pre_llm_call, post_tool_call")