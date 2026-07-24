"""MCP index auto-update hooks for Hermes Agent.

Provides:
- on_session_start: initialize MCP tool index if .ai-badger/mcp-tools.yaml doesn't exist
- post_tool_call: detect MCP tool usage, trigger index rebuild if stale

Installation: copy/symlink this file to ~/.hermes/plugins/mcp_index_hook.py
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("mcp_index_hook")


def _find_project_root(cwd: Optional[str] = None) -> Optional[Path]:
    """Find the project root by looking for .ai-badger/ directory."""
    start = Path(cwd) if cwd else Path.cwd()
    for d in [start, *start.parents]:
        if (d / ".ai-badger").is_dir():
            return d
    return None


def _has_mcp_index(project_root: Path) -> bool:
    """Check if MCP tool index exists."""
    return (project_root / ".ai-badger" / "mcp-tools.yaml").exists()


def _rebuild_index(project_root: Path) -> bool:
    """Rebuild MCP tool index. Returns True if rebuild was attempted."""
    try:
        import subprocess
        result = subprocess.run(
            ["python3", str(project_root / ".ai-badger" / "skills" / "mcp-index" / "scripts" / "mcp_index_build.py"),
             "--target", str(project_root)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logger.info("MCP index rebuilt successfully")
            return True
        logger.warning("MCP index rebuild failed: %s", result.stderr)
        return False
    except Exception as exc:
        logger.warning("MCP index rebuild error: %s", exc)
        return False


def on_session_start(ctx: Any = None) -> None:
    """Initialize MCP index if it doesn't exist."""
    cwd = getattr(ctx, "cwd", None) if ctx else None
    project_root = _find_project_root(cwd)
    if project_root is None:
        return
    if not _has_mcp_index(project_root):
        logger.info("MCP index not found, initializing...")
        _rebuild_index(project_root)


def post_tool_call(tool_name: str, args: Any = None, result: Any = None,
                   duration_ms: float = 0, ctx: Any = None) -> None:
    """Detect MCP tool usage and trigger index rebuild if needed."""
    # Check if this was an MCP-related tool call
    is_mcp = False
    if tool_name and "mcp" in tool_name.lower():
        is_mcp = True
    elif isinstance(args, dict) and "command" in args:
        cmd = str(args.get("command", ""))
        if "mcp" in cmd.lower():
            is_mcp = True

    if not is_mcp:
        return

    cwd = getattr(ctx, "cwd", None) if ctx else None
    project_root = _find_project_root(cwd)
    if project_root is None:
        return

    logger.info("MCP tool usage detected, checking index...")
    _rebuild_index(project_root)
