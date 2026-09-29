# ADR-0033 — Config-gated level-only persona emission (`personaModelPins`)

**Date:** 2026-09-29
**Status:** Accepted
**Supersedes:** Nothing. Extends ADR-0027 (dual-key persona lanes) with a project opt-out
of its `model:` half.

## Context

ADR-0027 kept `model:` beside `level:` everywhere (grandfather) because Claude routes on the
bare lane at runtime. Practice found the pin is not just redundant — it is hazardous on hosts
that resolve a persona's model themselves: an explicit pin wins over `level:` (G-6 precedence)
but bypasses the `MODEL_ID_PATTERN` validation registry ids get, so a bare alias (`sonnet`,
`opus`) resolves credential-blind to whichever provider advertises it and kills the delegation
at spawn — observed as `No API key found`, with a doomed fallback retry on the session model.

Projects that hit this drop the pins by hand (ai-raccoon `e9519ff9`: "route by level only;
tier taste now lives in one place: `.ai-badger/model-groups.json`" — verified end to end,
spawn rejections gone). The catalog copied them right back: `scaffold_personas` delivered
persona sources verbatim, so every `den-refresh` re-added every dropped pin. The drop was
correct and unkeepable — churn by design.

## Decision

1. **`personaModelPins` (boolean, default `true`) is the emission switch.** `true` — or the
   key absent — keeps ADR-0027's dual-key emission unchanged. `false` strips the `model:`
   frontmatter entry as each persona lands in `.ai-badger/agents/` — the entry's own lines
   and nothing else; the other entries, the fence and the body are preserved exactly.
2. **The strip happens once, at the source-of-truth write.** `.ai-badger/agents/` is the
   file the pi and Claude deliveries read (`.pi/agents/`, `.claude/agents/`), so both
   inherit the pin-free shape with no second policy. The Copilot delivery renders
   `.github/agents/` from the catalog source instead and omits `model:` from its merged
   frontmatter by construction (`features/copilot/adjustments/adjust_agents.py`) — pin-free
   today; should that merge ever pass `model` through, the same strip belongs there.
3. **Nothing resolves differently.** The knob only decides what is written; precedence stays
   PKG-2's three clauses (explicit model > level > session). A pin-less persona resolves on
   its `level:` where the host supports that (the pi reader resolves against
   `.ai-badger/model-groups.json`) and inherits the session model where it does not (Claude
   Code subagents, whose `level:` is stripped at delivery by ADR-0027 G-2).

## Consequences

- The drop becomes keepable: `personaModelPins: false` is stable across `den-refresh`,
  re-scaffold and release bumps.
- On a host that cannot resolve `level:`, a pin-less persona runs on the session model — the
  same degrade ADR-0027 records for a lane-less persona. Projects choosing the knob accept
  that trade; it is why the default stays `true`.
- ADR-0027's catalog contract is untouched: the catalog still ships dual-key and its tests
  still sweep it. `tests/test_persona_model_pins.py` pins the knob both ways (provocation
  pair) plus the churn itself — a second scaffold must not resurrect a dropped pin.

## Alternatives considered

- **Re-drop the pins after every refresh.** Rejected: permanent churn, kept alive only by
  someone remembering — the status quo this ADR ends.
- **Keep the pins.** Rejected: they keep killing delegations at spawn on hosts that resolve
  a persona's model, and the surviving evidence says the pin adds nothing the registry lacks.
- **Drop `model:` from the catalog outright (flip ADR-0027).** Rejected for now: Claude
  routes on the bare lane at runtime, and projects that still want the lane keep the default.
  Worth revisiting once no supported host needs the bare lane.
