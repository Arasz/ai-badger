#!/usr/bin/env python3
"""auto-wm CLI: partner/away/disable/status/decision for autonomic work mode (AWM).

Two modes:
  - partner (default): tool calls auto-approve, but you're around, so
    AskUserQuestion is left untouched. Bounded by a maximum lifetime.
  - away: same auto-approval, but AskUserQuestion is denied (no one is
    around to answer) and the window expires on wall-clock time.

Both modes record the project they were enabled in; the gate refuses to
auto-approve calls made from anywhere else.

State lives at ~/.claude/awm/state.json (user level, never inside a project).
Every mode change and registered decision is appended to ~/.claude/awm/decisions.jsonl.
"""
# pylint: disable=missing-function-docstring
# Ported verbatim from the originating job-search-ai-assistant repo's auto-wm skill: kept in
# lockstep with that source rather than churned for local docstring/style rules.
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"
MAX_DECISION_LINES = 5000
DEFAULT_AWAY_DURATION = "4h"
DEFAULT_PARTNER_DURATION = "8h"
# No auto-approval window is open-ended: an unattended one is capped here, and the gate
# re-checks the wall clock on every call.
MAX_DURATION_SECONDS = 12 * 3600

DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")


def parse_duration(text):
    """'4h', '90m', '1h30m', or bare number (hours) -> seconds."""
    text = text.strip().lower()
    if text.isdigit():
        return int(text) * 3600
    m = DURATION_RE.match(text)
    if not m or (m.group(1) is None and m.group(2) is None):
        raise ValueError(f"cannot parse duration {text!r} (use e.g. 4h, 90m, 1h30m)")
    seconds = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return seconds


def now_utc():
    return datetime.now(timezone.utc)


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def write_state(state):
    AWM_DIR.mkdir(parents=True, exist_ok=True)
    _own_only(AWM_DIR)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    _own_only(STATE_FILE)


def _own_only(path):
    """0600 for a file, 0700 for a directory. This state says where you work and what ran."""
    try:
        path.chmod(0o700 if path.is_dir() else 0o600)
    except OSError:
        pass


def log_event(event_type, detail):
    AWM_DIR.mkdir(parents=True, exist_ok=True)
    _own_only(AWM_DIR)
    entry = {"ts": now_utc().isoformat(timespec="seconds"), "type": event_type, "detail": detail}
    with DECISIONS_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    _own_only(DECISIONS_FILE)
    _trim_decisions()


def _trim_decisions():
    """Keep the newest MAX_DECISION_LINES entries. An unbounded audit log is its own risk."""
    try:
        lines = DECISIONS_FILE.read_text().splitlines(keepends=True)
    except OSError:
        return
    if len(lines) <= MAX_DECISION_LINES:
        return
    try:
        DECISIONS_FILE.write_text("".join(lines[-MAX_DECISION_LINES:]))
        _own_only(DECISIONS_FILE)
    except OSError:
        pass


def fmt_local(iso):
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def fmt_remaining(expires_at):
    delta = datetime.fromisoformat(expires_at) - now_utc()
    total = int(delta.total_seconds())
    if total <= 0:
        return "expired"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m remaining"


def capped_duration(duration_text):
    """Parse a duration and clamp it to MAX_DURATION_SECONDS. Returns (seconds, text)."""
    seconds = parse_duration(duration_text)
    if seconds <= MAX_DURATION_SECONDS:
        return seconds, duration_text
    print(f"AWM: {duration_text} exceeds the {MAX_DURATION_SECONDS // 3600}h maximum; "
          f"capping the window.")
    return MAX_DURATION_SECONDS, f"{MAX_DURATION_SECONDS // 3600}h"


def _enable(mode, duration_text):
    """Write an enabled, project-scoped, wall-clock-bounded state. Returns it."""
    seconds, duration_text = capped_duration(duration_text)
    prev_state = load_state() or {}
    prev_mode = prev_state.get("mode") if prev_state.get("enabled") else None
    enabled_at = now_utc()
    expires_at = enabled_at + timedelta(seconds=seconds)
    state = {
        "enabled": True,
        "mode": mode,
        "project": str(Path.cwd()),
        "enabled_at": enabled_at.isoformat(timespec="seconds"),
        "duration": duration_text,
        "duration_seconds": seconds,
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }
    write_state(state)
    detail = (f"mode={mode}, project={state['project']}, duration={duration_text}, "
              f"expires_at={state['expires_at']}")
    if prev_mode and prev_mode != mode:
        detail += f" (switched from {prev_mode})"
    log_event("mode_enabled", detail)
    return state


def cmd_partner(duration_text=DEFAULT_PARTNER_DURATION):
    state = _enable("partner", duration_text)
    print(f"AWM: partner mode enabled for {state['duration']} in {state['project']}, "
          f"expires {fmt_local(state['expires_at'])}.")
    print("Tool calls auto-approve and are logged to ~/.claude/awm/decisions.jsonl; "
          "questions still come to you normally.")


def cmd_away(duration_text):
    state = _enable("away", duration_text)
    print(f"AWM: away mode enabled for {state['duration']} in {state['project']}, "
          f"expires {fmt_local(state['expires_at'])}.")
    print("Tool calls auto-approve and are logged; AskUserQuestion is denied (no one to answer).")


def cmd_disable(reason="user"):
    state = load_state() or {}
    if not state.get("enabled"):
        print("AWM is not active.")
        return
    state["enabled"] = False
    state["disabled_at"] = now_utc().isoformat(timespec="seconds")
    state["disabled_reason"] = reason
    write_state(state)
    log_event("mode_disabled", f"reason={reason}")
    print("AWM disabled. Normal approvals resume.")


def cmd_status():
    state = load_state()
    if not state or not state.get("enabled"):
        print("AWM: inactive.")
        if state and state.get("disabled_at"):
            reason = state.get("disabled_reason", "?")
            print(f"Last disabled {fmt_local(state['disabled_at'])} (reason: {reason}).")
        return
    mode = state.get("mode", "away").upper()  # older state files predate the mode field
    scope = state.get("project") or "unset — the gate will refuse; re-enable to scope it"
    if not state.get("expires_at"):
        print(f"AWM: {mode} state records no expiry; the gate will refuse it. Re-enable.")
        return
    if now_utc() >= datetime.fromisoformat(state["expires_at"]):
        print(f"AWM: {mode} mode EXPIRED at {fmt_local(state['expires_at'])} "
              "(hooks will flip it off on next event).")
        return
    print(f"AWM: {mode} since {fmt_local(state['enabled_at'])}, "
          f"expires {fmt_local(state['expires_at'])} ({fmt_remaining(state['expires_at'])}).")
    print(f"Scope: {scope}")


def cmd_decision(text):
    log_event("decision", text)
    print("Decision registered.")


def main(argv):
    cmd = argv[0] if argv else "partner"
    if cmd in ("enable", "partner"):
        try:
            cmd_partner(argv[1] if len(argv) > 1 else DEFAULT_PARTNER_DURATION)
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
    elif cmd == "away":
        try:
            cmd_away(argv[1] if len(argv) > 1 else DEFAULT_AWAY_DURATION)
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
    elif cmd in ("disable", "off", "stop"):
        cmd_disable()
    elif cmd == "status":
        cmd_status()
    elif cmd == "decision":
        if len(argv) < 2 or not argv[1].strip():
            print("usage: awm.py decision \"<what was decided and why>\"", file=sys.stderr)
            return 1
        cmd_decision(" ".join(argv[1:]))
    else:
        print(f"unknown command {cmd!r}; use partner [duration] | away [duration] | disable | "
              "status | decision <text>", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
