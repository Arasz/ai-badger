#!/usr/bin/env python3
"""UserPromptSubmit hook for autonomic work mode (AWM).

If AWM is active, injects a status line (plain stdout becomes context) telling
Claude which mode is on and how to register decisions. Away mode's window can
lapse (wall-clock); this flips the state off and announces expiry once.
Silent (exit 0, no output) when the mode is off or on any internal error.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"


def now_utc():
    return datetime.now(timezone.utc)


def main():
    state = json.loads(STATE_FILE.read_text())
    if not state.get("enabled"):
        return

    mode = state.get("mode", "away")  # older state files predate the mode field

    if mode == "away":
        expires_at = state.get("expires_at")
        expires = datetime.fromisoformat(expires_at) if expires_at else None
        if expires and now_utc() >= expires:
            state["enabled"] = False
            state["disabled_at"] = now_utc().isoformat(timespec="seconds")
            state["disabled_reason"] = "expired"
            STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
            with DECISIONS_FILE.open("a") as f:
                f.write(json.dumps({"ts": now_utc().isoformat(timespec="seconds"),
                                    "type": "mode_expired",
                                    "detail": f"expired_at={expires_at}"}) + "\n")
            print(f"[auto-wm] AWAY MODE EXPIRED at "
                  f"{expires.astimezone().strftime('%Y-%m-%d %H:%M %Z')}. Normal approvals resume.")
            return

        total = int((expires - now_utc()).total_seconds()) if expires else 0
        remaining = f"{total // 3600}h {(total % 3600) // 60:02d}m"
        print(f"[auto-wm] AWAY MODE ACTIVE — expires "
              f"{expires.astimezone().strftime('%Y-%m-%d %H:%M %Z')} ({remaining} remaining). "
              "No user is available: never ask questions or wait for approval; choose the best "
              "option and keep working. Register significant judgment calls with: "
              "python3 ~/.claude/skills/auto-wm/scripts/awm.py decision \"<what and why>\"")
        return

    print(f"[auto-wm] PARTNER MODE ACTIVE since "
          f"{datetime.fromisoformat(state['enabled_at']).astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
          "(no expiry). Tool calls auto-approve; the user is available, so ask questions, "
          "brainstorm, or check in whenever it helps — don't hold back on that account. "
          "Still worth registering notable judgment calls with: "
          "python3 ~/.claude/skills/auto-wm/scripts/awm.py decision \"<what and why>\"")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)