# Split the persona's `level:` into a model group and a thinking level

- **Date:** 2026-10-20
- **Status:** design, not implemented
- **Owner:** the repo owner set the direction; the details below are proposals
- **Related:** [the 402 research](2026-10-20-model-registry-free-fallback-research.md), ADR-0027, ADR-0033, ADR-0037

## The problem: one word, three meanings

`level:` in a persona's frontmatter currently means the routing intent that ADR-0027 defined:
a name in `low|medium|high` that the pi harness resolves against the model-groups registry
to a concrete paid model id. That reading is wrong for what a persona actually wants to say.
A persona for an architect does not want "give me a 5-dollar model". It wants "think hard,
and do it on a model I can afford". Effort and cost are different axes, and the framework
collapses them into one key, so a request for a careful review silently becomes a request
for an expensive model.

Three collisions follow from that:

1. **The persona's own vocabulary.** ADR-0027 read the persona's `level:` as a cost tier
   and made the model registry the owner of that word. The persona wanted effort.
2. **The hosts' vocabulary.** pi calls effort a *thinking level* and spells it
   `off|minimal|low|medium|high|xhigh|max` (`docs/settings.md` in the pi package). The
   framework's three values are a subset of pi's seven, and the framework's `low` is
   simultaneously "cheap model" and "little thinking".
3. **The two registries.** The model-groups registry answers "which model?" and the
   delegation map answers "which tier?", but nothing in the framework answers "how hard
   should this persona think?".

The 402 in the sibling research is the visible symptom: a `level: high` persona was
dispatched to `openrouter/deepseek/deepseek-v4.1-flash`, the cheapest paid member of the
`high` group, and that member answered 402 because the account balance is negative
(-0.199 USD, measured 2026-10-20). A person who asked for a careful reviewer got a price
list, and the price list was wrong.

## The split

| concept | values | owner | meaning |
|---|---|---|---|
| model group | `low`, `medium`, `high`, `top` | a new model-map data file | a cost tier, anchored on one model per known family |
| model | a provider-qualified id, or a family name | the map, or the persona | the concrete thing that answers |
| thinking level | `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | pi's own vocabulary | how much the model thinks |

A persona becomes a template with two routing fields:

```yaml
---
name: architect
description: ...
model: high        # a model group, or a concrete model id
thinking: high     # a thinking level, pi's vocabulary
---
```

The thinking level gets its own key, `thinking:`, and `level:` is retired. The catalog's
values move as they are (`high` for architect, code-reviewer, delegator and qa; `medium`
for the rest are already valid thinking levels), so the migration is a rename plus the tier
moving into `model:`. Retiring `level:` outright beats repurposing it: a key that changes
meaning between versions still means two things to anyone reading an old scaffold next to
a new one, and that ambiguity is what we are removing.

## The model map

One data file owns the groups. It answers "which model is the `high` group" for every
family the framework knows, and it carries the ordered, priced, licensed list of concrete
models that the open harnesses resolve against.

```json
{
  "frameworkVersion": "0.208.0",
  "measuredAt": "2026-10-20",
  "groups": {
    "low":    { "anthropic": "haiku",  "openai": "luna"  },
    "medium": { "anthropic": "sonnet", "openai": "sol"   },
    "high":   { "anthropic": "opus",   "openai": "sol"   },
    "top":    { "anthropic": "fable",  "openai": "astra" }
  },
  "models": [ { "id": "openrouter/anthropic/claude-opus-5", "group": "high", "pricing": {...}, "license": "Proprietary", "score": 80.09, "evidence": "..." } ]
}
```

The family names carry no version, on purpose. `opus` means the newest opus the host
resolves, which is what Claude Code's `model:` field wants and what pi's fuzzy model
matching wants (`pi --model sonnet:high` is documented, `docs/cli.md`). The concrete ids
in `models` carry the version, because the open harnesses need an exact id.

The Anthropic ladder is the owner's: `top` is fable, `high` is opus, `medium` is sonnet,
`low` is haiku. The OpenAI ladder follows the same price shape, and the leaderboard
prices line up with it (per 1M tokens, from `~/Downloads/benchlm-leaderboard.csv`):

| group | anthropic | price | openai | price |
|---|---|---|---|---|
| top | fable | 10 / 50 | astra (GPT-6 Astra) | 10 / 50 |
| high | opus | 4 / 20 | sol (GPT-5.6 Sol) | 4 / 20 |
| medium | sonnet | 2 / 10 | sol (GPT-6.1 Sol) | 2 / 10 |
| low | haiku | 0.1 / 0.5 | luna (GPT-6 Luna) | 0.1 / 0.5 |

The analysis looks only at the newest model of each family, which is why the sol family
holds two slots. The sol family spans two price bands: its newest member, GPT-6.1 Sol, is
priced at 2/10 and sits in the medium band, while GPT-5.6 Sol at 4/20 sits in the high
band. A family may therefore anchor more than one group, and the newest member of each
family decides the band it lands in. Terra (GPT-5.6 Terra, 2/12) is the next candidate in
the medium band, behind sol.

The prices above come from the leaderboard CSV, which the owner picked as the pricing
source of truth.

## How each host resolves a persona

**pi** (the open harness) keeps the group in the persona and resolves it in the extension.
The resolution order becomes "concrete model, else group, else inherit the session model",
and the thinking level rides along separately as pi's own flag. The child argv grows a
`--thinking <level>` (or the `:high` suffix on `--model`), which pi clamps to what the
model supports. The pi extension lives in `Arasz/pi-badger-integration`, not in this
repository, so that half is a second pull request.

**Claude Code** takes a family name, so the delivery maps the group to the family's
version-less name (`high` becomes `opus`). `.claude/agents/` has no thinking-level field,
so the effort is dropped there and recorded as a degrade, the same way ADR-0027 recorded
the loss of `level:` in the Claude delivery.

**Codex** and the other named hosts take their own family names, so the map grows one row
per family the framework knows. The map is the only place that says which name belongs to
which group.

**The open harnesses** (pi, and anything else that speaks provider-qualified ids) keep the
group in the persona and resolve it against the ordered list, which is what the current
registry does with `preferred()`.

## Refreshing the list

The ordered list of concrete models is data, and the data has a machine-readable source
now: `~/Downloads/benchlm-leaderboard.csv` (50 rows, columns `rank`, `model`, `creator`,
`sourceType`, `overallScore`, per-capability scores, `inputPrice`, `outputPrice`). A
refresh step reads it, resolves each display name to a provider-qualified id against pi's
own model store (`~/.pi/agent/models-store.json`, 358 openrouter models, 15 of them free),
and writes the map's `models` list with price, license and score as the evidence.

Two things that source must not hide. The leaderboard CSV and the MODEL/LICENSE table
pasted alongside it are different snapshots of different benchmarks: the CSV scores Claude
Opus 5.5 at 86.66 with a price of 4/20, the pasted table scores it 51.0 at 7.20/1M, and
the pasted table carries models the CSV has no row for (Claude Mythos). The CSV is the
pricing source; the pasted table is not merged into the map.
Second, open-weight models are priced `0 / 0` in the CSV (GLM-5.3, Qwen3.8-Flash-Next,
dots3-note, Ornith), so the registry's rule that every member's price is above zero
(`_validate_pricing` in `features/common/skills/task/scripts/model_groups.py`) has to
change before a self-hosted or open-weight model can sit in a group. That rule is also
what made the earlier "free fallback" idea unrepresentable.

## The den-refresh option

A project that has taken the map should be able to take a new one without waiting for a
framework release, the same way `personaModelPins` survived a refresh. The option belongs
on the refresh path: `refresh.py --update-model-mapping` re-renders the map into the
project and reports what moved, group by group, so a reviewer sees "high moved from
deepseek-v4.1-flash to claude-opus-5" as a diff rather than a surprise.

## What this retires

The persona's `model:` pin in the catalog (a bare lane, `opus` or `sonnet`) loses its
reason to exist. Under the new shape the catalog writes `model: <group>` and lets the
map decide, which is what the `personaModelPins: false` knob was reaching for. The
registry's three groups become four, the validator's price rule changes, the delegation
map's "Level:" and "Lane:" line becomes "Model:" and "Thinking:", the gate's level
vocabulary changes with them, and the persona key `level:` is retired in favour of
`thinking:`. The pi extension's `resolveDelegationModel` gains the group rank and loses
the duty of reading `level:` as a tier.

## Rulings from the owner (2026-10-20)

1. **The analysis looks only at the newest model of each family per group.** A family may
   hold more than one slot, which is why sol takes both the high and the medium slot.
2. **The leaderboard CSV prices the registry.** The MODEL/LICENSE table is not a source.
3. **The thinking level gets its own key, `thinking:`, and `level:` is retired.**

## Test plan

The first commit is a failing test, one behaviour at a time.

- The map validates: four groups, one family anchor per known family, every family anchor
  a name the host can resolve, and a family allowed to hold more than one group.
- A persona's `model:` accepts a group name and a concrete id, and refuses anything else.
- A persona's `thinking:` accepts pi's seven thinking levels, and a persona that still
  carries `level:` is refused rather than read as either meaning.
- The Claude delivery maps a group to a family name and drops the thinking level with a
  recorded degrade.
- The map refresh reproduces the shipped map from the CSV and the model store, and a
  changed CSV changes only what it should.
- The registry validator accepts a zero-priced open-weight member and still refuses a
  group with no preferred member.

## Appendix: the old registry against the map

Recorded while the map was built, so the rewrite of the consumers that assert on the old
seed does not have to rediscover it. The old seed pinned ten ids the leaderboard has no
row for, and those ids are gone from the map: `glm-5.3-flash`, `deepseek-v4-flash-0731`,
`xiaomi/mimo-v2.5`, `anthropic/claude-haiku-4.5`, `deepseek-v4.1-flash`,
`xiaomi/mimo-v2.5-pro`, `deepseek-v4-pro`, `anthropic/claude-sonnet-5`,
`meta/muse-spark-1.3` and `meta/muse-spark-1.3-contributor`, the last being the demoted
tail together with its weights-identity twin. Seven of the old pins survive under the
same spelling: `openai/gpt-5.6-luna`, `deepseek/deepseek-v4-pro-0813`, `z-ai/glm-5.3`,
`openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, `anthropic/claude-opus-5` and
`anthropic/claude-fable-5.1`.

Thirteen of the leaderboard's fifty rows are not in the map, and the reasons differ.
Seven have no id pi's openrouter catalogue can resolve: Muse Wonder Full, Kimi K3,
Grok 4.5, Grok 4.6, Gemini 3.1 Pro, Qwen3.8-Flash-Next and Ornith-1.5-397B, the first
four of which the store lists only under github-copilot and radius. Five resolve but
carry no price in the leaderboard, so they have no tier: Qwen3.8 Max, Ling 3.1 Flash,
Muse Spark 1.1, Muse Spark Open and Qwen3.7 Max. One resolves only to a free listing
while the leaderboard prices it above zero, which would bind a paid price to a free id:
MiniMax M3.1 Flash.

Those five unpriced rows are a gap in the leaderboard, not in the map. The CSV is the
pricing source by the owner's ruling, so the prices belong there, and the refresh step
has to name the unpriced rows rather than drop them quietly. Two of the five carry a
price in the MODEL/LICENSE table that the CSV lacks, which is a measure of how far the
two snapshots have drifted, not a reason to merge them.

The tier a group resolves to was the open question, and it is decided: a group resolves
to its anchor, not to its cheapest member. The band shape stays (all 25 members, the
free open-weight tail included), and three fields make the anchor load-bearing: every
member carries the family it belongs to, every group names the `primary` anchor whose
model leads it, and the group's preferred member is the member whose family is that
anchor's name. The order rule changes with it: the preferred member first, then the rest
in ascending price, the zero-priced open-weight members last because they have no price
position. `high` therefore resolves to `openrouter/anthropic/claude-opus-5.5` rather than
to the cheapest model the tier happened to hold.

The anchor wins because the owner's ladder is a statement about models: high is opus,
medium is sonnet, low is haiku, top is fable or astra. A tier that resolved to whatever
it held cheapest would say the opposite, and the anchors would be decoration on the open
harness. The ladder shape (one member per anchored family per group) was measured as an
alternative and rejected: it collapses each tier to two members, drops the free
open-weight members, and leaves the price rule's zero-price branch exercised only by
fixtures. The ruling is cheap to reverse: the map is data plus one invariant, and the
render is one pass.

Neither shape makes a free member the resolved one, because a zero price has no position
in the order. The 402 that started this stays open on pi until the billing-error retry
lands in the extension, or a tier grows an explicit free-first preference. That is a
separate decision and is not folded in here.
