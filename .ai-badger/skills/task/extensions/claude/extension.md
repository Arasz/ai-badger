# task extension: claude

This is a **config-gated extension** of the base `task` skill (`skills/task/`), not a standalone
skill. The base skill names delegation *roles* — "a high-reasoning agent", "a cheap model" —
because it scaffolds for several coding agents. This extension binds those roles to concrete
Claude models, and records the subscription mechanics that motivate the binding.

**Activates when:** the project's `.ai-badger/config.json` has `"claude"` in its `agents` array.

## What the metering actually says

`config.json` carries no plan-tier signal, so this section states what is documented rather than
assuming which plan you are on. **Check Settings → Usage for your actual plan and limits before
leaning on any of it.**

On **Max plans, premium seats on Team plans, and premium seats on seat-based Enterprise plans**:

- Models included in the plan share a weekly pool. Anthropic on the top tier: *"Fable 5 draws
  from your plan's regular weekly usage limits and uses them faster than other Claude models."*
- Fable has a **billing threshold at 50%, not a ceiling**: *"once you use up to 50% of your
  weekly usage limits on Fable 5, you can continue in one of two ways: keep using Fable 5 with
  usage credits, or switch to another Claude model."* Past that point Fable stops being
  plan-funded and starts costing cash.
- There is also a second weekly limit **scoped to Sonnet models**: *"Max plans also have two
  weekly usage limits: one that applies across all models and another for Sonnet models only."*
  Anthropic does not document how the two interact — whether Sonnet usage is exempt from the
  all-model limit or is simply constrained twice. **Do not treat it as bonus capacity.** Sonnet
  is the cheap lane on per-token price and task fit, which is reason enough; it is not
  established that it spends an allowance the other lanes cannot.

On **Pro plans and standard seats on Team plans**: *"Fable 5 isn't included in your plan's usage
limits. You can use Fable 5 with usage credits."* Fable does not touch the weekly pool there at
all — it bills separately from the first call.

Whether Opus carries its own weekly limit is genuinely ambiguous: the Max-plan article describes
the second limit as Sonnet-only, while the usage-limit best-practices article still refers to a
reset *"for Opus only and all other models"*. Note that if Opus does have its own limit it is a
**cap, not a bonus** — the same reading that applies to the Sonnet one. Re-derive the lanes if
Anthropic clarifies which article is current.

> Verified 2026-07-26 against `support.claude.com`. Limits, tiers and pricing change; re-check
> the "Usage and limits" collection rather than trusting these numbers indefinitely.

## Claude model lanes

- **Opus — planning and the quality gate.** Phase 1 decomposition and the Phase 3 correctness +
  architecture review. Also: adversarial review of another agent's claims, money or other
  derivation-heavy math, non-obvious root-cause debugging, and arbitration when two work
  packages disagree about a contract. Dispatch `model: "opus"` and prefix the call's
  `description` with `"Opus: "` so the lane is visible in the agent panel.
- **Sonnet — implementation, by default.** Everything that executes an already-decided spec:
  writing code, writing ADRs and docs where the decision is already recorded, mechanical
  fix-ups, and test backfills with pre-derived expected values. Pass `model: "sonnet"`
  explicitly rather than relying on the default, so the lane survives a change of session model.
- **Haiku — trivial mechanical work.** Comment and doc touch-ups, rote refactors, liveness
  probes. Dispatch `general-purpose` with `model: "haiku"`.
- **Fable — not a routine lane**, on either plan shape, but for different reasons. On Max and
  premium seats it draws the same pool as Opus and drains it faster, then bills cash past the
  50% threshold — so for reasoning work Opus already handles it is strictly the worse trade. On
  Pro and standard Team seats it costs cash per call from the first call while Opus costs pool,
  so the trade is budget-versus-pool rather than pool-versus-pool; decide on which is actually
  scarce for you. Either way: reserve it for a problem Opus has been tried on and failed, and
  say why when you dispatch `model: "fable"`.

The orchestrating session must not assume it is already running the planning lane — the default
model for new sessions changes. Get the reasoning by dispatching an explicit `Agent` call with
the `model` override, not by doing the work in-session because the session "is" Opus today.
