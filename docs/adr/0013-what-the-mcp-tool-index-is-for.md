# ADR-0013 — What the MCP tool index is for

**Date:** 2026-07-29
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude
**Superseded in part by:** [ADR-0014](0014-mcp-support-is-configuration-not-retrieval.md)
(2026-07-29). The three purposes below stand; the premise that tool definitions are already
resident in the model's context is false on current Claude Code, and the ordering derived from
it is reversed there. Added 2026-08-07 — this pointer was missing, and `docs/adr/README.md`
requires a supersession to be said in both.

**Supersedes:** Nothing. [ADR-0004](0004-mcp-tool-index.md)'s first stated problem is recorded
below as never having been addressed; its decisions are not reversed.
[ADR-0012](0012-bm25-retrieval-with-a-falsifiable-eval.md) stands in full — BM25 remains the
matcher, and nothing here changes it.

## Context

A day of measurement against this repository's real 98-tool index and two fixture sets
(58 authored, 70 harder, plus a 40-fixture sealed set written blind) produced a set of results
that together change what this feature is *for*. They are recorded here so the question is not
re-litigated from intuition.

### The founding justification was two problems, and only one was ever addressed

ADR-0004's Context names them:

> 1. **Prompt bloat:** Tool definitions consume thousands of tokens that are wasted on most turns
> 2. **Tool selection errors:** The agent sometimes picks the wrong tool from a set of
>    near-duplicates

The index addresses the second. It has never addressed the first, and cannot while the host owns
the tool surface. On Claude Code every MCP tool definition is loaded into context each turn by
the host; ai-badger's hint does not replace them, it is appended to them. Measured on this
repository: the real schemas for 98 tools are already present, ai-badger's condensed index is
~2,300 tokens and lives on disk, and the injected hint is ~75 tokens **on top**. The feature is a
net addition to the context it was justified as reducing.

This is not a defect in the implementation. It is a premise that was true of the deployment
ai-badger began in — a Hermes plugin, where ai-badger's own hook composed the prompt — and false
of the one it now mostly runs in.

### What the measurements established

1. **BM25 ranks well on precise vocabulary and not at all on paraphrase.** recall@1/@3 of
   0.930/1.000 on the authored set; 0.442/0.481 on the harder one. Per class: `near-dup`
   1.000/1.000, `user-voice` 0.200/0.333, `paraphrase` **0.000/0.000**.
2. **The first fixture set could not see this.** It reported recall@3 of 1.000 and was read as
   "saturated, no headroom". The saturation was real; the inference was an artefact of an
   instrument whose queries were written in the vocabulary of the documents they were meant to
   find (mean token overlap 0.781).
3. **No query-side technique moves paraphrase.** 29 measured configurations — WordNet expansion
   (12), corpus-derived expansion (5), embedding-derived thesaurus (10), character n-grams (2) —
   left paraphrase recall@3 at 0.000. WordNet is not the obstacle its licence might have been:
   the licence permits redistribution and a corpus-scoped table is 42–271 KB. It simply does not
   contain the needed relations (`swap → replace` is absent), and only 23.3% of paraphrase
   out-of-vocabulary terms expand into their target document. An oracle expansion needs **two**
   correct terms per query to work (one scores 0.118, two 0.765, three 1.000); WordNet supplies
   about one.
4. **Semantic embeddings close the vocabulary gap and the gate takes it back.** Ungated, a 7.6 MB
   static table lifts recall@3 to 0.731 and paraphrase to 0.47. At unchanged false fire, across
   ~1,000 operating points per model, paraphrase returns to 0.000–0.059.
5. **The gap is answerability, not vocabulary.** Every paraphrase positive scores at or below the
   best adjacent negative, for static and contextual encoders alike; AUC for separating them is
   0.196 and 0.520 — chance or inverted. "Which routines have grown way past a reasonable length"
   is answerable here and "profile this code to find performance bottlenecks" is not, yet they
   are equally *similar* to a corpus of developer tools. No similarity function encodes which the
   index can serve, because that is a fact about the index's contents.
6. **A matcher fitted on our own descriptions is worthless.** A probe on the 43 authored
   positives scores recall@1 of 1.000 in-sample and 0.070–0.256 under leave-one-out — below the
   untrained baseline. The training set is ~100 documents and ~900 content tokens.
7. **Enriching the documents works, and only if it writes semantics rather than queries.** An
   agent-driven loop writing tool semantics scores 0.533 on the sealed set (0.800 ungated);
   the same loop writing the observed query text scores 1.000 in-sample and **0.000** sealed.
   Against the sealed set, enrichment gives McNemar b=16/c=0 (p=3.1e-05) with the authored set
   completely unmoved (b=0/c=0) and its false fire *falling* 0.267 → 0.067. Cost: +18 KB,
   +0.9 ms/turn.
8. **Partial enrichment is worth exactly what it enriches.** Enriching only the 21 tools that
   silent turns pointed at produced results identical to enriching all 98, with untouched tools
   flat.

## Decision

**The MCP tool index exists to supply what the model cannot derive from the tool definitions it
already has.** Concretely, three purposes, and work on this feature is scoped to them:

1. **Curation.** `intent` and `tags` are written by us, not by the server. Knowledge of the shape
   "this is the one that actually works on this repository" is absent from every description and
   cannot be recovered by any ranking of those descriptions.
2. **Answerability.** The index knows what is *not* in it. Finding 5 shows this is not expressible
   as a similarity score, so if it is to be delivered it must be delivered explicitly.
3. **Deployments where the tool list is not all in context** — tool sets too large to load,
   budget-limited hosts, and skills, whose listings are truncated by a budget with descriptions
   dropped least-invoked-first.

**Ranking quality is subordinate to all three.** It serves selection among tools the model can
already see, which is the weakest of the three cases and the one where the model is plausibly
better than the matcher advising it.

## Consequences

### Positive

- The enrichment loop (finding 7) is the primary mechanism, and it serves purpose 1 directly.
  Incremental enrichment is not a compromise (finding 8): an index part-way through is worth the
  tools it has covered.
- A great deal of tempting work is now out of scope with a measurement attached rather than an
  opinion: query expansion, thesauri, fine-tuning, and further weight or threshold tuning.
- The eval instruments (`tooling/retrieval_eval.py`, two fixture sets, the sealed set) stay, and
  any future proposal argues with them.

### Negative

- Purpose 2 has no implementation. The coverage gate half-performs it, on a scalar that
  provably cannot separate the two classes.
- Purpose 3 is unquantified pending cross-agent research: it is not yet established that any of
  the four target agents leaves the tool list out of context.
- The paraphrase class stays at 0.000. This ADR accepts that rather than fixing it, because
  every measured fix costs more than it returns.

### Neutral

- The write-back constraint in finding 7 must be enforced **at write time, not by prompt
  wording** — an agent asked not to paste the query will sometimes paste the query, and the
  in-sample score of doing so is perfect.
- [#165](https://github.com/Arasz/ai-badger/issues/165) is open and unaffected by this scoping:
  the gate suppresses correct matches on sentence-length prompts, which degrades every purpose
  above equally.

## Alternatives considered

- **Ship a small embedding model.** Measured, and it works: 0.731 recall@3 ungated, 22 ms cold
  with a pure-stdlib reader, licence clean (MIT), and `deps_guard` unaffected because a model
  file is data rather than an import. Rejected on distribution: 8.29 MB tracked in three places
  in this repository (+24.9 MB, ~8× clone growth against a 3.18 MiB pack, where the largest
  tracked file today is 48 KB) and two in every consumer repository. The shippable candidate is
  also not statistically significant on the available fixtures (McNemar 4 gained, 0 lost,
  p = 0.125).
- **Reverse ADR-0012 and abandon BM25.** Rejected. BM25 is not what fails; it is perfect on the
  class built to be hard (`near-dup` 1.000/1.000) and its failures are the ones no lexical method
  could reach.
- **Keep pursuing ranking quality.** Rejected as the primary axis, on the grounds in the Decision.
  It remains worth doing where it is cheap and measurable.
