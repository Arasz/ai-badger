# Implementation plan: aib-ai-raccoon-prompt-rag-hook (rev 3)

Rev 3 replaces rev 2 in full. It keeps every rev-2 decision except where a pipeline ruling changes
it (each change is listed in §0), and fills the §9 slot with the query-pipeline port: plan →
dedupe queries → one `memory_search` per planned query over the one proxy session → Jev score →
document-aware merge, with pi's single-search fallback. The injected block is unchanged.

Worktree base `4d8ed33b` (main `4abf5ade` + research record; task branch head `c3199e97`),
`VERSION` 0.177.3. pi source commit for every golden: `ee5f1c6e689b988a8924781b3acb5961ce40c326`
(last commit touching both `extensions/mem-based-rag/` and `extensions/query-pipeline/`,
MEASURED this session with `git log -1`). Paths are repo-relative unless absolute. Grades: READ
(source opened this session or by a review lane and re-checked), MEASURED (command run), INFERRED,
UNVERIFIED.

All gate commands run from the task worktree root with the main checkout's interpreter:

```
PY=/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3
```

**The five things an implementer must not get wrong** (repeated in §12):
1. The hook spawns exactly one process per run: the `ai-raccoon` executable, `argv == [exe]`, no
   shell, never pi. It never reads or sends the ai-raccoon token. Every planned query's search goes
   over that one session.
2. One wall-clock `Budget` bounds the whole run; every stage (open, planner, each search, each Jev
   attempt, close) draws a child of it. At the deadline or on any error the child is killed and
   reaped, the run takes pi's fallback or injects nothing, and the hook exits 0.
3. OpenRouter calls: `OPENROUTER_API_KEY` from the environment only, never logged; one opener that
   honours no proxy, refuses every redirect and verifies TLS with the default context; a watchdog
   holds every call inside its stage share even against a dripping server.
4. No test reaches the real `ai-raccoon` or the real network: the real binary is on this machine's
   PATH (`which -a ai-raccoon` → `/Users/arasz/.dotnet/tools/ai-raccoon`, MEASURED), so every test
   sets PATH to a temp dir holding the fake; OpenRouter is a local fake on `127.0.0.1`; a connect
   guard refuses any other address (G4).
5. Every package ends green on pre-push: sync + index + self-scaffold (`--no-install`) run at the
   end of every package that touches `features/`, and `VERSION` is bumped in the first one.

---

## 0. What rev 3 changes relative to rev 2

| Rev 2 | Rev 3 | Why |
|---|---|---|
| `BUDGET_SECONDS = 5.0`, hook `timeout` 10 | `SINGLE_BUDGET_SECONDS = 5.0` (pipeline off) and `PIPELINE_TOTAL_SECONDS = 90.0` (pi `totalMs`); Claude `timeout` 100, Copilot branch A `timeoutSec` 100 | Owner: the budget rises to cover the pipeline; full wait accepted (§9.4) |
| Two new files | Six new files: `memory_context.py`, `memory_context_hook.py`, plus `openrouter_client.py`, `query_planner.py`, `jev_scoring.py`, `query_pipeline.py` | Parallel lanes and module-level tests (§9.1); "Simpler shape?" §12 weighs the one-file alternative |
| `build()`: open → one search | `build()`: open → `query_pipeline.run(...)` when the pipeline is on; rev-2 single search when `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0` or a pipeline sibling fails to load | §9.2 |
| One env switch | Adds `AI_BADGER_MEMORY_CONTEXT_PIPELINE` (`"0"` forces single-search), `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`, the read of `OPENROUTER_API_KEY`, and a test-only, loopback-only `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE` | §1.3, §9.6 |
| `RaccoonSession` usable until closed | A search that timed out after its request was fully written leaves the session usable (a late reply is skipped by id, pi parity); a partial write, oversize line, EOF or crash poisons it (later searches return `None` at once) | Many searches now share one session (T24, T25) |
| S1 allowed `urllib` anywhere | `urllib` only in `openrouter_client.py`; no `urlopen`/`install_opener` anywhere | §9.5 |
| Hermes `SHARED_SKILL_MODULES` +1 row | +6 rows: `memory_context.py`, the four pipeline modules, and `("task", "model_groups.py")` | Hermes loads every sibling from its plugin dir (§9.7) |
| O-1 open | **O-1 RESOLVED**: the orchestrator verified `BackendLauncher.cs:234-240` and accepts kill-pid-only | §10 |
| — | New owner questions O-6 (Jev failure fallback: the ruling's wording versus pi's source) and O-7 (default-on whenever the key is exported sends prompt text and memory excerpts to OpenRouter) | §10 |
| One ADR (0031) | Adds `docs/adr/0032-query-pipeline-over-openrouter-in-the-memory-context-hook.md` | New cross-cutting dependency (OpenRouter HTTP from a hook) |

---

## 1. Design summary

**What ships.** On every user prompt that passes a port of pi's `shouldEnrich` (without the
`/skill:` rules), the hook spawns the `ai-raccoon` proxy and performs the MCP handshake over
newline-delimited JSON-RPC on its stdin/stdout. With the pipeline on (the default), it asks an
OpenRouter model for 2–6 retrieval queries, runs one `memory_search` per deduplicated query over
that one session, scores the pooled hits with Jev, and keeps the best five by pi's document-aware
merge. With the pipeline off, or when the planner fails, it runs one search on the gated prompt
(pi's fallback). If hits survive pruning, a "Memory context" block equal to pi's default-mode
`toMemoryContext` output (parity defined in §1.5) is injected as additional context. The block
format is identical in both modes. The hook runs on Claude Code and Hermes. It runs on Copilot only
if the P0 spike shows Copilot consumes the output. It never runs on pi.

**Why the proxy (owner ruling, binding).** The proxy performs ai-raccoon's per-request ECDSA identity
proof before any token-bearing request (ai-raccoon ADR-0106, finding F70: a squatter on the loopback
port received the token byte for byte; invariant "to any listener that has not proven identity: zero
secret bytes"). Stdlib Python has no ECDSA verification, and the "use platform security APIs"
invariant forbids hand-rolling it. Through the proxy the hook never touches the token. The owner
accepts the spawn cost (~0.17 s measured by the owner) and that the proxy may start a serve when none
is running.

**Why OpenRouter over HTTP (owner ruling, binding).** The planner and Jev are direct `urllib` POSTs to
OpenRouter; there is no pi and no second process. §9 is the whole pipeline design.

**Placement.** `features/common/skills/ai-raccoon-memory/scripts/`. The skill is `scope: default`,
already owns the other ai-raccoon hooks (`memory_first_gate*_hook.py`, `memory_grade_hook.py`), and
already carries a vendored `badger_store.py` (READ). Declining the skill through `config.exclude`
removes the Claude wiring through the existing `declined_skill` path in
`skills/welcome-ai-badger/scripts/hook_wiring.py`; Hermes gets an explicit decline check (§1.3).

**Module split: six files.**

| File (new) | Contents |
|---|---|
| `memory_context.py` | *Pure section:* `CONTROL_WORDS`, `NOISE_WORDS` (35 words), `unique_long_words`, `should_enrich(prompt, min_chars=20, min_words=6) -> Decision`, `prune_hits`, `one_line`, `js_number`, `format_block(query, mem, code)`. *Budget:* `Budget` (§1.2). *Transport:* `find_executable(env, home)`, `RaccoonSession` (§1.1). *Orchestration:* `build(prompt, cwd, session_id, *, env=None, home=None, budget=None) -> str \| None` (order in §9.2). Loads the four pipeline siblings and the model resolver by path. |
| `memory_context_hook.py` | Claude (and, in branch A, Copilot) entry. stdin JSON (`prompt`; `session_id` or `sessionId`; `cwd`) → `build()` → exactly one line `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":block}}` or nothing. Loads `memory_context.py` by path under a distinctive `sys.modules` key (the `context_enrichment_hook.py:41-68` pattern). `guarded_main()` always exits 0 and routes only unexpected exceptions to `record_hook_failure` (pattern `context_enrichment_hook.py:169-199`), with the log path resolved at call time. The final write is wrapped so a closed stdout also exits 0 (security N5). |
| `openrouter_client.py` | The one HTTP surface: `api_key(env)`, `api_base(env)`, `post_json(url, body, key, budget) -> Reply`, the opener and the watchdog (§9.5). |
| `query_planner.py` | `DELEGATOR_PERSONA`, `PLANNER_ADDENDUM`, `PLANNER_USER_PREFIX`, `build_user_prompt`, `parse_plan`, `resolve_model`, `plan(...)` (§9.3). |
| `jev_scoring.py` | Constants, `build_score_question`, `parse_score_body`, `classify`, `score(...)` (§9.4). |
| `query_pipeline.py` | Stage limits, fallback-reason vocabulary, `dedupe_queries`, `server_rank`, `doc_key`, `merge_select`, `run(...)` (§9.2). |

Hermes gets no entry file: `ai_badger_hooks.pre_llm_inject_context` loads `memory_context.py`
through the existing `_load_sibling_module` and calls `build()` in-process.

Core, budget and transport stay one file (feasibility simpler shape; rev 1 C1). The pure-core
boundary is held by review and by the pure functions taking no env, home or session argument. The
pipeline modules take every effect (HTTP post, search, clock, budget) as a parameter; only
`memory_context.build()` wires real effects, so each pipeline module is testable alone.

### 1.1 Transport: `RaccoonSession` over the proxy

Mirrors pi's `RaccoonClient` (`/Users/arasz/RiderProjects/pi-badger-integration/extensions/mem-based-rag/index.ts:270-430`, READ),
reduced to one synchronous client per hook run.

- **Resolve.** `find_executable(env, home)`: `shutil.which("ai-raccoon", path=env["PATH"])`, else
  `Path(home)/".dotnet"/"tools"/"ai-raccoon"` if it is a file with `os.access(X_OK)`, else `None`
  (silent, nothing spawned). Both `env` and `home` are read at call time. The result is made absolute.
  pi resolves only `~/.dotnet/tools/ai-raccoon` or its own env override (`index.ts:130`, READ); the
  PATH-first order is the owner's ruling.
- **Spawn.** `subprocess.Popen([exe], stdin=PIPE, stdout=PIPE, stderr=DEVNULL, shell=False, close_fds=True)`.
  No arguments: the bare binary is the proxy transport, never `--transport stdio` (pi header,
  `index.ts:301-306`). No `start_new_session` (see kill rule). Environment and cwd are inherited.
- **Handshake.** Line 1: `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ai-badger-memory-context","version":"1"}}}`.
  Wait for the `id:1` reply. Line 2: `{"jsonrpc":"2.0","method":"notifications/initialized"}`.
- **Search.** `session.search(query, budget)` writes
  `{"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"memory_search","arguments":{"projectId","sessionId","query","limit":5,"scope":"project"}}}`
  with `N` incrementing from 2, and returns `SearchResult(mem, code)` or `None`. `scope:"project"` is
  mandatory: the owner measured that omitting it leaks shared-tier hits from other projects (pi omits
  it; this is a deliberate difference). There is no `kind` argument (owner ruling; pi sends none).
  `limit: 5` equals pi's pipeline `searchLimit` default, so planned searches send the same arguments.
- **Framing (pi `onData` parity, `index.ts:326-355`).** Read stdout, split on `\n`, trim, skip blank
  lines, skip non-JSON lines, skip replies whose `id` is not the awaited one. `error` → `None`.
  `result.isError` → `None`. Otherwise take the first `content[]` part with `type:"text"`, parse it
  as JSON, and read `results` (memory) and `code` lists; a missing list is empty; non-JSON text →
  `None`. A stdout buffer over 1 MiB without a newline, or 4 MiB in total, → `None`.
- **Session state across searches (rev 3).** A search whose request line was fully written and whose
  reply did not arrive in its budget returns `None` and leaves the session usable: its late reply is
  skipped by id when the next search reads (pi continues to the next query on the same child,
  `pipeline.ts:320-338`, READ). A partial write, an oversize line, EOF on stdout or a dead child
  marks the session *poisoned*: every later `search` returns `None` at once without writing (T24, T25).
- **One mechanism for the deadline (feasibility S6).** Single-threaded I/O with `selectors` over the
  child's stdin and stdout, both set non-blocking. Every wait is `select(timeout=budget.remaining())`.
  A hung, dripping or stdin-refusing proxy cannot hold the call past the deadline, and no thread is
  created, so nothing leaks into Hermes's long-lived process (security SHOULD-3). Pipes are not
  selectable on Windows, so on `sys.platform == "win32"` the transport returns `None` without
  spawning (owner question O-3).
- **Close (always, in `finally`).** Close the child's stdin first, so the proxy's dispose path runs
  (ADR-0106 D13: the dispose-time prove-then-stop of its private fallback backends needs a client
  that closes stdin). Wait up to `min(GRACE_SECONDS=0.5, budget.remaining())` for exit. If still
  alive, `SIGKILL` the child pid, then `wait(timeout=1)` to reap it. Close stdout. On the deadline
  or error paths the grace is whatever budget remains (usually zero), so the kill is immediate.
- **Kill scope: the child pid, not a process group (O-1, RESOLVED).** The proxy's fork is the shared
  backend that attach-or-start launches on the configured port. `BackendLauncher.Start` uses
  `ProcessStartInfo` with `UseShellExecute=false` and no new session
  (`/Users/arasz/RiderProjects/ai-raccoon/src/AiRaccoon/Hosting/Proxy/BackendLauncher.cs:234-240`, READ;
  re-verified by the orchestrator), so that serve shares the proxy's process group, and its lifetime
  "belongs to IdleWatchdog alone". A group kill would boot and kill a serve on every prompt made
  while none was running, and would also hit the hook's own group. The hook kills the pid only.
  Private fallback children are stopped by the proxy's dispose on the graceful path and left to
  their idle timeout on the kill path (INFERRED from ADR-0106 Decision ¶2). Every `Popen` is waited
  in `finally`, so the hook leaves no zombie.

### 1.2 Budget

`Budget(seconds, clock=time.monotonic)` with `remaining()`, `expired()` and `child(seconds)`, which
returns a `Budget` whose deadline is `min(parent deadline, now + seconds)`. One run budget is created
in `build()` and passed down; every stage draws a child.

| Constant | Value | Source | Used by |
|---|---|---|---|
| `SINGLE_BUDGET_SECONDS` | 5.0 | rev 2 (brief "~5 s") | whole run when the pipeline is off |
| `PIPELINE_TOTAL_SECONDS` | 90.0 | pi `totalMs` 90 000 (`types.ts:100-135`, spec §1.2) | whole run when the pipeline is on |
| `PLANNER_SECONDS` | 15.0 | pi `plannerMs` | planner cap `min(15, max(0, 90 − 15 − 8))` = 15 |
| `SEARCH_SECONDS` | 15.0 | pi `searchMs` | session open; each planned search `min(15, max(0, remaining − 8))`; the fallback search |
| `SCORE_SECONDS` | 8.0 | pi `scoreMs` | Jev stage `min(deadline, now + 8)` |
| `ATTEMPT_SECONDS` | 15.0 | pi `SCORE_TIMEOUT_DEFAULT_MS` | each Jev attempt `min(15, score deadline − now)` |
| `GRACE_SECONDS` | 0.5 | rev 2 | proxy close |

The hook's host timeouts sit above the larger total: Claude `hooks.json` `"timeout": 100`, Copilot
branch A `timeoutSec: 100`. W2a/W2b derive the ordering (`timeout > max(totals) + GRACE_SECONDS`)
instead of restating literals. Hermes is bounded by the budget alone (O-5). Claude Code's `timeout`
field above 60 s has no precedent in this repo (every current entry is 10, MEASURED); Q3.1 grounds
it in current Claude Code docs before the value ships (UNVERIFIED until then).

Expected latency, pipeline on (INFERRED from measured parts): spawn 0.17 s + handshake + planner
(one chat completion, a few seconds) + up to 6 searches × ~1.3 s (research S2) + Jev (1–4 batches,
sequential) ≈ 10–20 s per gated prompt. Pipeline off: ≈ 1.5 s (rev 2). The P4.6 demo measures both.

### 1.3 Resolution and switches

- **Kill switch.** `AI_BADGER_MEMORY_CONTEXT`, read at call time. Only the literal `"0"` disables
  everything: no spawn, no HTTP. Any other value, or none, leaves it on. SKILL.md and the changelog
  state the exact literal (security N3).
- **Pipeline switch (rev 3).** `AI_BADGER_MEMORY_CONTEXT_PIPELINE`, read at call time. Only `"0"`
  forces single-search mode, which is rev 2's behaviour exactly (5 s budget, one search, no HTTP).
  Mirrors pi's `PI_BADGER_QUERY_PIPELINE=0` (`types.ts:101`, READ via spec §1.2).
- **Default-on detection (owner ruling).** On when `.ai-badger/project-id` resolves AND the
  executable resolves. The token file is not consulted. `AI_BADGER_MEMORY_CONTEXT_PORT` does not
  exist. With the pipeline on, a missing or blank `OPENROUTER_API_KEY` makes the planner return
  `no-model` without any request, and the run takes pi's single-search fallback (§9.2).
- **Planner model.** `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL` wins; else the `medium` tier's
  preferred entry through the existing resolver (§9.3, §9.7).
- **Env vars not ported from pi** (spec §1.2, §3.3): `PI_BADGER_QUERY_PIPELINE_{TOTAL,PLANNER,SEARCH,SCORE}_MS`,
  `…_SEARCH_LIMIT`, `PI_BADGER_JEV_ENDPOINT`, `PI_BADGER_JEV_MODEL`, `PI_BADGER_JEV_SCORE_TIMEOUT_MS`.
  pi's behaviour needs none of them: each is a tuning knob over a default this port keeps as a
  constant; tests reach every limit through function parameters. The one test seam that must cross a
  process boundary is the loopback-only base URL (§9.6).
- **Project id.** Sibling `badger_store.resolve_project_id(cwd)` (`features/common/hooks/badger_store.py:2105-2119`, READ):
  `AI_BADGER_PROJECT_ID` wins, otherwise the nearest `.ai-badger/project-id`; the walk stops at the
  nearest `.ai-badger/` (a nested scaffold without an id is silent, never the parent's memory). Blank
  → silent. `badger_store` is loaded lazily by path; a load failure → silent. `badger_store` has no
  spawn and no HOME write at import (security N7, READ). A globally exported `AI_BADGER_PROJECT_ID`
  routes every repo's prompts to one project; SKILL.md says so in one line.
- **Session id.** Blank → silent, nothing spawned (a missing `sessionId` is an `isError`, research S5).
- **Query.** The trimmed prompt, uncapped (pi parity; the budget bounds latency). Every enriched
  prompt is persisted in ai-raccoon's search log, and with the pipeline on every planned query is
  too; ADR-0031 names this (security N4). With the pipeline on and a key exported, the prompt (as
  planner input and Jev `state`, capped at 32 000 chars) and up to 48 hit excerpts (500 chars each)
  go to OpenRouter; ADR-0032 names this, O-7 asks the owner to confirm the default.
- **Hermes decline check (feasibility S5).** The Hermes arm calls `build()` only when
  `<project>/.ai-badger/skills/ai-raccoon-memory/` exists, because Hermes copies
  `SHARED_SKILL_MODULES` unconditionally (`features/hermes/adjustments/adjust_hooks.py:158-163,211-217`, READ)
  and a declined skill is not scaffolded.

**Failure visibility.** Expected states are silent on stdout and stderr and add no log line: every
gate skip, disabled, no project, no executable, no session, spawn failure, crash, timeout, `isError`,
JSON-RPC error, malformed output, no hits, and every pipeline fallback reason. Only an unexpected
exception in the Claude entry writes one `hook-errors.log` line, and that line never contains prompt
text or the key. The Hermes warning logs the exception type only, never `exc_info` or the message.
The fallback reason is returned by `query_pipeline.run()` for tests and a future telemetry follow-up
(C10); v1 records it nowhere.

### 1.4 Per-agent delivery

| Agent | Mechanism | Files |
|---|---|---|
| Claude | Manifest entry `memory-context`, claude arm `hooks-json`/`hooks.json`/`UserPromptSubmit`/`memory_context_hook.py`. `hook_wiring.py` selects the command by script, rewrites `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` → `${CLAUDE_PROJECT_DIR}/.ai-badger/skills/`, wraps it in `guarded()`, keeps `timeout`, and merges with script-identity dedupe (`hook_wiring.py:114-141`, READ). The four pipeline modules sit beside the hook in the skill's `scripts/`; the resolver is the scaffolded `.ai-badger/skills/task/scripts/model_groups.py` (§9.7). | `features/common/hooks/hooks-manifest.json`, `features/common/hooks/hooks.json` |
| Copilot, branch A | Copilot arm `hooks-json`/`userPromptSubmitted`/`memory_context_hook.py`, generated by `adjust_hooks.py`. The entry already accepts `sessionId`. `timeoutSec` 100. | manifest only |
| Copilot, branch B | No arm. `HOOKS_MANIFEST_AGENT_EXEMPTIONS["memory-context"]["copilot"]` recorded as a wall citing the P0 transcript and the vendor doc sentence. An issue is filed (not fixed) saying the existing Copilot `userPromptSubmitted` arms (`context-enrichment`, `prompt-markers`, `message-delivery-per-turn`) likely inject nothing and that `docs/dictionary.md:22` is wrong. Owner checkpoint first (O-4). | `tooling/validate.py` |
| Hermes | Manifest arm `plugin`/`ai_badger_hooks.py`/`pre_llm_call`. `pre_llm_inject_context` (`ai_badger_hooks.py:634-729`) gains `_load_memory_context()` via `_load_sibling_module`; the block is appended last in its own `try/except`, followed by the closing line `(end of memory context)` outside the parity block (security MUST-3; placement confirmed in P3b.0). Inputs: `message or user_message`, `_project_cwd(cwd)`, `kwargs["session_id"]`. `SHARED_SKILL_MODULES` gains six rows (§0) so every sibling and the resolver load from the plugin dir, never from the project. **Memo:** module dict `session_id -> (sha256(prompt), result)`; the same (session, prompt) returns the cached result (block or `None`, failures included) without spawning or calling OpenRouter; a new prompt replaces the entry. Cleared inside `on_session_start_drift_notice` (the registered callback, `:423`; it already calls `reset_gate_state()` at `:430`, READ via security SHOULD-5). A gateway process shares one dict, so one session's start clears the others' entries; the cost is one re-run (ADR note, feasibility N5). | `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py:35-43`, `tests/test_hermes_plugin_install.py:20-28` twin |
| pi | Nothing. | none |

**Why the memo caches the result.** If `pre_llm_call` fires on every tool-loop continuation
(`validate.py:199` says so, `ai_badger_hooks.py:640` says "once per turn"; READ, conflicting),
returning the cached block keeps the context on continuations and costs no spawn and no OpenRouter
call. With a 10–20 s pipeline this is the difference between one wait per turn and one per tool call.

### 1.5 Parity with pi (feasibility S2, QA M5)

**Definition.** `format_block` output equals pi's `toMemoryContext` output byte for byte for BMP text
whose fields are numbers, strings or absent. The oracle is pi itself: goldens are produced by running
pi's TypeScript under bun (`/opt/homebrew/bin/bun`, MEASURED) and committed with the pi source commit
`ee5f1c6e…`. A golden retyped from the TypeScript source is not acceptable. Rev 3 extends the same
rule to the pipeline: planner, Jev and merge/runner goldens are produced by running pi's
`query-pipeline` modules under bun (Q0).

Ported as JS does (pinned by C-rows):
- `ranking` via `??`: `0` → `(rank 0)`; `null`/absent → `(rank ?)`.
- `js_number` implements JS Number→String: shortest round-trip digits, exponent form only when the
  decimal exponent is < -6 or ≥ 21, spelled `1e-7` / `1e+21`; integral floats without `.0`.
- `path` via `??`: `""` does not fall back to `sourceFile`.
- Line suffix via `!== undefined`: `lineStart: 0` renders `:0-5`; a present `null` renders as JS
  does (`:10-null`). This is rare and parity is the product, so it is ported, not "fixed".

Accepted divergences (each pinned by a row and listed in SKILL.md):
- Truncation counts code points, not UTF-16 units (block snippets and, rev 3, Jev excerpts and
  `state`). JS can split a surrogate pair, and a lone surrogate cannot be UTF-8 encoded on the
  Hermes path.
- `one_line` collapses every Python whitespace and line-break character, including U+0085,
  U+2028 and U+2029, and the path is passed through `one_line` (no cap) as well as the snippet
  (security SHOULD-1/2). A non-numeric `ranking` renders `?`. pi interpolates path and rank raw
  (`rag-core.ts:259-273`, READ), so a crafted path could forge block structure there. An issue is
  filed against pi-badger-integration; owner question O-2 confirms the divergence.
- (rev 3) `server_rank` parses a numeric string with a decimal-literal regex, not JS `Number()`:
  `"0x10"` and `"1_000"` rank last instead of 16 / NaN-last respectively. ai-raccoon emits numeric
  rankings; MG2 pins the behaviour.
- (rev 3) Jev batches the pool in the order the runner hands it (already sorted by `server_rank`).
  pi's `capPool` re-sorts with a numbers-only rank, which differs only for numeric-string rankings
  (`jev-client.ts:400-418`, READ). Question names are `c<i>` by position either way.

### 1.6 pi exclusion

Structural, with no in-script guard:
1. The manifest entry has no `pi` arm; `HOOK_CAPABLE_AGENTS = ("claude","hermes","copilot")` (`tooling/validate.py:180`, READ).
2. pi's `before_agent_start` spawns only `DELIVERY_SCRIPT` = `message_delivery_hook.py` (`features/pi/adjustments/adapter/index.ts:68,324,729-733`); `loadGates()` reads only Pre/PostToolUse (`index.ts:101-114`, READ).
3. pi never calls `pre_llm_inject_context`. pi may carry `memory_context.py` and the pipeline
   modules (Hermes copies them into the shared project `.ai-badger/hooks/` in a hermes+pi project),
   but pi never invokes them.

I8 asserts what pi executes, not which files exist (§6, P4).

### 1.7 F2: manifest arm-resolution check

`tooling/validate.py` gains `hooks_manifest_unresolved(root) -> List[str]`, reported next to agent
coverage (`validate.py:650`).
- `entry` resolves relative to the manifest's own directory (the glob is
  `features/*/hooks/hooks-manifest.json`, `validate.py:372`; the meta fixture lives at
  `features/demo/hooks/`) (feasibility M1).
- `hooks-json` arm (Claude, Copilot): exactly one command under the arm's own event matches the
  generators' own rule, `command.rstrip('"').endswith(script)` (`hook_wiring.py:201-218`, Copilot
  `adjust_hooks.py:120-123`, READ), and that one command's basename equals `script` (feasibility S3).
  Zero matches or more than one → gap. A Copilot event maps to the source event through
  `COPILOT_TO_SOURCE_EVENT`, moved from the local `event_map` (`adjust_hooks.py:112`) into
  `engine/badger_lib.py`, which both `validate.py` and the adjuster already import (feasibility S4).
- `plugin-hooks-json` arm (Claude drift-notice): resolves against repo-root `hooks/hooks.json`,
  the documented exception.
- Hermes `plugin` arm: `ast`-parse the entry file and collect every `ctx.register_hook(<str>, <Name>)`.
  The method resolves when it equals a registered event or a registered callback name (orchestrator
  Q-R1). For Hermes this proves registration, not wiring; W1 and I11 are the Hermes wiring guards.
- Unknown arm `type`, unreadable `entry` → gap, never a crash.
- No discovery-fallback exemption: `prompt-markers` has no `hooks.json` command today (MEASURED exactly
  two gaps: prompt-markers claude and copilot), so P1 adds explicit `UserPromptSubmit` commands for
  `prompt-markers/scripts/user_prompt_hook.py`. Its Copilot `timeoutSec` becomes 10 (was 5 via
  discovery), named in the changelog.
- The check ignores `matcher` (security N1): recorded as a known limit in the function's contract.

---

## 2. Rulings table

| Id | Ruling | Where it lands |
|---|---|---|
| Brief | Fires every prompt, gated by the `shouldEnrich` port minus `/skill:` | P2 C1–C7 |
| Brief | pi excluded | §1.6, P4 I8 |
| Brief | Accept the full wait; hook timeout above the budget; any failure → nothing or fallback, exit 0 | §1.2, P2 T12–T16, P3a H3/H8, W2a |
| Brief | Stdlib-only 3.10+; tests never touch the live serve, the network or real `$HOME` | G1, G2, G4, conftest `_home_off_limits` |
| **Owner transport ruling** | Proxy spawned per call, `argv == [exe]`, PATH then `~/.dotnet/tools`; stdin/stdout piped, stderr discarded; `initialize` 2024-11-05 → `notifications/initialized` → `tools/call` `{projectId, sessionId, query, limit:5, scope:"project"}`; never pi; one process; one deadline; kill + reap; default-on = project-id + executable; `"0"` kill switch; port variable deleted | §1.1–1.3, P2 |
| **Owner pipeline rulings (rev 3)** | Port pi's pipeline (plan → dedupe → one search per planned query over the one session → Jev → document-aware merge); block unchanged | §9.2, Q2c, Q3 B9 |
| | Planner = direct HTTP to OpenRouter `/api/v1/chat/completions` via urllib; system = `DELEGATOR_PERSONA + "\n\n" + PLANNER_ADDENDUM` verbatim; model = `medium` preferred through `model_groups.py`, `openrouter/` removed; override `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`; decide the resolver route | §9.3, §9.7, Q2a |
| | Jev = direct HTTP to `https://openrouter.ai/api/alpha/decisions`, porting builder/parser/caps/error vocabulary | §9.4, Q2b |
| | Key from env only, never a file, never logged; missing key or planner/Jev failure → pi's single-search fallback with pi's reason vocabulary | §9.2, §9.6; Jev wording conflicts with pi's source → O-6 |
| | HTTP hygiene: `ProxyHandler({})`, redirects refused, TLS default context, child budgets per stage, a stalled response never exceeds its stage share | §9.5, Q1 O1–O6 |
| | Budget rises to cover the pipeline from pi's constants; Claude `timeout` above the total | §1.2, W2a |
| | `AI_BADGER_MEMORY_CONTEXT=0` disables everything; `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0` forces single search; no other tuning vars | §1.3, B11, B12 |
| | Hermetic tests: local fake OpenRouter on an ephemeral port via injected base URL; subprocess override refused unless host is `127.0.0.1`; port the portable pi cases with bun-recorded JSON goldens | §9.6, Q0, §6 |
| F2 | Every manifest arm resolves; watched red on a deleted command | §1.7, P1 V1–V16 |
| R1 | Script arms → same-event command; Hermes via `ast`; prompt-markers explicit; dedupe proven; drift-notice exception kept | P1 |
| R2 | One wall-clock deadline | §1.2 (opener/no-spawn parts superseded by the transport ruling; the rev-3 opener is §9.5) |
| R3 | No expanded mode, no tuning env vars, block byte-identical incl. `rank 1` | §1.3, §1.5 |
| R4 | Hermes memo per (session, prompt) | §1.4, P3b M1–M4 |
| R5 | Copilot spike first; two branches; branch B is an owner checkpoint + filed issue | P0, P4 |
| R6 | pi structural; red integration test; no `PI_SESSION_ID` guard | §1.6, I8 |
| Q-R1 | Hermes method resolves on event or callback name | §1.7 |
| prompt-markers | Accept Copilot `timeoutSec` 5 → 10 and reordering in `test_context_enrichment_wiring_end_to_end.py:57`; name the test in the PR if edited | P1 |
| O-1 | Kill pid only after graceful stdin close — **RESOLVED** (orchestrator verified `BackendLauncher.cs:234-240`) | §1.1, T18, T19 |

---

## 3. Conflicts resolved

| # | Conflict | Resolution |
|---|---|---|
| C1 | Module split | `memory_context.py` keeps core + budget + transport + build; the pipeline adds four effect-free modules (rev 3). |
| C2 | Copilot wiring | P0 spike decides; branch B needs owner sign-off. |
| C3 | Hermes arms naming callbacks | Event or callback name resolves (Q-R1). |
| C4 | Discovery fallback in F2 | Strict; prompt-markers made explicit. |
| C5 | `PI_SESSION_ID` guard | Cut. |
| C6 | Kill-switch name | `AI_BADGER_MEMORY_CONTEXT`. |
| C7 | Test route to the fake | Fake `ai-raccoon` first on a temp PATH with a temp HOME; fake OpenRouter on 127.0.0.1. |
| C8 | Claude hook timeout | 100 (rev 3; was 10); W2a derives ordering. |
| C9 | Error visibility | Expected failures fully silent; unexpected → one log line, no prompt text, no key. |
| C10 | Telemetry | Cut from v1; follow-up issue (now also carries the fallback reason and Jev usage). |
| C11 | Hermes memo | Caches and returns the result, failures included. |
| C12 | Manifest row placement | Integration package (P4). |
| C13 | ADRs | 0031 (proxy transport, P2) and 0032 (pipeline over OpenRouter, Q0), written before code. Re-check numbers at rebase (next free is 0031, MEASURED `ls docs/adr`). |
| C14 | Nested `.ai-badger/` without id | Stop (badger_store). |
| C15 | `SHARED_SKILL_FILES` twin | Out of scope; the existing equality test enforces the rows. |
| C16 | Kill scope | Pid only (O-1 RESOLVED). |
| C17 (rev 3) | Spec §0 "direct HTTP vs proxy" conflict | Stale; the proxy ruling stands. |
| C18 (rev 3) | Ruling "Jev fails → single search, as pi does" vs pi's source (Jev failure → null scores → merge by server rank, no fallback; `pipeline.ts:351-379`, READ) | Follow pi's source; owner confirms (O-6). |
| C19 (rev 3) | Resolver route: vendored copy vs reading `.ai-badger/model-groups.json` directly | Neither: load the one existing `model_groups.py` by path relative to the hook file and pass it the project's registry JSON (§9.7). |
| C20 (rev 3) | Planner env name: spec suggests `AI_BADGER_QUERY_PIPELINE_PLANNER_MODEL` | Owner's `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`. |
| C21 (rev 3) | pi dedupes twice (`merge.ts` `dedupeKind` and `rag-core.ts` `pruneHits`, pinned equal by `parity.test.ts:44`) | One implementation: the runner takes `prune_hits` as a parameter; pi's parity row becomes structurally true and is not ported. |
| C22 (rev 3) | Pool cap lives in both `pipeline.ts` and `jev-client.ts` `capPool` | The runner owns `POOL_MAX = 48`; `jev_scoring.score` batches what it is given. |

---

## 4. Packages

One task PR, one or more commits per package, pushed per package. Every package that touches
`features/`, `tooling/` or `engine/` ends with the **closing step**, so every package boundary is green
on pre-push (`.lefthook/pre-push/verify.sh:61,231-247` runs release, scaffold, plugin-skills, index,
validate and tdd lanes; `.pre-commit-config.yaml` runs sync/index/scaffold checks at commit time).

**Closing step:**
```
$PY tooling/sync_plugin_skills.py
$PY tooling/index_build.py
$PY features/common/skills/welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root . --no-install
   # use the exact remediation command gates/scaffold_freshness_guard.py prints, plus --no-install
$PY tooling/sync_plugin_skills.py --check && $PY tooling/index_build.py --check && $PY gates/scaffold_freshness_guard.py
git diff origin/main -- .ai-badger .claude .github   # no IDE-formatter drift ships
```
`--no-install` keeps the self-scaffold from rewriting `~/.hermes/plugins/ai-badger/`. Only the P4.6
demo does a deliberate install run.

**Generated outputs are serialized (feasibility S1).** Parallel lanes commit hand-edited files only.
The closing step runs once per merge into the task branch, by the integrating session, never inside
two parallel lanes. Generated paths: `skills/ai-raccoon-memory/scripts/`, `.ai-badger/**`,
`.claude/settings.json`, `.github/hooks/ai-badger-hooks.json`, `index.json`, `VERSION`,
`.claude-plugin/plugin.json`, `marketplace.json`, `docs/changelog/README.md`.

**Python floor.** Every new module runs on 3.10: no `datetime.UTC`, `tomllib`, `ExceptionGroup`,
`typing.Self`; `str.removeprefix` and `http.server.ThreadingHTTPServer` are fine (memory note: the
floor guard misses widened stdlib APIs).

### 4.0 Context map

| Kind | Paths |
|---|---|
| Primary (new) | `features/common/skills/ai-raccoon-memory/scripts/{memory_context,memory_context_hook,openrouter_client,query_planner,jev_scoring,query_pipeline}.py` |
| Primary (edited) | `features/common/hooks/hooks.json`, `features/common/hooks/hooks-manifest.json`, `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py`, `tooling/validate.py`, `engine/badger_lib.py`, `features/copilot/adjustments/adjust_hooks.py` |
| Read-only dependencies | `features/common/skills/task/scripts/model_groups.py` (`preferred`/`resolve`, `:320-359`), `features/common/data/model-groups.json`, `features/common/personas/delegator.md`, `badger_store.py` (sibling) |
| Tests (new) | `tests/test_memory_context_{core,transport,hook,hermes,integration,openrouter,planner,jev,pipeline,pipeline_wiring}.py`, `tests/test_hooks_manifest_resolution.py`, `tests/memory_context_support.py`, `tests/memory_context_openrouter.py` (fake server), `tests/fixtures/memory_context/*` |
| Tests (edited) | `tests/test_every_check_can_fail.py`, `tests/test_validate.py`, `tests/test_skills_lint.py`, `tests/test_hermes_plugin_install.py`, possibly `tests/test_scaffold_hook_wiring.py`, `tests/test_context_enrichment_wiring_end_to_end.py` |
| Patterns to follow | sibling load by path under a distinctive `sys.modules` key (`context_enrichment_hook.py:41-68`); Hermes `_load_sibling_module` + reset fixture (`tests/test_sibling_module_loading.py:34-55`); guarded entry (`context_enrichment_hook.py:169-199`); bun-recorded goldens (P2.3) |
| Edit sequence | P0 ∥ P1 ∥ P2 ∥ Q0 → Q1 ∥ Q2c → Q2a ∥ Q2b → Q3 → P3a ∥ P3b → P4 (§5) |

### P0: Copilot capability spike + owner checkpoint (no repo edit except the research record)

- **P0.1** Throwaway dir outside the repo. A `.github/hooks/x.json` `userPromptSubmitted` command
  prints `{"additionalContext":"The code word is PERIWINKLE"}`; a second variant uses the
  `hookSpecificOutput` envelope. The hook also dumps its stdin to a file (a marker that it ran, and
  the captured Copilot payload). Run `copilot -p "What is the code word in your context? Reply with the word or NONE."`
  with the installed CLI (`/opt/homebrew/bin/copilot`). Each arm runs 3 times.
- **P0.2** Positive control (QA S7): the same code word placed in `.github/copilot-instructions.md`
  must yield PERIWINKLE.
- **P0.3** Append the transcript to the research record as MEASURED with a branch verdict (A or B).
  Commit the captured payload as `tests/fixtures/memory_context/copilot_user_prompt_payload.json`
  (used by I7 in branch A; the fixture commit lands in P4).
- **P0.4 Owner checkpoint** (one hand-off, all questions together): O-2, O-3, O-4 (only if B), O-5,
  O-6, O-7 (§10). P2/Q packages may start before the answers; rows an answer would change are
  written to the recommendation and adjusted if the owner rules otherwise.
- **Acceptance:** the hook is shown to run (payload dump exists) in every run; the positive control
  says PERIWINKLE; the verdict and grade are recorded.
- **Gate:** the transcript in `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md`.
- **Files:** that research record.

### P1: release skeleton + F2 check + explicit prompt-markers wiring

- **P1.1 Release skeleton.** `VERSION` 0.177.3 → 0.178.0; `$PY tooling/version_sync.py`;
  `docs/changelog/0.178.0-per-prompt-memory-context.md` as a stub naming the feature, the pipeline
  and the F2 check; `$PY tooling/changelog_index.py` for the README row. `git fetch --tags` before
  the first push (memory: release_guard reads stale local tags).
- **P1.2** Move the Copilot event map to `engine/badger_lib.py` as `COPILOT_TO_SOURCE_EVENT`; the
  adjuster imports it. Pure refactor; `tests/test_adjust_hooks_copilot.py` stays green.
- **P1.3** Red first: write `tests/test_hooks_manifest_resolution.py` against a stub
  `hooks_manifest_unresolved` returning `[]`; watch V1's provocation fail. Then implement §1.7 with
  one `_report` line at `validate.py:650`.
- **P1.4 Fixtures the check turns red (feasibility M1).** Three helpers write a miniature manifest
  whose arms name `demo_hook.py`/`SessionStart` with no `hooks.json` beside it:
  `tests/test_every_check_can_fail.py:553-574` (`_hooks_manifest`/`_validate_tree`, five `--all`
  provocations at `:897-913` whose unprovoked controls must exit 0, `:1057-1066`),
  `tests/test_validate.py:17-27`, `tests/test_skills_lint.py:22-32`. Each helper writes a resolving
  `hooks.json` beside the manifest, uses the Copilot spelling for the copilot arm's event, and a
  Hermes `plugin` arm against a stub entry that registers the method (or drops the hermes/copilot
  arms for the exemption shape). The rc-1 tests in `test_validate.py`/`test_skills_lint.py` must
  still fail for their own reason, asserted on the message, not only the rc.
- **P1.5** Add `prompt-markers/scripts/user_prompt_hook.py` commands to `features/common/hooks/hooks.json`
  `UserPromptSubmit`. Prove dedupe (V14/V15).
- **P1.6** Register the check in the `tests/test_every_check_can_fail.py` REGISTRY; provocation =
  the deleted command.
- **P1.7** Closing step.
- **Acceptance:** real manifest resolves (`[]`); the check was watched red on a tmp copy with the
  `context_enrichment_hook.py` command deleted (exactly 2 gaps: claude, copilot), then green;
  `validate --all` exits non-zero on any gap; the five meta-test controls exit 0; re-wiring a target
  that already holds a literally different prompt-markers entry leaves exactly one; pre-push green.
- **Gate:** `$PY -m pytest -q tests/test_hooks_manifest_resolution.py tests/test_hooks_manifest_agent_coverage.py tests/test_every_check_can_fail.py tests/test_validate.py tests/test_skills_lint.py tests/test_adjust_hooks_copilot.py tests/test_scaffold_hook_wiring.py tests/test_context_enrichment_wiring_end_to_end.py`;
  `$PY tooling/validate.py --all`; `$PY tooling/version_sync.py --check`; `$PY tooling/changelog_index.py --check`;
  `$PY gates/release_guard.py`; pylint on touched non-test files; the closing-step checks.
- **Files:** `VERSION`, `.claude-plugin/plugin.json`, `marketplace.json`, `docs/changelog/0.178.0-per-prompt-memory-context.md`,
  `docs/changelog/README.md`, `engine/badger_lib.py`, `features/copilot/adjustments/adjust_hooks.py`,
  `tooling/validate.py`, `features/common/hooks/hooks.json`, `tests/test_hooks_manifest_resolution.py` (new),
  `tests/test_every_check_can_fail.py`, `tests/test_validate.py`, `tests/test_skills_lint.py`,
  possibly `tests/test_scaffold_hook_wiring.py`, plus the closing step's generated outputs.

### P2: `memory_context.py` complete (core + budget + transport + single-search build) + ADR-0031 + fake + goldens

- **P2.1 ADR first.** `docs/adr/0031-per-prompt-memory-context-through-the-ai-raccoon-proxy.md`
  (Nygard) + `docs/adr/README.md` row. Context: per-prompt retrieval; ai-raccoon ADR-0106/F70 and
  the zero-secret-bytes invariant; stdlib lacks ECDSA. Decision: proxy per call, one budget, kill
  pid after graceful close, default-on detection, one switch. Consequences: +0.17 s spawn and ~1.3 s
  per search; the proxy may start a serve; every enriched prompt (and planned query) lands in the
  search log; Hermes blocks the turn up to the budget; memo scope in gateways; parity divergences
  (§1.5). Alternatives: direct HTTP with the token (rejected: F70, ADR-0106 invariant, no stdlib
  ECDSA), `--transport stdio` (rejected: slated for removal), a persistent proxy per Hermes process
  (deferred), process-group kill (rejected, O-1 resolved).
- **P2.2 Fake executable** `tests/fixtures/memory_context/fake_ai_raccoon.py` and the fixtures in
  `tests/memory_context_support.py`: write the fake into a temp bin dir as `ai-raccoon` with
  `#!<sys.executable>` and mode 0755, plus a `python3` symlink to `sys.executable`; PATH = that dir
  only; HOME = a temp dir. Modes (env `FAKE_RACCOON_MODE`): `hits`, `empty`, `iserror`, `rpcerror`,
  `malformed`, `drip`, `hang`, `crash`, `nostdin`, `oversize`, `slowinit`, `grandchild`, and (rev 3)
  `perquery` (hits read from a JSON map `query -> {results, code}` named by `FAKE_RACCOON_HITS`;
  unknown query → empty) and `latereply` (the first `tools/call` is answered only after the second
  arrives, then both in order). Every invocation appends `{pid, argv, mode, stdin_lines, saw_eof}`
  to a JSONL log in the test's temp dir.
- **P2.3 Block goldens (QA M5).** `tests/fixtures/memory_context/gen_goldens.ts` imports `rag-core.ts`
  from `/Users/arasz/RiderProjects/pi-badger-integration/extensions/mem-based-rag/` and prints
  `toMemoryContext` for every case in the committed `golden_inputs.json`; the output is committed as
  `golden_outputs.json` with `{"pi_commit": "ee5f1c6e…", "generator": "gen_goldens.ts", "bun": "<version>"}`.
  Inputs cover: empty/empty, mem-only, code-only, 7+7 caps, snippet-dup, hash-dup, `sourceFile`-only,
  `path: ""`, missing rank, `ranking: 0`, `ranking: null`, `5e-05`, `1e-7`, `1e21`, `lineStart: 0`,
  `lineEnd: null`, multi-line snippet >300 chars, query >80 chars. Divergence inputs are not in the
  bun goldens; their rows assert the Python behaviour directly. CI does not run bun.
- **P2.4** Stubs so tests go red on assertions. Then implement the pure section, `Budget`,
  `find_executable`, `RaccoonSession` (with the rev-3 session-state rule), `build()` in its
  single-search form (Q3 adds the pipeline branch). T13 (drip) is written first against a naive
  `readline()` implementation and watched to hit the watchdog.
- **P2.5** Closing step.
- **Acceptance:** every C, T, B, S and G row green, each mutation applied by hand and seen red once;
  `format_block` equals every bun golden; no test spawned anything but the fake (G1); pre-push green.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_core.py tests/test_memory_context_transport.py tests/test_sync_plugin_skills.py tests/test_plugin_copy_points_at_the_tailored_one.py`;
  pylint on `memory_context.py`; `$PY gates/docs_guard.py`; the closing-step checks.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` (new),
  `tests/test_memory_context_core.py`, `tests/test_memory_context_transport.py`,
  `tests/memory_context_support.py`, `tests/fixtures/memory_context/{fake_ai_raccoon.py,gen_goldens.ts,golden_inputs.json,golden_outputs.json}` (all new),
  `docs/adr/0031-….md` (new), `docs/adr/README.md`, generated outputs.

### Q0–Q3: the query pipeline — see §9

Q0 (ADR-0032, pipeline goldens, docs grounding), Q1 (`openrouter_client.py` + fake OpenRouter),
Q2a (`query_planner.py`) ∥ Q2b (`jev_scoring.py`) ∥ Q2c (`query_pipeline.py`), Q3 (wiring into
`build()`). They sit between P2 and P3; §9.8 holds each package's steps, acceptance, gate and files.

### P3: entries, as two hand-edit lanes (P3a ∥ P3b), one closing step after both

**P3a — Claude/Copilot entry.**
- Write `memory_context_hook.py` (stdin → `build` → envelope; `guarded_main`; closed-stdout safe).
- Append the `UserPromptSubmit` command `python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/ai-raccoon-memory/scripts/memory_context_hook.py"`
  with `"timeout": 100` to `features/common/hooks/hooks.json`. It is inert until P4's manifest row.
- **Files:** the hook (new), `features/common/hooks/hooks.json`, `tests/test_memory_context_hook.py` (new).

**P3b — Hermes arm + memo.**
- **P3b.0** Confirm where Hermes places the returned `context` (read the installed Hermes source; if
  unavailable, record it in the P4.6 demo), whether a platform/gateway kwarg exists (O-5), and
  whether Hermes bounds a `pre_llm_call` hook's run time. Record the finding in the research record.
  The closing line (W2) ships either way.
- `_load_memory_context()`; in `pre_llm_inject_context`, if the decline check passes, call `build()`
  through the memo and append the block plus the closing line last, inside its own `try/except`
  that logs the exception type only.
- Clear the memo inside `on_session_start_drift_notice`.
- `SHARED_SKILL_MODULES +=` `("ai-raccoon-memory","memory_context.py")`, `("ai-raccoon-memory","openrouter_client.py")`,
  `("ai-raccoon-memory","query_planner.py")`, `("ai-raccoon-memory","jev_scoring.py")`,
  `("ai-raccoon-memory","query_pipeline.py")`, `("task","model_groups.py")`, each with its
  `SHARED_SKILL_FILES` twin row; `LEGACY_FLAT_FILES` derives. None of the six basenames exists among
  current Hermes files (MEASURED `find`). Update the `PLUGIN_YAML` description (`adjust_hooks.py:62-68`).
- **Files:** `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py`,
  `tests/test_hermes_plugin_install.py`, `tests/test_memory_context_hermes.py` (new).

**P3 closing step** after both lanes merge. Hermes now copies six more modules into `.ai-badger/hooks/`,
so the self-scaffold changes there.
- **Acceptance:** every H, W and M row green with mutations seen red; other `pre_llm_call` parts
  survive every memory-arm failure; the sibling-load derive test (`test_hermes_plugin_install.py:405-436`)
  passes; H12 shows the pipeline runs through the real entry; pre-push green.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_hook.py tests/test_context_enrichment_hook.py tests/test_memory_context_hermes.py tests/test_hermes_plugin_install.py tests/test_hermes_plugin_payloads.py tests/test_sibling_module_loading.py`;
  `$PY tooling/validate.py --all`; pylint on the hook and `ai_badger_hooks.py`; the closing-step checks.

### P4: integration (manifest row, Copilot branch, docs, demo, release text)

- **P4.1** Manifest entry `memory-context`: claude arm, hermes arm, and either the copilot arm
  (branch A) or the exemption in `tooling/validate.py` (branch B, after owner sign-off). Branch B:
  `gh issue create` for the inert Copilot arms and `docs/dictionary.md:22`. File the pi issue for
  path/rank sanitising (O-2) and the telemetry follow-up (C10, now including fallback reason and Jev
  usage).
- **P4.2** `tests/test_memory_context_integration.py` (I rows, W2b); commit the P0 Copilot payload
  fixture.
- **P4.3** Docs: `SKILL.md` section (what it does; pipeline and single-search modes; latency of
  each; proxy spawn and possible serve start; kill switch literal `"0"`; pipeline switch literal
  `"0"`; `OPENROUTER_API_KEY` read from env only and what leaves the machine when it is set; the
  planner-model override and the declined-`task` consequence; search-log persistence; exported
  `AI_BADGER_PROJECT_ID` effect; parity divergences; Copilot status; POSIX-only; skill `version`
  0.1.0 → 0.2.0). The test-only base URL is named in ADR-0032, not in SKILL.md. `docs/skills.md`
  ai-raccoon-memory section; `docs/dictionary.md` a `memory-context` row beside the memory-first
  gate row (`:27`) plus the Copilot wording per branch; `docs/hermes-claude-compatibility.md:11-16,31`
  (the `pre_llm_call` list). `README.md:204` and `docs/skills.md:106` mirror the SKILL
  `description`; update them only if the description changes, and say which in the PR. The
  drift-audit map (`features/common/skills/documentation-drift-audit/references/ai-badger-drift-audit-map.md:44-55`)
  is already stale: left as is, noted in the PR.
- **P4.4** Changelog text final (§8).
- **P4.5** Closing step. Rebase last (changelog README row and ADR numbers are conflict hotspots).
- **P4.6 Fired-in-anger demo** (manual, pasted into the PR; a deliberate install run; the only step
  that touches the real network). In a live Claude session in this repo with the serve running and
  `OPENROUTER_API_KEY` exported: one enrichable prompt shows the block; record the resolved planner
  model id, the planned queries, the number of `tools/call` lines (one proxy process, `pgrep -fl ai-raccoon`
  during the run), Jev batches and wall time. Unset the key: the same prompt runs single-search
  (`no-model`), record wall time. `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0`: single search, no HTTP.
  `AI_BADGER_MEMORY_CONTEXT=0`: no block. With the serve stopped: one prompt, then record whether
  the proxy started a serve and whether it still listens after the hook exits (`lsof -iTCP:7721`),
  the hook's wall time, and that no `ai-raccoon` proxy process remains. Repeat once in Hermes if
  available (record `pre_llm_call` frequency and whether a 10–20 s pipeline blocks other sessions,
  security SHOULD-4); otherwise record "not demonstrated".
- **P4.7** Run the repo's tri-agent hook checklist
  (`features/common/skills/code-review-evidence/references/ai-badger-hook-feature-review.md`) at review.
- **Acceptance:** composed scaffold wires Claude and Hermes, Copilot per branch; pi never executes
  any of the six files (I8); the wired Claude command string prints the block against the fakes;
  `validate --all` green and red on each provocation (I1, I2, I5); all release gates green; demo pasted.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_integration.py tests/test_hooks_manifest_agent_coverage.py tests/test_hooks_manifest_resolution.py tests/test_pi_hook_arm_coverage_contract.py tests/test_scaffold_hook_wiring.py tests/test_context_enrichment_wiring_end_to_end.py tests/test_adjust_hooks_copilot.py`;
  `$PY tooling/validate.py --all`; `$PY tooling/index_build.py --check`; `$PY tooling/sync_plugin_skills.py --check`;
  `$PY tooling/version_sync.py --check`; `$PY tooling/changelog_index.py --check`; `$PY gates/docs_guard.py`;
  `$PY gates/scaffold_freshness_guard.py`; `$PY gates/release_guard.py`; pylint on touched files; the
  docs/work README check CI runs. CI runs the full suite on push.
- **Files:** `features/common/hooks/hooks-manifest.json`, `tooling/validate.py` (branch B),
  `tests/test_memory_context_integration.py` (new), `tests/fixtures/memory_context/copilot_user_prompt_payload.json` (branch A),
  `features/common/skills/ai-raccoon-memory/SKILL.md`, `docs/skills.md`, `docs/dictionary.md`,
  `docs/hermes-claude-compatibility.md`, `docs/changelog/0.178.0-per-prompt-memory-context.md`,
  generated outputs.

---

## 5. Parallelism map

```
P0 (spike, owner checkpoint) ─────────────────────────────────────────────────────────┐
P1 (release skeleton, F2, prompt-markers) ─────────────────────────────► P3a ─┐        │
P2 (memory_context.py, ADR-0031, fake, block goldens) ─┬─► Q1 ─┬─► Q2a ─┐     │        │
Q0 (ADR-0032, pipeline goldens, docs grounding) ───────┤       └─► Q2b ─┼─► Q3 ┤ closing ├─► P4
                                                       └─► Q2c ─────────┘     └─► P3b ┘  │
```

| Concurrent lanes | Condition |
|---|---|
| P0 ∥ P1 ∥ P2 ∥ Q0 | disjoint hand-edited files; each in its own worktree (`isolation: worktree`); Q0 writes only `docs/adr/0032-…`, `docs/adr/README.md` (rebase P2's row), `tests/fixtures/memory_context/pipeline_*` |
| Q1 ∥ Q2c | both after P2 (`Budget`, `prune_hits`) and Q0 (goldens); Q2c has no HTTP |
| Q2a ∥ Q2b | both after Q1 (`post_json` contract and the fake server) and Q0 |
| P3a ∥ P3b | both after Q3 (P3a also after P1 for `hooks.json`); one closing step after both |

The contracts that let Q1, Q2a, Q2b and Q2c run apart are fixed in §9 before any lane starts:
`post_json(url, body, key, budget) -> Reply`, `plan(query, budget) -> PlanResult`,
`score(query, pool, budget) -> list[float | None]`, `search(query, budget) -> (mem, code) | None`,
`run(query, *, plan, search, score, prune, budget, limits) -> RunResult`.

| Shared file | Packages | Order |
|---|---|---|
| `features/common/hooks/hooks.json` | P1, P3a | P1 before P3a |
| `tooling/validate.py` | P1, P4 (branch B) | P1 before P4 |
| `memory_context.py` | P2, Q3 | P2 before Q3 |
| `tests/fixtures/memory_context/fake_ai_raccoon.py` | P2 (all modes incl. `perquery`, `latereply`) | P2 only |
| `tests/memory_context_support.py` | P2 (G1–G3), Q1 (G4 + scrub list) | P2 before Q1 |
| `docs/adr/README.md` | P2, Q0 | rebase the second |
| `hooks-manifest.json` | P4 only | — |
| Generated outputs (§4 list) | every closing step | serialized by the integrating session |
| `docs/changelog/*`, `VERSION` | P1 (skeleton), P4 (text) | rebase last |

---

## 6. Design-tests list

Row format: **behaviour | failure mode | mutation → red**. Default protocol: stubs first so red is an
assertion failure; after green, the row's mutation is applied by hand and must go red. Every "silent"
row has a paired control and asserts the fake's invocation count (0 when nothing may spawn, 1 when
the child must be reached and fail), because `CLAUDE_PROJECT_DIR` points at an id-less scratch
project (`tests/conftest.py:112-119`, READ). Pipeline rows also assert the fake OpenRouter's request
count. Timing rows assert upper bounds under a watchdog. Parametrized tables count as one row.

**Shared fixtures (in `tests/memory_context_support.py`, autouse in every new module):**
- *Env scrub (QA S3):* delete `AI_BADGER_PROJECT_ID`, `AI_BADGER_MEMORY_CONTEXT`,
  `AI_BADGER_MEMORY_CONTEXT_PIPELINE`, `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`,
  `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE`, `OPENROUTER_API_KEY`, and every proxy variable
  (`http_proxy`, `https_proxy`, `all_proxy`, `no_proxy`, upper and lower case); set `HOME` to a
  per-test temp dir and `PATH` to the per-test fake bin dir. Subprocess tests build `env` from that.
- *Real-executable guard:* at import, before any HOME redirect, record the realpaths of
  `shutil.which("ai-raccoon")` under the original PATH and of `<pwd home>/.dotnet/tools/ai-raccoon`
  (home from `pwd.getpwuid(os.getuid()).pw_dir`). Wrap `subprocess.Popen` (on top of conftest's
  `_TrackedPopen`) to fail the test if `realpath(argv[0])` is one of them, and record every argv in a
  per-test spawn log. The guard takes its forbidden set as a parameter so G1 can prove it.
- *Network guard (rev 3):* in-process, wrap `socket.socket.connect`/`connect_ex` and
  `socket.create_connection` to raise unless the address is `127.0.0.1`. Subprocess runs get the same
  guard through a temp-dir `sitecustomize.py` on `PYTHONPATH` that writes a marker file and raises.
- *Fake OpenRouter* (`tests/memory_context_openrouter.py`): `ThreadingHTTPServer` on `127.0.0.1:0`
  started per test; routes `POST /api/v1/chat/completions` and `POST /api/alpha/decisions`; a script
  of replies per route (status, headers, body, or a behaviour: `hang`, `header-drip`, `body-drip`,
  `oversize`, `redirect-to <url>`, `close`); records every request (path, headers, parsed body).
  A second instance acts as a *capture* server for redirect and proxy rows. Thread-count rows take
  their baseline after the servers start.
- *Hermes reset (QA M4, N7):* pop the memory-context and pipeline `sys.modules` keys, clear
  `_missing_siblings`, `_broken_siblings` and the memo, before and after every Hermes test.

### G: fixtures (`tests/test_memory_context_transport.py`, G4 in `tests/test_memory_context_openrouter.py`)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| G1 | Guard fires: a spawn of a stand-in "real" path fails the test (`pytest.raises` on the guard); control with the fake passes | A test reaches the live proxy and bank unnoticed | guard compares unresolved paths; guard skips symlinks |
| G2 | Scrub holds: with `AI_BADGER_MEMORY_CONTEXT=0`, `AI_BADGER_PROJECT_ID=x`, `OPENROUTER_API_KEY=k` and `https_proxy` exported by the outer env, a happy row still spawns once with the file's project id and sends 0 HTTP requests | Machine-dependent red/green; a developer's real key used | remove the scrub |
| G3 | Fake smoke: each mode behaves as named (hits replies; crash exits 1; hang never replies; drip sends no newline; `latereply` holds reply 1) | A fake that cannot produce the failure makes every failure row vacuous | make `hang` reply |
| G4 | Network guard: in-process connect to `203.0.113.1:443` raises before any packet (asserted with `pytest.raises`); a subprocess with the sitecustomize guard that connects there writes the marker and fails; control to `127.0.0.1` passes | A test reaches openrouter.ai with a test key | guard allows everything; guard not on `PYTHONPATH` |

### P1: `tests/test_hooks_manifest_resolution.py` (16)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| V1 | Real manifest → `[]`. Red first: tmp copy with the `context_enrichment_hook.py` command deleted → exactly 2 gaps (claude, copilot) | Arm that wires nothing | `return []` |
| V2 | Synthetic Claude arm with no command → 1 gap naming file, hook, agent, event, script | Silent pass | skip arms with `script` |
| V3 | Command under a different event → gap | Wired on the wrong event | search all events |
| V4 | `not_memory_context_hook.py` alone → gap; `memory_context_hook.py` + `x_memory_context_hook.py` → gap (ambiguous under `endswith`) | Validator and generators disagree | basename-only; `endswith`-only |
| V5 | Copilot `userPromptSubmitted` resolves via `badger_lib.COPILOT_TO_SOURCE_EVENT`; unmapped → gap | Twin event map | literal copy in validate; drop an entry |
| V6 | `plugin-hooks-json` resolves against root `hooks/hooks.json`; a `hooks-json` arm present only there → gap | Exception widened | one file for both types |
| V7 | Arm resolvable only via skill discovery → gap | Discovery silently accepted | add a discovery branch |
| V8 | Hermes: event string resolves; callback name resolves; unregistered `def` → gap; unknown → gap | Method never registered | accept any `def` |
| V9 | `register_hook("x", f)` in a comment/string does not count | Commented registration passes | regex over text |
| V10 | Unknown arm `type`; unreadable `entry` → gap, no crash | Crash hides other gaps | `continue`; let `OSError` escape |
| V11 | `entry` resolves relative to the manifest's directory (`features/demo/hooks/`) | Fake-root manifests misresolve | hard-code `features/common/hooks/` |
| V12 | `validate --all` exits non-zero on a gap | Detected, not failing | drop `ok &=` |
| V13 | Registered in `test_every_check_can_fail.py` with V1's provocation and an intact control | Unregistered check | omit registration |
| V14 | Claude: target holding a *literally different* prompt-markers entry for the same script → exactly one entry after re-wire (QA S1) | Prompt markers inject twice | break `_hook_key`; separately, drop the script from `_prune`'s superseded set |
| V15 | Copilot: exactly one `user_prompt_hook.py` entry in `userPromptSubmitted`, `timeoutSec` 10 | Double wiring | run discovery even when the command exists |
| V16 | The three fixture helpers' unprovoked trees exit 0 under `--all`; their rc-1 tests fail for their own named reason | Meta-test controls red / right rc wrong reason | revert a helper |

### P2 core: `tests/test_memory_context_core.py` (23)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| C1 | Long IDEA prompt → `ok`, `query == prompt.strip()`, word count right | Real prompts rejected | default `False`; drop strip |
| C2 | Control words table: each of 7, `STOP`, `"  Stop  "` → `control-word`; `"stop"` is `control-word` not `too-short`; `"stop! please halt the build runner now"` enriches | Word lost; gate order; substring | delete a word; length first; `startswith` |
| C3 | Command table: `/delegations`, `/monitors`, `/delegate <long>`, `/skill:task …` → `command`; no `bare-skill-call` | Slash turns searched; pi carve-out ported | delete gate; move below thinness; port `SKILL_PREFIX_RE` |
| C4 | `""`, whitespace → `empty` | Whitespace searched | skip strip |
| C5 | `min_words=1`: 20 chars ok, 19 `too-short` | Off-by-one | `<` → `<=` |
| C6 | 5-word thin prompt → `too-thin`; 6-word ok at default, `too-thin` at `min_words=7` | Floor off-by-one | 6 → 5; `<` → `<=` |
| C7 | `f: please explain …` enriches and the query keeps `f:`; no prefix strip | Marker stripped | `re.sub` leading `/\w+:` |
| C8 | Tokenizer table: case fold; `a an the it is on` → 0; `EPIPE ENOENT SIGTERM` counted; `use the api key for env bus` → 5; `wasn't isn't` → 0; `memory_search` kept whole; `café résumé` → `{caf, sum}` | Tokenizer drift vs JS | drop `.lower()`; `>=2`; `>3`; split on `[^a-z0-9]`; `\W+` |
| C9 | `NOISE_WORDS` is exactly the 35 pi words | Dictionary drift | delete `wasn` |
| C10 | **Bun goldens:** `format_block(case) == golden_outputs[case]` for every committed case; every input has an output and the file records `pi_commit` | Wording/format drift from pi | change one char of the header; `str(rank)` |
| C11 | Trust header has all pi phrases; neither `you must fetch` nor `always fetch` | Softened/hardened wording | edit a trust line |
| C12 | Empty/empty → both placeholders; mem-only → `(no code hits)` under code only | Section vanishes | single `(no hits)` |
| C13 | 7+7 → `[m5]`,`[c5]` present, `[m6]`,`[c6]` absent | Cap wrong | cap 6 |
| C14 | `sourceFile`-only renders sourceFile; `path: ""` does not fall back | Path fallback semantics differ from `??` | `or` instead of `is None` |
| C15 | Drop when path missing/`?` and snippet blank; keep path-only and snippet-only | Wrong drop rule | `and` → `or` |
| C16 | Duplicate hash once, first wins; same snippet different hash once | Dedupe wrong | iterate reversed; require both keys |
| C17 | Snippet 301 → 300 + `…`, 300 untouched; query echo capped at 80 | Boundary; header bloat | `>` → `>=`; echo 300 |
| C18 | `one_line` over `\n \r \t \v \f \x85 U+2028 U+2029`: no line-breaking char survives; `"\n- code (snippets"` cannot start a line | Snippet forges structure | collapse only `[\n\t ]` |
| C19 | Path containing `\n- code` does not start a line (accepted divergence, O-2) | Path forges structure | interpolate raw path |
| C20 | Prune before cap: 5 dups of A then B, C → B and C render | Slice before dedupe | slice first |
| C21 | Rank table: `1.0`→`1`, `0.8123`, `0`→`0`, `None`/missing→`?`, `5e-05`→`0.00005`, `1e-7`→`1e-7`, `1e21`→`1e+21`, `"x"`→`?` | Python number formatting leaks | `str(x)`; `or "?"`; `repr` |
| C22 | Line-suffix table: `lineStart 0, lineEnd 5` → `:0-5`; `lineEnd` absent → no suffix; `lineEnd: null` → `:10-null` | Truthiness vs `!== undefined` | truthiness check; `is not None` |
| C23 | Non-BMP snippet truncates by code points and the block UTF-8 encodes (accepted divergence) | Lone surrogate crashes Hermes | slice by UTF-16 units |

### P2 transport and build: `tests/test_memory_context_transport.py` (34, plus G1–G3)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| T1 | `find_executable`: PATH hit wins; else `<home>/.dotnet/tools/ai-raccoon` if executable; non-executable or absent → `None`; PATH and home read at call time (resolves a fake set up after import) | Real executable captured at import; fallback runs a non-executable | hoist `Path.home()`; drop `X_OK` |
| T2 | **Spawn shape:** across every mode the spawn log is exactly `[[fake_abs]]` per run; `shell` false; stderr is DEVNULL | Shell spawn; argv injection; stderr noise | `shell=True`; add `--transport stdio`; inherit stderr |
| T3 | **Wire:** fake records `initialize` `2024-11-05`, then `notifications/initialized` with no `id`, then `tools/call` `memory_search` with arguments `== {projectId, sessionId, query, limit:5, scope:"project"}` | Cross-project leak; handshake broken | drop `scope`; add `kind`; skip the notification; limit 8 |
| T4 | `slowinit`: nothing is written before the `initialize` reply | Talking to an uninitialized server | write the call before awaiting init |
| T5 | `hits` → mem and code lists parsed from the text part | Permanent silence | read `result` not `content[].text` |
| T6 | `empty` → empty lists | Crash on empty | index `[0]` |
| T7 | `iserror` → `None` | Error text injected as memory | ignore `isError` |
| T8 | `rpcerror` → `None` | KeyError | read `result` unguarded |
| T9 | `malformed` framing: non-JSON lines and wrong ids interleaved before the real reply → parsed | Fragile framing | first line only; no id check |
| T10 | `malformed` payload table: no text part / non-JSON text / missing `results`/`code` → `None` / `None` / empty lists | Crash on drift | unguarded `json.loads`; index directly |
| T11 | `crash` → `None` quickly; child reaped | Crash stalls or leaves a zombie | no `wait()` |
| T12 | `hang`, budget 0.3 → returns within 2 s; child pid gone | Prompt blocks; orphan | drop the deadline; kill without wait |
| T13 | `drip`, budget 0.3 → returns within 2 s. **Written first against blocking `readline()`; the watchdog must fire** | Per-line deadline only | blocking `readline()` |
| T14 | `nostdin` with a 1 MiB query, budget 0.3 → returns within 2 s | Blocking write holds the hook | blocking `stdin.write` |
| T15 | `oversize` → `None`, reading stops, child killed | Memory blow-up | remove the cap |
| T16 | `search`/`build` never raise: parametrized over every mode | Fail-silent broken in general | remove outer `except` |
| T17 | No zombie, no thread: 20 sequential runs over `hits`/`hang`/`crash` → every recorded pid is gone and `threading.active_count()` is unchanged | Zombies/threads accumulate in Hermes | skip `wait()`; use a reader thread |
| T18 | Graceful close: in `hits`, the fake records `saw_eof` and exits by itself; no SIGKILL within the grace | Proxy dispose path skipped | kill before closing stdin |
| T19 | `grandchild`: the grandchild (same group) survives the hook's kill; test reaps it | Group kill takes down the shared serve (O-1) | `killpg` |
| T20 | Spawn failure (`PermissionError`, `FileNotFoundError` raced after resolution) → `None`, no raise | Crash on race | unguarded `Popen` |
| T21 | **Pipeline seam:** one `RaccoonSession`, two `search()` calls → one spawn, one `initialize`, two `tools/call` with ids 2 and 3 | One proxy per query | reopen per search; reuse id |
| T22 | `Budget`: `child(s)` never outlives the parent; an expired budget makes `search` return `None` without writing | Stages overrun the run deadline | child uses its own `now + s` only |
| T23 | `sys.platform == "win32"` → `None`, 0 spawns (O-3) | Selector on pipes raises | remove the platform guard |
| T24 | **(rev 3) Late reply:** `latereply`, search A with budget 0.2 times out after its line is fully written; search B then returns B's hits even though A's reply arrives first; 3 `tools/call` lines total when a third search follows | Planned search N gets query N−1's hits | accept the first reply; poison on read timeout |
| T25 | **(rev 3) Poisoned session:** after `nostdin` (partial write), `oversize`, or `crash`, every later `search` returns `None` in < 0.05 s and writes nothing (fake line count unchanged) | Each remaining planned query waits its full share on a dead child | keep writing after a partial write |
| S1 | **Static** (`ast` over all six new modules): exactly one `Popen` call site (in `memory_context.py`); no `shell=` truthy; no `os.system/popen/exec*/spawn*/posix_spawn*/fork`; no `multiprocessing`; no `"pi"` in argv position; `urllib`/`http.client`/`ssl` imported only by `openrouter_client.py`; no `urlopen`, `install_opener` or `build_opener` call outside `openrouter_client.py` and none of `urlopen`/`install_opener` inside it; every `ProxyHandler(` call has the literal `{}` | A second spawn or network path on an undriven branch | add `subprocess.run(["pi", …])`; add `urllib.request.urlopen(url)` in the planner |
| B1 | Kill switch `"0"` → 0 spawns, 0 HTTP requests, and `resolve_project_id` never called | Switch checked after work | reorder |
| B2 | Kill switch table `""`, `false`, `off`, `no`, `00`, `" 0"` → enabled, 1 spawn | Truthiness widens the switch | `strip().lower() in {…}` |
| B3 | Default-on table: id + executable → 1 spawn; no executable → 0; no id → 0; unset switch | Fires without ai-raccoon; accidental opt-in | skip executable check; default `"0"` |
| B4 | Project id table: from `proj/a/b` → `proj`'s id; env `" X "` → `X` and wins; blank env ignored; nested `.ai-badger/` without id → 0 spawns; blank file → 0 spawns. Sent `projectId` read from the fake log | Cross-project search | continue the walk; no strip |
| B5 | Gate skip (each reason) → `None`, 0 spawns, 0 HTTP | A spawn on every prompt | search before gate |
| B6 | Blank session → `None`, 0 spawns; control → 1 | `isError` each prompt | send `"unknown"` |
| B7 | Only droppable hits → `None` | Empty block injected | format when both empty |
| B8 | 10 000-char prompt → sent `query` equals the trimmed prompt | Silent truncation | add a cap |

### Q1: `tests/test_memory_context_openrouter.py` (9, plus G4)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| O1 | **No proxy:** with `http_proxy`/`https_proxy`/`all_proxy` pointing at the capture server and `no_proxy` unset, `post_json` to the fake reaches the fake; the capture server records 0 requests | Key and prompt sent through an env-configured proxy | `ProxyHandler()` (default) |
| O2 | **No redirect:** fake answers 307 `Location: <capture>/x` → `Reply.status == 307`; the capture server records 0 requests (so no `Authorization` was forwarded) | Key forwarded to a redirect target | default `HTTPRedirectHandler` |
| O3 | **TLS:** the opener's HTTPS handler holds a context with `verify_mode == CERT_REQUIRED` and `check_hostname` true, built by `ssl.create_default_context()` | Unverified TLS to OpenRouter | `ssl._create_unverified_context()` |
| O4 | **Drip bound:** `header-drip` and `body-drip` (1 byte / 0.05 s for 10 s) with a 0.3 s child budget → returns `timeout` within 1.5 s; `threading.active_count()` back to baseline | A dripping server holds the prompt past its stage share | remove the watchdog; skip the timer `join()` |
| O5 | **Hang bound:** `hang` (accept, never answer) with 0.3 s → `timeout` within 1.5 s | Blocking read with no timeout | `timeout=None` |
| O6 | **Expired budget:** `post_json` with `remaining() <= 0` → `timeout`, fake records 0 connections | A stage runs after its share | drop the pre-check |
| O7 | **Oversize:** a 2 MiB body → `transport`; the client stops reading at 1 MiB | Memory blow-up | remove the cap |
| O8 | **Base URL table:** unset → `https://openrouter.ai`; `http://127.0.0.1:<port>` accepted; `http://localhost:<capture>`, `http://127.0.0.2:<capture>`, `http://[::1]:<capture>`, `https://127.0.0.1:<port>`, `http://user@127.0.0.1:<port>`, `http://127.0.0.1.example.com:80`, `http://127.0.0.1` (no port), `http://127.0.0.1:<port>/api` (path) → refused: `api_base` is `None`, the planner reports `transport`, the capture server and the fake record 0 requests | A test seam that ships the key to any listener | substring `"127.0.0.1" in url`; accept any loopback; fall back to production on refusal |
| O9 | **Key:** read from `env["OPENROUTER_API_KEY"]` only, stripped, blank → `None`; a `.env` in cwd and `~/.openrouter` in the temp HOME holding a key are ignored (0 requests); the fake sees `Authorization: Bearer <key>` and `Content-Type: application/json`; across every O-row the key string is absent from stdout, stderr, `caplog`, every returned value and every exception `str` | Key read from disk; key logged | read a dotenv; include the request in an error message |

### Q2a: `tests/test_memory_context_planner.py` (7)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| PL1 | Goldens: `PLANNER_ADDENDUM`, `PLANNER_USER_PREFIX` and `build_user_prompt(q)` for every recorded input (incl. tricky characters) equal pi's bun output; system prompt is `DELEGATOR_PERSONA + "\n\n" + PLANNER_ADDENDUM` (pi P12, P13, `planner-parser.test.ts:224-236`) | Prompt drift from pi | edit one char; `"\n"` separator; strip the query |
| PL2 | `DELEGATOR_PERSONA` equals `features/common/personas/delegator.md` from `# Delegator` to the end; contains no `name: delegator` and no `Managed by` (pi P11 re-pointed at the catalog source; MEASURED equal to pi's unescaped constant this session) | Persona twin drifts from its source | edit one char in the constant |
| PL3 | `parse_plan` golden corpus: every recorded input → pi's `{status, reason, plan}`; never raises. Corpus: P1 fragment-then-complete, P2 trailing prose, P3 unterminated, P4 blank, P5 bad shapes, P6 empty concepts / empty queries, P7 300 vs 301, P8 >6 truncation, P9 trimming, P10 malformed corpus, braces inside strings, 5 queries in one concept (cap 4), 121-char name | Parser drift from pi | first span instead of last; strict reject instead of truncate; count braces in strings; `>=` at 300; per-concept cap 5 |
| PL4 | Request through the fake: `POST /api/v1/chat/completions`, body exactly `{"model", "messages":[{"role":"system",…},{"role":"user",…}]}` with no other key (no `max_tokens`, `temperature`, reasoning field: pi sets none, spec §2.5) | Request shape drift; unapproved params | add `temperature`; swap roles |
| PL5 | Model table: override `vendor/m` → sent verbatim; override `openrouter/vendor/m` → `vendor/m`; override without `/` → `no-model`, 0 requests; unset → the `medium` preferred id of a fixture `.ai-badger/model-groups.json` through the scaffolded `model_groups.py` (copied from the catalog at test time), prefix removed; registry whose `medium[0].id` breaks `ID_RE` → `no-model` (the resolver refuses to emit); resolver file absent → `no-model`; key missing → `no-model`, 0 requests | Tier logic re-implemented; wrong wire id; a request with no key | read `groups["medium"][0]["id"]` directly (the `ID_RE` case goes red); skip the prefix strip; send without a key |
| PL6 | Reply table: `content` string → parsed; `content` as a parts list → text parts joined, others ignored; missing `choices`/non-string → `empty-text`; non-JSON body → `transport`; 500, 401 and 307 → `transport`; `hang`/`body-drip` → `timeout` within the child share | Reasoning text parsed as the plan; redirect treated as success | read `reasoning`; accept any 3xx |
| PL7 | Reason vocabulary: every result's reason is in `PLANNER_REASONS`, which equals pi's `PlannerFallbackReason` golden list; `plan` never raises across PL5 and PL6 | New reason strings; a raise escapes | add `"http-error"`; remove the outer `except` |

### Q2b: `tests/test_memory_context_jev.py` (9)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| J1 | Constants and prose equal pi's goldens: batch 12, attempts 3, attempt 15 s, state cap 32 000, excerpt cap 500, model `typesafe/jev-1.13`, path `/api/alpha/decisions`, `SCORE_QUESTION`, the four `SCORE_CRITERIA` (also equal to `score-fixtures.ts` `MEASURED_CRITERIA`/`MEASURED_QUESTION`, converted to JSON) (pi S1) | Wire prose drift | change a criterion char; batch 13 |
| J2 | Wire goldens: for each recorded candidate set, the request bodies the fake receives equal (as parsed JSON) the bodies pi's `createJevScorer` sent to a capturing `fetchFn`: `{model, state, questions:{c<i>:{type:"score", instructions:{candidate:{path, kind, excerpt}, question}, criteria}}}`; path `path ?? sourceFile ?? ""`; kind default `memory`; excerpt ≤ 500 and state ≤ 32 000 (code points) (pi S13, S13b, path fallback) | Request shape drift | `or` for path (`""` falls back); cap 499; name by hash |
| J3 | Batching: 25 candidates → requests of 12/12/1, each carrying only its own names; 12 → 1; 13 → 2 (pi S2, S3) | Oversized or mixed batches | batch 13; reuse the first batch's names |
| J4 | Status table through the fake: 400 → `misrouted-refusal`, 401 → `auth`, 402 → `billing`, 429 → `rate-limited`, 500 → `server`, 307 → `server` (never followed), 200 error envelope → `server`, 200 truncated / non-object → `malformed`; `ERROR_KINDS` and `RETRYABLE_KINDS` equal pi's golden lists; `classify` never raises (pi S7, S12, error-kind parity) | Error envelope scored; vocabulary drift | treat the envelope as ok; add a kind |
| J5 | Retries: 500 then 200 → 2 requests and scores from 200; 500 × 4 → exactly 3 requests; 401, 402, 400 → exactly 1; 429 twice then 200 → 3 requests with elapsed < 0.5 s (Retry-After never slept on) (pi S4, S5, S6, S8) | Retry storm; retry on auth; a sleeping hook | attempts 4; retry `auth`; `time.sleep(retry_after)` |
| J6 | Deadlines: attempt 1 `hang`, attempt 2 ok → scores from attempt 2 and the attempt-1 socket is closed; each attempt's child share is `min(15, deadline − now)` (fake clock); remaining ≤ 0 → all `None`, 0 requests; key missing or blank → all `None`, 0 requests (pi S9, S16, per-attempt, non-positive, S10) | A late reply corrupts the next attempt; attempts ignore the stage share | use 15 s regardless of the deadline; send without a key |
| J7 | One failed batch (401 on batch 2 of 3) leaves batches 1 and 3 scored; batch 2's candidates `None` (pi S14) | One failure nulls everything | return all `None` on any failure |
| J8 | Answer tolerance: missing answer → `None`, never 0; wrong `type`, non-number, NaN/inf → `None`; 4.2 → 3, −1 → 0; extra fields (`probabilities`, `legend`) ignored; results align with input order (pi S11, clamp, `PARTIAL_ANSWERS`, `WRONG_SHAPES` fixtures) | Fabricated zeros rank junk above unscored hits | `score or 0`; skip the clamp |
| J9 | Leak: with the `SYNTH_SCORE_BAD_REQUEST_BODY` fixture (`SECRET-BODY-MARKER`) and every error fixture, neither the marker nor the key appears in any returned value, stdout, stderr or `caplog` (pi S15) | Upstream error text or key surfaces in the prompt or logs | carry the body into the outcome |

### Q2c: `tests/test_memory_context_pipeline.py` (10)

Every row drives `run(...)` with fake `plan`/`search`/`score` callables, the real `prune_hits` from
`memory_context.py`, and a `Budget` on a fake clock the fakes advance.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| MG1 | **Merge goldens:** `merge_select(case)` equals pi's `mergeSelect` bun output for every recorded case: M1, M2, M3a, M3b, M3c, M4, M5, M6, M7, M8, M9, M10, M11, M12, M13, M14, M20 (shared 5 slots across kinds; pass 1 one chunk per document including null-scored ones; pass 2 only from admitted documents, global rank order, no repeated hash; ties keep retrieval order; `?`/empty path falls to `hash:`) | Merge drift from pi | per-kind slots; nulls before scores; pass 2 admits new documents; unstable tie; `?` treated as a path |
| MG2 | `server_rank` table: `3` → 3; `"2.5"` → 2.5 (pi M21); `"x"`, `None`, `nan`, `inf` → last (pi M22); `"0x10"`, `"1_000"` → last (accepted divergence, §1.5) | Rank parsing leaks Python `float` semantics | `float(raw)` |
| R1 | Stage order and searches: plan once with the query verbatim; one `search` per deduplicated planned query, sequentially, in plan order, never for the input query; then one `score` over the pool (pi R1, R2, R10) | Input query searched; order lost | also search the input; iterate a set |
| R2 | `dedupe_queries`: trimmed, blanks dropped, duplicates dropped, a query equal to the trimmed input dropped; all dropped → fallback `invalid-shape` with one search on the input (pi `pipeline.ts:118-131`, `:314`) | Duplicate searches waste the budget | do not seed the input; compare untrimmed |
| R3 | **Runner goldens:** for each recorded scenario (planner ok; planner each failure reason; planner raises; zero usable queries; all searches fail; one search fails; zero candidates; score raises; score returns partial nulls), `(status, reason, mem hashes, code hashes, queries searched)` equals pi's `runPipeline` bun output; the fallback search's success keeps the original planner reason (pi `pipeline.ts:286`) (pi R12, R4, R7, R8, "one failed", "all failing") | Fallback semantics drift from pi | report `"ok"` on fallback; search planned queries after a planner failure |
| R4 | Reason vocabulary: every returned reason is in `PLANNER_REASONS ∪ RUN_REASONS` (`ok`, `no-candidates`, `search-error`, `budget-exhausted`); the set equals pi's golden list minus `aborted` (unreachable: no external signal in a hook) | Unported or invented reasons | add a reason |
| R5 | Budget arithmetic (fake clock, pi R9, R11): planner share `min(15, max(0, 90 − 15 − 8))`; each search share `min(15, max(0, remaining − 8))`; the loop stops once `remaining ≤ 8.5`; score share `min(deadline, now + 8)`; fallback with `left < 1` → empty `search-error`-free result with the planner reason, else share `min(15, max(0, left − 8))`; a run whose clock passes the deadline during scoring → `budget-exhausted`, empty | Stages overrun the total or starve scoring | search share = 15 alone; planner cap ignores the reserve; drop the final expiry check |
| R6 | Search failures: a `None` from search N is skipped and N+1 still runs; every search `None` → exactly one fallback search, then `search-error` with empty lists if it fails too; `run` never raises when any fake raises | One bad query cancels the rest; a raise escapes | `break` on failure; remove the stage `try` |
| R7 | **Score failure keeps the pipeline (pi parity, O-6):** `score` raises, times out, or returns all `None` → status `pipeline`, reason `ok`, the pool merged by server rank, exactly N planned searches and no fallback search | Planned hits thrown away and a redundant search run | call the fallback on score failure |
| R8 | Pool: `prune_hits` applied to memory and code separately (a memory hit and a code hit sharing a hash both survive, pi M18/parity); droppable hits never reach a slot (pi M15); pool sorted by `server_rank` with insertion tiebreak, then capped at `POOL_MAX` 48 (pi pool-cap row); scores joined by hash, a hash absent from the scores → `None` | Cap before sort; cross-kind dedupe; index-joined scores | cap before sort; prune the concatenation; join by position |

### Q3: `tests/test_memory_context_pipeline_wiring.py` (6)

Real `build()` with the fake `ai-raccoon` (`perquery`), the fake OpenRouter via the injected base URL,
a fixture project with `.ai-badger/project-id`, `.ai-badger/model-groups.json` and
`.ai-badger/skills/task/scripts/model_groups.py` copied from the catalog.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| B9 | **End to end:** key set, planner returns 3 queries, Jev scores → exactly 1 spawn, 1 `initialize`, 3 `tools/call` (ids 2, 3, 4) each with `scope:"project"` and `limit:5`, 1 planner request, ⌈pool/12⌉ Jev requests; the result equals `format_block(prompt, prune(mem)[:5], prune(code)[:5])` over the MG1-style expected merge | One proxy per query; merge skipped; block format changed | open a session per query; return the unmerged pool |
| B10 | Missing key → 0 HTTP requests, exactly 1 `tools/call` whose `query` is the gated prompt, block identical to the pipeline-off output for the same fake hits | A request without a key; a different block in fallback | call the planner without a key; skip prune in fallback |
| B11 | Pipeline switch: `AI_BADGER_MEMORY_CONTEXT_PIPELINE="0"` with a key → 0 HTTP requests, 1 search, run budget `SINGLE_BUDGET_SECONDS` (observed through a `hang` fake returning within 5 s + 1 s); switch table `""`, `false`, `off`, `00`, `" 0"` → pipeline on; read at call time (pi E4, E8) | Truthiness widens the switch; switch cached at import | `strip().lower()`; read at import |
| B12 | Planner failure (500) → 1 fallback search on the gated prompt, block from it; Jev failure (500 × 3 on every batch) → no extra search, block from the planned searches ordered by server rank | Wrong fallback trigger | swap the two branches |
| B13 | A pipeline sibling missing or raising at import (each of the four, parametrized) → single-search mode, no raise, block present | One bad module kills memory context | unguarded sibling load |
| B14 | Stage bounds through `build()`: planner `body-drip` + Jev `hang` + a 3-query plan with total budget scaled to 3 s (limits passed as parameters) → `build()` returns within 3 s + 1 s, the proxy child is gone, thread count back to baseline | Stage shares add up past the total | give each stage its own fresh budget |

### P3a: `tests/test_memory_context_hook.py` (13)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| H1 | Payload + id + fake `hits` → exactly one JSON line, `hookEventName:"UserPromptSubmit"`, `additionalContext == format_block(...)`, exit 0; no `decision`/`prompt` keys | Envelope drift; hook rewrites input | rename key; print twice; add `"prompt"` |
| H2 | `sessionId` spelling accepted and sent | Copilot always silent | read only `session_id` |
| H3 | `iserror` and `crash` → silent stdout, empty stderr, tmp `hook-errors.log` unchanged, fake invoked exactly once (QA S11) | Expected states logged; routing unproven | route to `record_hook_failure` |
| H4 | `build` raises `RuntimeError` → exit 0, silent stdout, exactly one log line, no prompt text | Invisible bugs; privacy leak | log `repr(payload)`; swallow unlogged |
| H5 | Non-JSON, JSON array, empty stdin → exit 0, silent, 0 spawns | Crash on odd hosts | `.get` on list |
| H6 | Payload `cwd` (id A) beats `CLAUDE_PROJECT_DIR` (id B); absent cwd → B | Worktree/main confusion | prefer `CLAUDE_PROJECT_DIR` |
| H7 | Subprocess `[sys.executable, hook]`, HOME tmp, PATH fake bin, no key → rc 0, block on stdout, fake invoked once | In-process green, spawned broken | import sibling by package name |
| H8 | Subprocess `hang` (and `drip`) with a 0.3 s test budget via a test-only module constant patch in a wrapper script → process exits in bound, rc 0, empty stdout, fake pid gone afterwards (QA S5) | Hook process outlives its budget; orphaned proxy | kill without reap; blocking read |
| H9 | Hook copied alone (sibling missing) → rc 0, silent | Broken sibling blocks prompts | unguarded top-level import |
| H10 | Stdout closed by the host → exit 0, no traceback (security N5) | Exit 120 on BrokenPipe | remove the wrapper |
| H11 | `f: …` prompt → sent query contains `f:` alongside the prompt-markers hook on the same event | Two hooks interfere | strip markers |
| H12 | **(rev 3) Pipeline through the real entry:** subprocess from a scaffold-shaped temp tree (`.ai-badger/skills/ai-raccoon-memory/scripts/` with the six files, `.ai-badger/skills/task/scripts/model_groups.py`, registry), env `OPENROUTER_API_KEY=sk-test-…` + `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE=http://127.0.0.1:<port>`, sitecustomize network guard → the fake records 1 planner request and ≥ 1 Jev request, the block is on stdout, the key is absent from stdout and stderr, the guard marker is absent | Pipeline green in-process, inert in the scaffold layout | resolve siblings from cwd instead of `__file__` |
| W2a | `hooks.json` `timeout` for the command > `max(SINGLE_BUDGET_SECONDS, PIPELINE_TOTAL_SECONDS) + GRACE_SECONDS` (loaded from the modules) | Host kills the hook mid-pipeline | `"timeout": 10` |

### P3b: `tests/test_memory_context_hermes.py` (+ extended `test_hermes_plugin_install.py`) (14)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| W1 | Real payload (`session_id`, `user_message`) and `message=` variant + fake → `context` contains the block; sent `sessionId` = `"s"` | Kwarg mismatch | read only `user_message` |
| W2 | The block is the last part and is followed by `(end of memory context)` (security MUST-3) | The trust header swallows the user's message | drop the terminator; insert first |
| W3 | Sibling missing → other parts returned, "missing" logged once | One feature kills all injection | early return |
| W4 | `build` raises → other parts returned, no raise, warning has the exception type and no prompt text | Prompt text in logs | `exc_info=True` |
| W5 | Gate skip → no block, 0 spawns | A spawn every call | bypass gate |
| W6 | Project without `.ai-badger/skills/ai-raccoon-memory/` → 0 spawns; control → 1 | Declined skill still searches on Hermes | remove the decline check |
| W7 | Gateway/platform policy per P3b.0 and O-5 | Remote chat users get project memory | ignore the platform kwarg |
| M1 | Same (session, prompt) twice → 1 spawn, 1 planner request; both calls return the same block | N pipelines per tool loop | remove memo; return `None` on hit |
| M2 | Same session, new prompt → runs again; memo holds one entry for that session | Memo too sticky; unbounded | key on session only; append |
| M3 | Failure (`crash`) memoized: the second identical call spawns 0 | N × budget per loop during an outage | memoize successes only |
| M4 | `on_session_start_drift_notice`, obtained through `register()` with a fake ctx, clears the memo | Production never clears | clear in an unregistered function |
| W8 | `adjust()` into tmp HOME → all six modules in project `.ai-badger/hooks/` and `~/.hermes/plugins/ai-badger/`; `LEGACY_FLAT_FILES` contains them | Arm inert; pipeline absent in Hermes | drop one tuple row |
| W9 | In-process `hang` through `pre_llm_inject_context` → returns within budget + 1 s; no child pid remains; thread count unchanged | Zombie or thread in the long-lived gateway | skip `wait()` |
| W10 | **(rev 3)** The installed plugin dir (tmp HOME) runs the pipeline against the fakes; every pipeline module and `model_groups` in `sys.modules` has `__file__` under the plugin dir, none under the project tree; a planner `body-drip` returns within its share and the thread count is back to baseline | Hermes executes project-controlled code; watchdog thread leaks in the gateway | load `model_groups.py` from the project's `.ai-badger/skills/task/`; skip the timer `join()` |
| — | Existing `SHARED_SKILL_FILES` equality (`:205-208`) and sibling-load derive (`:405-436`) | Row mismatch | omit either row |

### P4: `tests/test_memory_context_integration.py` (12)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| I1 | Manifest `memory-context`: claude + hermes arms; copilot arm (A) or exemption (B); no `pi` key. Removing an arm (or the B exemption) → `hooks_manifest_agent_gaps` red | Registered, never run; exemption unenforced | drop an arm |
| I2 | `hooks_manifest_unresolved(ROOT) == []`; deleting the `memory_context_hook.py` command → gaps for claude (+copilot in A) | New wiring unprotected | typo the script |
| I3 | `HookWiring.wire()` on the real manifest: settings `UserPromptSubmit` names it, `guarded()`, `timeout` 100 kept; script absent → "not scaffolded — skipped" | Timeout stripped; missing file wired | drop timeout in rewrite |
| I4 | `config.exclude: [ai-raccoon-memory]` → not wired for Claude | Declined skill fires | skip `declined_skill` |
| I5 | Branch A: generated Copilot `userPromptSubmitted` ⊇ existing hooks + ours, `timeoutSec` > the larger budget (W2b). Branch B: `.github/hooks/ai-badger-hooks.json` does not name `memory_context` | Neighbour dropped; latency tax with dropped output | overwrite list; add arm |
| I6 | **Fired in anger, Claude:** the exact command string from the scaffolded `.claude/settings.json`, `${CLAUDE_PROJECT_DIR}` substituted, run by `sh -c` with cwd = an empty temp dir, HOME tmp, PATH = fake bin (fake `ai-raccoon`, `python3` symlink, and a marker-writing `pi`), sitecustomize network guard → block on stdout, no `systemMessage`, the first `guarded()` branch's path exists, fake invoked once, `pi` marker absent. Paired run with `AI_BADGER_MEMORY_CONTEXT=0` → silent, 0 invocations | Shipped, never ran; guarded fallback masks a bad rewrite | break the path rewrite |
| I7 | Branch A: the generated Copilot `bash` string fed the captured P0 payload → block | Relative path or payload shape wrong | wrong `hooks_rel` |
| I8 | **pi executes nothing:** (a) no `pi` arm; (b) `.pi/**` and the tmp-HOME pi extension dir contain none of the six files; (c) the pi adapter's `before_agent_start` spawns only `DELIVERY_SCRIPT` and no adapter `.ts` reads a `UserPromptSubmit` key from `HOOKS_CONFIG`; (d) pi's copy list lacks all six; (e) a pi-only scaffold has no `.ai-badger/hooks/memory_context.py` | A generic `UserPromptSubmit` replay runs it under pi | add a replay loop to the adapter; add a file to pi's list |
| I9 | Composed scaffold (`claude, copilot, hermes, pi`): Claude settings and Hermes dirs carry it (all six modules in Hermes dirs); Copilot per branch | Per-adjuster green, composition broken | drop a Hermes `SHARED_SKILL_MODULES` row |
| I10 | Scaffold twice → exactly one `memory_context_hook.py` and one `user_prompt_hook.py` entry per event | Double injection | break `_hook_key` |
| I11 | **Fired in anger, Hermes:** reset fixture, import `ai_badger_hooks` from the installed tmp-HOME plugin dir, assert `sys.modules[key].__file__` is under that dir, call `pre_llm_inject_context` against the fakes → block present | Source green, installed inert | drop the `SHARED_SKILL_MODULES` row and run after W1 in one process |
| I12 | Every spawn recorded across this module is the fake, never the real executable, never `pi`; the network guard marker never appears | Live bank or network reached from an integration path | point PATH at the inherited PATH |

**Totals:** G 4, P1 16, P2 core 23, P2 transport/build 34, Q1 9, Q2a 7, Q2b 9, Q2c 10, Q3 6, P3a 13,
P3b 14 (+2 existing), P4 12 = **157 rows** (rev 2: 111; rev 3 adds 46: G4, T24, T25, H12, W10,
O1–O9, PL1–PL7, J1–J9, MG1, MG2, R1–R8, B9–B14).

### 6.1 pi's 115 query-pipeline tests: port map

pi run: `bun test tests/query-pipeline/` → 115 pass (spec §5, MEASURED); per-file counts re-MEASURED
this session (extension 9, merge 24, parity 5, planner-call 18, planner-parser 13, runner 20,
score-client 26).

| pi file (tests) | Ported to | Not ported, and why |
|---|---|---|
| `merge.test.ts` (24) | M1–M14, M20 (17) → MG1 cases; M21, M22 → MG2 | M15–M19 (5): dedupe is `prune_hits` itself (one implementation, C21), already pinned by C15, C16, C20; the per-kind property is R8 |
| `parity.test.ts` (5) | mem/code independence and droppables → R8 | assignable-type (no structural typing in Python); dedupe == pruneHits (structurally true, C21); `retrieve == toEnvelope` (no envelope string: `build()` consumes lists) |
| `planner-parser.test.ts` (13) | P1–P10 → PL3 corpus; P11 → PL2; P12, P13 → PL1 | — |
| `planner-call.test.ts` (18) | request shape → PL4; text parts, empty-text, invalid-shape, transport, timeout → PL6; env ref split, no-slash, unresolved model → PL5; never throws → PL7; last-complete-object through the call → PL6 | signal forwarding (no signal); absent `find`/`complete` (no registry; replaced by resolver/key rows in PL5); env unset → session model (no ambient model in a hook; replaced by the `medium` tier, spec §2.5); no-pi-ai-import static row |
| `runner.test.ts` (20) | R1, R2, R10 → R1; R12, R4, R7, R8, one-failed, all-failing → R3/R6; R9, R11 → R5; search limit 5 → T3 | R5/R6/formatProgress (no progress UI in a hook); `resolvePipelineBudget` env clamps (no tuning env vars, §1.3); external abort (no signal; `aborted` unreachable, R4); `toEnvelope` × 2; counters from the clock (not exposed, C10) |
| `score-client.test.ts` (26) | S1 → J1; S7, S12, kind parity → J4; S2, S3 → J3; S13, S13b, path fallback → J2; S4, S5, S6, S8 → J5; S9, S16, per-attempt, non-positive, S10 → J6; S14 → J7; S11, clamp → J8; S15 → J9; pool cap 48 → R8 | usage sums (usage unused in v1, C10); warm × 2 (no session lifecycle, spec §7.1.6) |
| `extension.test.ts` (9) | E4, E8 (switch and env read per call) → B11; E5 (missing key) → B10 | E1–E3, E6, UI and registry smoke rows: pi's long-lived session lifecycle has no analogue in a one-shot hook (spec §5.7) |

---

## 7. Twin lists and registries

| Registry | Change | Enforcing check |
|---|---|---|
| `features/common/hooks/hooks-manifest.json` | `memory-context` entry (P4) | `validate --all`: schema, `hooks_manifest_agent_gaps`, `hooks_manifest_unresolved`; `test_hooks_manifest_agent_coverage.py`; `test_pi_hook_arm_coverage_contract.py` |
| `features/common/hooks/hooks.json` ↔ manifest `script` | `user_prompt_hook.py` (P1), `memory_context_hook.py` (P3a) | `hooks_manifest_unresolved`; I3, V14, V15 |
| Copilot event map | Moved to `engine/badger_lib.py`, imported by both | V5 |
| `tooling/validate.py` `_report` list | +1 line | V12 |
| `tests/test_every_check_can_fail.py` REGISTRY + fixture helper | New check; helper writes a resolving `hooks.json` | V13, V16 |
| `tests/test_validate.py`, `tests/test_skills_lint.py` fixture helpers | Resolving `hooks.json` | V16 |
| `HOOK_CAPABLE_AGENTS` | Unchanged | `test_pi_is_not_a_hook_capable_agent_today` |
| `HOOKS_MANIFEST_AGENT_EXEMPTIONS` | Branch B only | `test_hooks_manifest_agent_coverage.py`; I1 |
| Hermes `SHARED_SKILL_MODULES` + `SHARED_SKILL_FILES` twin | +6 rows each (§0) | `test_hermes_plugin_install.py:205-208`, `:405-436`; W8, W10, I9, I11 |
| `LEGACY_FLAT_FILES` | Derived | W8 |
| Plugin mirror `skills/ai-raccoon-memory/scripts/` | +6 files | `sync_plugin_skills --check`, `TestRealCatalogParity` |
| `index.json` | Regenerated per package | `index_build --check` |
| Self-scaffold outputs | Regenerated per package | `gates/scaffold_freshness_guard.py` |
| `VERSION` + stamped JSON | 0.178.0 in P1 | `version_sync --check`; `release_guard` |
| Changelog entry + README row | Stub P1, text P4 | `changelog_index --check`; `docs_guard` |
| `docs/adr/0031-…`, `docs/adr/0032-…` + README rows | New ADRs (P2, Q0) | `docs_guard` |
| Block goldens ↔ pi `rag-core.ts` | Committed with `pi_commit` | C10 |
| Pipeline goldens ↔ pi `query-pipeline/*.ts` (planner prose and parser, Jev prose/wire/kinds, merge, runner scenarios, reason lists) | Committed with `pi_commit` (Q0) | PL1, PL3, PL7, J1, J2, J4, MG1, R3, R4 |
| `score-fixtures.ts` → `score_fixtures.json` | Converted by running bun over the module's exports (no retyping) | J1, J8, J9 |
| `DELEGATOR_PERSONA` ↔ `features/common/personas/delegator.md` | Constant compared with its source | PL2 |
| Planner model | No copy: the one `model_groups.py` loaded by path; Hermes gets a generated copy through `SHARED_SKILL_MODULES` | PL5, W10 (§9.7) |
| Prune rule (pi has two) | One implementation, passed into the runner | R8 (C21) |
| Pool cap (pi has two) | Runner only | R8 (C22) |
| Budget constants ↔ Claude `timeout` ↔ Copilot `timeoutSec` | Derived comparison | W2a, W2b (I5) |
| Env switch names (`AI_BADGER_MEMORY_CONTEXT`, `…_PIPELINE`, `…_PLANNER_MODEL`, `…_TEST_OPENROUTER_BASE`) ↔ SKILL.md/ADR prose ↔ test scrub list | Scrub list is a module constant imported by the fixtures from `memory_context.py` (`ENV_NAMES`), so the list and the code cannot disagree | G2 |
| Message-bus reconciler (`test_message_bus_manifest.py:206-217`) | Becomes a subset twin of F2 | Follow-up issue (derive-or-delete), not this task |
| Prose: `SKILL.md`, `docs/skills.md`, `docs/dictionary.md`, `docs/hermes-claude-compatibility.md` | P4 | review |

## 8. VERSION and changelog

- `VERSION` 0.177.3 → 0.178.0 in P1 (minor: a new user-visible feature); `version_sync` in P1.
- `docs/changelog/0.178.0-per-prompt-memory-context.md` (stub in P1, final in P4) states: the hook,
  its agents and the Copilot outcome; the proxy transport (the hook never touches the token; the
  proxy may start a serve); the query pipeline (planner model and its override, Jev, merge, pi's
  fallback) and that it runs whenever `OPENROUTER_API_KEY` is exported, sending the prompt and hit
  excerpts to OpenRouter; default-on when a project id and the `ai-raccoon` executable exist; the
  literals `AI_BADGER_MEMORY_CONTEXT=0` and `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0`; measured cost per
  mode from the demo, and the 90 s / 5 s caps; each enriched prompt and planned query writes a
  search-log row; the parity divergences; the new `validate.py` arm-resolution check; prompt-markers
  now wired explicitly (Copilot `timeoutSec` 5 → 10); every renamed or rewritten test by name.
- Rebase last. Release tagging is automated; fetch tags before push.

---

## 9. The query pipeline (the slot rev 2 reserved)

### 9.1 Shape

Four modules beside `memory_context.py`, each taking its effects as parameters:

```
memory_context.build()
  ├─ openrouter_client  post_json, api_key, api_base          (the only HTTP)
  ├─ query_planner      plan(query, *, post, base, key, model_source, budget)
  ├─ jev_scoring        score(query, pool, *, post, base, key, budget)
  └─ query_pipeline     run(query, *, plan, search, score, prune, budget, limits)
```

`memory_context.py` loads each by path from `Path(__file__).parent` under a distinctive
`sys.modules` key (`ai_badger_memory_context__<name>`), the same pattern it uses for `badger_store`.
In the Claude scaffold the siblings sit in `.ai-badger/skills/ai-raccoon-memory/scripts/`; in both
Hermes destinations they sit flat beside `memory_context.py`. The pipeline modules never import each
other or `memory_context`; tests import each alone. Size estimate (spec §7.2, INFERRED): ~120 +
~250 + ~250 + ~220 lines, about 25% under pi's 1 710 TypeScript lines.

### 9.2 `build()` with the pipeline, and the runner

```
build(prompt, cwd, session_id, *, env, home, budget=None, limits=None):
  kill switch "0"            → None (no spawn, no HTTP)
  should_enrich(prompt)      → skip → None
  project id, executable, session id → any missing → None
  pipeline = env PIPELINE != "0" and all four siblings loaded
  run_budget = budget or Budget(PIPELINE_TOTAL_SECONDS if pipeline else SINGLE_BUDGET_SECONDS)
  session = RaccoonSession.open(exe, …, run_budget.child(SEARCH_SECONDS) if pipeline else run_budget)
  try:
    if pipeline: result = query_pipeline.run(query, plan=…, search=session.search, score=…,
                                             prune=prune_hits, budget=run_budget, limits=limits)
                 mem, code = result.mem, result.code
    else:        found = session.search(query, run_budget); mem, code = found or ([], [])
  finally: session.close(run_budget)
  mem, code = prune_hits(mem)[:5], prune_hits(code)[:5]      # pi index.ts:820-821, both modes
  both empty → None; else format_block(query, mem, code)
```

`run()` ports `runPipeline` (`pipeline.ts:161-392`, READ) with its arithmetic unchanged and its
race/abort plumbing replaced by child budgets (spec §7.1.1): each injected call receives a child
budget and must return within it (the transport and the HTTP client guarantee that); the runner
re-checks `remaining()` between stages.

1. **Plan** with `budget.child(min(PLANNER, max(0, TOTAL − SEARCH − SCORE)))`. A non-`ok` plan, or
   a raise (→ `transport`), → `fallback(reason)`.
2. **Dedupe queries**: flatten concepts' queries, trim, drop blanks and duplicates, seed the trimmed
   input so it is never searched. Empty → `fallback("invalid-shape")`.
3. **Search** sequentially: stop when `remaining() ≤ SCORE + 0.5`; share `min(SEARCH, max(0, remaining − SCORE))`;
   `None` → record, continue. Hits annotated with `kind`, `query`, `concept`.
4. **Pool**: `prune` per kind; concatenate memory then code; stable sort by `server_rank`; cap
   `POOL_MAX` 48. Empty → `fallback("no-candidates")`.
5. **Score** with `budget.child(SCORE)`: `score(query, pool, child)` returns one `float | None` per
   pool entry; any raise → all `None`. Scores join by hash.
6. **Merge**: `merge_select(pool, MERGE_SLOTS=5)`; split by kind. If the run budget expired →
   `budget-exhausted`, empty (pi `pipeline.ts:388-391`). Else `("pipeline", "ok")`.
7. **Fallback(reason)**: `left < 1.0` → empty with `reason`; else one search on the input query with
   share `min(SEARCH, max(0, left − SCORE))`; failure → `search-error`, empty; success → per-kind
   `prune` and `[:5]`, status `fallback`, the *original* `reason` (pi `:286`).

**Score failure does not fall back** (step 5). pi turns a Jev failure into null scores and merges by
server rank (`pipeline.ts:351-379`, READ); a fallback search would throw away up to six searches'
hits to run a seventh. The ruling's "planner or Jev fails → single search, as pi does" is read as
"as pi does"; O-6 asks the owner to confirm.

Fallback-reason vocabulary (pi's, carried): planner `no-model | timeout | transport | empty-text |
no-json-object | invalid-shape`; runner `ok | no-candidates | search-error | budget-exhausted`.
pi's `aborted` needs an external signal a hook does not have, so it is unreachable and not carried.
`search-error`, which pi re-throws for its `/rag status` diagnostics, is silent here like every
expected failure.

### 9.3 Planner (`query_planner.py`)

- **Prose.** `DELEGATOR_PERSONA` (pi `planner.ts:20-115`), `PLANNER_ADDENDUM` (`:118-129`),
  `PLANNER_USER_PREFIX` (`:131-149`) copied verbatim; `build_user_prompt(q) = PREFIX + q + "\n>>>"`
  with no trim or escape. System prompt = `DELEGATOR_PERSONA + "\n\n" + PLANNER_ADDENDUM`
  (`planner-call.ts:101`). The persona is compared with its source by PL2 (MEASURED this session:
  pi's constant, with its template-literal backtick escapes undone, equals
  `features/common/personas/delegator.md` from `# Delegator` to the end).
- **Parser.** `parse_plan(text)` ports `planner.ts:163-290`: brace-balanced spans with string-state
  tracking, tried last → first; the first span that parses and normalizes wins; limits
  `CONCEPT_NAME_MAX 120`, per-concept 1–4 queries, query 1–300 chars, 2–6 total, truncation not
  rejection (MG-2 amendment); reasons `empty-text`, `no-json-object`, `invalid-shape`.
- **Model.** `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`: blank → unset; no `/` → `no-model` (pi's
  first-slash rule, `planner-call.ts:94-96`); a leading `openrouter/` is removed; otherwise sent
  verbatim. Unset: `model_groups.resolve(level="medium", groups=model_groups.load_groups(<registry>))`
  with the resolver and registry located per §9.7, then `removeprefix("openrouter/")` — total and
  safe because `_emit_id` guarantees `^openrouter/<vendor>/<name>$` (`model_groups.py:25,311-317`,
  READ). Any resolver or registry failure → `no-model`.
- **Call.** No key → `no-model`, no request. `api_base` refused → `transport`, no request. Body
  `{"model", "messages":[system, user]}` with no sampling parameters (pi sets none; spec §2.5).
  `post_json` → `timeout` kind → `timeout`; `transport` kind, non-200 status, non-JSON body →
  `transport`. Text = `choices[0].message.content` if a string, else the joined `text` of parts
  whose `type == "text"` if a list, else `""`; then `parse_plan`.
- **Grounding (Q0).** OpenRouter's current API reference for `/api/v1/chat/completions` (request
  `model`, `messages`; response `choices[0].message.content`, string or parts) is fetched and cited
  in the research record before Q2a codes against it. UNVERIFIED until then.

### 9.4 Jev (`jev_scoring.py`)

Ports `jev-client.ts` (READ this session, `:40-529`):
- **Constants.** `BATCH_MAX 12`, `ATTEMPTS 3`, `ATTEMPT_SECONDS 15`, `STATE_CHAR_CAP 32000`,
  `EXCERPT_CHAR_CAP 500`, `MODEL "typesafe/jev-1.13"`, `DECISIONS_PATH "/api/alpha/decisions"`,
  `SCORE_QUESTION`, `SCORE_CRITERIA` (four strings). `ERROR_KINDS` (`misrouted-refusal`, `auth`,
  `billing`, `rate-limited`, `server`, `transport-timeout`, `malformed`, `missing-key`) and
  `RETRYABLE_KINDS` (`server`, `transport-timeout`, `malformed`, `rate-limited`).
- **Builder.** `build_score_question(c)`: `path = c.path if present else c.sourceFile if present
  else ""` (JS `??`), `kind` default `memory`, `excerpt = (snippet or "")[:500]` (code points);
  body `{"model", "state": query[:32000], "questions": {"c<i>": …}}` per batch of 12, `i` = pool position.
- **Classifier.** 400/401/402/429 → the four named kinds; any other non-200 (3xx included, since
  redirects are refused) → `server`; 200 → parse: invalid JSON or non-object → `malformed`; `error`
  present and `answers` absent → `server`; else answers per asked name through the tolerant parser
  (`type == "score"`, finite number clamped to [0, 3], else `None`). A transport failure or timeout
  from `post_json` → `transport-timeout`.
- **Attempts.** Per batch, up to 3 attempts, no sleep, retry only on a retryable kind. Each attempt
  gets `score_budget.child(ATTEMPT_SECONDS)`; `remaining() ≤ 0` skips the batch with `None`s and no
  request. Batches run sequentially (pi does the same, `jev-client.ts:445-478`).
- **Not ported:** `usage` sums and `Retry-After` clamping (recorded, never used in v1; C10), the
  warm-up call (needs a session lifecycle a one-shot hook lacks, spec §7.1.6), the endpoint/model/
  timeout env vars (§1.3), the second pool cap (C22).
- **Grounding (Q0).** The decisions endpoint and wire shape are pi's measured contract (spec §3,
  `score-fixtures.ts` honesty note: shape measured, numbers stipulated). Q0 records a pointer to the
  current OpenRouter doc for `/api/alpha/decisions` if one exists; otherwise the grade stays
  "measured by pi, not re-measured".

### 9.5 HTTP hygiene (`openrouter_client.py`)

- **Opener, one per call.** `urllib.request.build_opener(ProxyHandler({}), NoRedirect(),
  DeadlineHTTPSHandler(context=ssl.create_default_context(), watchdog=w), DeadlineHTTPHandler(watchdog=w))`.
  `ProxyHandler({})` honours no proxy variable and no system proxy. `NoRedirect` subclasses
  `HTTPRedirectHandler` and returns `None` from `redirect_request`, so a 3xx surfaces as an
  `HTTPError` and no second request is made, so the `Authorization` header is never forwarded. The
  HTTP handler exists only for the loopback test base (§9.6); production URLs are the constant
  `https://openrouter.ai`.
- **Deadline.** `post_json(url, body, key, budget)`: `remaining() ≤ 0` → `timeout` without
  connecting. Otherwise `opener.open(req, timeout=remaining())` bounds connect and each socket read,
  and a watchdog bounds the whole exchange: a `threading.Timer(remaining())` armed before `open`;
  the handlers' connection subclass hands its socket to the watchdog right after `connect()`; when
  the timer fires it calls `socket.socket.shutdown(raw_socket, SHUT_RDWR)` (the base-class method, so
  an in-flight TLS read sees EOF rather than a torn `SSLObject`), and a socket attached after the
  fire is shut down on attach. The exchange then fails inside the stage share and is reported as
  `timeout`. In `finally` the timer is cancelled and joined, so no thread outlives the call (O4,
  W10, B14). The only unbounded step is DNS resolution (`getaddrinfo` cannot be interrupted), left to
  the OS resolver timeout and the host timeout (R-i).
- **Reading.** Status, lower-cased headers and at most 1 MiB of body, read in chunks; more → `transport`.
  A non-2xx `HTTPError` is returned as a `Reply` (its body read under the same cap) so the Jev
  classifier sees the status; any other exception → `transport`, or `timeout` if the watchdog fired
  or a `TimeoutError`/`socket.timeout` was raised.
- **Key.** `api_key(env)`: `env.get("OPENROUTER_API_KEY", "").strip() or None`; no file is read.
  The key goes only into the `Authorization` header. No exception message, `Reply` field or log line
  carries it (O9); expected failures log nothing anyway (§1.3).
- **Headers.** `Authorization: Bearer <key>`, `Content-Type: application/json` (the pair
  `jev-client.ts:356-360` sends). Body `json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()`.

### 9.6 Test seam: the loopback-only base URL

Unit tests pass the fake's base URL as a parameter. Subprocess tests (H12) need a process-boundary
seam: `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE`. `api_base(env)` accepts it only when it
parses as scheme `http`, hostname exactly `127.0.0.1`, an explicit port, no userinfo, and an empty
path; anything else returns `None` and the run makes no OpenRouter request at all (never a silent
switch back to production; O8). The variable is named in ADR-0032 and in the test support module,
not in SKILL.md. Residual risk: a user who sets it points their real key at a loopback port (R-j).

### 9.7 Reaching the model resolver (owner decision point)

**Options weighed under derive-or-delete:**

| Option | Twin created | Comparator needed | Verdict |
|---|---|---|---|
| A. Vendored copy of `model_groups.py` beside the hook | A 360-line hand-kept copy in `ai-raccoon-memory/scripts/` | A new byte-equality check (the existing `vendored_copies_report` is specific to `badger_store.py`, READ `engine/badger_store.py:322-343`) | Rejected: a second copy of the resolver in the catalog plus a new check to keep it honest |
| B. Read `.ai-badger/model-groups.json` and take `groups.medium[0].id` | The resolver's rule (index 0, `ID_RE`, emit-time re-check) written a second time | None exists; `model_groups.py`'s docstring says it "duplicates the rules nowhere" | Rejected: re-implements the resolver the ruling says to use |
| **C. Load the one `model_groups.py` by path, pass it the project's registry** | None in the catalog | None | **Chosen** |

**Mechanics of C.**
- *Resolver code*, located relative to the running hook file, never the prompt's cwd: first
  `Path(__file__).parent / "model_groups.py"` (the Hermes destinations, where the adjuster copies it
  through a `("task", "model_groups.py")` `SHARED_SKILL_MODULES` row generated from the one catalog
  file), else `Path(__file__).parents[1].parent / "task" / "scripts" / "model_groups.py"` (the Claude
  scaffold `.ai-badger/skills/task/scripts/`, and the catalog tree itself). Loaded once per process
  under `ai_badger_memory_context__model_groups`. Both copies are written by existing generators
  from `features/common/skills/task/scripts/model_groups.py`; neither is hand-maintained.
- *Registry data*: `<nearest .ai-badger>/model-groups.json`, the `.ai-badger` directory the project-id
  walk stops at (via `badger_store._nearest_project_id_file(cwd).parent`, so the walk keeps one owner;
  one `protected-access` suppression with that reason). The scaffolder delivers this file on every
  run (`model_registry.deliver`, READ). `load_groups(path)` validates it before `resolve` reads it.
- *Why the Hermes copy is not loaded from the project*: `model_groups.py` is code. Claude hooks
  already run project-scaffolded code by design, but Hermes today executes only plugin-dir code;
  loading the resolver from `<project>/.ai-badger/skills/task/` would let any opened repo run code in
  the Hermes gateway. W10 pins that every loaded module's `__file__` is under the plugin dir.
- *Consequences*: a Claude project that declines `task` has no resolver → `no-model` → single-search
  fallback, unless the override is set (SKILL.md says so). The registry is project data: a repo can
  choose which `openrouter/` model the planner calls on the user's key (R-g).

### 9.8 Packages Q0–Q3

#### Q0: ADR-0032, pipeline goldens, docs grounding (no `features/` edit)

- **Q0.1 ADR first.** `docs/adr/0032-query-pipeline-over-openrouter-in-the-memory-context-hook.md`
  (Nygard) + README row. Context: pi's pipeline measured better retrieval than one search (cite pi's
  research); one-shot hook constraints. Decision: port pi's pipeline; planner and Jev over direct
  OpenRouter HTTP; one proxy session for all searches; child budgets; watchdog; single-search
  fallback; Jev failure merges by server rank (O-6); resolver route C (§9.7); loopback-only test base.
  Consequences: positive (better recall, pi parity); negative (10–20 s typical, 90 s cap per gated
  prompt; prompt and up to 48 × 500-char excerpts sent to OpenRouter whenever the key is exported
  (O-7); per-prompt OpenRouter cost; a watchdog thread per HTTP call; DNS unbounded; project-chosen
  planner model); neutral (six Hermes rows; four more mirrored files). Alternatives: spawn pi as
  planner (ruled out); parallel searches (one child; pi is sequential); no Jev (loses the merge
  signal); per-socket timeouts without a watchdog (a drip defeats them); threads per stage (leak
  risk in Hermes); resolver options A/B (§9.7).
- **Q0.2 Goldens.** `tests/fixtures/memory_context/gen_pipeline_goldens.ts` imports pi's
  `planner.ts`, `jev-client.ts`, `merge.ts`, `pipeline.ts` and `tests/query-pipeline/fixtures/score-fixtures.ts`
  at `ee5f1c6e…` and writes `pipeline_goldens.json` (`pi_commit`, `generator`, `bun` version):
  planner prose, `build_user_prompt` outputs, `parsePlan` outputs over the PL3 corpus, the
  `PlannerFallbackReason` list; Jev constants and prose, request bodies captured through an injected
  `fetchFn` for the J2 candidate sets, kinds and retryable lists; `mergeSelect` over the MG1 cases;
  `runPipeline` scenario outcomes (R3) with injected `plan`/`search`/`score`; and
  `score_fixtures.json` (every export of `score-fixtures.ts`, JSON-serialized by bun). Inputs live
  in the committed `pipeline_golden_inputs.json`; inputs may be transcribed from pi's test files,
  outputs must come from running pi.
- **Q0.3 Grounding.** Fetch and cite, in the research record: OpenRouter chat-completions request
  and response shape; any OpenRouter doc for `/api/alpha/decisions`; Claude Code's hook `timeout`
  field (unit, default, whether 100 is accepted). Grade each.
- **Acceptance:** ADR merged-ready; `pipeline_goldens.json` regenerates byte-identically on a second
  bun run; every golden input has an output; grounding recorded with grades.
- **Gate:** `bun tests/fixtures/memory_context/gen_pipeline_goldens.ts | diff - tests/fixtures/memory_context/pipeline_goldens.json`
  (by hand; CI does not run bun); `$PY gates/docs_guard.py`.
- **Files:** `docs/adr/0032-….md` (new), `docs/adr/README.md`, `tests/fixtures/memory_context/{gen_pipeline_goldens.ts,pipeline_golden_inputs.json,pipeline_goldens.json,score_fixtures.json}` (new),
  the research record.

#### Q1: `openrouter_client.py` + fake OpenRouter + network guard

- Red first: O-rows against a stub `post_json` that returns `Reply(200, {}, b"{}")`; O4 written first
  against a version without the watchdog and watched to exceed its bound.
- Implement §9.5 and `api_base` (§9.6). Add the fake server, the capture server and the network
  guard to the support modules; extend the env scrub (§6).
- Closing step (a new file under the skill's `scripts/`).
- **Acceptance:** O1–O9 and G4 green, each mutation seen red; S1 green over the new module; pylint
  clean; pre-push green.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_openrouter.py tests/test_memory_context_transport.py::test_S1`;
  pylint on `openrouter_client.py`; the closing-step checks.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py` (new),
  `tests/test_memory_context_openrouter.py` (new), `tests/memory_context_openrouter.py` (new),
  `tests/memory_context_support.py`, generated outputs.

#### Q2a: `query_planner.py` (∥ Q2b, Q2c)

- Stubs; PL1–PL7 red on assertions; implement §9.3.
- **Acceptance:** PL1–PL7 green, mutations seen red; the planner makes 0 requests without a key or
  with a refused base; pylint clean.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_planner.py`; pylint on `query_planner.py`.
  Closing step by the integrating session at merge.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/query_planner.py` (new),
  `tests/test_memory_context_planner.py` (new).

#### Q2b: `jev_scoring.py` (∥ Q2a, Q2c)

- Stubs; J1–J9 red on assertions; implement §9.4.
- **Acceptance:** J1–J9 green, mutations seen red; `score` never raises; pylint clean.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_jev.py`; pylint on `jev_scoring.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/jev_scoring.py` (new),
  `tests/test_memory_context_jev.py` (new).

#### Q2c: `query_pipeline.py` (∥ Q1, Q2a, Q2b)

- Stubs; MG1, MG2, R1–R8 red on assertions; implement merge and `run` (§9.2).
- **Acceptance:** all ten rows green, mutations seen red; `run` never raises; pylint clean.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_pipeline.py`; pylint on `query_pipeline.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/query_pipeline.py` (new),
  `tests/test_memory_context_pipeline.py` (new).

#### Q3: wiring into `build()`

- **Q3.1** Confirm Q0.3's Claude `timeout` finding; if 100 is not accepted, stop and return to the
  owner with the largest accepted value and a budget that fits under it.
- **Q3.2** Red first: B9–B14 against the P2 `build()`. Then add the sibling loads, resolver/registry
  location (§9.7), `ENV_NAMES`, the constants (§1.2), the pipeline branch (§9.2).
- **Q3.3** Closing step (after Q2a/b/c merged, once).
- **Acceptance:** B9–B14 green, mutations seen red; every P2 row still green (single-search mode is
  rev 2 unchanged: B11); S1 green over all six modules; pre-push green.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_pipeline_wiring.py tests/test_memory_context_transport.py tests/test_memory_context_core.py tests/test_memory_context_openrouter.py tests/test_memory_context_planner.py tests/test_memory_context_jev.py tests/test_memory_context_pipeline.py tests/test_sync_plugin_skills.py`;
  pylint on `memory_context.py`; the closing-step checks.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/memory_context.py`,
  `tests/test_memory_context_pipeline_wiring.py` (new), generated outputs.

---

## 10. Risks and owner questions

| # | Risk / question | Recommendation |
|---|---|---|
| O-1 | Kill scope (pid vs process group) | **RESOLVED.** The orchestrator verified `BackendLauncher.cs:234-240` and accepts kill-pid-only after a graceful stdin close (T18, T19). |
| O-2 | Sanitise `path` and non-numeric `rank` (divergence from pi) | **Owner:** accept the divergence; file a pi issue so parity returns when pi adopts it. |
| O-3 | POSIX-only transport (pipes are not selectable on Windows) | **Owner:** accept; silent on Windows; documented. |
| O-4 | Copilot branch B | Owner checkpoint before P4 commits the exemption. |
| O-5 | Hermes gateway exposure and event-loop blocking (security SHOULD-4), now up to 90 s per turn with the pipeline | P3b.0 finds the platform kwarg and any Hermes hook timeout; default CLI-only if a kwarg exists; demo records blocking; ADRs record the answer or the gap. |
| O-6 (new) | The ruling says "planner **or Jev** fails → single search, as pi does"; pi's source falls back only on planner failure and turns Jev failure into null scores merged by server rank (`pipeline.ts:351-379`, READ) | **Owner:** follow pi's source (R7, B12). The alternative costs a seventh search and discards the planned hits. |
| O-7 (new) | Default-on whenever `OPENROUTER_API_KEY` is exported: every gated prompt, and up to 48 memory/code excerpts, go to OpenRouter (planner vendor and Jev). A user who exports the key for other tools opts in silently | **Owner:** keep the ruling (pi parity) and state it in SKILL.md, the changelog and ADR-0032; or require `AI_BADGER_MEMORY_CONTEXT_PIPELINE=1`. Recommendation: keep, documented. |
| R-a | ~10–20 s per gated prompt with the pipeline, ~1.5 s without | Accepted by owner; both measured in the demo; two switches documented. |
| R-b | With no serve running, the first search pays serve start-up; the 15 s search share now likely covers it (INFERRED) | Demo measures it. |
| R-c | The proxy's own behaviour on SIGKILL mid-acquire | INFERRED harmless; demo checks the serve still listens. |
| R-d | `pre_llm_call` frequency contradicted in-repo | Memo correct under both; demo records the truth. |
| R-e | Goldens drift when pi changes | `pi_commit` recorded in both golden files; regeneration is manual; the rows pin the committed truth. |
| R-f | Validator ignores `matcher` | Documented limit of the check. |
| R-g (new) | The planner model comes from project data (`.ai-badger/model-groups.json`); a repo can pick an expensive `openrouter/` model billed to the user's key | Bounded by `ID_RE`, one call per prompt, 15 s share; the override pins it; ADR-0032 names it. |
| R-h (new) | Claude hook `timeout` 100 exceeds every precedent (all 10) | Q0.3/Q3.1 ground it in current docs before shipping. |
| R-i (new) | DNS resolution is not interruptible; a stalled resolver can exceed a stage share | OS resolver timeout; host timeout as backstop on Claude; Hermes has none (O-5). |
| R-j (new) | The test base URL, if set by a user, sends their real key to a local listener | Loopback-only, exact-port parse, not documented in SKILL.md, named "TEST" (O8). |
| R-k (new) | Any `delegator.md` edit reddens PL2 until `DELEGATOR_PERSONA` is updated, and pi's constant drifts until pi refreshes | Intended: the persona is one text with one source; PL2 is the comparator. |

## 11. Review disposition

Rev 2's three plan reviews stay folded as recorded; rev 3 adds the pipeline rows.

| Finding | Disposition | Reason / where |
|---|---|---|
| SEC MUST-1 token to unproven listener (F70) | **Folded (resolved by ruling)** | Proxy transport performs the ADR-0106 proof; hook never holds the token. |
| SEC MUST-2 urllib redirects forward the token | **Moot for ai-raccoon; applied to OpenRouter** | `NoRedirect` + O2 (§9.5). |
| SEC MUST-3 Hermes trust header covers the user message | **Folded** | Closing line after the block, P3b.0, W2. |
| SEC SHOULD-1 path not `one_line`d | **Folded** | §1.5 divergence, C19, O-2, pi issue. |
| SEC SHOULD-2 all Unicode line breaks | **Folded** | C18. |
| SEC SHOULD-3 deadline leaves a phase open; thread leak | **Folded (re-derived)** | Selector deadline for the proxy (T13, T14, T17, H8, W9); watchdog joined per HTTP call (O4, W10, B14). |
| SEC SHOULD-4 Hermes gateway exposure / blocking | **Folded** | O-5, P3b.0, W7, demo. |
| SEC SHOULD-5 Hermes F2 vacuous; `on_session_start` does not exist | **Folded** | §1.7; memo cleared in `on_session_start_drift_notice`; M4. |
| SEC SHOULD-6 token in exception text | **Moot for the token; applied to the OpenRouter key** | O9, J9, H12. |
| SEC N1 validator vs generators; matcher | **Folded** | V4; R-f. |
| SEC N2 port parsing | **Moot** | Port variable deleted. |
| SEC N3 kill-switch literal | **Folded** | §1.3 (both switches). |
| SEC N4 prompt persistence | **Folded** | ADR-0031; ADR-0032 adds OpenRouter egress (O-7). |
| SEC N5 BrokenPipe exit 120 | **Folded** | H10. |
| SEC N6 token location | **Moot** | Token not read. |
| SEC N7 projectId / exported env | **Folded** | §1.3; B4. |
| QA M1 header drip | **Folded (re-derived)** | Proxy drip T13; HTTP header/body drip O4. |
| QA M2 port ruling untested; live-serve guard aimed wrong | **Moot + folded** | G1, I12; network guard G4. |
| QA M3 I1 fails on correct code | **Folded** | §1.6(3); I8. |
| QA M4 `sys.modules` cache defeats I6, W8 order | **Folded** | Reset fixture covers pipeline keys; I11, W10 assert `__file__`. |
| QA M5 golden is code; parity inputs missing | **Folded** | Bun goldens for the block (P2.3) and the pipeline (Q0.2). |
| QA S1 V15 mutation not real | **Folded** | V14. |
| QA S2 `no_proxy` | **Folded for OpenRouter** | O1 with `no_proxy` unset so the mutation can go red. |
| QA S3 env scrub | **Folded** | Scrub list derives from `ENV_NAMES`; G2. |
| QA S4 raise-patch cannot see a caught spawn | **Folded (re-derived)** | Spawn log (T2, I12); S1. |
| QA S5 hook process exit | **Folded** | H8. |
| QA S6 positive direction | **Folded** | T1. |
| QA S7 spike control and payload | **Folded** | P0.2, I7. |
| QA S8 count connects not time | **Folded** | Rows count fake invocations and HTTP requests; timing only as bounds. |
| QA S9 guarded fallback masks rewrite | **Folded** | I6. |
| QA S10 token leaks via session HOME | **Moot (analogue folded)** | Temp HOME; O9 ignores key files. |
| QA S11 dead port proves no routing | **Folded** | H3. |
| QA N1–N8 | **Folded / noted** | As rev 2 (§1.7, I8(c), V1, S1, C23, W2a, reset fixture, B1). |
| FEAS M1–M4, S1–S8, N1–N6 | **Folded** | As rev 2 (P1.4, closing step, §1.5, §1.7, `badger_lib` map, decline check, selector transport, P4.3/P4.7, `--no-install`, recounts, memo note, `badger_store` reuse). |
| Rev 1 F1 / R2 / Q1 / C7 | **Superseded** | Owner transport ruling. |

## 12. Simpler shape?

Asked before calling the design finished:

- **One pipeline file instead of four.** Saves three Hermes rows, three twin rows and three mirror
  files. Costs the parallel lanes (Q2a ∥ Q2b ∥ Q2c) the owner expects and puts HTTP, prose constants
  and pure merge logic in one ~850-line file. Kept at four; a reviewer who prefers one file loses
  nothing but parallelism, since the contracts are the same.
- **No watchdog thread.** Per-socket timeouts alone are simpler, but a dripping server defeats them
  (O4's mutation), and the ruling requires a stalled response to stay inside its share. Kept.
- **Jev failure → single search** (the ruling's literal words) would be one line simpler in the
  runner but discards planned hits; pi's behaviour kept pending O-6.
- **Missing key → rev-2 single-search mode directly** would skip the runner, but the runner's
  fallback *is* that search with pi's reason; one path instead of two. Kept.
- **Cut from the pi port:** progress UI, scheduler, abort signals, `aborted`, env clamps, warm-up,
  usage sums, Retry-After clamp, the second prune and the second pool cap, the pi-registry rows.
- **Cut earlier and still cut:** direct HTTP to ai-raccoon, the port variable, the sitecustomize
  routing shim (the new sitecustomize is a network *guard*, not a route), expanded mode.

The five non-negotiables, again:
1. One spawn per run: `ai-raccoon`, `argv == [exe]`, no shell, never pi, never the token; every
   planned search on that one session.
2. One run budget with a child per stage; kill and reap on deadline or error; fallback or nothing;
   exit 0.
3. OpenRouter: key from env only, never logged; no proxy, no redirect, verified TLS; a watchdog keeps
   every call inside its share.
4. No test reaches the real executable or the network: temp PATH + temp HOME + G1 + G4.
5. Every package ends green on pre-push: VERSION in P1, closing step after every `features/` package.
