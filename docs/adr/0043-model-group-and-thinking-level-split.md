# ADR-0043 — Model group and thinking level split in the persona frontmatter

**Date:** 2026-10-20
**Status:** Accepted
**Supersedes:** ADR-0027 in part. The dual-key contract survives, but the `level:` key and
the bare Claude lane carried beside it do not.
**Extends:** ADR-0033 (config-gated level-only persona emission) and ADR-0037 (provider
and model pins). Sits next to ADR-0038, which is where the Codex delivery lives.

## Context

ADR-0027 gave every catalog persona a `level:` key and defined it as routing intent: a
name in `low|medium|high` that the pi harness resolves against the model-groups registry
into a concrete paid model id. That definition put three meanings in one key. The key
carried the effort a persona is supposed to spend, the cost tier of the model that answers
it, and the registry's routing vocabulary. Effort and cost are different axes, and the
framework had no way to say both. Under the merged key the cost reading won by default, so
a persona written to ask for a careful review silently became a persona written to ask for
an expensive model.

The hosts already disagreed about the vocabulary. pi calls effort a thinking level and
spells it `off|minimal|low|medium|high|xhigh|max`. The framework's three values are a
subset of those seven, and the framework's `low` had to mean "cheap model" and "little
thinking" in the same breath. The two registries answered two different questions and
neither answered the third: the model-groups registry answered which model, the delegation
map answered which tier, and nothing in the framework said how hard a persona should
think.

The collision was not academic. A persona carrying `level: high` was dispatched to
`openrouter/deepseek/deepseek-v4.1-flash`, the cheapest paid member of the high group.
The OpenRouter account's paid balance measured -0.199 USD, so the request came back 402
while the parent session, running a free tier id on the same provider, kept answering
normally. A person who asked for a careful reviewer was answered with a price list, and
the price list was wrong. The traced path, the measured balance and the corrections to
the earlier reading are in
[the 402 research](../work/2026-10-20-model-registry-free-fallback-research.md).

The design that follows from this is in
[the split design](../work/2026-10-20-model-group-and-thinking-level-split.md), together
with the owner's three rulings: the newest model of each family decides the price band it
lands in, the leaderboard CSV is the pricing source, and the thinking level takes its own
key while `level:` retires.

## Decision

1. **The persona's `level:` key is retired.** A persona carries two routing fields
   instead. `model:` holds a model group (`low|medium|high|top`) or a concrete model id.
   `thinking:` holds a thinking level in pi's vocabulary
   (`off|minimal|low|medium|high|xhigh|max`). A gate that finds a persona still carrying
   `level:` refuses it. The key is not read as either of its old meanings, because a key
   that keeps its name and changes its meaning is a key that still means two things.

2. **From ADR-0027, these clauses survive.** The idea of two routing fields in the
   persona's frontmatter survives, with the second field renamed. Routing intent stays in
   the persona file and never in the dispatch argument, so the `declares_level()`
   disjunct's role is taken over by a `declares_model()` and `declares_thinking()` pair
   that read the lane file only. The resolution precedence survives with the group in
   place of the level: an explicit model wins verbatim, else the persona's group resolves
   to that group's anchor, else the session model is inherited. The degrade discipline
   survives: a value that cannot be resolved renders loud rather than aborting the
   scaffold, and a host that cannot carry a field drops it and records the drop. The
   stance that tests are the contract survives unchanged.

3. **From ADR-0027, these clauses die.** The key name `level:` dies, and with it the
   closed set of three values as a persona field. The catalog sweep dies as written, and
   with it the lane-to-tier mapping (`opus` to `high`, `sonnet` to `medium`) as a persona
   field: the tier survives, but as a group inside `model:`. The grandfather clause dies,
   and so does the scaffold test that banned new bare pins, because both had the bare
   Claude lane as their subject and the bare lane leaves `model:` altogether. What
   replaces them is a positive rule: `model:` holds a group name or a concrete model id,
   and the gate refuses anything else. The quoted precedence sentence in the gate's deny
   text dies in its old wording and is restated with the group in place of the level and
   the thinking level riding beside it rather than folded into it. The recorded loss of
   `level:` at the Claude delivery becomes the recorded loss of `thinking:` there; the
   persona keeps `model:` in that delivery, because Claude Code can carry the family name.
   ADR-0033's knob keeps its shape and narrows its subject: `personaModelPins` still
   strips `model:`, but the value it strips is now a group or a concrete id, and the
   credential-blind bare-alias hazard ADR-0033 recorded goes away with the bare lane.
   ADR-0037's shape-only grammar is unchanged and still governs the concrete-id case.

4. **A model map owns the groups.** One data file holds four cost-tier groups, and each
   group names one anchor per known family. The anchors are version-less family names, so
   a host that takes a family name resolves its own newest member: `haiku`, `sonnet`,
   `opus` and `fable` on the Anthropic side, `luna`, `sol`, `sol` and `astra` on the
   OpenAI side. A family may anchor more than one group, because the analysis looks only
   at the newest model of each family per group. The sol family spans two price bands for
   that reason: its newest member, priced 2/10, sits in the medium group, while the
   older member priced 4/20 sits in the high group. The map is the only place in the
   framework that says which family name belongs to which group.

5. **The leaderboard CSV prices the registry.** The MODEL/LICENSE table pasted beside it
   is not a source and is not merged into the map. The two are different snapshots of
   different benchmarks: they disagree on the price and the score of the same model, and
   the table carries models the CSV has no row for. The CSV also prices open-weight
   models at 0/0, so the registry's rule that every member's price is above zero has to
   change before a self-hosted or open-weight model can sit in a group. That rule is also
   what made a free member unrepresentable before, so relaxing it is what lets one
   exist. The rule that a group must have a preferred member stays.

6. **Each host resolves a persona its own way.** pi keeps the group in the persona and
   the harness resolves it to a concrete id, with the order concrete model, else group,
   else the session model; the thinking level rides along as pi's own flag and pi clamps
   it to what the model supports. The pi extension lives in `Arasz/pi-badger-integration`,
   so that half of the change is a separate pull request and nothing in this repository
   resolves a group on pi's behalf. Claude Code and Codex take the version-less family
   name, so the delivery maps the group to that name and the map grows one row per family
   the framework knows. A host with no thinking-level field drops the thinking level and
   records the degrade the way ADR-0027 recorded the loss of `level:` in the Claude
   delivery.

7. **The catalog migrates as it stands.** The thinking values move as they are: `high`
   for architect, code-reviewer, delegator and qa, `medium` for the rest, all of them
   already valid thinking levels, with the qa family variants keeping the rating ADR-0027
   gave them. The tier moves into `model:`. The bare Claude lanes leave `model:`. The
   gate refuses a persona that still carries `level:` rather than read it as either
   meaning, so a persona written against the old contract fails loudly at the gate
   instead of dispatching to a meaning nobody chose.

## Consequences

Effort and cost are orthogonal now, and that orthogonality is the point of the whole
change. A persona can ask for a careful review on a cheap anchor, or a fast answer on
the newest model, and the two asks are separately visible in the frontmatter instead of
one standing in for the other. The measured 402 stops being a routing accident: asking
for care is no longer silently upgraded into asking for money.

The registry's three groups become four. The validator and the schema change together:
the group set gains `top`, a group names one anchor per known family, a family may hold
more than one group, and the price rule accepts a zero-priced open-weight member while
still refusing a group with no preferred member. The map is data with a machine-readable
source, so a refresh re-renders it and reports what moved group by group, and a project
can take a newer map without waiting for a framework release.

The delegation map's "Level:" and "Lane:" line becomes "Model:" and "Thinking:". The
generator still renders a routing field for every scaffolded persona and still degrades
loud rather than aborting the run.

The cost of the split is a persona file that carries two keys where it carried one, and a
reader who knows only the old contract who finds neither `level:` nor a bare lane. The
gate refusing a stale `level:` is deliberately strict: an ambiguous key that survives is
worse than a persona that stops working loudly. ADR-0033's knob keeps working with a
narrower subject. And the pi half of the change lands in another repository, so for a
while the framework and its harness describe the same contract in two places.

Neutral: the thinking level is pi's vocabulary and pi clamps it to what the model
supports, so a persona may ask for a level its anchor does not offer. A host that cannot
carry a thinking level drops it, and the drop is recorded rather than hidden. The
MODEL/LICENSE table stays out of the map and stays a table.

## Alternatives considered

**Repurpose `level:` for the thinking level instead of adding `thinking:`.** Rejected. A
key whose meaning changes between versions still means two things to anyone reading an
old scaffold next to a new one, and that ambiguity is exactly what this change removes.
A new key can be absent, which says "not written down", or present with one meaning. A
repurposed key is present with two.

**Keep the tier inside `model:` as a bare lane.** Rejected. That is the pin this change
retires. A bare alias resolves credential-blind to whichever provider advertises it, and
the dispatch dies at spawn with no API key found, which is the failure ADR-0033 recorded
when it gave projects a way to drop the pin. The group name is not a bare alias: it is a
name only the map may interpret.

**A second per-dispatch knob for the thinking level.** Rejected. ADR-0027 already settled
that question, keeping the routing intent in the persona file so the invocation carries
only the model or nothing. A knob at the call site would put the effort decision back
where the persona had already answered it.

**Let the group carry the effort, so no second field is needed.** Rejected. A group is a
cost tier and effort does not follow price: the cheapest anchor can reason at the highest
thinking level, and the newest model can answer at the lowest. Collapsing the two axes
into one is the mistake being undone.

**Use the MODEL/LICENSE table as the pricing source, or merge the two.** Rejected. They
are different snapshots of different benchmarks, they disagree on the price of the same
model, and the table carries models the CSV has no row for. The CSV is the source, and
the table is not merged.
