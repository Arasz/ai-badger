# Implementation review — aib-pi-message-bus-push-delivery (architecture lens)

**Date:** 2026-09-01 · **Reviewer:** architect persona (authored the structure lane; judged the result as a whole system)
**Target:** worktree `.ai-badger/worktrees/aib-pi-message-bus-push-delivery`, branch `task/aib-pi-message-bus-push-delivery` (13 commits ahead of main; 89 files, +7750/−656)
**Method:** every ADR-0026 decision, residual and checkable open question verified against code at file:line; md5 across the full vendored set; three-way pbi ↔ ai-badger ↔ user-scope adapter equality; layer purity by import audit; the whole 89-file diff classified against plan rev 2's P0–P4 ownership lists. Read-only review.

## Verdict: REQUEST-CHANGES

One BLOCKER: ADR-0026 as shipped claims a shipped mitigation (`nextTurn` compensation retry) that does not exist in the code. The architecture itself is sound — layering is clean, ADR-0022/0024/0025 all hold, byte-equality is real, and the changelog/SKILL contract are accurate with two scoping caveats. But this framework's own rule was stated in the brief: ADRs are never edited after acceptance, so an ADR that misdescribes its implementation must be caught now.

---

## BLOCKER

### B1 — ADR-0026 claims a `nextTurn` compensation retry that was never shipped

**ADR text:** `docs/adr/0026-pi-bus-delivery-pushes-with-an-in-adapter-poll.md:143-144` — "Mitigated by the stale-ctx generation guard and a `nextTurn` compensation retry; the residual window is sub-millisecond on a live ctx." Present tense, stated as the shipped state of the consume-then-lose residual.

**Code truth:**
- The stale-ctx generation guard half is real: `features/pi/adjustments/adapter/index.ts:478-530` (post-await `busSession !== session || busGeneration !== session.gen` re-checks) and `index.ts:532-543` (`disarmBus` bumps the generation).
- The compensation retry half does not exist. `grep -rni "nextturn|next_turn"` across all `.ts`/`.py` hits **only docs** — zero occurrences in `features/pi/**` or any test. On a non-stale `sendMessage` throw the adapter notifies once and moves on: `index.ts:519-524` (`notifyLatched(session, ... message wake failed ...)` — no retry, no `deliverAs:"nextTurn"`). The watermark has already advanced by then (`spawnAndSettle`, `index.ts:447-457`), and the store cursor advanced inside the txn, so that mail is silently gone except for one notice line.
- The retry was explicitly designed and expected: `docs/work/plan-proposals/2026-09-01-api-engineer.md:166` — "(b) on a non-stale throw … one compensation retry with `deliverAs:"nextTurn"` (no turn, rides the next prompt) … Documented as accepted in the ADR." Plan rev 2's C3 folded the *residual* into the ADR but never folded the mitigation *out*; the ADR text retained the proposal's mitigation list verbatim.

**Why BLOCKER and not SHOULD:** the ADR is marked Accepted (0.159.0) and this framework's rule is that ADRs are never edited after acceptance. A mitigation that exists only in the document is worse than no mitigation: it converts a named residual into an unowned one while claiming coverage.

**Resolution paths (either clears the blocker):**
1. Ship the retry — it is small and the content is in hand: in the `busTick` catch (`index.ts:519-524`), on a non-stale throw, re-send the already-consumed `outcome.content` once with `{deliverAs:"nextTurn", triggerTurn:false}`; keep the stale-ctx silent drop. Pin it with a test (see N4).
2. Or correct the ADR sentence *before* acceptance (e.g. "Mitigated only by the stale-ctx generation guard; the compensation retry proposed in the api-engineer lane was not shipped — the residual is the full consume-then-lose window on a failed wake") and re-accept. Post-merge edits are not an option under the framework's own ADR rule.

---

## SHOULD

### S1 — The pbi canonical claims are true only on unmerged branches; pbi main can clobber the shipped adapter

ADR-0026 Decision 10 (`0026-…md:165-166`) and the changelog (`docs/changelog/0.159.0-pi-bus-push-delivery.md:46-49`, "canonical adapter healed back into byte-equality … with the two new adapter files in the exact set") verified:

- **True** on pbi branch `task/aib-pi-message-bus-push-delivery-p3` (728db83): `ADAPTER_FILES` = `{index.ts, hook-bridge.ts, bus-prefilter.ts, bus-store.ts, package.json, .ai-badger-capability-resources-discover}` (`publish.ts:59-66`), and all five adapter files **byte-equal three-way** against the ai-badger worktree and the live user scope `~/.pi/agent/extensions/ai-badger/`.
- **False at pbi main**: neither pbi branch is merged (`git merge-base --is-ancestor HEAD origin/main` fails on the P3 branch), and pbi's primary worktree sits on `task/…-heal`, whose `publish.ts:59-64` exact-set still lacks both bus files and whose adapter tree has no bus files at all (it is the 0.157.2 reverse-sync, 7301ac1).

Consequence: anyone running `bun publish.ts` from pbi main republishes the bus-less adapter over user scope, silently removing the push delivery this release advertises. The changelog sentence also compresses two different events (the 0.157.2 reverse-sync heal and the P3 forward mirror) into one "healed back into byte-equality" claim.

**Ask:** merge the pbi branches (heal first, then the P3 mirror) before release publication — or qualify the changelog/ADR claim as branch-scoped. The ADR is the harder of the two to amend; merging is the cheap path.

### S2 — The merge gate's own evidence for P3 and P5 is not in the shipped record

`docs/work/2026-09-01-pi-bus-push-red-witnesses.md` (211 lines) holds only the P1/P2 gates: B1–B3 red-first, then B6/B7/B4-B5/B8 with pasted RED output and applied-and-reverted mutations — well done as far as it goes. But plan rev 2's merge gate requires "Every new gate RED-first with pasted output" in that file, and grep across `docs/work/` finds **no** P3 bun red-first outputs and **no** record of live probes L1–L5 (or L6's conditional outcome): no `idle-wake`, no `L3′`, no probe transcripts anywhere. The ADR honestly frames TUI wake as inferred (open question 1) — that is not the issue — but L1 (idle-wake rpc) was a *merge gate*, and nothing shipped witnesses push delivery ever working end-to-end. The changelog's headline claim currently rests on unit-level pins alone.

**Ask:** append the P3 bun red-first outputs and the L1–L5 probe transcripts (or an explicit record that they did not run, with reason) to the witness file before release.

---

## Verified true (the truth-check ledger)

Every claim below was checked against code at file:line and holds.

**ADR-0026 decisions vs code:**
- **D1 prefilter** — default 2 s / floor 0.5 (`bus-prefilter.ts:47-73`); one `{MAX(id), COUNT(*)}` query + stat identity (`bus-store.ts:127-135, 55-70`); skip iff exact MAX **and** COUNT **and** identity **and** <60 s freshness (`bus-prefilter.ts:134, 142-190`); ENOENT sound skip (`bus-prefilter.ts:151-158`, `bus-store.ts:205-207`); every error ⇒ spawn; advance only to the tick-time capture on a marker-free parseable outcome (`index.ts:447-457`); first tick always spawns (watermark null). Arming exactly as stated: `session_start`, wake≠off, tui/rpc, script-exists (`index.ts:628-660`).
- **D2 txn ownership** — TS opens `readOnly` (pinned by the A11 write-negative, `bus-store.test.ts:296-364`), reads only the two aggregates (`bus-store.ts:127-135`), never classifies, never advances a cursor. Summary is computed inside the txn from the delivered rows only (`engine/badger_store.py:1960-1976`), post-gate/post-cap/post-R2; merged after `build_response` (`message_delivery_hook.py:135-141`).
- **D3/C2b marker** — exact shape `{"hookSpecificOutput": {"aiBadgerBus": {"error": true}}}`, exit 0 (`message_delivery_hook.py:176, 262-277`); clean-empty stays exactly `{}` (pinned `tests/test_message_delivery_hook.py:693`).
- **D4 wake matrix** — all cells match `bus-prefilter.ts:216-244`: idle+addressed ⇒ followUp+triggerTurn; idle+broadcast-only under `addressed` ⇒ steer, no wake; streaming ⇒ steer (addressed) / followUp-no-wake (broadcast under `all`); compacting defers the tick (`index.ts:484`); `off` never arms while seams stay gated (C7, `index.ts:656` + `index.ts:465-476`); `ctx.isIdle()` authority with flags as hints (`index.ts:427-433`); compacting flag timestamped, expiring, cleared by compact/compact-failed/agent_start (`index.ts:668-685`, `bus-prefilter.ts:262-270`).
- **D5 seams prefilter-gated** — same rules shared (`index.ts:465-476`); 30 s timer budget / 5 s seam budget (`index.ts:61, 68`); SessionEnd cursor cleanup deliberately ungated with the reason in code (`index.ts:615-621`).
- **D7 send validation** — depth-4 walk, pruned noise trees, no symlink descent (`send_message.py:126-176`); self-project + `AI_BADGER_PROJECT_ID` legs (`send_message.py:178-189`); refusal lists found ids, no bypass flag (`send_message.py:191-198`); dual-flag skip claim in SKILL.md is true — the store drops `target_project` at write when a session targets (`engine/badger_store.py:1867-1868`).
- **D8 hook-error diagnosability** — sanitized exception message, payload-derived candidates redacted (`message_delivery_hook.py:180-247`); fail-open unchanged.
- **D9 wrap guard** — strict `>`, cursor-less *for that read*, gate+cap+leg-scoped landing (`engine/badger_store.py:1922-1933`); real sqlite_sequence-reset test plus the caught-up boundary test (`tests/test_message_bus_store.py:1131-1180`).
- **Residuals** — in-flight-tick-across-shutdown, same-inode restore, no-rate-limit-on-`all`, schema coupling (A11 contract test runs the *shipped probe* against a Python-created store DB, `bus-store.test.ts:296-364`), bun-degrades-to-unconditional-ticks (probe error ⇒ spawn, notice-latched): all honestly described. **Except the mitigation claim in B1.**
- **Changelog specifics** — the 5 s/5 s busy-timeout race claim is real: store `busy_timeout = 5000` (`engine/badger_store.py:2153`).

**ADR-0022/0024/0025 consistency:**
- **0022** — no per-hook manifest entries anywhere in the diff (manifest changes are hash/version/frameworkCommit refreshes only); arming lives solely in the adapter (`index.ts:628-660`); `hooks.json` untouched.
- **0024** — the store remains the single exactly-once owner; **all 33 `badger_store.py` copies md5-identical** (`64f12c5e…`), all 5 `message_delivery_hook.py` copies identical, all 3 `send_message.py` copies identical.
- **0025** — `resolve_project_id` untouched (0 diff lines); the new validation composes on top of the resolver without altering it (`send_message.py:178-189`); the delivery hook's cwd resolution unchanged (`message_delivery_hook.py:83-97`).

**SKILL.md env contract** (`features/common/skills/send-message/SKILL.md:105-125`) — matches code exactly: knob names, `off|addressed|all` with `addressed` default, default 2 / floor 0.5, invalid ⇒ default + one-time notice, read at arm time, tui/rpc only, print/json on seams, `off` ⇒ seams carry, fail-open. Docs tell the truth.

**Layering:**
- `bus-prefilter.ts` — **pure**: one `import type` from hook-bridge (`:25`), zero `node:*`, clock/env/stat all injected. ✓
- `hook-bridge.ts` — **zero imports at all**; purity preserved; the fourth parse shape (`aiBadgerBus`) folded into the single `parseDeliveryStdout`, no second parser. ✓
- `bus-store.ts` — the only DB/stat I/O in the bus machinery; every failure is a value; ENOENT is data. ✓
- `index.ts` — composition root; all new bus I/O arrives via the `BusDeps` port (`index.ts:103-121`), bun suites inject fakes. The gate/delivery spawn engine remaining inline is the pre-existing 0.156 shape, not a regression of this task. ✓

**Diff shape (89 files vs plan rev 2 ownership):** every file maps to a declared owner — P1, P2 (the four ripple test files amended inside the named C2 commits 73c81ef6/f8d0736f, per QA-3's one-named-commit rule), P3, P4 (VERSION, plugin.json, marketplace.json, index.json, config.json = the version literals), self-scaffold copies + manifest hash refresh, version-only agent-file refreshes (0 non-version lines in each of CLAUDE.md/HERMES.md/.hermes.md/copilot-instructions.md/.ai-badger agent files), and the docs/work record set. **Nothing outside declared ownership.**

---

## NOTE

- **N1 — session-id authority sentence over-scoped.** ADR-0026 Context (`:72-73`): "the session id authority is `ctx.sessionManager.getSessionId()`, never `PI_SESSION_ID`". True for the *push path* (`bus-prefilter.ts:96-107`, plan ruling C6), but the seam deliveries still carry the documented 0.156 `PI_SESSION_ID` fallback (`hook-bridge.ts` `resolveSessionId`, used at `index.ts:563-565, 596-598`). A future reader could "fix" the fallback and break the documented seam contract; the ADR sentence wanted the words "push path".
- **N2 — README Covers row compresses the skip rule.** `docs/adr/README.md:40` summarizes "skip only on exact fingerprint equality", omitting the 60 s staleness and file-identity halves (`bus-prefilter.ts:134, 176-180`). Summary-grade compression; the ADR body is exact.
- **N3 — dead cache lines in the one file that must not accrete.** `bus-store.ts:149` re-assigns `cachedSqlite` after `loadSqlite()` already cached it; `bus-store.ts:110`'s `?? cachedSqlite` is unreachable (`loadSqlite` returns `null` or the ctor, never `undefined`). Harmless; tidy while the file is young.
- **N4 — the wake-throw path has no owning test.** Tests pin the stale-ctx throw (A6, `adapter-bus.test.ts:272-280`) and routing (A8), but nothing covers a generic non-stale `sendMessage` throw (notice + advanced watermark, no retry). Whatever B1's resolution, its test belongs here.
- **N5 — root `skills/send-message/SKILL.md` not updated, by design.** It is the pointer-wrapper variant (skew vs `features/common` pre-exists on main); the full content with the new sections landed in `SKILL.full.md` (byte-equal to the canonical and the self-scaffold copy). Consistent with the wrapper convention used by mcp-index/prompt-markers et al.

---

## What clears the verdict

1. **B1**: ship the `nextTurn` compensation retry (≈6 lines in `busTick`'s catch + one test), or correct the ADR sentence and re-accept before merge. Either is a small, reviewable delta.
2. **S1**: merge pbi heal → P3-mirror, or qualify the changelog/ADR canonical-flow claims.
3. **S2**: paste P3 red-first outputs and L1–L5 probe records into the witness file.

The structure lane's core bets held: the pure-decision/I-O-port split survived contact with the full implementation, the store's exactly-once ownership is intact and provably byte-uniform, and the wake matrix in the ADR is the wake matrix in the code. The one place the docs outran the code is B1 — which is precisely what this review existed to catch.
