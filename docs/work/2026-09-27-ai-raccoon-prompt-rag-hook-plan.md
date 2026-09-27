# Implementation plan: aib-ai-raccoon-prompt-rag-hook (rev 4, final)

Rev 4 replaces rev 3 (commit `9dea8180`) in full and is the last plan before implementation. It
applies the P0 Copilot verdict (branch A), folds the round-2 reviews (security 3 MUST, feasibility
1 MUST, QA 5 MUST, and every SHOULD and NOTE not rejected in §11), cuts the design to three modules
and one ADR, and carries the owner rulings on rev 3 unchanged (§13). §0 lists every change.

Worktree `.ai-badger/worktrees/aib-ai-raccoon-prompt-rag-hook`, branch
`task/aib-ai-raccoon-prompt-rag-hook` (head `0a31b32e`, main `4abf5ade`), `VERSION` 0.177.3. pi
source commit for every golden: `ee5f1c6e689b988a8924781b3acb5961ce40c326` (security review
MEASURED `git log ee5f1c6e..HEAD -- extensions/query-pipeline extensions/mem-based-rag` empty at pi
HEAD `161673c0`). Paths are repo-relative unless absolute. Grades: READ (source opened and
re-checked), MEASURED (command run), INFERRED, UNVERIFIED.

All gate commands run from the task worktree root with the main checkout's interpreter:

```
PY=/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3
```

**The five things an implementer must not get wrong** (repeated in §12):
1. The hook spawns exactly one process per run: the `ai-raccoon` executable, `argv == [exe]`, no
   shell, never pi. It never reads or sends the ai-raccoon token. Every planned query's search goes
   over that one session.
2. One wall-clock `Budget` bounds the whole run; every stage draws a child of it. The pipeline
   (90 s) runs only when `OPENROUTER_API_KEY` is set and the pipeline switch is not `"0"`; every
   other run is single-search under 5 s. At the deadline or on any error the child is killed and
   reaped, the run takes pi's fallback or injects nothing, and the hook exits 0.
3. OpenRouter calls: key from the environment only, never logged; one opener with no proxy, no
   redirect and default-context TLS; the stage deadline covers DNS, connect (every address tried)
   and the TLS handshake, and a watchdog covers every byte after, so a call never outlives its share.
4. No test reaches the real `ai-raccoon`, the real network or a real key. The guards record every
   refusal and an autouse teardown fails the test on any record, so production code that catches
   the refusal cannot hide it. Every blocking fake ends by a 20 s ceiling, so a mutant that drops a
   deadline goes red instead of hanging the suite.
5. Lanes commit in their own worktrees and hand back; they never push. Only the integrating
   session merges, runs the closing step (sync, index, self-scaffold) and pushes, because
   `.ai-badger/manifest.json` stores one hash for the whole `ai-raccoon-memory` skill folder and two
   lanes' closing steps always collide on it.

---

## 0. Changes versus rev 3

| Rev 3 | Rev 4 | Source |
|---|---|---|
| P0 spike package, branches A/B, O-4 open | **P0 done, verdict A** (research record addendum, MEASURED 3/3 flat, 0/3 envelope). P0 package, branch B and O-4 removed. Copilot gets a full arm | Binding 1 |
| Entry prints the Claude envelope only | The entry picks the output shape from the payload: Claude (`hook_event_name == "UserPromptSubmit"`) → `hookSpecificOutput` envelope; anything else (Copilot: `{sessionId, timestamp, cwd, prompt}`) → flat `{"additionalContext": …}`. Session id from `session_id` or `sessionId` | Binding 1 |
| Payload fixture committed in P4 | `tests/fixtures/memory_context/copilot_user_prompt_payload.json` lands in P3a (H2 uses it) | Binding 1 |
| Envelope defect of existing Copilot arms: branch-B issue | Out of scope: issue #530 | Binding 1 |
| Six new modules, two ADRs | **Three modules** (`memory_context.py`, `openrouter_client.py`, `query_pipeline.py`) plus the thin entry `memory_context_hook.py`; **one ADR** (0031) with two numbered decisions | Binding 3; feasibility F4, F10 |
| Q2a ∥ Q2b ∥ Q2c lanes | One Q2 lane (`query_pipeline.py`); Q1 ∥ Q2 | Binding 3 |
| Closing step inside each package; "pushed per package" | Lanes commit only; the integrating session merges, runs the closing step once per merge wave and pushes | Binding 3; feasibility F2 |
| `pipeline = switch != "0" and siblings loaded`; missing key → runner `no-model` inside the 90 s budget | `pipeline = switch != "0" and api_key(env) is not None and siblings loaded`; missing key → single-search, 5 s budget, no runner | Binding 2; security MUST-2 |
| Watchdog attached "right after `connect()`"; DNS unbounded (R-i) | Own `connect()`: resolve under the deadline (IP literal inline; host name on one named resolver thread, at most one per host), connect each address with a timeout recomputed from `remaining()`, `settimeout(remaining())` before the TLS wrap (the whole handshake is one deadline), watchdog holds a `dup()` of the connected socket so it survives `wrap_socket`'s detach | Binding 2; security MUST-1; QA F5 |
| Hermes: CLI-only "if a kwarg exists" | Fail closed: `build()` runs only when `platform == "cli"` (the positive signal; P3b.0 confirms the value in Hermes source). Absent, unknown or gateway platform → inert | Binding 2; security MUST-3 |
| `parse_plan` unbounded | Text over `PLAN_TEXT_MAX` 64 KiB → `no-json-object`; `raw_decode` at the span start; `RecursionError` skips the span | Binding 2; security SHOULD-1 |
| Copilot `timeoutSec` 100 "manifest only" | P1 edits `features/copilot/adjustments/adjust_hooks.py:148` to `h.get("timeout", 10)`; row A1 proves it | Binding 2; feasibility F1 |
| Resolver: sibling, else `parents[1].parent/task/scripts` | Layout-exact: skill layout (`…/ai-raccoon-memory/scripts/`) → only `parents[2]/task/scripts/model_groups.py`; any other layout → only the flat sibling. And only when `<nearest .ai-badger>/skills/task/` exists, on both agents | Binding 2; security SHOULD-2; feasibility F5, F8 |
| O-2: path through `one_line`, non-numeric rank → `?`, promise "byte-identical for every hit without such characters" | `sanitize_field` replaces only the O-2 set in path and rank; string ranks render raw; JS whitespace class implemented exactly; promise scoped in §1.5 | Binding 2; security SHOULD-3 |
| Guards raise an ordinary exception | Guards append to a per-test refusal list, raise a `BaseException` subclass; autouse teardown asserts the list empty; companion rows prove the teardown | Binding 2; QA F1 |
| O2 redirect row: 307 only | Parametrized 301/302/303/307/308 (302 is the case the default handler follows) | QA F2 |
| No test ceiling | Every blocking fake ends by 20 s; row bounds ≤ 3 s | QA F3 |
| `threading.active_count()` assertions | Named threads `ai-badger-openrouter-watchdog` and `ai-badger-openrouter-dns`; assert none alive; proxy rows assert reaped pids | QA F4 |
| Plain-HTTP drip rows only | O4b: TLS body drip with a throwaway certificate, plus a handshake drip | QA F5; security MUST-1 |
| `ENV_NAMES` added in Q3 | Defined in P2 with all six names | Feasibility F6 |
| Hand-listed Hermes rows | `memory_context.SIBLINGS` + `RESOLVER` constants read by the loader and by the extended derive test | Feasibility F3 |
| Q3.1 stop condition on Claude `timeout` | Resolved: Claude docs READ by feasibility (default 600, lowered to 30 on `UserPromptSubmit`, no stated maximum); R-h closed | Feasibility F7 |
| Test base URL accepted with any key (R-j) | Accepted only with a key starting `sk-test-` | Security NOTE-4 |
| QA seven cuts | O5, C11, T6, T11, I12, W5 cut; R4 merged into PL7 | QA Proportion |
| 157 rows | 159 rows (§6 totals) | §6 |

---

## 1. Design summary

**What ships.** On every user prompt that passes a port of pi's `shouldEnrich` (without the
`/skill:` rules), the hook spawns the `ai-raccoon` proxy and performs the MCP handshake over
newline-delimited JSON-RPC on its stdin/stdout. When `OPENROUTER_API_KEY` is set and
`AI_BADGER_MEMORY_CONTEXT_PIPELINE` is not `"0"`, it asks an OpenRouter model for 2–6 retrieval
queries, runs one `memory_search` per deduplicated query over that one session, scores the pooled
hits with Jev, and keeps the best five by pi's document-aware merge. Otherwise, or when the planner
fails, it runs one search on the gated prompt. If hits survive pruning, a "Memory context" block
equal to pi's default-mode `toMemoryContext` output (parity scoped in §1.5) is injected as
additional context. The block format is identical in both modes. The hook runs on Claude Code,
Copilot CLI and Hermes (CLI sessions only). It never runs on pi.

**Why the proxy (owner ruling, binding).** The proxy performs ai-raccoon's per-request ECDSA
identity proof before any token-bearing request (ai-raccoon ADR-0106, finding F70; invariant "to any
listener that has not proven identity: zero secret bytes"). Stdlib Python has no ECDSA
verification, and the "use platform security APIs" invariant forbids hand-rolling it. Through the
proxy the hook never touches the token. The owner accepts the spawn cost (~0.17 s) and that the
proxy may start a serve when none is running.

**Why OpenRouter over HTTP (owner ruling, binding).** Planner and Jev are direct `urllib` POSTs to
OpenRouter; no pi, no second process. §9 is the pipeline design.

**Placement.** `features/common/skills/ai-raccoon-memory/scripts/`. The skill is `scope: default`,
already owns the other ai-raccoon hooks and carries a vendored `badger_store.py` (READ). Declining
the skill through `config.exclude` removes the Claude and Copilot wiring through the existing
`declined_skill` path in `skills/welcome-ai-badger/scripts/hook_wiring.py`; Hermes gets an explicit
decline check (§1.3).

**Files: three modules and one entry.**

| File (new) | Contents |
|---|---|
| `memory_context.py` | *Pure:* `CONTROL_WORDS`, `NOISE_WORDS` (35), `unique_long_words`, `should_enrich(prompt, min_chars=20, min_words=6) -> Decision`, `JS_SPACE`, `js_trim`, `FIELD_BREAKS` (the O-2 set), `sanitize_field`, `one_line`, `js_number`, `prune_hits`, `format_block(query, mem, code)`. *Budget:* `Budget` (§1.2). *Transport:* `find_executable(env, home)`, `RaccoonSession` (§1.1). *Orchestration:* `ENV_NAMES`, `SIBLINGS = ("openrouter_client.py", "query_pipeline.py")`, `RESOLVER = "model_groups.py"`, the by-path sibling loader, the resolver locator (§9.7), `build(prompt, cwd, session_id, *, env=None, home=None, budget=None, limits=None) -> str \| None` (§9.2). |
| `openrouter_client.py` | The one network surface: `Reply`, `api_key(env)`, `api_base(env, key)`, `post_json(url, body, key, budget) -> Reply`, the opener, the deadline connection classes, the resolver thread and the watchdog (§9.5). The only module that imports `urllib`, `http.client`, `ssl`, `socket` or `threading`. |
| `query_pipeline.py` | Planner (`DELEGATOR_PERSONA`, `PLANNER_ADDENDUM`, `PLANNER_USER_PREFIX`, `build_user_prompt`, `parse_plan`, `plan`), Jev (constants, `build_score_question`, `classify`, `score`), `dedupe_queries`, `server_rank`, `doc_key`, `merge_select`, the reason vocabularies, the stage limits and `run` (§9.2–9.4). No imports of the other two modules; every effect (`post`, `search`, `score`, `prune`, budget, clock) is a parameter. |
| `memory_context_hook.py` (entry) | Claude and Copilot entry. stdin JSON → `build()` → exactly one output line in the shape the payload calls for (§1.4) or nothing. Loads `memory_context.py` by path under a distinctive `sys.modules` key (pattern `context_enrichment_hook.py:41-68`). `guarded_main()` always exits 0 and routes only unexpected exceptions to `record_hook_failure` (pattern `context_enrichment_hook.py:169-199`), log path resolved at call time; the final write is wrapped so a closed stdout also exits 0. |

The entry stays a separate ~60-line file: hook entries in this repo are `*_hook.py`, and the
process concerns (stdin parsing, output shape, closed stdout, `hook-errors.log`) do not belong in the
module Hermes imports in-process. Hermes gets no entry: `ai_badger_hooks.pre_llm_inject_context`
loads `memory_context.py` through the existing `_load_sibling_module` and calls `build()`.

The pure-core boundary is held by review and by the pure functions taking no env, home or session
argument. `query_pipeline.py` is testable alone because it receives every effect as a parameter;
only `memory_context.build()` wires real effects.

### 1.1 Transport: `RaccoonSession` over the proxy

Mirrors pi's `RaccoonClient` (`/Users/arasz/RiderProjects/pi-badger-integration/extensions/mem-based-rag/index.ts:270-430`, READ),
reduced to one synchronous client per hook run.

- **Resolve.** `find_executable(env, home)`: `shutil.which("ai-raccoon", path=env["PATH"])`, else
  `Path(home)/".dotnet"/"tools"/"ai-raccoon"` if it is a file with `os.access(X_OK)`, else `None`
  (silent, nothing spawned). `env` and `home` are read at call time; the result is made absolute.
  PATH-first is the owner's ruling (pi resolves only `~/.dotnet/tools`, `index.ts:130`).
- **Spawn.** `subprocess.Popen([exe], stdin=PIPE, stdout=PIPE, stderr=DEVNULL, shell=False, close_fds=True)`.
  No arguments (the bare binary is the proxy transport, never `--transport stdio`). No
  `start_new_session`. Environment and cwd inherited.
- **Handshake.** Line 1: `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ai-badger-memory-context","version":"1"}}}`.
  Wait for the `id:1` reply. Line 2: `{"jsonrpc":"2.0","method":"notifications/initialized"}`.
- **Search.** `session.search(query, budget)` writes
  `{"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"memory_search","arguments":{"projectId","sessionId","query","limit":5,"scope":"project"}}}`
  with `N` from 2, and returns `SearchResult(mem, code)` or `None`. `scope:"project"` is mandatory
  (the owner measured that omitting it leaks shared-tier hits; deliberate difference from pi). No
  `kind` argument. `limit: 5` equals pi's pipeline `searchLimit`.
- **Framing (pi `onData` parity, `index.ts:326-355`).** Split stdout on `\n`, trim, skip blank and
  non-JSON lines and replies whose `id` is not the awaited one. `error` → `None`; `result.isError` →
  `None`; else the first `content[]` part with `type:"text"`, parsed as JSON, `results` (memory) and
  `code` lists (missing → empty; non-JSON text → `None`). A stdout buffer over 1 MiB without a
  newline, or 4 MiB in total, → `None`.
- **Session state across searches.** A search whose request line was fully written and whose reply
  did not arrive in its budget returns `None` and leaves the session usable; its late reply is skipped
  by id (pi continues on the same child, `pipeline.ts:320-338`). A partial write, an oversize line,
  EOF on stdout or a dead child *poisons* the session: every later `search` returns `None` at once
  without writing (T24, T25). All writes go through one method, `_write`, so T25 can spy on it.
- **Deadline.** Single-threaded I/O with `selectors` over the child's stdin and stdout, both
  non-blocking; every wait is `select(timeout=budget.remaining())`. No thread is created. Pipes are
  not selectable on Windows, so on `sys.platform == "win32"` the transport returns `None` without
  spawning (O-3).
- **Close (always, in `finally`).** Close the child's stdin first so the proxy's dispose path runs
  (ADR-0106 D13). Wait up to `min(GRACE_SECONDS=0.5, budget.remaining())`. If still alive, `SIGKILL`
  the child pid, then `wait(timeout=1)` to reap. Close stdout.
- **Kill scope: the pid, never the group (O-1).** `BackendLauncher.Start` uses `ProcessStartInfo`
  with `UseShellExecute=false` and no new session (`/Users/arasz/RiderProjects/ai-raccoon/src/AiRaccoon/Hosting/Proxy/BackendLauncher.cs:234-240`, READ),
  so a serve the proxy starts shares its process group and its lifetime belongs to `IdleWatchdog`. A
  group kill would kill that serve and the hook's own group. Every `Popen` is waited in `finally`.

### 1.2 Budget

`Budget(seconds, clock=time.monotonic)` with `remaining()`, `expired()` and `child(seconds)`
(deadline `min(parent deadline, now + seconds)`). `build()` creates one run budget; every stage draws
a child.

| Constant | Value | Source | Used by |
|---|---|---|---|
| `SINGLE_BUDGET_SECONDS` | 5.0 | brief | whole run when the pipeline is off (switch `"0"`, no key, or a sibling failed to load) |
| `PIPELINE_TOTAL_SECONDS` | 90.0 | pi `totalMs` | whole run when the pipeline is on |
| `PLANNER_SECONDS` | 15.0 | pi `plannerMs` | planner share `min(15, max(0, 90 − 15 − 8))` |
| `SEARCH_SECONDS` | 15.0 | pi `searchMs` | session open; each planned search `min(15, max(0, remaining − 8))`; the fallback search |
| `SCORE_SECONDS` | 8.0 | pi `scoreMs` | Jev stage `min(deadline, now + 8)` |
| `ATTEMPT_SECONDS` | 15.0 | pi `SCORE_TIMEOUT_DEFAULT_MS` | each Jev attempt `min(15, score deadline − now)` |
| `GRACE_SECONDS` | 0.5 | rev 2 | proxy close |

Host timeouts sit above the larger total: Claude `hooks.json` `"timeout": 100`; Copilot
`timeoutSec: 100`, carried from the same source value by the adjuster (A1). W2a and I5 derive the
ordering (`timeout > max(totals) + GRACE_SECONDS`) from the module constants. Claude Code's hook doc
(code.claude.com/docs/en/hooks, READ by the feasibility review) gives `command` hooks a default of
600 s, lowered to 30 s on `UserPromptSubmit`, and states no maximum; the explicit 100 is therefore
required, and W2a's docstring says so. Copilot's `timeoutSec` semantics are grounded in Q0.3
(UNVERIFIED until then; stop condition there). Hermes is bounded by the budget alone.

Expected latency (INFERRED from measured parts): pipeline on ≈ 10–20 s per gated prompt (spawn
0.17 s + handshake + one chat completion + up to 6 searches × ~1.3 s + 1–4 Jev batches);
single-search ≈ 1.5 s. The P4 demo measures both.

### 1.3 Resolution and switches

- **Kill switch.** `AI_BADGER_MEMORY_CONTEXT`, read at call time. Only the literal `"0"` disables
  everything (no spawn, no HTTP). SKILL.md and the changelog state the literal.
- **Pipeline decision.** `pipeline = env.get("AI_BADGER_MEMORY_CONTEXT_PIPELINE") != "0" and
  openrouter_client.api_key(env) is not None and every name in SIBLINGS loaded`. Anything false →
  single-search with `SINGLE_BUDGET_SECONDS`, no HTTP, `query_pipeline.run` never called (B10, B11,
  B13). This is O-7's ruling applied literally: the pipeline is on by default *when the key exists*.
- **Default-on detection (owner ruling).** On when `.ai-badger/project-id` resolves AND the
  executable resolves. The token file is not consulted. No port variable.
- **Planner model.** `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL` wins; else the `medium` tier's
  preferred entry through the one `model_groups.py` (§9.7). A project without
  `.ai-badger/skills/task/` (task declined) has no resolver on either agent → planner `no-model` →
  runner fallback search, unless the override is set (B16).
- **`ENV_NAMES`** (P2, module constant): `AI_BADGER_PROJECT_ID`, `AI_BADGER_MEMORY_CONTEXT`,
  `AI_BADGER_MEMORY_CONTEXT_PIPELINE`, `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`,
  `AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE`, `OPENROUTER_API_KEY`. The test scrub imports it.
- **Env vars not ported from pi**: the `PI_BADGER_QUERY_PIPELINE_*_MS`, `…_SEARCH_LIMIT`,
  `PI_BADGER_JEV_ENDPOINT/MODEL/SCORE_TIMEOUT_MS` tuning knobs. Constants here; tests reach every
  limit through function parameters or module-constant patches.
- **Project id.** Sibling `badger_store.resolve_project_id(cwd)` (`badger_store.py:2105-2119`, READ):
  `AI_BADGER_PROJECT_ID` wins, else the nearest `.ai-badger/project-id`; the walk stops at the
  nearest `.ai-badger/`. Blank → silent. `badger_store` loaded lazily by path; load failure → silent.
  An exported `AI_BADGER_PROJECT_ID` routes every repo to one project; SKILL.md says so.
- **Session id.** From `session_id` or `sessionId`. Blank → silent, nothing spawned.
- **Query.** The trimmed prompt, uncapped (pi parity). Every enriched prompt, and every planned
  query, is persisted in ai-raccoon's search log (ADR-0031 D1).
- **What leaves the machine (O-7, security NOTE-3).** With the pipeline on: the gated prompt
  (planner input, and Jev `state` capped at 32 000 chars), and for up to 48 pooled hits their file
  path, kind and a 500-char excerpt of memory *and source code*, go to OpenRouter. SKILL.md, the
  changelog and ADR-0031 D2 say this in those words.
- **Hermes gates.** The Hermes arm calls `build()` only when (a) `kwargs.get("platform") == "cli"`
  (the positive CLI signal; absent, `None`, empty, unknown or any gateway platform → inert, 0 spawns,
  0 HTTP; P3b.0 confirms the literal in Hermes source) and (b)
  `<project>/.ai-badger/skills/ai-raccoon-memory/` exists (Hermes copies `SHARED_SKILL_MODULES`
  unconditionally, `features/hermes/adjustments/adjust_hooks.py:158-163,211-217`, READ). The
  `platform` kwarg is READ second-hand from `tests/test_hermes_plugin_payloads.py:7,105-110`, which
  cites Hermes's `pre_llm_call` payload (`session_id, user_message, conversation_history,
  is_first_turn, model, platform`) and uses `platform="cli"`.

**Failure visibility.** Expected states are silent on stdout and stderr and add no log line: every
gate skip, disabled, no project, no executable, no session, spawn failure, crash, timeout,
`isError`, JSON-RPC error, malformed output, no hits, every pipeline fallback reason. Only an
unexpected exception in the entry writes one `hook-errors.log` line, never containing prompt text or
the key. The Hermes warning logs the exception type only. `query_pipeline.run()` returns its
fallback reason for tests; v1 records it nowhere (C10).

### 1.4 Per-agent delivery

| Agent | Mechanism | Files |
|---|---|---|
| Claude | Manifest entry `memory-context`, claude arm `hooks-json`/`hooks.json`/`UserPromptSubmit`/`memory_context_hook.py`. `hook_wiring.py` selects the command by script, rewrites `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` → `${CLAUDE_PROJECT_DIR}/.ai-badger/skills/`, wraps it in `guarded()`, keeps `timeout` (`dict(h)` copy, `hook_wiring.py:306-331`, READ by feasibility), dedupes by script identity. Payload carries `hook_event_name: "UserPromptSubmit"` → the entry prints `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":block}}` | `features/common/hooks/hooks-manifest.json`, `features/common/hooks/hooks.json` |
| Copilot | Copilot arm `hooks-json`/`userPromptSubmitted`/`memory_context_hook.py`, generated by `features/copilot/adjustments/adjust_hooks.py`, which rewrites the skills path to `.ai-badger/skills/` and (P1) carries `timeout` 100 into `timeoutSec`. Payload `{sessionId, timestamp, cwd, prompt}` (MEASURED, P0) → the entry prints `{"additionalContext": block}` (the only shape Copilot CLI 1.0.88 consumed, 3/3; envelope 0/3, MEASURED). Repo hooks load only in a folder listed in `~/.copilot/config.json` `trustedFolders` (MEASURED gotcha; SKILL.md says so) | manifest; adjuster (P1) |
| Hermes | Manifest arm `plugin`/`ai_badger_hooks.py`/`pre_llm_call`. `pre_llm_inject_context` (`ai_badger_hooks.py:634-729`) gains `_load_memory_context()` via `_load_sibling_module`; the block is appended last in its own `try/except`, followed by the closing line `(end of memory context)` outside the parity block. Inputs: `message or user_message`, `_project_cwd(cwd)`, `kwargs["session_id"]`, gated on `platform == "cli"` and the decline check (§1.3). `SHARED_SKILL_MODULES` gains four rows: `("ai-raccoon-memory","memory_context.py")`, `("ai-raccoon-memory","openrouter_client.py")`, `("ai-raccoon-memory","query_pipeline.py")`, `("task","model_groups.py")`. **Memo:** module dict `session_id -> (sha256(prompt), result)`; same (session, prompt) returns the cached result (block or `None`, failures included) without spawning or HTTP; a new prompt replaces the entry; cleared inside `on_session_start_drift_notice` (registered callback, `:423`; already calls `reset_gate_state()` at `:430`) | `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py:35-43`, `tests/test_hermes_plugin_install.py` twin rows |
| pi | Nothing | none |

**Output-shape rule.** `hook_event_name == "UserPromptSubmit"` (the documented Claude common input
field; Q0.3 cites it) selects the envelope; every other payload, including one where a future
Copilot adds `hook_event_name: "userPromptSubmitted"`, gets the flat shape. One object carrying both
keys was rejected: whether Claude tolerates an unknown top-level key is unverified, and the payload
already tells the two hosts apart.

**Why the Hermes memo caches the result.** `pre_llm_call` frequency is contradicted in-repo
(`validate.py:199` vs `ai_badger_hooks.py:640`). Caching the result keeps the context on
continuations at no cost; with a 10–20 s pipeline it is one wait per turn instead of one per tool call.

### 1.5 Parity with pi

**Oracle.** Goldens come from running pi's TypeScript under bun (`/opt/homebrew/bin/bun`) at
`ee5f1c6e…`; a retyped golden is not acceptable. The same rule covers the pipeline (Q0.2). GP1
checks each golden file's provenance fields.

**Ported as JS does** (pinned by C-rows):
- Whitespace. `JS_SPACE` is the ECMAScript WhiteSpace ∪ LineTerminator set (`\t \n \v \f \r`,
  U+0020, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000, U+FEFF). `js_trim`
  strips it; every `.trim()` in the port is `js_trim`. Python's own `str.strip()`/`\s` differ (they
  include U+001C–U+001F and U+0085 and exclude U+FEFF), so they are not used.
- `ranking` via `??`: numbers through `js_number`; strings raw after `sanitize_field`; `true`/`false`
  as JS prints them; `None`/absent → `?`.
- `js_number`: shortest round-trip digits; exponent form only when the decimal exponent is < -6 or
  ≥ 21, spelled `1e-7` / `1e+21`; integral floats without `.0`.
- `path` = `sanitize_field(path ?? sourceFile ?? "")`, then `js_trim`, then `or "?"`; `""` does not
  fall back to `sourceFile` (`rag-core.ts:177,261,271`, READ).
- Line suffix via `!== undefined`: `lineStart: 0` → `:0-5`; a present `null` → `:10-null`.

**O-2 sanitising (owner ruling).** `FIELD_BREAKS = {\r, \n, \t, \v, \f, U+0085, U+2028, U+2029}`.
`sanitize_field` replaces each maximal run of `FIELD_BREAKS` characters with one space and leaves
every other character raw (so `docs/My  Notes.md` and rank `"high"` render exactly as pi renders
them). `one_line` (snippets and the query echo) is pi's `replace(/\s+/g, " ").trim()` over
`JS_SPACE ∪ {U+0085}`.

**The byte-identity promise, scoped.** `format_block` output equals pi's `toMemoryContext` output
byte for byte for every hit list in which (a) no `path`, `sourceFile` or string `ranking` contains a
`FIELD_BREAKS` character, (b) no snippet contains U+0085, (c) every `ranking` is a number, string,
boolean, `null` or absent, and (d) no snippet or query is truncated inside a non-BMP character.
Outside those conditions the accepted divergences apply:
- path/rank with a `FIELD_BREAKS` character: collapsed here, raw in pi (O-2; a pi issue is filed);
- snippet with U+0085: collapsed here (a line break for many renderers), kept in pi;
- `ranking` of another type (list, object): `?` here, JS `String()` in pi;
- truncation counts code points, not UTF-16 units (a lone surrogate cannot be UTF-8 encoded on the
  Hermes path);
- `server_rank` parses numeric strings with a decimal-literal regex, not JS `Number()` (`"0x10"`,
  `"1_000"` rank last);
- Jev batches the pool in runner order (pi's `capPool` re-sort differs only for numeric-string ranks);
- `parse_plan` returns `no-json-object` for planner text over 64 KiB (pi parses any length).

### 1.6 pi exclusion

Structural, no in-script guard: (1) no `pi` arm; `HOOK_CAPABLE_AGENTS = ("claude","hermes","copilot")`
(`tooling/validate.py:180`, READ); (2) pi's `before_agent_start` spawns only `DELIVERY_SCRIPT`
(`features/pi/adjustments/adapter/index.ts:68,324,729-733`) and `loadGates()` reads only
Pre/PostToolUse (`:101-114`, READ); (3) pi never calls `pre_llm_inject_context`. pi may carry the
module files (Hermes copies them into the shared `.ai-badger/hooks/` in a hermes+pi project) but
never invokes them. I8 asserts what pi executes.

### 1.7 F2: manifest arm-resolution check

`tooling/validate.py` gains `hooks_manifest_unresolved(root) -> List[str]`, reported next to agent
coverage (`validate.py:650`).
- `entry` resolves relative to the manifest's own directory (glob `features/*/hooks/hooks-manifest.json`, `validate.py:372`).
- `hooks-json` arm (Claude, Copilot): exactly one command under the arm's own event matches the
  generators' rule `command.rstrip('"').endswith(script)` and its basename equals `script`. Zero or
  several → gap. Copilot events map through `COPILOT_TO_SOURCE_EVENT`, moved from the adjuster's
  local `event_map` (`adjust_hooks.py:112-118`, READ) into `engine/badger_lib.py`.
- `plugin-hooks-json` arm: resolves against repo-root `hooks/hooks.json` (the drift-notice exception).
- Hermes `plugin` arm: `ast`-parse the entry and collect every `ctx.register_hook(<str>, <Name>)`;
  resolves on a registered event or callback name.
- Unknown arm `type`, unreadable `entry` → gap, never a crash. No discovery-fallback exemption:
  P1 adds explicit `UserPromptSubmit` commands for `prompt-markers/scripts/user_prompt_hook.py`
  (Copilot `timeoutSec` 5 → 10, named in the changelog). The check ignores `matcher` (documented).

---

## 2. Rulings table

| Id | Ruling | Where it lands |
|---|---|---|
| Brief | Fires every prompt, gated by the `shouldEnrich` port minus `/skill:` | P2 C1–C7 |
| Brief | pi excluded | §1.6, I8 |
| Brief | Accept the full wait; host timeout above the budget; any failure → nothing or fallback, exit 0 | §1.2, T12–T16, H3/H8, W2a, I5 |
| Brief | Stdlib-only 3.10+; tests never touch the live serve, the network, a real key or real `$HOME` | §6 shared fixtures, G1, G2, G4 |
| Owner transport ruling | Proxy per call, `argv == [exe]`, PATH then `~/.dotnet/tools`; handshake then `tools/call {projectId, sessionId, query, limit:5, scope:"project"}`; never pi; one process; one deadline; kill + reap; default-on = project id + executable; `"0"` kill switch; no port variable | §1.1–1.3, P2 |
| Owner pipeline rulings | Port pi's pipeline; planner via OpenRouter chat completions with `DELEGATOR_PERSONA + "\n\n" + PLANNER_ADDENDUM`, `medium` model via `model_groups.py`, override env; Jev via `/api/alpha/decisions`; key from env only; HTTP hygiene; hermetic tests with bun goldens | §9, Q0–Q3 |
| P0 (done) | Copilot branch A: flat `additionalContext`; payload `{sessionId, timestamp, cwd, prompt}` | §1.4, H2, I5, I7; research record addendum |
| F2 | Every manifest arm resolves; watched red on a deleted command | §1.7, P1 V1–V16 |
| R1–R6, Q-R1 | As rev 3 (script arms, one deadline, no expanded mode, Hermes memo, pi structural, Hermes method resolves on event or callback name) | §1.4, §1.7, P1, P3b |
| prompt-markers | Accept Copilot `timeoutSec` 5 → 10 and the reorder in `test_context_enrichment_wiring_end_to_end.py:57`; name the test in the PR if edited | P1 |
| O-1…O-7, Budget | Carried unchanged (§13) | §1.1, §1.2, §1.3, §1.5, §9.2 |

## 3. Conflicts resolved

| # | Conflict | Resolution |
|---|---|---|
| C1 | Module split | Three modules + entry (binding 3). |
| C2 | Copilot wiring | P0 verdict A: full arm, flat output. |
| C3 | Hermes arms naming callbacks | Event or callback name resolves (Q-R1). |
| C4 | Discovery fallback in F2 | Strict; prompt-markers explicit. |
| C5 | `PI_SESSION_ID` guard | Cut. |
| C6 | Kill-switch name | `AI_BADGER_MEMORY_CONTEXT`. |
| C7 | Test route to the fakes | Fake `ai-raccoon` first on a temp PATH with a temp HOME; fake OpenRouter on `127.0.0.1`, reached through a parameter or the sentinel-guarded test base. |
| C8 | Host timeouts | Claude `timeout` 100; Copilot `timeoutSec` carried from it (A1). |
| C9 | Error visibility | Expected failures silent; unexpected → one log line, no prompt, no key. |
| C10 | Telemetry | Out of v1; follow-up issue (fallback reason, Jev usage). |
| C11 | Hermes memo | Caches the result, failures included. |
| C12 | Manifest row placement | Integration package (P4). |
| C13 | ADRs | One: `docs/adr/0031-per-prompt-memory-context-through-the-ai-raccoon-proxy.md`, decisions D1 (transport) and D2 (pipeline over OpenRouter). Next free number is 0031 (MEASURED `ls docs/adr`: last is 0030); re-check at rebase. |
| C14 | Nested `.ai-badger/` without id | Stop (badger_store). |
| C15 | `SHARED_SKILL_FILES` twin | Existing equality test enforces the rows. |
| C16 | Kill scope | Pid only (O-1). |
| C17 | Spec §0 "direct HTTP vs proxy" | Stale; the proxy ruling stands. |
| C18 | "Jev fails → single search" vs pi's source | pi's source (O-6): null scores, merge by server rank. |
| C19 | Resolver route | Load the one `model_groups.py` by a layout-exact path; pass it the project registry (§9.7). |
| C20 | Planner env name | `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`. |
| C21 | pi dedupes twice | One implementation: the runner takes `prune_hits` as a parameter. |
| C22 | Pool cap in two pi files | The runner owns `POOL_MAX = 48`. |
| C23 (new) | Missing key: pi parity (runner `no-model`) vs O-7 wording | O-7 wins: no key → pipeline off, 5 s budget (security MUST-2; pi's planner does not use the key, so parity never argued for the 90 s path). |
| C24 (new) | Security MUST-1 suggested "except DNS (R-i)" | Binding 2 wins: DNS is under the deadline via a resolver thread (§9.5). |
| C25 (new) | Declined `task`: Claude has no resolver, Hermes does (feasibility F5) | Aligned: the resolver is used only when `<nearest .ai-badger>/skills/task/` exists, on both agents (B16). |

---

## 4. Packages

One task PR. **Lanes never push.** Each implementation lane works in its own worktree
(`isolation: worktree`) branched from the task-branch head the integrator names, commits one or
more coherent commits, runs its own package gate, and hands back the commit SHAs. The integrating
session merges lanes into `task/aib-ai-raccoon-prompt-rag-hook`, runs the closing step once per
merge wave, and pushes (draft PR opened after the first wave).

**Closing step (integrator only):**
```
$PY tooling/sync_plugin_skills.py
$PY tooling/index_build.py
$PY features/common/skills/welcome-ai-badger/scripts/scaffold.py --config .ai-badger/config.json --target . --root . --no-install
   # use the exact remediation command gates/scaffold_freshness_guard.py prints, plus --no-install
$PY tooling/sync_plugin_skills.py --check && $PY tooling/index_build.py --check && $PY gates/scaffold_freshness_guard.py
git diff origin/main -- .ai-badger .claude .github   # no IDE-formatter drift ships
git fetch --tags   # release_guard reads local tags
```
`--no-install` keeps the self-scaffold from rewriting `~/.hermes/plugins/ai-badger/`. Generated paths
lanes must not commit: `skills/ai-raccoon-memory/scripts/`, `.ai-badger/**`, `.claude/settings.json`,
`.github/hooks/ai-badger-hooks.json`, `index.json`, `.claude-plugin/plugin.json`, `marketplace.json`,
`docs/changelog/README.md` (P1 generates the README row in its lane only because it is the one lane
touching the changelog index; the integrator re-runs `changelog_index.py` if a rebase conflicts).

**Lane gate vs pre-push.** A lane's acceptance is its own gate; "pre-push green" is an integration
acceptance, checked per merge wave by the integrator.

**Python floor.** Every new module runs on 3.10: no `datetime.UTC`, `tomllib`, `ExceptionGroup`,
`typing.Self`; `str.removeprefix` and `http.server.ThreadingHTTPServer` are fine.

### 4.0 Context map

| Kind | Paths |
|---|---|
| Primary (new) | `features/common/skills/ai-raccoon-memory/scripts/{memory_context,openrouter_client,query_pipeline,memory_context_hook}.py`; `docs/adr/0031-per-prompt-memory-context-through-the-ai-raccoon-proxy.md` |
| Primary (edited) | `features/common/hooks/hooks.json`, `features/common/hooks/hooks-manifest.json`, `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py`, `features/copilot/adjustments/adjust_hooks.py`, `tooling/validate.py`, `engine/badger_lib.py` |
| Read-only dependencies | `features/common/skills/task/scripts/model_groups.py` (`load_groups`, `resolve`, `_emit_id`, `:14-21,289-358`), `features/common/data/model-groups.json`, `features/common/personas/delegator.md`, sibling `badger_store.py` |
| Tests (new) | `tests/test_memory_context_{core,transport,openrouter,planner,jev,pipeline,pipeline_wiring,hook,hermes,integration}.py`, `tests/test_hooks_manifest_resolution.py`, `tests/memory_context_support.py` (guards, scrub, fake-bin fixtures), `tests/memory_context_openrouter.py` (fake servers), `tests/fixtures/memory_context/*` |
| Tests (edited) | `tests/test_every_check_can_fail.py`, `tests/test_validate.py`, `tests/test_skills_lint.py`, `tests/test_adjust_hooks_copilot.py`, `tests/test_hermes_plugin_install.py`, possibly `tests/test_scaffold_hook_wiring.py`, `tests/test_context_enrichment_wiring_end_to_end.py` |
| Patterns to follow | sibling load by path under a distinctive `sys.modules` key (`context_enrichment_hook.py:41-68`); Hermes `_load_sibling_module` + reset fixture (`tests/test_sibling_module_loading.py:34-55`); guarded entry (`context_enrichment_hook.py:169-199`) |
| Edit sequence | Wave 1: P1 ∥ P2 ∥ Q0 → Wave 2: Q1 ∥ Q2 → Wave 3: Q3 → Wave 4: P3a ∥ P3b → P4 (§5) |

### P1: release skeleton, F2 check, explicit prompt-markers wiring, Copilot adjuster

- **P1.1 Release skeleton.** `VERSION` 0.177.3 → 0.178.0; `$PY tooling/version_sync.py`;
  `docs/changelog/0.178.0-per-prompt-memory-context.md` stub (feature, pipeline, F2 check, Copilot
  timeout carry); `$PY tooling/changelog_index.py`.
- **P1.2** Move the Copilot event map to `engine/badger_lib.py` as `COPILOT_TO_SOURCE_EVENT`; the
  adjuster imports it (pure refactor).
- **P1.3 Timeout carry, red first.** A1 in `tests/test_adjust_hooks_copilot.py` fails against the
  literal; then change `adjust_hooks.py:148` to `"timeoutSec": h.get("timeout", 10)`. The discovery
  path's literal 5 (`:176`) stays (prompt-markers leaves it in P1.6). Every existing source command
  has either no `timeout` or `timeout: 10` (MEASURED: 50 commands, 10 carry `"timeout": 10`), so the
  generated file does not change for any existing entry.
- **P1.4** Red first: `tests/test_hooks_manifest_resolution.py` against a stub
  `hooks_manifest_unresolved` returning `[]`; watch V1 fail. Implement §1.7; one `_report` line at
  `validate.py:650`.
- **P1.5 Fixtures the check turns red.** The three helpers that write a miniature manifest
  (`tests/test_every_check_can_fail.py:553-574` with provocations `:897-913` and controls
  `:1057-1066`; `tests/test_validate.py:17-27`; `tests/test_skills_lint.py:22-32`) each write a
  resolving `hooks.json`, the Copilot event spelling, and a Hermes stub entry that registers the
  method. Their rc-1 tests still fail for their own reason, asserted on the message.
- **P1.6** Add `prompt-markers/scripts/user_prompt_hook.py` commands to `hooks.json`
  `UserPromptSubmit` (no `timeout` key; Copilot gets the default 10). Prove dedupe (V14, V15).
- **P1.7** Register the check in `test_every_check_can_fail.py` REGISTRY with the deleted-command provocation.
- **Acceptance:** real manifest resolves (`[]`); the check watched red on a tmp copy with the
  `context_enrichment_hook.py` command deleted (exactly 2 gaps: claude, copilot) and green again;
  `validate --all` exits non-zero on any gap; the five meta-test controls exit 0; A1 green and red
  under the literal; re-wiring a target with a literally different prompt-markers entry leaves one.
- **Gate:** `$PY -m pytest -q tests/test_hooks_manifest_resolution.py tests/test_hooks_manifest_agent_coverage.py tests/test_every_check_can_fail.py tests/test_validate.py tests/test_skills_lint.py tests/test_adjust_hooks_copilot.py tests/test_scaffold_hook_wiring.py tests/test_context_enrichment_wiring_end_to_end.py`;
  `$PY tooling/validate.py --all`; `$PY tooling/version_sync.py --check`; `$PY tooling/changelog_index.py --check`;
  pylint on touched non-test files.
- **Files:** `VERSION`, `.claude-plugin/plugin.json`, `marketplace.json`, `docs/changelog/0.178.0-per-prompt-memory-context.md`,
  `docs/changelog/README.md`, `engine/badger_lib.py`, `features/copilot/adjustments/adjust_hooks.py`,
  `tooling/validate.py`, `features/common/hooks/hooks.json`, `tests/test_hooks_manifest_resolution.py` (new),
  `tests/test_every_check_can_fail.py`, `tests/test_validate.py`, `tests/test_skills_lint.py`,
  `tests/test_adjust_hooks_copilot.py`, possibly `tests/test_scaffold_hook_wiring.py`.

### P2: `memory_context.py` (core, budget, transport, single-search build), test support, block goldens

- **P2.1 Test support first** (`tests/memory_context_support.py`, §6 shared fixtures): env scrub
  from `ENV_NAMES` plus proxy variables; temp HOME; fake bin dir; the real-executable guard and the
  network guard (in-process and `sitecustomize`) with refusal lists, the `GuardRefusal(BaseException)`
  raise and the autouse teardown; fake ceilings.
- **P2.2 Fake executable** `tests/fixtures/memory_context/fake_ai_raccoon.py`, written into the
  temp bin dir as `ai-raccoon` (`#!<sys.executable>`, 0755) with a `python3` symlink to
  `sys.executable`. Modes (`FAKE_RACCOON_MODE`): `hits`, `empty`, `iserror`, `rpcerror`,
  `malformed`, `drip`, `hang`, `crash`, `nostdin`, `oversize`, `slowinit`, `grandchild`, `perquery`
  (hits from a JSON map `query -> {results, code}` named by `FAKE_RACCOON_HITS`; unknown → empty),
  `latereply` (holds reply 1 until it has *read* request 2's line, then writes reply 1 then reply 2;
  the two queries map to different hits). `hang`, `drip` and `nostdin` exit after 20 s
  (`FAKE_CEILING_SECONDS`). Every invocation appends `{pid, argv, mode, stdin_lines, saw_eof}` to a
  JSONL log in the test's temp dir.
- **P2.3 Block goldens.** `tests/fixtures/memory_context/gen_goldens.ts` imports `rag-core.ts` and
  prints `toMemoryContext` for every case in `golden_inputs.json`; output committed as
  `golden_outputs.json` with `{"pi_commit": "ee5f1c6e…", "generator": "gen_goldens.ts", "bun": "<version>"}`.
  Inputs: empty/empty, mem-only, code-only, 7+7 caps, snippet-dup, hash-dup, `sourceFile`-only,
  `path: ""`, missing rank, `ranking: 0`, `ranking: null`, `5e-05`, `1e-7`, `1e21`, rank `"high"`,
  rank `true`, path `docs/My  Notes.md`, path with inner U+00A0 and leading U+FEFF, snippet with
  U+001C and U+00A0, `lineStart: 0`, `lineEnd: null`, multi-line snippet > 300 chars, query > 80
  chars. Divergence inputs are not in the bun goldens; their rows assert Python behaviour directly.
  CI does not run bun.
- **P2.4** Stubs so tests go red on assertions. Implement the pure section, `Budget`,
  `find_executable`, `RaccoonSession`, `ENV_NAMES`, `SIBLINGS`, `RESOLVER`, and `build()` in its
  single-search form (Q3 adds the pipeline branch). T13 is written first against a naive
  `readline()` and watched to exceed its bound (by the fake's ceiling, not a hang).
- **Acceptance:** every G, C, T, S1, B1–B8 and GP1 row green, each mutation applied by hand and seen
  red once; `format_block` equals every bun golden; the guard teardown reports 0 refusals across the
  module.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_core.py tests/test_memory_context_transport.py`;
  pylint on `memory_context.py`; `$PY gates/docs_guard.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` (new),
  `tests/test_memory_context_core.py`, `tests/test_memory_context_transport.py`,
  `tests/memory_context_support.py`, `tests/fixtures/memory_context/{fake_ai_raccoon.py,gen_goldens.ts,golden_inputs.json,golden_outputs.json}` (all new).

### Q0: ADR-0031, pipeline goldens, docs grounding (no `features/` edit)

- **Q0.1 ADR first.** `docs/adr/0031-per-prompt-memory-context-through-the-ai-raccoon-proxy.md`
  (Nygard) + `docs/adr/README.md` row.
  - *Context:* per-prompt retrieval for Claude, Copilot and Hermes; ai-raccoon ADR-0106/F70 and the
    zero-secret-bytes invariant; stdlib lacks ECDSA; pi's pipeline measured better retrieval than one
    search (cite pi's research); one-shot hook constraints; P0 Copilot measurement.
  - *Decision D1 (transport):* proxy per call, `argv == [exe]`, one run budget, graceful stdin close
    then kill pid only, default-on detection, the `"0"` kill switch, per-host output shape.
  - *Decision D2 (pipeline):* port pi's pipeline; planner and Jev over direct OpenRouter HTTP; one
    proxy session for every search; child budgets; resolver-thread DNS deadline, per-address connect
    timeout, handshake deadline and watchdog; pipeline only with a key; single-search otherwise;
    Jev failure merges by server rank (O-6); layout-exact resolver route (§9.7); sentinel-guarded
    loopback test base.
  - *Consequences:* positive (better recall, pi parity, no token in the hook); negative (+0.17 s
    spawn and ~1.3 s per search; 10–20 s typical and 90 s cap per gated prompt with a key; the proxy
    may start a serve; every enriched prompt and planned query lands in the search log; what leaves
    the machine per §1.3; per-prompt OpenRouter cost; a watchdog thread per HTTP call; a hung DNS
    resolver thread may outlive its call, at most one per host; project-chosen planner model (R-g);
    Hermes blocks the turn up to the budget; memo scope in gateways); neutral (four Hermes rows,
    three mirrored module files).
  - *Alternatives:* direct HTTP to ai-raccoon with the token (F70); `--transport stdio` (slated for
    removal); persistent proxy per Hermes process (deferred); process-group kill (O-1); spawn pi as
    planner (ruled out); parallel searches (one child; pi is sequential); no Jev (loses the merge
    signal); per-socket timeouts without a watchdog (a drip defeats them); DNS left unbounded
    (binding 2); resolver options A/B (§9.7); four pipeline modules (more rows, no behaviour).
- **Q0.2 Pipeline goldens.** `tests/fixtures/memory_context/gen_pipeline_goldens.ts` imports pi's
  `planner.ts`, `jev-client.ts`, `merge.ts`, `pipeline.ts` and `tests/query-pipeline/fixtures/score-fixtures.ts`
  at `ee5f1c6e…` and writes `pipeline_goldens.json` (`pi_commit`, `generator`, `bun`): planner prose,
  `build_user_prompt` outputs, `parsePlan` over the PL3 corpus, `PlannerFallbackReason`; Jev
  constants and prose, request bodies captured through an injected `fetchFn` for the J2 candidate
  sets, error and retryable kinds; `mergeSelect` over the MG1 cases; `runPipeline` scenario outcomes
  (R3) with injected `plan`/`search`/`score`; the runner reason list; and `score_fixtures.json`
  (every export of `score-fixtures.ts`, serialized by bun). Inputs in `pipeline_golden_inputs.json`
  may be transcribed from pi's tests; outputs must come from running pi.
- **Q0.3 Grounding** (fetched and cited in the research record, each graded): OpenRouter
  `/api/v1/chat/completions` request (`model`, `messages`) and response (`choices[0].message.content`
  string or parts); any OpenRouter doc for `/api/alpha/decisions` (else "measured by pi, not
  re-measured"); Claude Code hooks doc — the `timeout` row (READ by feasibility; recorded now) and the
  common input field `hook_event_name`; Copilot CLI hooks doc — `timeoutSec` default and maximum,
  and the `userPromptSubmitted` output contract. **Stop condition:** if Copilot documents a
  `timeoutSec` maximum below 91, stop and return to the owner before P4.
- Record in the research record, one line: "P0 Copilot capability spike: done 2026-09-28, verdict A
  (addendum above)."
- **Acceptance:** ADR merge-ready with both decisions; `pipeline_goldens.json` regenerates
  byte-identically on a second bun run; every golden input has an output; grounding recorded with grades.
- **Gate:** `bun tests/fixtures/memory_context/gen_pipeline_goldens.ts | diff - tests/fixtures/memory_context/pipeline_goldens.json`
  (by hand; CI does not run bun); `$PY gates/docs_guard.py`.
- **Files:** `docs/adr/0031-….md` (new), `docs/adr/README.md`, `tests/fixtures/memory_context/{gen_pipeline_goldens.ts,pipeline_golden_inputs.json,pipeline_goldens.json,score_fixtures.json}` (new),
  `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md`.

### Q1: `openrouter_client.py` and the fake servers

- Red first: O-rows against a stub `post_json` returning `Reply(200, {}, b"{}")`; O4 and O4b first
  against a version without the watchdog, O10 against a fixed per-attempt timeout, O11 against an
  inline `getaddrinfo`; each watched to exceed its bound (ending at the fake's 20 s ceiling).
- Implement §9.5 and `api_base` (§9.6).
- Fake servers in `tests/memory_context_openrouter.py` (§6).
- **Acceptance:** O1–O4, O4b, O6–O11 green, each mutation seen red; S1 green over the new module;
  no live thread named `ai-badger-openrouter-*` after any row; pylint clean.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_openrouter.py tests/test_memory_context_transport.py -k S1`;
  pylint on `openrouter_client.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py` (new),
  `tests/test_memory_context_openrouter.py` (new), `tests/memory_context_openrouter.py` (new).

### Q2: `query_pipeline.py` (planner, Jev, merge, runner)

- Stubs; PL, J and MG/R rows red on assertions; implement §9.2–9.4. Every row drives injected
  `post`/`search`/`score` callables returning `Reply` objects or timeout values, and a `Budget` on a
  fake clock; no socket, no thread (QA F12). The wiring proofs through the real `post_json` are
  B15 and J6b in Q3.
- **Acceptance:** PL1–PL7, J1–J9, MG1, MG2, R1–R3, R5–R8 green, mutations seen red; `plan`,
  `score`, `run` never raise; S1 green over the module; pylint clean.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_planner.py tests/test_memory_context_jev.py tests/test_memory_context_pipeline.py tests/test_memory_context_transport.py -k S1`;
  pylint on `query_pipeline.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/query_pipeline.py` (new),
  `tests/test_memory_context_{planner,jev,pipeline}.py` (new).

### Q3: wiring into `build()`

- Red first: B9–B17 and J6b against the P2 `build()`. Then add the sibling loads over `SIBLINGS`,
  the layout-exact resolver locator and the task-dir check (§9.7), the pipeline decision (§1.3) and
  the pipeline branch (§9.2).
- **Acceptance:** B9–B17 and J6b green, mutations seen red; every P2 row still green (single-search
  unchanged); S1 green over all four new files.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_pipeline_wiring.py tests/test_memory_context_transport.py tests/test_memory_context_core.py tests/test_memory_context_openrouter.py tests/test_memory_context_planner.py tests/test_memory_context_jev.py tests/test_memory_context_pipeline.py`;
  pylint on `memory_context.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/memory_context.py`,
  `tests/test_memory_context_pipeline_wiring.py` (new).

### P3a: Claude/Copilot entry

- Write `memory_context_hook.py` (stdin → `build` → per-host output shape; `guarded_main`;
  closed-stdout safe).
- Append the `UserPromptSubmit` command `python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/ai-raccoon-memory/scripts/memory_context_hook.py"`
  with `"timeout": 100` to `features/common/hooks/hooks.json` (inert until P4's manifest row;
  repo-root `hooks/hooks.json` holds only the drift notice, READ by feasibility).
- Commit the P0 payload verbatim as `tests/fixtures/memory_context/copilot_user_prompt_payload.json`
  (tests replace its `cwd` with the temp project).
- **Acceptance:** H1–H12 and W2a green, mutations seen red.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_hook.py tests/test_context_enrichment_hook.py`; pylint on the entry.
- **Files:** the entry (new), `features/common/hooks/hooks.json`, `tests/test_memory_context_hook.py` (new),
  `tests/fixtures/memory_context/copilot_user_prompt_payload.json` (new).

### P3b: Hermes arm and memo

- **P3b.0** From Hermes source (the installed CLI is absent on this machine, MEASURED `hermes`
  ENOENT; read upstream source), record in the research record with file:line: the `platform` value
  a CLI session passes to `pre_llm_call` (expected `"cli"`), where Hermes places the returned
  `context`, and whether Hermes bounds a `pre_llm_call` hook's run time. If no positive CLI signal
  exists, the arm ships inert (W7's first column only) and the finding goes to the owner before P4.
- `_load_memory_context()`; in `pre_llm_inject_context`, if `platform == "cli"` and the decline
  check passes, call `build()` through the memo; append the block plus `(end of memory context)`
  last, in its own `try/except` that logs the exception type only.
- Clear the memo inside `on_session_start_drift_notice`.
- `SHARED_SKILL_MODULES +=` the four rows (§1.4), each with its `SHARED_SKILL_FILES` twin row;
  `LEGACY_FLAT_FILES` derives. None of the basenames exists among current Hermes files (MEASURED in
  rev 3). Update the `PLUGIN_YAML` description (`adjust_hooks.py:62-68`).
- Extend the sibling-load derive test (`tests/test_hermes_plugin_install.py:400-436`) to also
  require every name in `memory_context.SIBLINGS + (RESOLVER,)` in the shipped set (feasibility F3).
- **Acceptance:** W1–W4, W6–W10, M1–M4 and the extended derive test green, mutations seen red; other
  `pre_llm_call` parts survive every memory-arm failure.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_hermes.py tests/test_hermes_plugin_install.py tests/test_hermes_plugin_payloads.py tests/test_sibling_module_loading.py`;
  pylint on `ai_badger_hooks.py` and the Hermes adjuster.
- **Files:** `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py`,
  `tests/test_hermes_plugin_install.py`, `tests/test_memory_context_hermes.py` (new), the research record (P3b.0 lines).

### P4: integration (last package; integrating session)

- **P4.1** Merge P3a and P3b; closing step. Manifest entry `memory-context` with claude, copilot and
  hermes arms. File the pi issue for path/rank sanitising (O-2) and the telemetry follow-up (C10).
- **P4.2** `tests/test_memory_context_integration.py` (I rows).
- **P4.3 Docs.** `SKILL.md` section: what it does; the two modes and when each runs (key present and
  switch not `"0"`); latency of each; proxy spawn and possible serve start; kill switch literal
  `"0"`; pipeline switch literal `"0"`; `OPENROUTER_API_KEY` read from env only and exactly what
  leaves the machine (§1.3 wording); planner override and the declined-`task` consequence;
  search-log persistence; exported `AI_BADGER_PROJECT_ID`; the scoped parity promise and its
  divergences; Copilot `trustedFolders` requirement; Hermes CLI-only; POSIX-only; skill `version`
  0.1.0 → 0.2.0. The test base URL is named in ADR-0031, not SKILL.md. `docs/skills.md`
  ai-raccoon-memory section; `docs/dictionary.md` a `memory-context` row beside the memory-first
  gate row (`:27`); `docs/hermes-claude-compatibility.md:11-16,31` (the `pre_llm_call` list).
  `README.md:204` and `docs/skills.md:106` change only if the SKILL `description` does; say which in
  the PR. `docs/dictionary.md:22` belongs to #530.
- **P4.4** Changelog text final (§8); rebase last (ADR number, changelog README row).
- **P4.5 Fired-in-anger demo** (manual, pasted into the PR; a deliberate install run; the only step
  that touches the real network). Claude, in this repo, serve running, key exported: one enrichable
  prompt shows the block; record planner model id, planned queries, `tools/call` count, one proxy
  process (`pgrep -fl ai-raccoon`), Jev batches, wall time. Key unset: single-search, wall time
  under 5 s. `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0`: single search, no HTTP. `AI_BADGER_MEMORY_CONTEXT=0`:
  no block. Serve stopped: whether the proxy started a serve, whether it still listens after exit
  (`lsof -iTCP:7721`), no proxy process remains. **Copilot**, repo in `trustedFolders`: one prompt
  whose answer depends on the block (the P0 method) and the hook's wall time under the pipeline.
  **Hermes** CLI if available: block present, `pre_llm_call` frequency, blocking behaviour; a
  non-CLI platform shows no spawn; else "not demonstrated".
- **P4.6** Run the tri-agent hook checklist
  (`features/common/skills/code-review-evidence/references/ai-badger-hook-feature-review.md`) at
  review; `review-tests` by a non-author over the new test files (invariant).
- **Acceptance:** composed scaffold wires Claude, Copilot and Hermes; pi never executes any new file
  (I8); the wired Claude and Copilot command strings print the right shape against the fakes;
  `validate --all` green and red on each provocation; all release gates green; pre-push green; demo
  pasted; PR names every rewritten test.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_integration.py tests/test_hooks_manifest_agent_coverage.py tests/test_hooks_manifest_resolution.py tests/test_pi_hook_arm_coverage_contract.py tests/test_scaffold_hook_wiring.py tests/test_context_enrichment_wiring_end_to_end.py tests/test_adjust_hooks_copilot.py`;
  `$PY tooling/validate.py --all`; `$PY tooling/index_build.py --check`; `$PY tooling/sync_plugin_skills.py --check`;
  `$PY tooling/version_sync.py --check`; `$PY tooling/changelog_index.py --check`; `$PY gates/docs_guard.py`;
  `$PY gates/scaffold_freshness_guard.py`; `$PY gates/release_guard.py`; pylint on touched files; the
  docs/work README check CI runs. CI runs the full suite on push.
- **Files:** `features/common/hooks/hooks-manifest.json`, `tests/test_memory_context_integration.py` (new),
  `features/common/skills/ai-raccoon-memory/SKILL.md`, `docs/skills.md`, `docs/dictionary.md`,
  `docs/hermes-claude-compatibility.md`, `docs/changelog/0.178.0-per-prompt-memory-context.md`,
  generated outputs.

---

## 5. Parallelism map

```
Wave 1   P1 (validate, adjuster, hooks.json, VERSION) ─────────────────────────┐
         P2 (memory_context.py, support, fake, block goldens) ─┬─ Wave 2 ─ Q1 ─┐│
         Q0 (ADR-0031, pipeline goldens, grounding) ───────────┴─────────── Q2 ─┴┼─ Wave 3 Q3 ─┬─ Wave 4 P3a ─┬─ P4
                                                                                │             └─ P3b ─────┘
                                                                                └─ (P3a also needs P1)
```

| Wave | Lanes | Needs | Disjoint files |
|---|---|---|---|
| 1 | P1 ∥ P2 ∥ Q0 | task-branch head | P1: `VERSION`, stamped JSON, changelog, `engine/badger_lib.py`, both validate/test helpers, Copilot adjuster, `hooks.json`. P2: `memory_context.py`, `tests/memory_context_support.py`, P2 tests and fixtures. Q0: `docs/adr/*`, `tests/fixtures/memory_context/{gen_pipeline_goldens.ts,pipeline_*,score_fixtures.json}`, research record |
| 2 | Q1 ∥ Q2 | P2 (`Budget`, `prune_hits`, support module) and Q0 (goldens) merged | Q1: `openrouter_client.py`, `tests/test_memory_context_openrouter.py`, `tests/memory_context_openrouter.py`. Q2: `query_pipeline.py`, three test files |
| 3 | Q3 | Q1, Q2 | `memory_context.py`, wiring tests |
| 4 | P3a ∥ P3b | Q3 (P3a also P1) | P3a: entry, `hooks.json`, hook tests, payload fixture. P3b: `ai_badger_hooks.py`, Hermes adjuster, Hermes tests, research record lines |
| 5 | P4 | all | integration |

Contracts fixed before any lane starts: `post_json(url, body, key, budget) -> Reply`;
`plan(query, *, post, base, key, model, budget) -> PlanResult`;
`score(query, pool, *, post, base, key, budget) -> list[float | None]`;
`search(query, budget) -> SearchResult | None`;
`run(query, *, plan, search, score, prune, budget, limits) -> RunResult`;
`Budget.remaining() / expired() / child(s)`.

| Shared file | Packages | Order |
|---|---|---|
| `features/common/hooks/hooks.json` | P1, P3a | P1 before P3a |
| `memory_context.py` | P2, Q3 | P2 before Q3 |
| `tests/memory_context_support.py` | P2 only | — |
| `docs/work/…-research.md` | Q0, P3b | different sections; rebase the second |
| `hooks-manifest.json` | P4 only | — |
| Generated outputs | integrator only | serialized per merge wave |
| `docs/changelog/*`, `VERSION` | P1 (skeleton), P4 (text) | rebase last |

---

## 6. Design-tests list

Row format: **behaviour | failure mode | mutation → red**. Default protocol: stubs first so red is an
assertion failure; after green the row's mutation is applied by hand and must go red. Every "silent"
row has a paired control and asserts the fake's invocation count (0 when nothing may spawn, 1 when
the child must be reached and fail), because `CLAUDE_PROJECT_DIR` points at an id-less scratch
project (`tests/conftest.py:112-119`). Pipeline rows also assert the fake OpenRouter's request
count. Timing rows assert upper bounds of at most 3 s against fakes whose blocking behaviour ends by
a 20 s ceiling, so a deadline-removing mutant returns late and fails the bound. Parametrized tables
count as one row.

**Shared fixtures (`tests/memory_context_support.py`, autouse in every new module):**
- *Env scrub:* delete every name in `memory_context.ENV_NAMES` and every proxy variable
  (`http_proxy`, `https_proxy`, `all_proxy`, `no_proxy`, both cases); `HOME` = per-test temp dir;
  `PATH` = per-test fake bin dir. Subprocess tests build `env` from that.
- *Guards and refusals (QA F1):* both guards append each refusal to a per-test list and raise
  `GuardRefusal(BaseException)`; an autouse teardown calls `assert_no_refusals()`, which
  `pytest.fail`s on a non-empty list. Production code catches `Exception` at most (S1 forbids
  `except BaseException` and bare `except:`), so a refusal can neither be swallowed nor go unreported.
  - *Real-executable guard:* at import, before any HOME redirect, record the realpaths of
    `shutil.which("ai-raccoon")` under the original PATH and of `<pwd home>/.dotnet/tools/ai-raccoon`.
    Wrap `subprocess.Popen` (on top of conftest's `_TrackedPopen`) to refuse when `realpath(argv[0])`
    is one of them; record every argv in a per-test spawn log. The forbidden set is a parameter.
  - *Network guard:* in-process, wrap `socket.getaddrinfo` (refuse any host other than
    `"127.0.0.1"`, before resolution), `socket.socket.connect`/`connect_ex` and
    `socket.create_connection` (refuse any address other than `127.0.0.1`). Subprocess runs get the
    same guard through a temp-dir `sitecustomize.py` on `PYTHONPATH` that writes a marker file and
    raises `SystemExit`-class refusal; the teardown also fails on a marker.
- *Threads (QA F4):* `live_openrouter_threads()` returns live threads whose name starts
  `ai-badger-openrouter-` plus live `threading.Timer`s; rows assert it empty. No row asserts
  `threading.active_count()`. Proxy-side rows assert reaped pids.
- *Fake OpenRouter* (`tests/memory_context_openrouter.py`): `ThreadingHTTPServer` on `127.0.0.1:0`
  per test; routes `POST /api/v1/chat/completions` and `POST /api/alpha/decisions`; a script of
  replies per route (status, headers, body, or a behaviour: `hang`, `header-drip`, `body-drip`,
  `oversize`, `redirect <code> <url>`, `close`); records every request (path, headers, parsed body).
  A second instance is the *capture* server. `TlsFake`: the same handler wrapped with a throwaway
  self-signed EC certificate with `subjectAltName=IP:127.0.0.1`, generated per session with
  `openssl req -x509 -newkey ec …` (skip with the reason if `openssl` is absent). `DripTcp`: a plain
  TCP listener that drips bytes. Every blocking behaviour ends by `FAKE_CEILING_SECONDS = 20`.
- *Hermes reset:* pop the memory-context and pipeline `sys.modules` keys, clear
  `_missing_siblings`, `_broken_siblings` and the memo, before and after every Hermes test.

### G: fixtures (`tests/test_memory_context_transport.py`)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| G1 | Real-executable guard: a spawn of a stand-in "real" path is refused and recorded; control with the fake passes. Companion: a stand-in that wraps the spawn in `except Exception` still leaves the refusal recorded, and `assert_no_refusals()` called on it raises `Failed` | A test reaches the live proxy unnoticed; production's catch-all hides the refusal | guard compares unresolved paths; guard raises `Exception`; teardown not autouse |
| G2 | Scrub holds: with `AI_BADGER_MEMORY_CONTEXT=0`, `AI_BADGER_PROJECT_ID=x`, `OPENROUTER_API_KEY=k` and `https_proxy` exported by the outer env, a happy row spawns once with the file's project id, sends 0 HTTP requests, and the guard records 0 refusals | Machine-dependent result; a developer's real key used | remove the scrub |
| G3 | Fake smoke: each mode behaves as named; `hang`, `drip`, `nostdin` each end by the ceiling (run with the ceiling patched to 1 s); `latereply` writes reply 1 only after reading request 2 | A fake that cannot produce the failure; a mutant that hangs the suite | make `hang` reply; drop the ceiling |
| G4 | Network guard: in-process `getaddrinfo("openrouter.ai", 443)` and a connect to `203.0.113.1:443` are refused before any packet and recorded; a subprocess with the `sitecustomize` guard that connects there writes the marker; control to `127.0.0.1` passes. Companion as in G1 | A test reaches openrouter.ai; DNS query leaks | guard allows everything; guard not on `PYTHONPATH`; `getaddrinfo` unwrapped |

### P1: `tests/test_hooks_manifest_resolution.py` (16) + `tests/test_adjust_hooks_copilot.py` (1)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| V1 | Real manifest → `[]`. Red first: tmp copy with the `context_enrichment_hook.py` command deleted → exactly 2 gaps (claude, copilot) | Arm that wires nothing | `return []` |
| V2 | Synthetic Claude arm with no command → 1 gap naming file, hook, agent, event, script | Silent pass | skip arms with `script` |
| V3 | Command under a different event → gap | Wired on the wrong event | search all events |
| V4 | `not_memory_context_hook.py` alone → gap; `memory_context_hook.py` + `x_memory_context_hook.py` → gap | Validator and generators disagree | basename-only; `endswith`-only |
| V5 | Copilot `userPromptSubmitted` resolves via `badger_lib.COPILOT_TO_SOURCE_EVENT`; unmapped → gap | Twin event map | literal copy in validate; drop an entry |
| V6 | `plugin-hooks-json` resolves against root `hooks/hooks.json`; a `hooks-json` arm present only there → gap | Exception widened | one file for both types |
| V7 | Arm resolvable only via skill discovery → gap | Discovery silently accepted | add a discovery branch |
| V8 | Hermes: event string resolves; callback name resolves; unregistered `def` → gap; unknown → gap | Method never registered | accept any `def` |
| V9 | `register_hook("x", f)` in a comment or string does not count | Commented registration passes | regex over text |
| V10 | Unknown arm `type`; unreadable `entry` → gap, no crash | Crash hides other gaps | `continue`; let `OSError` escape |
| V11 | `entry` resolves relative to the manifest's directory (`features/demo/hooks/`) | Fake-root manifests misresolve | hard-code `features/common/hooks/` |
| V12 | `validate --all` exits non-zero on a gap | Detected, not failing | drop `ok &=` |
| V13 | Registered in `test_every_check_can_fail.py` with V1's provocation and an intact control | Unregistered check | omit registration |
| V14 | Claude: target holding a literally different prompt-markers entry for the same script → exactly one entry after re-wire | Prompt markers inject twice | break `_hook_key`; drop the script from `_prune`'s superseded set |
| V15 | Copilot: exactly one `user_prompt_hook.py` entry in `userPromptSubmitted`, `timeoutSec` 10 | Double wiring | run discovery even when the command exists |
| V16 | The three fixture helpers' unprovoked trees exit 0 under `--all`; their rc-1 tests fail for their own named reason | Meta-test controls red / right rc wrong reason | revert a helper |
| A1 | Copilot adjuster carries the source `timeout`: a synthetic source command with `"timeout": 100` → `timeoutSec` 100; one without `timeout` → 10; one with 10 → 10; the real catalog's generated file is unchanged for every existing entry | Copilot kills the pipeline at 10 s | literal `10`; `h.get("timeout")` without default |

### P2 core: `tests/test_memory_context_core.py` (23)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| C1 | Long IDEA prompt → `ok`, `query == js_trim(prompt)`, word count right | Real prompts rejected | default `False`; drop trim |
| C2 | Control words: each of 7, `STOP`, `"  Stop  "` → `control-word`; `"stop"` is `control-word` not `too-short`; `"stop! please halt the build runner now"` enriches | Word lost; gate order; substring | delete a word; length first; `startswith` |
| C3 | Commands: `/delegations`, `/monitors`, `/delegate <long>`, `/skill:task …` → `command`; no `bare-skill-call` | Slash turns searched; pi carve-out ported | delete gate; move below thinness; port `SKILL_PREFIX_RE` |
| C4 | `""`, whitespace → `empty` | Whitespace searched | skip trim |
| C5 | `min_words=1`: 20 chars ok, 19 `too-short` | Off-by-one | `<` → `<=` |
| C6 | 5-word thin prompt → `too-thin`; 6-word ok at default, `too-thin` at `min_words=7` | Floor off-by-one | 6 → 5; `<` → `<=` |
| C7 | `f: please explain …` enriches and the query keeps `f:` | Marker stripped | `re.sub` leading `/\w+:` |
| C8 | Tokenizer table: case fold; `a an the it is on` → 0; `EPIPE ENOENT SIGTERM` counted; `use the api key for env bus` → 5; `wasn't isn't` → 0; `memory_search` whole; `café résumé` → `{caf, sum}` | Tokenizer drift vs JS | drop `.lower()`; `>=2`; `>3`; split on `[^a-z0-9]`; `\W+` |
| C9 | `NOISE_WORDS` is exactly the 35 pi words | Dictionary drift | delete `wasn` |
| C10 | **Bun goldens:** `format_block(case) == golden_outputs[case]` for every committed case (incl. rank `"high"`, rank `true`, path `docs/My  Notes.md`, U+00A0/U+FEFF path, U+001C snippet) | Wording, format or whitespace-class drift from pi (incl. trust header) | change one header char; `str(rank)`; `str.strip()` for `js_trim`; `one_line` on the path |
| C12 | Empty/empty → both placeholders; mem-only → `(no code hits)` under code only | Section vanishes | single `(no hits)` |
| C13 | 7+7 → `[m5]`,`[c5]` present, `[m6]`,`[c6]` absent | Cap wrong | cap 6 |
| C14 | `sourceFile`-only renders sourceFile; `path: ""` does not fall back to sourceFile and renders `?` | `??` semantics lost | `or` instead of `is None` |
| C15 | Drop when path missing/`?` and snippet blank; keep path-only and snippet-only | Wrong drop rule | `and` → `or` |
| C16 | Duplicate hash once, first wins; same snippet different hash once | Dedupe wrong | iterate reversed; require both keys |
| C17 | Snippet 301 → 300 + `…`, 300 untouched; query echo capped at 80 | Boundary; header bloat | `>` → `>=`; echo 300 |
| C18 | `one_line` over `\n \r \t \v \f \x85 U+2028 U+2029` and every `JS_SPACE` char: no line break survives; `"\n- code (snippets"` cannot start a line; U+001C survives (JS parity) | Snippet forges structure; Python `\s` leaks | collapse only `[\n\t ]`; use Python `\s` |
| C19 | `sanitize_field`: path containing `\n- code` does not start a line; path `"a  b"` and `"a b"` are unchanged; a run `"\r\n "` becomes one space (O-2) | Path forges structure; sanitising widens beyond the ruling | interpolate raw path; `one_line` on the path |
| C20 | Prune before cap: 5 dups of A then B, C → B and C render | Slice before dedupe | slice first |
| C21 | Rank table: `1.0`→`1`, `0.8123`, `0`→`0`, `None`/missing→`?`, `5e-05`→`0.00005`, `1e-7`→`1e-7`, `1e21`→`1e+21`, `"x"`→`x`, `"high\nX"`→`high X`, `True`→`true`, `[1]`→`?` | Python number formatting leaks; string rank lost | `str(x)`; `or "?"`; `repr`; `?` for strings |
| C22 | Line suffix: `lineStart 0, lineEnd 5` → `:0-5`; `lineEnd` absent → none; `lineEnd: null` → `:10-null` | Truthiness vs `!== undefined` | truthiness; `is not None` |
| C23 | Non-BMP snippet truncates by code points and the block UTF-8 encodes (accepted divergence) | Lone surrogate crashes Hermes | slice by UTF-16 units |
| GP1 | **Golden provenance (QA F15):** `golden_outputs.json` and `pipeline_goldens.json` each record `generator` equal to their `.ts` name, a non-empty `bun`, and `pi_commit == ee5f1c6e…`; every input key has an output; no `tests/**/*.py` contains a write to either file name | A Python-generated golden passes as pi's | edit `generator`; drop an output; add a writer |

### P2 transport and build: `tests/test_memory_context_transport.py` (32, plus G1–G4)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| T1 | `find_executable`: PATH hit wins; else `<home>/.dotnet/tools/ai-raccoon` if executable; non-executable or absent → `None`; PATH and home read at call time | Real executable captured at import; fallback runs a non-executable | hoist `Path.home()`; drop `X_OK` |
| T2 | Spawn shape: across every mode the spawn log is exactly `[[fake_abs]]` per run; `shell` false; stderr DEVNULL | Shell spawn; argv injection; stderr noise | `shell=True`; add `--transport stdio`; inherit stderr |
| T3 | Wire: `initialize` `2024-11-05`, then `notifications/initialized` with no `id`, then `tools/call` `memory_search` with arguments `== {projectId, sessionId, query, limit:5, scope:"project"}` | Cross-project leak; handshake broken | drop `scope`; add `kind`; skip the notification; limit 8 |
| T4 | `slowinit`: nothing written before the `initialize` reply | Talking to an uninitialized server | write the call before awaiting init |
| T5 | `hits` → mem and code lists parsed from the text part | Permanent silence | read `result` not `content[].text` |
| T7 | `iserror` → `None` | Error text injected as memory | ignore `isError` |
| T8 | `rpcerror` → `None` | KeyError | read `result` unguarded |
| T9 | `malformed` framing: non-JSON lines and wrong ids before the real reply → parsed | Fragile framing | first line only; no id check |
| T10 | Payload table: no text part → `None`; non-JSON text → `None`; missing `results`/`code` → empty lists; both lists empty → empty (absorbs T6) | Crash on drift or on empty | unguarded `json.loads`; index `[0]` |
| T12 | `hang`, budget 0.3 → returns within 2 s; child pid gone | Prompt blocks; orphan | drop the deadline; kill without wait |
| T13 | `drip`, budget 0.3 → returns within 2 s. Written first against blocking `readline()` | Per-line deadline only | blocking `readline()` |
| T14 | `nostdin` with a 1 MiB query, budget 0.3 → returns within 2 s | Blocking write holds the hook | blocking `stdin.write` |
| T15 | `oversize` → `None`, reading stops, child killed | Memory blow-up | remove the cap |
| T16 | `search`/`build` never raise: parametrized over every mode incl. `crash` → `None` (absorbs T11) | Fail-silent broken | remove outer `except` |
| T17 | 20 sequential runs over `hits`/`hang`/`crash` → every recorded pid reaped; no thread started (`threading.enumerate()` names unchanged; no in-process server in this row) | Zombies or threads accumulate in Hermes | skip `wait()`; use a reader thread |
| T18 | Graceful close: in `hits`, the fake records `saw_eof` and exits by itself; no SIGKILL within the grace | Proxy dispose path skipped | kill before closing stdin |
| T19 | `grandchild`: the grandchild (same group) survives the hook's kill; test reaps it | Group kill takes down the shared serve (O-1) | `killpg` |
| T20 | Spawn failure (`PermissionError`, `FileNotFoundError` raced after resolution) → `None` | Crash on race | unguarded `Popen` |
| T21 | One `RaccoonSession`, two `search()` calls → one spawn, one `initialize`, two `tools/call` ids 2 and 3 | One proxy per query | reopen per search; reuse id |
| T22 | `Budget.child(s)` never outlives the parent; an expired budget makes `search` return `None` without writing | Stages overrun the run deadline | child uses its own `now + s` only |
| T23 | `sys.platform == "win32"` → `None`, 0 spawns (O-3) | Selector on pipes raises | remove the platform guard |
| T24 | Late reply (`latereply`, event-driven): search A with budget 0.2 times out after its line is fully written; search B returns B's hits although A's reply arrives first; a third search makes 3 `tools/call` lines total | Planned search N gets query N−1's hits | accept the first reply; poison on read timeout |
| T25 | Poisoned session: after `nostdin` (partial write), `oversize` or `crash`, every later `search` returns `None` within 1 s with 0 calls to the spied `_write` and the selector not entered | Each remaining planned query waits its share on a dead child | keep writing after a partial write |
| S1 | **Static** (`ast` over the four new files): one `Popen` call site (in `memory_context.py`); no truthy `shell=`; no `os.system/popen/exec*/spawn*/posix_spawn*/fork`; no `multiprocessing`; no `"pi"` in argv position; `urllib`, `http.client`, `ssl`, `socket`, `threading` imported only by `openrouter_client.py`; no `urlopen`/`install_opener` anywhere; `build_opener` only in `openrouter_client.py`; every `ProxyHandler(` call has the literal `{}`; no `except BaseException` and no bare `except:`; no `time.sleep` in `query_pipeline.py` | A second spawn, network path, thread or guard-swallowing catch on an undriven branch | add `subprocess.run(["pi", …])`; add `urlopen`; add `except BaseException` |
| B1 | Kill switch `"0"` → 0 spawns, 0 HTTP, `resolve_project_id` never called | Switch checked after work | reorder |
| B2 | Kill-switch table `""`, `false`, `off`, `no`, `00`, `" 0"` → enabled, 1 spawn | Truthiness widens the switch | `strip().lower() in {…}` |
| B3 | Default-on table: id + executable → 1 spawn; no executable → 0; no id → 0 | Fires without ai-raccoon; accidental opt-in | skip executable check; default `"0"` |
| B4 | Project id table: from `proj/a/b` → `proj`'s id; env `" X "` → `X` and wins; blank env ignored; nested `.ai-badger/` without id → 0; blank file → 0. Sent `projectId` read from the fake log | Cross-project search | continue the walk; no strip |
| B5 | Gate skip (each reason) → `None`, 0 spawns, 0 HTTP | A spawn on every prompt | search before gate |
| B6 | Blank session → `None`, 0 spawns; control → 1 | `isError` each prompt | send `"unknown"` |
| B7 | Only droppable hits → `None` | Empty block injected | format when both empty |
| B8 | 10 000-char prompt → sent `query` equals the trimmed prompt | Silent truncation | add a cap |

### Q1: `tests/test_memory_context_openrouter.py` (11)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| O1 | No proxy: with `http_proxy`/`https_proxy`/`all_proxy` at the capture server and `no_proxy` unset, `post_json` reaches the fake; capture records 0 | Key and prompt through an env proxy | `ProxyHandler()` |
| O2 | No redirect, parametrized 301/302/303/307/308 `Location: <capture>/x` → `Reply.status == code`; capture records 0 requests (302 is the case the default handler follows as GET with `Authorization`, MEASURED by QA p5) | Key forwarded to a redirect target | default `HTTPRedirectHandler` (302 red); `add_header` instead of `add_unredirected_header` with a redirect-following mutant |
| O3 | TLS: the HTTPS handler's context has `verify_mode == CERT_REQUIRED`, `check_hostname` true, built by `ssl.create_default_context()`; both deadline handlers subclass `HTTPSHandler`/`HTTPHandler` so `build_opener` adds no default handler | Unverified TLS; a default handler bypasses the deadline | `_create_unverified_context()`; base the handler on `BaseHandler` |
| O4 | Plain-HTTP bounds table: `header-drip`, `body-drip` (1 byte / 0.05 s), `hang` with a 0.3 s share → `timeout` within 1.5 s; `live_openrouter_threads()` empty afterwards (absorbs O5) | A dripping or hung server holds the prompt past its share; watchdog thread leaks | remove the watchdog (drips red); skip the timer `join()` (thread assertion red) |
| O4b | TLS bounds (QA F5): `TlsFake` sends headers then drips the body, 0.3 s share, called with `https://127.0.0.1:<port>` and the throwaway CA trusted (via `SSL_CERT_FILE`, confirmed when written; else a `create_default_context(cafile=…)` wrapper) → `timeout` within 1.5 s; `DripTcp` dripping a TLS record header during the handshake → `timeout` within 1.5 s | The production HTTPS path is unbounded while plain-HTTP rows stay green | watchdog holds the pre-wrap socket instead of a `dup()` (body drip red); no `settimeout(remaining())` before the wrap and no dup (handshake red) |
| O6 | Expired budget → `timeout`, fake records 0 connections | A stage runs after its share | drop the pre-check |
| O7 | Oversize: 2 MiB body → `transport`; client stops reading at 1 MiB | Memory blow-up | remove the cap |
| O8 | Base URL table: unset → `https://openrouter.ai`; `http://127.0.0.1:<port>` with key `sk-test-x` accepted; the same base with key `sk-or-v1-x` → refused; `http://localhost:<p>`, `http://127.0.0.2:<p>`, `http://[::1]:<p>`, `https://127.0.0.1:<p>`, `http://user@127.0.0.1:<p>`, `http://127.0.0.1.example.com:80`, `http://127.0.0.1` (no port), `http://127.0.0.1:<p>/api` → refused. Refused: `api_base` is `None`, the planner reports `transport`, capture and fake record 0 requests, the guard records 0 refusals | A test seam that ships a real key to any listener; silent switch to production | substring `"127.0.0.1" in url`; drop the sentinel check; fall back to production on refusal (guard refusal recorded → red) |
| O9 | Key: from `env["OPENROUTER_API_KEY"]` only, stripped; blank, containing whitespace or `\n` inside, or non-printable-ASCII → `None`, 0 requests; a `.env` in cwd and `~/.openrouter` in the temp HOME are ignored; the fake sees `Authorization: Bearer <key>` and `Content-Type: application/json`; across every O-row the key is absent from stdout, stderr, `caplog`, every returned value and every exception `str` | Key read from disk; key logged; `ValueError('Invalid header value …')` carries the key | read a dotenv; accept `"a\nb"`; include the request in an error message |
| O10 | Multi-address connect (security MUST-1): patched `getaddrinfo` returns 4 `127.0.0.1` entries and a patched `connect` blocks for its socket timeout then raises `TimeoutError`; 0.4 s share → `timeout` within 0.9 s | Each address gets the full share (4× budget) | `settimeout(share)` fixed per attempt; `socket.create_connection(timeout=share)` |
| O11 | DNS deadline: patched `getaddrinfo` blocks on an event (ceiling 20 s) for host `openrouter.test`; 0.3 s share → `timeout` within 0.8 s; a second call while it is blocked → `timeout` at once and still exactly one live `ai-badger-openrouter-dns` thread; after the event is set the thread ends within 1 s; an IP-literal host starts no thread | A stalled resolver holds the stage past its share; threads pile up | resolve inline; start a thread per call |

### Q2: planner `tests/test_memory_context_planner.py` (7)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| PL1 | Goldens: `PLANNER_ADDENDUM`, `PLANNER_USER_PREFIX` and `build_user_prompt(q)` for every recorded input equal pi's bun output; system prompt is `DELEGATOR_PERSONA + "\n\n" + PLANNER_ADDENDUM` | Prompt drift | edit one char; `"\n"` separator; strip the query |
| PL2 | `DELEGATOR_PERSONA` equals `features/common/personas/delegator.md` from `# Delegator` to the end; no `name: delegator`, no `Managed by` | Persona twin drifts | edit one char |
| PL3 | `parse_plan` corpus: every recorded input → pi's `{status, reason, plan}`; never raises. Corpus: fragment-then-complete, trailing prose, unterminated, blank, bad shapes, empty concepts/queries, 300 vs 301, >6 truncation, trimming, malformed, braces in strings, 5 queries in one concept (cap 4), 121-char name. Bound rows: 1 MiB of nested `{` → `no-json-object` within 0.5 s; 64 KiB of `{"a":` nesting → returns within 1 s (MEASURE when written; if over, lower `PLAN_TEXT_MAX` to 16 KiB and record) | Parser drift; adversarial output costs seconds outside the budget | first span; strict reject; count braces in strings; `>=` at 300; remove the size cap; slice-copy `json.loads` without the `RecursionError` catch |
| PL4 | Request body passed to the injected `post`: exactly `{"model", "messages":[{"role":"system",…},{"role":"user",…}]}`, path `/api/v1/chat/completions`, no other key | Request shape drift; unapproved params | add `temperature`; swap roles |
| PL5 | Model table: override `vendor/m` → verbatim; `openrouter/vendor/m` → `vendor/m`; no `/` → `no-model`, 0 posts; unset → the `medium` preferred id of a fixture registry through a copied `model_groups.py`, prefix removed; registry whose `medium[0].id` breaks `ID_RE` → `no-model`; resolver `None` → `no-model` | Tier logic re-implemented; wrong wire id | read `groups["medium"][0]["id"]` directly; skip the prefix strip |
| PL6 | Reply table (scripted `post`): `content` string → parsed; parts list → text parts joined; missing `choices`/non-string → `empty-text`; non-JSON body → `transport`; 500, 401, 301, 302, 303, 307, 308 → `transport`; timeout value → `timeout` | Reasoning text parsed as the plan; redirect treated as success | read `reasoning`; accept any 3xx |
| PL7 | Vocabulary (absorbs R4): every planner result's reason ∈ `PLANNER_REASONS`, equal to pi's `PlannerFallbackReason` golden; every runner reason ∈ `PLANNER_REASONS ∪ RUN_REASONS`, equal to pi's list minus `aborted`; `plan` never raises across PL5–PL6 | New or unported reason strings; a raise escapes | add `"http-error"`; remove the outer `except` |

### Q2: Jev `tests/test_memory_context_jev.py` (9)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| J1 | Constants and prose equal pi's goldens (batch 12, attempts 3, attempt 15 s, state cap 32 000, excerpt cap 500, model `typesafe/jev-1.13`, path `/api/alpha/decisions`, `SCORE_QUESTION`, four `SCORE_CRITERIA`, also equal to `score_fixtures.json`) | Wire prose drift | change a criterion char; batch 13 |
| J2 | Wire goldens: bodies passed to the injected `post` equal (as parsed JSON) pi's captured bodies: `{model, state, questions:{c<i>:{type:"score", instructions:{candidate:{path, kind, excerpt}, question}, criteria}}}`; path `path ?? sourceFile ?? ""`; kind default `memory`; code-point caps | Request shape drift | `or` for path; cap 499; name by hash |
| J3 | Batching: 25 → 12/12/1 with their own names; 12 → 1; 13 → 2 | Oversized or mixed batches | batch 13; reuse names |
| J4 | Status table: 400 → `misrouted-refusal`, 401 → `auth`, 402 → `billing`, 429 → `rate-limited`, 500 → `server`, 301/302/303/307/308 → `server`, 200 error envelope → `server`, 200 truncated/non-object → `malformed`; `ERROR_KINDS`, `RETRYABLE_KINDS` equal pi's lists; `classify` never raises | Error envelope scored; vocabulary drift | treat the envelope as ok; add a kind |
| J5 | Retries: 500 then 200 → 2 posts; 500 × 4 → 3 posts; 401, 402, 400 → 1; 429 with `Retry-After: 30` twice then 200 → 3 posts and 0 calls to a monkeypatched `time.sleep` | Retry storm; retry on auth; a sleeping hook | attempts 4; retry `auth`; sleep on Retry-After |
| J6a | Deadlines on a fake clock: the injected `post` records `budget.remaining()` per attempt, each `min(15, score deadline − now)`; remaining ≤ 0 → all `None`, 0 posts; key missing → all `None`, 0 posts | Attempts ignore the stage share | 15 s regardless; send without a key |
| J7 | One failed batch (401 on batch 2 of 3) leaves batches 1 and 3 scored, batch 2 `None` | One failure nulls everything | all `None` on any failure |
| J8 | Answer tolerance: missing → `None`, never 0; wrong `type`, non-number, NaN/inf → `None`; 4.2 → 3, −1 → 0; extra fields ignored; results align with input order | Fabricated zeros | `score or 0`; skip the clamp |
| J9 | Leak: with `SYNTH_SCORE_BAD_REQUEST_BODY` (`SECRET-BODY-MARKER`) and every error fixture as real `Reply` objects, neither the marker nor the key appears in any returned value, stdout, stderr or `caplog` | Upstream error text or key surfaces | carry the body into the outcome |

### Q2: merge and runner `tests/test_memory_context_pipeline.py` (9)

Every row drives `run(...)` with fake `plan`/`search`/`score`, the real `prune_hits`, and a `Budget`
on a fake clock the fakes advance.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| MG1 | `merge_select(case)` equals pi's `mergeSelect` bun output for M1–M14, M20 | Merge drift | per-kind slots; nulls before scores; pass 2 admits new documents; unstable tie; `?` as a path |
| MG2 | `server_rank`: `3` → 3; `"2.5"` → 2.5; `"x"`, `None`, `nan`, `inf` → last; `"0x10"`, `"1_000"` → last (divergence) | Python `float` semantics leak | `float(raw)` |
| R1 | Plan once with the query verbatim; one `search` per deduplicated planned query, sequential, in plan order, never the input query; then one `score` over the pool | Input searched; order lost | also search the input; iterate a set |
| R2 | `dedupe_queries`: trimmed, blanks and duplicates dropped, a query equal to the trimmed input dropped; all dropped → fallback `invalid-shape` with one search on the input | Duplicate searches | do not seed the input; compare untrimmed |
| R3 | Runner goldens: each recorded scenario's `(status, reason, mem hashes, code hashes, queries searched)` equals pi's `runPipeline` output; the fallback keeps the original planner reason | Fallback semantics drift | report `"ok"` on fallback; search planned queries after a planner failure |
| R5 | Budget arithmetic: planner share `min(15, max(0, 90 − 15 − 8))`; each search `min(15, max(0, remaining − 8))`; loop stops once `remaining ≤ 8.5`; score `min(deadline, now + 8)`; fallback `left < 1` → empty with the planner reason, else `min(15, max(0, left − 8))`; clock passing the deadline during scoring → `budget-exhausted`, empty | Stages overrun or starve scoring | search share = 15; planner cap ignores the reserve; drop the final expiry check |
| R6 | A `None` from search N is skipped and N+1 runs; all `None` → exactly one fallback search, then `search-error` with empty lists; `run` never raises when any fake raises | One bad query cancels the rest | `break`; remove the stage `try` |
| R7 | Score raises, times out or returns all `None` → status `pipeline`, reason `ok`, merged by server rank, N planned searches, no fallback (O-6) | Planned hits thrown away | call the fallback on score failure |
| R8 | Pool: `prune_hits` per kind (a memory and a code hit sharing a hash both survive); droppables never reach a slot; sorted by `server_rank` with insertion tiebreak, then capped at 48; scores joined by hash, absent → `None` | Cap before sort; cross-kind dedupe; index-joined scores | cap before sort; prune the concatenation; join by position |

### Q3: `tests/test_memory_context_pipeline_wiring.py` (10)

Real `build()` with the fake `ai-raccoon` (`perquery`), the fake OpenRouter reached through the
injected base URL and an `sk-test-` key, a fixture project with `.ai-badger/project-id`,
`.ai-badger/model-groups.json` and `.ai-badger/skills/task/scripts/model_groups.py` copied from the
catalog.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| B9 | End to end: planner returns 3 queries, Jev scores → 1 spawn, 1 `initialize`, 3 `tools/call` (ids 2–4) with `scope:"project"`, `limit:5`; 1 planner request; ⌈pool/12⌉ Jev requests; result equals `format_block(prompt, …)` over the expected merge; the block contains no planned query, concept name or planner text (security NOTE-5) | One proxy per query; merge skipped; planner text injected | session per query; return the unmerged pool; annotate hits with `query` in the block |
| B10 | Missing key → pipeline off: 0 HTTP, exactly 1 `tools/call` with the gated prompt, `query_pipeline.run` called 0 times (spy), run budget `SINGLE_BUDGET_SECONDS` (constants patched to 0.3 s single / 30 s pipeline; `hang` fake returns within 2 s), block identical to switch-off output | Keyless users pay the 90 s path (security MUST-2) | decide the pipeline without the key |
| B11 | Switch `"0"` with a key → the same observations as B10; table `""`, `false`, `off`, `00`, `" 0"` → pipeline on; read at call time | Truthiness widens the switch; switch cached at import | `strip().lower()`; read at import |
| B12 | Planner 500 → 1 fallback search on the gated prompt; Jev 500 × 3 on every batch → no extra search, block from the planned searches by server rank | Wrong fallback trigger | swap the branches |
| B13 | Each name in `SIBLINGS` missing or raising at import (parametrized over the constant) → single-search, no raise, block present | One bad module kills memory context | unguarded sibling load |
| B14 | Stage bounds: planner `body-drip`, Jev `hang`, 3-query plan, total scaled to 3 s → returns within 4 s; proxy child reaped; `live_openrouter_threads()` empty | Stage shares add past the total | fresh budget per stage |
| B15 | Wiring proof (QA F12): planner and Jev requests arrive at the fake server through the real `post_json` with the PL4 and J2 bodies | Injected-`post` rows green, real client unwired | pass a stub `post` from `build()` |
| B16 | Declined `task` (no `<.ai-badger>/skills/task/`): planner `no-model`, 1 fallback search, 0 planner requests, on both the skill layout and a flat layout with a sibling `model_groups.py`; override set → planner runs | Claude and Hermes diverge; Hermes plans for a project that declined `task` | drop the task-dir check |
| B17 | Layout-exact resolver: flat dir without a sibling `model_groups.py`, with planted `<dir>/../task/scripts/model_groups.py` and `<dir>/task/scripts/model_groups.py` that write a marker on import → `no-model`, no marker; skill layout → loads `parents[2]/task/scripts/model_groups.py` only | Resolver loaded from a repo-controlled path | keep the rev-3 two-candidate probe |
| J6b | Real clock: score budget 0.5 s, attempt 1 against `hang`, attempt 2 `ok` → scores from attempt 2; the attempt-1 connection is closed server-side before attempt 2 is read | A late reply corrupts the next attempt | reuse the connection; no close in `finally` |

### P3a: `tests/test_memory_context_hook.py` (13)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| H1 | Claude payload (`session_id`, `hook_event_name:"UserPromptSubmit"`) + fake `hits` → exactly one JSON line `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":…}}`, exit 0; no `decision`/`prompt` keys | Envelope drift | always flat; rename key; print twice |
| H2 | The committed Copilot payload (`sessionId`, no `hook_event_name`, `cwd` replaced) → exactly one line `{"additionalContext": block}` with no `hookSpecificOutput`; the sent `sessionId` equals the payload's | Copilot drops the block (0/3 MEASURED for the envelope) | always envelope; read only `session_id` |
| H3 | `iserror` and `crash` → silent stdout, empty stderr, tmp `hook-errors.log` unchanged, fake invoked once | Expected states logged | route to `record_hook_failure` |
| H4 | `build` raises `RuntimeError` → exit 0, silent stdout, one log line, no prompt text | Invisible bugs; privacy leak | log `repr(payload)`; swallow unlogged |
| H5 | Non-JSON, JSON array, empty stdin → exit 0, silent, 0 spawns | Crash on odd hosts | `.get` on list |
| H6 | Payload `cwd` (id A) beats `CLAUDE_PROJECT_DIR` (id B); absent cwd → B | Worktree/main confusion | prefer `CLAUDE_PROJECT_DIR` |
| H7 | Subprocess `[sys.executable, hook]`, HOME tmp, PATH fake bin, no key → rc 0, block on stdout, fake invoked once | In-process green, spawned broken | import sibling by package name |
| H8 | Subprocess `hang` and `drip` with a 0.3 s budget via a module-constant patch in a wrapper → exits within 3 s, rc 0, empty stdout, fake pid gone | Hook outlives its budget; orphaned proxy | kill without reap; blocking read |
| H9 | Hook copied alone (sibling missing) → rc 0, silent | Broken sibling blocks prompts | unguarded top-level import |
| H10 | Stdout closed by the host → exit 0, no traceback | Exit 120 on BrokenPipe | remove the wrapper |
| H11 | `f: …` prompt → sent query contains `f:` alongside the prompt-markers hook on the same event | Two hooks interfere | strip markers |
| H12 | Pipeline through the real entry: subprocess from a scaffold-shaped temp tree (`.ai-badger/skills/ai-raccoon-memory/scripts/` with the four new files and `badger_store.py`, `.ai-badger/skills/task/scripts/model_groups.py`, registry), `OPENROUTER_API_KEY=sk-test-…`, the test base, the `sitecustomize` guard → 1 planner and ≥ 1 Jev request, block on stdout, key absent from stdout and stderr, no guard marker | Pipeline green in-process, inert in the scaffold layout | resolve siblings from cwd |
| W2a | `hooks.json` `timeout` for the command > `max(SINGLE_BUDGET_SECONDS, PIPELINE_TOTAL_SECONDS) + GRACE_SECONDS`; docstring cites the 30 s `UserPromptSubmit` default | Host kills the hook mid-pipeline; explicit value deleted as redundant | `"timeout": 10`; remove the key |

### P3b: `tests/test_memory_context_hermes.py` (13, plus the extended derive test)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| W1 | Real payload (`session_id`, `user_message`, `platform="cli"`) and the `message=` variant + fake → `context` contains the block; sent `sessionId` = the session | Kwarg mismatch | read only `user_message` |
| W2 | The block is the last part, followed by `(end of memory context)` | The trust header swallows the user's message | drop the terminator; insert first |
| W3 | Sibling missing → other parts returned, "missing" logged once | One feature kills all injection | early return |
| W4 | `build` raises → other parts returned, warning has the exception type and no prompt text | Prompt text in logs | `exc_info=True` |
| W6 | Project without `.ai-badger/skills/ai-raccoon-memory/` → 0 spawns; control → 1 | Declined skill still searches | remove the decline check |
| W7 | Platform table (fail closed, security MUST-3): `"cli"` → 1 spawn; absent, `None`, `""`, `"CLI"`, `"telegram"`, `"discord"`, `"gateway"`, `"subagent"` → 0 spawns, 0 HTTP | Remote chat users trigger retrieval and OpenRouter egress | default to run when the kwarg is missing; `.lower()`; a deny-list |
| W8 | `adjust()` into tmp HOME → the four modules in project `.ai-badger/hooks/` and `~/.hermes/plugins/ai-badger/`; `LEGACY_FLAT_FILES` contains them | Arm inert; pipeline absent | drop a tuple row |
| W9 | In-process `hang` through `pre_llm_inject_context` with `PIPELINE_TOTAL_SECONDS` and `SINGLE_BUDGET_SECONDS` patched to 0.5 → returns within 2 s; no child pid remains; `live_openrouter_threads()` empty | Zombie or thread in the gateway | skip `wait()` |
| W10 | Installed plugin dir (tmp HOME) runs the pipeline against the fakes; every pipeline module and `model_groups` in `sys.modules` has `__file__` under the plugin dir; with the plugin-dir `model_groups.py` deleted and planted `~/.hermes/task/scripts/model_groups.py` and `<project>/task/scripts/model_groups.py` that write a marker on import → `no-model`, no marker; a planner `body-drip` returns within its share and `live_openrouter_threads()` is empty | Hermes executes project- or HOME-controlled code; thread leak | load the resolver from the project; rev-3 probe; skip `join()` |
| M1 | Same (session, prompt) twice → 1 spawn, 1 planner request; same block both times | N pipelines per tool loop | remove memo; return `None` on hit |
| M2 | Same session, new prompt → runs again; one entry for that session | Memo too sticky; unbounded | key on session only; append |
| M3 | Failure (`crash`) memoized: second identical call spawns 0 | N × budget per loop in an outage | memoize successes only |
| M4 | `on_session_start_drift_notice`, obtained through `register()` with a fake ctx, clears the memo | Production never clears | clear in an unregistered function |
| — | Existing `SHARED_SKILL_FILES` equality (`:205-208`) and the sibling-load derive (`:400-436`), extended to require `memory_context.SIBLINGS + (RESOLVER,)` (feasibility F3) | A missing row silently turns Hermes into single-search | omit a row |

### P4: `tests/test_memory_context_integration.py` (11)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| I1 | Manifest `memory-context`: claude, copilot and hermes arms; no `pi` key. Removing an arm → `hooks_manifest_agent_gaps` red | Registered, never run | drop an arm |
| I2 | `hooks_manifest_unresolved(ROOT) == []`; deleting the `memory_context_hook.py` command → gaps for claude and copilot | New wiring unprotected | typo the script |
| I3 | `HookWiring.wire()` on the real manifest: settings `UserPromptSubmit` names it, `guarded()`, `timeout` 100 kept; script absent → "not scaffolded — skipped" | Timeout stripped; missing file wired | drop timeout in rewrite |
| I4 | `config.exclude: [ai-raccoon-memory]` → not wired for Claude or Copilot | Declined skill fires | skip `declined_skill` |
| I5 | Generated Copilot `userPromptSubmitted` ⊇ existing hooks + ours; ours has `timeoutSec` > `max(totals) + GRACE_SECONDS` (derived) | Neighbour dropped; host kills the pipeline | overwrite list; revert A1 |
| I6 | Fired in anger, Claude: the command string from the scaffolded `.claude/settings.json`, `${CLAUDE_PROJECT_DIR}` substituted, run by `sh -c` with cwd an empty temp dir, HOME tmp, PATH = fake bin (fake `ai-raccoon`, `python3` symlink, marker-writing `pi`), `sitecustomize` guard, Claude payload → envelope on stdout, no `systemMessage`, fake invoked once, `pi` marker absent. Paired run with `AI_BADGER_MEMORY_CONTEXT=0` → silent, 0 invocations | Shipped, never ran; guarded fallback masks a bad rewrite | break the path rewrite |
| I7 | Fired in anger, Copilot: the generated `bash` string from `.github/hooks/ai-badger-hooks.json`, cwd = project root, fed the committed Copilot payload → flat `{"additionalContext": …}` | Relative path, payload shape or output shape wrong | wrong `hooks_rel`; always envelope |
| I8 | pi executes nothing: no `pi` arm; `.pi/**` and the tmp-HOME pi extension dir contain none of the new files; the pi adapter's `before_agent_start` spawns only `DELIVERY_SCRIPT` and no adapter `.ts` reads a `UserPromptSubmit` key; pi's copy list lacks them; a pi-only scaffold has no `.ai-badger/hooks/memory_context.py` | A generic replay runs it under pi | add a replay loop; add a file to pi's list |
| I9 | Composed scaffold (`claude, copilot, hermes, pi`): Claude settings, Copilot hooks file and both Hermes dirs carry it | Per-adjuster green, composition broken | drop a Hermes row |
| I10 | Scaffold twice → exactly one `memory_context_hook.py` and one `user_prompt_hook.py` entry per event per agent | Double injection | break `_hook_key` |
| I11 | Fired in anger, Hermes: reset fixture, import `ai_badger_hooks` from the installed tmp-HOME plugin dir, assert `sys.modules[key].__file__` is under it, call `pre_llm_inject_context(platform="cli", …)` against the fakes → block present | Source green, installed inert | drop a `SHARED_SKILL_MODULES` row and run after W1 in one process |

**Totals:** G 4, P1 17, P2 core 23, P2 transport/build 32, Q1 11, Q2 planner 7, Q2 Jev 9, Q2 merge/runner 9,
Q3 10, P3a 13, P3b 13 (+2 existing, one extended), P4 11 = **159 rows**. From rev 3's 157: QA's cuts
remove 7 (O5, C11, T6, T11, I12, W5, R4); added 9 (A1, GP1, O4b, O10, O11, J6 split into J6a/J6b,
B15, B16, B17).

### 6.1 pi's 115 query-pipeline tests: port map

Per-file counts MEASURED (extension 9, merge 24, parity 5, planner-call 18, planner-parser 13,
runner 20, score-client 26).

| pi file (tests) | Ported to | Not ported, and why |
|---|---|---|
| `merge.test.ts` (24) | M1–M14, M20 → MG1; M21, M22 → MG2; M15 (droppables) and M18 (mem/code independent) → R8 | M16, M17, M19: dedupe is `prune_hits` itself (C21), already pinned by C15, C16, C20 |
| `parity.test.ts` (5) | mem/code independence and droppables → R8 | assignable-type (no structural typing); dedupe == pruneHits (structurally true, C21); `retrieve == toEnvelope` (no envelope string) |
| `planner-parser.test.ts` (13) | P1–P10 → PL3; P11 → PL2; P12, P13 → PL1 | — |
| `planner-call.test.ts` (18) | request shape → PL4, B15; text parts, empty-text, invalid-shape, transport, timeout → PL6; env ref split, no-slash, unresolved model → PL5; never throws → PL7 | signal forwarding; absent `find`/`complete` (replaced by PL5 resolver rows); env unset → session model (replaced by the `medium` tier); no-pi-ai-import static row |
| `runner.test.ts` (20) | R1, R2, R10 → R1; R12, R4, R7, R8, one-failed, all-failing → R3/R6; R9, R11 → R5; search limit 5 → T3 | progress UI; env clamps; external abort (`aborted` unreachable, PL7); `toEnvelope` × 2; counters (C10) |
| `score-client.test.ts` (26) | S1 → J1; S7, S12, kind parity → J4; S2, S3 → J3; S13, S13b, path fallback → J2; S4, S5, S6, S8 → J5; S9, S16, per-attempt, non-positive, S10 → J6a/J6b; S14 → J7; S11, clamp → J8; S15 → J9; pool cap 48 → R8 | usage sums (C10); warm × 2 (no session lifecycle) |
| `extension.test.ts` (9) | E4, E8 → B11; E5 (missing key) → B10 | E1–E3, E6, UI and registry smoke rows (no long-lived session in a hook) |

---

## 7. Twin lists and registries

| Registry | Change | Enforcing check |
|---|---|---|
| `features/common/hooks/hooks-manifest.json` | `memory-context` entry (P4) | `validate --all`: schema, agent gaps, `hooks_manifest_unresolved`; `test_hooks_manifest_agent_coverage.py`; `test_pi_hook_arm_coverage_contract.py` |
| `hooks.json` ↔ manifest `script` | `user_prompt_hook.py` (P1), `memory_context_hook.py` (P3a) | `hooks_manifest_unresolved`; I3, V14, V15 |
| Copilot event map | Moved to `engine/badger_lib.py` | V5 |
| Source `timeout` ↔ Copilot `timeoutSec` | Derived by the adjuster (P1) | A1, I5 |
| Budget constants ↔ Claude `timeout` ↔ Copilot `timeoutSec` | Derived comparison | W2a, I5 |
| `tooling/validate.py` `_report` list | +1 line | V12 |
| `test_every_check_can_fail.py` REGISTRY + helpers; `test_validate.py`, `test_skills_lint.py` helpers | New check; resolving `hooks.json` | V13, V16 |
| `HOOK_CAPABLE_AGENTS` | Unchanged | `test_pi_is_not_a_hook_capable_agent_today` |
| Hermes `SHARED_SKILL_MODULES` + `SHARED_SKILL_FILES` | +4 rows each | `test_hermes_plugin_install.py:205-208`; the derive test extended to read `memory_context.SIBLINGS + (RESOLVER,)`; W8, W10, I9, I11 |
| `memory_context.SIBLINGS` ↔ the loader ↔ Hermes rows | One constant read by loader and derive test | extended derive test; B13 parametrized over it |
| `LEGACY_FLAT_FILES` | Derived | W8 |
| Plugin mirror `skills/ai-raccoon-memory/scripts/` | +4 files | `sync_plugin_skills --check`, `TestRealCatalogParity` |
| `index.json`, self-scaffold outputs | Regenerated by the integrator | `index_build --check`; `scaffold_freshness_guard` |
| `VERSION` + stamped JSON | 0.178.0 in P1 | `version_sync --check`; `release_guard` |
| Changelog entry + README row | Stub P1, text P4 | `changelog_index --check`; `docs_guard` |
| `docs/adr/0031-…` + README row | Q0 | `docs_guard` |
| Block goldens ↔ pi `rag-core.ts`; pipeline goldens ↔ pi `query-pipeline/*.ts`; `score_fixtures.json` ↔ `score-fixtures.ts` | Committed with `pi_commit`, generated by bun | C10, GP1, PL1, PL3, PL7, J1, J2, J4, MG1, R3 |
| `JS_SPACE` ↔ ECMAScript whitespace | Constant; pinned through bun goldens | C10, C18 |
| `FIELD_BREAKS` ↔ O-2 ruling text | One constant used by `sanitize_field` and `one_line` | C18, C19 |
| `DELEGATOR_PERSONA` ↔ `features/common/personas/delegator.md` | Constant compared with its source | PL2 |
| Planner model | No copy: the one `model_groups.py` loaded by a layout-exact path | PL5, B16, B17, W10 |
| Prune rule; pool cap | One implementation each | R8 |
| `ENV_NAMES` ↔ SKILL.md/ADR prose ↔ test scrub | Scrub imports the constant (P2) | G2 |
| Message-bus reconciler (`test_message_bus_manifest.py:206-217`) | Becomes a subset twin of F2 | Follow-up issue, not this task |
| Prose: `SKILL.md`, `docs/skills.md`, `docs/dictionary.md`, `docs/hermes-claude-compatibility.md` | P4 | review |

## 8. VERSION and changelog

- `VERSION` 0.177.3 → 0.178.0 in P1 (minor: a new user-visible feature); `version_sync` in P1.
- `docs/changelog/0.178.0-per-prompt-memory-context.md` (stub P1, final P4) states: the hook on
  Claude, Copilot (flat output; `trustedFolders`) and Hermes (CLI sessions only); the proxy
  transport (the hook never touches the token; the proxy may start a serve); default-on when a
  project id and the `ai-raccoon` executable exist; the pipeline (planner model and override, Jev,
  merge, pi's fallback) runs only when `OPENROUTER_API_KEY` is set, and then the gated prompt, file
  paths and memory and source-code excerpts (≤ 48 × 500 chars) go to OpenRouter; the literals
  `AI_BADGER_MEMORY_CONTEXT=0` and `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0`; measured cost per mode from
  the demo, and the 90 s / 5 s caps; each enriched prompt and planned query writes a search-log row;
  the scoped parity promise; the new `validate.py` arm-resolution check; prompt-markers wired
  explicitly (Copilot `timeoutSec` 5 → 10); the Copilot adjuster now carries a hook's `timeout`;
  every renamed or rewritten test by name.
- Rebase last. Tagging is automated; fetch tags before push.

---

## 9. The query pipeline

### 9.1 Shape

```
memory_context.build()
  ├─ openrouter_client  post_json, api_key, api_base            (the only network code)
  └─ query_pipeline     plan(query, *, post, base, key, model, budget)
                        score(query, pool, *, post, base, key, budget)
                        run(query, *, plan, search, score, prune, budget, limits)
```

`memory_context.py` loads each name in `SIBLINGS` by path from `Path(__file__).resolve().parent`
under `ai_badger_memory_context__<stem>`, the pattern it uses for `badger_store`. In the Claude
scaffold the siblings sit in `.ai-badger/skills/ai-raccoon-memory/scripts/`; in both Hermes
destinations they sit flat beside `memory_context.py`. Neither sibling imports the other or
`memory_context`. Size (INFERRED): `openrouter_client.py` ~200 lines, `query_pipeline.py` ~700
(of which ~100 is the persona constant).

### 9.2 `build()` and the runner

```
build(prompt, cwd, session_id, *, env, home, budget=None, limits=None):
  kill switch "0"                              → None (no spawn, no HTTP)
  should_enrich(prompt)                        → skip → None
  project id, executable, session id           → any missing → None
  key      = openrouter_client.api_key(env)    (only if the sibling loaded)
  pipeline = env PIPELINE != "0" and key is not None and all SIBLINGS loaded
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

`plan=` is `partial(query_pipeline.plan, post=openrouter_client.post_json, base=api_base(env, key),
key=key, model=<resolved per §9.3>)`; `score=` likewise. `run()` ports `runPipeline`
(`pipeline.ts:161-392`, READ) with its arithmetic unchanged and race/abort plumbing replaced by
child budgets; each injected call must return within its child budget (the transport and the HTTP
client guarantee it); the runner re-checks `remaining()` between stages.

1. **Plan** with `budget.child(min(PLANNER, max(0, TOTAL − SEARCH − SCORE)))`. Non-`ok` or a raise
   (→ `transport`) → `fallback(reason)`.
2. **Dedupe queries**: flatten, `js_trim`, drop blanks and duplicates, seed the trimmed input. Empty →
   `fallback("invalid-shape")`.
3. **Search** sequentially: stop when `remaining() ≤ SCORE + 0.5`; share `min(SEARCH, max(0, remaining − SCORE))`;
   `None` → record, continue. Hits annotated with `kind`, `query`, `concept` (runner-internal; never
   rendered, B9).
4. **Pool**: `prune` per kind; concatenate memory then code; stable sort by `server_rank`; cap 48.
   Empty → `fallback("no-candidates")`.
5. **Score** with `budget.child(SCORE)`: one `float | None` per pool entry; any raise → all `None`;
   joined by hash.
6. **Merge**: `merge_select(pool, MERGE_SLOTS=5)`; split by kind. Run budget expired →
   `budget-exhausted`, empty. Else `("pipeline", "ok")`.
7. **Fallback(reason)**: `left < 1.0` → empty with `reason`; else one search on the input with share
   `min(SEARCH, max(0, left − SCORE))`; failure → `search-error`, empty; success → per-kind `prune`
   and `[:5]`, status `fallback`, the original `reason`.

**Score failure does not fall back** (O-6): pi turns a Jev failure into null scores merged by server
rank (`pipeline.ts:351-379`, READ). Vocabulary (pi's): planner `no-model | timeout | transport |
empty-text | no-json-object | invalid-shape`; runner `ok | no-candidates | search-error |
budget-exhausted`. `aborted` is unreachable (no external signal) and not carried. Missing key never
reaches the runner (§1.3).

### 9.3 Planner

- **Prose.** `DELEGATOR_PERSONA` (pi `planner.ts:20-115`), `PLANNER_ADDENDUM` (`:118-129`),
  `PLANNER_USER_PREFIX` (`:131-149`) verbatim; `build_user_prompt(q) = PREFIX + q + "\n>>>"`, no trim
  or escape. System prompt `DELEGATOR_PERSONA + "\n\n" + PLANNER_ADDENDUM` (`planner-call.ts:101`).
- **Parser.** `parse_plan(text)` ports `planner.ts:163-290`: if `len(text) > PLAN_TEXT_MAX` (65 536)
  → `no-json-object` without scanning (accepted divergence; a maximal valid plan is under 3 KB). Else
  brace-balanced spans with string-state tracking, tried last → first; each tried with
  `json.JSONDecoder().raw_decode(text, start)` requiring `end == span_end + 1` (no slice copy); a
  `RecursionError` or `ValueError` skips the span; the first span that parses and normalizes wins.
  Limits `CONCEPT_NAME_MAX 120`, per-concept 1–4 queries, query 1–300 chars, 2–6 total, truncation
  not rejection. Reasons `empty-text`, `no-json-object`, `invalid-shape`.
- **Model.** `AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL`: blank → unset; no `/` → `no-model`; a leading
  `openrouter/` removed; else verbatim. Unset: `model_groups.resolve(level="medium",
  groups=model_groups.load_groups(<registry>))` via §9.7, then `removeprefix("openrouter/")` (total
  because `_emit_id` guarantees `^openrouter/<vendor>/<name>$`, `model_groups.py:25,311-317`, READ).
  Resolver absent or any resolver/registry failure → `no-model`.
- **Call.** `api_base` refused → `transport`, no request. Body `{"model", "messages":[system, user]}`,
  no sampling parameters. `post` timeout → `timeout`; transport, non-200, non-JSON → `transport`.
  Text = `choices[0].message.content` if a string, else joined `text` of parts whose `type == "text"`,
  else `""`; then `parse_plan`.
- **Grounding** (Q0.3): OpenRouter chat-completions shape, UNVERIFIED until recorded.

### 9.4 Jev

Ports `jev-client.ts` (`:40-529`, READ):
- **Constants.** `BATCH_MAX 12`, `ATTEMPTS 3`, `ATTEMPT_SECONDS 15`, `STATE_CHAR_CAP 32000`,
  `EXCERPT_CHAR_CAP 500`, `MODEL "typesafe/jev-1.13"`, `DECISIONS_PATH "/api/alpha/decisions"`,
  `SCORE_QUESTION`, `SCORE_CRITERIA` (four). `ERROR_KINDS` (`misrouted-refusal`, `auth`, `billing`,
  `rate-limited`, `server`, `transport-timeout`, `malformed`, `missing-key`); `RETRYABLE_KINDS`
  (`server`, `transport-timeout`, `malformed`, `rate-limited`).
- **Builder.** `path = c.path if present else c.sourceFile if present else ""` (JS `??`, raw, not
  sanitized: it travels as JSON), `kind` default `memory`, `excerpt = (snippet or "")[:500]` (code
  points); body `{"model", "state": query[:32000], "questions": {"c<i>": …}}` per batch of 12.
- **Classifier.** 400/401/402/429 → the four named kinds; any other non-200 (3xx included) → `server`;
  200 → invalid JSON or non-object → `malformed`; `error` present and `answers` absent → `server`;
  else answers per asked name (`type == "score"`, finite number clamped to [0, 3], else `None`).
  Transport failure or timeout → `transport-timeout`.
- **Attempts.** Per batch, up to 3, no sleep, retry only on a retryable kind; each attempt gets
  `score_budget.child(ATTEMPT_SECONDS)`; `remaining() ≤ 0` skips the batch with `None`s. Batches
  sequential.
- **Not ported:** `usage` sums, `Retry-After` handling, warm-up, the tuning env vars, the second
  pool cap.

### 9.5 Network hygiene (`openrouter_client.py`)

- **Opener, one per call.** `build_opener(ProxyHandler({}), NoRedirect(),
  DeadlineHTTPSHandler(context=ssl.create_default_context(), call=c), DeadlineHTTPHandler(call=c))`.
  `DeadlineHTTPSHandler` subclasses `HTTPSHandler` and `DeadlineHTTPHandler` subclasses `HTTPHandler`,
  so `build_opener` adds no default handler that would bypass the deadline. `NoRedirect` subclasses
  `HTTPRedirectHandler` and returns `None` from `redirect_request`; a 3xx surfaces as `HTTPError`.
  `Authorization` is added with `add_unredirected_header` as a second guard. The HTTP handler exists
  only for the loopback test base; production URLs are the constant `https://openrouter.ai`.
- **Deadline across every phase** (security MUST-1, binding 2). `post_json(url, body, key, budget)`:
  `remaining() ≤ 0` → `timeout` without resolving. The connection classes override `connect()`:
  1. *Resolve.* An IP-literal host (`ipaddress.ip_address` parses) resolves inline with
     `AI_NUMERICHOST`. A host name resolves on a daemon thread named `ai-badger-openrouter-dns`,
     joined with `timeout=remaining()`; not done → `timeout`. A module dict keeps at most one live
     resolver thread per host: if one is still running, the call returns `timeout` at once without
     starting another. The thread holds no socket and writes nothing but its result slot; it ends
     when the OS resolver returns.
  2. *Connect.* For each address in order: `left = remaining()`; `left ≤ 0` → `timeout`; create the
     socket, `settimeout(left)`, `connect`; on `OSError` close it and try the next. The per-attempt
     timeout is recomputed, so all attempts together stay inside the share.
  3. *Attach.* The watchdog receives `sock.dup()`. `shutdown` acts on the connection, not the file
     descriptor, so shutting the dup ends the TLS session too, and the dup survives `wrap_socket`
     detaching the original (QA p3/p3b MEASURED: the pre-wrap socket raised `EBADF`, the dup ended
     the read at 0.51 s).
  4. *TLS.* `sock.settimeout(remaining())`, then `context.wrap_socket(sock, server_hostname=host)`.
     CPython applies the socket timeout as one deadline for the whole handshake (QA p3 MEASURED),
     and the watchdog covers it as well.
  5. *Exchange.* The watchdog is a `threading.Timer(remaining())` named `ai-badger-openrouter-watchdog`,
     armed before resolution; when it fires it calls `socket.socket.shutdown(dup, SHUT_RDWR)` inside
     `except OSError` (NOTE-1), and a socket attached after the fire is shut at once. `finally`
     cancels and joins the timer, closes the dup, the response and any `HTTPError`.
  The exchange then fails inside the stage share and is reported as `timeout`.
- **Reading.** Status, lower-cased headers, at most 1 MiB of body in chunks; more → `transport`. A
  non-2xx `HTTPError` is returned as a `Reply` (body read under the same cap). Any other exception →
  `transport`, or `timeout` if the watchdog fired or a `TimeoutError`/`socket.timeout` was raised.
  `except Exception` only.
- **Key.** `api_key(env)`: `env.get("OPENROUTER_API_KEY", "").strip()`; `None` if empty, if it
  contains whitespace, or if any character is outside printable ASCII. No file is read. The key goes
  only into the `Authorization` header; no exception message, `Reply` field or log line carries it.
- **Headers.** `Authorization: Bearer <key>` (unredirected), `Content-Type: application/json`. Body
  `json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()`.

### 9.6 Test seam: the loopback-only base URL

Unit tests pass the fake's URL as a parameter. Subprocess tests (H12) need
`AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE`. `api_base(env, key)` accepts it only when the key
starts with `sk-test-` (a real OpenRouter key never does) and the value parses as scheme `http`,
hostname exactly `127.0.0.1`, an explicit port, no userinfo, empty path. Otherwise it returns `None`
when the variable is set, and the run makes no OpenRouter request (never a silent switch to
production; O8). Named in ADR-0031 and the test support module, not in SKILL.md.

### 9.7 Reaching the model resolver

Options under derive-or-delete: (A) vendored copy of `model_groups.py` — rejected, a 360-line twin
plus a new comparator; (B) read `groups.medium[0].id` from the registry — rejected, re-implements the
resolver's rules; **(C) load the one `model_groups.py` by a layout-exact path and pass it the
project registry — chosen.**

**Mechanics of C.**
- *Task gate.* The resolver is used only when `<nearest .ai-badger>/skills/task/` exists (the
  `.ai-badger` directory the project-id walk stops at, via `badger_store._nearest_project_id_file(cwd).parent`;
  one `protected-access` suppression with that reason). Absent → planner `no-model` (unless the
  override is set), on Claude and Hermes alike (B16).
- *Resolver code, layout-exact.* `here = Path(__file__).resolve()`.
  - Skill layout — `here.parent.name == "scripts"` and `here.parents[1].name == "ai-raccoon-memory"`
    (the Claude scaffold, the catalog, the plugin mirror): only
    `(here.parents[2] / "task" / "scripts" / "model_groups.py").resolve()`, accepted only if it lies
    under `here.parents[2]`.
  - Any other layout (the flat Hermes plugin dir): only `(here.parent / "model_groups.py").resolve()`,
    accepted only if its parent is `here.parent`.
  - No other candidate. Not found → `no-model`. Loaded once per process under
    `ai_badger_memory_context__model_groups`. Both copies come from
    `features/common/skills/task/scripts/model_groups.py` through existing generators.
- *Registry data*: `<nearest .ai-badger>/model-groups.json`, delivered on every scaffold
  (`model_registry.deliver`, READ); `load_groups(path)` validates it.
- *Why Hermes never loads the project's copy*: `model_groups.py` is code; Hermes today executes only
  plugin-dir code. W10 pins every loaded module's `__file__` under the plugin dir.
- *Consequences*: the registry is project data, so a repo chooses which `openrouter/` model the
  planner calls on the user's key (R-g).

---

## 10. Risks

| # | Risk | Recommendation |
|---|---|---|
| R-a | ~10–20 s per gated prompt with a key, ~1.5 s without | Accepted; demo measures both; two switches documented. |
| R-b | With no serve running, the first search pays serve start-up | 15 s share likely covers it (INFERRED); demo measures. |
| R-c | The proxy's behaviour on SIGKILL mid-acquire | INFERRED harmless; demo checks the serve still listens. |
| R-d | `pre_llm_call` frequency contradicted in-repo | Memo correct under both; demo records the truth. |
| R-e | Goldens drift when pi changes | `pi_commit` in every golden file (GP1); regeneration manual. |
| R-f | Validator ignores `matcher` | Documented limit. |
| R-g | Planner model comes from project data; a repo can pick an expensive model billed to the user's key | Bounded by `ID_RE`, one call per prompt, 15 s share; the override pins it; ADR names it. |
| R-i | A hung OS resolver thread outlives its call | At most one per host per process; holds no socket; the call itself returns at its share (O11). |
| R-j | A user sets the test base URL | Accepted only with an `sk-test-` key, loopback, exact port (O8): a real key never reaches it. |
| R-k | A `delegator.md` edit reddens PL2 | Intended: one text, one source, PL2 is the comparator. |
| R-l (new) | Copilot may cap `timeoutSec` below the pipeline total | Q0.3 grounds it; stop condition before P4; demo measures a pipeline run under Copilot. |
| R-m (new) | Copilot repo hooks run only in `trustedFolders`; an untrusted repo looks identical to "output dropped" | SKILL.md says so; demo runs in a trusted folder (MEASURED gotcha). |
| R-n (new) | The Hermes CLI signal is second-hand (repo test docstring) | P3b.0 confirms in Hermes source; fail-closed either way (W7). |
| R-o (new) | The committed Copilot payload holds a local path (`/Users/arasz/.aib-copilot-spike/flat`) | Kept verbatim for provenance (binding); tests replace `cwd`; no secret in it (READ). |

No open owner questions. Two stop conditions return to the owner: Copilot `timeoutSec` cap below
91 (Q0.3) and no positive Hermes CLI signal in the source (P3b.0).

## 11. Review disposition, round 2

Round-1 dispositions stand as recorded in rev 3 §11 (commit `9dea8180`).

| Finding | Disposition | Where |
|---|---|---|
| SEC MUST-1 watchdog misses connect (4 addresses × share) and possibly TLS | **Folded, widened by binding 2** | §9.5 steps 1–5 cover DNS, every address, TLS; O4b, O10, O11; non-negotiable 3. The suggested "except DNS" wording is rejected (C24) |
| SEC MUST-2 keyless runs take the 90 s path | **Folded** | §1.3 pipeline decision; §9.2; B10 rewritten; C23; §12 bullet |
| SEC MUST-3 O-5 lands fail-open | **Folded** | §1.3 Hermes gates (`platform == "cli"`), P3b.0 stop condition, W7 table |
| SEC SHOULD-1 `parse_plan` CPU outside the budget | **Folded** | §9.3 `PLAN_TEXT_MAX`, `raw_decode`, `RecursionError`; PL3 bound rows; §1.5 divergence |
| SEC SHOULD-2 resolver probe layout-blind | **Folded** | §9.7 layout-exact; B17, W10 |
| SEC SHOULD-3 O-2 promise broken for rank strings and path spacing | **Folded** | `sanitize_field`, `JS_SPACE`, scoped promise (§1.5); C10 inputs, C19, C21 |
| SEC NOTE-1 timer `OSError`; FD hygiene | **Folded** | §9.5 step 5 |
| SEC NOTE-2 key header hardening; handler subclassing | **Folded** | §9.5 Key, Opener; O3, O9 |
| SEC NOTE-3 disclosure narrower than egress | **Folded** | §1.3 wording; §8; P4.3 |
| SEC NOTE-4 close R-j | **Folded** | §9.6 `sk-test-` sentinel; O8 |
| SEC NOTE-5 injection surface | **Folded** | B9 assertion; §9.2 step 3 note |
| FEAS F1 adjuster hard-codes `timeoutSec` 10 | **Folded** | P1.3, A1, I5 |
| FEAS F2 lanes cannot push per package | **Folded** | §4 intro, non-negotiable 5 |
| FEAS F3 derive test blind to pipeline siblings | **Folded** | `SIBLINGS`/`RESOLVER`, P3b derive-test extension, B13 |
| FEAS F4 four modules + second ADR | **Folded (binding 3)** | Three modules, one Q2 lane |
| FEAS F5 declined `task` differs by agent | **Folded (aligned)** | §9.7 task gate; B16; C25 |
| FEAS F6 `ENV_NAMES` added too late | **Folded** | P2 (§1.3) |
| FEAS F7 Claude `timeout` 100 accepted | **Folded** | §1.2 citation; R-h closed; W2a docstring |
| FEAS F8 Hermes fallback path outside plugin | **Folded** | §9.7 |
| FEAS F9 edit-sequence mismatch | **Moot** | Waves rewritten (§4.0, §5) |
| FEAS F10 one ADR | **Folded (binding 3)** | ADR-0031 D1 + D2 |
| QA F1 guards raise into catch-alls | **Folded** | §6 guards: refusal list, `GuardRefusal(BaseException)`, autouse teardown; G1/G4 companions; S1 forbids `except BaseException`/bare `except` |
| QA F2 O2 307 cannot go red | **Folded** | O2 over 301/302/303/307/308; PL6, J4 3xx tables |
| QA F3 no per-test ceiling | **Folded** | 20 s ceilings on every blocking fake; bounds ≤ 3 s; G3 ceiling case |
| QA F4 thread-count counts fake threads | **Folded** | Named threads, `live_openrouter_threads()`; reaped pids for proxy rows |
| QA F5 HTTPS watchdog path never exercised | **Folded** | O4b with throwaway cert; dup-socket design (§9.5 step 3) |
| QA F6 T25 red only on timing | **Folded** | `_write` spy, selector not entered, bound 1 s |
| QA F7 J5 wall-clock stands in for "never sleeps" | **Folded** | `time.sleep` spy, `Retry-After: 30` |
| QA F8 J6 fake clock on a real socket | **Folded** | J6a (fake clock, injected post) in Q2; J6b (real clock) in Q3 |
| QA F9 real waits in B11, W9 | **Folded** | Module-constant patches; stated bounds |
| QA F10 `latereply` not event-driven | **Folded** | P2.2 fake spec; T24 |
| QA F11 O5 vacuous | **Folded (cut)** | `hang` is an O4 mode |
| QA F12 PL/J through the real server | **Folded** | Injected `post` in Q2; one wiring row per module in Q3 (B15, J6b) |
| QA F13 G2's key half vacuous | **Folded** | G2 asserts 0 refusals |
| QA F14 §6.1 map errata | **Folded** | §6.1 merge and parity rows corrected |
| QA F15 nothing proves bun provenance | **Folded** | GP1 |
| QA F16 cuts O5, C11, T6, T11, I12, W5, R4 | **Folded** | §6 totals |
| QA F17 DNS egress relies on `create_connection` wrap | **Folded (re-derived)** | The client now calls `getaddrinfo` itself, so the guard also wraps `getaddrinfo` (G4) |
| QA F5 trust route `SSL_CERT_FILE` (INFERRED) | **Folded with fallback** | O4b: confirm when written, else a `cafile` wrapper |
| QA alternative: fake OpenRouter in a subprocess | **Rejected** | Named threads settle F4 at lower cost (QA's own recommendation) |

## 12. Simpler shape?

Asked before calling the design finished:
- **Three modules, one entry, one ADR** (applied). Four Hermes rows instead of six; one Q2 lane. The
  pipeline file is ~700 lines of which ~100 is a prose constant; per-concern test files keep the
  tests navigable.
- **Fold the entry into `memory_context.py`** (`if __name__ == "__main__"`). Saves one file and one
  mirror row. Rejected: the process concerns (stdin, output shape, closed stdout, error log) would
  ship into the module Hermes imports in-process, and the repo names hook entries `*_hook.py`.
- **Missing key → single-search directly** (applied, security MUST-2): one decision in `build()`
  instead of a runner detour, and a 5 s bound for the default user.
- **No resolver thread for DNS.** Simpler, but binding 2 puts DNS under the deadline and `getaddrinfo`
  cannot be interrupted any other way in the stdlib. The thread is skipped for IP literals and capped
  at one per host.
- **No watchdog.** Per-socket timeouts reset on every byte, so a drip defeats them (O4, O4b).
- **Jev failure → single search** would discard planned hits; pi's behaviour kept (O-6).
- **Cut from the pi port:** progress UI, scheduler, abort signals, `aborted`, env clamps, warm-up,
  usage sums, Retry-After, the second prune and pool cap, pi-registry rows.
- **Cut earlier and still cut:** direct HTTP to ai-raccoon, the port variable, the sitecustomize
  routing shim (today's sitecustomize is a network *guard*), expanded mode, branch B.

The five non-negotiables, again:
1. One spawn per run: `ai-raccoon`, `argv == [exe]`, no shell, never pi, never the token; every
   planned search on that one session.
2. One run budget with a child per stage; pipeline (90 s) only with a key and the switch not `"0"`,
   otherwise single-search (5 s); kill and reap on deadline or error; exit 0.
3. OpenRouter: key from env only, never logged; no proxy, no redirect, verified TLS; the deadline
   covers DNS, every connect attempt and the handshake, and the watchdog covers the rest.
4. No test reaches the real executable, the network or a real key; guard refusals are recorded and
   fail the test in teardown; every blocking fake has a 20 s ceiling.
5. Lanes commit and hand back; only the integrating session runs the closing step and pushes.

## 13. Owner rulings on rev 3 (2026-09-28, binding, carried)

| # | Ruling | Rev 4 landing |
|---|---|---|
| O-1 | RESOLVED: close stdin, then kill and reap the proxy pid only. Never the process group. | §1.1, T18, T19 |
| O-2 | Sanitise the `path` and `rank` lines: collapse control and line-separator characters (`\r \n \t \v \f`, U+0085, U+2028, U+2029). Output stays byte-identical to pi for every hit without such characters. | `FIELD_BREAKS`, `sanitize_field`; the promise scoped exactly in §1.5 (the extra conditions are U+0085 in snippets, non-scalar ranks and non-BMP truncation, which the ruling's characters do not cover) |
| O-3 | POSIX only; on Windows the hook is inert and silent. | §1.1, T23 |
| O-4 | Closed by P0 (verdict A, 2026-09-28). No branch B. | §1.4; research record addendum |
| O-5 | Hermes: CLI sessions only; gateway-originated sessions are skipped. | Fail closed on `platform == "cli"` (§1.3, W7, P3b.0) |
| O-6 | Follow pi's source: a Jev failure leaves scores null and the merge ranks by server rank; not a single-search fallback. | §9.2, R7, B12 |
| O-7 | The pipeline is on by default when `OPENROUTER_API_KEY` exists; `AI_BADGER_MEMORY_CONTEXT_PIPELINE=0` keeps everything but ai-raccoon local. SKILL.md and the changelog state what leaves the machine. | §1.3 pipeline decision (key required), B10, B11; §8, P4.3 wording |
| Budget | pi parity: total 90 s, planner 15 s, search 15 s each, Jev 8 s; Claude hook `timeout` 100. | §1.2; Copilot `timeoutSec` 100 via A1 |
