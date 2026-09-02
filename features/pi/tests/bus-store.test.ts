/**
 * bus-store.ts — the injected I/O port under the prefilter (plan aib-pi-message-bus-push-delivery,
 * package P3; C5, CR-N5iii, QA-8/A11). Everything here is the ONLY code that touches the
 * user database from the adapter: the path mirror of badger_store.user_db_path, the stat
 * identity, and one read-only query. Tests inject paths and env — none of these tests may
 * touch the real ~/.ai-badger DB (CR-N5iii), and the A11 DDL pin creates its store in a
 * temp dir with AI_BADGER_USER_ROOT redirected.
 */

import { describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import {
  openProbeDb,
  probeUserDb,
  readFingerprint,
  statIdentity,
  userDbPath,
} from "../adjustments/adapter/bus-store.ts";

// ---------------------------------------------------------------------------
// the user-db path mirror (badger_store.py:388, user_db_path)
// ---------------------------------------------------------------------------

describe("userDbPath mirrors badger_store.user_db_path exactly", () => {
  test("an absolute AI_BADGER_USER_ROOT wins", () => {
    expect(userDbPath({ AI_BADGER_USER_ROOT: "/tmp/root" }, "/any/cwd")).toBe(
      join("/tmp/root", "ai-badger.db"),
    );
  });

  test("a relative root resolves against the session cwd — the spawn's cwd, same as Python's", () => {
    expect(userDbPath({ AI_BADGER_USER_ROOT: "state" }, "/repo/deep")).toBe(
      resolve("/repo/deep", "state", "ai-badger.db"),
    );
  });

  test("a blank value is unset-like (Python `if env:`): the default home applies", () => {
    expect(userDbPath({ AI_BADGER_USER_ROOT: "" }, "/repo")).toBe(
      join(homedir(), ".ai-badger", "ai-badger.db"),
    );
  });

  test("no env ⇒ ~/.ai-badger/ai-badger.db", () => {
    expect(userDbPath({}, "/repo")).toBe(join(homedir(), ".ai-badger", "ai-badger.db"));
  });
});

// ---------------------------------------------------------------------------
// stat identity — the fingerprint's file-identity half
// ---------------------------------------------------------------------------

describe("statIdentity", () => {
  let dir: string;
  let path: string;

  function fresh(): void {
    dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    path = join(dir, "ai-badger.db");
  }

  function cleanup(): void {
    rmSync(dir, { recursive: true, force: true });
  }

  test("an existing file yields its dev/ino — the same numbers a raw stat sees", () => {
    fresh();
    try {
      writeFileSync(path, "x");
      const st = statSync(path);
      expect(statIdentity(path)).toEqual({
        kind: "ok",
        identity: { dev: st.dev, ino: st.ino },
      });
    } finally {
      cleanup();
    }
  });

  test("an absent file is 'missing' — the sound-skip shape (QA-9), not an error", () => {
    fresh();
    try {
      expect(statIdentity(join(dir, "absent.db"))).toEqual({ kind: "missing" });
    } finally {
      cleanup();
    }
  });

  test("a non-ENOENT stat error is an error, never a throw", () => {
    fresh();
    try {
      writeFileSync(join(dir, "plain.txt"), "x");
      // stat through a FILE component: ENOTDIR, a different errno than ENOENT
      const through = join(dir, "plain.txt", "sub", "ai-badger.db");
      const r = statIdentity(through);
      expect(r.kind).toBe("error");
    } finally {
      cleanup();
    }
  });
});

// ---------------------------------------------------------------------------
// the one probe query — MAX(id) and COUNT(*) in a single SELECT (CR-N3)
// ---------------------------------------------------------------------------

describe("readFingerprint — one query, two aggregates", () => {
  function makeDb(withRows: boolean): { db: InstanceType<typeof DatabaseSync>; path: string; dir: string } {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    const path = join(dir, "ai-badger.db");
    const db = new DatabaseSync(path);
    db.exec(
      "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, " +
        "sender_session TEXT NOT NULL, sender_project TEXT NOT NULL, target_session TEXT, " +
        "target_project TEXT, content TEXT NOT NULL)",
    );
    if (withRows) {
      db.prepare(
        "INSERT INTO messages (ts, sender_session, sender_project, content) VALUES (?, ?, ?, ?)",
      ).run("2026-09-01T00:00:00+00:00", "other", "proj", "one");
      db.prepare(
        "INSERT INTO messages (ts, sender_session, sender_project, content) VALUES (?, ?, ?, ?)",
      ).run("2026-09-01T00:00:01+00:00", "other", "proj", "two");
    }
    return { db, path, dir };
  }

  test("seeded rows yield MAX and COUNT", async () => {
    const { db, path, dir } = makeDb(true);
    try {
      db.close();
      const probe = await openProbeDb(path);
      try {
        expect(readFingerprint(probe)).toEqual({ maxId: 2, count: 2 });
      } finally {
        probe.close();
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("an empty table yields maxId 0 and count 0 — the watermark-0 skip's other half", async () => {
    const { db, path, dir } = makeDb(false);
    try {
      db.close();
      const probe = await openProbeDb(path);
      try {
        expect(readFingerprint(probe)).toEqual({ maxId: 0, count: 0 });
      } finally {
        probe.close();
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a missing table throws — the caller converts to a probe error (fail-open spawn)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    try {
      const path = join(dir, "ai-badger.db");
      const db = new DatabaseSync(path);
      db.exec("CREATE TABLE other (id INTEGER)");
      db.close();
      const probe = await openProbeDb(path);
      try {
        expect(() => readFingerprint(probe)).toThrow();
      } finally {
        probe.close();
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// read-only enforcement — the TS side provably cannot write (A11's negative)
// ---------------------------------------------------------------------------

describe("the probe connection cannot write", () => {
  test("an INSERT attempt through the read-only open throws", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    try {
      const path = join(dir, "ai-badger.db");
      const writer = new DatabaseSync(path);
      writer.exec(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, " +
          "sender_session TEXT NOT NULL, sender_project TEXT NOT NULL, target_session TEXT, " +
          "target_project TEXT, content TEXT NOT NULL)",
      );
      writer.close();

      const probe = await openProbeDb(path);
      try {
        expect(() =>
          probe.exec(
            "INSERT INTO messages (ts, sender_session, sender_project, content) " +
              "VALUES ('2026-09-01T00:00:00+00:00', 'x', 'p', 'the probe must not write')",
          ),
        ).toThrow();
      } finally {
        probe.close();
      }
      // and nothing was written
      const verifier = new DatabaseSync(path);
      try {
        expect(verifier.prepare("SELECT COUNT(*) AS n FROM messages").get()).toEqual({ n: 0 });
      } finally {
        verifier.close();
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// probeUserDb — the composed probe the tick decision consumes
// ---------------------------------------------------------------------------

describe("probeUserDb composes stat + query into one BusProbe", () => {
  test("an absent DB file probes as missing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    try {
      const r = await probeUserDb({ AI_BADGER_USER_ROOT: dir }, "/cwd");
      expect(r).toEqual({ kind: "missing" });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a real DB probes as ok with the full fingerprint", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    try {
      const path = join(dir, "ai-badger.db");
      const db = new DatabaseSync(path);
      db.exec(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, " +
          "sender_session TEXT NOT NULL, sender_project TEXT NOT NULL, target_session TEXT, " +
          "target_project TEXT, content TEXT NOT NULL)",
      );
      db.prepare(
        "INSERT INTO messages (ts, sender_session, sender_project, content) VALUES (?, ?, ?, ?)",
      ).run("2026-09-01T00:00:00+00:00", "other", "proj", "hello");
      db.close();
      const st = statSync(path);

      const r = await probeUserDb({ AI_BADGER_USER_ROOT: dir }, "/cwd");
      expect(r).toEqual({
        kind: "ok",
        fingerprint: { maxId: 1, count: 1, dev: st.dev, ino: st.ino },
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a corrupt DB file probes as an error — never a throw, never a fake empty", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    try {
      writeFileSync(join(dir, "ai-badger.db"), "this is not a sqlite database at all");
      const r = await probeUserDb({ AI_BADGER_USER_ROOT: dir }, "/cwd");
      expect(r.kind).toBe("error");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("a stat error probes as an error (fail-open)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-"));
    try {
      writeFileSync(join(dir, "plain.txt"), "x");
      // a path whose parent is a file: the stat half errors before any sqlite open
      const r = await probeUserDb(
        { AI_BADGER_USER_ROOT: join(dir, "plain.txt", "sub") },
        "/cwd",
      );
      expect(r.kind).toBe("error");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// ---------------------------------------------------------------------------
// A11 (QA-8) — the SQL↔DDL contract pin: the probe query runs against a REAL
// store-created database. The store's DDL is the authority; if a table or column
// the probe names ever drifts, this fails a test instead of silently spawning
// python every 2 s forever (the fail-open direction makes that symptom invisible).
// The store is created by python in a temp dir — never the real user DB (CR-N5iii).
// ---------------------------------------------------------------------------

describe("A11: the probe SQL against a store-created real DB", () => {
  /** Locate the canonical badger_store.py by walking up from this test file. The pin's
   * home is the ai-badger repo, where the Python store lives; a mirror without it (the
   * pbi fork) skips loudly rather than pinning against a copy of the DDL. */
  function findBadgerStore(): string | null {
    let dir = import.meta.dir;
    for (let i = 0; i < 6; i++) {
      const candidate = join(dir, "features", "common", "hooks", "badger_store.py");
      try {
        statSync(candidate);
        return candidate;
      } catch {
        dir = join(dir, "..");
      }
    }
    return null;
  }

  const hooksDir = findBadgerStore();

  test("bus-store's probe reads the store's own schema", async () => {
    if (hooksDir === null) {
      console.warn(
        "[bus-store] LOUD SKIP: A11 DDL pin — no features/common/hooks/badger_store.py above this " +
          "test tree (a mirror without the Python store cannot pin its schema); run this in ai-badger",
      );
      return;
    }
    const dir = mkdtempSync(join(tmpdir(), "aib-bus-store-ddl-"));
    try {
      // Create + seed the real store: open_user runs the store's own DDL, migrations and
      // retention, exactly as any delivery txn would find it. The seeder exits WITHOUT a
      // clean close (os._exit), leaving the committed `-wal`/`-shm` sidecars on disk —
      // the live-session steady state the probe actually sees in production. (Node —
      // the runtime pi loads extensions under — also opens a cleanly-closed, sidecar-less
      // WAL DB read-only, creating the transient sidecars itself; bun 1.4's sqlite build
      // refuses that specific state, so the fixture pins the sidecars-present one.)
      const script = [
        "import sys, os",
        `sys.path.insert(0, ${JSON.stringify(hooksDir.replace(/\/badger_store\.py$/, ""))})`,
        "import badger_store",
        "store = badger_store.open_user()",
        'store.send_message(sender_session="other-1", sender_project="proj", content="one", target_session="sess-1")',
        'store.send_message(sender_session="other-2", sender_project="proj", content="two")',
        "os._exit(0)",
      ].join("\n");
      const proc = Bun.spawnSync(["python3", "-c", script], {
        cwd: dir,
        env: { ...process.env, AI_BADGER_USER_ROOT: dir },
        stdout: "pipe",
        stderr: "pipe",
      });
      expect(new TextDecoder().decode(proc.stderr)).toBe("");
      expect(proc.exitCode).toBe(0);

      // The probe — the exact module the adapter ships — against the store-created DB.
      const r = await probeUserDb({ AI_BADGER_USER_ROOT: dir }, dir);
      expect(r).toEqual({
        kind: "ok",
        fingerprint: { maxId: 2, count: 2, ...identityOf(join(dir, "ai-badger.db")) },
      });

      // The write-negative against the SAME real store DB: a read-only probe must throw
      // on a write attempt, not silently no-op it.
      const probe = await openProbeDb(join(dir, "ai-badger.db"));
      try {
        expect(() =>
          probe.exec(
            "INSERT INTO messages (ts, sender_session, sender_project, content) " +
              "VALUES ('2026-09-01T00:00:00+00:00', 'x', 'p', 'no')",
          ),
        ).toThrow();
      } finally {
        probe.close();
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  function identityOf(path: string): { dev: number; ino: number } {
    const st = statSync(path);
    return { dev: st.dev, ino: st.ino };
  }
});
