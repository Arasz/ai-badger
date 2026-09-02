/**
 * bus-store.ts — the message-bus prefilter's I/O port (plan aib-pi-message-bus-push-delivery,
 * package P3; C5, CR-N5iii, QA-8/A11). This is the ONLY adapter code that touches the user
 * database: the path mirror of badger_store.user_db_path, the file-stat identity, and one
 * read-only query. Everything is composed into `probeUserDb`, whose BusProbe result is the
 * single input the pure tick decision (bus-prefilter.decideTick) consumes.
 *
 * Invariants:
 *  - READ-ONLY, provably: the sqlite connection is opened `readOnly` (a write attempt
 *    throws — pinned by test), every statement is a SELECT, and the handle is opened and
 *    closed within one probe (never held across ticks — a DB replacement must be seen).
 *  - ENOENT is data, not an error: a read-only probe must not create the user DB as a side
 *    effect (QA-9), so a missing file probes as "missing" (the sound skip) instead of
 *    failing open into a spawn that would materialise the DB.
 *  - Every failure is a value, never a throw, once it crosses `probeUserDb` — the caller
 *    cannot forget an error shape (fail-open spawn, D31).
 *  - `node:sqlite` is feature-detected at use: a runtime without it (or a jiti loader that
 *    cannot import it) probes as an error ⇒ always-spawn ⇒ exactly today's seam behavior.
 */

import { statSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import type { BusFingerprint, BusProbe } from "./bus-prefilter.ts";

// ---------------------------------------------------------------------------
// the path mirror (badger_store.py:388, user_db_path — semantics, not a copy)
// ---------------------------------------------------------------------------

/**
 * The user DB path, resolved exactly as the Python store resolves it: `AI_BADGER_USER_ROOT`
 * set to any non-empty string wins (`Path(env) / "ai-badger.db"` — a relative value resolves
 * against the cwd of the process, which for the delivery spawn is the session's cwd); any
 * other case lands at `~/.ai-badger/ai-badger.db`. The spawn inherits this process's env,
 * so both sides derive the same file as long as this mirror agrees with the Python one.
 */
export function userDbPath(env: Record<string, string | undefined>, cwd: string): string {
  const root = env.AI_BADGER_USER_ROOT;
  if (root) return resolve(cwd, root, "ai-badger.db");
  return join(homedir(), ".ai-badger", "ai-badger.db");
}

// ---------------------------------------------------------------------------
// file identity — the fingerprint's stat half
// ---------------------------------------------------------------------------

export type StatIdentity =
  | { kind: "ok"; identity: { dev: number; ino: number } }
  | { kind: "missing" }
  | { kind: "error"; reason: string };

/** statSync, converted to data. ENOENT is "missing" (the sound skip); every other errno
 *  (EACCES, ENOTDIR, …) is an error (fail-open spawn). */
export function statIdentity(dbPath: string): StatIdentity {
  try {
    const st = statSync(dbPath);
    return { kind: "ok", identity: { dev: st.dev, ino: st.ino } };
  } catch (error) {
    if ((error as NodeJS.ErrnoException | null)?.code === "ENOENT") return { kind: "missing" };
    return { kind: "error", reason: String(error) };
  }
}

// ---------------------------------------------------------------------------
// the read-only sqlite probe (feature-detected)
// ---------------------------------------------------------------------------

interface SqliteRow {
  max_id: unknown;
  row_count: unknown;
}

interface SqliteDatabase {
  prepare(sql: string): { get(...params: unknown[]): unknown };
  exec(sql: string): void;
  close(): void;
}

type DatabaseSyncCtor = new (path: string, options?: { readOnly?: boolean }) => SqliteDatabase;

let cachedSqlite: DatabaseSyncCtor | null | undefined;

/** Feature-detect `node:sqlite` once. pi runs extensions under Node (measured, F1), bun
 *  1.4 provides it for tests; any runtime or loader without it yields null ⇒ the probe
 *  reports an error ⇒ the prefilter always spawns (today's behavior, D31). */
async function loadSqlite(): Promise<DatabaseSyncCtor | null> {
  if (cachedSqlite !== undefined) return cachedSqlite;
  try {
    const mod = (await import("node:sqlite")) as { DatabaseSync?: DatabaseSyncCtor };
    cachedSqlite = typeof mod.DatabaseSync === "function" ? mod.DatabaseSync : null;
  } catch {
    cachedSqlite = null;
  }
  return cachedSqlite;
}

/**
 * A read-only connection with a small busy_timeout: WAL readers never block on the
 * delivery txn's BEGIN IMMEDIATE, so a probe cannot collide with a writer; the timeout
 * only bounds the pathological contended open instead of hanging a tick. Throws on any
 * open failure — `probeUserDb` is the conversion point, not this function.
 *
 * (Runtime note, verified on this machine: Node 26.8.1's `node:sqlite` — the runtime pi
 * actually loads extensions under — opens a cleanly-closed WAL-mode DB read-only by
 * creating the transient `-wal`/`-shm` sidecars SQLite needs for the wal-index; bun 1.4's
 * build refuses the same open for an owner-only (0600) sidecar-less DB, so the A11 test
 * fixture chmods its store DB 0644. Neither behavior writes the database file.)
 */
export async function openProbeDb(dbPath: string): Promise<SqliteDatabase> {
  const DatabaseSync = (await loadSqlite()) ?? cachedSqlite;
  if (!DatabaseSync) {
    throw new Error("node:sqlite is not available in this runtime");
  }
  const db = new DatabaseSync(dbPath, { readOnly: true });
  db.exec("PRAGMA busy_timeout = 250");
  return db;
}

/**
 * The ONE probe query (C1/CR-N3): MAX(id) and COUNT(*) in a single SELECT — MAX alone
 * cannot see a same-MAX restore, the count folds CR-N3's hardening in for free. The
 * `messages(id)` spelling is pinned against the store's real DDL by the A11 contract test
 * (features/pi/tests/bus-store.test.ts); drift there must fail a test, not a session.
 */
export function readFingerprint(db: SqliteDatabase): { maxId: number; count: number } {
  const row = db.prepare(
    "SELECT COALESCE(MAX(id), 0) AS max_id, COUNT(*) AS row_count FROM messages",
  ).get() as SqliteRow | null;
  return { maxId: Number(row?.max_id ?? 0), count: Number(row?.row_count ?? 0) };
}

// ---------------------------------------------------------------------------
// the composed probe
// ---------------------------------------------------------------------------

export async function probeUserDb(
  env: Record<string, string | undefined>,
  cwd: string,
): Promise<BusProbe> {
  const dbPath = userDbPath(env, cwd);
  const stat = statIdentity(dbPath);
  if (stat.kind === "missing") return { kind: "missing" };
  if (stat.kind === "error") return { kind: "error", reason: stat.reason };

  const DatabaseSync = await loadSqlite();
  if (DatabaseSync === null) {
    return { kind: "error", reason: "node:sqlite is not available in this runtime" };
  }
  cachedSqlite = DatabaseSync;

  let db: SqliteDatabase;
  try {
    db = await openProbeDb(dbPath);
  } catch (error) {
    return { kind: "error", reason: `probe open failed: ${String(error)}` };
  }
  try {
    const partial: Omit<BusFingerprint, "dev" | "ino"> = readFingerprint(db);
    return { kind: "ok", fingerprint: { ...partial, ...stat.identity } };
  } catch (error) {
    return { kind: "error", reason: `probe query failed: ${String(error)}` };
  } finally {
    try {
      db.close();
    } catch {
      // a failed close must not mask the probe's result
    }
  }
}
