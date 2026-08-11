"""Follow-through detection — passive implicit-feedback measurement.

After memory_search: stash {correlationId, sourceFiles, ts}.
After read_file: check the stash for a path match within a 60 s window.
Match -> write follow_through_count/files to the search_quality table.

Extracted from ai_badger_hooks.py to keep the file under the 1000-line cap.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict

# In-memory stash of recent search results for follow-through correlation.
# Keyed by project path; entries expire after FOLLOW_THROUGH_WINDOW seconds.
_RECENT_SEARCHES: Dict[str, list] = {}
FOLLOW_THROUGH_WINDOW = 60  # seconds


def _is_memory_search(tool_name: Any) -> bool:
    """True for any naming spelling of the memory_search tool. Duplicated from ai_badger_hooks."""
    if not isinstance(tool_name, str):
        return False
    name = tool_name
    if name.startswith("mcp__"):
        name = name[len("mcp__"):].split("__", 1)[-1]
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    return name == "memory_search"


def _is_read_file(tool_name: Any) -> bool:
    """True for file-reading tool names across agents (Hermes/Claude/Copilot)."""
    if not isinstance(tool_name, str):
        return False
    name = tool_name
    if name.startswith("mcp__"):
        name = name[len("mcp__"):].split("__", 1)[-1]
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    return name in ("read_file", "Read", "ReadFile", "readfile")


def stash_search_sources(tool_name: str, result: str, cwd: str,
                         debug_fn=None) -> None:
    """After memory_search, stash {correlationId, sourceFiles, timestamp} for follow-through."""
    if not _is_memory_search(tool_name):
        return
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        return
    if not isinstance(data, dict):
        return
    meta = data.get("meta") or data.get("Meta") or {}
    corr_id = meta.get("correlationId") or meta.get("CorrelationId") or ""
    if not corr_id:
        return
    search_results = data.get("results") or data.get("data") or []
    source_files = []
    for r in search_results:
        sf = r.get("sourceFile") or r.get("SourceFile")
        if sf and sf not in source_files:
            source_files.append(sf)
    if not source_files:
        return
    project = cwd or os.getcwd()
    now = time.time()
    entry = {"correlationId": corr_id, "sourceFiles": source_files, "ts": now}
    _RECENT_SEARCHES.setdefault(project, []).append(entry)
    _RECENT_SEARCHES[project] = [
        e for e in _RECENT_SEARCHES[project] if now - e["ts"] < FOLLOW_THROUGH_WINDOW * 2
    ]
    if debug_fn:
        debug_fn("ai_badger_hooks/follow_through", "stashed",
                 project=project, corr_id=corr_id, files=len(source_files))


def maybe_record_follow_through(tool_name: str, result: str, cwd: str,
                                debug_fn=None) -> None:
    """After read_file, check if the path matches a recent search result's sourceFile."""
    if not _is_read_file(tool_name):
        return
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    file_path = data.get("path") or data.get("filePath") or data.get("file_path") or ""
    if not file_path:
        return
    file_path = str(Path(file_path).resolve())
    project = cwd or os.getcwd()
    now = time.time()
    entries = _RECENT_SEARCHES.get(project, [])
    for entry in entries:
        if now - entry["ts"] > FOLLOW_THROUGH_WINDOW:
            continue
        for sf in entry["sourceFiles"]:
            try:
                sf_resolved = str(Path(sf).resolve())
            except (ValueError, OSError):
                continue
            if file_path == sf_resolved or file_path.startswith(sf_resolved + os.sep):
                _record_follow_through_sql(entry["correlationId"], sf)
                if debug_fn:
                    debug_fn("ai_badger_hooks/follow_through", "recorded",
                             project=project, corr_id=entry["correlationId"], file=sf)
                return  # first match wins


def _record_follow_through_sql(correlation_id: str, file_path: str) -> None:
    """Write follow-through directly to the search_quality table via SQLite. Best-effort."""
    db_path = Path.home() / ".ai-raccoon" / "memory.db"
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT follow_through_files FROM search_quality WHERE correlation_id = ?",
                (correlation_id,)
            ).fetchone()
            if row is None:
                return
            existing = row[0] or "[]"
            try:
                files = json.loads(existing)
            except (ValueError, TypeError):
                files = []
            if not isinstance(files, list):
                files = []
            if file_path not in files:
                files.append(file_path)
            conn.execute(
                "UPDATE search_quality SET follow_through_count = ?, "
                "follow_through_files = ? WHERE correlation_id = ?",
                (len(files), json.dumps(files), correlation_id)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:  # pylint: disable=broad-exception-caught
        pass
