#!/usr/bin/env python3
"""call-behaviorist CLI: switch ai-badger's own debug audit log on and off.

  behaviorist.py on [DURATION] [--project]   enable (user-wide by default)
  behaviorist.py off                          disable
  behaviorist.py status                       mode, scope, remaining, log size
  behaviorist.py tail [N]                     last N records
  behaviorist.py clear                        truncate the log

Debug is user-scoped by default: every project logs. `--project` narrows it to the current
working directory. See docs/design/debug-mode-and-call-behaviorist.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import debug_log as dl  # pylint: disable=import-error
except ImportError:  # pragma: no cover - vendored copy is missing
    print("call-behaviorist: debug_log.py not found beside this script", file=sys.stderr)
    raise

DEFAULT_DURATION = "4h"
DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")
MAX_DURATION_SECONDS = 24 * 3600


def parse_duration(text: str) -> int:
    """'4h', '90m', '1h30m', or a bare number of hours -> seconds."""
    text = text.strip().lower()
    if text.isdigit():
        seconds = int(text) * 3600
    else:
        match = DURATION_RE.match(text)
        if not match or (match.group(1) is None and match.group(2) is None):
            raise ValueError(f"cannot parse duration {text!r} (use 4h, 90m, 1h30m)")
        seconds = int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return min(seconds, MAX_DURATION_SECONDS)


def cmd_on(duration: str, project_scoped: bool) -> int:
    seconds = parse_duration(duration)
    expires = dl.now() + timedelta(seconds=seconds)
    state = {
        "enabled": True,
        "scope": dl.SCOPE_PROJECT if project_scoped else dl.SCOPE_USER,
        "project": str(Path.cwd()) if project_scoped else None,
        "enabled_at": dl.iso(dl.now()),
        "expires_at": dl.iso(expires),
    }
    dl.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    dl.STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    # pylint: disable=protected-access
    dl._own_only(dl.DEBUG_DIR)
    dl._own_only(dl.STATE_FILE)
    where = state["project"] if project_scoped else "every project"
    print(f"debug logging ON for {where}, expires {state['expires_at']}")
    print(f"records: {dl.AUDIT_FILE}")
    dl.log_event("call-behaviorist", "enabled", project=state["project"], scope=state["scope"])
    return 0


def cmd_off() -> int:
    if not dl.STATE_FILE.exists():
        print("debug logging is already off.")
        return 0
    dl.log_event("call-behaviorist", "disabled")
    dl.STATE_FILE.write_text(json.dumps({"enabled": False}, indent=2) + "\n", encoding="utf-8")
    print("debug logging OFF.")
    return 0


def _line_count() -> int:
    try:
        return sum(1 for _ in dl.AUDIT_FILE.open("r", encoding="utf-8"))
    except OSError:
        return 0


def cmd_status() -> int:
    state = dl._state()  # pylint: disable=protected-access
    if state is None:
        print("debug logging: OFF")
    else:
        scope = state.get("scope", dl.SCOPE_USER)
        target = state.get("project") or "every project"
        print(f"debug logging: ON ({scope} — {target})")
        print(f"expires: {state.get('expires_at', 'never')}")
    print(f"records: {_line_count()} in {dl.AUDIT_FILE}")
    return 0


def cmd_tail(count: int) -> int:
    if not dl.AUDIT_FILE.exists():
        print("no records yet.")
        return 0
    lines = dl.AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-count:]
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        fixed = (dl.KEY_TS, dl.KEY_COMPONENT, dl.KEY_EVENT, dl.KEY_VERSION)
        extra = " ".join(f"{dl.KEY_NAMES.get(k, k)}={v}" for k, v in rec.items()
                         if k not in fixed)
        print(f"{rec[dl.KEY_TS]}  {rec[dl.KEY_COMPONENT]:<40} {rec[dl.KEY_EVENT]:<8} "
              f"v{rec[dl.KEY_VERSION]}  {extra}")
    return 0


def cmd_clear() -> int:
    if dl.AUDIT_FILE.exists():
        dl.AUDIT_FILE.write_text("", encoding="utf-8")
        dl._own_only(dl.AUDIT_FILE)  # pylint: disable=protected-access
    dl.log_event("call-behaviorist", "cleared")
    print("audit log cleared.")
    return 0


def main(argv=None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")

    on = sub.add_parser("on", help="enable debug logging")
    on.add_argument("duration", nargs="?", default=DEFAULT_DURATION)
    on.add_argument("--project", action="store_true",
                    help="limit to the current directory (default: every project)")
    sub.add_parser("off", help="disable debug logging")
    sub.add_parser("status", help="show mode, scope and record count")
    tail = sub.add_parser("tail", help="show the last records")
    tail.add_argument("count", nargs="?", type=int, default=20)
    sub.add_parser("clear", help="truncate the audit log")

    args = parser.parse_args(argv)
    if args.command == "on":
        try:
            return cmd_on(args.duration, args.project)
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
    if args.command == "off":
        return cmd_off()
    if args.command == "tail":
        return cmd_tail(args.count)
    if args.command == "clear":
        return cmd_clear()
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
