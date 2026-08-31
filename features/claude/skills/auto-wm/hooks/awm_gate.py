#!/usr/bin/env python3
"""PreToolUse hook for autonomic work mode (AWM).

While away or partner mode is enabled for a project containing the call's cwd, a tool call
auto-approves (permissionDecision: allow) and is registered in ~/.claude/awm/decisions.jsonl —
unless one of three guards fires first, in which case nothing is emitted and the
normal permission prompt reaches the human:

  - expiry: both modes carry a wall-clock expiry, re-checked on every call.
  - project scope: the state holds one entry per project; a call whose cwd is outside
    every armed tree is never auto-approved. Two checkouts can be armed at once.
  - denylist: destructive shell commands, network egress and writes outside the
    project are never auto-approved, in either mode.

The two modes then differ only on AskUserQuestion:

  - partner: passes through untouched (you're around to answer).
  - away: denied (no one to answer).

Outside AWM (or on any internal error) it emits nothing and exits 0, so the
normal permission flow is untouched.

State is read from the awm_state rows of the user store, merged with a legacy
~/.claude/awm/state.json until its first write migrates it (D5a); a broken store falls
back to that file, and with no readable source the hook stays out of the way entirely.
"""
# pylint: disable=missing-function-docstring,broad-exception-caught
# Ported verbatim from the originating job-search-ai-assistant repo's auto-wm skill: kept in
# lockstep with that source rather than churned for local docstring/style rules. The broad
# except below is intentional — a broken hook must never break the session's permission flow.
import json
import re
import shlex
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"
MAX_DETAIL_LEN = 300

# The store is vendored beside awm.py in the sibling scripts/ dir of this skill; in tests
# engine/ is already on sys.path. Explicit insert: a hook never inherits the caller's path.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import badger_store  # pylint: disable=wrong-import-position  # noqa: E402


def open_store():
    """The user store narrowed to the awm_state family, rebound to this module's STATE_FILE."""
    family = badger_store.Family(
        table="awm_state", db="user", legacy_path=lambda: STATE_FILE, legacy_kind="awm",
    )
    return badger_store.open_user(families={"awm_state": family})


def load_state():
    """Per-project entries: store rows merged with the legacy file (D5a); fail open to it.

    With no rows anywhere the raw legacy document comes back verbatim — a pre-#296 unscoped
    entry is machine-global and unimportable (no project key), so its top level must stay
    visible — and its absence or corruption surfaces exactly as it did before the store.
    """
    try:
        store = open_store()
        try:
            rows = store.kv_all("awm_state")
        finally:
            store.close()
    except Exception:  # pylint: disable=broad-exception-caught
        return json.loads(STATE_FILE.read_text())  # today's read; raises when absent
    if rows:
        return {"version": 2, "projects": rows}
    return json.loads(STATE_FILE.read_text())

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
    r"\bgit\s+push\b[^|;&]*\s(--force|-f|--force-with-lease)\b",
    r"\bgit\s+push\b[^|;&]*\s\+[\w./-]+",
    r"\bfind\b[^|;&]*\s-(delete|exec)\b",
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

LONG_FLAG_ALIASES = {
    "--recursive": "-r",
    "--force": "-f",
    "--dir": "-d",
    "--no-preserve-root": "-r",
}

# A verb that destroys or escalates. Its arguments must be readable to be judged.
UNRESOLVABLE_ARG_HEADS = {
    "rm", "dd", "mkfs", "fdisk", "diskutil", "chmod", "chown",
    "shutdown", "reboot", "halt", "killall", "crontab", "sudo", "doas", "su", "find",
}
EXPANSION_RE = re.compile(r"[$`]")
SEGMENT_RE = re.compile(r"[;&|]+|\n")


def normalise_command(command):
    """Rewrite a command so the denylist matches intent, not flag spelling.

    Long flags become their short equivalents; unparseable input is returned unchanged
    so the patterns still run against the raw text rather than being skipped.
    """
    try:
        tokens = shlex.split(command, comments=False)
    except ValueError:
        return command
    return " ".join(LONG_FLAG_ALIASES.get(token, token) for token in tokens)


def hides_arguments_from_the_denylist(command):
    """True when a destructive verb's arguments are expansions this gate cannot resolve.

    `V=-rf; rm $V` reads as harmless and runs as `rm -rf`, so an unreadable argument to a
    destructive verb is treated as the dangerous reading.
    """
    for segment in SEGMENT_RE.split(command):
        tokens = segment.split()
        if len(tokens) < 2:
            continue
        if Path(tokens[0]).name in UNRESOLVABLE_ARG_HEADS:
            if any(EXPANSION_RE.search(token) for token in tokens[1:]):
                return True
    return False


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


def projects(state):
    """Per-project entries, migrating the pre-#296 single-project shape on read."""
    if isinstance(state.get("projects"), dict):
        return state["projects"]
    if state.get("project"):
        return {state["project"]: state}
    return {}


def entry_for(state, cwd):
    """The armed entry whose project contains *cwd*, most specific first, or None.

    One machine-wide scope meant enabling AWM in a second repo disarmed the first (#296).
    """
    best_project, best_entry = None, None
    for project, entry in projects(state).items():
        if not isinstance(entry, dict) or not entry.get("enabled"):
            continue
        if within(project, cwd) and (best_project is None
                                     or len(str(project)) > len(str(best_project))):
            best_project, best_entry = project, entry
    return (best_project, best_entry) if best_project is not None else None


def denylist_reason(tool_name, tool_input, project):
    """Fixed-vocabulary reason this call may never be auto-approved, or None.

    The vocabulary is closed on purpose: no scanned byte reaches the decision log.
    """
    if tool_name in DENIED_TOOLS:
        return "denied_tool"
    if tool_name == "Bash":
        command = (tool_input or {}).get("command") or ""
        normalised = normalise_command(command)
        if any(pattern.search(normalised) for pattern in DENIED_COMMAND_PATTERNS):
            return "destructive_command"
        if hides_arguments_from_the_denylist(command):
            return "destructive_command"
        return None
    if tool_name in PATH_SCOPED_TOOLS:
        target = next((tool_input[k] for k in PATH_KEYS if (tool_input or {}).get(k)), None)
        if target and not within(project, target):
            return "write_outside_project"
    return None


def disable(project, entry, reason, detail, session_id, cwd):
    """Flip one project's entry off in its store row and record why; the caller emits nothing."""
    entry["enabled"] = False
    entry["disabled_at"] = now_utc().isoformat(timespec="seconds")
    entry["disabled_reason"] = reason
    store = open_store()
    try:
        store.kv_set("awm_state", project, entry)  # first write imports + renames legacy (D6)
    finally:
        store.close()
    log_event("mode_expired", detail, session_id, cwd)


def main():
    payload = json.load(sys.stdin)
    state = load_state()

    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    tool_name = payload.get("tool_name", "?")
    tool_input = payload.get("tool_input")

    # A window enabled in one project never speaks for another, and never for a
    # state file that predates project scoping.
    found = entry_for(state, cwd)
    if not found:
        armed = sorted(p for p, e in projects(state).items()
                       if isinstance(e, dict) and e.get("enabled"))
        # A window open elsewhere — or an enabled-but-unscoped legacy state — is a refusal
        # worth recording. AWM simply being off everywhere is not.
        if armed or state.get("enabled"):
            log_event("out_of_scope", f"project={', '.join(armed) or 'unset'}",
                      session_id, cwd, tool_name)
        return

    project, entry = found
    mode = entry.get("mode", "away")  # older state files predate the mode field
    expires_at = entry.get("expires_at")

    if expired(entry):
        detail = f"expired_at={expires_at}" if expires_at else "no expiry recorded in state"
        disable(project, entry, "expired", detail, session_id, cwd)
        return  # no output -> normal permission flow resumes

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