# ADR-0022 — pi arms hooks dynamically; the hooks manifest stays a wiring truth for claude/hermes/copilot

**Date:** 2026-08-29
**Status:** Accepted (2026-08-29, 0.146.0)
**Author:** Rafał Araszkiewicz (Arasz) with ox-alpha (implementation lane)
**Extends:** ADR-0017 (memory-first gate), ADR-0015 (mechanisms, not prose)
**Scope:** `features/common/hooks/hooks-manifest.json`, `features/pi/adjustments/adapter/`,
`tests/test_pi_hook_arm_coverage_contract.py`

## Context

The hooks manifest maps every framework hook to the agents that arm it, per hook:
`agents.{claude,hermes,copilot}` entries name the event, the script and the wiring type, and
the scaffolder reads exactly those entries to install each arm (hook_wiring for claude,
adjust_hooks for copilot, the Hermes plugin module for hermes). pi arrived with a different
arming model: its adapter extension registers TWO pi events (`tool_call`, `tool_result`) and
at runtime reads the same generated `.ai-badger/hooks/hooks.json` claude's wiring produces,
dispatching each entry's command through the hook bridge. One registration point arms every
hook — present and future — with no per-hook scaffolding at all.

That raised the queued decision: should the manifest gain per-hook `pi` entries?

## Decision

**No.** The manifest stays a per-hook wiring truth for the hosts that wire per hook. pi's
arming contract is recorded once, at the whole-agent level, and is:

> Everything claude's generated hooks.json arms, the pi adapter arms dynamically.

Three consequences, all deliberate:

1. **No `pi` keys in `agents`** — adding them would be documentation wearing a wiring
   costume. The scaffolder must never act on a per-hook pi entry (there is nothing to
   install), and a future per-hook pi key would tempt the adapter back toward static
   registration, re-creating the every-new-hook-needs-pi-changes failure mode the dynamic
   reader exists to avoid.
2. **The contract is enforced by test, not by prose**:
   `tests/test_pi_hook_arm_coverage_contract.py` pins that the adapter subscribes both
   families (`tool_call` and `tool_result`) and recognizes the MCP-suffix spelling rule —
   the same coverage the manifest grants claude, checked at the only level pi has.
3. **The manifest's `agents` object stays closed** to claude/hermes/copilot wiring types.
   If pi ever grows a per-hook arm worth wiring (an event the adapter cannot observe), that
   is a new decision, not a silent manifest extension.

## Consequences

- A new hook wired for claude is automatically armed for pi with zero manifest edits — the
  failure mode shifts from "forgot to add pi" to "the contract test catches a bridge
  regression", which is where we want it.
- The manifest can no longer answer "which hooks does pi arm?" by enumeration; the answer
  lives in this ADR and the contract test. Accepted: the manifest was never read by the pi
  path anyway, so nothing that consumed it loses accuracy.
- The pi adapter is the single point of failure for pi hooking; its unit coverage (mirrored
  in the pi-badger-integration repo, the canonical source) is the compensating control.
