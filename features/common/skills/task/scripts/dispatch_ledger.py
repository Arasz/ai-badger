"""Per-session ledger of recent Agent dispatches, so a gate can tell fan-out from a lone lane.

Append-only with a time window rather than PreToolUse/PostToolUse pairing: pairing would
track an agent's real lifetime but depends on `PostToolUse` firing for `Agent`, and a
missed pair leaves a stale entry that wedges the gate closed for every later dispatch. A
window cannot wedge — entries age out on their own. It catches what matters because
parallel dispatch is expressed as several `Agent` calls in one assistant message, so
siblings land milliseconds apart.

Every read fails open (0 siblings): a gate that cannot read its own state must allow.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

LEDGER_DIR = Path.home() / ".ai-badger" / "dispatch-lanes"

# Entries older than this are dropped when the file is next written. Only a housekeeping
# bound on file size — the window passed to concurrent() is what decides parallelism.
PRUNE_SECONDS = 3600.0

# How long a recorded dispatch keeps counting as a live lane. Unmeasured: it stands in for
# "is that agent still running", which only a PostToolUse pairing could answer exactly.
# Too short misses a sibling that is genuinely still running; too long denies a dispatch
# whose sibling has already finished. The cost of the second is one retry carrying
# isolation="worktree" — which is the right call anyway — so this errs long. If Agent turns
# out to fire PostToolUse reliably, releasing the entry there makes the window a fallback
# rather than the primary signal, and the number stops mattering.
DEFAULT_WINDOW_SECONDS = 90.0


def _safe_session(session_id: Optional[str]) -> str:
    """Session id made filesystem-safe; the empty string is not a valid ledger.

    Keeps [A-Za-z0-9._-]; substitutes '_' for everything else, and guards the dot-only
    traversal segments. Same rule as the memory-first gate's marker names.
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
    """Parsed `<ts> <tool_use_id>` lines; unreadable or malformed input yields nothing."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
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


def record(session_id: Optional[str], tool_use_id: str, now: Optional[float] = None) -> bool:
    """Append this dispatch to its session's ledger, pruning anything past PRUNE_SECONDS.

    False on a missing session id or IO failure — recording is best-effort, and a failure
    to record can only ever make the gate quieter.
    """
    path = ledger_path(session_id)
    if not path.name or not tool_use_id:
        return False
    stamp = time.time() if now is None else now
    kept = [entry for entry in _entries(path) if stamp - entry[0] <= PRUNE_SECONDS]
    kept.append((stamp, str(tool_use_id)))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(f"{ts} {tid}\n" for ts, tid in kept), encoding="utf-8")
        return True
    except OSError:
        return False


def concurrent(session_id: Optional[str], tool_use_id: str,
               now: Optional[float] = None, window: float = DEFAULT_WINDOW_SECONDS) -> int:
    """How many *other* dispatches this session recorded inside `window` seconds.

    Counts distinct tool_use_ids so a retried dispatch never counts as its own sibling.
    """
    path = ledger_path(session_id)
    if not path.name:
        return 0
    stamp = time.time() if now is None else now
    siblings = {
        tid for ts, tid in _entries(path)
        if tid != str(tool_use_id) and stamp - ts <= window
    }
    return len(siblings)
