# Model dispatch on pi when the paid tier is empty — traced path, corrections, and the smallest fix

- **Date:** 2026-10-20
- **Status:** research — traced, not implemented
- **Subject:** a delegated persona lane answers 402 (OpenRouter) while the parent session keeps working
- **Scope note:** the failure spans two repositories. The registry, its schema and its
  validator live in this repository, so design A lands here. The pi harness that resolves
  and spawns the child lives in `Arasz/pi-badger-integration` (the extension under
  `~/.pi/agent/extensions/subagent/`), so design D lands there. Neither half belongs
  upstream through `feed-badger`.

## Symptom

A delegated persona lane (`delegate` / `queue` fan-out) fails with an OpenRouter
402 — insufficient credits — while the parent session continues to answer normally.

## Traced path (caller → entry point)

1. **Persona delivery.** `features/pi/adjustments/adjust_agents.py:118-121` renders
   `.pi/agents/<persona>.md` from `features/*/personas/<persona>.md`, keeping only
   `PI_KEYS = ("name", "description", "level")` (line 35) plus `model:` **iff** it is a
   provider-qualified id (`render()`, lines 108-121; the comment at lines 31-33 says a bare
   Claude lane is "rejected there" and is therefore stripped).
   READ: in this checkout every delivered persona carries `level:` and **no** `model:`
   (`.pi/agents/architect.md`, `code-reviewer.md`, and the five others).
2. **Resolution.** `features/common/skills/task/scripts/model_groups.py:338-356`
   `resolve()` — explicit model wins verbatim → else the level's preferred pin
   (`preferred()`, lines 320-336) → else `None` (inherit the session model).
   The same order is stated for the pi harness in
   `features/common/skills/task/extensions/pi/extension.md:21-23`.
3. **The preferred pins are valid pi ids.** `features/common/data/model-groups.json`
   lines 11, 68 and 189 — `openrouter/z-ai/glm-5.3-flash` (low),
   `openrouter/deepseek/deepseek-v4.1-flash` (medium and high). Both ids exist in pi's own
   model store (`~/.pi/agent/models-store.json`, provider `openrouter`).
   → **The failure is not a resolution error and not a gate refusal.**
4. **The failure is billing.** `GET https://openrouter.ai/api/v1/credits`:
   `total_credits 830.95`, `total_usage 831.14` → balance ≈ **−0.19 USD**.
   MEASURED 2026-10-20, and the same account is reached through both credentials —
   the environment key `OPENROUTER_API_KEY` and pi's own stored credential
   (`~/.pi/agent/auth.json` → `openrouter.access`, an oauth token) return identical
   totals. Paid ids on this account answer 402; `:free` ids do not.
5. **Why the parent session survives.** `PI_PROVIDER=openrouter`,
   `PI_MODEL=minimax/minimax-m3.1-flash:free` — the session's own id is a **free** id
   (pi's store lists 15 `:free` openrouter ids).

## Corrections to the earlier reading of this failure

| Earlier claim | What the source says |
|---|---|
| "Every scaffolded persona pins a bare alias, so the pin beats the level and fails the gate." | The **catalog** templates do carry bare lanes (`features/common/personas/*.md`: `model: opus` in 6, `model: sonnet` in 8). The **delivered pi files** do not: a bare alias is stripped by `adjust_agents.render()`. On pi the level decides; the alias is Claude-lane vocabulary grandfathered by ADR-0027. |
| "A providerAffinity mechanism keeps a level-resolved id on the session's provider; here the provider is openrouter, so affinity is a no-op." | The mechanism exists, but not in this repository. It lives in the pi harness: `~/.pi/agent/extensions/subagent/delegation-core.ts:1329` (`withProviderAffinity`) swaps a level-resolved id for the group's first same-provider member, or for the session model, when the resolved id sits on a different provider. Here it is a no-op for a precise reason: the level resolves to `openrouter/deepseek/deepseek-v4.1-flash` and the session model is also on provider `openrouter`, so there is nothing to swap. The session's own id, `openrouter/minimax/minimax-m3.1-flash:free`, is a free-tier id that no group lists, so the registry cannot route to it either. |
| "The registry's paid ids never get a turn." | The preferred pins are the **cheapest** paid ids ($0.15 in / $0.60 out per M). They do get a turn; they answer 402. |
| "The persona pin wins over the level, so the level never decides." | The pin cannot shadow the level, twice over. The pi delivery keeps a persona's `model:` only when it is a provider-qualified id (`features/pi/adjustments/adjust_agents.py:121`), so the catalog's bare lanes never reach `.pi/agents/`. And even if a bare pin did arrive, `admitExplicitModel` (`delegation-core.ts:1180`) refuses it, names it in `modelWarning` and treats it as absent at its rank, so the level decides (the grandfather clause for legacy bare pins is retired, `delegation-core.ts:1211`). |
| "The session's own id demonstrates quota." | It demonstrates **free-tier** access (a `:free` id), not paid quota. It proves the id and the key work; it says nothing about the paid balance, which is negative. |

## A second, separate failure shape: the provider-less id

A sibling project's working tree (ai-raccoon, uncommitted at the time of writing) worked
around the 402 by rewriting every persona's pin to
`model: minimax/minimax-m3.1-flash:free`. That id is not a form pi's store guarantees:

- pi's registry keys a model by provider plus id, and the store holds the free model as
  provider `openrouter`, id `minimax/minimax-m3.1-flash:free` — the addressable id is
  `openrouter/minimax/minimax-m3.1-flash:free` (this session's own `PI_MODEL` /
  `PI_PROVIDER` pair says the same thing). `~/.pi/agent/models-store.json` lists eight
  providers, and `minimax` is not one of them; the free id sits inside the `openrouter`
  provider's 358 models, 15 of which end in `:free`.
- The framework's pi delivery keeps a persona's `model:` only when it matches
  `<provider>/<model>` (`features/pi/adjustments/adjust_agents.py:31-36, 108-121`), so
  `minimax/minimax-m3.1-flash:free` **passes** the filter and is handed to pi.

The log evidence for the provider-less form is weaker than it first looked. The run
`cfe47dab/d-87.jsonl` used that id and did work: 460 log lines, ten assistant turns ending
on `stopReason: stop`, exit 0, and every message served by provider `openrouter` with model
`minimax/minimax-m3.1-flash:free`. So pi resolved the provider-less id by matching it
inside the openrouter catalogue. That is luck of the catalogue, not a contract, and it
leaves the pin ambiguous the moment two providers carry the same model name.

The earlier note that "d-87 died before any session event was written (1 log line)" does
not hold. No `d-87.jsonl` in any project log directory has one line: the ai-badger
directory's `d-87` is an unrelated `openai/gpt-6-sol` test-engineer lane, and the
one-line logs in the ai-raccoon directory are `d-94` and `d-95`, two dotnet-engineer lanes
on an observability task. The safe rule stands anyway: use the provider-qualified id
`openrouter/minimax/minimax-m3.1-flash:free`, and treat the provider-less form as
unverified rather than broken.

## Root cause

Two independent facts, one of which is a framework gap:

1. The OpenRouter account's paid balance is exhausted (measured above). Not a code fault —
   it needs a top-up, and until then only `:free` ids answer.
2. The registry has **no free-tier member**: all 19 ids are priced paid ids
   (`features/common/data/model-groups.json`), and `model_groups` has no way to express
   "when the paid pin is unaffordable, use this one instead". So a level resolution can
   only ever land on a paid id, and the framework has no signal that separates
   *this id is unaffordable right now* from *this id is wrong*.
3. The registry cannot even *hold* a free id today. `model_groups.validate_registry`
   requires every member's `pricing.inputPerM` and `outputPerM` to be numbers greater than
   zero (`_validate_pricing`), requires the preferred member at index 0
   (`_validate_group`), and requires ascending price order over the active members
   (`_validate_order`). A zero-cost member is refused by the price rule, and a member
   priced above zero is not free, so the free tier needs a schema and validator change,
   not just a data change.
4. The runner's model-failure retry does not cover billing. The retry arms only when the
   child dies with exit code 1, parses no progress event, and its stderr matches
   `MODEL_STARTUP_FAILURE_RE` (`delegation-runner.ts:524`, the pattern at
   `delegation-runner.ts`: `/no api key found for|model "[^"]*" not found|is ambiguous
   across providers|unknown provider|no models available/i`). An OpenRouter 402 arrives as
   an assistant message with `stopReason: "error"` inside a child that keeps running
   (`cfe47dab/d-83.jsonl`: exit 0, one 402 message, nothing else), so the retry never
   arms even though the parent session's model is a working `:free` id on the same
   provider.

## Candidate designs

**A. A free member in the registry + a free-tier resolution mode.**
`schemas/model-groups.schema.json` gains the shape (the member object is
`additionalProperties: false`, so `pricing: {0,0}` plus a discriminator field is needed);
`model_groups` gains a second resolution entry point; the pi extension documents the
dispatch form. No network, no hot-path cost. The open question is the *trigger* — see
the owner decision below.

**B. Probe provider credits before dispatch.** Rejected: it puts a network round-trip in
the dispatch path, and the framework has no portable notion of "this provider's balance".

**C. Documentation only.** State in the pi extension that a 402 means "top up, or
dispatch an explicit `:free` id" and list the free ids pi's store offers. Zero code, but
the failure stays in place and the operator must know the id to type.

**D. Retry a billing failure on the parent model.** The runner already has the machinery:
a fallback argv, one respawn under the same run id, and a recorded reason. It just does
not fire for a 402, because the 402 is an API error inside a live child rather than a
startup failure. Widening the trigger to a provider billing error (402, or a
`requires more credits` message) and letting it respawn on the parent model would make
every delegation survive an empty paid balance, at the cost of one extra spawn, with no
network call in the dispatch path and no schema change. It also removes the need to
guess which ids are free.

**Recommendation:** D first, then A with C's text as the operator-facing half. D is a
change to one predicate and reuses machinery that already exists; A needs a schema and
validator change and still needs a trigger, which D supplies. B costs a round-trip per
dispatch for a signal the caller already has (the 402 itself).

## Test plan (TDD — the first commit is a failing test)

- `tests/test_model_groups_registry.py` — a free member validates; `resolve(level=...)`
  still returns the paid preferred pin by default; the free mode returns the free id;
  a member that is neither pinned nor free is refused.
- `tests/test_registry_free_fallback.py` (new) — the resolver never returns an id that
  fails `MODEL_ID_RE`; a `:free` id survives the schema's `pattern` (it does:
  `:[A-Za-z0-9._~@:+-]*` is in the allowed class).
- RED witness required before the implementation (invariant: a check that has never been
  seen fail is not a check).

## Open decisions for the owner

1. **Trigger.** Explicit opt-in (an env var such as `AIB_MODEL_FREE_FALLBACK=1`), a
   per-dispatch flag, or the caller reacting to the 402 it just saw? The third needs no
   framework state and is the smallest; the first is the most predictable.
2. **Shape.** A `tier: "free" | "paid"` discriminator on the member, or a separate
   per-group `free` id?
3. **Catalog personas.** Keep the bare Claude lanes in `features/*/personas/*.md`
   (ADR-0027's grandfather clause). Do **not** replace them with provider-qualified pins:
   on pi a qualified pin passes the shape gate and overrides the level, which would freeze
   every persona to one provider and defeat the registry. The catalog already ships the
   level-only path (ADR-0033's `personaModelPins: false`), and the pi delivery is
   pin-free today.
4. **Where each half lands.** Design A is a change here (schema, validator, seed data).
   Design D is a change in `Arasz/pi-badger-integration` (the runner's retry predicate).
   Neither is a `feed-badger` contribution, and the two need separate pull requests.

## Related state, measured on 2026-10-20

- The ai-raccoon review lane `d-82` (owner: the ai-raccoon session, project
  `cfe47dab-…`) is the `code-reviewer` lane asked to review ai-raccoon PR #889
  (`task/air-fix-repair-open-workspaces-census`). It ran for a long time rather than dying
  early: 964 log lines, ending mid-`dotnet test` inside a worktree at `/tmp/air-review-wt`,
  with **no exit record**. No `pi -p --mode json` child is running any more, so that lane
  will not deliver a result; it needs a re-run. Its target is stale as well: `gh pr view
  889 --repo Arasz/ai-raccoon` reports the pull request as MERGED.
- Sibling runs in the same session show the three failure shapes apart. `d-83`
  (`openrouter/deepseek/deepseek-v4.1-flash`, a paid registry id) exits 0 with a single
  402 message: "This request requires more credits, or fewer max_tokens. You requested up
  to 179633 tokens, but can only afford 6681." `d-81` (`anthropic/claude-sonnet-5-5`)
  fails the same way. `d-84` (`openrouter/deepseek/deepseek-v4.1-flash`) wrote five lines
  and no exit record, which is the stale-extension-context shape ("This extension ctx is
  stale after session replacement or reload"). `d-87` (`minimax/minimax-m3.1-flash:free`,
  provider-less) and `d-92` (`openrouter/minimax/minimax-m3.1-flash:free`) both completed
  with exit 0 and no error, and `d-93` (`openrouter/thinkingmachines/inkling:free`)
  completed too. Free ids work; paid ids answer 402.
- The 402 and the "unknown model" are **different failures**: 402 is the exhausted
  balance (measured above); the instant deaths are id resolution and a stale pi
  extension context. Fixing the id does not restore the paid balance.
- A free id is available in pi's own store: `~/.pi/agent/models-store.json` lists 15
  `:free` models under the `openrouter` provider, including the one this session runs on,
  `openrouter/minimax/minimax-m3.1-flash:free`.
