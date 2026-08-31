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
from datetime import datetime, timezone
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
        state             TEXT NOT NULL DEFAULT 'ACTIVE',
        resume_attempts   TEXT NOT NULL DEFAULT '[]',
        state_json_updated INTEGER NOT NULL DEFAULT 0
    )
    """,
    # Defense in depth for the one-active-task-per-session rule (D14); the FINISHED-terminal
    # and attach-refusal checks stay application-level (P0.3).
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_active_session
        ON tasks(session_id) WHERE state <> 'FINISHED'
    """,
    # subagents is a JSON column pending the P0.6a schema-review gate ruling (D1/D15).
    """
    CREATE TABLE IF NOT EXISTS token_usage (
        task_id     TEXT PRIMARY KEY,
        session_id  TEXT,
        subagents   TEXT NOT NULL DEFAULT '[]',
        checkpoints TEXT NOT NULL DEFAULT '{}',
        usage       TEXT NOT NULL DEFAULT '{}',
        grade       TEXT
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


def _create_schema(conn: sqlite3.Connection) -> None:
    for statement in _DDL:
        conn.execute(statement)


def _ensure_schema_version(conn: sqlite3.Connection) -> None:
    """Stamp SCHEMA_VERSION on a fresh DB; dispatch upgrade hooks older; fail closed newer (D27)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        return
    stored = int(row[0])
    if stored > SCHEMA_VERSION:
        raise sqlite3.OperationalError(
            f"store schema version {stored} is newer than this code knows ({SCHEMA_VERSION}); "
            f"refusing to write in an old shape — run den-refresh to upgrade ai-badger "
            f"({tracking_db_path()})"
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
    """One migrating store family: its table, its database, and its legacy JSON source."""

    table: str
    db: str  # "tracking" or "user"
    legacy_path: Callable[[], Path]
    legacy_kind: str  # "map": top-level dict keyed like the table


#: Families with a legacy JSON source to lazy-migrate. marker_state's legacy dir is the
#: prompt-markers sibling of the tracking root (D5/D6; P1/P2 register their families here).
FAMILIES: dict[str, Family] = {
    "marker_state": Family(
        table="marker_state",
        db="tracking",
        legacy_path=lambda: tracking_db_path().parent.parent / "prompt-markers"
        / "marker-state.json",
        legacy_kind="map",
    ),
}


def _stamp_key(table: str) -> str:
    return f"migrated_at.{table}"


def _check_table_name(table: str) -> None:
    """Refuse anything that is not a plain identifier before it reaches an f-string SQL slot."""
    if not _TABLE_NAME.match(table):
        raise ValueError(f"not a store table name: {table!r}")


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
    """One open SQLite store: the raw connection plus KV accessors and lazy family migration."""

    def __init__(self, conn: sqlite3.Connection, db_path: Path, kind: str) -> None:
        self.conn = conn
        self.db_path = db_path
        self.kind = kind

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

    def _legacy_rows(self, table: str) -> dict:
        """Legacy rows still mergeable for *table*; a resurrected legacy file fails closed."""
        family = FAMILIES.get(table)
        if family is None:
            return {}
        path = family.legacy_path()
        if not path.exists():
            return {}
        stamp = self._migration_stamp(table)
        if stamp is not None and path.stat().st_mtime > stamp:
            raise sqlite3.OperationalError(
                f"legacy {path} reappeared after its migration (a stale surface is writing "
                f"behind the store); restore the *.migrated.json name or den-refresh the stale "
                f"surface — the store refuses to diverge"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}  # unreadable legacy file: the DB rows stay authoritative (D31)
        return data if isinstance(data, dict) else {}

    def _check_resurrections(self) -> None:
        """Open-time gate (D5c): a legacy file newer than its migration stamp fails closed."""
        for family in FAMILIES.values():
            if family.db != self.kind:
                continue
            path = family.legacy_path()
            if not path.exists():
                continue
            stamp = self._migration_stamp(family.table)
            if stamp is not None and path.stat().st_mtime > stamp:
                raise sqlite3.OperationalError(
                    f"legacy {path} reappeared after its migration (a stale surface is writing "
                    f"behind the store); restore the *.migrated.json name or den-refresh the "
                    f"stale surface — the store refuses to diverge"
                )

    # -- writes (may raise) ------------------------------------------------------------

    def kv_set(self, table: str, key: str, value: Any) -> None:
        """Write *value* under *key*; the first write lazy-migrates the family (D6)."""
        _check_table_name(table)
        self._migrate(table)
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

    def _migrate(self, table: str) -> None:
        """Import the legacy file into *table* — COMMIT first, rename after, idempotently (D6)."""
        family = FAMILIES.get(table)
        if family is None:
            return
        path = family.legacy_path()
        if not path.exists():
            return
        stamp = self._migration_stamp(table)
        if stamp is not None and path.stat().st_mtime > stamp:
            raise sqlite3.OperationalError(
                f"legacy {path} reappeared after its migration (a stale surface is writing "
                f"behind the store); restore the *.migrated.json name or den-refresh the stale "
                f"surface — the store refuses to diverge"
            )
        with _legacy_lock(path.parent / ".write.lock"):
            if not path.exists():  # re-check under the lock: another writer migrated it
                return
            rows = self._legacy_rows(table)
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for legacy_key, legacy_value in rows.items():
                    self.conn.execute(
                        f"INSERT OR IGNORE INTO {table}(key, value, updated_at) VALUES (?, ?, ?)",
                        (legacy_key, json.dumps(legacy_value), _now()),
                    )
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (_stamp_key(table), str(time.time())),
                )
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
            # Only after COMMIT: a crash before the rename leaves both artifacts, and the
            # next write re-runs this idempotent import (D6).
            os.replace(path, path.with_name(f"{path.stem}.migrated{path.suffix}"))
        _assert_file_perms(self.db_path)


def _open(db_path: Path, kind: str) -> Store:
    _ensure_root(db_path)
    conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    store = Store(conn, db_path, kind)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _create_schema(conn)
        _ensure_schema_version(conn)
        store._check_resurrections()
    except BaseException:
        conn.close()
        raise
    _assert_file_perms(db_path)
    return store


def open_tracking() -> Store:
    """Open (creating when absent) the project tracking store."""
    return _open(tracking_db_path(), "tracking")


def open_user() -> Store:
    """Open (creating when absent) the user-level store."""
    return _open(user_db_path(), "user")
