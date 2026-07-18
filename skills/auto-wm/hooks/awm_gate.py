#!/usr/bin/env python3
"""PreToolUse hook for autonomic work mode (AWM).

While ~/.claude/awm/state.json is enabled, every tool call auto-approves
(permissionDecision: allow) and is registered in ~/.claude/awm/decisions.jsonl.
The two modes only differ on AskUserQuestion and on expiry:

  - partner: AskUserQuestion passes through untouched (you're around to
    answer). No expiry check — indefinite until switched or disabled.
  - away: AskUserQuestion is denied (no one to answer) and the window
    expires on wall-clock time, checked here on every call.

Outside AWM (or on any internal error) it emits nothing and exits 0, so the
normal permission flow is untouched.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"
MAX_DETAIL_LEN = 300


def now_utc():
    return datetime.now(timezone.utc)


def log_event(event_type, detail, session_id=None, cwd=None, tool_name=None):
    entry = {"ts": now_utc().isoformat(timespec="seconds"), "type": event_type}
    if tool_name:
        entry["tool_name"] = tool_name
    if session_id:
        entry["session_id"] = session_id
    if cwd:
        entry["cwd"] = cwd
    entry["detail"] = detail
    with DECISIONS_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def summarize_input(tool_input):
    text = json.dumps(tool_input, ensure_ascii=False) if tool_input else "{}"
    return text[:MAX_DETAIL_LEN] + ("…" if len(text) > MAX_DETAIL_LEN else "")


def emit(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


def main():
    payload = json.load(sys.stdin)
    state = json.loads(STATE_FILE.read_text())
    if not state.get("enabled"):
        return

    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    tool_name = payload.get("tool_name", "?")
    mode = state.get("mode", "away")  # older state files predate the mode field

    if mode == "away":
        expires_at = state.get("expires_at")
        if expires_at and now_utc() >= datetime.fromisoformat(expires_at):
            state["enabled"] = False
            state["disabled_at"] = now_utc().isoformat(timespec="seconds")
            state["disabled_reason"] = "expired"
            STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
            log_event("mode_expired", f"expired_at={expires_at}", session_id, cwd)
            return  # no output -> normal permission flow resumes

        expires_local = datetime.fromisoformat(expires_at).astimezone().strftime("%H:%M") if expires_at else "?"

        if tool_name == "AskUserQuestion":
            log_event("question_denied", summarize_input(payload.get("tool_input")),
                      session_id, cwd, tool_name)
            emit("deny",
                 f"AWM away mode is active until {expires_local}: no user is available "
                 "to answer. Do not ask — pick the best option yourself, then register the choice "
                 "and reasoning with: python3 ~/.claude/skills/auto-wm/scripts/awm.py decision \"...\" "
                 "and continue working.")
            return

        log_event("auto_approve", summarize_input(payload.get("tool_input")),
                  session_id, cwd, tool_name)
        emit("allow", f"AWM away mode active until {expires_local}: auto-approved and registered in decisions.jsonl")
        return

    # partner mode: leave AskUserQuestion alone, auto-approve everything else, no expiry.
    if tool_name == "AskUserQuestion":
        return

    log_event("auto_approve", summarize_input(payload.get("tool_input")),
              session_id, cwd, tool_name)
    emit("allow", "AWM partner mode active: auto-approved and registered in decisions.jsonl")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break the session; absence of output means normal flow
    sys.exit(0)