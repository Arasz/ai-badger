# How retrieval works

An agent's context window is a budget, and every tool description, skill listing and instruction
file spends from it before the user has said anything. ai-badger's retrieval layer exists to turn
that fixed cost into a variable one: instead of putting *every* MCP tool in front of the model,
put the two or three that this turn is actually about, and stay silent otherwise.

This document explains what that layer does, how a single query travels through it, why it is
built out of BM25 rather than the two more obvious alternatives, and — the part most write-ups
leave out — how we can tell whether it is working at all.

- **The pieces:** [`features/common/retrieval/`](../features/common/retrieval) — `tokenizer.py`,
  `bm25.py`, `mcp_matcher.py`, and an eval fixture set.
- **The decisions:** [ADR-0004](adr/0004-mcp-tool-index.md) introduced the tool index;
  [ADR-0012](adr/0012-bm25-retrieval-with-a-falsifiable-eval.md) replaced its keyword matcher.
- **The releases:** [`0.47.0-retrieval-that-can-fail.md`](changelog/0.47.0-retrieval-that-can-fail.md)
  and [`0.47.0-retrieval-tells-you-what-it-did.md`](changelog/0.47.0-retrieval-tells-you-what-it-did.md).

---

## 1. The problem

A project that connects a handful of MCP servers can easily reach a hundred tools. In this
repository's own index there are **98 tools**, spread very unevenly across 9 configured
sources — four of them carry all 98 (41, 30, 24 and 3), and five carry none at all. Each one
carries a name, a
description, and a schema; all of it is loaded whether or not the conversation will ever touch
it. The same pressure applies to skills, where hosts have started shipping explicit budgets — a
listing that overflows gets silently truncated rather than prioritised.

The naive fixes both fail in interesting ways:

- **Show everything.** Predictable, and the reason context budgets get eaten by tools nobody
  calls.
- **Show nothing and let the agent ask.** Cheap, but the agent can only ask for what it knows
  exists.

Retrieval is the third option: keep the catalogue on disk, and put a small, ranked slice of it in
front of the model when the turn looks like it needs one. The interesting engineering is not the
ranking — BM25 is fifty-year-old arithmetic — it is **knowing when to say nothing**, and being
able to prove afterwards which of those silences were correct.

## 2. Architecture

```mermaid
flowchart LR
    subgraph project["The project"]
        idx[".ai-badger/mcp-tools.json<br/>98 tools · 4 sources that carry any"]
    end

    subgraph retrieval["features/common/retrieval/"]
        tok["tokenizer.py<br/>fold · stopwords · split"]
        bm["bm25.py<br/>generic ranking<br/>knows nothing about tools"]
        mm["mcp_matcher.py<br/>field weights · coverage gate"]
    end

    subgraph hook["features/common/hooks/ai_badger_hooks.py"]
        enrich["pre_llm_inject_context"]
        rec["_record_retrieval"]
    end

    subgraph obs["Observability"]
        dl["debug_log.py"]
        audit["~/.ai-badger/debug/audit.jsonl"]
        beh["call-behaviorist<br/>tail · analyze"]
    end

    idx --> mm
    tok --> mm
    bm --> mm
    enrich -- "user's message" --> mm
    mm -- "top 3, or nothing" --> enrich
    enrich -- "hint prepended to the turn" --> agent(["The agent"])
    enrich --> rec --> dl --> audit --> beh

    style bm fill:#eef,stroke:#557
    style mm fill:#efe,stroke:#575
```

Two boundaries in that picture are load-bearing.

**`bm25.py` knows nothing about MCP tools.** It takes a mapping of document id → weighted
term-frequency `Counter` and returns scores. That is the whole interface. Anything with fields
and an id — tools today, skills next — can be ranked by it without the ranker growing a special
case.

**The hook only calls; it does not score.** `ai_badger_hooks.py` loads the matcher lazily by
path and degrades to "no recommendations" when it is missing, which is what lets a project
scaffolded by an older version keep working instead of crashing on an import.

## 3. One query, end to end

```mermaid
flowchart TD
    A["Turn begins<br/>user's message"] --> B{"index on disk?"}
    B -- no --> E1["event: absent"]
    B -- yes --> F["fuse each tool into one document<br/>name ×3 · tags ×2 · intent ×1"]
    F --> C["tokenize the query"]
    C --> D{"any usable terms?"}
    D -- no --> E2["event: no_terms<br/>nothing was scored at all"]
    D -- yes --> G["BM25 rank all 98"]
    G --> H{"coverage ≥ 0.20<br/>and ≥1 matched term?"}
    H -- no --> E3["event: gate<br/>scored, and deliberately silent"]
    H -- yes --> I["take top 3"]
    I --> J["prepend<br/>'[ai-badger] Relevant MCP tools: …'"]
    J --> E4["event: hit"]

    style E1 fill:#fee,stroke:#a55
    style E2 fill:#ffe,stroke:#aa5
    style E3 fill:#eef,stroke:#55a
    style E4 fill:#efe,stroke:#5a5
```

Four terminal states, four distinct records. That is not bookkeeping pedantry — see §6.

### Tokenizing

`tokenize()` lowercases, splits on non-alphanumerics, drops 109 function words and any token
under two characters, then folds a small set of suffixes (`ies → y`, then `ing|ed|es|s` when at
least three characters remain).

The split matters more than the folding. The matcher this replaced tested `keyword in query` —
substring containment — so the tag `ts` matched the word "tests", and `go` matched "going",
"category" and "algorithm". Splitting first makes token identity exact, and that single change
removed a whole class of confident wrong answers.

### Fusing fields

Each tool becomes **one** document rather than three, with its fields folded together at
different weights:

```python
documents[full_name] = fuse_document([
    (tokenize(full_name.replace(":", " ")), NAME_WEIGHT),    # 3.0
    (tokenize(" ".join(tags)),             TAGS_WEIGHT),     # 2.0
    (tokenize(intent),                     INTENT_WEIGHT),   # 1.0
])
```

A token from the tool's own name contributes 3 to the term count instead of 1. This is a
deliberately cheap approximation of BM25F, which would score each field as its own sub-document
with its own length normalisation. The approximation is chosen on corpus shape: these documents
have a median of **nine** distinct tokens and an `intent` a median of **six**. There is
essentially nothing to length-normalise, so the machinery BM25F adds has almost no signal to
work with here. That is an argument from the corpus, not a measurement — we have not run a
controlled BM25F comparison on this index, and this document does not claim one.

Curated `tags` were kept, not thrown away. They stopped being a lookup key and became a weighted
field — which means the human curation still pays, but a query that misses every tag can still
find the tool through its name or intent.

### Ranking

Textbook BM25 with `k1 = 1.2`, `b = 0.75`:

$$\text{idf}(t) = \log\left(1 + \frac{N - \text{df}(t) + 0.5}{\text{df}(t) + 0.5}\right)$$

Ties break deterministically on `(-score, -coverage, doc_id)`, so the same query against the
same index always produces the same list — a property tests depend on and users never notice
until it is absent.

## 4. The gate is coverage, not score

This is the part worth stealing for other systems.

The obvious way to decide "is this good enough to show?" is a score threshold. It does not
survive contact with a second corpus, because BM25 scores are not comparable across corpora of
different size: `idf` depends on `N`, so the same query against 13 documents and against 98
produces different absolute numbers for an equally good match. A threshold tuned on one is
meaningless on the other.

So the gate is a ratio instead:

$$\text{coverage} = \frac{\sum \text{idf}(\text{matched terms})}{\sum \text{idf}(\text{all query terms})}$$

"What fraction of this query's *information* did the best document actually account for?" — a
number between 0 and 1, on the same scale whatever the corpus size. A document clears the gate at
**0.20**. The code also requires at least one matched term, which is worth flagging as
decoration rather than a safeguard: coverage is a sum over matched terms, so it is provably 0
when nothing matched, and the threshold already excludes that case.

It emphatically does **not** stop a single term from carrying a match on its own. All four false
fires in our eval set are single-term matches, and they are the kind of thing a reader should see
rather than take on trust:

| Query that should return nothing | What fired | Terms matched |
|---|---|---|
| "write a poem about autumn" | `rider:apply_patch`, `rider:replace_text_in_file`, `rider:create_new_file` | 1 — *write* |
| "how many days until new year" | `rider:create_new_file` | 1 — *new* |
| "scaffold this repo" | `code-review-graph:list_repos_tool` | 1 — *repo* |
| "start task 12" | `code-review-graph:get_minimal_context_tool` | 1 — *task* |

A rare enough term clears a 0.20 coverage bar by itself, and "write" against a corpus of
file-editing tools is exactly that. This is the layer's most visible weakness.

Two further caveats, measured rather than assumed:

- **0.20 is a ceiling, not a comfortable setting.** It is the highest value at which
  zero-result-on-positives stays at 0 for our fixture set. On this 98-tool corpus the margin to
  the first failure is **0.0089** — the tightest true positive and a false fire sit at the same
  coverage to four decimal places. Because `idf` depends on the corpus size `N`, that margin is a
  property of *this* index and not a constant; a smaller consumer index is a different
  measurement, and we have not made it.
- **No scalar threshold cleanly separates good from bad here.** Driving false fires to zero costs
  true positives. We chose to keep the positives and accept that some turns get a suggestion they
  did not need.

Also worth knowing: field weights **cannot** change the false-fire rate, and this is structural
rather than empirical. Coverage is a ratio of `idf` sums; `idf` depends only on document
frequency; and `fuse_document` scales term counts without ever making a present term absent or an
absent term present. Sweeping all 343 combinations of `{0.5, 1, 1.5, 2, 3, 4, 5}` across the three
field weights leaves `false_fire` at exactly 0.2667 in every one, as the algebra says it must.

The one thing that *does* move it is changing which fields exist at all: dropping `tags`
entirely takes false fire from 0.267 to 0.200, because it removes terms from the corpus rather
than reweighting them. Knobs in the interior are theatre; the field set is not.

## 5. Falsifiability

The matcher ships with [`eval/mcp_queries.jsonl`](../features/common/retrieval/eval/mcp_queries.jsonl):
**58 fixtures — 43 queries with an expected tool, 15 that must return nothing.** A test runs them
against the repository's real index on every suite run, so a change that improves top-1 by
wrecking silence fails immediately.

Current standing, and we publish the unflattering ones on purpose:

| Metric | Value |
|---|---|
| recall@3 | 1.000 |
| recall@1 | 0.907 |
| false fire on negatives | 0.267 |
| coverage margin at the threshold | 0.0089 |

The fixture set is **saturated**: recall@3 is already 1.000, so no reranking technique can
improve it, and the remaining top-1 headroom is four queries out of 43.

It is also biased, in a way worth stating plainly because every hand-written eval set has this
problem. Mean token overlap between a query and the tool it is supposed to find is **0.781**, and
40 of 43 fixtures sit at 0.50 or above: the fixtures are written in the vocabulary of the
documents they are meant to find, by the same person who wrote the documents. A retrieval system
scored only against such a set is being asked the easy version of the question.

Two conclusions follow, and they point in opposite directions:

1. Further matcher tuning is not worth doing against these fixtures. With 39 of 43 correct at
   rank 1, the Wilson 95% interval is [0.784, 0.963] — wide enough to swallow any tuning gain
   whole. Improvements smaller than the measurement error are not improvements.
2. Harder fixtures — paraphrases with zero lexical overlap, user-voice queries, near-duplicate
   tools — would tell us something the current set cannot. That work is tracked, and it is
   deliberately *not* framed as "improve the matcher", because we do not yet know that the
   matcher is what is wrong.

## 6. Telemetry, and why silence needs more than one name

A retrieval layer that recommends nothing looks identical, from the outside, to one that is not
running. This is the failure mode that hides itself: everything appears fine, forever.

So every terminal state writes a record under the `ai_badger_hooks/mcp_retrieval` component:

| Event | Means | The mistake it prevents |
|---|---|---|
| `hit` | Something cleared the gate and was recommended | — |
| `gate` | Everything was scored; nothing cleared the threshold | Reading a correct, frequent silence as a fault |
| `no_terms` | The query tokenized to nothing, so **no candidate was ever compared to the threshold** | Reporting a tokenizer miss as a threshold miss — misattributing the exact failure the telemetry exists to count |
| `absent` | There is no index to search | Reading "no index" as "no match" |
| `legacy` | There *is* an index, in the pre-0.48.0 YAML format this path no longer reads | Reading "not migrated yet" as "never had one" |

Two more events, `known` and `unknown`, share the same component name: they come from a separate
after-the-fact check of whether a tool the agent actually called was one the index knew about.
Worth knowing before you tail the log and wonder where the extra names came from.

`legacy` is the newest of these and arrived the way the others did — from someone noticing a
silence with two meanings. Moving the index from YAML to JSON in 0.48.0 made the reader
JSON-only, which quietly gave `absent` a second sense: "no index" and "an index I no longer
read" became the same record. The rule that produced `gate` and `no_terms` produced this one too.

The `gate`/`no_terms` split was not designed in; it came out of reviewing the first version, where
a query that produced no terms was recorded as `gate` with a threshold field attached — a record
that asserted a comparison which never happened.

A `gate` record carries the query, the extracted terms, the candidate count, the top three scored
candidates as `name:score:coverage`, and the threshold in force — so a later threshold change is
attributable rather than mysterious. A `no_terms` record carries neither the threshold nor any
candidates, and the reason is worth following: scoring needs query terms, and `no_terms` is
precisely the case where there are none. There is no "suppressed top scorer" to show. That is a
real difference from the keyword-map era this event was designed in, when a query could produce
no *tags* while still being perfectly rankable — under BM25, no terms means nothing was ever
scored, full stop.

```mermaid
sequenceDiagram
    participant U as User
    participant H as pre_llm_inject_context
    participant M as mcp_matcher
    participant D as debug_log
    participant A as audit.jsonl

    U->>H: message
    H->>H: load index
    H->>M: find_relevant_tools(query, index)
    M-->>H: [] or top 3
    alt debug logging enabled
        H->>M: rank everything, ungated
        M-->>H: all candidates incl. near-misses
        H->>D: hit | gate | no_terms | absent
        D->>A: one JSON line, <4096 bytes
    else disabled
        Note over H,D: nothing computed, nothing written
    end
    H-->>U: turn proceeds, with or without a hint
```

Note the `alt`. The near-miss scoring exists only for telemetry, and it is not cheap: to show you
the candidates that *didn't* make it, it rebuilds the corpus and re-ranks everything the gated
retrieval just ranked. An early version did that unconditionally. Measured over the 58 eval
queries on this index, the instrumented path costs **about 1.6× the retrieval alone** — paid on
every turn, to fill a log nobody had switched on. It is now behind the enabled check. An
observability feature that taxes the thing it observes gets switched off, and then observes
nothing.

### The query field, and the redaction flag

One field carries user content: `q`, the message that drove retrieval. It is indispensable —
it is how you diagnose a miss, and it is the raw material for new eval fixtures — and it is the
one field someone may not want on disk.

It is recorded by default. Setting `AI_BADGER_DEBUG_REDACT` drops **that field only** from every
record written afterwards, leaving the terms, scores, counts and outcome intact, so the log stays
useful for counting even when it can no longer be read for content.

The drop happens inside `log_event` at the point of writing, not in a post-processing pass. A
redacted record never contains the text at all, so there is nothing to scrub, nothing to leak
through a crash between write and scrub, and no window where a partially-processed log is more
revealing than a finished one. Redaction that runs after the write is a cleanup job pretending to
be a guarantee.

The log itself is user-level and `0600`, capped at 5000 records, and every record stays under
`PIPE_BUF` (4096 bytes) so concurrent appends from several hooks cannot interleave. That budget
is why the keys are single letters, with the legend in `debug_log.KEY_NAMES` rather than repeated
on every line.

## 7. What this has cost, and what it has taught

The honest summary of the first two releases of this layer:

**The parts that worked.** Replacing substring containment with tokenized BM25 removed a class of
confidently-wrong matches. Making the gate a coverage ratio made the threshold portable across
corpus sizes. Shipping an eval fixture set meant the next change to the matcher has to argue with
data rather than with taste.

**The part that did not — and still does not.** This runs nowhere on Claude Code. Debug logging
is what surfaced it — **501 records, zero of them `mcp_retrieval`.** A feature implemented,
tested, documented and released, that has never executed a single query on the host this project
is distributed as a plugin for.

The cause has narrowed but not closed. `mcp_matcher.py`, `bm25.py` and `tokenizer.py` *are* now
copied into the scaffolded hooks directory — that half was fixed in passing by the 0.48.0 index
migration. What remains is the registration: `context-enrichment` in `hooks-manifest.json`
declares an agent entry for `hermes` and for nothing else, so on Claude Code the code is present,
importable, correct, and never called.

**That gap is open as of this writing**, tracked as issue #147. Everything above describes a
mechanism that is real and correct and, on one of its two target hosts, unreached. It would be
easy to write this section in the past tense and let a reader assume the discovery implies a
fix. It does not yet.

That is the same defect shape three times over in this repository's history: a component that is
built, covered by tests, copied into place by the scaffolder, and **registered nowhere**. Tests
pass because they call the code directly. The scaffold looks right because the file is there. The
only thing missing is the line that causes it to run, and nothing in the pipeline was watching
for that.

The generalisable lesson is not "write more tests". It is that **shipped and running are
different claims, and only one of them was ever being checked.** The telemetry above exists
because we could not answer the second question, and the first time we could answer it, the
answer was no.

---

## Reading further

- [ADR-0012](adr/0012-bm25-retrieval-with-a-falsifiable-eval.md) — the decision, the sweep tables,
  and what was rejected.
- [ADR-0004](adr/0004-mcp-tool-index.md) — the index itself: why it exists and where it comes
  from. The curation commands, and what `status: removed` means, are in
  [`mcp-index/SKILL.md`](../features/common/skills/mcp-index/SKILL.md).
- [`call-behaviorist`](../features/common/skills/call-behaviorist/SKILL.md) — switching the log
  on, reading it, and producing a health report from it.
- [`framework-architecture.md`](framework-architecture.md) — where retrieval sits in the wider
  scaffolding model.
