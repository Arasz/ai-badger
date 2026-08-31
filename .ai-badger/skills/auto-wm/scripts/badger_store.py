# the P1 user families pushed this single vendored module past 1000 lines; one file per
# ADR-0009, so the line budget yields (same arrangement as badger_lib.py)
# pylint: disable=too-many-lines
"""SQLite runtime store for ai-badger (ADR-0024).

One stdlib-only module, vendored verbatim per ADR-0009: project runtime state lives in
``<project>/.ai-badger/task-tracking/tracking.db``, user-level state in ``~/.ai-badger/ai-badger.db``,
and the audit sink in its own DB file. Roots resolve from the environment at call time, never at
import (``AI_BADGER_TRACKING_ROOT``, ``AI_BADGER_USER_ROOT``, ``AI_BADGER_DEBUG_DIR``). This module
imports nothing from the engine and nothing outside the standard library.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl; locking degrades to a no-op
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = 1

#: On-open upgrade seam: hook for version N migrates a database stamped N to N+1 (D27).
UPGRADE_HOOKS: dict[int, Callable[[sqlite3.Connection], None]] = {}

TRACKING_ROOT_ENV = "AI_BADGER_TRACKING_ROOT"
USER_ROOT_ENV = "AI_BADGER_USER_ROOT"
DEBUG_DIR_ENV = "AI_BADGER_DEBUG_DIR"

_TABLE_NAME = re.compile(r"[a-z_][a-z0-9_]*\Z")

#: Minimum seconds between two prunes of the same log table (D9/D30): the open-time prune
#: is throttled by the per-table ``pruned_at`` meta stamp so a burst of opens prunes once.
_PRUNE_THROTTLE_SECONDS = 3600

# The default home snapshots at import, before anything redirects $HOME for a session (the same
# pattern conftest's REAL_HOME uses): $HOME is session-wide state, never one of the three
# call-time env roots below. With no env override the store lands under the real home.
_DEFAULT_HOME = Path.home()

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id           TEXT,
        session_id        TEXT NOT NULL,
        title             TEXT,
        cwd               TEXT,
        branch            TEXT,
        transcript_path   TEXT,
        resume_command    TEXT,
        started_at        TEXT,
        finished_at       TEXT,
        state             TEXT NOT NULL DEFAULT 'STARTED',
        resume_attempts   TEXT NOT NULL DEFAULT '[]',
        tracking_source   TEXT,
        state_json_updated        INTEGER NOT NULL DEFAULT 0,
        state_json_reminder_sent  INTEGER NOT NULL DEFAULT 0,
        compaction_reminder_sent  INTEGER NOT NULL DEFAULT 0
    )
    """,
    # Defense in depth for the one-active-task-per-session rule (D14); the FINISHED-terminal
    # and attach-refusal checks stay application-level (P0.3).
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_session
        ON tasks(session_id) WHERE state <> 'FINISHED'
    """,
    # subagents is a JSON column per the P0.6a ruling (D1/D15); task_id NOT NULL because a
    # TEXT PK otherwise admits distinct NULLs and the natural-key dedup would never dedupe
    # them (P0.6a finding 4).
    """
    CREATE TABLE IF NOT EXISTS token_usage (
        task_id     TEXT NOT NULL PRIMARY KEY,
        session_id  TEXT,
        subagents   TEXT NOT NULL DEFAULT '[]',
        checkpoints TEXT NOT NULL DEFAULT '{}',
        usage       TEXT NOT NULL DEFAULT '{}',
        grade       TEXT,
        graded_at   TEXT,
        tracking_source TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_id      TEXT PRIMARY KEY,
        transcript_path TEXT,
        cwd             TEXT,
        pid             INTEGER,
        recorded_at     TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS statusline (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS marker_state (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # P1 user families (ADR-0024): the three KV tables share the statusline shape; the two
    # append-log tables follow the ts-index convention — every log table carries an index on
    # its ts column at creation (D17c), so the 60-day prune's range query stays indexed:
    # awm_decisions and searches here, hook_audit with its DDL in P2.1.
    """
    CREATE TABLE IF NOT EXISTS awm_state (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commit_reminder (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_feedback (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS awm_decisions (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_awm_decisions_ts ON awm_decisions(ts)",
    """
    CREATE TABLE IF NOT EXISTS searches (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_searches_ts ON searches(ts)",
)


#: Where vendored copies of this module live or will land, repo-relative (D16). The running
#: module is the byte-equality reference; entries whose file is absent have not landed yet
#: (vendorin happens with the P0.5 re-scaffold and P2.2's mirror sync, which reuse this list).
VENDORED_PATHS: tuple[dict[str, str], ...] = (
    {"consumer": "hooks", "lands_in": "features/common/hooks/badger_store.py"},
    {"consumer": "task", "lands_in": "features/common/skills/task/scripts/badger_store.py"},
    {"consumer": "prompt-markers",
     "lands_in": "features/common/skills/prompt-markers/scripts/badger_store.py"},
    {"consumer": "welcome-ai-badger",
     "lands_in": "features/common/skills/welcome-ai-badger/scripts/badger_store.py"},
    {"consumer": "commit-reminder",
     "lands_in": "features/common/skills/commit-reminder/scripts/badger_store.py"},
    {"consumer": "mcp-index",
     "lands_in": "features/common/skills/mcp-index/scripts/badger_store.py"},
    {"consumer": "ai-raccoon-memory",
     "lands_in": "features/common/skills/ai-raccoon-memory/scripts/badger_store.py"},
    {"consumer": "ai-raccoon-memory",
     "lands_in": "skills/ai-raccoon-memory/scripts/badger_store.py"},
    {"consumer": "worktree-agent-isolation",
     "lands_in": "features/common/skills/worktree-agent-isolation/scripts/badger_store.py"},
    {"consumer": "worktree-agent-isolation",
     "lands_in": ".ai-badger/skills/worktree-agent-isolation/scripts/badger_store.py"},
    {"consumer": "auto-wm", "lands_in": "features/claude/skills/auto-wm/scripts/badger_store.py"},
    {"consumer": "auto-wm", "lands_in": "skills/auto-wm/scripts/badger_store.py"},
    {"consumer": "mcp-index", "lands_in": "skills/mcp-index/scripts/badger_store.py"},
)


def vendored_copies_report(repo_root: Optional[Path] = None) -> list[str]:
    """Skew findings for landed vendored copies; empty means every landed copy is byte-identical.

    Copies not yet landed are named by the manifest but unchecked; a landed copy that differs
    from the running module is the failure the manifest exists to catch (D16).
    """
    root = repo_root if repo_root is not None else _default_badger_root().parent
    canonical = Path(__file__).resolve()
    try:
        expected = canonical.read_bytes()
    except OSError as exc:
        return [f"canonical {canonical} unreadable: {exc}"]
    findings = []
    for entry in VENDORED_PATHS:
        landed = root / entry["lands_in"]
        if not landed.exists():
            continue
        try:
            if landed.read_bytes() != expected:
                findings.append(f"{entry['lands_in']} differs from {canonical.name}")
        except OSError as exc:
            findings.append(f"{entry['lands_in']} unreadable: {exc}")
    return findings


def _now() -> str:
    """UTC ISO-8601 timestamp for row-level recency."""
    return datetime.now(timezone.utc).isoformat()


def _default_badger_root() -> Path:
    """The nearest existing ``.ai-badger`` directory above this module file (hook convention)."""
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / ".ai-badger").is_dir():
            return ancestor / ".ai-badger"
    return Path.home() / ".ai-badger"


def tracking_db_path() -> Path:
    """tracking.db — under ``AI_BADGER_TRACKING_ROOT`` when set, else the project root's."""
    env = os.environ.get(TRACKING_ROOT_ENV)
    if env:
        return Path(env) / "tracking.db"
    return _default_badger_root() / "task-tracking" / "tracking.db"


def user_db_path() -> Path:
    """ai-badger.db — under ``AI_BADGER_USER_ROOT`` when set, else the real home's .ai-badger."""
    env = os.environ.get(USER_ROOT_ENV)
    if env:
        return Path(env) / "ai-badger.db"
    return _DEFAULT_HOME / ".ai-badger" / "ai-badger.db"


def audit_db_path() -> Path:
    """The audit sink's own DB file — the ``AI_BADGER_DEBUG_DIR`` contract moves it whole (D21)."""
    env = os.environ.get(DEBUG_DIR_ENV)
    debug_dir = Path(env) if env else _DEFAULT_HOME / ".ai-badger" / "debug"
    return debug_dir / "audit.db"


def _ensure_root(db_path: Path) -> None:
    """Create the DB's parent 0700 when absent; an existing root keeps its own mode (D17)."""
    if not db_path.parent.is_dir():
        db_path.parent.mkdir(parents=True)
        os.chmod(db_path.parent, 0o700)


def _assert_file_perms(db_path: Path) -> None:
    """Re-assert owner-only on the DB and its WAL sidecars (D17)."""
    for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if candidate.exists():
            os.chmod(candidate, 0o600)


def _precreate_db_file(db_path: Path) -> None:
    """Create an absent DB file at 0600 BEFORE sqlite3.connect runs (P0.6b carry 1).

    sqlite creates the file with the process umask, leaving a first-open window where a new
    DB exists world-readable until the end-of-open chmod; creating it here closes that window
    for both DBs, and the explicit chmod keeps the mode umask-independent.
    """
    if db_path.exists():
        return
    fd = os.open(str(db_path), os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    os.chmod(db_path, 0o600)


def _create_schema(conn: sqlite3.Connection) -> None:
    for statement in _DDL:
        conn.execute(statement)


def _ensure_schema_version(conn: sqlite3.Connection, db_path: Path) -> None:
    """Stamp SCHEMA_VERSION on a fresh DB; dispatch upgrade hooks older; fail closed newer (D27)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        return
    stored = int(row[0])
    if stored > SCHEMA_VERSION:
        # Name the database that actually failed, not whichever path tracking_db_path()
        # resolves to — the user DB must not be misnamed (P0.6a finding 6).
        raise sqlite3.OperationalError(
            f"store schema version {stored} is newer than this code knows ({SCHEMA_VERSION}); "
            f"refusing to write in an old shape — run den-refresh to upgrade ai-badger "
            f"({db_path})"
        )
    if stored < SCHEMA_VERSION:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for version in range(stored, SCHEMA_VERSION):
                hook = UPGRADE_HOOKS.get(version)
                if hook is not None:
                    hook(conn)
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),)
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


class Family(NamedTuple):
    """One migrating store family: its table, its database, and its legacy JSON source.

    ``legacy_kind`` selects the import shape: ``map`` is a top-level dict keyed like the KV
    table (marker-state.json); ``kvdoc`` is one whole JSON document stored as a single KV row
    named by ``row_key`` (statusline-state.json / statusline-delegate.json); ``tasks`` and
    ``usage`` are ``{"tasks": [...]}`` row lists keyed on ``taskId`` (executed-tasks.json,
    token-usage.json); ``sessions`` is ``{"sessions": {id: info}}`` keyed on the session id
    (current-session.json); ``awm`` is the away-mode document whose per-project entries sit
    under ``projects`` (or the pre-#296 single-project shape) keyed by project path;
    ``jsonl`` is one JSON object per line written by the legacy appender (decisions.jsonl)
    with no natural key — imported with its own ``ts`` verbatim and deduped on exact
    (ts, payload) content so a re-import adds nothing.
    """

    table: str
    db: str  # "tracking" or "user"
    legacy_path: Callable[[], Path]
    legacy_kind: str  # "map" | "kvdoc" | "tasks" | "usage" | "sessions" | "awm" | "jsonl"
    row_key: str = ""  # kvdoc only: the KV row key this file's document becomes


#: Families with a legacy JSON source to lazy-migrate. marker_state's legacy dir is the
#: prompt-markers sibling of the tracking root (D5/D6; P1/P2 register their families here).
#: The task-family entries are NOT registered here: tracker_lib opens the store with its own
#: family set (its path constants are redirectable per test), built by _task_families() —
#: see tracker_lib. Consumers that never import tracker_lib use this default set.
FAMILIES: dict[str, Family] = {
    "marker_state": Family(
        table="marker_state",
        db="tracking",
        legacy_path=lambda: tracking_db_path().parent.parent / "prompt-markers"
        / "marker-state.json",
        legacy_kind="map",
    ),
}


def _user_root() -> Path:
    """The root .ai-badger user artifacts resolve against: USER_ROOT env, else the real home."""
    env = os.environ.get(USER_ROOT_ENV)
    return Path(env) if env else _DEFAULT_HOME / ".ai-badger"


#: The user-DB families (P1.1): schema and legacy paths land here; each family's import wiring
#: ("deferred" -> a real kind) lands with the lane that rewires its writer, so no store open
#: imports or renames a source its writer still owns (D5/D6): commit_reminder with the
#: commit-reminder lane, searches with P1.4. awm_state flipped to its real kind with P1.2a's
#: awm rewiring, awm_decisions to "jsonl" with P1.2b's decision rewiring. Until then a
#: deferred family has neither dual-read nor lazy import.
USER_FAMILIES: dict[str, Family] = {
    "awm_state": Family(
        table="awm_state",
        db="user",
        # ~/.claude/awm is not a .ai-badger artifact: it follows the real home, never
        # AI_BADGER_USER_ROOT (the snapshot also keeps the suite's $HOME redirect from moving it).
        legacy_path=lambda: _DEFAULT_HOME / ".claude" / "awm" / "state.json",
        legacy_kind="awm",
    ),
    "awm_decisions": Family(
        table="awm_decisions",
        db="user",
        legacy_path=lambda: _DEFAULT_HOME / ".claude" / "awm" / "decisions.jsonl",
        legacy_kind="jsonl",  # flipped from "deferred" by P1.2b's decision-log rewiring
    ),
    "commit_reminder": Family(
        table="commit_reminder",
        db="user",
        legacy_path=lambda: _user_root() / "commit-reminder" / "state.json",
        legacy_kind="deferred",
    ),
    "pending_feedback": Family(
        table="pending_feedback",
        db="user",
        legacy_path=lambda: _user_root() / "pending-feedback.json",
        legacy_kind="deferred",
        row_key="pending",  # the kvdoc row key its import lands under
    ),
    "searches": Family(
        table="searches",
        db="user",
        legacy_path=lambda: _user_root() / "memory-grade" / "searches.json",
        legacy_kind="deferred",
    ),
}

# -- task-family shapes: legacy entry key <-> row column -----------------------------
# Direct text columns; read back only when the column is non-NULL, so an entry never grows
# keys its writer did not set (stop_hook pins "reminder flag not in entry" until sent).
_TASK_TEXT_COLUMNS = {
    "taskId": "task_id", "title": "title", "sessionId": "session_id",
    "cwd": "cwd", "branch": "branch", "transcriptPath": "transcript_path",
    "resumeCommand": "resume_command", "startedAt": "started_at",
    "finishedAt": "finished_at", "state": "state", "trackingSource": "tracking_source",
}
_TASK_JSON_COLUMNS = {"resumeAttempts": "resume_attempts"}
_TASK_FLAG_COLUMNS = {
    "stateJsonUpdated": "state_json_updated",
    "stateJsonReminderSent": "state_json_reminder_sent",
    "compactionReminderSent": "compaction_reminder_sent",
}
_USAGE_TEXT_COLUMNS = {
    "sessionId": "session_id", "trackingSource": "tracking_source", "gradedAt": "graded_at",
}
_USAGE_JSON_COLUMNS = {"subagents": "subagents", "checkpoints": "checkpoints",
                       "usage": "usage"}
_SESSION_INFO_COLUMNS = {
    "transcriptPath": "transcript_path", "cwd": "cwd", "pid": "pid",
    "recordedAt": "recorded_at",
}

# Legacy residue with no live writer, intentionally dropped on migration (P0.6a finding 10):
# ``risk`` (executed-tasks) and ``note`` (token-usage). Recorded here so a future
# archaeologist does not re-add them.


def _dump(value, default):
    return json.dumps(value if value is not None else default)


def task_row_values(entry: dict) -> dict:
    """One executed-tasks entry as a tasks-row value dict (the single encode for import+writes)."""
    values = {column: entry.get(key) for key, column in _TASK_TEXT_COLUMNS.items()}
    values["state"] = values["state"] or "STARTED"
    values["resume_attempts"] = _dump(entry.get("resumeAttempts"), [])
    for key, column in _TASK_FLAG_COLUMNS.items():
        values[column] = 1 if entry.get(key) else 0
    return values


def task_entry(row: dict) -> dict:
    """One tasks row back as an executed-tasks entry (the single decode for reads)."""
    entry = {key: row[column] for key, column in _TASK_TEXT_COLUMNS.items()
             if row.get(column) is not None}
    entry["resumeAttempts"] = json.loads(row.get("resume_attempts") or "[]")
    for key, column in _TASK_FLAG_COLUMNS.items():
        if row.get(column):
            entry[key] = True
    return entry


def usage_row_values(entry: dict) -> dict:
    """One token-usage entry as a token_usage-row value dict."""
    values = {column: entry.get(key) for key, column in _USAGE_TEXT_COLUMNS.items()}
    values["task_id"] = entry.get("taskId")
    values["grade"] = None if entry.get("grade") is None else json.dumps(entry["grade"])
    for key, column in _USAGE_JSON_COLUMNS.items():
        values[column] = _dump(entry.get(key), [] if key == "subagents" else {})
    return values


def usage_entry(row: dict) -> dict:
    """One token_usage row back as a token-usage entry."""
    entry = {key: row[column] for key, column in _USAGE_TEXT_COLUMNS.items()
             if row.get(column) is not None}
    entry["taskId"] = row["task_id"]
    if row.get("grade") is not None:
        entry["grade"] = json.loads(row["grade"])
    for key, column in _USAGE_JSON_COLUMNS.items():
        entry[key] = json.loads(row.get(column) or ("[]" if key == "subagents" else "{}"))
    return entry


def session_row_values(session_id: str, info) -> dict:
    """One current-session entry as a sessions-row value dict."""
    values = {"session_id": session_id}
    for key, column in _SESSION_INFO_COLUMNS.items():
        values[column] = info.get(key) if isinstance(info, dict) else None
    return values


def session_info(row: dict) -> dict:
    """One sessions row back as a current-session info dict."""
    return {key: row[column] for key, column in _SESSION_INFO_COLUMNS.items()
            if row.get(column) is not None}



def _awm_projects(data: dict) -> dict:
    """An away-mode state document's per-project entries, keyed by project path.

    Both on-disk shapes: the #296 per-project form ({"projects": {path: entry}}) and the
    pre-#296 single-project form whose top level IS the entry (it names its own "project").
    """
    projects = data.get("projects")
    if isinstance(projects, dict):
        return dict(projects)
    if data.get("project"):
        return {data["project"]: data}
    return {}


def _stamp_key(table: str) -> str:
    return f"migrated_at.{table}"


def _check_table_name(table: str) -> None:
    """Refuse anything that is not a plain identifier before it reaches an f-string SQL slot."""
    if not _TABLE_NAME.match(table):
        raise ValueError(f"not a store table name: {table!r}")


#: Observers of committed store writes, invoked with the path that was written (D24). The
#: suite's write-attribution marking registers here so the conftest leak-guards keep working
#: once task state moves from JSON files into this store. Never raises into the writer.
WRITE_OBSERVERS: list[Callable[[Path], None]] = []


def notify_write(path: Path) -> None:
    """Tell every observer one store write committed at *path*; a broken observer is ignored."""
    for observer in WRITE_OBSERVERS:
        try:
            observer(path)
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # a diagnostic does not get to fail the write it observes



@contextlib.contextmanager
def _legacy_lock(lock_path: Path) -> Iterator[None]:
    """Hold the legacy writers' ``.write.lock`` flock so import never races a legacy write (D5b)."""
    if fcntl is None:  # pragma: no cover - Windows: no legacy flock convention to honour
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # blocking: wait out the legacy writer
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class Store:
    """One open SQLite store: the raw connection plus KV accessors and lazy family migration.

    ``families`` selects which legacy JSON sources this store knows about; the default is the
    module's FAMILIES registry, and tracker_lib passes its own (redirectable) task-family set.
    """

    def __init__(self, conn: sqlite3.Connection, db_path: Path, kind: str,
                 families: Optional[dict] = None) -> None:
        self.conn = conn
        self.db_path = db_path
        self.kind = kind
        self.families = FAMILIES if families is None else families

    def close(self) -> None:
        """Close the connection; sidecars disappear with the last open WAL connection."""
        with contextlib.suppress(sqlite3.Error):
            self.conn.close()

    # -- reads (fail open, D31) --------------------------------------------------------

    def kv_get(self, table: str, key: str, default: Any = None) -> Any:
        """The value for *key*: the DB row when present, else the legacy row, else *default*."""
        _check_table_name(table)
        try:
            row = self.conn.execute(
                f"SELECT value FROM {table} WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error:
            return default  # D31: a broken store never blocks a caller
        if row is not None:
            return self._decode(row[0], default)
        legacy = self._legacy_rows(table)  # raises on resurrection: never diverge (D5c)
        return legacy.get(key, default)

    def kv_all(self, table: str) -> dict:
        """Every key of *table*: DB rows merged with legacy-only rows (per-key LWW, D5a)."""
        _check_table_name(table)
        try:
            rows = {
                key: self._decode(value, None)
                for key, value in self.conn.execute(f"SELECT key, value FROM {table}")
            }
        except sqlite3.Error:
            return {}  # D31: a broken store never blocks a caller
        for key, value in self._legacy_rows(table).items():
            rows.setdefault(key, value)
        return {key: value for key, value in rows.items() if value is not None}

    @staticmethod
    def _decode(raw: str, default: Any) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default  # a corrupt row reads as absence, never a crash (D31)

    def _migration_stamp(self, table: str) -> Optional[float]:
        """When this family's import committed, or None before the first migration."""
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = ?", (_stamp_key(table),)
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return None

    def _families_for_table(self, table: str) -> list:
        return [family for family in self.families.values() if family.table == table]

    def _raise_on_resurrection(self, path: Path, table: str) -> None:
        """A legacy file newer than its migration stamp fails closed: never diverge (D5c)."""
        stamp = self._migration_stamp(table)
        if stamp is not None and path.stat().st_mtime > stamp:
            raise sqlite3.OperationalError(
                f"legacy {path} reappeared after its migration (a stale surface is writing "
                f"behind the store); restore the *.migrated.json name or den-refresh the stale "
                f"surface — the store refuses to diverge"
            )

    def _legacy_rows(self, table: str) -> dict:
        """Legacy KV rows still mergeable for *table*; a resurrected legacy file fails closed."""
        merged: dict = {}
        for family in self._families_for_table(table):
            if family.legacy_kind not in ("map", "kvdoc", "awm"):
                continue
            path = family.legacy_path()
            if not path.exists():
                continue
            self._raise_on_resurrection(path, family.table)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # unreadable legacy file: the DB rows stay authoritative (D31)
            if not isinstance(data, dict):
                continue
            if family.legacy_kind == "kvdoc":
                merged[family.row_key] = data
            elif family.legacy_kind == "awm":
                merged.update(_awm_projects(data))
            else:
                merged.update(data)
        return merged

    def _check_resurrections(self) -> None:
        """Open-time gate (D5c): a legacy file newer than its migration stamp fails closed."""
        for family in self.families.values():
            if family.db != self.kind:
                continue
            path = family.legacy_path()
            if not path.exists():
                continue
            self._raise_on_resurrection(path, family.table)

    # -- task-family rows (caller-managed transactions; see tracking_transaction there) ---

    def _row_map(self, table: str, key_column: str) -> dict:
        """Every row of *table* keyed on its natural-key column, in insertion order."""
        columns = [row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")]
        if key_column not in columns:
            raise sqlite3.OperationalError(f"table {table} has no column {key_column}")
        return {
            record[key_column]: record
            for record in (dict(zip(columns, row))
                           for row in self.conn.execute(f"SELECT * FROM {table} ORDER BY rowid"))
            if record.get(key_column) is not None
        }

    def _family_entries(self, family: Family) -> list:
        """A row-kind family's legacy entries, verbatim; a resurrected file fails closed."""
        path = family.legacy_path()
        if not path.exists():
            return []
        self._raise_on_resurrection(path, family.table)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []  # unreadable legacy file: the DB rows stay authoritative (D31)
        if not isinstance(data, dict):
            return []
        entries = data.get("tasks")
        return [entry for entry in entries if isinstance(entry, dict)] \
            if isinstance(entries, list) else []

    def tasks_all(self) -> list:
        """Every task entry: DB rows merged with legacy-only entries, DB wins per key (D5a)."""
        _check_table_name("tasks")
        try:
            merged = {task_id: task_entry(row)
                      for task_id, row in self._row_map("tasks", "task_id").items()}
        except sqlite3.Error:
            merged = {}  # D31: a broken store never blocks a reader
        for family in self._families_for_table("tasks"):
            for entry in self._family_entries(family):
                task_id = entry.get("taskId")
                if task_id is not None:
                    merged.setdefault(task_id, entry)
        return list(merged.values())

    def stop_blocks(self) -> dict:
        """The per-session stop-hook block budget (meta bookkeeping; no ruled column carries it)."""
        value = self.meta_get("stopBlocks", {})
        return value if isinstance(value, dict) else {}

    def usage_all(self) -> list:
        """Every token-usage entry: DB rows merged with legacy-only entries (D5a)."""
        _check_table_name("token_usage")
        try:
            merged = {task_id: usage_entry(row)
                      for task_id, row in self._row_map("token_usage", "task_id").items()}
        except sqlite3.Error:
            merged = {}
        for family in self._families_for_table("token_usage"):
            for entry in self._family_entries(family):
                task_id = entry.get("taskId")
                if task_id is not None:
                    merged.setdefault(task_id, entry)
        return list(merged.values())

    def sessions_map(self) -> dict:
        """Every known session as {sessionId: info}: DB rows merged with legacy rows (D5a)."""
        _check_table_name("sessions")
        try:
            merged = {session_id: session_info(row)
                      for session_id, row in self._row_map("sessions", "session_id").items()}
        except sqlite3.Error:
            merged = {}
        for family in self._families_for_table("sessions"):
            path = family.legacy_path()
            if not path.exists():
                continue
            self._raise_on_resurrection(path, family.table)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # unreadable legacy file: the DB rows stay authoritative (D31)
            sessions = data.get("sessions") if isinstance(data, dict) else None
            if not isinstance(sessions, dict):
                continue
            for session_id, info in sessions.items():
                if isinstance(info, dict):
                    merged.setdefault(session_id, info)
        return merged

    def task_upsert(self, entry: dict) -> None:
        """Insert or explicitly UPDATE one tasks row keyed on task_id.

        Never INSERT OR REPLACE: against tasks it silently deletes the session's other ACTIVE
        row (P0.6a MUST-2, scratch-verified), bypassing the exit-2 attach contract.
        """
        values = task_row_values(entry)
        task_id = values["task_id"]
        if not task_id:
            raise ValueError("task entry without taskId")
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        existing = self.conn.execute(
            "SELECT id FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if existing:
            self.conn.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?",
                (*values.values(), existing[0]),
            )
        else:
            self.conn.execute(
                f"INSERT INTO tasks({', '.join(columns)}) VALUES ({placeholders})",
                tuple(values.values()),
            )

    def usage_upsert(self, entry: dict) -> None:
        """Insert or explicitly UPDATE one token_usage row keyed on its primary key."""
        values = usage_row_values(entry)
        if not values["task_id"]:
            raise ValueError("usage entry without taskId")
        columns = list(values)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        existing = self.conn.execute(
            "SELECT task_id FROM token_usage WHERE task_id = ?", (values["task_id"],)
        ).fetchone()
        if existing:
            self.conn.execute(
                f"UPDATE token_usage SET {assignments} WHERE task_id = ?",
                (*values.values(), values["task_id"]),
            )
        else:
            self.conn.execute(
                f"INSERT INTO token_usage({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(values.values()),
            )

    def session_upsert(self, session_id: str, info: dict) -> None:
        """Insert or explicitly UPDATE one sessions row keyed on the session id."""
        values = session_row_values(session_id, info)
        columns = list(values)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        existing = self.conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing:
            self.conn.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?",
                (*values.values(), session_id),
            )
        else:
            self.conn.execute(
                f"INSERT INTO sessions({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(values.values()),
            )

    def session_delete(self, session_id: str) -> None:
        """Drop one session row (the current-session prune of dead pids)."""
        self.conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def meta_get(self, key: str, default=None):
        """One meta row as JSON, or *default* when absent or unparsable."""
        try:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error:
            return default
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return default

    def meta_set(self, key: str, value) -> None:
        """Upsert one meta row as JSON (caller-managed transaction)."""
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    # -- retention seam (the open-time caller and full prune UX land with P2.3; D9/D17c) --

    def prune_expired(self, table: str, *, max_age_days: int = 60) -> int:
        """Delete log rows whose ``ts`` predates the age cutoff; return the deleted row count.

        The per-table ``pruned_at.<table>`` meta stamp throttles: a second call inside the
        window deletes nothing (returns 0) even when rows expired since — the next window
        catches them. Stamp check, DELETE, and stamp rewrite share one BEGIN IMMEDIATE, so
        the throttle has no check-then-act window; every sqlite failure fails open as 0 (D9).
        """
        _check_table_name(table)
        stamp_key = f"pruned_at.{table}"
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = ?", (stamp_key,)
            ).fetchone()
        except sqlite3.Error:
            return 0
        if row is not None:
            try:
                last = float(json.loads(row[0]))
            except (TypeError, ValueError):
                last = None
            if last is not None and time.time() - last < _PRUNE_THROTTLE_SECONDS:
                return 0
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = self.conn.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
                pruned = cursor.rowcount
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (stamp_key, json.dumps(time.time())),
                )
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
        except sqlite3.Error:
            return 0  # a broken store never blocks a caller on maintenance (D31)
        return pruned


    # -- writes (may raise) ------------------------------------------------------------

    def kv_set(self, table: str, key: str, value: Any) -> None:
        """Write *value* under *key*; the first write lazy-migrates the family (D6)."""
        _check_table_name(table)
        self.migrate(table)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                f"INSERT OR REPLACE INTO {table}(key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), _now()),
            )
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        _assert_file_perms(self.db_path)
        notify_write(self.db_path)

    def kv_delete(self, table: str, key: str) -> None:
        """Drop one KV row; the first write lazy-migrates the family (D6), like kv_set."""
        _check_table_name(table)
        self.migrate(table)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(f"DELETE FROM {table} WHERE key = ?", (key,))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        _assert_file_perms(self.db_path)
        notify_write(self.db_path)

    def log_append(self, table: str, ts: str, payload: dict) -> None:
        """Append one log row (ts, payload JSON); the first write lazy-migrates the family (D6)."""
        _check_table_name(table)
        self.migrate(table)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                f"INSERT INTO {table}(ts, payload) VALUES (?, ?)",
                (ts, json.dumps(payload)),
            )
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        _assert_file_perms(self.db_path)
        notify_write(self.db_path)

    def migrate(self, table: str) -> None:
        """Import every legacy source for *table* — COMMIT first, rename after (D6).

        Idempotent: re-import after a crash between COMMIT and rename adds no duplicate rows,
        and a legacy file whose mtime postdates the migration stamp fails closed (D5c) instead
        of diverging. Row-kind families carry a post-import count check because INSERT OR
        IGNORE silently drops rows violating NOT NULL/CHECK (P0.6a finding 3).
        """
        for family in self._families_for_table(table):
            self._migrate_family(family)

    def _migrate_family(self, family: Family) -> None:
        if family.legacy_kind == "deferred":
            return  # import wiring lands with the family's writer lane (see USER_FAMILIES)
        path = family.legacy_path()
        if not path.exists():
            return
        self._raise_on_resurrection(path, family.table)
        with _legacy_lock(path.parent / ".write.lock"):
            if not path.exists():  # re-check under the lock: another writer migrated it
                return
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                expected = self._import_legacy(family, path)
                missing = [key for key in expected if not self._row_exists(family.table, key)]
                if missing:
                    raise sqlite3.IntegrityError(
                        f"legacy import for {family.table} would drop {len(missing)} row(s) "
                        f"violating the schema (first: {missing[0]!r}) — fix or remove "
                        f"{path}; the store refuses to migrate with silent drops"
                    )
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (_stamp_key(family.table), str(time.time())),
                )
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
            # Only after COMMIT: a crash before the rename leaves both artifacts, and the
            # next write re-runs this idempotent import (D6).
            os.replace(path, path.with_name(f"{path.stem}.migrated{path.suffix}"))
        _assert_file_perms(self.db_path)
        notify_write(self.db_path)
        notify_write(path.with_name(f"{path.stem}.migrated{path.suffix}"))

    def _row_exists(self, table: str, key) -> bool:
        if isinstance(key, tuple):  # jsonl log rows: the (ts, payload) content key
            row = self.conn.execute(
                f"SELECT 1 FROM {table} WHERE ts = ? AND payload = ?", key
            ).fetchone()
            return row is not None
        key_column = {"tasks": "task_id", "token_usage": "task_id", "sessions": "session_id"}.get(
            table, "key"
        )
        row = self.conn.execute(
            f"SELECT 1 FROM {table} WHERE {key_column} = ?", (key,)
        ).fetchone()
        return row is not None

    def _import_legacy(self, family: Family, path: Path) -> list:
        """Insert every legacy row with OR IGNORE on the natural key; return the expected keys.

        The expected-keys list is what the post-import count check verifies: a row dropped by
        OR IGNORE (NOT NULL/CHECK violation) shows up as missing and fails the migration loudly
        instead of silently (P0.6a finding 3). Unreadable or shape-less files import nothing and
        rename anyway — quarantine, matching the map-kind behavior this module shipped with.
        """
        if family.legacy_kind == "jsonl":
            return self._import_jsonl(family, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        stamp = _now()
        if family.legacy_kind == "kvdoc":
            self.conn.execute(
                f"INSERT OR IGNORE INTO {family.table}(key, value, updated_at) VALUES (?, ?, ?)",
                (family.row_key, json.dumps(data), stamp),
            )
            return [family.row_key]
        if family.legacy_kind == "map":
            for key, value in data.items():
                self.conn.execute(
                    f"INSERT OR IGNORE INTO {family.table}(key, value, updated_at) "
                    f"VALUES (?, ?, ?)",
                    (key, json.dumps(value), stamp),
                )
            return list(data)
        if family.legacy_kind == "awm":
            projects = _awm_projects(data)
            for project, entry in projects.items():
                self.conn.execute(
                    f"INSERT OR IGNORE INTO {family.table}(key, value, updated_at) "
                    f"VALUES (?, ?, ?)",
                    (project, json.dumps(entry), stamp),
                )
            return list(projects)
        if family.legacy_kind == "tasks":
            entries = data.get("tasks") if isinstance(data.get("tasks"), list) else []
            blocks = data.get("stopBlocks")
            if isinstance(blocks, dict) and blocks:
                # Doc-level residue of executed-tasks.json: the per-session stop-hook block
                # budget carries no ruled column, so it lives in meta (DO NOTHING: a re-import
                # must never clobber the newer DB state with legacy counts).
                self.conn.execute(
                    "INSERT INTO meta(key, value) VALUES ('stopBlocks', ?) "
                    "ON CONFLICT(key) DO NOTHING",
                    (json.dumps(blocks),),
                )
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("taskId") is None:
                    continue  # unreachable by find_entry; not expected by the count check
                values = task_row_values(entry)
                self.conn.execute(
                    f"INSERT OR IGNORE INTO tasks({', '.join(values)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
            return [entry["taskId"] for entry in entries
                    if isinstance(entry, dict) and entry.get("taskId") is not None]
        if family.legacy_kind == "usage":
            entries = data.get("tasks") if isinstance(data.get("tasks"), list) else []
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("taskId") is None:
                    continue
                values = usage_row_values(entry)
                self.conn.execute(
                    f"INSERT OR IGNORE INTO token_usage({', '.join(values)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
            return [entry["taskId"] for entry in entries
                    if isinstance(entry, dict) and entry.get("taskId") is not None]
        if family.legacy_kind == "sessions":
            sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
            for session_id, info in sessions.items():
                values = session_row_values(session_id, info)
                self.conn.execute(
                    f"INSERT OR IGNORE INTO sessions({', '.join(values)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
            return list(sessions)
        raise ValueError(f"unsupported family legacy kind: {family.legacy_kind!r}")

    def _import_jsonl(self, family: Family, path: Path) -> list:
        """One JSON object per line, no natural key: exact (ts, payload) content is the key.

        Re-import after a crash between COMMIT and rename re-reads the same lines and finds
        their rows already present, so the import stays idempotent (D6) without a schema-level
        unique column. A torn or non-object line imports nothing and quarantines with the file
        rename, like the doc-kind families.
        """
        expected: list = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            ts = entry.get("ts") if isinstance(entry.get("ts"), str) and entry["ts"] else _now()
            payload = json.dumps(entry)
            exists = self.conn.execute(
                f"SELECT 1 FROM {family.table} WHERE ts = ? AND payload = ?", (ts, payload)
            ).fetchone()
            if exists is None:
                self.conn.execute(
                    f"INSERT INTO {family.table}(ts, payload) VALUES (?, ?)", (ts, payload)
                )
            expected.append((ts, payload))
        return expected


def _open(db_path: Path, kind: str, families: Optional[dict] = None) -> Store:
    _ensure_root(db_path)
    _precreate_db_file(db_path)
    conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    store = Store(conn, db_path, kind, families)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _create_schema(conn)
        _ensure_schema_version(conn, db_path)
        store._check_resurrections()
    except BaseException:
        conn.close()
        raise
    _assert_file_perms(db_path)
    return store


def open_tracking(families: Optional[dict] = None) -> Store:
    """Open (creating when absent) the project tracking store."""
    return _open(tracking_db_path(), "tracking", families)


def open_user(families: Optional[dict] = None) -> Store:
    """Open (creating when absent) the user-level store; defaults to USER_FAMILIES."""
    return _open(user_db_path(), "user", USER_FAMILIES if families is None else families)
