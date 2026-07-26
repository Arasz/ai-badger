# task extension: claude

This is a **config-gated extension** of the base `task` skill (`skills/task/`), not a standalone
skill. The base skill names delegation *roles* — "a high-reasoning agent", "a cheap model" —
because it scaffolds for several coding agents. This extension binds those roles to concrete
Claude models, and explains the subscription economics that make the binding worth following.

**Activates when:** the project's `.ai-badger/config.json` has `"claude"` in its `agents` array.

## Why the lanes are what they are

The lanes below are not a quality ranking. They follow from how a Claude subscription meters
usage, which is not what most people assume:

- **One weekly pool covers every model.** There is no bonus allowance that a more expensive
  model draws from instead. Anthropic's own wording for the top tier: *"Fable 5 draws from your
  plan's regular weekly usage limits and uses them faster than other Claude models."*
- **Fable 5 is additionally capped at half that pool** on Max and Team Premium: *"You can use up
  to 50% of your weekly limit on Fable 5, but your use of other models draws from the same usage
  limits and you can never use more than your weekly limit."* So Fable is not extra capacity —
  it is the same capacity spent faster, against a ceiling.
- **Sonnet has headroom nothing else can reach.** Max plans carry a second weekly limit that
  applies to Sonnet only. Work pushed to Sonnet is therefore the cheapest work in the literal
  sense: some of it is paid for out of an allowance the other lanes cannot spend.
- **On Pro and Team Standard the picture differs** — there Fable is billed from separate
  pay-as-you-go usage credits rather than the plan, so it costs cash per call instead of pool.

Whether Opus additionally has its own sub-pool is genuinely ambiguous in Anthropic's docs — the
Max-plan article describes the second weekly limit as Sonnet-only, while the usage-limit
best-practices article still refers to a reset "for Opus only and all other models". The
recommendation is robust either way: if Opus shares the pool it is no worse than the tier above
it, and if Opus has its own reset it is strictly better.

> Verified 2026-07-26 against `support.claude.com`. Limits and tiers change; re-check the
> "Usage and limits" collection before treating these numbers as current, and prefer whatever
> the plan's own Settings → Usage page shows.

## Claude model lanes

- **Opus — planning and the quality gate.** Phase 1 decomposition and the Phase 3 correctness +
  architecture review. Also: adversarial review of another agent's claims, money/tax or other
  derivation-heavy math, non-obvious root-cause debugging, and arbitration when two work
  packages disagree about a contract. Dispatch with `model: "opus"` and prefix the call's
  `description` with `"Opus: "` so the lane is visible in the agent panel.
- **Sonnet — implementation, by default.** Everything that executes an already-decided spec:
  writing code, writing ADRs and docs where the decision is already recorded, mechanical
  fix-ups, and test backfills with pre-derived expected values. Pass `model: "sonnet"`
  explicitly rather than relying on the default, so the lane survives a change of session model.
- **Haiku — trivial mechanical work.** Comment and doc touch-ups, rote refactors, liveness
  probes. Dispatch `general-purpose` with `model: "haiku"`.
- **Fable — not a routine lane.** Same pool, faster burn, 50% ceiling. Reserve it for a problem
  Opus has actually been tried on and failed, and state that reason when you dispatch it.

The orchestrating session must not assume it is already running the planning lane — the default
model for new sessions changes. Get the reasoning by dispatching an explicit `Agent` call with
the `model` override, not by doing the work in-session because the session "is" Opus today.
