/**
 * The message-bus push prefilter's PURE decision core (plan aib-pi-message-bus-push-delivery,
 * package P3; rulings C1 as amended by CR-M1/CR-M2/CR-M3, C3/C4, C7, C10, C11).
 *
 * Purity contract (the hook-bridge rule): no `node:*` imports, no I/O, nothing here can
 * touch a file, a database, or a process. Everything a decision needs arrives as injected
 * state — the tick fingerprint comes from bus-store.ts's probe, the clock comes in as a
 * `now` number, the wake summary comes from the parsed delivery stdout. That is what makes
 * the whole state machine unit-testable without a database, a stat call, or a python spawn.
 *
 * The invariants this module owns:
 *  - The tick SKIP is the narrowest gate in the adapter: exact MAX AND COUNT equality,
 *    file identity unchanged, a spawn younger than the 60 s staleness bound (CR-M2), on a
 *    probe that actually read the DB. ENOENT is the one other sound skip (QA-9: a read-only
 *    probe must not create the user DB). Every error ⇒ spawn (fail-open, D31).
 *  - The watermark advances only to the TICK-TIME fingerprint captured before the spawn
 *    (CR-M3 — never re-read post-spawn), only on a parseable outcome that does not carry
 *    the failure marker (CR-M1 — a fail-open `{}` from a broken store must read as "unknown",
 *    not "empty").
 *  - Wake routing consults the P2 summary (`aiBadgerBus`) per the owner matrix; a missing
 *    summary on a mail-bearing response is treated as addressed (C10 — old hook copies on
 *    un-refreshed projects wake on day one).
 */

import type { DeliveryBus, DeliveryOutcome } from "./hook-bridge.ts";

// ---------------------------------------------------------------------------
// env parsing (read once per session at arm time — the awayFromEnv discipline)
// ---------------------------------------------------------------------------

/** `AI_BADGER_PI_BUS_WAKE`: `off` never arms the timer, `addressed` (default) wakes on
 * 1:1/project mail, `all` additionally wakes on broadcasts. */
export type WakePolicy = "off" | "addressed" | "all";

export function wakePolicyFromEnv(
  env: Record<string, string | undefined>,
): { policy: WakePolicy; warn?: string } {
  const raw = env.AI_BADGER_PI_BUS_WAKE;
  if (raw === undefined || raw.trim() === "") return { policy: "addressed" };
  if (raw === "off" || raw === "addressed" || raw === "all") return { policy: raw };
  return {
    policy: "addressed",
    warn: `ai-badger: AI_BADGER_PI_BUS_WAKE='${raw.slice(0, 40)}' is not off|addressed|all — using 'addressed'.`,
  };
}

/** The floor any poll interval clamps up to: a faster tick cannot make delivery more
 *  timely (the store txn is the bottleneck) and turns every error path into a spawn storm. */
export const MIN_POLL_SECS = 0.5;

export function pollSecsFromEnv(
  env: Record<string, string | undefined>,
): { secs: number; warn?: string } {
  const raw = env.AI_BADGER_PI_BUS_POLL_SECS;
  if (raw === undefined || raw.trim() === "") return { secs: 2 };
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return {
      secs: 2,
      warn: `ai-badger: AI_BADGER_PI_BUS_POLL_SECS='${raw.slice(0, 40)}' is not a usable number — using 2s.`,
    };
  }
  if (parsed < MIN_POLL_SECS) {
    return {
      secs: MIN_POLL_SECS,
      warn: `ai-badger: AI_BADGER_PI_BUS_POLL_SECS='${raw.slice(0, 40)}' is under the 0.5s floor — clamped.`,
    };
  }
  return { secs: parsed };
}

// ---------------------------------------------------------------------------
// session identity (C6: the push path keys on the session manager's id only)
// ---------------------------------------------------------------------------

/**
 * The session id the push path keys on: `ctx.sessionManager.getSessionId()` with NO env
 * fallback. `PI_SESSION_ID` is injected only into shell-tool subprocesses and can carry a
 * DIFFERENT session's id inside the pi process (measured, pi API evidence F9) — keying the
 * watermark or the wake on it would deliver another session's mail. An empty return means
 * nothing is addressable: the timer skips silently.
 */
export function managerSessionId(
  ctx: { sessionManager?: { getSessionId?: () => string } },
  _env?: Record<string, string | undefined>,
): string {
  try {
    const id = ctx.sessionManager?.getSessionId?.();
    if (typeof id === "string" && id) return id;
  } catch {
    // fall through — an older build's session manager shape must not take down the tick
  }
  return "";
}

// ---------------------------------------------------------------------------
// the tick decision (C1 as amended)
// ---------------------------------------------------------------------------

/** The tick-time capture: one read of MAX(id)+COUNT(*) plus the DB file's stat identity. */
export interface BusFingerprint {
  maxId: number;
  count: number;
  dev: number;
  ino: number;
}

/** Per-session in-memory tick state. Nothing is persisted: process death, /new, /resume,
 *  /fork and /clone all lose it, and a lost watermark only means "probe once more". */
export interface BusTickState {
  /** Fingerprint at the last watermark advance; null = unknown (the first tick spawns). */
  lastClean: BusFingerprint | null;
  /** Epoch ms of the last spawn (any outcome) — the freshness half of the skip rule. */
  lastSpawnAt: number | null;
}

/** What one probe of the user DB observed. Every failure is data, never a throw — the
 * caller cannot forget to handle an error shape that never reaches it. */
export type BusProbe =
  | { kind: "ok"; fingerprint: BusFingerprint }
  | { kind: "missing" }
  | { kind: "error"; reason: string };

/** A skipped tick names its reason — the only observable difference between the two
 * sound silences (unchanged DB vs absent DB file). */
export type TickDecision =
  | { action: "skip"; reason: "unchanged-since-last-clean-probe" | "db-file-missing"; state: BusTickState }
  | { action: "spawn"; tickFingerprint?: BusFingerprint; state: BusTickState };

/** Exact-equality skips strand deliverable mail when deliverability changes without a new
 *  row (D7 project resolution is re-evaluated per read — CR-M2). A spawn older than this
 *  bound forces one re-probe: ~1 spawn/min/session at worst, against the per-LLM-call
 *  spawns the prefilter removes. */
export const MAX_SKIP_STALENESS_MS = 60_000;

/**
 * The tick decision over injected state (C1 as amended). Errors never skip; the only skips
 * are the two sound silences. A spawn decision carries the tick-time fingerprint the caller
 * may advance to LATER — only once the delivery outcome comes back parseable without the
 * failure marker. Nothing here re-reads anything after the spawn (CR-M3).
 */
export function decideTick(
  state: BusTickState,
  probe: BusProbe,
  now: number,
  stalenessMs: number = MAX_SKIP_STALENESS_MS,
): TickDecision {
  // ENOENT: no file ⇒ no rows. Skipping is sound AND keeps a read-only probe from
  // creating the user DB as a side effect on bus-less machines (QA-9). The fingerprint
  // is discarded: when a sender recreates the file, the first tick spawns.
  if (probe.kind === "missing") {
    return {
      action: "skip",
      reason: "db-file-missing",
      state: { lastClean: null, lastSpawnAt: state.lastSpawnAt },
    };
  }
  // Every other failure (stat error, sqlite error, node:sqlite unavailable) ⇒ spawn.
  // Fail-open is the sound direction: never silent when unsure (D31). No fingerprint is
  // captured, so this spawn can never advance the watermark.
  if (probe.kind === "error") {
    return { action: "spawn", state: { lastClean: state.lastClean, lastSpawnAt: now } };
  }

  const f = probe.fingerprint;
  const clean = state.lastClean;
  const unchanged =
    clean !== null &&
    f.maxId === clean.maxId &&
    f.count === clean.count &&
    f.dev === clean.dev &&
    f.ino === clean.ino;
  const fresh = state.lastSpawnAt !== null && now - state.lastSpawnAt < stalenessMs;
  if (unchanged && fresh) {
    return { action: "skip", reason: "unchanged-since-last-clean-probe", state };
  }
  // Spawn, and carry the tick-time capture. lastClean stays as-is here: it advances only
  // after the outcome comes back marker-free parseable. Any row committed after this read
  // has id > f.maxId, so a mail-bearing advance can never strand it (CR-M3).
  return { action: "spawn", tickFingerprint: f, state: { lastClean: state.lastClean, lastSpawnAt: now } };
}

// ---------------------------------------------------------------------------
// the watermark-advance rule (C1 as amended by CR-M1 + CR-M3)
// ---------------------------------------------------------------------------

/** The hook's fail-open net (C2b): on an internal failure the response is parseable JSON
 *  carrying `aiBadgerBus: {error: true}` with exit 0 — indistinguishable from a genuine
 *  empty inbox unless this marker is checked. The marker (or a non-parseable stdout) means
 *  the cursor may not have moved: the watermark must stay stale so the next tick retries. */
export function carriesFailureMarker(outcome: DeliveryOutcome): boolean {
  if (outcome.kind === "error") return true;
  return outcome.bus !== undefined && "error" in outcome.bus;
}

/** The watermark may advance only on a parseable outcome without the failure marker —
 *  clean-empty `{}`, mail with a summary, and mail without one (old hook copies). The
 *  advance VALUE is always the tick-time fingerprint captured before the spawn (CR-M3). */
export function advanceAllowed(outcome: DeliveryOutcome): boolean {
  return !carriesFailureMarker(outcome);
}

// ---------------------------------------------------------------------------
// wake routing from the P2 summary (C3, C4, C10, C11)
// ---------------------------------------------------------------------------

/** The delivered-batch counts the Python txn merged into `hookSpecificOutput.aiBadgerBus`. */
export interface MailSummary {
  addressed: number;
  broadcast: number;
}

export interface WakeRouting {
  deliverAs: "steer" | "followUp";
  triggerTurn: boolean;
}

/**
 * The summary the wake routing acts on. A mail-bearing response with NO summary is an old
 * hook copy on an un-refreshed project (C10): treat as addressed — fail-open toward the
 * wake, which never loses mail and makes push work machine-wide on day one. A failure
 * marker never reaches routing (the outcome is not injected), but stays total: zero counts.
 */
export function mailSummary(bus: DeliveryBus | undefined): MailSummary {
  if (bus !== undefined && "addressed" in bus) return bus;
  if (bus !== undefined && "error" in bus) return { addressed: 0, broadcast: 0 };
  return { addressed: 1, broadcast: 0 };
}

/**
 * The wake matrix (C3 as ruled, C4's cell ruled by QA-4, C11's isIdle authority folded
 * into `session.idle` by the caller). `policy === "off"` never reaches here (the timer is
 * not armed), but the fallback keeps the function total and C3-consistent.
 *
 * | session \ mail            | addressed > 0                    | broadcast-only                    |
 * |---------------------------|----------------------------------|-----------------------------------|
 * | idle                      | followUp + triggerTurn           | addressed: steer (C3) · all: wake |
 * | streaming                 | steer, no triggerTurn            | addressed: steer (C4) · all: followUp, no wake |
 *
 * A zero-count summary next to content is contractually impossible; steering it injects
 * the mail without a wake rather than dropping it.
 */
export function wakeRoute(mail: MailSummary, session: { idle: boolean }, policy: WakePolicy): WakeRouting {
  if (mail.addressed > 0) {
    return session.idle
      ? { deliverAs: "followUp", triggerTurn: true }
      : { deliverAs: "steer", triggerTurn: false };
  }
  if (mail.broadcast > 0 && policy === "all") {
    return session.idle
      ? { deliverAs: "followUp", triggerTurn: true }
      : { deliverAs: "followUp", triggerTurn: false };
  }
  return { deliverAs: "steer", triggerTurn: false };
}

// ---------------------------------------------------------------------------
// the compaction flag's age half (C11: timestamped, expires, cleared by agent_start)
// ---------------------------------------------------------------------------

/** A stuck compacting flag must not defer ticks forever (CR-S3): the timestamp expires. */
export const COMPACT_FLAG_TTL_MS = 10 * 60_000;

/** True while a `session_before_compact` timestamp is still young enough to defer ticks.
 *  The clearing half (session_compact / session_compact_failed / agent_start) lives in the
 *  wiring; this is the passive expiry that bounds a missed clear. */
export function compactingActive(now: number, flagAt: number | null): boolean {
  return flagAt !== null && now - flagAt < COMPACT_FLAG_TTL_MS;
}
