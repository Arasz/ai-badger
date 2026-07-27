#!/usr/bin/env python3
"""UserPromptSubmit hook for autonomic work mode (AWM).

If AWM is active, injects a status line (plain stdout becomes context) telling
Claude which mode is on and how to register decisions. Both modes' windows lapse
on wall-clock time; this flips the state off and announces expiry once.
Silent (exit 0, no output) when the mode is off or on any internal error.
"""
# pylint: disable=missing-function-docstring,broad-exception-caught
# Ported verbatim from the originating job-search-ai-assistant repo's auto-wm skill: kept in
# lockstep with that source rather than churned for local docstring/style rules. The broad
# except below is intentional — a broken hook must never block a prompt.
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"


def now_utc():
    return datetime.now(timezone.utc)


def retire(state, mode, expires):
    """Flip an elapsed window off, record it, and announce the expiry once."""
    expires_at = state.get("expires_at")
    state["enabled"] = False
    state["disabled_at"] = now_utc().isoformat(timespec="seconds")
    state["disabled_reason"] = "expired"
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    with DECISIONS_FILE.open("a") as f:
        f.write(json.dumps({"ts": now_utc().isoformat(timespec="seconds"),
                            "type": "mode_expired",
                            "detail": f"expired_at={expires_at}"}) + "\n")
    when = f" at {expires.astimezone().strftime('%Y-%m-%d %H:%M %Z')}" if expires else \
        " (no expiry was recorded)"
    print(f"[auto-wm] {mode.upper()} MODE EXPIRED{when}. Normal approvals resume.")


def main():
    state = json.loads(STATE_FILE.read_text())
    if not state.get("enabled"):
        return

    mode = state.get("mode", "away")  # older state files predate the mode field
    expires_at = state.get("expires_at")
    expires = datetime.fromisoformat(expires_at) if expires_at else None

    # Both modes are wall-clock bounded; a state file with no expiry predates that and
    # the gate refuses it, so retire it here too rather than announcing a live window.
    if expires is None or now_utc() >= expires:
        retire(state, mode, expires)
        return

    total = int((expires - now_utc()).total_seconds())
    remaining = f"{total // 3600}h {(total % 3600) // 60:02d}m"
    window = (f"expires {expires.astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
              f"({remaining} remaining)")

    if mode == "away":
        print(f"[auto-wm] AWAY MODE ACTIVE — {window}. "
              "No user is available: never ask questions or wait for approval; choose the best "
              "option and keep working. Register significant judgment calls with: "
              "python3 ~/.claude/skills/auto-wm/scripts/awm.py decision \"<what and why>\"")
        return

    print(f"[auto-wm] PARTNER MODE ACTIVE — {window}. "
          "Tool calls auto-approve; the user is available, so ask questions, "
          "brainstorm, or check in whenever it helps — don't hold back on that account. "
          "Still worth registering notable judgment calls with: "
          "python3 ~/.claude/skills/auto-wm/scripts/awm.py decision \"<what and why>\"")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
