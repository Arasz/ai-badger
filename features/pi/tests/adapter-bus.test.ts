/**
 * The adapter's push-delivery wiring (plan aib-pi-message-bus-push-delivery, package P3),
 * driven the way pi drives it: session_start / session_shutdown / compaction / agent events
 * against the real default export, with the timer + probe + delivery I/O injected (CR-N5iii:
 * no bun test touches the real user DB, spawns the real hook, or uses the real clock-happy
 * setInterval).
 *
 * Gate names follow the qa review's amended A-list: A1 (off ⇒ NO timer handle), A4 (mode
 * gating), A5 (lifecycle/rebind), A6 (stale-ctx caught, not fatal), A7 (manager-id
 * authority), A8 (wake routing), A9 (watermark advance at the wiring level), A10
 * (compaction flag incl. session_compact_failed), A12 (probe-error notice latch), plus the
 * seam decorator's gating (C7) and the 30 s timer-spawn timeout (CR-S5).
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import adapter from "../adjustments/adapter/index.ts";
import type { BusTimerHandle } from "../adjustments/adapter/index.ts";
import type { BusFingerprint, BusProbe } from "../adjustments/adapter/bus-prefilter.ts";
import type { ClaudeDeliveryPayload, DeliveryOutcome } from "../adjustments/adapter/hook-bridge.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown> | unknown;

interface RecordedSpawn {
  payload: ClaudeDeliveryPayload;
  timeoutMs: number;
}

function fp(maxId: number, count: number, dev = 1, ino = 2): BusFingerprint {
  return { maxId, count, dev, ino };
}

function ok(f: BusFingerprint): BusProbe {
  return { kind: "ok", fingerprint: f };
}

/** A pi extension context: session-manager id, isIdle, a notify sink, one mode. */
function busCtx(
  cwd: string,
  opts?: { mode?: string; sessionId?: string; idle?: boolean },
): Record<string, unknown> & { notices: string[] } {
  const notices: string[] = [];
  return {
    cwd,
    mode: opts?.mode ?? "tui",
    hasUI: false,
    signal: undefined,
    isIdle: () => opts?.idle ?? true,
    sessionManager: { getSessionId: () => opts?.sessionId ?? "sess-1" },
    ui: { notify: (m: string) => notices.push(m), confirm: async () => false },
    notices,
  };
}

/** A project the adapter considers "wired": the delivery script exists (never executed —
 * deliver is injected), and the hooks gates dir can exist or not, unrelated to the bus. */
function makeWiredProject(): string {
  const dir = mkdtempSync(join(tmpdir(), "aib-bus-adapter-"));
  mkdirSync(join(dir, ".ai-badger", "hooks"), { recursive: true });
  writeFileSync(join(dir, ".ai-badger", "hooks", "message_delivery_hook.py"), "# fixture\n");
  return dir;
}

async function loadBusAdapter(overrides?: {
  probe?: (cwd: string) => Promise<BusProbe>;
  deliver?: (payload: ClaudeDeliveryPayload, timeoutMs: number) => Promise<DeliveryOutcome>;
  sendMessage?: (message: unknown, options: unknown) => unknown;
}) {
  const on = new Map<string, Handler>();
  const timers: Array<{ fn: () => unknown; ms: number; handle: BusTimerHandle & { id: number } }> = [];
  const cleared: Array<BusTimerHandle> = [];
  const sent: Array<{ message: unknown; options: unknown }> = [];
  let seq = 0;

  await adapter(
    {
      on: (event: string, handler: Handler) => {
        on.set(event, handler);
      },
      registerCommand: () => {},
      sendMessage: (message: unknown, options: unknown) => {
        if (overrides?.sendMessage) return overrides.sendMessage(message, options);
        sent.push({ message, options });
        return undefined;
      },
    } as never,
    {
      setInterval: (fn: () => unknown, ms: number) => {
        const handle: BusTimerHandle & { id: number } = { id: ++seq };
        timers.push({ fn, ms, handle });
        return handle;
      },
      clearInterval: (handle: BusTimerHandle) => {
        cleared.push(handle);
      },
      probeBus: overrides?.probe ?? (async () => ok(fp(0, 0, 1, 2))),
      deliver:
        overrides?.deliver ??
        (async () => ({ kind: "empty" }) as DeliveryOutcome),
    },
  );

  const start = async (ctx: Record<string, unknown>) => on.get("session_start")!({}, ctx);
  const shutdown = async (ctx: Record<string, unknown>) => on.get("session_shutdown")!({}, ctx);
  const beforeCompact = async (ctx: Record<string, unknown>) =>
    on.get("session_before_compact")!({}, ctx);
  const compact = async (ctx: Record<string, unknown>) => on.get("session_compact")!({}, ctx);
  const compactFailed = async (ctx: Record<string, unknown>) =>
    on.get("session_compact_failed")!({}, ctx);
  const agentStart = async (ctx: Record<string, unknown>) => on.get("agent_start")!({}, ctx);
  const fireTick = async (which = 0) => {
    expect(timers.length > which).toBe(true);
    await timers[which]!.fn();
  };

  return { on, timers, cleared, sent, start, shutdown, beforeCompact, compact, compactFailed, agentStart, fireTick };
}

describe("push-delivery wiring", () => {
  let dir: string;
  let probeResult: BusProbe;
  let probeCalls: number;
  let deliverResult: DeliveryOutcome;
  let deliverCalls: RecordedSpawn[];

  beforeEach(() => {
    dir = makeWiredProject();
    probeResult = ok(fp(7, 7, 1, 2));
    probeCalls = 0;
    deliverResult = { kind: "empty" };
    deliverCalls = [];
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
    delete process.env.AI_BADGER_PI_BUS_WAKE;
    delete process.env.AI_BADGER_PI_BUS_POLL_SECS;
    delete process.env.PI_SESSION_ID;
  });

  const probe = async () => {
    probeCalls += 1;
    return probeResult;
  };
  const deliver = async (payload: ClaudeDeliveryPayload, timeoutMs: number) => {
    deliverCalls.push({ payload, timeoutMs });
    return deliverResult;
  };

  // -----------------------------------------------------------------------
  // A1 — AI_BADGER_PI_BUS_WAKE=off means the interval is NEVER CREATED
  // -----------------------------------------------------------------------

  test("A1: wake=off arms no timer handle at all — not a timer that no-ops", async () => {
    process.env.AI_BADGER_PI_BUS_WAKE = "off";
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));

    expect(h.timers).toHaveLength(0);
    // and the seams still deliver under off (C7): the decorator is policy-independent
    deliverResult = { kind: "context", content: "mail", bus: { addressed: 1, broadcast: 0 } };
    const ctx = busCtx(dir);
    const injection = await h.on.get("before_agent_start")!({}, ctx);
    expect(deliverCalls).toHaveLength(1);
    expect((injection as { message?: { content: string } }).message?.content).toBe("mail");
  });

  test("A1: the default policy arms the timer, garbage falls back to it with a notice", async () => {
    process.env.AI_BADGER_PI_BUS_WAKE = "sometimes";
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);

    expect(h.timers).toHaveLength(1);
    expect(ctx.notices.some((n) => n.includes("AI_BADGER_PI_BUS_WAKE"))).toBe(true);
  });

  // -----------------------------------------------------------------------
  // A4 — the timer arms for tui/rpc only, and only with a delivery script
  // -----------------------------------------------------------------------

  test("A4: print and json modes never arm; rpc and tui do", async () => {
    for (const mode of ["json", "print"]) {
      const h = await loadBusAdapter({ probe, deliver });
      await h.start(busCtx(dir, { mode }));
      expect(h.timers, `mode=${mode} must not arm`).toHaveLength(0);
    }
    for (const mode of ["rpc", "tui"]) {
      const h = await loadBusAdapter({ probe, deliver });
      await h.start(busCtx(dir, { mode }));
      expect(h.timers, `mode=${mode} must arm`).toHaveLength(1);
    }
  });

  test("A4: an unwired project (no delivery script) never arms", async () => {
    rmSync(join(dir, ".ai-badger", "hooks", "message_delivery_hook.py"));
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    expect(h.timers).toHaveLength(0);
  });

  test("A2 at the wiring: the poll env value is the one scheduled (5s ⇒ 5000ms; default ⇒ 2000ms)", async () => {
    const plain = await loadBusAdapter({ probe, deliver });
    await plain.start(busCtx(dir));
    expect(plain.timers[0]!.ms).toBe(2000);

    process.env.AI_BADGER_PI_BUS_POLL_SECS = "5";
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    expect(h.timers[0]!.ms).toBe(5000);
  });

  // -----------------------------------------------------------------------
  // A5 — lifecycle: cleared at shutdown, cursor cleanup ungated, rebind-safe
  // -----------------------------------------------------------------------

  test("A5: shutdown clears the timer and runs the cursor-cleanup spawn (ungated — no probe)", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    expect(h.timers).toHaveLength(1);

    await h.shutdown(ctx);
    expect(h.cleared).toEqual([h.timers[0]!.handle]);
    expect(deliverCalls).toHaveLength(1);
    expect(deliverCalls[0]!.payload.hook_event_name).toBe("SessionEnd");
    expect(probeCalls).toBe(0); // cleanup is not mail: the prefilter never gates it
  });

  test("A5: double shutdown is harmless", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    await h.shutdown(ctx);
    await h.shutdown(ctx);
    expect(h.cleared).toHaveLength(1);
  });

  test("A5: a rebind (shutdown → session_start) polls the NEW session's id, watermark reset", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { sessionId: "sess-a" }));
    await h.shutdown(busCtx(dir));
    await h.start(busCtx(dir, { sessionId: "sess-b" }));

    await h.fireTick(1); // the second arm's timer
    expect(deliverCalls).toHaveLength(2); // cleanup spawn + this tick's mail poll
    const tickSpawn = deliverCalls[1]!;
    expect(tickSpawn.payload.session_id).toBe("sess-b");
    expect(tickSpawn.payload.hook_event_name).toBe("UserPromptSubmit");
  });

  // -----------------------------------------------------------------------
  // A6 — a stale timer callback is caught, never fatal (Lane A F7)
  // -----------------------------------------------------------------------

  test("A6: a tick firing after shutdown does nothing and does not throw", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    const staleTick = h.timers[0]!.fn;
    await h.shutdown(ctx);

    probeCalls = 0;
    deliverCalls.length = 0;
    await staleTick(); // must resolve — an uncaught throw here kills the process
    expect(probeCalls).toBe(0);
    expect(deliverCalls).toHaveLength(0);
  });

  test("A6: a sendMessage that throws the pi stale-ctx error is caught, callback completes", async () => {
    deliverResult = { kind: "context", content: "mail", bus: { addressed: 1, broadcast: 0 } };
    const h = await loadBusAdapter({
      probe,
      deliver,
      sendMessage: () => {
        throw new Error("This extension ctx is stale after session replacement or reload");
      },
    });
    const ctx = busCtx(dir);
    await h.start(ctx);
    await h.fireTick(); // must resolve
    expect(deliverCalls).toHaveLength(1);
  });

  // -----------------------------------------------------------------------
  // A7 — the wake path keys on the session manager's id only (C6)
  // -----------------------------------------------------------------------

  test("A7: the tick's payload keys on the manager id, never the PI_SESSION_ID env", async () => {
    process.env.PI_SESSION_ID = "env-id";
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { sessionId: "sm-id" }));

    await h.fireTick();
    expect(deliverCalls).toHaveLength(1);
    expect(deliverCalls[0]!.payload.session_id).toBe("sm-id");
  });

  test("A7: an empty manager id skips the tick silently — nothing is addressable", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { sessionId: "" }));

    await h.fireTick();
    expect(probeCalls).toBe(0);
    expect(deliverCalls).toHaveLength(0);
  });

  // -----------------------------------------------------------------------
  // A8 — wake routing from the P2 summary, at the pi.sendMessage call
  // -----------------------------------------------------------------------

  test("A8: idle + addressed mail ⇒ one sendMessage followUp with triggerTurn", async () => {
    deliverResult = { kind: "context", content: "mail body", bus: { addressed: 2, broadcast: 1 } };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { idle: true }));

    await h.fireTick();
    expect(h.sent).toHaveLength(1);
    expect(h.sent[0]!.message).toEqual({
      customType: "ai-badger",
      content: "mail body",
      display: true,
    });
    expect(h.sent[0]!.options).toEqual({ deliverAs: "followUp", triggerTurn: true });
  });

  test("A8: idle + broadcast-only under the default policy ⇒ steer without a wake (C3)", async () => {
    deliverResult = { kind: "context", content: "shout", bus: { addressed: 0, broadcast: 3 } };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { idle: true }));

    await h.fireTick();
    expect(h.sent).toHaveLength(1);
    expect(h.sent[0]!.options).toEqual({ deliverAs: "steer", triggerTurn: false });
  });

  test("A8: streaming + addressed ⇒ steer, never a second triggerTurn", async () => {
    deliverResult = { kind: "context", content: "mail", bus: { addressed: 1, broadcast: 0 } };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { idle: false }));

    await h.fireTick();
    expect(h.sent[0]!.options).toEqual({ deliverAs: "steer", triggerTurn: false });
  });

  test("A8: streaming + broadcast-only under all ⇒ followUp without a wake", async () => {
    process.env.AI_BADGER_PI_BUS_WAKE = "all";
    deliverResult = { kind: "context", content: "shout", bus: { addressed: 0, broadcast: 1 } };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { idle: false }));

    await h.fireTick();
    expect(h.sent[0]!.options).toEqual({ deliverAs: "followUp", triggerTurn: false });
  });

  test("A8: a clean empty response sends nothing", async () => {
    deliverResult = { kind: "empty" };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));

    await h.fireTick();
    expect(h.sent).toHaveLength(0);
  });

  test("A8/C10: a mail response with NO summary (old hook copy) wakes as addressed", async () => {
    deliverResult = { kind: "context", content: "legacy mail" };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir, { idle: true }));

    await h.fireTick();
    expect(h.sent).toHaveLength(1);
    expect(h.sent[0]!.options).toEqual({ deliverAs: "followUp", triggerTurn: true });
  });

  test("A9 at the wiring: the failure marker sends nothing and never advances", async () => {
    deliverResult = { kind: "empty", bus: { error: true } };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));

    await h.fireTick();
    expect(h.sent).toHaveLength(0);
    // no advance ⇒ the identical next tick spawns again (retry, CR-M1)
    await h.fireTick();
    expect(deliverCalls).toHaveLength(2);
  });

  // -----------------------------------------------------------------------
  // A9 — the watermark advances on marker-free parseable outcomes, to the
  // tick-time capture, and to nothing else
  // -----------------------------------------------------------------------

  test("A9: a mail-bearing parseable outcome ADVANCES (tick-time capture, CR-M3) — the identical next tick skips", async () => {
    deliverResult = { kind: "context", content: "mail", bus: { addressed: 1, broadcast: 0 } };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));

    await h.fireTick();
    expect(deliverCalls).toHaveLength(1);
    await h.fireTick();
    expect(deliverCalls).toHaveLength(1); // skipped: MAX+COUNT+identity equal the advanced capture
  });

  test("A9: a clean empty outcome advances too; an error outcome never advances", async () => {
    deliverResult = { kind: "empty" };
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    await h.fireTick();
    await h.fireTick();
    expect(deliverCalls).toHaveLength(1); // advanced on {}

    deliverResult = { kind: "error", reason: "killed after 30000ms" };
    probeResult = ok(fp(9, 9, 1, 2)); // a send moved MAX ⇒ probe differs ⇒ spawn
    await h.fireTick();
    expect(deliverCalls).toHaveLength(2);
    // the error outcome left the watermark stale: the same probe spawns again
    await h.fireTick();
    expect(deliverCalls).toHaveLength(3);
  });

  test("A9: a changed MAX always spawns, whichever class of message moved it", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    deliverResult = { kind: "empty" };

    await h.fireTick(); // first tick: watermark null ⇒ spawn, advances to fp(7,7)
    probeResult = ok(fp(8, 8, 1, 2)); // a 1:1 for another session / a project row / a broadcast
    await h.fireTick();
    expect(deliverCalls).toHaveLength(2);
  });

  // -----------------------------------------------------------------------
  // A10 — the compaction flag defers ticks; compact AND compact_failed clear it
  // -----------------------------------------------------------------------

  test("A10: session_before_compact defers the tick — no probe I/O, no spawn", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    await h.beforeCompact(ctx);

    await h.fireTick();
    expect(probeCalls).toBe(0);
    expect(deliverCalls).toHaveLength(0);
  });

  test("A10: session_compact clears the flag and the tick resumes", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    await h.beforeCompact(ctx);
    await h.compact(ctx);

    await h.fireTick();
    expect(probeCalls).toBe(1);
    expect(deliverCalls).toHaveLength(1);
  });

  test("A10: session_compact_failed ALSO clears the flag (the drift-prone half, QA-6)", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    await h.beforeCompact(ctx);
    await h.compactFailed(ctx);

    await h.fireTick();
    expect(probeCalls).toBe(1);
    expect(deliverCalls).toHaveLength(1);
  });

  test("A10/C11: agent_start clears a stuck compaction flag", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);
    await h.beforeCompact(ctx);
    await h.agentStart(ctx);

    await h.fireTick();
    expect(probeCalls).toBe(1);
  });

  // -----------------------------------------------------------------------
  // A12 — the probe-error path fails open AND notifies at most once per streak
  // -----------------------------------------------------------------------

  test("A12: a probe error spawns anyway and latches its notice; a success resets the latch", async () => {
    probeResult = { kind: "error", reason: "no such table: messages" };
    deliverResult = { kind: "empty", bus: { error: true } }; // the broken-store shape (C2b)
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);

    await h.fireTick();
    expect(deliverCalls).toHaveLength(1); // fail-open: spawned despite the probe error
    const streakNotices = ctx.notices.filter((n) => n.includes("message bus probe failed"));
    expect(streakNotices).toHaveLength(1);

    await h.fireTick();
    await h.fireTick();
    expect(deliverCalls).toHaveLength(3); // still failing open every tick
    expect(ctx.notices.filter((n) => n.includes("message bus probe failed"))).toHaveLength(1);

    // a marker-free parseable outcome resets the latch ⇒ the next failure notifies again
    probeResult = ok(fp(7, 7, 1, 2));
    deliverResult = { kind: "empty" };
    await h.fireTick();
    probeResult = { kind: "error", reason: "EACCES" };
    deliverResult = { kind: "empty", bus: { error: true } };
    await h.fireTick();
    expect(ctx.notices.filter((n) => n.includes("message bus probe failed"))).toHaveLength(2);
  });

  test("A12: a failure-marked timer spawn notifies once per streak with the tick-failed voice", async () => {
    deliverResult = { kind: "empty", bus: { error: true } };
    const h = await loadBusAdapter({ probe, deliver });
    const ctx = busCtx(dir);
    await h.start(ctx);

    await h.fireTick();
    await h.fireTick();
    const failed = ctx.notices.filter((n) => n.includes("message delivery tick failed"));
    expect(failed).toHaveLength(1);
  });

  // -----------------------------------------------------------------------
  // CR-S5 — the timer spawn's timeout is 30 s; the seams keep 5 s
  // -----------------------------------------------------------------------

  test("the timer path spawns with the 30s budget; the seam path keeps 5s", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    await h.fireTick();
    expect(deliverCalls[0]!.timeoutMs).toBe(30_000);

    probeResult = ok(fp(9, 9, 1, 2)); // a send moved MAX: the seam's probe says spawn
    deliverCalls.length = 0;
    await h.on.get("before_agent_start")!({}, busCtx(dir));
    expect(deliverCalls[0]!.timeoutMs).toBe(5_000);
  });

  // -----------------------------------------------------------------------
  // the seam decorator (C1's CR-N4a: the seams share every rule; C7: on under off)
  // -----------------------------------------------------------------------

  test("the seam decorator spawns on uncertainty and skips only on the sound silence", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    deliverResult = { kind: "empty" };

    // first seam: watermark null ⇒ spawn (and advance to fp(7,7) on the clean outcome)
    await h.on.get("before_agent_start")!({}, busCtx(dir));
    expect(deliverCalls).toHaveLength(1);

    // second seam, identical probe: the txn would return nothing ⇒ silent skip
    await h.on.get("before_agent_start")!({}, busCtx(dir));
    expect(deliverCalls).toHaveLength(1);

    // a send moves MAX ⇒ the next seam spawns again
    probeResult = ok(fp(8, 8, 1, 2));
    await h.on.get("context")!({ messages: [] }, busCtx(dir));
    expect(deliverCalls).toHaveLength(2);
  });

  test("the seam decorator still gates under wake=off (C7) and fails open on probe errors", async () => {
    process.env.AI_BADGER_PI_BUS_WAKE = "off";
    const h = await loadBusAdapter({ probe, deliver });
    await h.start(busCtx(dir));
    deliverResult = { kind: "empty" };

    await h.on.get("before_agent_start")!({}, busCtx(dir));
    expect(deliverCalls).toHaveLength(1);
    await h.on.get("before_agent_start")!({}, busCtx(dir));
    expect(deliverCalls).toHaveLength(1); // gated under off too

    probeResult = { kind: "error", reason: "EACCES" };
    await h.on.get("before_agent_start")!({}, busCtx(dir));
    expect(deliverCalls).toHaveLength(2); // fail-open ⇒ today's behavior
  });

  test("PI_DELIVERY_EVENT_MAP gains no session_start entry — session_start is not a delivery event", async () => {
    const h = await loadBusAdapter({ probe, deliver });
    // session_start exists as a subscription (it arms the timer), but the router's event
    // map is pinned by tests/test_pi_hook_arm_coverage_contract.py from the bridge source;
    // here we pin the observable: session_start spawns nothing.
    deliverCalls.length = 0;
    await h.start(busCtx(dir));
    expect(deliverCalls).toHaveLength(0);
    expect(h.on.has("session_start")).toBe(true);
  });
});
