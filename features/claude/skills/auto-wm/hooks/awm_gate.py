#!/usr/bin/env python3
"""PreToolUse hook for autonomic work mode (AWM).

While away or partner mode is enabled for a project containing the call's cwd, a tool call
auto-approves (permissionDecision: allow) and is registered as an ``awm_decisions`` row of the
user store — a legacy ~/.claude/awm/decisions.jsonl is imported and renamed on the first such
write (D6) — unless one of three guards fires first, in which case nothing is emitted and the
normal permission prompt reaches the human:

  - expiry: both modes carry a wall-clock expiry, re-checked on every call.
  - project scope: the state holds one entry per project; a call whose cwd is outside
    every armed tree is never auto-approved. Two checkouts can be armed at once.
  - denylist: destructive shell commands, network egress (MCP tools included), writes
    outside the project and changes to away-mode state are never auto-approved, in either
    mode. Every tool whose input carries a shell command is scanned, not only Bash.

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
import os
import re
import shlex
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

AWM_DIR = Path.home() / ".claude" / "awm"
STATE_FILE = AWM_DIR / "state.json"
DECISIONS_FILE = AWM_DIR / "decisions.jsonl"  # legacy source; rows replace it (P1.2b)
MAX_DETAIL_LEN = 300

# The store is vendored beside awm.py in the sibling scripts/ dir of this skill; in tests
# engine/ is already on sys.path. Explicit insert: a hook never inherits the caller's path.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import badger_store  # pylint: disable=wrong-import-position  # noqa: E402


def open_store():
    """The user store narrowed to the awm families, rebound to this module's legacy paths."""
    families = {
        "awm_state": badger_store.Family(
            table="awm_state", db="user", legacy_path=lambda: STATE_FILE, legacy_kind="awm",
        ),
        "awm_decisions": badger_store.Family(
            table="awm_decisions", db="user",
            legacy_path=lambda: DECISIONS_FILE, legacy_kind="jsonl",
        ),
    }
    return badger_store.open_user(families=families)


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
# Every MCP tool counts as egress: the hook payload carries nothing that proves a call
# read-only, and the server receives its arguments whatever the tool is named.
MCP_PREFIX = "mcp__"

# Tools whose target path must stay inside the project AWM was enabled in.
PATH_SCOPED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PATH_KEYS = ("file_path", "notebook_path", "path")
# A tool whose input carries one of these runs a shell command, whatever the tool is called.
COMMAND_KEYS = ("command", "cmd")

# Shell commands that are irreversible, escalate privilege, rewrite published history,
# execute network content, or install persistence. A human approves these, always.
# rm, git, kill, network clients, awm.py and redirections are judged word by word below.
DENIED_COMMAND_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\b(sudo|doas|su)\b",
    r"\bfind\b[^|;&]*\s-(delete|exec)\b",
    r"\b(mkfs|fdisk|diskutil)\b",
    r"\bdd\s+if=",
    r"\bchmod\s+(-\w+\s+)*777\b",
    r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k)?sh\b",
    r"\b(shutdown|reboot|halt|killall)\b",
    r":\s*\(\s*\)\s*\{.*\}\s*;\s*:",
    r"\bcrontab\b",
    r"\bhistory\s+-c\b",
)]

RM_LONG_FLAGS = {"--recursive", "--force", "--no-preserve-root"}
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
GIT_PUSH_REWRITES = {"--delete", "--mirror", "--prune"}
NETWORK_CLIENTS = {"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "ftp", "sftp",
                   "scp", "ssh"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "eval"}
# Words that run the word after them: skipped, with their options, to find the real command.
WRAPPERS = {"env", "command", "builtin", "exec", "nohup", "time", "nice", "timeout", "stdbuf",
            "xargs", "sudo", "doas"}
WRAPPER_ARG_RE = re.compile(r"^(-.*|\w+=.*|\d+(\.\d+)?[smhd]?)$")
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_]\w*=")
PYTHON_RE = re.compile(r"^python[\d.]*$")
# awm.py subcommands that change no away-mode state; the away-mode denial asks for `decision`.
AWM_READ_ONLY = {"status", "decision"}
# Where away-mode state lives. A command that names it is editing the window by hand.
AWM_STATE_MARKERS = (".claude/awm", "ai-badger.db")
SAFE_SINKS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}

# A verb that destroys or escalates. Its arguments must be readable to be judged.
UNRESOLVABLE_ARG_HEADS = {
    "rm", "dd", "mkfs", "fdisk", "diskutil", "chmod", "chown",
    "shutdown", "reboot", "halt", "killall", "crontab", "sudo", "doas", "su", "find",
}
EXPANSION_RE = re.compile(r"[$`]")

SHELL_OPERATORS = "();<>|&\n"
REDIRECTS = {"<", ">", ">>", ">|", "&>", "&>>", ">&", "<&", "<>", "<<", "<<<"}
QUOTED_OPERATOR_RE = re.compile(r"""(["'])[();<>|&\n]+\1""")
SUBSTITUTION_RE = re.compile(r"\$\(|`|<\(|>\(")


def split_commands(command):
    """Split shell text into simple commands: lists of unquoted words, operators dropped.

    Redirection operators stay as words so their targets can be judged. Text shlex cannot
    parse is split quote-blind instead, so a stray quote never hides a word.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_OPERATORS)
        lexer.whitespace_split = True
        lexer.whitespace = " \t\r"
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        tokens = re.findall(r"[();<>|&\n]+|[^\s();<>|&]+", command)
    commands, words = [], []
    for token in tokens:
        if token in REDIRECTS or not token or token.strip(SHELL_OPERATORS):
            words.append(token)
        elif words:
            commands.append(words)
            words = []
    if words:
        commands.append(words)
    return commands


def _name(word):
    return Path(word.strip("`")).name


def command_head(words):
    """Index of the word a simple command runs, past assignments and wrappers, or None."""
    i = 0
    while i < len(words) and ASSIGNMENT_RE.match(words[i]):
        i += 1
    while i < len(words) and _name(words[i]) in WRAPPERS:
        i += 1
        while i < len(words) and WRAPPER_ARG_RE.match(words[i]):
            i += 1
    return i if i < len(words) else None


def short_flags(args):
    """The letters of every single-dash option cluster in *args*, up to `--`."""
    letters = []
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("-") and not arg.startswith("--"):
            letters.append(arg[1:])
    return "".join(letters)


def rm_is_destructive(args):
    return bool(set(short_flags(args).lower()) & set("rf") or RM_LONG_FLAGS.intersection(args))


def git_is_destructive(args):
    """A forcing or deleting push, `reset --hard`, or a forcing `clean`, past git's own options."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GIT_OPTIONS_WITH_VALUE else 1
    if i >= len(args):
        return False
    subcommand, rest = args[i], args[i + 1:]
    flags = short_flags(rest)
    if subcommand == "push":
        refspecs = [a for a in rest if not a.startswith("-")]
        return bool(set(flags) & set("fd")
                    or any(a.startswith("--force") or a in GIT_PUSH_REWRITES for a in rest)
                    or any(r.startswith(("+", ":")) for r in refspecs))
    if subcommand == "reset":
        return "--hard" in rest
    if subcommand == "clean":
        return bool(set(flags.lower()) & set("fdx")) or "--force" in rest
    return False


def kill_hits_everything(args):
    """True when kill targets pid 1 or -1, which reaches every process the user can signal."""
    if args[:1] in (["-s"], ["-n"]):
        args = args[2:]
    elif args and args[0].startswith("-") and args[0] != "--":
        args = args[1:]
    return bool({"1", "-1"}.intersection(args))


# Verbs judged wherever they appear in a command (`git rm -r` too), by their own options.
DESTRUCTIVE_VERBS = {"rm": rm_is_destructive, "git": git_is_destructive,
                     "kill": kill_hits_everything}


def runs_awm(name, args):
    """True when the command runs awm.py with a subcommand that changes away-mode state."""
    if PYTHON_RE.match(name):
        scripts = [a for a in args if not a.startswith("-")]
        if not scripts or _name(scripts[0]) != "awm.py":
            return False
        args = args[args.index(scripts[0]) + 1:]
    elif name != "awm.py":
        return False
    return (args[0] if args else "partner") not in AWM_READ_ONLY


def writes_outside(target, project, cwd):
    """True when a redirection to *target* lands outside *project*; an unexpandable one does."""
    if target.isdigit() or target == "-":
        return False  # `>&2`, `>&-`: a file descriptor, not a file
    path = os.path.expanduser(os.path.expandvars(target))
    if EXPANSION_RE.search(path):
        return True
    if path in SAFE_SINKS or path.startswith("/dev/fd/"):
        return False
    return not within(project, Path(cwd or project, path))


def command_reason(words, project, cwd):
    """Why one simple command may never be auto-approved, or None."""
    head = command_head(words)
    if head is not None:
        name, args = _name(words[head]), words[head + 1:]
        if EXPANSION_RE.search(words[head]):
            return "destructive_command"  # `$V` runs whatever V holds
        if name in NETWORK_CLIENTS:
            return "network_egress"
        # `V=-rf; rm $V` reads as harmless and runs as `rm -rf`.
        if name in UNRESOLVABLE_ARG_HEADS and any(EXPANSION_RE.search(a) for a in args):
            return "destructive_command"
        if runs_awm(name, args):
            return "awm_state_change"
    for i, word in enumerate(words):
        check, rest = DESTRUCTIVE_VERBS.get(_name(word)), words[i + 1:]
        if check and check(rest):
            return "destructive_command"
        if word in REDIRECTS and ">" in word and rest and writes_outside(rest[0], project, cwd):
            return "write_outside_project"
    return None


def shell_script(args):
    """The script a shell or eval runs: the word after a `-c` cluster, else its operands."""
    for i, arg in enumerate(args[:-1]):
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg:
            return args[i + 1]
    return " ".join(a for a in args if not a.startswith("-"))


def shell_reason(command, project, cwd):
    """Fixed-vocabulary reason a shell command may never be auto-approved, or None.

    Quoted text that still runs is scanned too: everything after `$(`, a backtick, `<(` or
    `>(`, and the script a shell or eval is handed.
    """
    if any(marker in command for marker in AWM_STATE_MARKERS):
        return "awm_state_change"
    if any(pattern.search(command) for pattern in DENIED_COMMAND_PATTERNS):
        return "destructive_command"
    pending = [command] + [command[m.end():] for m in SUBSTITUTION_RE.finditer(command)]
    while pending:
        text = pending.pop()
        commands = split_commands(text)
        if QUOTED_OPERATOR_RE.search(text):  # `rm ";" -rf x` must not split rm from -rf
            commands.append([word for words in commands for word in words])
        for words in commands:
            if any(pattern.search(" ".join(words)) for pattern in DENIED_COMMAND_PATTERNS):
                return "destructive_command"
            reason = command_reason(words, project, cwd)
            if reason:
                return reason
            head = command_head(words)
            if head is not None and _name(words[head]) in SHELLS:
                pending.append(shell_script(words[head + 1:]))
    return None


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
    store = open_store()  # first write imports + renames a legacy decisions.jsonl (D6)
    try:
        store.log_append("awm_decisions", entry["ts"], entry)
        store.prune_expired("awm_decisions", max_age_days=60)
    finally:
        store.close()


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


def covers_everything(project):
    """True for `/` or $HOME: a window armed there scopes nothing, so it is never honoured."""
    try:
        resolved = Path(project).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return True
    return resolved in (Path("/"), Path.home().resolve())


def entry_for(state, cwd):
    """The armed entry whose project contains *cwd*, most specific first, or None.

    One machine-wide scope meant enabling AWM in a second repo disarmed the first (#296).
    """
    best_project, best_entry = None, None
    for project, entry in projects(state).items():
        if not isinstance(entry, dict) or not entry.get("enabled") or covers_everything(project):
            continue
        if within(project, cwd) and (best_project is None
                                     or len(str(project)) > len(str(best_project))):
            best_project, best_entry = project, entry
    return (best_project, best_entry) if best_project is not None else None


def denylist_reason(tool_name, tool_input, project, cwd=None):
    """Fixed-vocabulary reason this call may never be auto-approved, or None.

    The vocabulary is closed on purpose: no scanned byte reaches the decision log.
    """
    if tool_name in DENIED_TOOLS:
        return "denied_tool"
    if str(tool_name).startswith(MCP_PREFIX):
        return "mcp_tool"
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    for key in COMMAND_KEYS:
        if isinstance(tool_input.get(key), str):
            reason = shell_reason(tool_input[key], project, cwd)
            if reason:
                return reason
    if tool_name in PATH_SCOPED_TOOLS:
        target = next((tool_input[k] for k in PATH_KEYS if tool_input.get(k)), None)
        if target and any(marker in str(target) for marker in AWM_STATE_MARKERS):
            return "awm_state_change"
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

    reason = denylist_reason(tool_name, tool_input, project, cwd)
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
             "in the AWM decision log")
        return

    # partner mode: leave AskUserQuestion alone, auto-approve everything else.
    if tool_name == "AskUserQuestion":
        return

    log_event("auto_approve", summarize_input(payload.get("tool_input")),
              session_id, cwd, tool_name)
    emit("allow", "AWM partner mode active: auto-approved and registered in the AWM decision log")


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