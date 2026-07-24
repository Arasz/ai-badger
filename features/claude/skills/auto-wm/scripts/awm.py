#!/usr/bin/env python3
"""auto-wm CLI: partner/away/disable/status/decision for autonomic work mode (AWM).

Two modes:
  - partner (default): tool calls auto-approve, but you're around, so
    AskUserQuestion is left untouched. No expiry — stays on until you
    switch to away or disable.
  - away: same auto-approval, but AskUserQuestion is denied (no one is
    around to answer) and the window expires on wall-clock time.

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
DEFAULT_AWAY_DURATION = "4h"

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
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def log_event(event_type, detail):
    AWM_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"ts": now_utc().isoformat(timespec="seconds"), "type": event_type, "detail": detail}
    with DECISIONS_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def fmt_local(iso):
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def fmt_remaining(expires_at):
    delta = datetime.fromisoformat(expires_at) - now_utc()
    total = int(delta.total_seconds())
    if total <= 0:
        return "expired"
    return f"{total // 3600}h {(total % 3600) // 60:02d}m remaining"


def cmd_partner():
    prev_state = load_state() or {}
    prev_mode = prev_state.get("mode") if prev_state.get("enabled") else None
    enabled_at = now_utc()
    write_state({
        "enabled": True,
        "mode": "partner",
        "enabled_at": enabled_at.isoformat(timespec="seconds"),
        "duration": None,
        "duration_seconds": None,
        "expires_at": None,
    })
    detail = "mode=partner, no expiry"
    if prev_mode and prev_mode != "partner":
        detail += f" (switched from {prev_mode})"
    log_event("mode_enabled", detail)
    print("AWM: partner mode enabled (indefinite).")
    print("Tool calls auto-approve and are logged to ~/.claude/awm/decisions.jsonl; "
          "questions still come to you normally.")


def cmd_away(duration_text):
    seconds = parse_duration(duration_text)
    prev_state = load_state() or {}
    prev_mode = prev_state.get("mode") if prev_state.get("enabled") else None
    enabled_at = now_utc()
    expires_at = enabled_at + timedelta(seconds=seconds)
    write_state({
        "enabled": True,
        "mode": "away",
        "enabled_at": enabled_at.isoformat(timespec="seconds"),
        "duration": duration_text,
        "duration_seconds": seconds,
        "expires_at": expires_at.isoformat(timespec="seconds"),
    })
    expires_at_iso = expires_at.isoformat(timespec="seconds")
    detail = f"mode=away, duration={duration_text}, expires_at={expires_at_iso}"
    if prev_mode and prev_mode != "away":
        detail += f" (switched from {prev_mode})"
    log_event("mode_enabled", detail)
    print(f"AWM: away mode enabled for {duration_text}, "
          f"expires {fmt_local(expires_at.isoformat())}.")
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
    mode = state.get("mode", "away")  # older state files predate the mode field
    if mode == "away" and state.get("expires_at"):
        if now_utc() >= datetime.fromisoformat(state["expires_at"]):
            print(f"AWM: away mode EXPIRED at {fmt_local(state['expires_at'])} "
                  "(hooks will flip it off on next event).")
            return
        print(f"AWM: AWAY since {fmt_local(state['enabled_at'])}, "
              f"expires {fmt_local(state['expires_at'])} ({fmt_remaining(state['expires_at'])}).")
    else:
        print(f"AWM: PARTNER since {fmt_local(state['enabled_at'])}, no expiry "
              "(switch to away, or turn off, to change this).")


def cmd_decision(text):
    log_event("decision", text)
    print("Decision registered.")


def main(argv):
    cmd = argv[0] if argv else "partner"
    if cmd in ("enable", "partner"):
        cmd_partner()
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
        print(f"unknown command {cmd!r}; use partner | away [duration] | disable | status | "
              "decision <text>", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
