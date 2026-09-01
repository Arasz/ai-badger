/**
 * The bus prefilter's pure decision core (plan aib-pi-message-bus-push-delivery, package P3;
 * rulings C1 as amended, C3/C4, C7, C10, C11). Every function here is pure — no `node:*`
 * imports, no I/O — so the whole tick state machine is testable without a database, a
 * stat call, or a python spawn. The I/O port it sits on lives in bus-store.ts; the wiring
 * that feeds it lives in adapter-bus.test.ts.
 *
 * Gate naming follows the qa review's amended A-list (docs/work/plan-reviews/2026-09-01-qa.md):
 * A1 (wake env), A2 (poll env), A3 (global-watermark property, replacing the deleted
 * predicate mirror), A7 (manager-id authority), A8 (wake routing from the P2 summary),
 * A9's pure half (watermark-advance rule), A10's pure half (compaction expiry).
 */

import { describe, expect, test } from "bun:test";
import {
  COMPACT_FLAG_TTL_MS,
  MAX_SKIP_STALENESS_MS,
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
} from "../adjustments/adapter/bus-prefilter.ts";
import { parseDeliveryStdout } from "../adjustments/adapter/hook-bridge.ts";
import type { DeliveryOutcome } from "../adjustments/adapter/hook-bridge.ts";

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

/** A fingerprint over the tick-time capture: MAX(id), COUNT(*) and the file identity. */
function fp(maxId: number, count: number, dev = 1, ino = 2): BusFingerprint {
  return { maxId, count, dev, ino };
}

function probeOk(f: BusFingerprint): BusProbe {
  return { kind: "ok", fingerprint: f };
}

function state(lastClean: BusFingerprint | null, lastSpawnAt: number | null): BusTickState {
  return { lastClean, lastSpawnAt };
}

const NOW = 1_000_000_000_000;

// ---------------------------------------------------------------------------
// A1 — AI_BADGER_PI_BUS_WAKE parses to the owner matrix
// ---------------------------------------------------------------------------

describe("A1: AI_BADGER_PI_BUS_WAKE env parsing", () => {
  test("unset defaults to addressed, silently", () => {
    expect(wakePolicyFromEnv({})).toEqual({ policy: "addressed" });
  });

  test("each owner value parses exactly", () => {
    expect(wakePolicyFromEnv({ AI_BADGER_PI_BUS_WAKE: "off" }).policy).toBe("off");
    expect(wakePolicyFromEnv({ AI_BADGER_PI_BUS_WAKE: "addressed" }).policy).toBe("addressed");
    expect(wakePolicyFromEnv({ AI_BADGER_PI_BUS_WAKE: "all" }).policy).toBe("all");
  });

  test("garbage degrades to the default with a warning naming the value", () => {
    const r = wakePolicyFromEnv({ AI_BADGER_PI_BUS_WAKE: "sometimes" });
    expect(r.policy).toBe("addressed");
    expect(r.warn).toContain("sometimes");
    expect(r.warn).toContain("AI_BADGER_PI_BUS_WAKE");
  });

  test("a blank value is unset-like: default, no warning noise", () => {
    expect(wakePolicyFromEnv({ AI_BADGER_PI_BUS_WAKE: "" })).toEqual({ policy: "addressed" });
  });
});

// ---------------------------------------------------------------------------
// A2 — AI_BADGER_PI_BUS_POLL_SECS parses with a sane floor
// ---------------------------------------------------------------------------

describe("A2: AI_BADGER_PI_BUS_POLL_SECS env parsing", () => {
  test("unset defaults to 2 seconds, silently", () => {
    expect(pollSecsFromEnv({})).toEqual({ secs: 2 });
  });

  test("a real non-default value is the one used (fixture realism)", () => {
    expect(pollSecsFromEnv({ AI_BADGER_PI_BUS_POLL_SECS: "5" }).secs).toBe(5);
    expect(pollSecsFromEnv({ AI_BADGER_PI_BUS_POLL_SECS: "0.75" }).secs).toBe(0.75);
  });

  test("non-numeric, zero and negative fall back to the default — never a hot loop", () => {
    for (const garbage of ["banana", "0", "-3", "Infinity", "NaN", "1e400"]) {
      const r = pollSecsFromEnv({ AI_BADGER_PI_BUS_POLL_SECS: garbage });
      expect(r.secs).toBe(2);
      expect(r.warn).toContain("AI_BADGER_PI_BUS_POLL_SECS");
    }
  });

  test("a positive value under the 0.5s floor is clamped to the floor, not defaulted", () => {
    const r = pollSecsFromEnv({ AI_BADGER_PI_BUS_POLL_SECS: "0.2" });
    expect(r.secs).toBe(0.5);
    expect(r.warn).toContain("AI_BADGER_PI_BUS_POLL_SECS");
  });
});

// ---------------------------------------------------------------------------
// A3 — watermark soundness: false negatives are the only intolerable failure.
// The amended property (qa Q1): the TS side never reads rows, cursors or
// addressing — the entire decision is the {maxId, count, dev, ino} fingerprint
// against the last clean probe, plus ENOENT and fail-open-on-error.
// ---------------------------------------------------------------------------

describe("A3: global-watermark tick decision", () => {
  test("the first tick always spawns (watermark null)", () => {
    const d = decideTick(state(null, null), probeOk(fp(7, 7)), NOW);
    expect(d.action).toBe("spawn");
    if (d.action === "spawn") {
      expect(d.tickFingerprint).toEqual(fp(7, 7));
      expect(d.state.lastSpawnAt).toBe(NOW);
    }
  });

  test("exact MAX AND COUNT equality + identity unchanged + recent spawn ⇒ skip (the only skip)", () => {
    const d = decideTick(state(fp(7, 7, 1, 2), NOW - 1_000), probeOk(fp(7, 7, 1, 2)), NOW);
    expect(d.action).toBe("skip");
  });

  test("MAX equal but COUNT differs ⇒ spawn (a prune or any other row delta)", () => {
    const d = decideTick(state(fp(7, 7), NOW - 1_000), probeOk(fp(7, 9)), NOW);
    expect(d.action).toBe("spawn");
  });

  test("COUNT equal but identity changed ⇒ spawn (DB replaced on disk)", () => {
    const d = decideTick(state(fp(7, 7, 1, 2), NOW - 1_000), probeOk(fp(7, 7, 1, 3)), NOW);
    expect(d.action).toBe("spawn");
  });

  test("any insert moves MAX ⇒ spawn, whichever class wrote it (C1's over-approximation)", () => {
    // The watermark cannot see addressing — a 1:1 for another session, a project row
    // and a machine broadcast are the same {maxId+1, count+1} shape. Spawning on all
    // of them is correct; a "smart" skip here is the mutation this case kills.
    for (const [maxId, count] of [[8, 8], [8, 9], [12, 30]] as const) {
      const d = decideTick(state(fp(7, 7, 1, 2), NOW - 1_000), probeOk(fp(maxId, count, 1, 2)), NOW);
      expect(d.action).toBe("spawn");
    }
  });

  test("MAX < watermark ⇒ spawn — the skip test is exact equality, never ≤ (restored/pruned DB)", () => {
    // count EQUAL, MAX lower: flips the maxId comparison alone, so a ≤ mutant dies here
    const d = decideTick(state(fp(9, 7), NOW - 1_000), probeOk(fp(7, 7)), NOW);
    expect(d.action).toBe("spawn");
    const alsoSpawn = decideTick(state(fp(9, 9), NOW - 1_000), probeOk(fp(7, 7)), NOW);
    expect(alsoSpawn.action).toBe("spawn");
  });

  test("empty table: watermark 0 + identity unchanged + recent spawn ⇒ skip (sound: no rows, no mail)", () => {
    const d = decideTick(state(fp(0, 0, 1, 2), NOW - 1_000), probeOk(fp(0, 0, 1, 2)), NOW);
    expect(d.action).toBe("skip");
  });

  test("equality but the last spawn is older than the 60 s staleness bound ⇒ spawn (CR-M2)", () => {
    const d = decideTick(
      state(fp(7, 7, 1, 2), NOW - MAX_SKIP_STALENESS_MS - 1),
      probeOk(fp(7, 7, 1, 2)),
      NOW,
    );
    expect(d.action).toBe("spawn");
  });

  test("equality at exactly the staleness bound ⇒ spawn (the bound is exclusive)", () => {
    const d = decideTick(
      state(fp(7, 7, 1, 2), NOW - MAX_SKIP_STALENESS_MS),
      probeOk(fp(7, 7, 1, 2)),
      NOW,
    );
    expect(d.action).toBe("spawn");
  });

  test("equality with no recorded spawn ⇒ spawn (freshness unverifiable)", () => {
    const d = decideTick(state(fp(7, 7, 1, 2), null), probeOk(fp(7, 7, 1, 2)), NOW);
    expect(d.action).toBe("spawn");
  });

  test("a probe error of any kind ⇒ spawn and the last clean probe survives (fail-open, D31)", () => {
    const before = state(fp(7, 7, 1, 2), NOW - 1_000);
    const d = decideTick(before, { kind: "error", reason: "no such table: messages" }, NOW);
    expect(d.action).toBe("spawn");
    if (d.action === "spawn") {
      // Nothing was captured — an error spawn must not be able to advance the watermark.
      expect(d.tickFingerprint).toBeUndefined();
      expect(d.state.lastClean).toEqual(before.lastClean);
      // The spawn itself still counts for the staleness clock (any outcome, CR-M2).
      expect(d.state.lastSpawnAt).toBe(NOW);
    }
  });

  test("stat errors surface through the same fail-open error probe ⇒ spawn", () => {
    const d = decideTick(state(fp(7, 7), NOW - 1_000), { kind: "error", reason: "EACCES" }, NOW);
    expect(d.action).toBe("spawn");
  });

  test("ENOENT ⇒ skip (a read-only probe must not create the user DB, QA-9)…", () => {
    const d = decideTick(state(fp(7, 7, 1, 2), NOW - 1_000), { kind: "missing" }, NOW);
    expect(d.action).toBe("skip");
  });

  test("…and the ENOENT skip DISCARDS the fingerprint: the first tick after the file reappears spawns", () => {
    const first = decideTick(state(fp(7, 7, 1, 2), NOW - 1_000), { kind: "missing" }, NOW);
    expect(first.action).toBe("skip");
    expect(first.state.lastClean).toBeNull();
    const second = decideTick(first.state, probeOk(fp(7, 7, 1, 2)), NOW + 2_000);
    expect(second.action).toBe("spawn");
  });

  test("the decision is total: no input shape throws out of the tick", () => {
    const probes: BusProbe[] = [
      probeOk(fp(0, 0)),
      probeOk(fp(Number.MAX_SAFE_INTEGER, 0)),
      { kind: "missing" },
      { kind: "error", reason: "" },
    ];
    const states: BusTickState[] = [
      state(null, null),
      state(null, NOW),
      state(fp(0, 0), null),
      state(fp(3, 3, 9, 9), 0),
    ];
    for (const s of states) {
      for (const p of probes) {
        expect(() => decideTick(s, p, NOW)).not.toThrow();
      }
    }
  });
});

// ---------------------------------------------------------------------------
// A7 — the push path's session identity is the session manager's, with no env fallback
// ---------------------------------------------------------------------------

describe("A7: push-path session identity", () => {
  test("ctx.sessionManager.getSessionId() is the authority", () => {
    expect(managerSessionId({ sessionManager: { getSessionId: () => "sm-1" } })).toBe("sm-1");
  });

  test("no PI_SESSION_ID fallback on the push path (Lane A F9: the env var can be another session's id)", () => {
    const env = { PI_SESSION_ID: "env-id" };
    expect(managerSessionId({}, env)).toBe("");
    expect(managerSessionId({ sessionManager: {} }, env)).toBe("");
    expect(
      managerSessionId(
        { sessionManager: { getSessionId: () => {
          throw new Error("old build");
        } } },
        env,
      ),
    ).toBe("");
  });

  test("an empty manager id stays empty — the timer skips silently on it", () => {
    expect(managerSessionId({ sessionManager: { getSessionId: () => "" } }, {})).toBe("");
  });
});

// ---------------------------------------------------------------------------
// A8 — wake routing from the P2 summary (C3, C4, C10; the qa-amended matrix)
// ---------------------------------------------------------------------------

describe("A8: wake routing from the delivery summary", () => {
  test("idle + addressed mail ⇒ followUp with triggerTurn (the measured idle-wake shape)", () => {
    expect(wakeRoute({ addressed: 1, broadcast: 0 }, { idle: true }, "addressed")).toEqual({
      deliverAs: "followUp",
      triggerTurn: true,
    });
    expect(wakeRoute({ addressed: 2, broadcast: 1 }, { idle: true }, "all")).toEqual({
      deliverAs: "followUp",
      triggerTurn: true,
    });
  });

  test("idle + broadcast-only under addressed ⇒ consume + inject WITHOUT waking (C3)", () => {
    expect(wakeRoute({ addressed: 0, broadcast: 3 }, { idle: true }, "addressed")).toEqual({
      deliverAs: "steer",
      triggerTurn: false,
    });
  });

  test("idle + broadcast-only under all ⇒ the same call as addressed mail", () => {
    expect(wakeRoute({ addressed: 0, broadcast: 3 }, { idle: true }, "all")).toEqual({
      deliverAs: "followUp",
      triggerTurn: true,
    });
  });

  test("streaming + addressed ⇒ steer, never a second triggerTurn", () => {
    expect(wakeRoute({ addressed: 1, broadcast: 0 }, { idle: false }, "addressed")).toEqual({
      deliverAs: "steer",
      triggerTurn: false,
    });
  });

  test("streaming + broadcast-only under addressed ⇒ steer without a wake (C4's ruled cell)", () => {
    expect(wakeRoute({ addressed: 0, broadcast: 1 }, { idle: false }, "addressed")).toEqual({
      deliverAs: "steer",
      triggerTurn: false,
    });
  });

  test("streaming + broadcast-only under all ⇒ followUp without a wake", () => {
    expect(wakeRoute({ addressed: 0, broadcast: 1 }, { idle: false }, "all")).toEqual({
      deliverAs: "followUp",
      triggerTurn: false,
    });
  });

  test("a zero-count summary next to content still injects (steer) — mail is never dropped", () => {
    expect(wakeRoute({ addressed: 0, broadcast: 0 }, { idle: true }, "addressed")).toEqual({
      deliverAs: "steer",
      triggerTurn: false,
    });
  });

  test("C10: a missing summary (old hook copies) is treated as addressed", () => {
    expect(mailSummary(undefined)).toEqual({ addressed: 1, broadcast: 0 });
    expect(mailSummary({ addressed: 2, broadcast: 1 })).toEqual({ addressed: 2, broadcast: 1 });
    expect(mailSummary({ error: true })).toEqual({ addressed: 0, broadcast: 0 });
  });
});

// ---------------------------------------------------------------------------
// A9 (pure half) — the watermark advances only on parseable outcomes that do not
// carry the failure marker (C1 as amended by CR-M1/CR-M3).
// ---------------------------------------------------------------------------

describe("A9: watermark-advance rule over parsed delivery outcomes", () => {
  test("a clean empty response advances", () => {
    expect(advanceAllowed(parseDeliveryStdout("{}"))).toBe(true);
  });

  test("a mail-bearing response with a summary advances (tick-time capture makes it sound, CR-M3)", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "UserPromptSubmit",
          additionalContext: "mail",
          aiBadgerBus: { addressed: 2, broadcast: 1 },
        },
      }),
    );
    expect(advanceAllowed(out)).toBe(true);
  });

  test("a mail-bearing response WITHOUT a summary (old hook copy) advances", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({ hookSpecificOutput: { hookEventName: "UserPromptSubmit", additionalContext: "mail" } }),
    );
    expect(out.kind).toBe("context");
    expect(advanceAllowed(out)).toBe(true);
  });

  test("the failure marker does not advance (CR-M1: the cursor may not have moved)", () => {
    const out = parseDeliveryStdout(
      JSON.stringify({ hookSpecificOutput: { aiBadgerBus: { error: true } } }),
    );
    expect(out.kind).toBe("empty");
    expect(advanceAllowed(out)).toBe(false);
  });

  test("a spawn error or timeout (an error outcome) does not advance", () => {
    const error: DeliveryOutcome = { kind: "error", reason: "killed after 30000ms" };
    expect(advanceAllowed(error)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// A10 (pure half) — the timestamped compaction flag expires after 10 minutes (C11)
// ---------------------------------------------------------------------------

describe("A10: compaction flag expiry", () => {
  test("no flag ⇒ not compacting", () => {
    expect(compactingActive(NOW, null)).toBe(false);
  });

  test("a fresh timestamp ⇒ compacting (the tick defers)", () => {
    expect(compactingActive(NOW, NOW - 1_000)).toBe(true);
  });

  test("a timestamp older than the 10-minute TTL ⇒ expired (the tick proceeds again)", () => {
    expect(compactingActive(NOW, NOW - COMPACT_FLAG_TTL_MS - 1)).toBe(false);
    expect(COMPACT_FLAG_TTL_MS).toBe(10 * 60_000);
  });
});
