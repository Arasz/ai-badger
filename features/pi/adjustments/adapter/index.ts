/**
 * ai-badger hooks adapter for pi: runs the project's Claude-shaped PreToolUse gates before
 * every tool call and maps their decision back onto pi's `{ block, reason }` contract, and
 * runs the PostToolUse entries (marker recorders, memory telemetry) after every tool result
 * — advisory only, never touching the result. Both arms read the project's
 * `.ai-badger/hooks/hooks.json` at event time; both carry the same session id, because the
 * consulted marker a post arm records is looked up by the pre arm.
 *
 * Installed user-scope at `~/.pi/agent/extensions/ai-badger/index.ts`, never project-local:
 * `.pi/extensions/` is trust-gated, and pi's settings docs state that `-p`, `--mode json` and
 * `--mode rpc` ignore project resources without a saved trust decision — a project-local gate
 * would gate nothing in exactly the headless runs it is most needed for.
 */

import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  AI_BADGER_CUSTOM_TYPE,
  commandsForTool,
  createAwayState,
  createDeliveryRouter,
  parseDeliveryStdout,
  parseHookStdout,
  postCommandsForTool,
  postToolUseCommands,
  preToolUseCommands,
  resolve,
  resolvePost,
  resolveSessionId,
  toClaudeDeliveryPayload,
  toClaudePayload,
  toClaudePostPayload,
  type ClaudeDeliveryPayload,
  type DeliveryOutcome,
  type GateOutcome,
  type HookCommand,
  type PostOutcome,
} from "./hook-bridge.ts";
import {
  advanceAllowed,
  compactingActive,
  decideTick,
  mailSummary,
  managerSessionId,
  pollSecsFromEnv,
  wakePolicyFromEnv,
  wakeRoute,
  type BusFingerprint,
  type BusProbe,
  type BusTickState,
  type WakePolicy,
} from "./bus-prefilter.ts";
import { probeUserDb } from "./bus-store.ts";

const GATE_TIMEOUT_MS = 5000;
/** Timer spawns run off the turn's critical path (nothing gates on them), so their budget
 * is larger than the seam spawns' 5 s — which races the store's own busy_timeout + WAL
 * retries (CR-S5, architect R5). */
const BUS_SPAWN_TIMEOUT_MS = 30_000;
const HOOKS_CONFIG = [".ai-badger", "hooks", "hooks.json"];
const DELIVERY_SCRIPT = [".ai-badger", "hooks", "message_delivery_hook.py"];

/** A timer handle, typed minimally so tests can inject spies. `unref` keeps a live
 * session's poller from delaying pi's exit (pi exits via process.exit on every path). */
export interface BusTimerHandle {
  unref?: () => void;
}

/** The bus wiring's I/O port. Everything that can touch a clock, a database or a process
 * arrives through here, so bun suites inject fakes and never see the real user DB, the
 * real hook script, or the real event loop (CR-N5iii). */
export interface BusDeps {
  setInterval: (fn: () => unknown, ms: number) => BusTimerHandle;
  clearInterval: (handle: BusTimerHandle) => void;
  probeBus: (cwd: string) => Promise<BusProbe>;
  deliver: (payload: ClaudeDeliveryPayload, timeoutMs: number) => Promise<DeliveryOutcome>;
}

function realBusDeps(): BusDeps {
  return {
    setInterval: (fn, ms) => setInterval(fn as () => void, ms),
    clearInterval: (handle) => clearInterval(handle as unknown as Parameters<typeof clearInterval>[0]),
    probeBus: (cwd) => probeUserDb(process.env as Record<string, string | undefined>, cwd),
    deliver: (payload, timeoutMs) =>
      runDelivery(payload, { cwd: payload.cwd, signal: undefined }, timeoutMs),
  };
}

/** Projects already reported as having no hook config; absence is announced once, not per call. */
const absenceReported = new Set<string>();

type Gates = { pre: HookCommand[]; post: HookCommand[] } | { absent: string } | { broken: string };

function loadGates(cwd: string): Gates {
  const path = join(cwd, ...HOOKS_CONFIG);
  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch {
    return { absent: `${path} does not exist` };
  }
  try {
    const parsed = JSON.parse(raw);
    return { pre: preToolUseCommands(parsed), post: postToolUseCommands(parsed) };
  } catch (error) {
    return { broken: `${path} is not valid JSON (${String(error)})` };
  }
}

/** Run one gate command, converting every failure mode into a reportable error outcome. */
function runGate(
  command: string,
  payload: unknown,
  ctx: { cwd: string; signal: AbortSignal | undefined },
): Promise<GateOutcome> {
  return new Promise((settle) => {
    let child;
    try {
      child = spawn("/bin/sh", ["-c", command], {
        cwd: ctx.cwd,
        env: { ...process.env, CLAUDE_PROJECT_DIR: ctx.cwd },
        signal: ctx.signal,
        timeout: GATE_TIMEOUT_MS,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      settle({ kind: "error", reason: `${command} could not start (${String(error)})` });
      return;
    }

    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      settle({ kind: "error", reason: `${command} failed (${String(error)})` });
    });
    child.on("close", (code, signal) => {
      if (signal) {
        settle({ kind: "error", reason: `${command} was killed after ${GATE_TIMEOUT_MS}ms` });
        return;
      }
      if (code !== 0) {
        settle({
          kind: "error",
          reason: `${command} exited ${code}: ${stderr.trim().slice(-400) || "(no stderr)"}`,
        });
        return;
      }
      const decision = parseHookStdout(stdout);
      if (decision === null) {
        settle({
          kind: "error",
          reason: `${command} printed output that is not a hook decision: ${stdout.trim().slice(0, 200)}`,
        });
        return;
      }
      settle({ kind: "decision", decision: decision.decision, reason: decision.reason });
    });

    // A gate that exits or is killed before reading stdin makes this write fail with EPIPE.
    // That is the gate's failure, already reported by the close handler, not a crash for pi.
    child.stdin?.on("error", () => {});
    try {
      child.stdin?.end(JSON.stringify(payload));
    } catch {
      // same case, thrown synchronously
    }
  });
}

/** Every gate outcome for one tool call, including "there are no gates here". */
async function gateOutcomes(
  event: { toolName: string; input: Record<string, unknown> },
  ctx: ExtensionContext,
): Promise<GateOutcome[]> {
  const gates = loadGates(ctx.cwd);
  if ("broken" in gates) return [{ kind: "error", reason: gates.broken }];
  if ("absent" in gates) {
    if (absenceReported.has(ctx.cwd)) return [];
    absenceReported.add(ctx.cwd);
    return [{ kind: "absent", reason: gates.absent }];
  }

  const payload = toClaudePayload(event, {
    cwd: ctx.cwd,
    sessionId: resolveSessionId(ctx, process.env),
  });
  const broken: string[] = [];
  const commands = commandsForTool(gates.pre, payload.tool_name, (reason) => broken.push(reason));
  const outcomes = await Promise.all(
    commands.map((command) => runGate(command, payload, { cwd: ctx.cwd, signal: ctx.signal })),
  );
  // A matcher that does not compile skips its command; that is reported like a gate error
  // rather than vanishing, so a typo'd shipped matcher cannot silently gate nothing.
  return [...broken.map((reason): GateOutcome => ({ kind: "error", reason })), ...outcomes];
}

/** Run one PostToolUse command, converting every failure mode into a reportable outcome.
 * Mirrors runGate's spawn discipline but never parses a decision: post hooks are advisory
 * side effects (marker recording, telemetry), and their stdout is theirs alone. */
function runPostHook(
  command: string,
  payload: unknown,
  ctx: { cwd: string; signal: AbortSignal | undefined },
): Promise<PostOutcome> {
  return new Promise((settle) => {
    let child;
    try {
      child = spawn("/bin/sh", ["-c", command], {
        cwd: ctx.cwd,
        env: { ...process.env, CLAUDE_PROJECT_DIR: ctx.cwd },
        signal: ctx.signal,
        timeout: GATE_TIMEOUT_MS,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      settle({ kind: "error", reason: `${command} could not start (${String(error)})` });
      return;
    }

    let stderr = "";
    child.stdout?.resume(); // drain: post hooks may print; nobody parses it
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      settle({ kind: "error", reason: `${command} failed (${String(error)})` });
    });
    child.on("close", (code, signal) => {
      if (signal) {
        settle({ kind: "error", reason: `${command} was killed after ${GATE_TIMEOUT_MS}ms` });
        return;
      }
      if (code !== 0) {
        settle({
          kind: "error",
          reason: `${command} exited ${code}: ${stderr.trim().slice(-400) || "(no stderr)"}`,
        });
        return;
      }
      settle({ kind: "ok" });
    });

    child.stdin?.on("error", () => {});
    try {
      child.stdin?.end(JSON.stringify(payload));
    } catch {
      // same case, thrown synchronously
    }
  });
}

/** Every post-hook outcome for one tool result. A missing hooks config stays silent here —
 * the pre arm already reports absence once per cwd, and post hooks are advisory. */
async function postHookOutcomes(
  event: { toolName: string; input?: Record<string, unknown>; content?: unknown },
  ctx: ExtensionContext,
): Promise<PostOutcome[]> {
  const gates = loadGates(ctx.cwd);
  if ("broken" in gates) return [{ kind: "error", reason: gates.broken }];
  if ("absent" in gates) return [];

  const payload = toClaudePostPayload(event, {
    cwd: ctx.cwd,
    sessionId: resolveSessionId(ctx, process.env),
  });
  const broken: string[] = [];
  const commands = postCommandsForTool(gates.post, payload.tool_name, (reason) =>
    broken.push(reason),
  );
  const outcomes = await Promise.all(
    commands.map((command) => runPostHook(command, payload, { cwd: ctx.cwd, signal: ctx.signal })),
  );
  return [...broken.map((reason): PostOutcome => ({ kind: "error", reason })), ...outcomes];
}

/** Run one delivery-script firing for the message bus. Mirrors runGate's spawn
 * discipline (env-redirected CLAUDE_PROJECT_DIR, timeout, stdin JSON) but never parses a
 * decision — the response is the mail document the bridge parses. A project without the
 * script is an UNWIRED project (Rule 7 scenario 2): silent no-op, never a notice, never
 * a spawn — the adapter is installed user-globally and most projects have no bus.
 * `timeoutMs` separates the two budgets: seam spawns gate a turn (5 s), timer spawns do
 * not (30 s, CR-S5). */
async function runDelivery(
  payload: ClaudeDeliveryPayload,
  ctx: { cwd: string; signal: AbortSignal | undefined },
  timeoutMs: number = GATE_TIMEOUT_MS,
): Promise<DeliveryOutcome> {
  const script = join(ctx.cwd, ...DELIVERY_SCRIPT);
  if (!existsSync(script)) return { kind: "empty" };
  return new Promise((settle) => {
    let child;
    try {
      child = spawn("python3", [script], {
        cwd: ctx.cwd,
        env: { ...process.env, CLAUDE_PROJECT_DIR: ctx.cwd },
        signal: ctx.signal,
        timeout: timeoutMs,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      settle({ kind: "error", reason: `${script} could not start (${String(error)})` });
      return;
    }

    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("error", (error) => {
      settle({ kind: "error", reason: `${script} failed (${String(error)})` });
    });
    child.on("close", (code, signal) => {
      if (signal) {
        settle({ kind: "error", reason: `${script} was killed after ${timeoutMs}ms` });
        return;
      }
      if (code !== 0) {
        settle({
          kind: "error",
          reason: `${script} exited ${code}: ${stderr.trim().slice(-400) || "(no stderr)"}`,
        });
        return;
      }
      settle(parseDeliveryStdout(stdout));
    });

    child.stdin?.on("error", () => {});
    try {
      child.stdin?.end(JSON.stringify(payload));
    } catch {
      // same case, thrown synchronously
    }
  });
}

export default async function (pi: ExtensionAPI, busDeps: BusDeps = realBusDeps()) {
  // Away mode lives here because pi has no API letting one extension answer another's dialog:
  // the confirm this adapter raises can only be pre-empted by this adapter.
  const away = createAwayState(process.env);

  if (typeof pi?.on !== "function") {
    console.error(
      "ai-badger: pi.on is not a function — this pi build's extension API has moved; the hook gate is not installed.",
    );
    return;
  }

  const apiComplete = typeof pi.registerCommand === "function";
  let apiWarned = false;

  // -----------------------------------------------------------------------
  // Message-bus push state (plan aib-pi-message-bus-push-delivery P3). Per-session,
  // in-memory only — a lost watermark just means "probe once more". `busGeneration`
  // invalidates every in-flight timer callback at shutdown/rebind: a tick that resumes
  // after teardown must not touch the dead session's ctx (an uncaught stale-ctx throw
  // inside a timer callback is FATAL in pi — Lane A F7, measured).
  // -----------------------------------------------------------------------
  interface BusSessionState {
    tick: BusTickState;
    inFlight: boolean;
    /** `session_before_compact` timestamp; cleared by session_compact(_failed) and
     * agent_start, and expired by age (C11). */
    compactingAt: number | null;
    /** agent_start..agent_end hint; `ctx.isIdle()` is the wake-time authority (C11). */
    streaming: boolean;
    /** The timer path's notice latch: at most one failure line per failure streak. */
    failNotified: boolean;
  }
  interface BusSession {
    gen: number;
    state: BusSessionState;
    /** The manager's session id (C6) — may be "": nothing is addressable then. */
    sessionId: string;
    cwd: string;
    policy: WakePolicy;
    ctx: ExtensionContext;
  }

  const freshState = (): BusSessionState => ({
    tick: { lastClean: null, lastSpawnAt: null },
    inFlight: false,
    compactingAt: null,
    streaming: false,
    failNotified: false,
  });

  let busGeneration = 0;
  let busSession: BusSession | null = null;
  let busState: BusSessionState | null = null;
  let busTimer: BusTimerHandle | null = null;

  function notifyQuietly(ctx: ExtensionContext, line: string): void {
    try {
      ctx.ui.notify(line, "warning");
    } catch {
      // the UI may already be tearing down; the state change itself has fired either way
    }
  }

  /** At most one failure line per consecutive-failure streak (per D31's taxonomy): the
   * first failure notifies, continuations are silent, any marker-free parseable outcome
   * (timer or seam) resets the latch. */
  function notifyLatched(session: BusSession, line: string): void {
    if (session.state.failNotified) return;
    session.state.failNotified = true;
    notifyQuietly(session.ctx, line);
  }

  function failureReason(outcome: DeliveryOutcome): string {
    return outcome.kind === "error" ? outcome.reason : "the delivery reported a failure marker";
  }

  /** C11: `ctx.isIdle()` is the wake-time authority; the agent_start/agent_end flag is
   * only the fallback for a context that cannot answer. */
  function sessionIdle(session: BusSession): boolean {
    try {
      return session.ctx.isIdle();
    } catch {
      return !session.state.streaming;
    }
  }

  /** The shared spawn tail: run the delivery, then — and only then — advance the watermark
   * to the TICK-TIME fingerprint captured before the spawn (CR-M3, never a post-spawn
   * re-read) on a parseable outcome without the failure marker (CR-M1). A failure-marked,
   * errored or timed-out outcome leaves the watermark stale, so the next tick retries. */
  async function spawnAndSettle(
    payload: ClaudeDeliveryPayload,
    timeoutMs: number,
    state: BusSessionState,
    tickFingerprint: BusFingerprint | undefined,
  ): Promise<DeliveryOutcome> {
    state.inFlight = true;
    try {
      const outcome = await busDeps.deliver(payload, timeoutMs);
      if (advanceAllowed(outcome)) {
        if (tickFingerprint !== undefined) state.tick.lastClean = tickFingerprint;
        state.failNotified = false; // success — timer or seam — resets the notice latch
      }
      return outcome;
    } finally {
      state.inFlight = false;
    }
  }

  /** The seam decorator AROUND the delivery router's spawn closure: every seam spawn runs
   * the same prefilter the timer runs (C1's CR-N4a), so a provably-empty inbox skips the
   * python spawn entirely and every error fails OPEN to today's behavior. Gating is spawn
   * economy and is wake-policy-INDEPENDENT — under `off` the seams still prefilter (C7).
   * An in-flight spawn for the session makes a concurrent txn provably return nothing (the
   * store's exactly-once txn serializes; the loser reads the advanced cursor), so the
   * second spawn skips silently. */
  async function gatedDelivery(payload: ClaudeDeliveryPayload, timeoutMs: number): Promise<DeliveryOutcome> {
    const state = busState ?? (busState = freshState());
    if (state.inFlight) return { kind: "empty" };
    const probe = await busDeps.probeBus(payload.cwd);
    const decision = decideTick(state.tick, probe, Date.now());
    state.tick = decision.state;
    if (decision.action === "skip") return { kind: "empty" };
    return spawnAndSettle(payload, timeoutMs, state, decision.tickFingerprint);
  }

  /** One timer tick (C1 as amended). Full try/catch and a generation re-check after every
   * await: a stale callback must never throw out of the interval (F7) and never touch a
   * dead session. */
  async function busTick(session: BusSession): Promise<void> {
    try {
      if (busSession !== session || busGeneration !== session.gen) return;
      const state = session.state;
      if (compactingActive(Date.now(), state.compactingAt)) return; // C11: defer while compacting
      if (!session.sessionId) return; // nothing addressable — skip silently
      if (state.inFlight) return; // one spawn per session at a time; ticks are 2s, spawns 5–30s

      const probe = await busDeps.probeBus(session.cwd);
      if (busSession !== session || busGeneration !== session.gen) return;
      const decision = decideTick(state.tick, probe, Date.now());
      state.tick = decision.state;
      if (decision.action === "skip") return;

      if (probe.kind === "error") {
        notifyLatched(
          session,
          `ai-badger: message bus probe failed, delivery spawned anyway — ${probe.reason}`,
        );
      }

      const outcome = await spawnAndSettle(
        toClaudeDeliveryPayload("before_agent_start", { cwd: session.cwd, sessionId: session.sessionId }),
        BUS_SPAWN_TIMEOUT_MS,
        state,
        decision.tickFingerprint,
      );
      if (busSession !== session || busGeneration !== session.gen) return;

      if (!advanceAllowed(outcome)) {
        // failure marker / error / timeout: the cursor may not have moved — the watermark
        // stays stale (the next tick retries) and the streak's first failure notifies.
        notifyLatched(session, `ai-badger: message delivery tick failed — ${failureReason(outcome)}`);
        return;
      }
      if (outcome.kind === "context") {
        const routing = wakeRoute(mailSummary(outcome.bus), { idle: sessionIdle(session) }, session.policy);
        try {
          await pi.sendMessage(
            { customType: AI_BADGER_CUSTOM_TYPE, content: outcome.content, display: true },
            routing,
          );
        } catch (error) {
          // stale ctx: silent — the session is gone and a notice has no UI left (F7)
          if (!String(error).includes("stale")) {
            notifyLatched(session, `ai-badger: message wake failed — ${String(error)}`);
          }
        }
      }
    } catch {
      // never fatal: anything thrown inside a timer callback kills the process (F7)
    }
  }

  function disarmBus(): void {
    if (busTimer !== null) {
      try {
        busDeps.clearInterval(busTimer);
      } catch {
        // a spy or a dead loop must not block shutdown
      }
      busTimer = null;
    }
    busGeneration += 1;
    busSession = null;
    busState = null;
  }

  // Skills contribution (plan §1 M4, decision D2): UNGATED. pi honors
  // source-verified skillPaths in all modes (agent-session.js:1920-1941) and
  // derives the event from the session cwd (runner.js:935-947), so the handler
  // reads event.cwd and never the extension context — no ctx.cwd, no
  // isProjectTrusted(): the effective trust decision is installing this adapter
  // user-globally (ADR-0023's recorded asymmetry, calibrated by the pre-existing
  // hooks-shell-command channel, ADR-0022). Absent-safe: a project without
  // .ai-badger/skills contributes no paths and never throws.
  pi.on("resources_discover", (event) => {
    const skillsDir = join(event.cwd, ".ai-badger", "skills");
    if (!existsSync(skillsDir)) return { skillPaths: [] };
    return { skillPaths: [skillsDir] };
  });

  pi.on("tool_call", async (event, ctx) => {
    if (!apiWarned && !apiComplete) {
      apiWarned = true;
      ctx.ui.notify(
        "ai-badger: pi.registerCommand is missing — this pi build's extension API has moved; commands are unavailable.",
        "warning",
      );
    }

    const outcomes = await gateOutcomes(
      { toolName: event.toolName, input: event.input as Record<string, unknown> },
      ctx,
    );
    const resolution = resolve(outcomes, { armed: away.armed(), hasUI: ctx.hasUI });
    for (const notice of resolution.notices) ctx.ui.notify(notice, "warning");

    if (resolution.action === "block") {
      return { block: true, reason: resolution.reason ?? "blocked by an ai-badger hook gate" };
    }
    if (resolution.action === "confirm") {
      const approved = await ctx.ui.confirm(
        "ai-badger hook gate",
        resolution.reason ?? "Allow this tool call?",
      );
      if (!approved) return { block: true, reason: resolution.reason ?? "declined" };
    }
    return undefined;
  });

  pi.on("tool_result", async (event, ctx) => {
    const outcomes = await postHookOutcomes(
      {
        toolName: event.toolName,
        input: (event.input ?? {}) as Record<string, unknown>,
        content: (event as { content?: unknown }).content,
      },
      ctx,
    );
    for (const notice of resolvePost(outcomes).notices) ctx.ui.notify(notice, "warning");
    return undefined; // advisory: the tool result is never modified
  });

  // Message-bus delivery (plan aib-user-db-message-bus §3 P6; start-spawn deferred per
  // D4/P4): the same Claude-shaped delivery script Claude and Copilot run, translated
  // through the bridge's router. There is no session_start delivery — a session that
  // never turns consumes nothing. before_agent_start injects through the result-message
  // seam; the per-turn context event appends mail that arrived between LLM calls;
  // session_shutdown is cursor cleanup.
  const deliveryCtx = (ctx: ExtensionContext) => ({
    cwd: ctx.cwd,
    sessionId: resolveSessionId(ctx, process.env),
  });
  // The router's spawn closure, decorated with the same prefilter the timer runs. The one
  // exception is the close event: cursor cleanup is NOT mail (its response is discarded),
  // so it stays ungated — the prefilter must never decide whether cleanup happens.
  const router = createDeliveryRouter((payload) =>
    payload.hook_event_name === "SessionEnd"
      ? busDeps.deliver(payload, GATE_TIMEOUT_MS)
      : gatedDelivery(payload, GATE_TIMEOUT_MS),
  );

  // Timer arm/disarm (F8's sanctioned lifecycle: defer background work to session_start,
  // clean it up in session_shutdown). Arming conditions, all three required: a delivery
  // script in this project (the silent-unwired rule — no timer, no probe, no spawn), a
  // mode with a persistent idle session (tui/rpc — print/json bind at stdin EOF, F7), and
  // a non-off wake policy (C7 keeps the seam decorator above ON under off). Rebinds
  // (/new, /resume, /fork, /clone re-fire session_start after session_shutdown, F10)
  // clear any prior timer and reset state: the first tick of a session always probes.
  pi.on("session_start", (_event, ctx) => {
    if (busTimer !== null) {
      try {
        busDeps.clearInterval(busTimer);
      } catch {
        // same tolerance as disarmBus
      }
      busTimer = null;
    }
    busGeneration += 1;
    busState = freshState();

    const wake = wakePolicyFromEnv(process.env);
    if (wake.warn) notifyQuietly(ctx, wake.warn);
    const poll = pollSecsFromEnv(process.env);
    if (poll.warn) notifyQuietly(ctx, poll.warn);

    const session: BusSession = {
      gen: busGeneration,
      state: busState,
      sessionId: managerSessionId(ctx),
      cwd: ctx.cwd,
      policy: wake.policy,
      ctx,
    };
    busSession = session;

    if (
      wake.policy !== "off" &&
      (ctx.mode === "tui" || ctx.mode === "rpc") &&
      existsSync(join(ctx.cwd, ...DELIVERY_SCRIPT))
    ) {
      busTimer = busDeps.setInterval(() => busTick(session), poll.secs * 1000);
      busTimer.unref?.(); // an unref'd tick never delays pi's exit (F8)
    }
  });

  // The flag pairs are two boolean writes each — no I/O (C11/CR-S3). A missed clear cannot
  // wedge push: the compacting timestamp expires and agent_start clears it; the wake
  // routing consults ctx.isIdle() as the authority regardless.
  pi.on("session_before_compact", () => {
    if (busState) busState.compactingAt = Date.now();
  });
  pi.on("session_compact", () => {
    if (busState) busState.compactingAt = null;
  });
  pi.on("session_compact_failed", () => {
    if (busState) busState.compactingAt = null;
  });
  pi.on("agent_start", () => {
    if (!busState) return;
    busState.compactingAt = null; // a live agent run also clears a stuck compaction flag
    busState.streaming = true;
  });
  pi.on("agent_end", () => {
    if (busState) busState.streaming = false;
  });

  pi.on("before_agent_start", async (_event, ctx) => {
    const { injection, notices } = await router.beforeAgentStart(deliveryCtx(ctx));
    for (const notice of notices) ctx.ui.notify(notice, "warning");
    return injection; // undefined = inject nothing this turn
  });

  pi.on("context", async (event, ctx) => {
    const { injection, notices } = await router.context(deliveryCtx(ctx));
    for (const notice of notices) ctx.ui.notify(notice, "warning");
    if (!injection) return undefined; // no mail between tasks: the array passes through unmodified
    return { messages: [...event.messages, injection.message] };
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    // Disarm + invalidate FIRST (before the router's cursor-cleanup spawn): an in-flight
    // tick's post-await checks then fail, and its sends are bounded (CR-N5i).
    disarmBus();
    const { notices } = await router.sessionShutdown(deliveryCtx(ctx));
    for (const notice of notices) {
      try {
        ctx.ui.notify(notice, "warning");
      } catch {
        // the UI may already be tearing down; the cleanup itself has fired either way
      }
    }
    return undefined;
  });

  if (!apiComplete) return;
  pi.registerCommand("away", {
    description: "Toggle ai-badger away mode: auto-approve hook gates that ask (never a deny)",
    handler: async (_args, ctx) => {
      const armed = away.toggle();
      ctx.ui.notify(
        armed
          ? "ai-badger away mode ON — an explicit 'ask' is auto-approved and notified; denials and gate errors are unaffected."
          : "ai-badger away mode OFF — an 'ask' prompts again.",
        "info",
      );
    },
  });
}
