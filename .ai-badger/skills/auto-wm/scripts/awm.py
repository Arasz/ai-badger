#!/usr/bin/env python3
"""auto-wm CLI: partner/away/disable/status/decision for autonomic work mode (AWM).

Two modes:
  - partner (default): tool calls auto-approve, but you're around, so
    AskUserQuestion is left untouched. Bounded by a maximum lifetime.
  - away: same auto-approval, but AskUserQuestion is denied (no one is
    around to answer) and the window expires on wall-clock time.

Each project gets its own entry, with its own mode and its own clock: the gate refuses
to auto-approve calls made from anywhere else, and enabling AWM in one checkout neither
arms the machine nor disarms another checkout (#296).

State lives at ~/.claude/awm/state.json (user level, never inside a project), keyed by
project path. A pre-0.74 single-project file is read as one entry and rewritten on change.
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


def projects(state):
    """Per-project entries, migrating the pre-#296 single-project shape on read."""
    if isinstance(state.get("projects"), dict):
        return dict(state["projects"])
    if state.get("project"):
        return {state["project"]: state}
    return {}


def save_entry(state, project, entry):
    """Write one project's entry back, leaving every other project's window alone."""
    data = {"version": 2, "projects": projects(state)}
    data["projects"][project] = entry
    write_state(data)


def entry_here(state):
    """This project's entry, or None — the most specific match, as the gate resolves it.

    A worktree sits inside its checkout, so first-match would let `off` in the worktree
    disarm the whole repo.
    """
    here = str(Path.cwd())
    best_project, best_entry = None, None
    for project, entry in projects(state).items():
        if not isinstance(entry, dict) or not within(project, here):
            continue
        if best_project is None or len(str(project)) > len(str(best_project)):
            best_project, best_entry = project, entry
    return (best_project, best_entry) if best_project is not None else None


def covering_entry(state):
    """What the gate would resolve for this cwd: the most specific *enabled* entry.

    `entry_here` answers "whose entry is this directory's"; this answers "will a call from
    here auto-approve". They differ when a disabled worktree entry sits inside an armed
    checkout, and reporting the first as if it were the second is how the CLI would tell
    you AWM is off while every call was approved.
    """
    here = str(Path.cwd())
    best_project, best_entry = None, None
    for project, entry in projects(state).items():
        if not isinstance(entry, dict) or not entry.get("enabled"):
            continue
        if within(project, here) and (best_project is None
                                      or len(str(project)) > len(str(best_project))):
            best_project, best_entry = project, entry
    return (best_project, best_entry) if best_project is not None else None


def armed_elsewhere(state):
    """Projects other than this one that still hold a live window."""
    here = str(Path.cwd())
    return sorted(p for p, e in projects(state).items()
                  if isinstance(e, dict) and e.get("enabled") and not within(p, here))


def _enable(mode, duration_text):
    """Write an enabled, project-scoped, wall-clock-bounded entry. Returns it."""
    seconds, duration_text = capped_duration(duration_text)
    state = load_state() or {}
    found = entry_here(state)
    prev_mode = found[1].get("mode") if found and found[1].get("enabled") else None
    enabled_at = now_utc()
    expires_at = enabled_at + timedelta(seconds=seconds)
    project = str(Path.cwd())
    entry = {
        "enabled": True,
        "mode": mode,
        "project": project,
        "enabled_at": enabled_at.isoformat(timespec="seconds"),
        "duration": duration_text,
        "duration_seconds": seconds,
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }
    save_entry(state, project, entry)
    detail = (f"mode={mode}, project={project}, duration={duration_text}, "
              f"expires_at={entry['expires_at']}")
    if prev_mode and prev_mode != mode:
        detail += f" (switched from {prev_mode})"
    log_event("mode_enabled", detail)
    return entry


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
    found = entry_here(state)
    if not found or not found[1].get("enabled"):
        print("AWM is not active in this project.")
        _report_elsewhere(state)
        return
    project, entry = found
    entry["enabled"] = False
    entry["disabled_at"] = now_utc().isoformat(timespec="seconds")
    entry["disabled_reason"] = reason
    save_entry(state, project, entry)
    log_event("mode_disabled", f"reason={reason}, project={project}")
    still = covering_entry(load_state() or {})
    if still:
        print(f"AWM disabled for {project}, but {still[0]} still covers this directory — "
              f"calls from here keep auto-approving. Disable it there to stop them.")
    else:
        print("AWM disabled here. Normal approvals resume.")
    _report_elsewhere(state)


def _report_elsewhere(state):
    """Name the other projects still armed, so a window is never invisible."""
    others = armed_elsewhere(state)
    if others:
        print("Still active in: " + ", ".join(others))


def cmd_status():
    state = load_state() or {}
    # Report the window the gate would use, not merely this directory's own entry: a
    # disabled worktree entry inside an armed checkout still auto-approves.
    found = covering_entry(state) or entry_here(state)
    entry = found[1] if found else None
    if not entry or not entry.get("enabled"):
        print("AWM: inactive in this project.")
        if entry and entry.get("disabled_at"):
            reason = entry.get("disabled_reason", "?")
            print(f"Last disabled {fmt_local(entry['disabled_at'])} (reason: {reason}).")
        _report_elsewhere(state)
        return
    mode = entry.get("mode", "away").upper()  # older state files predate the mode field
    scope = entry.get("project") or found[0]
    if not entry.get("expires_at"):
        print(f"AWM: {mode} state records no expiry; the gate will refuse it. Re-enable.")
        return
    if now_utc() >= datetime.fromisoformat(entry["expires_at"]):
        print(f"AWM: {mode} mode EXPIRED at {fmt_local(entry['expires_at'])} "
              "(hooks will flip it off on next event).")
        return
    print(f"AWM: {mode} since {fmt_local(entry['enabled_at'])}, "
          f"expires {fmt_local(entry['expires_at'])} ({fmt_remaining(entry['expires_at'])}).")
    print(f"Scope: {scope}")
    _report_elsewhere(state)


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
