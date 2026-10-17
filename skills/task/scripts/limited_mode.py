#!/usr/bin/env python3
"""Limited mode for machines where policy disables Claude Code hooks.

`checkin` replays the project's own hook commands; `on`/`off` manage a block in CLAUDE.local.md.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BEGIN = "<!-- BEGIN ai-badger limited mode -->"
END = "<!-- END ai-badger limited mode -->"
LOCAL_FILE = "CLAUDE.local.md"
TIMEOUT_SECONDS = 60

BLOCK_TEXT = """## ai-badger limited mode (hooks disabled on this machine)

Your organisation's policy disables Claude Code hooks here, so ai-badger's automatic context, guards and checkpoints do not run. Do them by hand:

- At session start, and again before opening a PR or finishing a task, run `python3 .ai-badger/skills/task/scripts/limited_mode.py checkin`; at the end of a turn that finishes a task, run it with `--end`.
- Prompt markers (`f:`, `q:`, `i!:` ...) are not expanded: apply them yourself per the Prompt markers section.
- Every Agent dispatch names its `model` (see `.ai-badger/delegation.md`); nothing checks it.
- Search memory (`memory_search`) before repo text search; nothing checks it.
- Never hand-edit files under `.git/` or the generated `.ai-badger/` output; use git commands and edit the `features/` source.
- Before killing processes or clearing shared caches while other agents run, scope the kill to your own lane.
- Commit small and often, run each test suite once, and cite failing output before a fix: the invariants still apply, only their reminders are gone.
- Interrupted turns are not checkpointed; run `checkin --end` yourself before you stop.
"""


def find_root(explicit):
    """Return the project root: --root, else the git toplevel of cwd, else cwd."""
    if explicit:
        return Path(explicit).resolve()
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True,
            text=True, check=True, timeout=10).stdout.strip()
        if top:
            return Path(top)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def main_checkout(explicit):
    """Return --root, else the main checkout that every linked worktree nests under."""
    if explicit:
        return Path(explicit).resolve()
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        if common:
            return Path(common).parent
    except (OSError, subprocess.SubprocessError):
        pass
    return find_root(None)


def transcript_path(cwd, session_id):
    """Claude's transcript location for this cwd and session."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    return str(Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl")


def hook_commands(hooks_file, event):
    """Every command registered for the event; matchers are ignored."""
    spec = json.loads(Path(hooks_file).read_text(encoding="utf-8"))
    commands = []
    for entry in spec.get("hooks", {}).get(event, []):
        for hook in entry.get("hooks", []):
            if hook.get("type") == "command" and hook.get("command"):
                commands.append(hook["command"])
    return commands


def reply_lines(stdout):
    """Text a hook reply contributes: context, system message, block reason."""
    text = stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return [text]
    if not isinstance(data, dict):
        return [text]
    found = [
        (data.get("hookSpecificOutput") or {}).get("additionalContext"),
        data.get("systemMessage"),
        data.get("reason"),
    ]
    return [item for item in found if item]


def checkin(args):
    """Replay the hook commands for the session start, or the stop with --end."""
    if os.environ.get("CLAUDE_CODE_CHILD_SESSION"):
        print("limited-mode checkin: a subagent must not check in "
              "(it would consume the parent's mail); nothing run.")
        return 0
    root = find_root(args.root)
    hooks_file = Path(args.hooks) if args.hooks else root / ".ai-badger" / "hooks" / "hooks.json"
    event = "Stop" if args.end else "SessionStart"
    session_id = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    cwd = os.getcwd()
    payload = json.dumps({
        "hook_event_name": event,
        "session_id": session_id,
        "cwd": cwd,
        "transcript_path": transcript_path(cwd, session_id),
        "source": "resume",
    })
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    if not hooks_file.is_file():
        print(f"limited-mode checkin: no hooks.json at {hooks_file}; re-scaffold with welcome-ai-badger")
        return 0
    commands = hook_commands(hooks_file, event)
    for command in commands:
        try:
            result = subprocess.run(
                command, shell=True, input=payload, capture_output=True, text=True,
                cwd=cwd, env=env, timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            print(f"limited-mode: command timed out after {TIMEOUT_SECONDS}s: {command[:80]}")
            continue
        if result.returncode != 0:
            print(f"limited-mode: command exit {result.returncode}: {command[:80]}")
        for line in reply_lines(result.stdout):
            print(line)
    print(f"limited-mode checkin: {len(commands)} commands run")
    return 0


def split_block(text):
    """Return (before, after) around the marked block, or None when absent."""
    start = text.find(BEGIN)
    stop = text.find(END)
    if start == -1 or stop == -1 or stop < start:
        return None
    return text[:start], text[stop + len(END):]


def turn_on(args):
    """Write the limited-mode block, replacing any earlier one in place."""
    path = main_checkout(args.root) / LOCAL_FILE
    block = f"{BEGIN}\n{BLOCK_TEXT}{END}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    parts = split_block(existing)
    if parts:
        before, after = parts
        path.write_text(before + block.rstrip("\n") + after, encoding="utf-8")
    else:
        separator = "\n" if existing and not existing.endswith("\n\n") else ""
        path.write_text(existing + separator + block, encoding="utf-8")
    print(f"limited mode on: {path}")
    return 0


def turn_off(args):
    """Remove the block; delete the file when nothing else is left."""
    path = main_checkout(args.root) / LOCAL_FILE
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    parts = split_block(text)
    if not parts:
        return 0
    rest = (parts[0].rstrip("\n") + "\n" + parts[1].lstrip("\n")).strip("\n")
    if rest.strip():
        path.write_text(rest + "\n", encoding="utf-8")
    else:
        path.unlink()
    print("limited mode off")
    return 0


def build_parser():
    """Command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("checkin", help="replay the project's hook commands")
    check.add_argument("--end", action="store_true", help="replay Stop instead of SessionStart")
    check.add_argument("--session", help="session id for the hook payload")
    check.add_argument("--hooks", help="path to hooks.json")
    check.add_argument("--root", help="project root")
    check.set_defaults(run=checkin)
    for name, run, helptext in (("on", turn_on, "write the CLAUDE.local.md block"),
                                ("off", turn_off, "remove the CLAUDE.local.md block")):
        item = sub.add_parser(name, help=helptext)
        item.add_argument("--root", help="project root")
        item.set_defaults(run=run)
    return parser


def main(argv=None):
    """Entry point."""
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
