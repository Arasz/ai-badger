# ADR-0031 — Per-prompt memory context through the ai-raccoon proxy, planned by an OpenRouter pipeline

**Date:** 2026-09-28
**Status:** Accepted (2026-09-28, targeting 0.178.0 — see `docs/changelog/0.178.0-per-prompt-memory-context.md`).
Amended 2026-09-28 after the implementation review: Hermes stage limits (D1.6), the Hermes memo
removed, failure reporting (D1.7) and the "Parity with pi" section.
**Author:** Rafał Araszkiewicz (Arasz) with Claude (task `aib-ai-raccoon-prompt-rag-hook`, lane Q0)
**Scope:** `features/common/skills/ai-raccoon-memory/scripts/{memory_context,openrouter_client,query_pipeline,memory_context_hook}.py`
and their Claude/Copilot/Hermes hook wiring (`features/common/hooks/hooks.json`,
`features/common/hooks/hooks-manifest.json`, `features/common/hooks/ai_badger_hooks.py`,
`features/copilot/adjustments/adjust_hooks.py`).
**Supersedes:** Nothing.

## Context

Every user prompt on Claude Code, Copilot CLI and Hermes CLI sessions is a chance to enrich the
model's context from this project's ai-raccoon memory bank before the model answers — the same job
pi's `mem-based-rag` and `query-pipeline` extensions already do for pi sessions. ai-badger has no
per-prompt memory hook of its own; porting one raises two questions this ADR answers: how the hook
reaches ai-raccoon at all, and whether one `memory_search` call per prompt is enough or whether it
is worth planning several.

**Why not talk to ai-raccoon directly.** ai-raccoon's own transport ADR
(`ai-raccoon` ADR-0106, "Attach-or-start again, proven by a per-root identity key") closed F70 — a
squatter holding the configured loopback port and echoing back `jsonrpc` receiving the data root's
token byte for byte — by making every token-bearing request prove the listener's identity first
with an ECDSA challenge the listener alone can answer. ADR-0106 states the resulting invariant in
so many words: "to any listener that has not proven identity: **zero secret bytes**." A hook that
opened its own connection and carried the token would have to perform that proof itself. Python's
standard library has no ECDSA verification, and this project's own "use platform security APIs"
invariant (`.ai-badger/invariants/no-hand-rolled-crypto.md`) forbids hand-rolling one. The
`ai-raccoon` binary already performs the proof, as a proxy, on every launch. Routing every search
through it — instead of reimplementing the proof or skipping it — means the hook never touches the
token at all.

**Why plan more than one search.** A pi research spike measured that a delegate-planned multi-query
retrieval pass, scored by the Jev model and merged document-aware, beat a single full-prompt search
on every one of four test prompts: on the 0–3 Jev scale, path-deduped top-5 scores rose from
0.98→1.49, 0.45→1.94, 0.11→1.27 and 0.93→1.85
(`pi-badger-integration` `docs/work/2026-09-21-delegated-multi-query-rag-with-jev-selection.md`,
finding F8, MEASURED). The same doc's F9 shows the win is mostly retrieval, not just reranking:
scoring the single-search baseline's own pool with Jev closed only part of the gap. pi shipped this
as `extensions/query-pipeline` (`planner.ts`, `jev-client.ts`, `merge.ts`, `pipeline.ts`), calling a
model through pi's own in-process `ModelRegistry` for the planner and Jev over OpenRouter's
`/api/alpha/decisions`. ai-badger's hook has no such in-process model registry to call — it is a
one-shot external process per prompt, with a wall-clock deadline set by the host (Claude's
`UserPromptSubmit` hooks default to a 30 s timeout absent an explicit value; Copilot CLI's
`userPromptSubmitted` command hooks default `timeoutSec` to 30 s; Hermes abandons a `pre_llm_call`
callback after 30 s by default, `hermes_cli/plugins_dispatch.py:153`) —
so the pipeline has to be ported as direct HTTP calls the hook makes and owns end to end, not as a
call into a host's model registry.

**Constraints from being a hook, not a long-lived session.** Every invocation spawns fresh, has no
warm connection to reuse across prompts (Hermes included: it runs the hook once per user turn and
nothing is cached between turns), and must exit 0 whatever happens. An expected miss (no project,
no key, no hits, a dead proxy) is silent, and only a genuinely unexpected exception writes one log
line (D1.7). There is no UI to report progress to, unlike pi's TUI card. These constraints, not a
preference, are why this ADR's pipeline design carries no progress-reporting surface and folds pi's
several timeout knobs into one wall-clock `Budget` (§1.2 of the implementation plan).

**Capability spike.** Before committing this design to Copilot CLI, a P0 spike measured (not
assumed) which of two output shapes Copilot actually consumes: a flat `{"additionalContext": …}`
worked 3 of 3 runs against Copilot CLI 1.0.88; the Claude-style
`{"hookSpecificOutput": {...}}` envelope worked 0 of 3
(`docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md`, "Addendum (2026-09-28): P0 Copilot
capability spike"). This ADR's transport decision (D1) therefore branches the hook's output shape on
the payload it receives, not on a single hard-coded format.

## Decision

### D1 — Transport: one proxy process per hook run, never the token

1. **Spawn the bare `ai-raccoon` executable as a subprocess, `argv == [exe]`, once per hook run.**
   No `--transport stdio`, no shell, no arguments. Resolution is `PATH` first (`shutil.which`), then
   `~/.dotnet/tools/ai-raccoon` if executable, else nothing is spawned. The hook speaks newline-
   delimited JSON-RPC to the child's stdin/stdout: an `initialize` handshake, then one
   `tools/call memory_search` per planned (or single) query, over that one session — never a new
   process per query.
2. **One wall-clock `Budget` bounds the whole run**; every stage (session open, each search, the
   planner call, each Jev batch) draws a bounded child of it. A single-search run gets 5 s on
   every host; a pipeline run gets 90 s (pi's own total) on Claude and Copilot and 25 s under
   Hermes (D1.6). At the deadline, or on any error, the child is killed
   (`SIGKILL` the pid, then reaped — never the process group, so a serve the proxy itself started
   under `BackendLauncher` is not taken down) and the run either falls back to a single search or
   injects nothing. The hook always exits 0.
3. **Close gracefully before killing.** The child's stdin is closed first (so the proxy's own
   dispose path runs), with up to 0.5 s of grace before a forced kill — matching how the proxy
   itself expects to be told a caller is done.
4. **Default-on detection**: the hook runs whenever `.ai-badger/project-id` resolves *and* the
   `ai-raccoon` executable resolves; no port variable, no separate opt-in flag. The literal
   `AI_BADGER_MEMORY_CONTEXT=0` is the one kill switch, checked before any spawn.
5. **Per-host output shape.** The entry picks the shape from the payload it receives, not from a
   fixed per-agent assumption: `hook_event_name == "UserPromptSubmit"` (Claude's documented common
   input field) selects the `hookSpecificOutput` envelope; every other payload (today, Copilot's
   `{sessionId, timestamp, cwd, prompt}`) gets the flat `{"additionalContext": …}` the P0 spike
   measured working. This is deliberately payload-shaped, not agent-shaped, because P0 found the two
   hosts already disagree on what they consume and a future third disagreement should not need a
   third hard-coded branch.
6. **Hermes gets its own stage limits, derived, not copied.** Hermes abandons a `pre_llm_call`
   callback after 30 s by default (`hermes_cli/plugins_dispatch.py:42-44,153`) and then drops
   the whole turn's injection, the parts other arms already produced included. Its arm passes
   `stage_limits(25)`: pi's planner, search and score limits scaled down so that a full planner,
   two full searches and the score stage fit in 25 s (about 7.1, 7.1 and 3.8 s). Lowering only
   the total, as the first implementation did, left a slow planner with no time to search. The
   arm does not move ahead of the message-bus arm, which consumes its messages before the
   memory search runs; a turn that overruns Hermes's timeout loses that delivery with the rest,
   and the 25 s limits exist to keep that a tail case.
7. **Failures are sorted, not all silenced.** `build()` treats `OSError` and subprocess errors
   (no proxy, a dead pipe, a timeout) as expected and returns None without a trace. Any other
   exception is a defect: it is still swallowed for the prompt, but handed once per process to the
   caller's recorder, which writes the exception type and location (never the prompt or the key)
   to `~/.ai-badger/hook-errors.log` on Claude and Copilot and to a Hermes warning under Hermes.
   A missing or unimportable `memory_context.py` beside the entry is logged the same way. The
   proxy child gets a copy of the environment without `OPENROUTER_API_KEY` or any
   `AI_BADGER_MEMORY_CONTEXT_*` variable, and `PATH` entries that are not absolute are never
   searched for the executable.

### D2 — Pipeline: port pi's planner+Jev pipeline over direct OpenRouter HTTP, single-search when there is no key

1. **Port, don't call back into a host.** `query_pipeline.py` re-implements pi's planner
   (`planner.ts`/`planner-call.ts`), Jev scoring client (`jev-client.ts`) and document-aware merge
   (`merge.ts`/`pipeline.ts`) as pure functions over injected `plan`/`search`/`score`/`budget`
   parameters — no import of the transport or network modules, so it is testable with fakes alone.
   `openrouter_client.py` is the one module that ever imports `urllib`, `http.client`, `ssl`,
   `socket` or `threading`, and the one surface that ever leaves the machine besides the ai-raccoon
   proxy itself.
2. **The pipeline runs only when a key is present**: `pipeline = AI_BADGER_MEMORY_CONTEXT_PIPELINE
   != "0" and OPENROUTER_API_KEY is set and every pipeline module loaded`. Any of those false means
   a single search on the gated prompt, a 5 s budget, and `query_pipeline.run()` is never called —
   a user with no key never pays the 90 s path or sends anything to OpenRouter (security MUST-2).
   This reads pi parity backwards on purpose: pi's own planner has no key requirement because it
   calls a host model registry, not OpenRouter directly, so "missing key → `no-model` inside the 90 s
   budget" never actually arose for pi and is not carried here.
3. **One proxy session serves every planned query.** The planner asks OpenRouter chat completions
   for 2–6 retrieval queries grouped by concept; each deduplicated query is searched once, in order,
   over the one `RaccoonSession` already open; hits are pooled, pruned, scored by Jev
   (`/api/alpha/decisions`) and merged into five document-aware slots exactly as pi's `mergeSelect`
   does. Every stage draws a child `Budget`, so a slow planner cannot eat the search window and a
   slow Jev batch cannot eat the run's tail (§9.2 of the implementation plan carries pi's own
   arithmetic forward unchanged).
4. **A Jev failure is not a fallback trigger.** Following pi's own source rather than a stricter
   reading of the brief: if scoring raises, times out, or returns every score `null`, the run still
   reports `("pipeline", "ok")`, merged by ai-raccoon's own server rank instead of Jev's score
   (owner ruling O-6). Only a planner failure, an empty deduplicated query set, or an empty candidate
   pool trigger the one-shot single-search fallback.
5. **Network hygiene is symmetric with the proxy's own trust model.** Every OpenRouter call carries
   the key from the environment only (never logged, never in an exception message), goes through one
   opener with no environment proxy and no redirect-following, and is bounded end to end: a
   resolver-thread DNS deadline (at most one live resolver thread per host), a per-address connect
   timeout recomputed from the remaining share, one TLS-handshake deadline, and a watchdog timer that
   covers every byte read afterward. A dripping or hung OpenRouter endpoint can therefore never hold
   the hook past its stage's share, matching the same "never outlive the budget" contract the proxy
   transport already gives D1.
6. **The model resolver is loaded, not copied.** Rather than vendor a second copy of
   `model_groups.py`'s tier-resolution rules, `memory_context.py` loads the project's one copy by a
   layout-exact path (the Claude scaffold's `.ai-badger/skills/task/scripts/model_groups.py`, or the
   flat Hermes plugin layout) and passes it the project's own `model-groups.json` registry. A project
   that declined the `task` skill gets `no-model` on both agents alike, not divergent behavior
   between Claude and Hermes.
7. **The test seam is a sentinel, not a flag.** Tests reach a loopback OpenRouter fake only when the
   supplied key starts with `sk-test-` and the base URL parses to `http://127.0.0.1:<port>` exactly —
   a real OpenRouter key can never be redirected to the test seam, and an invalid combination refuses
   outright rather than silently falling back to production (security NOTE-4, O8).

## Consequences

**Positive**
- Better recall than today's single search, on pi's own measured evidence (F8/F9 above), without
  reimplementing an identity proof this project has no crypto primitive for.
- The hook never holds the ai-raccoon token; every request that could leak it goes through the
  proxy, which already proved its own identity.
- Pipeline and single-search share one output format (`format_block`/`toMemoryContext` parity), so
  downstream consumers of the injected context see no difference between the two paths.

**Negative**
- Latency: roughly 0.17 s spawn plus ~1.3 s per single search; with the pipeline, 10–20 s typical
  and up to 90 s worst case per gated prompt (INFERRED from measured parts; the P4 integration
  package measures both paths against the real binaries).
- The proxy may start its own `ai-raccoon serve` when none is running, paying that cold-start cost
  inside the hook's own budget share.
- With the pipeline on, every enriched prompt's gated text, and every planned query, lands in
  ai-raccoon's own search log; and for up to 48 pooled hits, their path, kind and a 500-character
  excerpt of memory *and source code* go to OpenRouter. This is stated in SKILL.md and the changelog
  in those words, not left implicit.
- A per-prompt OpenRouter cost is paid whenever the pipeline runs, on the project's own key.
- A project's `model-groups.json` chooses which `openrouter/` model the planner calls, billed to the
  user's key (R-g in the implementation plan) — bounded by one call per prompt, a 15 s share, and an
  `ID_RE`-validated model id, but not capped in price.
- A resolver thread per uncached DNS lookup, and a watchdog timer per HTTP call, are threads this
  hook creates and must reap; at most one resolver thread is live per host per process.
- Hermes blocks the calling turn for up to its 25 s total plus the proxy reap (no async surface to
  hand the wait to).

**Neutral**
- Three new modules plus one thin per-agent entry, versus the six-module/two-ADR shape an earlier
  revision of the plan considered (binding 3; feasibility F4/F10) — reviewed down to this shape
  because splitting further added rows, not behavior.
- Four new rows in Hermes's `SHARED_SKILL_MODULES`/`SHARED_SKILL_FILES` tables, and one new resolver
  constant read by both the sibling loader and its own derive test.

## Parity with pi

The block is byte-identical to pi's `toMemoryContext` output for every hit list in which no
`path`, `sourceFile` or string `ranking` contains a line break or tab, no snippet contains U+0085,
every `ranking` is a number, string, boolean, `null` or absent, no path exceeds 300 characters, no
string rank exceeds 32, and no snippet or query is cut inside a non-BMP character. The accepted
divergences outside that:

- a path or rank with a line break or tab: collapsed to one space here, raw in pi (O-2);
- a snippet with U+0085: collapsed here, kept in pi;
- a `ranking` of another type (list, object): `?` here, JS `String()` in pi;
- truncation counts code points, not UTF-16 units;
- a path is cut at 300 characters and a rank at 32, with a trailing `…`; pi caps neither, so a
  memory written with a huge path could otherwise inflate the block without bound;
- `server_rank` parses numeric strings with a decimal-literal regex, not JS `Number()`;
- Jev batches the pool in runner order (pi's `capPool` re-sort differs only for numeric-string
  ranks);
- `parse_plan` returns `no-json-object` for planner text over 64 KiB, and never decodes an object
  that opens more than 8 braces deep (pi parses any length and depth); this bounds the parse on
  pathological text to 8 decodes.

## Alternatives rejected

- **Direct HTTP to ai-raccoon with the token (the F70-era shape).** Rejected outright: the token
  would have to leave the hook process, and the hook would have to either skip ADR-0106's identity
  proof (reopening F70) or reimplement ECDSA verification, which stdlib does not provide and this
  project's own invariants forbid hand-rolling.
- **`--transport stdio`.** ai-raccoon's own roadmap slates this transport for removal; building a new
  ai-badger feature on top of it would ship an integration against a mode already scheduled to
  disappear.
- **A persistent proxy connection per Hermes process**, reused across turns instead of reopened per
  prompt. Deferred: it would remove the ~0.17 s spawn cost on the Hermes path specifically, but adds
  a connection-lifecycle problem (when does it close, what happens if the proxy restarts underneath
  it) that a one-shot-per-prompt model does not have to answer at all.
- **Process-group kill** instead of pid-only (O-1). Rejected: `BackendLauncher.Start` runs the proxy
  without a new process group, so a serve the proxy started shares the hook's group; killing the
  group would kill that shared serve along with the hook's own child.
- **Spawning pi itself as the planner call.** Ruled out: it would make ai-badger's hook depend on a
  second CLI being installed and configured, for a call this ADR can make directly over HTTP.
- **Parallel searches** instead of one child at a time. Rejected for parity: pi's own runner searches
  sequentially over one session; running several ai-raccoon searches concurrently over the same
  child process is not a protocol this design (or pi's) supports, and one session per hook run is
  already the design's own constraint (D1.1).
- **Dropping Jev and merging by server rank alone.** Rejected: F9 above shows reranking alone closes
  only part of the recall gap; the win is mostly in what gets retrieved, but Jev's scoring still adds
  a measurable improvement over server rank on its own (F9's baseline-rerank row still trails the
  full pipeline on every prompt).
- **Per-socket timeouts without a watchdog.** Rejected: a byte-at-a-time drip attack (or a merely slow
  server) defeats a connect/read timeout that only fires between reads; a watchdog timer covering the
  whole stage share is required to bound total wall time regardless of how the bytes arrive.
- **Leaving DNS resolution unbounded** (an early binding-2 draft's exception for it). Rejected: a
  resolver thread with its own deadline, capped at one live thread per host, closes that gap without
  reintroducing the parallel-searches problem above.
- **A vendored copy of `model_groups.py`, or reading `groups["medium"][0]["id"]` directly** instead
  of loading the one canonical module by path. Rejected under this project's own "derive the list, or
  delete it" invariant: either option re-implements or duplicates rules that already exist in one
  place.
- **Four pipeline modules instead of one.** An earlier revision split planner, Jev, merge and the
  runner into separate files; folded into one `query_pipeline.py` because the split added rows to
  track without changing any behavior (binding 3).

## References

- Implementation plan: `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-plan.md` (rev 4), §1, §2, §9,
  §13
- Research record: `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md`, Research D lane
  report and the P0/Q0.3 addenda
- `ai-raccoon` ADR-0106 — "Attach-or-start again, proven by a per-root identity key" (F70, F49, F39;
  the zero-secret-bytes invariant)
- pi research: `pi-badger-integration` `docs/work/2026-09-21-delegated-multi-query-rag-with-jev-selection.md`
  (F8, F9 — measured recall improvement) and `docs/work/2026-09-22-query-pipeline-v1-research.md`
- pi source (frozen at commit `ee5f1c6e689b988a8924781b3acb5961ce40c326`, unchanged through
  `161673c0` for `extensions/query-pipeline`, `extensions/mem-based-rag` and
  `tests/query-pipeline`): `extensions/query-pipeline/{planner,planner-call,jev-client,merge,pipeline,types}.ts`,
  `extensions/mem-based-rag/{index,rag-core}.ts`
- This project's own invariants: `.ai-badger/invariants/no-hand-rolled-crypto.md`,
  `.ai-badger/invariants/derive-or-delete-the-list.md`, `.ai-badger/invariants/no-hardcoded-secrets.md`
