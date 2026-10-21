# ADR-0046 — The map pins only the ids the key may route

**Date:** 2026-10-21
**Status:** Accepted
**Extends:** [ADR-0043](0043-model-group-and-thinking-level-split.md) (the model map and
its cost-tier groups). That record owns the map's shape, its groups and the leaderboard
pricing; this one owns which ids the map is allowed to pin.
**Supersedes:** nothing.

## Context

The map gives every cost tier a concrete provider-qualified id, so a host that speaks
those ids (pi) can spawn on it without asking anything of the person. The refresh that
renders the map resolves each leaderboard row against pi's own model store
(`~/.pi/agent/models-store.json`): a listing under the `openrouter` provider is admitted
verbatim, and a model pi lists only under a native vendor (anthropic, openai, google) was
admitted too, whenever the *public* OpenRouter catalogue listed the id derived from that
listing's display name.

The second admission is the defect. pi's `openrouter` section is not the public catalogue:
with a key, pi lists only the models that key may use, and that list comes from
OpenRouter's per-key endpoint, which already applies the workspace's guardrails and
provider restrictions. A model a guardrail excludes is absent from pi's list, and the
id the catalogue still lists for it reaches no provider.

Measured on 2026-10-21, on the machine that renders the map: the key's own model list
carries 308 models and no anthropic id at all, while the public catalogue lists 468. The
shipped map led all four tiers with `openrouter/anthropic/claude-haiku-5.5`,
`openrouter/anthropic/claude-sonnet-5.5`, `openrouter/anthropic/claude-opus-5.5` and
`openrouter/anthropic/claude-fable-5.1`. Three delegations that carried those ids came
back with this body and nothing else:

> 404: {"message":"0 endpoints out of 2 requested are available matching your guardrail
> restrictions and data policy. We removed them for the following reasons (an endpoint
> may have matched multiple reasons):\nProvider blocked by guardrail: 2 endpoints
> excluded; configurable at https://openrouter.ai/workspaces/default/guardrails"}

The same run's other pins behaved: `openrouter/z-ai/glm-5.3` and
`openrouter/openai/gpt-5.6-luna` reached the provider and came back 402 (credits), and
the free ids answered. The map was not wrong about OpenRouter; it was wrong about *this
key*.

## Decision

1. **A row's id comes from pi's model store, and the `openrouter` section of that store
   is the key's own list.** A model that list does not carry has no id: the row stays out
   of the map, and the reason names the list that refused it.
2. **The public catalogue is the record of what OpenRouter lists, not a source of ids.**
   It stays in the map's source block and in the exclusion reason, and it no longer
   admits a row.
3. **The ladder decides the lead when the key can route a member of the ladder's
   family.** A group whose ladder families are all out of reach leads with the best
   member of a declared family, and that member's family becomes the group's primary
   anchor — so the primary always names a family the group holds, and the map's rule
   ("the primary anchor's model leads the group") keeps its meaning.
4. **The declared families and the ladder do not move.** anthropic and openai stay
   declared, and the ladder stays the owner's (ADR-0043 decision 4). A family with no
   member this key can route keeps its ladder slot, because that slot is the family name
   a host that takes family names resolves on its own.
5. **The newest member of the anchor family leads.** The old "exactly one member" check
   is gone: a family may hold several members in a tier, and the best-scoring one leads
   while the rest follow in price.

## Consequences

A delegation that carries a map pin now fails on a price (402, and the router's fallback
takes it from there) instead of on a policy (404, no fallback). A key that blocks a
vendor moves that vendor's tiers onto the other declared family, and the map records
every excluded row with the reason that excluded it.

The map is rendered from the machine's own key, so two operators' maps differ in their
ids: the ids are per key, the ladder and the declared families are not. A consumer that
wants a different vendor's tier re-tunes the ladder in
`tooling/generate_model_map.py` and re-renders; nothing else in the framework has to
change.
