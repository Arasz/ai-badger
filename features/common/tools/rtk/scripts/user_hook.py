#!/usr/bin/env python3
"""Print, or write with --apply, the user-scope Claude hook for the rtk guard.

The command carries rtk_guard.py's source inline, exactly as project scope wires it, so it does
not depend on this checkout. --apply edits $CLAUDE_CONFIG_DIR/settings.json (default
~/.claude/settings.json), replacing earlier rtk guard entries; re-run it to pick up guard fixes.

Usage: python3 user_hook.py [--apply]
Exit code: 0 = printed or applied, non-zero = refused.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "skills/welcome-ai-badger/scripts"))
from tool_hooks import MARKER, guarded_command  # noqa: E402  pylint: disable=wrong-import-position

GUARD = HERE / "rtk_guard.py"


def settings_path() -> Path:
    """The user settings file Claude reads: under $CLAUDE_CONFIG_DIR, else ~/.claude."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    return Path(base) / "settings.json"


def entry() -> dict:
    """The PreToolUse group that runs the inlined guard for Bash."""
    command = guarded_command("rtk", "claude", GUARD.read_text(encoding="utf-8"))
    return {"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}


def is_guard(hook: dict) -> bool:
    """True for an earlier rtk guard entry: the marked inline form or a path to rtk_guard.py."""
    command = hook.get("command") or ""
    return f"{MARKER}=rtk " in command or "rtk_guard.py" in command


def pre_tool_use(settings: dict) -> list:
    """The PreToolUse groups; ValueError when the settings do not have the documented shape."""
    hooks = settings.get("hooks", {})
    groups = hooks.get("PreToolUse", []) if isinstance(hooks, dict) else None
    if not isinstance(groups, list) or not all(
            isinstance(g, dict) and isinstance(g.get("hooks", []), list)
            and all(isinstance(h, dict) for h in g.get("hooks", [])) for g in groups):
        raise ValueError("hooks.PreToolUse is not a list of hook groups")
    return groups


def is_current(groups: list) -> bool:
    """True when the only guard entry is the current one, under the Bash matcher."""
    current = entry()
    found = [(g.get("matcher"), h) for g in groups for h in g.get("hooks", []) if is_guard(h)]
    return found == [(current["matcher"], current["hooks"][0])]


def merged(settings: dict) -> dict:
    """*settings* with every earlier guard entry removed and the current one appended."""
    existing = pre_tool_use(settings)
    if is_current(existing):
        return settings
    groups = []
    for group in existing:
        kept = [h for h in group.get("hooks", []) if not is_guard(h)]
        if kept:
            groups.append({**group, "hooks": kept})
        elif not group.get("hooks"):
            groups.append(group)
    groups.append(entry())
    return {**settings, "hooks": {**settings.get("hooks", {}), "PreToolUse": groups}}


def bare_hooks(groups: list) -> list[str]:
    """Unguarded `rtk hook ...` PreToolUse commands, as `rtk init -g` writes them."""
    return [h["command"] for g in groups for h in g.get("hooks", [])
            if str(h.get("command") or "").startswith("rtk hook ")]


def load(path: Path) -> dict:
    """The settings object at *path*, {} when absent; ValueError when unreadable or malformed."""
    if not path.exists():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(settings, dict):
        raise ValueError(f"{path} is not a JSON object")
    pre_tool_use(settings)
    return settings


def write(path: Path, settings: dict) -> Path:
    """Write *settings* through any symlink, keeping the file mode; return the backup path."""
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(f"{target.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    if target.exists():
        shutil.copy2(target, backup)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)
    return backup


def main(argv: list[str] | None = None) -> int:
    """Print the hook entry and whether the settings file holds it, or apply it with --apply."""
    parser = argparse.ArgumentParser(description="User-scope Claude hook for the rtk guard.")
    parser.add_argument("--apply", action="store_true", help="Write it into the settings file")
    args = parser.parse_args(argv)
    if os.name == "nt":
        print("refused: the rtk guard hook is POSIX-only", file=sys.stderr)
        return 1
    path = settings_path()
    try:
        settings = load(path)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    groups = pre_tool_use(settings)
    for command in bare_hooks(groups):
        print(f"note: `{command}` also runs before Bash and rewrites past permissions.ask "
              "rules; remove it (rtk init -g --uninstall) to leave rewriting to the guard")
    if is_current(groups):
        print(f"{path} already has the current rtk guard hook")
        return 0
    if not args.apply:
        print(f"{path} lacks the current rtk guard hook. Add to hooks.PreToolUse "
              "(or pass --apply):")
        print(json.dumps(entry(), indent=2))
        return 0
    backup = write(path, merged(settings))
    note = f" (previous file: {backup})" if backup.exists() else ""
    print(f"wrote the rtk guard hook to {path}{note}; it applies from the next session")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
