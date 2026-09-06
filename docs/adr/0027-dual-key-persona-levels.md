# ADR-0027 — Dual-key persona lanes: `level:` beside `model:`

**Date:** 2026-09-06
**Status:** Accepted
**Author:** PKG-3 lane (tiers/pkg3-lanes)
**Supersedes:** Nothing. Extends ADR-0015 (lever 1: the `model:` lane) without
revisiting its deny-vs-inject ruling.

## Context

ADR-0015 put a `model:` lane (opus/sonnet/…) in each persona's frontmatter so
a dispatch to a named persona gets the right Claude lane with nobody deciding
anything. PKG-1 (parallel lane, `tiers/pkg1-registry`) adds the other half of
the vocabulary: a `model-groups` registry mapping a routing intent
(`low`|`medium`|`high`) to ordered OpenRouter pins, with `resolve()` giving
explicit-model > level > inherit.

Two gaps remain, and both are vocabulary, not mechanism:

1. A persona today names only its Claude lane (`model: opus`). It states no
   routing intent, so nothing can resolve it against the registry, and the
   delegation map cannot show what derivation a persona needs — only what
   bare lane it happens to pin.
2. The gate's deny text still speaks bare lanes (`haiku`/`sonnet`/`opus`)
   with no notion of levels, so a reader it denies learns the old
   vocabulary at the exact moment the framework is moving to the new one.

The DUAL-KEY contract was ratified pre-dispatch for this lane: personas carry
`level:` (routing intent) **plus** the Claude-legible `model:` (bare lane).
Grandfather clause: legacy bare pins keep today's best-effort fallback; new
personas are banned from bare via a scaffold test (L1-A4).

Resolution precedence across the two keys is OWNED by PKG-2 (parallel lane,
skill prose). This ADR quotes PKG-2's canonical 3-clause sentence and never
restates it (M2):

> "An explicit model wins verbatim; else the persona's level resolves to its
> group's preferred pin; else the session model is inherited."

## Decision

1. **Every catalog persona gains `level:` beside its existing `model:`.**
   The sweep is `features/*/personas/*.md` (14 files, S7) — not just
   `features/common/personas/` (5). `api-engineer` lives in
   `features/node/personas/`, `hermes-agent-author` in
   `features/hermes/personas/`; dotnet, react, angular, azure and vue homes
   hold the rest. `tests/test_qa_personas.py` (qa in common, qa-backend in
   dotnet, qa-frontend in react) decides the distribution. Mapping follows
   the lanes ADR-0015 already set, opus → high, sonnet → medium:
   `architect`, `code-reviewer`, `delegator`, `qa`, `qa-backend`,
   `qa-frontend` are `high`; `test-engineer`, `api-engineer`,
   `hermes-agent-author`, `dotnet-engineer`, both `frontend-engineer`s,
   `angular-engineer`, `cloud-infra-engineer` are `medium`. No persona
   defaults to `low` today — low is reserved for mechanical dispatches that
   name it explicitly; no catalog persona is haiku-grade. `model:` is kept
   verbatim everywhere (grandfather).
2. **`level:` lives in lane frontmatter only — no new `tool_input` field.**
   A future `declares_level()` disjunct beside `declares_model()` is
   recorded here as **gate-only** vocabulary: it will read the lane file,
   never a dispatch argument. This lane wires no logic (3c is DENY_REASON +
   docstring text only); the disjunct is documented, not implemented.
   Gate-declared ≠ runtime-routed on Claude: `adjust_agents.CLAUDE_KEYS`
   does not carry `level:`, so it is stripped at `.claude/agents/`
   delivery by design, and the gate docstring says so. Fail-open on
   unreadable files is preserved (S6); loud (deny/marker) only for
   parseable ones.
3. **The delegation-map generator names the level beside the lane,
   unconditionally (S7).** `_persona_lines` renders `Level: <level>` next
   to the existing `Lane: <model>` for every scaffolded persona, and the
   `delegation.md.tmpl` reasoning-model section is rewritten in levels
   terms. An invalid registry/level degrades loud, never aborts (M5): the
   offending line carries an `UNKNOWN LEVEL` marker naming the bad value
   and the closed set, plus a scaffold note — the run still renders.
4. **Gate deny text names the levels and quotes the precedence (M2).**
   `DENY_REASON` keeps its shape (deny, name the fix, point at
   `.ai-badger/delegation.md`) and gains the three level names plus the
   quoted sentence above as its context. Zero logic change.
5. **Tests are the contract (TDD, RED-witnessed).**
   `tests/test_persona_levels.py`: L1-A1..A4 (sweep declares a level /
   closed set / keeps the bare lane / bare banned), L1-B1/B2 (map renders
   levels; unknown level is a loud marker, not an abort) with a catalog-
   sweep discovery rule and a bare-fixture provocation pair (M12/G4).
   B3-fail-loud was cut: the warn-convention (`model_groups.resolve`
   warns on a stale non-deciding level, T-A7; hooks fail open; M5
   marker+note) settles it, so B3 asserts marker/note content instead.

## Consequences

Positive:

- Personas state intent (`high` = must be derived; `medium` = determined by
  an existing spec) where today they state only a bare lane. The map can
  teach routing; the registry can resolve it.
- The deny path teaches the new vocabulary at the moment of need, quoting
  (not forking) PKG-2's precedence.
- Grandfathering keeps every existing dispatch working: nothing that
  resolved yesterday stops resolving today.

Negative:

- Two keys can disagree (`level: high` beside `model: sonnet`). No
  validator cross-checks them in this lane; a mismatch reads as intent
  without enforcement until the `declares_level()` disjunct lands.
- `low` has no default persona, so the map advertises a level no persona
  exemplifies — honest (no persona is mechanical) but asymmetric.

Neutral:

- `.claude/agents/` copies do not carry `level:` (stripped at delivery).
  A reader diffing source against delivery sees the key vanish; that is the
  gate-only contract, recorded here and in the gate docstring.

## Alternatives considered

- **Replace `model:` with `level:` outright.** Rejected: Claude routes on
  the bare lane at runtime; dropping it would break every dispatch on the
  day PKG-1 is still unmerged. Dual-key keeps both readers working.
- **New `tool_input.level` dispatch argument.** Rejected: a second
  per-invocation knob beside `model` re-opens the override fight ADR-0015
  settled (per-invocation beats frontmatter). Intent lives in the lane
  file; the invocation carries only `model` or nothing.
- **Fail-loud on an invalid registry (B3 as written).** Cut: three
  precedents say degrade — `resolve()` warns on stale levels, hooks fail
  open, M5 requires marker+note. A scaffold that aborts on one bad level
  bricks every project for a typo.
