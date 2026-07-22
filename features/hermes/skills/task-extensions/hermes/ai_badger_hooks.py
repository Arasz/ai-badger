"""Hermes plugin hooks for ai-badger framework integration.

Provides feature-parity with Claude Code hooks:
- on_session_start: drift notice (Tier 1, ADR-0001 decision 5)
- pre_llm_call: inject framework version context and usage hints
- post_tool_call: log tool usage for session tracking (equivalent to Claude's
  statusline capture, but adapted for Hermes's native tooling)

Installation: copy/symlink this file to ~/.hermes/plugins/ai_badger_hooks.py
or include it in a Hermes plugin package with a register() entry point.

The plugin self-locates the ai-badger framework root by walking ancestor
directories (same pattern as _bootstrap_lib in the scaffold scripts),
NOT via a hardcoded path or environment variable.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

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


def on_session_start_drift_notice(session_id: str = "", cwd: str = "",
                                   platform: str = "", **kwargs: Any) -> None:
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
# Context enrichment — equivalent to Claude's UserPromptSubmit hook
# ---------------------------------------------------------------------------

def pre_llm_inject_context(cwd: str = "", **kwargs: Any) -> Optional[Dict[str, str]]:
    """Inject ai-badger framework context into every LLM turn.

    Returns a context dict that Hermes prepends to the user message,
    or None to leave the prompt unchanged. This fires once per turn,
    before the tool-calling loop.

    What we inject:
    - Framework version info (so the agent knows which ai-badger features are available)
    - Drift notice if the project is behind
    - Hermes-specific usage hints (/usage, hermes insights, session_search)
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

    # Usage hints — equivalent to Claude's statusline info, adapted for Hermes
    parts.append(
        "[Hermes] Use /usage for token consumption and model info. "
        "Use hermes insights --days 7 for weekly analytics. "
        "Use session_search to recall past decisions."
    )

    if not parts:
        return None
    return {"context": "\n".join(parts)}


# ---------------------------------------------------------------------------
# Tool call observer — equivalent to Claude's PostToolUse hook
# ---------------------------------------------------------------------------

def post_tool_observer(tool_name: str = "", result: str = "",
                        duration_ms: int = 0, **kwargs: Any) -> None:
    """Observe tool calls for debugging and metrics.

    Fires after every tool execution. The `result` parameter is the tool's
    JSON return value. Use for audit logging, duration tracking, or
    detecting slow tool calls.

    Currently a no-op observer — logs at DEBUG level so it doesn't flood
    the console. Enable by setting LOG_LEVEL=DEBUG on the ai_badger_hooks
    logger.
    """
    logger.debug(
        "tool=%s duration_ms=%d result_len=%d",
        tool_name, duration_ms, len(result) if result else 0,
    )


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
