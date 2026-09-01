#!/usr/bin/env python3
"""Message-bus delivery hook: inject the session's unread bus mail into its context.

The ONE delivery surface for every hook-shaped harness: Claude (UserPromptSubmit /
SessionStart / SessionEnd), Copilot (userPromptSubmitted / sessionStart), and pi via the
adapter's child-process bridge all speak the same Claude-shaped contract —

    stdin:  {"hook_event_name": "...", "session_id": "...", "cwd": "..."}
    stdout: {"hookSpecificOutput": {"hookEventName": "...", "additionalContext": "..."}}

Delivery events (SessionStart, UserPromptSubmit, either harness's spelling) call
``Store.deliver_for_session`` — exactly-once + the 30-minute first-read gate + the
16-message start cap are the store's one transaction, not this script's (P1); the
cursor-less per-turn read applies that gate once too (D5). Close events (SessionEnd)
drop the session's cursor (R6). Everything else is a no-op.

``additionalContext`` carries one schema-conformant message document per line
(``schemas/message.schema.json``, F4) in chronological order — render_messages is the
seam P9-t1 asserts through. An empty inbox injects nothing: the response is ``{}``.

Fail-open (D31): any store, registry or input failure exits 0 with parseable no-op
JSON — a broken bus must never break a session. The only trace is one content-free
line in the operator's hook-error log, because a hook that dies quietly is
indistinguishable from one that did its job.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_store  # pylint: disable=wrong-import-position

#: Events that deliver mail. Claude's spellings plus Copilot's (sessionStart /
#: userPromptSubmitted) — one surface, per-harness event names, matched case-insensitively.
DELIVERY_EVENTS = frozenset({"sessionstart", "userpromptsubmit", "userpromptsubmitted"})

#: Events that end a session: drop the cursor (R6). Copilot's sessionEnd is wired for this
#: too (P8's verdict: the event exists — tooling/validate.py, changelog 0.50.0), so its
#: lowercase spelling routes here like Claude's; unwired harnesses' cursors die by the 4-day
#: TTL.
CLOSE_EVENTS = frozenset({"sessionend"})

#: The project directory env Claude sets for hook commands. Preferred over the payload's
#: cwd for ADDRESSING — it is the project the session belongs to and stays stable while
#: a session cd-wanders; the payload cwd is the fallback for harnesses that carry no env.
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"


def _event_name(payload: Dict[str, Any]) -> Optional[str]:
    """The harness's own event spelling, echoed verbatim in the response."""
    value = payload.get("hook_event_name") or payload.get("hookEventName")
    return value if isinstance(value, str) and value.strip() else None


def _session_id(payload: Dict[str, Any]) -> Optional[str]:
    """The session's id — the cursor's identity; blank or non-string is no session."""
    value = payload.get("session_id") or payload.get("sessionId")
    return value if isinstance(value, str) and value.strip() else None


def _probe_cwd(payload: Dict[str, Any]) -> Optional[str]:
    """The directory the project id resolves from: $CLAUDE_PROJECT_DIR, else payload cwd."""
    env_root = os.environ.get(PROJECT_DIR_ENV)
    if env_root:
        return env_root
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd.strip() else None


def _resolve_project(payload: Dict[str, Any]) -> Optional[str]:
    """The cwd resolver (D4) — its explicit-override env wins inside it. Its two DESIGNED
    refusals (nothing matches, several match) degrade to 1:1-only delivery (D7); an
    unexpected registry error is not designed and propagates to the fail-open net."""
    try:
        return badger_store.resolve_project_id(_probe_cwd(payload))
    except badger_store.ProjectIdAmbiguous:
        return None


def render_messages(messages: list) -> str:
    """The injected context: ONE message document per line, chronological, verbatim —
    each line parses to the exact document the store returned and validates clean
    against schemas/message.schema.json (F4; the seam P9-t1 asserts through)."""
    return "\n".join(json.dumps(message, ensure_ascii=False) for message in messages)


def build_response(event_name: Optional[str], context: str) -> dict:
    """The hook's whole reply: additionalContext when there is mail, ``{}`` when not —
    never any coercing key (decision/continue): a delivery hook is advisory only."""
    if not context:
        return {}
    inner: Dict[str, Any] = {"additionalContext": context}
    if event_name:
        inner["hookEventName"] = event_name
    return {"hookSpecificOutput": inner}


def _deliver(event_name: Optional[str], session_id: str, payload: Dict[str, Any]) -> dict:
    """One store transaction: read + cursor advance (the store's; index-bounded, D6)."""
    project_id = _resolve_project(payload)
    store = badger_store.open_user()
    try:
        messages = store.deliver_for_session(session_id, project_id)
    finally:
        store.close()
    return build_response(event_name, render_messages(messages))


def _close(event_name: Optional[str], session_id: str) -> dict:
    """The close event's cleanup: drop the cursor (R6); a second close is harmless."""
    store = badger_store.open_user()
    try:
        store.delete_cursor(session_id)
    finally:
        store.close()
    return {}


def main() -> int:
    """One firing: parse, route by event, print one JSON response — every path prints."""
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        payload = {}
    event_name = _event_name(payload)
    session_id = _session_id(payload)
    kind = (event_name or "").strip().lower()
    if session_id and kind in DELIVERY_EVENTS:
        response = _deliver(event_name, session_id, payload)
    elif session_id and kind in CLOSE_EVENTS:
        response = _close(event_name, session_id)
    else:
        response = {}
    print(json.dumps(response))
    return 0


HOOK_ERRORS_FILE = Path.home() / ".ai-badger" / "hook-errors.log"
MAX_ERROR_LOG_BYTES = 1_000_000


def record_hook_failure(where: str) -> None:
    """Leave one content-free line behind before the net swallows an exception.

    Type and location only: an exception message can quote scanned input.
    """
    exc_type, _, tb = sys.exc_info()
    frame = traceback.extract_tb(tb)[-1] if tb else None
    at = f"{Path(frame.filename).name}:{frame.lineno}" if frame else "unknown"
    name = exc_type.__name__ if exc_type else "Unknown"
    print(f"[ai-badger] {where} hook failed: {name} at {at}", file=sys.stderr)
    try:
        HOOK_ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if HOOK_ERRORS_FILE.exists() and HOOK_ERRORS_FILE.stat().st_size > MAX_ERROR_LOG_BYTES:
            HOOK_ERRORS_FILE.unlink()
        with HOOK_ERRORS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {where} {name} at {at}\n")
    except OSError:
        pass


def guarded_main() -> int:
    """Run main(): a hook never breaks the session, but never fails invisibly either —
    the failure line goes to the log, and the host still gets parseable no-op JSON."""
    try:
        return main() or 0
    except Exception:  # pylint: disable=broad-exception-caught
        record_hook_failure("message_delivery_hook")
        try:
            print("{}")
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
