"""Memory-grade hook logic: match memory_search calls, gate on AI_BADGER_MEMORY_GRADE=1,
append one JSONL line per search to a machine-wide quality log, and stash the grade ask.
Default OFF (absent/unset/0/garbage): no reads, no writes, no injection."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ENABLED_ENV = "AI_BADGER_MEMORY_GRADE"
LOG_FILE = Path.home() / ".ai-badger" / "memory-grade" / "memory-quality.jsonl"
PENDING_FILE = Path.home() / ".ai-badger" / "memory-grade" / "pending.json"
# The helper's own absolute path, so every deployment shape asks for its own copy.
HELPER = Path(__file__).resolve()

_SEARCH_TOOL = "memory_search"
_MCP_PREFIX = "mcp__"
_DOUBLE_UNDERSCORE = "__"


def enabled() -> bool:
    """True when AI_BADGER_MEMORY_GRADE is exactly "1" (anything else is off)."""
    return os.environ.get(ENABLED_ENV, "") == "1"


def is_memory_search(tool_name: Any) -> bool:
    """True for any naming spelling of the memory_search tool; never matches other tools."""
    if not isinstance(tool_name, str):
        return False
    name = tool_name
    if name.startswith(_MCP_PREFIX):
        name = name[len(_MCP_PREFIX):].split(_DOUBLE_UNDERSCORE, 1)[-1]
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    return name == _SEARCH_TOOL


def _now_iso() -> str:
    """UTC timestamp with microseconds; unique per line and the grade pointer."""
    return datetime.now(timezone.utc).isoformat()


def _result_payload(result: Any) -> Any:
    """The parsed tool result, or {"raw": result} when it is not JSON."""
    if isinstance(result, (dict, list, int, float, bool)) or result is None:
        return result
    if isinstance(result, bytes):
        try:
            result = result.decode("utf-8")
        except UnicodeDecodeError:
            return {"raw": str(result)}
    if isinstance(result, str):
        try:
            return json.loads(result)
        except ValueError:
            return {"raw": result}
    return {"raw": str(result)}


def _build_line(args: Dict[str, Any], result: Any) -> Dict[str, Any]:
    """One JSONL line; key spellings are read defensively (F4), workspace null when absent."""
    return {
        "ts": _now_iso(),
        "query": args.get("query", ""),
        "scope": args.get("scope", "all"),
        "projectId": args.get("projectId", args.get("project_id", "")),
        "workspaceId": args.get("workspaceId", args.get("workspace_id")),
        "result": _result_payload(result),
        "usefulness": None,
        "note": None,
    }


def _append_log(line: Dict[str, Any]) -> None:
    """Append one line, creating the log's parent directory lazily."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def _ask_text(ts: str) -> str:
    """The one-line grade ask; ts is the exact log-line pointer to grade."""
    return (f"[ai-badger] Rate that memory_search's usefulness 1-5 (5=best, or skip): "
            f"python3 {HELPER} grade {ts} <1-5> [note]")


def _load_pending() -> Dict[str, str]:
    """Load the pending-ask file; {} on missing file, read error, or malformed JSON."""
    try:
        raw = PENDING_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_pending(pending: Dict[str, str]) -> None:
    """Persist the pending-ask file, creating parent directories as needed."""
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(pending), encoding="utf-8")


def _set_pending(project: str, ask: str) -> None:
    """Stash the ask keyed by the project's resolved absolute path (last wins)."""
    pending = _load_pending()
    pending[str(Path(project).resolve())] = ask
    _save_pending(pending)


def log_search(args: Dict[str, Any], result: Any, cwd: str) -> Optional[str]:
    """Append one line for a memory_search call and stash the ask; the ask text back.

    Returns None when disabled: no reads, no writes, nothing to inject.
    """
    if not enabled():
        return None
    line = _build_line(args, result)
    ts = line["ts"]
    _append_log(line)
    ask = _ask_text(ts)
    _set_pending(cwd, ask)
    return ask


def pop_ask(project: str) -> Optional[str]:
    """Return and clear the pending grade ask for project, or None (also when disabled)."""
    if not enabled():
        return None
    pending = _load_pending()
    key = str(Path(project).resolve())
    ask = pending.pop(key, None)
    if ask is not None:
        _save_pending(pending)
    return ask
