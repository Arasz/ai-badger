"""Per-session ledger of recent Agent dispatches, so a gate can tell fan-out from a lone lane.

Append-only: one `O_APPEND` write per dispatch, counted within a time window. Every read
fails open (0 siblings) — a gate that cannot read its own state must allow.

Why a window and not PreToolUse/PostToolUse pairing, and why append rather than rewrite:
`docs/changelog/0.138.0-a-contract-with-no-gate-behind-it.md`.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

LEDGER_DIR = Path.home() / ".ai-badger" / "dispatch-lanes"

# Housekeeping only; the window passed to concurrent() is what decides parallelism.
PRUNE_SECONDS = 3600.0

# Rewriting is the one operation that can lose a concurrent append, so it waits for length.
PRUNE_ABOVE_ENTRIES = 500

# How long a recorded dispatch keeps counting as a live lane. UNMEASURED estimate standing
# in for "is that agent still running"; errs long. Tradeoff: `docs/changelog/0.138.0-a-contract-with-no-gate-behind-it.md`.
DEFAULT_WINDOW_SECONDS = 90.0


def _safe_session(session_id: Optional[str]) -> str:
    """Session id made filesystem-safe; the empty string is not a valid ledger.

    Keeps [A-Za-z0-9._-] and guards dot-only segments. Same rule as memory-first's markers.
    """
    if not session_id:
        return ""
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_" for ch in str(session_id)
    )
    if sanitized == ".":
        return "_"
    if sanitized == "..":
        return "__"
    return sanitized


def ledger_path(session_id: Optional[str]) -> Path:
    """The ledger file for a session (empty path when no session id)."""
    safe = _safe_session(session_id)
    return LEDGER_DIR / safe if safe else Path("")


def _entries(path: Path) -> list[tuple[float, str]]:
    """Parsed `<ts> <tool_use_id>` lines; unreadable or malformed input yields nothing.

    Catches `ValueError` too — `UnicodeDecodeError` is one, and it used to escape `record`.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    parsed: list[tuple[float, str]] = []
    for line in raw.splitlines():
        stamp, _, tool_use_id = line.partition(" ")
        if not tool_use_id:
            continue
        try:
            parsed.append((float(stamp), tool_use_id))
        except ValueError:
            continue
    return parsed


def _prune(path: Path, stamp: float) -> None:
    """Drop entries past PRUNE_SECONDS, only once the file exceeds PRUNE_ABOVE_ENTRIES.

    The one rewrite that can lose a concurrent append, so it stays off a fan-out's path.
    """
    entries = _entries(path)
    if len(entries) <= PRUNE_ABOVE_ENTRIES:
        return
    kept = [entry for entry in entries if 0 <= stamp - entry[0] <= PRUNE_SECONDS]
    try:
        path.write_text("".join(f"{ts} {tid}\n" for ts, tid in kept), encoding="utf-8")
    except OSError:
        return


def record(session_id: Optional[str], tool_use_id: str, now: Optional[float] = None) -> bool:
    """Append this dispatch to its session's ledger; False on no session id or IO failure.

    One `O_APPEND` write of one short line, which POSIX makes atomic below PIPE_BUF.
    """
    path = ledger_path(session_id)
    if not path.name or not tool_use_id:
        return False
    stamp = time.time() if now is None else now
    # A newline in the id would forge extra entries.
    tid = str(tool_use_id).replace("\n", "_").replace("\r", "_")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {tid}\n")
    except OSError:
        return False
    _prune(path, stamp)
    return True


def concurrent(session_id: Optional[str], tool_use_id: str,
               now: Optional[float] = None, window: float = DEFAULT_WINDOW_SECONDS) -> int:
    """How many *other* dispatches this session recorded inside `window` seconds.

    Counts distinct tool_use_ids so a retried dispatch never counts as its own sibling.
    """
    path = ledger_path(session_id)
    if not path.name:
        return 0
    stamp = time.time() if now is None else now
    # `0 <=` too: a backward clock step leaves entries ahead of now, counted forever.
    siblings = {
        tid for ts, tid in _entries(path)
        if tid != str(tool_use_id) and 0 <= stamp - ts <= window
    }
    return len(siblings)
