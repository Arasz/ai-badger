#!/usr/bin/env python3
"""PreToolUse hook for autonomic work mode (AWM).

While ~/.claude/awm/state.json is enabled, a tool call auto-approves
(permissionDecision: allow) and is registered in ~/.claude/awm/decisions.jsonl —
unless one of three guards fires first, in which case nothing is emitted and the
normal permission prompt reaches the human:

  - expiry: both modes carry a wall-clock expiry, re-checked on every call.
  - project scope: the state records the project it was enabled in; a call whose
    cwd is outside that tree is never auto-approved.
  - denylist: destructive shell commands, network egress and writes outside the
    project are never auto-approved, in either mode.

The two modes then differ only on AskUserQuestion:

  - partner: passes through untouched (you're around to answer).
  - away: denied (no one to answer).

Outside AWM (or on any internal error) it emits nothing and exits 0, so the
normal permission flow is untouched.
"""
# pylint: disable=missing-function-docstring,broad-exception-caught
# Ported verbatim from the originating job-search-ai-assistant repo's auto-wm skill: kept in
# lockstep with that source rather than churned for local docstring/style rules. The broad
# except below is intentional — a broken hook must never break the session's permission flow.
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"
MAX_DETAIL_LEN = 300

# Tools that reach outside the project or outside this machine. Never auto-approved.
DENIED_TOOLS = {"WebFetch", "WebSearch"}

# Tools whose target path must stay inside the project AWM was enabled in.
PATH_SCOPED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PATH_KEYS = ("file_path", "notebook_path", "path")

# Shell commands that are irreversible, escalate privilege, rewrite published history,
# execute network content, or install persistence. A human approves these, always.
DENIED_COMMAND_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\brm\s+(-\w+\s+)*-\w*[rf]",
    r"\b(sudo|doas|su)\b",
    r"\bgit\s+push\b[^|;&]*\s(--force|-f)\b",
    r"\bgit\s+(reset\s+--hard|clean\s+-\w*[fdx])\b",
    r"\b(mkfs|fdisk|diskutil)\b",
    r"\bdd\s+if=",
    r"\bchmod\s+(-\w+\s+)*777\b",
    r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k)?sh\b",
    r"\b(shutdown|reboot|halt|killall)\b",
    r"\bkill\s+-9\s+1\b",
    r":\s*\(\s*\)\s*\{.*\}\s*;\s*:",
    r"\bcrontab\b",
    r"\bhistory\s+-c\b",
)]


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


def within(root, path):
    """True when path is root itself or lives underneath it."""
    if not root or not path:
        return False
    try:
        base = Path(root).expanduser().resolve()
        candidate = Path(path).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return candidate == base or base in candidate.parents


def expired(state):
    """True when the window has run out — including a state file that records no expiry."""
    expires_at = state.get("expires_at")
    if not expires_at:
        return True
    return now_utc() >= datetime.fromisoformat(expires_at)


def denylist_reason(tool_name, tool_input, project):
    """Fixed-vocabulary reason this call may never be auto-approved, or None.

    The vocabulary is closed on purpose: no scanned byte reaches the decision log.
    """
    if tool_name in DENIED_TOOLS:
        return "denied_tool"
    if tool_name == "Bash":
        command = (tool_input or {}).get("command") or ""
        if any(pattern.search(command) for pattern in DENIED_COMMAND_PATTERNS):
            return "destructive_command"
        return None
    if tool_name in PATH_SCOPED_TOOLS:
        target = next((tool_input[k] for k in PATH_KEYS if (tool_input or {}).get(k)), None)
        if target and not within(project, target):
            return "write_outside_project"
    return None


def disable(state, reason, detail, session_id, cwd):
    """Flip the state off on disk and record why; the caller then emits nothing."""
    state["enabled"] = False
    state["disabled_at"] = now_utc().isoformat(timespec="seconds")
    state["disabled_reason"] = reason
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    log_event("mode_expired", detail, session_id, cwd)


def main():
    payload = json.load(sys.stdin)
    state = json.loads(STATE_FILE.read_text())
    if not state.get("enabled"):
        return

    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    tool_name = payload.get("tool_name", "?")
    tool_input = payload.get("tool_input")
    mode = state.get("mode", "away")  # older state files predate the mode field
    project = state.get("project")
    expires_at = state.get("expires_at")

    if expired(state):
        detail = f"expired_at={expires_at}" if expires_at else "no expiry recorded in state"
        disable(state, "expired", detail, session_id, cwd)
        return  # no output -> normal permission flow resumes

    # A window enabled in one project never speaks for another, and never for a
    # state file that predates project scoping.
    if not within(project, cwd):
        log_event("out_of_scope", f"project={project or 'unset'}", session_id, cwd, tool_name)
        return

    reason = denylist_reason(tool_name, tool_input, project)
    if reason:
        log_event("denylisted", reason, session_id, cwd, tool_name)
        return

    if mode == "away":
        expires_local = (
            datetime.fromisoformat(expires_at).astimezone().strftime("%H:%M") if expires_at else "?"
        )

        if tool_name == "AskUserQuestion":
            log_event("question_denied", summarize_input(payload.get("tool_input")),
                      session_id, cwd, tool_name)
            emit("deny",
                 f"AWM away mode is active until {expires_local}: no user is available "
                 "to answer. Do not ask — pick the best option yourself, then register the "
                 "choice and reasoning with: "
                 "python3 ~/.claude/skills/auto-wm/scripts/awm.py decision \"...\" "
                 "and continue working.")
            return

        log_event("auto_approve", summarize_input(payload.get("tool_input")),
                  session_id, cwd, tool_name)
        emit("allow",
             f"AWM away mode active until {expires_local}: auto-approved and registered "
             "in decisions.jsonl")
        return

    # partner mode: leave AskUserQuestion alone, auto-approve everything else.
    if tool_name == "AskUserQuestion":
        return

    log_event("auto_approve", summarize_input(payload.get("tool_input")),
              session_id, cwd, tool_name)
    emit("allow", "AWM partner mode active: auto-approved and registered in decisions.jsonl")


HOOK_ERRORS_FILE = Path.home() / ".ai-badger" / "hook-errors.log"
MAX_ERROR_LOG_BYTES = 1_000_000


def record_hook_failure(where):
    """Leave one content-free line behind before a hook swallows an exception.

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


def guarded_main():
    """Run main(): a hook never breaks the session, but never fails invisibly either."""
    try:
        return main() or 0
    except Exception:  # pylint: disable=broad-exception-caught
        record_hook_failure("awm_gate")
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
