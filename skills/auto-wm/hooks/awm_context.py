#!/usr/bin/env python3
"""UserPromptSubmit hook for autonomic work mode (AWM).

If AWM is active *for the project this prompt came from*, injects a status line (plain
stdout becomes context) telling Claude which mode is on and how to register decisions.
Scope is load-bearing: this hook used to ignore it and announce away mode in every project
on the machine, including ones where the gate denied every call (#296).
Both modes' windows lapse on wall-clock time; this flips that project's entry off and
announces expiry once. Silent (exit 0, no output) when the mode is off here or on any
internal error.

State is read from the awm_state rows of the user store, merged with a legacy
~/.claude/awm/state.json until its first write migrates it (D5a); a broken store falls
back to that file — exactly the missing-file contract, so a hook never blocks a prompt.
"""
# pylint: disable=missing-function-docstring,broad-exception-caught
# Ported verbatim from the originating job-search-ai-assistant repo's auto-wm skill: kept in
# lockstep with that source rather than churned for local docstring/style rules. The broad
# except below is intentional — a broken hook must never block a prompt.
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"

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

    With no rows anywhere the raw legacy document comes back verbatim, so a pre-#296
    unscoped entry reads exactly as it did before the store — including raising when
    absent, which guarded_main records the way it always has.
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


def now_utc():
    return datetime.now(timezone.utc)


def session_cwd():
    """Where this prompt came from. Hooks receive it on stdin; fall back to the process cwd."""
    try:
        return (json.load(sys.stdin) or {}).get("cwd") or str(Path.cwd())
    except Exception:  # pylint: disable=broad-exception-caught
        return str(Path.cwd())


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
        return state["projects"]
    if state.get("project"):
        return {state["project"]: state}
    return {}


def entry_for(state, cwd):
    """The armed entry whose project contains *cwd*, most specific first, or None.

    The banner used to skip this check entirely, so it announced away mode in every
    project on the machine while the gate denied all but one of them (#296).
    """
    best_project, best_entry = None, None
    for project, entry in projects(state).items():
        if not isinstance(entry, dict) or not entry.get("enabled"):
            continue
        if within(project, cwd) and (best_project is None
                                     or len(str(project)) > len(str(best_project))):
            best_project, best_entry = project, entry
    return (best_project, best_entry) if best_project is not None else None


def save(project, entry):
    """Write one project's entry to its own row, leaving every other project's window alone."""
    store = open_store()
    try:
        store.kv_set("awm_state", project, entry)  # first write imports + renames legacy (D6)
    finally:
        store.close()


def retire(project, entry, mode, expires):
    """Flip one project's elapsed window off, record it, and announce the expiry once."""
    expires_at = entry.get("expires_at")
    entry["enabled"] = False
    entry["disabled_at"] = now_utc().isoformat(timespec="seconds")
    entry["disabled_reason"] = "expired"
    save(project, entry)
    with DECISIONS_FILE.open("a") as f:
        f.write(json.dumps({"ts": now_utc().isoformat(timespec="seconds"),
                            "type": "mode_expired",
                            "detail": f"expired_at={expires_at}"}) + "\n")
    when = f" at {expires.astimezone().strftime('%Y-%m-%d %H:%M %Z')}" if expires else \
        " (no expiry was recorded)"
    print(f"[auto-wm] {mode.upper()} MODE EXPIRED{when}. Normal approvals resume.")


def main():
    state = load_state()
    found = entry_for(state, session_cwd())
    if not found:
        return  # AWM is off here, whatever it is doing in another project

    project, entry = found
    mode = entry.get("mode", "away")  # older state files predate the mode field
    expires_at = entry.get("expires_at")
    expires = datetime.fromisoformat(expires_at) if expires_at else None

    # Both modes are wall-clock bounded; a state file with no expiry predates that and
    # the gate refuses it, so retire it here too rather than announcing a live window.
    if expires is None or now_utc() >= expires:
        retire(project, entry, mode, expires)
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
        record_hook_failure("awm_context")
        return 0


if __name__ == "__main__":
    sys.exit(guarded_main())
