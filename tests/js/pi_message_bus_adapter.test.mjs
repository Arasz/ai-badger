// P6 (aib-user-db-message-bus): the pi adapter's message-bus delivery translations.
//
// The bridge is pure TypeScript loaded directly (node strips types), so every payload,
// response mapping and router branch is unit-tested here against the shapes pi's own
// extension API defines (BeforeAgentStartEventResult.message) and the Claude-shaped
// contract features/common/hooks/message_delivery_hook.py parses. The E2E block at the
// bottom runs the REAL delivery script against an env-redirected user DB
// (AI_BADGER_USER_ROOT / AI_BADGER_RACCOON_DB / CLAUDE_PROJECT_DIR) — the real stores
// are never touched.
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(here, "..", "..");
const BRIDGE = path.join(REPO, "features/pi/adjustments/adapter/hook-bridge.ts");
const DELIVERY_HOOK = path.join(REPO, "features/common/hooks/message_delivery_hook.py");

const bridge = await import(BRIDGE);

const CTX = { cwd: "/tmp/project", sessionId: "sess-1" };

test("toClaudeDeliveryPayload stamps the three Claude event spellings with ctx and no tool fields", () => {
  assert.deepEqual(bridge.toClaudeDeliveryPayload("session_start", CTX), {
    hook_event_name: "SessionStart",
    session_id: "sess-1",
    cwd: "/tmp/project",
  });
  assert.deepEqual(bridge.toClaudeDeliveryPayload("before_agent_start", CTX), {
    hook_event_name: "UserPromptSubmit",
    session_id: "sess-1",
    cwd: "/tmp/project",
  });
  assert.deepEqual(bridge.toClaudeDeliveryPayload("session_shutdown", CTX), {
    hook_event_name: "SessionEnd",
    session_id: "sess-1",
    cwd: "/tmp/project",
  });
});

test("parseDeliveryStdout maps the script's three stdout shapes to context, empty and error", () => {
  // mail: one hookSpecificOutput document carrying the rendered additionalContext
  const mail = { hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: "line 1\nline 2" } };
  assert.deepEqual(bridge.parseDeliveryStdout(JSON.stringify(mail)),
    { kind: "context", content: "line 1\nline 2" });
  // empty inbox: the script's documented no-mail response is {}
  assert.deepEqual(bridge.parseDeliveryStdout("{}"), { kind: "empty" });
  // additionalContext present but empty string — the script never sends it, but a
  // contextless hookSpecificOutput must not inject an empty message
  assert.deepEqual(
    bridge.parseDeliveryStdout(JSON.stringify({ hookSpecificOutput: { additionalContext: "" } })),
    { kind: "empty" },
  );
  // unparseable stdout is an ERROR outcome, never an injection and never a throw
  const garbage = bridge.parseDeliveryStdout("Traceback (most recent call last): ...");
  assert.equal(garbage.kind, "error");
  assert.match(garbage.reason, /not JSON/);
  const silent = bridge.parseDeliveryStdout("");
  assert.equal(silent.kind, "error");
  assert.match(silent.reason, /printed nothing/);
  // a non-string additionalContext is an error outcome too
  const wrong = bridge.parseDeliveryStdout(JSON.stringify({ hookSpecificOutput: { additionalContext: 7 } }));
  assert.equal(wrong.kind, "error");
  assert.match(wrong.reason, /not a string/);
});

test("piMessageFromContext returns exactly pi's BeforeAgentStartEventResult message shape", () => {
  const injection = bridge.piMessageFromContext("bus mail");
  assert.deepEqual(injection, {
    message: { customType: "ai-badger", content: "bus mail", display: true },
  });
  // pi's type is Pick<CustomMessage, "customType" | "content" | "display" | "details">
  // — exactly these keys, nothing extra that a stricter future check would reject
  assert.deepEqual(Object.keys(injection), ["message"]);
  assert.deepEqual(Object.keys(injection.message).sort(), ["content", "customType", "display"]);
});

// --- the router: the subscription state machine index.ts delegates to -----------------

/** A fake spawn scripted per Claude event (a queue per event); records every payload. */
function scriptedSpawn(script) {
  const seen = [];
  const queues = new Map(Object.entries(script));
  const spawn = async (payload) => {
    seen.push(payload);
    const queue = queues.get(payload.hook_event_name);
    if (!queue || queue.length === 0) throw new Error(`unexpected event ${payload.hook_event_name}`);
    return queue.shift();
  };
  return { spawn, seen };
}

test("router hands the start-delivered mail to the first turn exactly once, then goes live", async () => {
  const mail = { kind: "context", content: "start mail" };
  const empty = { kind: "empty" };
  const live = { kind: "context", content: "live mail" };
  const { spawn, seen } = scriptedSpawn({
    SessionStart: [mail],
    UserPromptSubmit: [live, empty],
  });
  const router = bridge.createDeliveryRouter(spawn);

  // session_start fires: the child is launched, nothing injected yet (pi's
  // session_start handlers have no return seam to inject through)
  const atStart = await router.sessionStart(CTX);
  assert.deepEqual(atStart, { notices: [] });
  assert.equal(atStart.injection, undefined);
  assert.deepEqual(seen, [{ hook_event_name: "SessionStart", session_id: "sess-1", cwd: "/tmp/project" }]);

  // the FIRST turn consumes the start delivery through the return seam
  const firstTurn = await router.beforeAgentStart(CTX);
  assert.deepEqual(firstTurn, {
    injection: { message: { customType: "ai-badger", content: "start mail", display: true } },
    notices: [],
  });
  // the start delivery consumed itself: NO second store hit for that turn
  assert.deepEqual(seen.map((p) => p.hook_event_name), ["SessionStart"]);

  // later turns are live deliveries
  const secondTurn = await router.beforeAgentStart(CTX);
  assert.deepEqual(secondTurn, {
    injection: { message: { customType: "ai-badger", content: "live mail", display: true } },
    notices: [],
  });
  assert.deepEqual(seen.map((p) => p.hook_event_name), ["SessionStart", "UserPromptSubmit"]);

  // an empty live inbox injects nothing
  const thirdTurn = await router.beforeAgentStart(CTX);
  assert.deepEqual(thirdTurn, { notices: [] });
  assert.equal(thirdTurn.injection, undefined);
});

test("router falls through to the live read when the start delivery was empty or errored", async () => {
  // an empty START delivery does not mean an empty turn inbox: mail may have arrived
  // between the start child and the first prompt, so the live read must still run
  {
    const { spawn, seen } = scriptedSpawn({
      SessionStart: [{ kind: "empty" }],
      UserPromptSubmit: [{ kind: "context", content: "arrived late" }],
    });
    const router = bridge.createDeliveryRouter(spawn);
    await router.sessionStart(CTX);
    const firstTurn = await router.beforeAgentStart(CTX);
    assert.deepEqual(firstTurn, {
      injection: { message: { customType: "ai-badger", content: "arrived late", display: true } },
      notices: [],
    });
    assert.deepEqual(seen.map((p) => p.hook_event_name), ["SessionStart", "UserPromptSubmit"]);
  }
  // an ERRORED start delivery (spawn failure) falls through too and reports a notice
  {
    const { spawn, seen } = scriptedSpawn({
      SessionStart: [{ kind: "error", reason: "python3 died" }],
      UserPromptSubmit: [{ kind: "context", content: "still delivers" }],
    });
    const router = bridge.createDeliveryRouter(spawn);
    await router.sessionStart(CTX);
    const firstTurn = await router.beforeAgentStart(CTX);
    assert.equal(firstTurn.injection.message.content, "still delivers");
    assert.equal(firstTurn.notices.length, 0, "the start error must not double-report on the turn");
    assert.deepEqual(seen.map((p) => p.hook_event_name), ["SessionStart", "UserPromptSubmit"]);
  }
});

test("router turns a rejecting spawn into a notice — never a throw, never an injection", async () => {
  const rejectingSpawn = async () => {
    throw new Error("ENOENT: python3 missing");
  };
  const router = bridge.createDeliveryRouter(rejectingSpawn);

  // per-turn: the agent loop is unaffected (D31) — a notice, no injection
  const turn = await router.beforeAgentStart(CTX);
  assert.equal(turn.injection, undefined);
  assert.equal(turn.notices.length, 1);
  assert.match(turn.notices[0], /ENOENT/);

  // the same rejection surfacing through the held start promise must not break the turn
  await router.sessionStart(CTX);
  const heldTurn = await router.beforeAgentStart(CTX);
  assert.equal(heldTurn.injection, undefined);
  assert.ok(heldTurn.notices.length >= 1);

  // shutdown: a dead store must not block (or break) teardown (AC3 fail-open)
  const shutdown = await router.sessionShutdown(CTX);
  assert.equal(shutdown.injection, undefined);
  assert.ok(shutdown.notices.length >= 1);
});

test("router's sessionShutdown fires the SessionEnd payload and discards the response", async () => {
  // a close response could never be injected anyway — and must not be: the session is
  // going away. The mail-shaped close response must be dropped, not surfaced.
  const { spawn, seen } = scriptedSpawn({
    SessionEnd: [{ kind: "context", content: "a close event must never inject this" }],
  });
  const router = bridge.createDeliveryRouter(spawn);

  const result = await router.sessionShutdown(CTX);

  assert.deepEqual(seen, [{ hook_event_name: "SessionEnd", session_id: "sess-1", cwd: "/tmp/project" }]);
  assert.deepEqual(result, { notices: [] });
  assert.equal(result.injection, undefined);

  // an EMPTY close response is equally a clean no-op
  const { spawn: spawn2, seen: seen2 } = scriptedSpawn({ SessionEnd: [{ kind: "empty" }] });
  const router2 = bridge.createDeliveryRouter(spawn2);
  const result2 = await router2.sessionShutdown(CTX);
  assert.deepEqual(result2, { notices: [] });
  assert.deepEqual(seen2.length, 1);
});

// --- E2E: the real script against an env-redirected user DB ---------------------------
// Everything below runs the REAL features/common/hooks/message_delivery_hook.py with a
// redirected user store (AI_BADGER_USER_ROOT), a redirected raccoon bank path, a temp
// HOME and an explicit project override — the real ~/.ai-badger/ and ~/.ai-raccoon/
// stores are never touched. This block is the executable pi leg of the @deferred
// close-event verdict (plan §6 Rule 6 / P6-t5): session_shutdown maps to cursor cleanup.

function e2eEnv(root) {
  return {
    PATH: process.env.PATH ?? "/usr/bin:/bin:/usr/sbin:/sbin",
    HOME: root,
    AI_BADGER_USER_ROOT: root,
    AI_BADGER_PROJECT_ID: "P",
    AI_BADGER_RACCOON_DB: path.join(root, "raccoon", "memory.db"),
    CLAUDE_PROJECT_DIR: root,
  };
}

function runDeliveryHook(env, payload) {
  return new Promise((resolvePromise) => {
    const child = spawn("python3", [DELIVERY_HOOK], { env, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += String(chunk); });
    child.stderr.on("data", (chunk) => { stderr += String(chunk); });
    child.on("close", (code) => resolvePromise({ code, stdout, stderr }));
    child.stdin.end(JSON.stringify(payload));
  });
}

function seedMessage(env, senderSession, senderProject, content, targetProject) {
  const code = [
    'import sys; sys.path.insert(0, "features/common/hooks"); import badger_store',
    "store = badger_store.open_user()",
    `store.send_message(sender_session=${JSON.stringify(senderSession)}, sender_project=${JSON.stringify(senderProject)}, content=${JSON.stringify(content)}, target_project=${JSON.stringify(targetProject)})`,
    "store.close()",
  ].join("\n");
  return execFileSync("python3", ["-c", code], { env, encoding: "utf8", cwd: REPO });
}

function cursorRow(env, sessionId) {
  const code = [
    'import sys; sys.path.insert(0, "features/common/hooks"); import badger_store',
    "store = badger_store.open_user()",
    `row = store.conn.execute('SELECT cursor_id FROM cursors WHERE session_id = ?', (${JSON.stringify(sessionId)},)).fetchone()`,
    "print('CURSOR_ROW', row)",
    "store.close()",
  ].join("\n");
  return execFileSync("python3", ["-c", code], { env, encoding: "utf8", cwd: REPO });
}

test("E2E: session_start payload delivers seeded mail through the real script into pi's message shape", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "aib-pi-bus-"));
  const env = e2eEnv(root);
  seedMessage(env, "S1", "P", "bus mail for pi", "P");
  const receiver = { cwd: root, sessionId: "pi-sess-1" };

  // the pi adapter's exact translation: bridge payload → real child → bridge parse
  const firing = await runDeliveryHook(env, bridge.toClaudeDeliveryPayload("session_start", receiver));
  assert.equal(firing.code, 0, `hook exited ${firing.code}: ${firing.stderr}`);
  const outcome = bridge.parseDeliveryStdout(firing.stdout);
  assert.equal(outcome.kind, "context");
  const injection = bridge.piMessageFromContext(outcome.content);
  assert.equal(injection.message.customType, "ai-badger");
  assert.equal(injection.message.display, true);
  assert.match(injection.message.content, /bus mail for pi/);

  // secondary observable: the cursor advanced — a second firing must not re-deliver
  assert.match(cursorRow(env, "pi-sess-1"), /CURSOR_ROW \(\d+,\)/);
  const refire = await runDeliveryHook(env, bridge.toClaudeDeliveryPayload("session_start", receiver));
  assert.deepEqual(bridge.parseDeliveryStdout(refire.stdout), { kind: "empty" });

  // CLOSE-EVENT VERDICT (pi leg): session_shutdown → SessionEnd → the cursor row is gone
  const close = await runDeliveryHook(env, bridge.toClaudeDeliveryPayload("session_shutdown", receiver));
  assert.equal(close.code, 0, `close exited ${close.code}: ${close.stderr}`);
  assert.match(cursorRow(env, "pi-sess-1"), /CURSOR_ROW None/);
}, { timeout: 30_000 });

test("E2E: an empty inbox and the session's own mail both inject nothing at the pi seam", async () => {
  const root = mkdtempSync(path.join(tmpdir(), "aib-pi-bus-"));
  const env = e2eEnv(root);
  const receiver = { cwd: root, sessionId: "pi-sess-2" };

  // no mail at all → the script's {} → no injection (no flood, no fabrications)
  const firing = await runDeliveryHook(env, bridge.toClaudeDeliveryPayload("session_start", receiver));
  assert.equal(firing.code, 0, firing.stderr);
  assert.deepEqual(bridge.parseDeliveryStdout(firing.stdout), { kind: "empty" });

  // self-suppression (Rule 2) at the pi surface: the session's own broadcast must not
  // come back to it — the bridge carries the same session_id the store excludes on
  seedMessage(env, "pi-sess-2", "P", "my own broadcast", "P");
  const own = await runDeliveryHook(env, bridge.toClaudeDeliveryPayload("before_agent_start", receiver));
  assert.equal(own.code, 0, own.stderr);
  assert.deepEqual(bridge.parseDeliveryStdout(own.stdout), { kind: "empty" });
}, { timeout: 30_000 });
