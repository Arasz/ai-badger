"""Shared helpers for the /task skill: JSON stores, transcript token parsing, session refs.

Data lives in <project-root>/.ai-badger/task-tracking/ (gitignored):
  executed-tasks.json  — task execution records (session refs, timestamps, state)
  token-usage.json     — per-task token checkpoints, usage deltas, quality grade
  current-session.json — every currently-active session (keyed by sessionId), so multiple
                          concurrent Claude Code sessions can share the file safely — see
                          resolve_own_session().

Project-agnostic: the project root is resolved via `resolve_project_root()` (env var, then a
cwd walk for the `.ai-badger/config.json` contract marker, then a fallback relative to this
file's own location), and every path is then derived from that root via a project-root-relative
`.ai-badger/` tracking convention, never an absolute path baked in at authoring time. This
matters because ai-badger ships `task` as an installable plugin skill: when Claude Code runs it
from its plugin cache (`~/.claude/plugins/cache/ai-badger/ai-badger/skills/task/scripts/`), the
script's own location is nowhere near the user's project, so a naive fixed-depth-from-`__file__`
lookup would misroot. Anything project-specific (build/test commands, source-control platform,
persona routing) lives in the project's `.ai-badger/config.json`, not here.
"""
# pylint: disable=missing-function-docstring,invalid-name
# Ported verbatim from the originating job-search-ai-assistant repo's /task skill: kept in
# lockstep with that source rather than churned for local docstring/naming style rules.
# `locked_store` (lower_snake_case class) is referenced by that name elsewhere; not renamed.

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

SCRIPT_DIR = Path(__file__).resolve().parent


def resolve_project_root(
    env: dict | None = None, cwd: Path | None = None, script_dir: Path = SCRIPT_DIR
) -> Path:
    """Resolve the ai-badger project root, in precedence order:

    1. `CLAUDE_PROJECT_DIR` env var, when set and pointing at an existing directory --
       authoritative for hook/statusLine invocations (Claude Code sets it; ai-badger's own
       scaffolded settings.json hooks already rely on it).
    2. Walk up from `cwd` to the nearest ancestor containing `.ai-badger/config.json` (the
       ai-badger contract marker) -- covers script invocations from anywhere in the repo.
    3. Fallback: `script_dir.parents[3]` -- today's behavior for in-repo scaffolded copies
       (`<repo>/.claude/skills/task/scripts` or `<repo>/.ai-badger/skills/task/scripts`)
       invoked with no session context.

    Deliberately does not walk up from `script_dir` looking for a `.claude/` directory (as
    poll_limit's old `_find_project_root` did): from a Claude Code plugin cache
    (`~/.claude/plugins/cache/ai-badger/ai-badger/skills/task/scripts/`), that walk finds
    `$HOME` -- because `~/.claude` always exists there -- which is both the wrong start point
    and the wrong marker.
    """
    env = os.environ if env is None else env
    env_dir = env.get("CLAUDE_PROJECT_DIR")
    if env_dir and Path(env_dir).is_dir():
        return Path(env_dir)

    start = Path.cwd() if cwd is None else Path(cwd)
    for ancestor in (start, *start.parents):
        if (ancestor / ".ai-badger" / "config.json").is_file():
            return ancestor

    return script_dir.parents[3]  # .claude/skills/task/scripts -> repo root


def compute_paths(project_root: Path) -> dict:
    """Derive every tracker_lib path constant from a resolved project root."""
    data_dir = project_root / ".ai-badger" / "task-tracking"
    return {
        "project_root": project_root,
        "data_dir": data_dir,
        "executed_tasks": data_dir / "executed-tasks.json",
        "token_usage": data_dir / "token-usage.json",
        "current_session": data_dir / "current-session.json",
        "lock_file": data_dir / ".write.lock",
        "claude_md": project_root / "CLAUDE.md",
        "state_json": project_root / ".ai-badger" / "state.json",
        "config_json": project_root / ".ai-badger" / "config.json",
    }


_PATHS = compute_paths(resolve_project_root())
PROJECT_ROOT = _PATHS["project_root"]
DATA_DIR = _PATHS["data_dir"]

EXECUTED_TASKS = _PATHS["executed_tasks"]
TOKEN_USAGE = _PATHS["token_usage"]
CURRENT_SESSION = _PATHS["current_session"]
LOCK_FILE = _PATHS["lock_file"]

STATE_STARTED = "STARTED"
STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_FINISHED = "FINISHED"

CLAUDE_MD = _PATHS["claude_md"]
CLAUDE_MD_MAX_CHARS = 12000
CLAUDE_MD_MAX_LINES = 110
STATE_JSON = _PATHS["state_json"]
CONFIG_JSON = _PATHS["config_json"]


def now_iso() -> str:
    # Full microsecond precision: startedAt is compared against file mtimes
    # (state.json freshness), and second-level truncation flips comparisons
    # for events less than a second apart.
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class locked_store:
    """Context manager: exclusive lock over the tracking data dir for read-modify-write."""

    def __init__(self):
        self._fh = None

    def __enter__(self):
        ensure_data_dir()
        self._fh = open(LOCK_FILE, "w", encoding="utf-8")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    ensure_data_dir()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_tasks() -> dict:
    return load_json(EXECUTED_TASKS, {"tasks": []})


def load_usage() -> dict:
    return load_json(TOKEN_USAGE, {"tasks": []})


def load_config() -> dict:
    """Project profile from `.ai-badger/config.json` (see schemas/config.schema.json).

    Returns {} if the project hasn't scaffolded ai-badger config yet (or it's unreadable) —
    callers must treat every key as optional and fall back to a clear no-op message rather
    than assume a stack-specific default.
    """
    return load_json(CONFIG_JSON, {})


def find_entry(doc: dict, task_id: str):
    for entry in doc["tasks"]:
        if entry.get("taskId") == task_id:
            return entry
    return None


def find_other_entry_with_session(doc: dict, session_id: str, exclude_task_id: str):
    """Another task already attached to session_id, if any (used to catch cross-task collisions)."""
    for entry in doc["tasks"]:
        if entry.get("taskId") != exclude_task_id and entry.get("sessionId") == session_id:
            return entry
    return None


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError):
        return True  # exists but not ours to signal (or malformed input) — assume alive
    return True


def load_current_sessions() -> dict:
    """Every currently-known active session, keyed by sessionId."""
    return load_json(CURRENT_SESSION, {"sessions": {}}).get("sessions", {})


def save_current_session(session_id: str, transcript_path: str, cwd: str = "") -> None:
    """Record this session into the shared multi-session index.

    Lock-protected read-modify-write: multiple Claude Code sessions call this concurrently
    (once per SessionStart/UserPromptSubmit), so it must not race a plain save_json overwrite
    that would drop another session's entry. Also opportunistically prunes entries whose
    process no longer exists, so the file self-cleans without a separate GC job.
    """
    with locked_store():
        doc = load_json(CURRENT_SESSION, {"sessions": {}})
        sessions = doc.setdefault("sessions", {})
        for sid in list(sessions):
            if sid != session_id and not _pid_alive(sessions[sid].get("pid")):
                del sessions[sid]
        sessions[session_id] = {
            "transcriptPath": transcript_path,
            "cwd": cwd or str(PROJECT_ROOT),
            "pid": os.getppid(),  # the long-lived Claude Code process that spawned this hook
            "recordedAt": now_iso(),
        }
        save_json(CURRENT_SESSION, doc)


def _own_pid_ancestry(max_depth: int = 12) -> list[int]:
    """PIDs of this process and its ancestors, nearest first (best-effort via `ps`)."""
    chain = []
    pid = os.getpid()
    for _ in range(max_depth):
        chain.append(pid)
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, check=False
        )
        ppid_str = result.stdout.strip()
        if not ppid_str:
            break
        try:
            ppid = int(ppid_str)
        except ValueError:
            break
        if ppid <= 1 or ppid == pid:
            break
        pid = ppid
    return chain


def resolve_own_session() -> dict:
    """Best-effort identification of the session invoking this process.

    Tried in order:
    1. CLAUDE_CODE_SESSION_ID env var — Claude Code sets this on every tool subprocess, so
       it identifies the calling session exactly, with no ambiguity even when several
       sessions run concurrently against the same project.
    2. This process's PID ancestry matched against a recorded session's pid (covers CLI
       versions without the env var).
    3. A unique cwd match among active sessions (last resort; only used if exactly one
       active session shares this process's cwd, since a shared cwd is otherwise ambiguous).

    Returns {} if nothing resolves — callers should then require explicit --session-id.
    """
    sessions = load_current_sessions()

    env_id = os.environ.get(CLAUDE_SESSION_ENV)
    if env_id:
        if env_id in sessions:
            return {"sessionId": env_id, **sessions[env_id]}
        return {"sessionId": env_id, "transcriptPath": None}  # exact id, hook just hasn't fired yet

    ancestry = set(_own_pid_ancestry())
    for sid, info in sessions.items():
        if info.get("pid") in ancestry:
            return {"sessionId": sid, **info}

    cwd = str(Path.cwd())
    cwd_matches = [(sid, info) for sid, info in sessions.items() if info.get("cwd") == cwd]
    if len(cwd_matches) == 1:
        sid, info = cwd_matches[0]
        return {"sessionId": sid, **info}

    return {}


def parse_transcript_usage(transcript_path: str) -> dict:
    """Aggregate token usage from a Claude Code transcript (JSONL).

    contextTokens  — context-window occupancy of the latest main-chain assistant
                     message (input + cache_read + cache_creation).
    cumulative     — sums over every assistant message in the file (sidechains
                     included: they are billed work too).
    """
    cumulative = {
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "cacheCreationTokens": 0,
    }
    context_tokens = 0
    messages = 0
    path = Path(transcript_path) if transcript_path else None
    if path is None or not path.exists():
        return {
            "contextTokens": 0, "assistantMessages": 0,
            "cumulative": cumulative, "transcriptFound": False,
        }

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "assistant":
                continue
            usage = (record.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                continue
            messages += 1
            inp = usage.get("input_tokens") or 0
            out = usage.get("output_tokens") or 0
            cr = usage.get("cache_read_input_tokens") or 0
            cc = usage.get("cache_creation_input_tokens") or 0
            cumulative["inputTokens"] += inp
            cumulative["outputTokens"] += out
            cumulative["cacheReadTokens"] += cr
            cumulative["cacheCreationTokens"] += cc
            if not record.get("isSidechain"):
                context_tokens = inp + cr + cc

    return {
        "contextTokens": context_tokens,
        "assistantMessages": messages,
        "cumulative": cumulative,
        "transcriptFound": True,
    }


def make_checkpoint(transcript_path: str) -> dict:
    usage = parse_transcript_usage(transcript_path)
    return {
        "timestamp": now_iso(),
        "contextTokens": usage["contextTokens"],
        "assistantMessages": usage["assistantMessages"],
        "cumulative": usage["cumulative"],
    }


def compute_usage(start_cp: dict, finish_cp: dict, subagents: list) -> dict:
    """Delta between two checkpoints of the same session, plus reported subagent tokens."""

    def delta(key: str) -> int:
        return max(0, finish_cp["cumulative"].get(key, 0) - start_cp["cumulative"].get(key, 0))

    subagent_tokens = sum(entry.get("totalTokens", 0) for entry in subagents)
    input_d = delta("inputTokens")
    output_d = delta("outputTokens")
    cache_read_d = delta("cacheReadTokens")
    cache_creation_d = delta("cacheCreationTokens")
    # Main-session cache health: fraction of cacheable input served from cache (~0.1x) vs.
    # freshly written (~1.25x). None when nothing cacheable ran. Subagent caches are separate
    # and their split isn't exposed to the orchestrator (only totalTokens), so this is
    # main-session only.
    cacheable = cache_read_d + cache_creation_d
    cache_efficiency = round(cache_read_d / cacheable, 3) if cacheable else None
    return {
        "inputTokens": input_d,
        "outputTokens": output_d,
        "cacheReadTokens": cache_read_d,
        "cacheCreationTokens": cache_creation_d,
        "cacheEfficiency": cache_efficiency,
        "subagentTokens": subagent_tokens,
        "contextTokensAtStart": start_cp.get("contextTokens", 0),
        "contextTokensAtFinish": finish_cp.get("contextTokens", 0),
        "contextGrowth": finish_cp.get("contextTokens", 0) - start_cp.get("contextTokens", 0),
        "mainSessionTotal": input_d + output_d + cache_read_d + cache_creation_d,
        "grandTotal": input_d + output_d + cache_read_d + cache_creation_d + subagent_tokens,
    }


def claude_md_stats() -> dict:
    try:
        text = CLAUDE_MD.read_text()
    except FileNotFoundError:
        text = ""
    chars = len(text)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return {
        "path": str(CLAUDE_MD),
        "chars": chars,
        "lines": lines,
        "maxChars": CLAUDE_MD_MAX_CHARS,
        "maxLines": CLAUDE_MD_MAX_LINES,
        "overBudget": chars > CLAUDE_MD_MAX_CHARS or lines > CLAUDE_MD_MAX_LINES,
    }


def state_json_updated_since(started_at: str) -> bool:
    try:
        mtime = datetime.fromtimestamp(STATE_JSON.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return False
    return mtime > parse_iso(started_at)
