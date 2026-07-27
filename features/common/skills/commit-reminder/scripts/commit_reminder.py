"""Pure logic for the commit-reminder skill: parse `git status --porcelain`, recognize an
edit-shaped tool call, and debounce the nudge with a per-project marker persisted outside
any scaffolded repo (a state file inside the measured repo would inflate its own count).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

STATE_FILE = Path.home() / ".ai-badger" / "commit-reminder" / "state.json"

_EDIT_TOOL_NAMES = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_HERMES_EDIT_SUBSTRINGS = ("write", "edit", "patch", "replace")


def _strip_quotes(path: str) -> str:
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        return path[1:-1]
    return path


def parse_porcelain(text: str) -> List[str]:
    """Parse `git status --porcelain` output into a list of file paths."""
    if not text or not text.strip():
        return []
    files: List[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        path = line[3:] if len(line) > 3 else ""
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        files.append(_strip_quotes(path))
    return files


def is_edit_tool(tool_name) -> bool:
    """True for Claude/Copilot's edit tool names, or a permissive Hermes lowercase match."""
    if tool_name is None:
        return False
    if tool_name in _EDIT_TOOL_NAMES:
        return True
    if not isinstance(tool_name, str) or tool_name != tool_name.lower():
        return False
    return any(sub in tool_name for sub in _HERMES_EDIT_SUBSTRINGS)


def should_remind(count: int, marker: int, threshold: int = 5) -> Tuple[bool, int]:
    """Debounce ratchet: fire once per threshold-crossing, re-arm as soon as count drops.

    If ``count`` falls below ``marker`` (a commit happened), ``marker`` ratchets down to
    ``count`` immediately so a later re-crossing of ``threshold`` fires again — it never
    stays stuck true forever the way a set-only flag would.
    """
    marker = min(marker, count)
    fires = count >= threshold and count > marker
    if fires:
        marker = count
    return fires, marker


def uncommitted_files(root: str, timeout: float = 5.0) -> List[str]:
    """Run `git status --porcelain` in ``root``; `[]` on any failure, never raises."""
    try:
        result = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return parse_porcelain(result.stdout)


def load_state() -> Dict[str, int]:
    """Load the marker state file; `{}` on missing file, read error, or malformed JSON."""
    try:
        raw = STATE_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: Dict[str, int]) -> None:
    """Persist the marker state file, creating parent directories as needed."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def get_marker(root: str) -> int:
    """Return the persisted marker for ``root``, or 0 if never seen."""
    key = str(Path(root).resolve())
    value = load_state().get(key, 0)
    return value if isinstance(value, int) else 0


def set_marker(root: str, marker: int) -> None:
    """Persist ``marker`` for ``root``, keyed by its resolved absolute path."""
    key = str(Path(root).resolve())
    state = load_state()
    state[key] = marker
    save_state(state)
