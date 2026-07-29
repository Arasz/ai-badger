# ADR-0012 — BM25 retrieval for the MCP tool index, and an eval that can fail

**Date:** 2026-07-29
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude
**Supersedes:** [ADR-0004](0004-mcp-tool-index.md) — DD-2 (closed tag taxonomy) and DD-3
(YAML for hand-editability) are reversed below. DD-1, DD-4, DD-5 and DD-6 are unaffected. The
Alternatives section's rejection of embeddings (B) is re-affirmed, with evidence, not repeated
by citation.

## Context

`_extract_query_tags` in `features/common/hooks/ai_badger_hooks.py` matched ~70 hand-written
keywords against a query with `keyword in query` — a raw substring test. `_find_relevant_tools`
returned `[]` immediately whenever that produced no tags, before its own intent-word-overlap
scoring ever ran. Measured on 15 realistic queries against this repo's real
`.ai-badger/mcp-tools.yaml` (98 tools): **8 returned nothing** — `"commit and push"`,
`"refresh ai-badger"`, `"scaffold this repo"`, `"start task 12"`, `"take a screenshot of the
page"`, `"navigate the browser to a url"`, `"what's in the architecture overview"`, `"fill out
the signup form"` — and the substring test fired `typescript` inside *tests* and `log` inside
*login* (see the PR for the reproduction script and full output). Of those eight, **two**
(`"commit and push"`, `"refresh ai-badger"`) are genuinely outside the MCP corpus's domain and
stay negative under the new matcher too; **four** (the screenshot, browser-navigate,
architecture-overview, and signup-form queries) are real tools the old gate never reached because
it bailed out before intent-word overlap ever ran, and the new matcher recovers them cleanly. The
remaining **two** (`"scaffold this repo"`, `"start task 12"`) do not stay negative, but they also
aren't recoveries: the new matcher now fires on them, on the wrong tool
(`code-review-graph:list_repos_tool` and `code-review-graph:get_minimal_context_tool`
respectively) — a false-fire the coverage gate lets through on a single shared content word
(`repo`, `task`). "No longer silent" and "recovered" are not the same claim, and this ADR keeps
them distinct rather than letting the second borrow the first's credibility.

Two further things about ADR-0004 turned out not to hold up:

- **"100% accuracy on a 16-query spike suite"** (DD-6, References) cites
  `job-search-ai-assistant/scripts/spike_mcp_match.py` — a script in a different repo. It cannot
  be run from here and therefore cannot fail. A claim nothing can falsify is not evidence the
  matcher works; this ADR's own eval harness (below) exists to replace it with one that can.
- **"Observability: the post_tool_observer hook logs index hit/miss metrics"** (Consequences →
  Positive) describes `logger.debug("mcp_index_hit=...")` on a bare `logging.getLogger` with no
  configured handler in any shipped deployment shape. Nobody has ever read one of those lines.
  It was the *appearance* of observability, not observability.

## Decision

### 1. BM25 replaces the keyword/tag matcher (supersedes DD-2)

`features/common/retrieval/` — new, stdlib-only, no knowledge of skills or MCP tools:

- `tokenizer.py`: lowercase, split on `[^a-z0-9]+` (so hyphens split, `ai-badger` → `ai`,
  `badger`), drop tokens shorter than 2 chars, drop an ~80-word stoplist, fold `ies→y` then
  strip `ing|ed|es|s` when the remainder is ≥3 chars. Splitting on non-alphanumerics makes token
  identity **exact, not substring** — `"ts"` is a token and folding turns `"tests"` into `"test"`,
  so the two can never collide again. Same fix removes the `login`-contains-`log` failure.
- `bm25.py`: a generic `Bm25Corpus` over a fused per-document term-frequency map. `k1=1.2`,
  `b=0.75`, `idf(t) = log(1 + (N - df + 0.5)/(df + 0.5))`. `b` is what scores a 5-12-word MCP
  `intent` fairly against a longer document — the reason one implementation can serve both MCP
  tools now and a skill-description matcher later, if Phase 0 of the skill-index spec ever
  justifies building one.
- `mcp_matcher.py`: document construction (`name` weight 3.0, `tags` 2.0, `intent` 1.0 — existing
  tool `tags` are not discarded, they become a weighted field) and the coverage gate.

Existing tools' `tags` survive as a weighted field, not a filter. `mcp-tags.json` is unaffected
by this ADR — it remains the vocabulary `mcp-index validate` checks tags against, not the
matching mechanism (that was DD-2's actual claim, and it is what's being reversed).

### 2. The gate is coverage, not raw score

Measured on this corpus: the worst true-positive score and the best out-of-domain false-positive
score overlap, so no fixed score cutoff separates them. `coverage = Σ idf(matched query terms) /
Σ idf(all query terms)` is scale-free and comparable across queries of different length; emit the
top 3 (tie-break `(-score, -coverage, name)`, deterministic) above a threshold, requiring ≥1
matched term.

**The threshold is corpus-specific and was re-derived, not copied.** The skill-index spec's
`coverage >= 0.30` was measured on a 13-document corpus; this one has 98 tools, and IDF behaves
differently at that size. Sweeping thresholds against
`features/common/retrieval/eval/mcp_queries.jsonl` on the real index in this repo:

| threshold | recall@3 | top-1 | false-fire | zero-result-on-positive |
|---|---|---|---|---|
| 0.05 – 0.205 | 1.000 | 0.907 | 0.267 | 0/43 |
| 0.21 – 0.22 | 0.977 | 0.884 | 0.200 | 1/43 |
| 0.23 – 0.24 | 0.977 | 0.884 | 0.133 | 1/43 |
| 0.25 – 0.28 | 0.953 | 0.860 | 0.133 | 2/43 |
| 0.30 – 0.35 | 0.953 | 0.860–0.884 | 0.067 | 2/43 |
| 0.39 – 0.405 | 0.837 | 0.814 | 0.067 | 5/43 |

An earlier version of this table had a `0.40` row carrying the last line's numbers; re-run
independently, threshold `0.40` reproduces identically to `0.39` (both give 0.837/0.814/0.067,
5/43) — the row's numbers were real, but its label wasn't the whole story. The next break, to
0.814/0.814/0.067 at 6/43, does not arrive until ~0.41, past this sweep's granularity.

Zero-result-on-positive is treated as a hard constraint (it is the old matcher's defining bug),
so the threshold is chosen from the range that keeps it at 0. The 0.21–0.24 band already gets
false-fire under 0.15 (0.133) — better than this section used to claim was reachable — but at
the cost of exactly one zero-result positive, which is disqualifying under the hard constraint
above. **`DEFAULT_COVERAGE_THRESHOLD = 0.20`**, the highest value in `mcp_matcher.py` that still
keeps zero-result-on-positive at 0, is chosen instead. The margin between 0.20 and the 0.21 point
where that constraint first breaks is **0.009** — not the comfortable cushion "safety margin"
implies. The tightest true positive at this threshold, `"rename this variable everywhere it's
used"` (coverage 0.2089), and a false fire, `"how many days until new year"` (coverage 0.2089),
sit at the *same* coverage value to four decimal places; 0.20 separates them only because BM25
scores don't tie in the fifth digit, not because of any margin the two queries' content actually
supports. `mcp_matcher.py`'s own comment is corrected to match.

**A finding worth recording plainly: false-fire does not fall below ~0.13–0.27 anywhere
zero-result-on-positive stays at 0, on this fixture set.** Inspecting the false fires shows why —
short negative queries sharing exactly one content word with the corpus (`"scaffold this repo"`
↔ `repo`, `"start task 12"` ↔ `task`, `"write a poem about autumn"` ↔ the `write` *tag* itself)
get non-trivial coverage from that single term, because BM25's idf does not grow large enough
relative to a query's other, wholly-absent terms to suppress it. The skill-index spec names this
exact tradeoff (§3 Phase 3): *"Requiring ≥2 terms gives a clean negative sheet but loses three
legitimate short queries; recommendations are advisory, so favour recall."* This ADR makes the
same choice for the same reason, though at a different price on this corpus: requiring
`matched_terms >= 2` here measures at false-fire 0.000, recall 0.977, top-1 0.884, and exactly
one zero-result positive (the same `"rename this variable everywhere it's used"` query above,
whose only matched term is a single word) — not three lost queries, one. Favouring recall was
still the right call: that one query has a real, single-word-match answer that `>= 2` throws
away outright, and the corpus is small enough that a human or agent can absorb one occasional
irrelevant suggestion more easily than a real tool going permanently unfindable. The false-fire
bar below is therefore set from this corpus's own measurement, not copied from the skill-index
spec's 11%/15% figures — copying it would repeat exactly the mistake this ADR just corrected for
the coverage threshold itself.

### 3. The eval harness is the deliverable ADR-0004 never had

`features/common/retrieval/eval/mcp_queries.jsonl`: 58 fixtures (43 positive, 15 negative —
25.9%) against the real `.ai-badger/mcp-tools.yaml` in this repo, one JSON object per line,
`"expect": []` a first-class negative. `tests/test_mcp_retrieval_quality.py` runs under `pytest`
and gates four numbers, each set with margin around measured performance so the suite catches
regression rather than pinning a lucky run:

| metric | bar | measured |
|---|---|---|
| recall@3 | ≥ 0.90 | 1.000 |
| top-1 | ≥ 0.75 | 0.907 |
| false-fire on negatives | ≤ 0.30 | 0.267 |
| zero-result on positives | == 0 (hard fail) | 0/43 |

Plus determinism across two runs, and structural checks (every `expect` resolves to a real tool
in the index; negatives are ≥25% of the set). **The fixtures are author-written**, which biases
all four numbers upward — a matcher tuned against its own eval always looks better than it will
against unseen queries. This is stated here as a limitation of the measurement, not hidden.

This harness — runnable, in this repo, under `pytest --check`-equivalent CI — is what
ADR-0004's 16-query spike suite was not, and directly answers "does the MCP index work" instead
of asserting it.

### 4. YAML is reversed (supersedes DD-3): JSON is now this project's answer

DD-3 chose YAML for one reason: hand-editability, so a human or agent could co-author
`mcp-tools.yaml` alongside the CLI. **That premise no longer holds — the person who owns this
decision has withdrawn it: "we don't need hand editability."** With it gone there is no
remaining argument for YAML, and the costs were already on record:

- `features/common/hooks/ai_badger_hooks.py`'s `import yaml` was the only unguarded third-party
  import in the tree (CONTRIBUTING.md's own rule against exactly this). If pyyaml were absent
  from a Hermes plugin environment, the whole module failed to import and `register()` never
  ran — taking the drift notice, commit reminder, session hints, and MCP recommendations down
  **together, silently**. Filed as issue #136.
- `tooling/validate.py:58` exempts `mcp-tools.schema.json` from `--all` *because the instance is
  YAML*. Five servers with `tools: {}` violate the schema's own `minProperties: 1` unnoticed.
- A JSON instance can be validated at `mcp_index.py`'s `_write_index` — the single choke point
  all four write commands (`init`, `update`, `tag`, `intent`) already pass through — so a
  malformed write is refused instead of persisted.

**Decision: `.ai-badger/mcp-tools.json` is the format going forward.** A reversal made because
its premise no longer holds is a stronger record than one made because it turned out expensive,
which is why this section leads with the withdrawal rather than the cost list.

**Scope decision for this PR: the import is guarded here too; the format migration is deferred.**
`import yaml` in `ai_badger_hooks.py` is changed to a guarded `try/except ImportError` (matching
the existing `debug_log` pattern) as part of this PR's own changes to that file, so an absent
pyyaml degrades `_load_mcp_index` to `None` instead of taking the module down. The guard for
issue #136 itself shipped separately, as its own dedicated PR (**#142**), which closes #136 on
the import guard specifically — this PR's guard lands the same fix incidentally, because it
already touches the same import. The larger migration — a dual-format reader so an existing
project's `mcp-tools.yaml` is never stranded, `mcp_index.py`'s `_write_index` emitting JSON, a
`mcp-index migrate` command, and `tooling/validate.py`'s exemption removed — is **not** done
here: this PR's primary deliverable is the matcher and its eval harness, and folding a format
migration into it would risk both. This is recorded as a decided-but-not-yet-implemented gap, not
a silent omission: **issue #145** tracks the JSON migration specifically, filed fresh rather than
retitling #136 — #136 is scoped to the import guard and is closed by #142, not by this decision —
and whoever picks up the migration should read this section first.

### 5. Embeddings remain rejected (re-affirms B, with evidence)

ADR-0004 §B rejected embeddings for v1 pending evidence that lexical matching was insufficient.
That evidence now exists, in the other direction: pure lexical BM25, stdlib-only, clears every
bar in the table above on a 98-tool corpus. `gates/deps_guard.py` also still bars a third runtime
dependency mechanically, independent of this measurement. Both hold, so B stands — re-affirmed
by what was actually measured here, not by re-citing the original argument.

## Consequences

### Positive

- Every query in this corpus that has a real answer gets one; the four previously-silent
  MCP-relevant queries now return their tool (see the PR body for exact before/after).
- The false-fire vs. zero-result tradeoff is a measured, named number instead of an invisible
  gate.
- The eval harness can fail — in CI, on this repo, today.
- `import yaml` no longer takes four hooks down together when pyyaml is absent.

### Negative

- False-fire (26.7%) is higher than the skill-index spec's own figure on a different corpus
  (11%). This is disclosed above as a real, measured property of short queries against a 98-tool
  lexical corpus, not hidden behind a borrowed number.
- The JSON migration is decided but not implemented (tracked in #145); `mcp-tools.yaml` and its
  unexempted-in-name YAML validation gap persist until that follow-up lands.
- Fixtures are author-written, biasing all four eval numbers upward until real usage (via the
  debug log, per the skill-index spec's Phase 0) supplies independent queries.

## References

- `features/common/retrieval/eval/mcp_queries.jsonl` — the fixture set
- `tests/test_mcp_retrieval_quality.py` — the four gated metrics
- Issue #136 — `import yaml` unguarded; also guarded here, closed by the dedicated #142
- Issue #145 — the JSON migration this ADR decides and defers, not yet implemented
- The skill discovery/measurement/retrieval-index spec (§2 D5, §3 Phase 3) supplied to this PR's
  author — not tracked in this repo, but the source of the threshold-re-derivation and
  false-fire/recall tradeoff reasoning this ADR follows
