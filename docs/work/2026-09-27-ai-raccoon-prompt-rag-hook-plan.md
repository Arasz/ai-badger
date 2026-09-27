# Implementation plan: aib-ai-raccoon-prompt-rag-hook (merged)

Merged from `plan-architect.md`, `plan-delivery.md` and `plan-tests.md`, under the brief, owner feedback
F1/F2 and orchestrator rulings R1–R6. Worktree base `4d8ed33b` (main `4abf5ade` + the research record),
`VERSION` 0.177.3. Paths are repo-relative. Grades: READ (opened this session or by a proposal lane and
re-checked), MEASURED, INFERRED, UNVERIFIED.

All gate commands run from the task worktree root with the main checkout's interpreter:

```
PY=/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3
```

(local invariant `venv-python`; the path exists, READ.)

---

## 1. Design summary

**What ships.** On every user prompt that passes a port of pi's `shouldEnrich` (without the `/skill:`
rules), one direct HTTP `tools/call` of `memory_search` goes to the local ai-raccoon serve. If memory or
code hits survive pruning, a "Memory context" block that is byte-identical to pi's default-mode
`toMemoryContext` is injected as additional context. The hook runs on Claude Code and Hermes. It runs on
Copilot only if the P0 spike shows that Copilot actually consumes the output. It never runs on pi.

**Placement.** `features/common/skills/ai-raccoon-memory/scripts/` (ruling; all three lanes agreed).
The skill is `scope: default` and already owns the other ai-raccoon hooks (`memory_first_gate*_hook.py`,
`memory_grade_hook.py`). It already carries a vendored `badger_store.py` (READ, `ls`). Declining the skill
through `config.exclude` removes the Claude wiring through the existing `declined_skill` path
(`skills/welcome-ai-badger/scripts/hook_wiring.py` rewrite loop).

**Module split: two files.**

| File (new) | Contents |
|---|---|
| `memory_context.py` | *Pure section:* `CONTROL_WORDS`, `NOISE_WORDS` (35 words), `unique_long_words`, `should_enrich(prompt, min_chars=20, min_words=6) -> Decision`, `prune_hits`, `one_line`, `_js_number`, `format_block(query, mem, code)`. *Transport section:* `search(arguments, token, *, url=DEFAULT_URL, budget=BUDGET_SECONDS, opener=None)`. It uses one wall-clock deadline over connect+headers+body (chunked reads with a deadline check, or a worker thread joined on the deadline), a no-proxy opener `urllib.request.build_opener(urllib.request.ProxyHandler({}))`, a body-size cap, SSE-or-JSON parsing, and returns `None` on every failure. *Orchestration:* `build(prompt, cwd, session_id, *, env=None, home=None, search_fn=search) -> str | None`. The order is kill switch → gate → project id → token → session → search → prune → both-empty → format. |
| `memory_context_hook.py` | Claude (and, in branch A, Copilot) entry. stdin JSON (`prompt`; `session_id` or `sessionId`; `cwd`) → `build()` → exactly one line `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":block}}` or nothing. It loads `memory_context.py` by path under a distinctive `sys.modules` key (the `context_enrichment_hook.py:41-68` pattern). `guarded_main()` always exits 0 and routes only *unexpected* exceptions to `record_hook_failure` (pattern `context_enrichment_hook.py:169-199`), with the log path resolved at call time. |

Hermes gets no third file. `ai_badger_hooks.pre_llm_inject_context` loads `memory_context.py` through the
existing `_load_sibling_module` and calls `build()` in-process.

**Constants, no knobs (R3).**
- `DEFAULT_URL = "http://127.0.0.1:7721/mcp"`, `BUDGET_SECONDS = 5.0`, `LIMIT = 5`, snippet cap 300, query-echo cap 80.
- There is exactly one env switch, `AI_BADGER_MEMORY_CONTEXT`, read at call time: the literal `"0"` disables the hook, and any other value (or none) leaves it on. There is no expanded mode, no mode variable, no URL override and no min-words/min-chars/timeout variables. Tests reach thresholds and the endpoint through function parameters, never through env.

**Request (brief S1–S5, owner measurement).** Headers: `X-AiRaccoon-Token: <~/.ai-raccoon/mcp-token, stripped>`,
`Content-Type: application/json`, `Accept: application/json, text/event-stream`. Body:
`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_search","arguments":{"projectId","sessionId","query","kind":"both","scope":"project","limit":5}}}`.
There is no `initialize`. `scope:"project"` is mandatory, because the owner measured that omitting it
leaks shared-tier hits from other projects.

**Resolution rules.**
- *Project id:* sibling `badger_store.resolve_project_id(cwd)` (`features/common/hooks/badger_store.py:2105-2119`). `AI_BADGER_PROJECT_ID` wins, otherwise the nearest `.ai-badger/project-id` is used, and the walk stops at the nearest `.ai-badger/`. If nothing is found, or the resolved id is blank, the hook stays silent. `badger_store` is loaded lazily by path; if it fails to load, the hook stays silent.
- *Token:* `Path(home or Path.home()) / ".ai-raccoon" / "mcp-token"`, resolved at call time. If the file is missing, empty or unreadable, the hook stays silent and makes no request.
- *Session:* a blank session id means silence and no request (a missing `sessionId` is an `isError`, S5).
- *Query:* the trimmed prompt, sent uncapped (pi parity; the 5 s deadline bounds latency). See Q2.

**Failure visibility.** Expected states are silent on stdout and stderr and add no log line. These are
every gate skip, disabled, no project, no token, no session, connection refused, timeout, 401, 406, 500,
`isError`, JSON-RPC error, malformed body and no hits. Only an unexpected exception in the entry writes one
`hook-errors.log` line, and that line never contains prompt text.

**Timeouts.** Script budget 5 s. The Claude `hooks.json` command carries `"timeout": 10`. Copilot (branch A)
gets the generator's hardcoded `timeoutSec: 10` (`features/copilot/adjustments/adjust_hooks.py:148`, READ).
Hermes is bounded only by the transport's own total deadline. A test derives the ordering (W2) instead of
restating the literals.

### 1.1 Per-agent delivery

| Agent | Mechanism | Files |
|---|---|---|
| Claude | Manifest entry `memory-context`, claude arm `hooks-json`/`hooks.json`/`UserPromptSubmit`/`memory_context_hook.py`. `hook_wiring.py` selects the `hooks.json` command by script, rewrites `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` → `${CLAUDE_PROJECT_DIR}/.ai-badger/skills/`, wraps it in `guarded()`, keeps `timeout` (`new_h = dict(h)`), and merges with script-identity dedupe (`hook_wiring.py:114-141`, READ). | `features/common/hooks/hooks-manifest.json`, `features/common/hooks/hooks.json` |
| Copilot, branch A (spike shows injection works) | Copilot arm `hooks-json`/`userPromptSubmitted`/`memory_context_hook.py`, generated by `adjust_hooks.py` (event map `:112-119`, READ). The entry already accepts `sessionId`. | manifest only |
| Copilot, branch B (spike shows output dropped) | No arm. `HOOKS_MANIFEST_AGENT_EXEMPTIONS["memory-context"]["copilot"]` is recorded as a wall, citing the P0 transcript and the vendor doc sentence. An issue is filed, not fixed, saying the existing Copilot `userPromptSubmitted` arms (`context-enrichment`, `prompt-markers`, `message-delivery-per-turn`) likely inject nothing and that `docs/dictionary.md:22` is wrong. **Owner checkpoint** before this ships (R5). | `tooling/validate.py` |
| Hermes | Manifest arm `plugin`/`ai_badger_hooks.py`/`pre_llm_call`. `pre_llm_inject_context` (`ai_badger_hooks.py:634-729`) gains `_load_memory_context()` through `_load_sibling_module`. The block is appended **last** in its own `try/except` + `logger.warning`. Inputs: `message or user_message`, `_project_cwd(cwd)` and `kwargs["session_id"]`. **Memo (R4):** an in-process `dict[session_id] -> (sha256(prompt), result)`. The same (session, prompt) returns the cached result (block *or* `None`, including failures) without searching. A new prompt replaces the session's entry, so the memo holds one entry per session. `on_session_start` clears it. `SHARED_SKILL_MODULES += ("ai-raccoon-memory","memory_context.py")`. | `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py:35-43`, `tests/test_hermes_plugin_install.py:20-28` twin |
| pi | Nothing (R6). | none |

**Why the memo caches the result and does not skip.** If `pre_llm_call` fires on every tool-loop
continuation (`validate.py:199` says so, while `ai_badger_hooks.py:640` says "once per turn", READ; the
two conflict), a skip would drop the block from continuation calls. Returning the cached block keeps the
context and costs no search.

### 1.2 pi exclusion (R6)

It is structural, with no in-script guard and no `PI_SESSION_ID` check:
1. The manifest entry has no `pi` arm, and `HOOK_CAPABLE_AGENTS = ("claude","hermes","copilot")` (`tooling/validate.py:180`, READ).
2. pi's `before_agent_start` spawns only `DELIVERY_SCRIPT` = `message_delivery_hook.py` (`features/pi/adjustments/adapter/index.ts:68,324,729-733`). `loadGates()` reads `.ai-badger/hooks/hooks.json` for Pre/PostToolUse only.
3. pi's fixed copy list (`features/pi/adjustments/adjust_hooks.py:83-91`) excludes `memory_context.py`. pi does copy `ai_badger_hooks.py`, but it never calls `pre_llm_inject_context`, and the sibling is absent there, so the arm stays inert.

The integration test I4 goes red if any of these three changes.

### 1.3 F2: manifest arm resolution check (R1)

`tooling/validate.py` gains `hooks_manifest_unresolved(root) -> List[str]`, reported next to agent coverage
(`validate.py:650`).
- `hooks-json` arm (Claude, Copilot): the arm's `script` must be the **basename** of a command under the
  arm's own event in `features/common/hooks/<entry>`. A Copilot event is mapped to the source event
  through the map `adjust_hooks.py` uses. That map is hoisted from the local `event_map` (`:112`) to a
  module constant and imported by `validate.py` (loaded by path), never copied.
- `plugin-hooks-json` arm (Claude drift-notice): resolves against repo-root `hooks/hooks.json`, per the
  documented exception (`features/common/hooks/hooks.json:2` description, READ).
- Hermes `plugin` arm: parse the entry file with `ast` and collect every `ctx.register_hook(<str>, <Name>)`
  call (`ai_badger_hooks.py:1178-1183`, READ). The `method` resolves if it equals a registered event
  string. See conflict C3: it also resolves if it equals a registered callback name.
- An unknown arm `type` or an unreadable `entry` counts as a gap, not a crash.
- **No discovery-fallback exemption.** `prompt-markers` (`hooks-manifest.json:162-177`, READ) has no
  `hooks.json` command today (grep: only `grounded_feedback_hook.py` of that skill is present, READ), so
  P1 adds explicit `UserPromptSubmit` commands for `prompt-markers/scripts/user_prompt_hook.py`. The wirers
  keep their discovery code path, because consumer-side skills may still use it. The *framework*
  manifest must now resolve explicitly.

---

## 2. Rulings table

| Id | Ruling | Where it lands |
|---|---|---|
| Brief | Fires every prompt, gated by the `shouldEnrich` port minus `/skill:` | P2 (C1–C13) |
| Brief | pi excluded | §1.2, P6 I4 |
| Brief | One HTTP `tools/call` `memory_search`, kind both, `scope:"project"`, limit 5, token file | P3 T12–T13 |
| Brief | Accept the full wait; ~5 s script budget, hook timeout above it; any failure → nothing, exit 0 | P3 T25/T26/T30, P4 H6/H8, W2 |
| Brief | On by default when project-id + token exist; `"0"` kill switch | P3 T8–T11 |
| Brief | Stdlib-only 3.10+; tests never touch live serve or real `$HOME` | S2, I7, conftest `_home_off_limits` |
| Brief | Jev/decision-router out of scope | — |
| F1 | Direct HTTP only, no process spawned, no proxy fallback | P3 T28, P4 S1–S3, P5 W14 |
| F2 | Every manifest arm resolves; watched red on a deleted command | P1 V1–V13 |
| R1 | Script arms → same-event command; Hermes via `ast` `register_hook`; prompt-markers made explicit, no discovery exemption; dedupe proven; drift-notice exception kept | P1 |
| R2 | One wall-clock deadline per call; no-proxy opener; no spawn | P3 T25/T26/T28, P4 S1–S3 |
| R3 | No expanded mode, no tuning env vars, one switch; block byte-identical including `rank 1` | P2 C22/C35, P3 T9/T10 |
| R4 | Hermes memo per (session, prompt) | P5 M1–M5 |
| R5 | Copilot spike first; two branches; branch B is an owner checkpoint + filed issue | P0, P6 |
| R6 | pi structural; red integration test; no `PI_SESSION_ID` guard | P6 I4 |
| Loc | `features/common/skills/ai-raccoon-memory/scripts/{memory_context.py,memory_context_hook.py}` | P2–P4 |

---

## 3. Conflicts resolved

| # | Conflict | Resolution |
|---|---|---|
| C1 | Module split: architect 2 files; delivery 3 (`raccoon_search.py`); tests 3 (`memory_rag*.py`) | **2 files, `memory_context*` names** (ruling). The pure-core boundary is enforced by the `search_fn`/`opener` parameters and by test C0 (the pure functions take no env or home). A separate transport file would add a `SHARED_SKILL_MODULES` row, a test twin row, a loader and plugin copies without adding any behaviour. |
| C2 | Copilot: architect wires it (trusts `dictionary.md`); delivery exempts it (vendor docs say output is dropped); tests wire it but flag it | **R5**: P0 spike decides. Both branches are planned, and branch B needs the owner's sign-off. |
| C3 | F2 Hermes rule: R1 says the method resolves to `register_hook("<method>", …)`. The orchestrator counted 11 event-name arms. The manifest has **12 Hermes arms**: 10 event names and 2 callback names, `pre_tool_call_memory_gate` (`hooks-manifest.json:275`) and `pre_tool_call_git_internals_guard` (`:428`) (READ, grep this session). | Keep R1's `ast` approach. A method also resolves when it names the callback `ast.Name` passed as the second argument of a `register_hook` call. Both callbacks are registered (`ai_badger_hooks.py:1180-1181`, READ). Without this branch the check starts red on real data. A `def` that is never registered is still a gap (V8). **Flag to the orchestrator:** if strict first-argument-only is intended, those two manifest arms must be renamed to `pre_tool_call`, which is a manifest change outside this task. |
| C4 | Discovery fallback in F2 (tests V7 proposed keeping it; Q6) | **R1**: strict. prompt-markers gets explicit commands in P1. V7 flips to "discovery-only arm → gap". |
| C5 | `PI_SESSION_ID` guard: architect keeps it; delivery and tests cut it | **Cut** (R6). |
| C6 | Kill-switch name: `AI_BADGER_MEMORY_CONTEXT` (architect, delivery) vs `AI_BADGER_MEM_RAG` (tests) | `AI_BADGER_MEMORY_CONTEXT` (R3). |
| C7 | URL override env `AI_BADGER_MEM_RAG_URL` (tests, used for hermetic subprocess runs) | **Cut** (R3). In-process tests pass `url=`. Subprocess tests use a test-only `sitecustomize.py` on `PYTHONPATH` that redirects `socket.create_connection(("127.0.0.1", 7721))` to the fake's port. They always use a bogus token, so a failed shim hits the live serve's 401, and they assert the fake saw exactly 1 request, so a missing shim fails red. See Q1. |
| C8 | Claude hook timeout: 10 (architect) vs 8 (delivery, tests) | **10**. It matches the existing `hooks.json` values (`:46,103`) and Copilot's generated 10. W2 derives `timeout > BUDGET_SECONDS`, so the literal is not load-bearing. |
| C9 | Error visibility: architect prints one stderr line on errors; tests require expected failures to be fully silent and unexpected ones to write one `hook-errors.log` line | **Tests' rule** (H6/H7). A stderr line on every prompt while the serve is down is noise, and `conftest.py:219-260` watches the error log. |
| C10 | Telemetry (`debug_log`, delivery risk 10, tests H18) | **Cut from v1** (simpler shape). The fired-in-anger demo answers "does it run". Follow-up issue. |
| C11 | Hermes memo: delivery skips the search on repeat | **Cache and return the result** (see §1.1). |
| C12 | Where the manifest row lands: architect P3; delivery integration; tests P4 | **Integration package (P6).** `hooks_manifest_agent_gaps` needs all three agents covered at once, and the F2 check needs the `hooks.json` command to exist. P6 is the first point where both Claude and Hermes code exist and the Copilot branch is decided. The `hooks.json` command (P4) is inert until then. |
| C13 | ADR: architect proposes `docs/adr/0031-…` | **Keep** (architect gate 3: a new per-prompt network dependency across hooks). It is written in P2 before code. The next free number is 0031 (`docs/adr/` ends at 0030, READ). |
| C14 | Nested `.ai-badger/` without `project-id`: stop (badger_store) or keep walking (pi) | **Stop.** Reuse `badger_store` unchanged (tests Q1, T4). Searching a parent project's memory is the cross-project leak. |
| C15 | Test twin `SHARED_SKILL_FILES`: delivery suggests deleting it (derive-or-delete) | **Out of scope.** Add the row and let the existing equality test (`test_hermes_plugin_install.py:205-208`) enforce it. Deleting the twin is a separate refactor. |

---

## 4. Packages

One task PR, one or more commits per package. The suite is green at every package boundary. Only P6
touches `VERSION`, the changelog and the self-re-scaffold, so an intermediate package merged alone
would need its own patch bump (`release_guard`).

### P0: Copilot capability spike (no repo edit, except the research record)

- **P0.1** Throwaway dir outside the repo. Add a `.github/hooks/x.json` `userPromptSubmitted` command that prints `{"additionalContext":"The code word is PERIWINKLE"}`, then run a second time with the `hookSpecificOutput` envelope. Run `copilot -p "What is the code word in your context? Reply with the word or NONE."` with the installed CLI (`/opt/homebrew/bin/copilot` 1.0.88, MEASURED by the delivery lane). Include a control run with the hook printing a marker file, to prove the hook *ran*.
- **P0.2** Append the transcript to the research record as MEASURED, with a branch verdict of A or B.
- **Acceptance:** the hook is shown to run (the marker file exists), and the answer is either PERIWINKLE (branch A) or NONE (branch B), recorded with its grade.
- **Gate:** the transcript in `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md`. If it is **branch B, stop and hand off to the orchestrator for the owner checkpoint** before P6 commits the exemption.
- **Files:** `docs/work/2026-09-27-ai-raccoon-prompt-rag-hook-research.md`.

### P1: F2 arm-resolution check + explicit prompt-markers wiring

- **P1.1** Hoist Copilot `event_map` to a module constant `COPILOT_TO_SOURCE_EVENT` in `features/copilot/adjustments/adjust_hooks.py`. This is a pure refactor, and the existing `tests/test_adjust_hooks_copilot.py` stays green.
- **P1.2** Write `hooks_manifest_unresolved(root)` in `tooling/validate.py` (§1.3), with one `_report` line at `:650`. Write it red-first against stubs.
- **P1.3** Add `prompt-markers/scripts/user_prompt_hook.py` commands to `features/common/hooks/hooks.json` `UserPromptSubmit`. Claude selects by basename, and Copilot uses the same source event through the map. Prove the dedupe (V15/V16).
- **P1.4** Register the check in the `tests/test_every_check_can_fail.py` REGISTRY. The provocation is the deleted command.
- **Acceptance:** the real manifest resolves (`[]`). The check was watched red on a tmp copy with the `context_enrichment_hook.py` command deleted, giving exactly 2 gaps, then green. `validate --all` exits non-zero on any gap. Re-wiring a target whose `.claude/settings.json` already holds the discovery-generated prompt-markers entry leaves exactly one entry. The Copilot prompt-markers entry now carries `timeoutSec: 10`, where discovery gave 5. That behaviour change is named in the changelog.
- **Gate:** `$PY -m pytest -q tests/test_hooks_manifest_resolution.py tests/test_hooks_manifest_agent_coverage.py tests/test_every_check_can_fail.py tests/test_adjust_hooks_copilot.py tests/test_scaffold_hook_wiring.py tests/test_context_enrichment_wiring_end_to_end.py` and `$PY tooling/validate.py --all`, plus lint on the touched files.
- **Files:** `tooling/validate.py`, `features/copilot/adjustments/adjust_hooks.py`, `features/common/hooks/hooks.json`, `tests/test_hooks_manifest_resolution.py` (new), `tests/test_every_check_can_fail.py`, and possibly `tests/test_scaffold_hook_wiring.py` (a new dedupe case).

### P2: pure core + ADR

- **P2.1** Stub the module with typed stubs so the tests go red on assertions, not on `ImportError`.
- **P2.2** Implement the gate, the tokenizer, prune, `one_line`, `_js_number` and `format_block`.
- **P2.3** Write `docs/adr/0031-per-prompt-memory-context-over-ai-raccoon-http.md` (Nygard shape) and add its `docs/adr/README.md` row.
- **Acceptance:** every C row is green, and each mutation was applied by hand and seen red once. The pure functions read no env, file or socket. `format_block` equals the pi goldens byte for byte.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_core.py` and `$PY -m pylint features/common/skills/ai-raccoon-memory/scripts/memory_context.py`.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` (new), `tests/test_memory_context_core.py` (new), `docs/adr/0031-….md` (new), `docs/adr/README.md`.

### P3: transport + orchestration (`search`, `build`)

- **P3a** Write the `tests/raccoon_fake.py` helper: an in-process `ThreadingHTTPServer` on `127.0.0.1:0` with the modes `sse|json|status|hang|drip|oversize|garbage`, request recording, a release `Event` on teardown, and a dead-port helper. **It can start in parallel with P2**, because it touches no shared file.
- **P3b** Write `search()`: the total deadline, the no-proxy opener, the size cap, the SSE/JSON parse, and never raising. Write T26 (drip) **first**, against a naive `urlopen(timeout=)` implementation, and watch the watchdog fire.
- **P3c** Write `build()`: the orchestration order in §1, using the `badger_store` sibling for the project id.
- **Acceptance:** every T/B row is green. No test opens 7721 (T24 uses the injected opener). The drip server cannot hold the call past budget + 0.5 s.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_transport.py tests/test_memory_context_core.py` plus pylint on `memory_context.py`.
- **Files:** `memory_context.py` (shared with P2, so P3 runs strictly after P2), `tests/test_memory_context_transport.py` (new), `tests/raccoon_fake.py` (new).

### P4: Claude/Copilot entry script + `hooks.json` command

- **P4.1** Write `memory_context_hook.py` (stdin → `build` → envelope; `guarded_main`).
- **P4.2** Append the `UserPromptSubmit` command `python3 "${CLAUDE_PLUGIN_ROOT}/features/common/skills/ai-raccoon-memory/scripts/memory_context_hook.py"` with `"timeout": 10` to `features/common/hooks/hooks.json`. **Precondition:** confirm that no test asserts every `hooks.json` command is named by a manifest row (UNVERIFIED). If one does, move P4.2 into P6.
- **P4.3** Write the test-only `tests/raccoon_sitecustomize/sitecustomize.py` port-redirect shim (C7).
- **Acceptance:** every H and S row is green. Exit code 0 on every path. The command is inert until P6, so `validate --all` stays green.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_hook.py tests/test_context_enrichment_hook.py tests/test_hooks_manifest_resolution.py` and `$PY tooling/validate.py --all`, plus pylint on the hook.
- **Files:** `features/common/skills/ai-raccoon-memory/scripts/memory_context_hook.py` (new), `features/common/hooks/hooks.json` (shared with P1), `tests/test_memory_context_hook.py` (new), `tests/raccoon_sitecustomize/sitecustomize.py` (new).

### P5: Hermes arm + memo

- **P5.1** Add `_load_memory_context()`, and in `pre_llm_inject_context` call `build()` through the memo and append the block last inside its own `try/except`.
- **P5.2** Clear the memo in `on_session_start` (next to `reset_gate_state()`, `ai_badger_hooks.py:331-334`).
- **P5.3** Add the `SHARED_SKILL_MODULES` row and the `SHARED_SKILL_FILES` twin row. `LEGACY_FLAT_FILES` derives from them automatically.
- **P5.4** Update the `PLUGIN_YAML` description (`adjust_hooks.py:62-68`) to mention memory context.
- **Acceptance:** the M and W rows are green. The sibling-load derive test (`test_hermes_plugin_install.py:405-436`) passes. Other `pre_llm_call` parts survive every failure of the memory arm.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_hermes.py tests/test_hermes_plugin_install.py tests/test_hermes_plugin_payloads.py` plus pylint on `ai_badger_hooks.py`.
- **Files:** `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py`, `tests/test_hermes_plugin_install.py`, `tests/test_memory_context_hermes.py` (new).

### P6: Integration (last)

- **P6.1** Add the manifest entry `memory-context` with the claude arm and the hermes arm. Then either the copilot arm (**branch A**) or the `HOOKS_MANIFEST_AGENT_EXEMPTIONS` copilot wall in `tooling/validate.py` (**branch B**, only after the owner signs off). In branch B, file an issue (`gh issue create`) about the inert existing Copilot `userPromptSubmitted` arms and `docs/dictionary.md:22`.
- **P6.2** Write `tests/test_memory_context_integration.py` (the I rows, plus W1–W5, W12, W13, W15 and V14).
- **P6.3** Update the docs: the `SKILL.md` section (what it does, latency cost, kill switch, the search-log row per prompt, the Copilot status; skill `version` 0.1.0 → 0.2.0), the `docs/skills.md` ai-raccoon-memory section, `docs/dictionary.md:22,94` (a `memory-context` row, plus the Copilot wording per branch), `docs/hermes-claude-compatibility.md:11-16,31` (the `pre_llm_call` list), and the `README.md` hook row if one exists (tests lane cited `:204`; UNVERIFIED).
- **P6.4** Regenerate: `$PY tooling/sync_plugin_skills.py` (plugin mirror `skills/ai-raccoon-memory/scripts/`), `$PY tooling/index_build.py`, then re-scaffold this repo against itself. That refreshes `.ai-badger/skills/…`, `.ai-badger/hooks/*`, `.claude/settings.json` and `.github/hooks/ai-badger-hooks.json`, and it also picks up P1's explicit prompt-markers entry. Diff the result against `origin/main` so no IDE-formatter drift ships.
- **P6.5** Release: `VERSION` 0.178.0, `$PY tooling/version_sync.py`, `docs/changelog/0.178.0-per-prompt-memory-context.md`, and `$PY tooling/changelog_index.py` for the README row. Rebase last, because the README row is a conflict hotspot.
- **P6.6** Fired-in-anger demo (manual, pasted into the PR). In a live Claude session in this repo with the serve running, send one enrichable prompt and show that the block appears. Then show that `AI_BADGER_MEMORY_CONTEXT=0` removes it. Repeat once in Hermes if a Hermes session is available, otherwise record it as not demonstrated.
- **Acceptance:** a scaffolded tmp repo (`claude, copilot, hermes, pi`) has the hook wired for Claude and Hermes, and for Copilot in branch A or explicitly absent in branch B. No pi surface names `memory_context`. The wired Claude command string, when executed, prints the block against the fake. `validate --all` is green, and it goes red when the copilot arm or exemption is removed and when the `hooks.json` command is deleted. All release gates are green.
- **Gate:** `$PY -m pytest -q tests/test_memory_context_integration.py tests/test_hooks_manifest_agent_coverage.py tests/test_hooks_manifest_resolution.py tests/test_pi_hook_arm_coverage_contract.py tests/test_scaffold_hook_wiring.py tests/test_sync_plugin_skills.py tests/test_context_enrichment_wiring_end_to_end.py tests/test_adjust_hooks_copilot.py`; `$PY tooling/validate.py --all`; `$PY tooling/index_build.py --check`; `$PY tooling/sync_plugin_skills.py --check`; `$PY tooling/version_sync.py --check`; `$PY tooling/changelog_index.py --check`; `$PY gates/docs_guard.py`; `$PY gates/scaffold_freshness_guard.py`; `$PY -m pylint $(git ls-files '*.py' | grep -v '^tests/')` scoped to the touched files. CI runs the full suite on push.
- **Files:** `features/common/hooks/hooks-manifest.json`, `tooling/validate.py` (branch B), `tests/test_memory_context_integration.py` (new), `features/common/skills/ai-raccoon-memory/SKILL.md`, `docs/skills.md`, `docs/dictionary.md`, `docs/hermes-claude-compatibility.md`, `README.md` (if applicable), `skills/ai-raccoon-memory/scripts/*`, `index.json`, `.ai-badger/**`, `.claude/settings.json`, `.github/hooks/ai-badger-hooks.json`, `VERSION`, `.claude-plugin/plugin.json` + `marketplace.json` (via version_sync), `docs/changelog/0.178.0-per-prompt-memory-context.md`, `docs/changelog/README.md`, and the `docs/work/README.md` row (already present at `:144`, READ; add a row only if another `docs/work` file is committed).

---

## 5. Parallelism map

```
P0 (spike) ─────────────────────────────────────────────┐
P1 (F2 + prompt-markers) ──────► P4 (hooks.json) ───────┤
P2 (core) ──► P3b/c (transport, build) ──► P4 ──────────┼──► P6
P3a (fake server) ─┘                  └──► P5 (Hermes) ─┘
```

| Concurrent lanes | Condition |
|---|---|
| P0 ∥ P1 ∥ P2 ∥ P3a | disjoint files; each in its own worktree (`isolation: worktree`) |
| P4 ∥ P5 | both after P3; disjoint files |

| Shared file | Packages | Order |
|---|---|---|
| `features/common/hooks/hooks.json` | P1 (prompt-markers), P4 (memory_context) | P1 before P4 |
| `memory_context.py` | P2, P3 | P2 before P3 |
| `tooling/validate.py` | P1 (check), P6 (branch-B exemption) | P1 before P6 |
| `hooks-manifest.json` | P6 only | — |
| `skills/ai-raccoon-memory/scripts/`, `index.json`, `.ai-badger/**`, `.claude/settings.json`, `.github/hooks/*` | P6 only (generated) | P6 regenerates once, after everything else |
| `docs/changelog/README.md`, `VERSION` | P6 only | rebase last |

The two worktree lanes (P4, P5) do not share build output, because this is a Python repo with no `obj/`.

---

## 6. Design-tests list per package

Row format: **behaviour | failure mode | mutation → red**. IDs are carried from `plan-tests.md` (V, C, T, H,
S, W, I), and new rows are M (memo), B (build) and V15+. The default protocol applies throughout: stubs
first so red is an assertion failure, then after green the row's mutation is applied by hand and the test
must go red. Every "silent" row has a paired control and asserts **fake request count == 0**, because of
the false-green trap from `conftest.py:112-119`, where `CLAUDE_PROJECT_DIR` points at an id-less project.
Timing rows assert upper bounds only, under a watchdog thread.

### P1: `tests/test_hooks_manifest_resolution.py`

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| V1 | Real manifest resolves (`[]`). **Red first:** a tmp copy of `features/common/hooks/` + `hooks/` with the `context_enrichment_hook.py` command deleted → exactly 2 gaps (claude, copilot) | Arm that wires nothing | `return []` |
| V2 | Synthetic Claude arm whose script is under no command → 1 gap naming file, hook, agent, event, script | Silent pass | skip arms with `script` |
| V3 | Command present under a different event → gap | Wired on the wrong event | search all events |
| V4 | `not_memory_context_hook.py` does not satisfy `memory_context_hook.py` (basename equality) | Suffix false-match | `endswith` |
| V5 | Copilot `userPromptSubmitted` resolves via the hoisted `COPILOT_TO_SOURCE_EVENT` imported from the adjuster; unmapped event → gap | Twin event map | literal copy in validate.py; drop an entry |
| V6 | `plugin-hooks-json` resolves against root `hooks/hooks.json`; a `hooks-json` arm present only in the root file → gap | Exception widened | resolve both types against one file |
| V7 | **Strict (R1):** an arm resolvable only through skill discovery → gap | Discovery silently accepted | add a discovery branch |
| V8 | Hermes method = registered event string resolves; = registered callback name resolves (C3); unregistered `def` → gap; unknown name → gap | Method the plugin never registers | accept any `def` |
| V9 | `register_hook("x", f)` in a comment/string does not count (`ast`) | Commented registration passes | regex over text |
| V10 | Unknown arm `type` → gap | New type unchecked | `continue` |
| V11 | Missing/unreadable `entry` → gap, no crash | Crash hides other gaps | let `OSError` escape |
| V12 | `validate --all` exits non-zero on a gap | Detected but not failing | drop `ok &=` |
| V13 | Registered in `test_every_check_can_fail.py` with V1's provocation and an intact control | Unregistered check | omit registration |
| V15 | Claude: target whose settings already hold the discovery-generated `prompt-markers/scripts/user_prompt_hook.py` entry, re-wired from the explicit `hooks.json` command → exactly one entry (script-identity dedupe, `hook_wiring.py:114-141`) | Prompt markers inject twice | key the dedupe on literal command |
| V16 | Copilot: generated `userPromptSubmitted` has exactly one `user_prompt_hook.py` entry, `timeoutSec` 10 | Double wiring via explicit + discovery paths | run discovery even when the source command exists |

### P2: `tests/test_memory_context_core.py`

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| C0 | Pure functions take no env/home and the module's pure section imports no `urllib`/`socket` at top level beyond what `search` needs (AST check on the pure function bodies) | I/O leaks into the core | read `os.environ` in `should_enrich` |
| C1 | Long IDEA prompt → `ok`, `query == prompt.strip()`, word count right | Real prompts rejected | default `False`; drop strip |
| C2 | Each of 7 control words → `control-word` (parametrized) | Word lost | delete one word |
| C3 | `"stop"` → `control-word`, not `too-short` | Gate order | length gate first |
| C4 | `"STOP"`, `"  Stop  "` skip; `"stop! please halt the build runner now"` enriches | Substring match | `startswith` |
| C5 | `/delegations`, `/monitors` → `command` | Slash turns searched | delete command gate |
| C6 | `/delegate some long task with many words here` → `command` | Command gate after thinness | move below too-thin |
| C7 | `/skill:task …` → `command`; no `bare-skill-call` reason | pi carve-out ported | port `SKILL_PREFIX_RE` |
| C8 | `""`, `"   \n\t"` → `empty` | Whitespace searched | skip strip |
| C9 | `min_words=1`: 20 chars → ok, 19 → `too-short` | Off-by-one | `<` → `<=` |
| C10 | `prompt context injection extension filter` → `too-thin`, 5 | Thin searched | default 6 → 5 |
| C11 | 6-word probe ok at default, `too-thin` at `min_words=7` | Floor off-by-one | `<` → `<=` |
| C12 | `f: please explain …` enriches, query keeps `f:` | Marker stripped | strip marker |
| C13 | Query is the trimmed prompt (no prefix strip) | Dead `extract_query` | `re.sub` leading `/\w+:` |
| C14 | `"Stop the router Router fallback"` → `{stop, router, fallback}` | No case fold | drop `.lower()` |
| C15 | `"a an the it is on"` → 0 | Short tokens counted | `>=3` → `>=2` |
| C16 | `"fix EPIPE ENOENT SIGTERM in stdio child"` → 6 | 3-char words dropped | `> 3` |
| C17 | `"the and for are you can"` → 0 | Noise incomplete | remove `the` |
| C18 | `"use the api key for env bus"` → 5 | Signal words as noise | add `api` |
| C19 | `"wasn't isn't"` → 0; `len(NOISE_WORDS) == 35`, exact members | Dictionary drift | delete `wasn` |
| C20 | `"memory_search tool"` → `{memory_search, tool}` | Tokenizer drift | split on `[^a-z0-9]` |
| C21 | `"café résumé"` → `{caf, sum}` | Unicode `\W` diverges from JS | `re.split(r"\W+")` |
| C22 | **Golden block** `==` whole string from `rag-core.ts:412-435` | Wording drift | change one char |
| C23 | Trust header has all phrases, neither `you must fetch` nor `always fetch` | Softened/hardened wording | edit a trust line |
| C24 | Empty/empty → both placeholders; mem-only → `(no code hits)` under code heading only | Section vanishes/misplaced | single "(no hits)" |
| C25 | 7+7 → `[m5]`,`[c5]` present, `[m6]`,`[c6]` absent | Cap wrong | cap 6 |
| C26 | `sourceFile`-only hit renders sourceFile | Path fallback lost | `or "?"` only |
| C27 | Drop when path missing/`?` **and** snippet blank; keep path-only, snippet-only | Wrong drop rule | `and` → `or` |
| C28 | Duplicate hash once, first wins | Last wins | iterate reversed |
| C29 | Same snippet, different hash → once | Snippet dedupe lost | require both keys |
| C30 | 301 chars → 300 + `…`; exactly 300 not truncated | Boundary | `>` → `>=` |
| C31 | Query echo capped at 80 | Header bloat | echo 300 |
| C32 | `one_line` collapses `\n`/`\t`/runs; `"\n- code (snippets"` cannot start a line | Snippet forges structure | remove collapse |
| C33 | Prune before cap: 5 dups of A then B, C → B and C render | Slice before dedupe | slice first |
| C34 | `prune_hits` returns lists, makes no skip decision | Core coupling | return `None` on empty |
| C35 | **R3 parity:** rank `1.0` → `(rank 1)`, `0.8123` → `(rank 0.8123)`, missing → `(rank ?)`; code hit without `lineEnd` → no `:a-b` | Python `str(1.0)` = `"1.0"` | `str(rank)`; always suffix |
| C36 | Intersection golden (empty, snippet-dup, sourceFile-only, missing rank, multi-line >300, 7 per side) | Bugs where rules meet | any C26–C35 mutation |

Not ported: pi expanded-mode cases (`:149-160`, `:240-246`, `:291-302`), TUI cards and `/skill:` helpers.

### P3: `tests/test_memory_context_transport.py`

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| T1 | From `proj/a/b` the id is read from `proj/.ai-badger/project-id`, trimmed | Walk stops early | cwd only |
| T2 | `AI_BADGER_PROJECT_ID=" X "` → `X`, beats the file; blank env ignored | Override lost / blank wins | ignore env; no strip |
| T3 | No id → silent, 0 requests; control: add file → 1 request | Cross-project search | basename fallback |
| T4 | Nested `.ai-badger/` without id under a parent with one → silent (C14) | Parent's memory searched | continue walk |
| T5 | Blank `project-id` file → silent | Empty projectId sent | return `""` |
| T6 | Token path resolved at call time (set HOME after import) | Real home captured at import | hoist `Path.home()` |
| T7 | `"abc\n"` token → header `abc` | 401 from newline | drop strip |
| T8 | Token missing/empty/dir → 0 requests; control: valid → 1 | Fires without ai-raccoon | try anyway |
| T9 | `AI_BADGER_MEMORY_CONTEXT="0"` → 0 requests | Kill switch ignored | delete check |
| T10 | `""`, `"false"`, `"off"`, `"no"`, `"00"`, `" 0"` → enabled | Truthiness widens switch | `strip().lower() in {...}` |
| T11 | Unset, id + token present → exactly 1 request (default-on) | Accidental opt-in | default `"0"` |
| T12 | POST `/mcp`, 3 headers, body `==` the exact envelope incl. `kind:"both"`, `scope:"project"`, `limit:5`, `sessionId` | Cross-project leak / isError | drop `scope`; limit 8 |
| T13 | Exactly one request, no `initialize` | Doubled latency | add initialize |
| T14 | SSE `event: message\ndata: {…}` parses | Permanent silence | parse as JSON |
| T15 | `\r\n` framing and multi-`data:` join parse | Fragile framing | first `data:` only |
| T16 | Plain `application/json` reply parses | Framing change → silence | SSE-only |
| T17 | `result.isError` → `None` | Error text as memory | ignore isError |
| T18 | JSON-RPC `error` → `None` | KeyError | read `result` unguarded |
| T19 | No text part / non-JSON text → `None` | Crash | unguarded `json.loads` |
| T20 | Missing `data.results`/`data.code` → empty lists | Crash on drift | index directly |
| T21 | 401 → `None`, no raise | Exception escapes | let `HTTPError` out |
| T22 | 406, 500 → `None` | Same | same |
| T23 | Dead port → `None` < 0.5 s | Serve down stalls | retry loop |
| T24 | Default URL `http://127.0.0.1:7721/mcp` asserted through injected opener, no socket | Wrong port, silently dead | change port |
| T25 | Hang, `budget=0.3` → `None` within 2 s (watchdog) | Prompt blocks | drop timeout |
| T26 | **R2 drip:** headers then 1 byte / 0.1 s for 30 s, `budget=0.3` → returns within 2 s. **Written first against naive `urlopen(timeout=)`; watchdog must fire** | Per-op timeout only | replace total deadline with `urlopen(timeout=)` |
| T28 | **R2 proxy:** `http_proxy`/`HTTP_PROXY` → second fake; proxy gets 0, real fake 1 | Token via proxy | default `urlopen` |
| T29 | Body over cap (1 MB) → `None`, read stops | Memory blow-up | remove cap |
| T30 | Parametrized over every fake mode: `search` never raises | Fail-silent broken in general | remove outer `except` |
| B1 | `build`: gate skip (each reason, parametrized) → `None`, 0 requests (was H4) | 1.3 s on every prompt | search before gate |
| B2 | `build`: blank session → `None`, 0 requests; control H1 (was H3) | isError each prompt | send `"unknown"` |
| B3 | `build`: only droppable hits → `None` (was H5) | Empty block injected | format when both empty |
| B4 | `build`: kill switch checked before any file read or request | Switch after search | reorder |
| B5 | `build`: sent `query` == trimmed prompt for a 10 000-char prompt (Q2 pins "uncapped") (was H12) | Silent truncation drift | add a cap |

Cut from plan-tests: T27 (URL env var; R3).

### P4: `tests/test_memory_context_hook.py`

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| H1 | Payload + id + token + fake hits → exactly one JSON line, `hookEventName:"UserPromptSubmit"`, `additionalContext == format_block(...)`, exit 0 | Envelope drift | rename key; print twice |
| H2 | `sessionId` spelling accepted and sent | Copilot always silent | read only `session_id` |
| H6 | Serve down → silent, exit 0, **stderr empty**, tmp `hook-errors.log` unchanged | Expected states logged every prompt | route `URLError` to `record_hook_failure` |
| H7 | `build` raises `RuntimeError` → exit 0, silent stdout, exactly one log line, no prompt text | Invisible bugs / privacy leak | log `repr(payload)`; swallow unlogged |
| H8 | Non-JSON, JSON array, empty stdin → exit 0, silent | Crash on odd hosts | `.get` on list |
| H10 | Payload `cwd` (id A) beats `CLAUDE_PROJECT_DIR` (id B); absent cwd → B | Worktree/main confusion | prefer `CLAUDE_PROJECT_DIR` |
| H11 | `f: …` prompt → request `query` contains `f:` | Two hooks on one event interfere | strip markers |
| H13 | Subprocess `[sys.executable, hook]`, `HOME=tmp`, `PYTHONPATH=<sitecustomize shim>` → rc 0, block on stdout; fake saw 1 request | In-process green, spawned broken | import sibling by package name |
| H14 | Hook copied alone to tmp (sibling missing) → rc 0, silent | Broken sibling blocks prompt | unguarded top-level import |
| H15 | `BUDGET_SECONDS <= 5` | Budget creeps past host timeout | `= 9` |
| H16 | Only the one JSON object on stdout (happy); nothing on skip | Stray print breaks protocol | debug print |
| H17 | No `decision`/`prompt` keys in output | Hook rewrites user input | add `"prompt"` |
| W2a | `hooks.json` `timeout` for the command > `BUDGET_SECONDS` (loaded from the module) | Host kills hook mid-search | `"timeout": 4` |
| S1 | **F1 dynamic:** patch `subprocess.*`, `os.system/popen/fork/posix_spawn*/exec*/spawn*` to raise; drive happy, serve-down, no-token, 401, hang → expected output, no patched callable reached | Proxy-child fallback | add `Popen` on no-token |
| S2 | **F1 static:** `ast` scan of `memory_context.py`, `memory_context_hook.py` (and sibling `badger_store.py`): no `subprocess`/`multiprocessing` import, no spawn attribute calls | Spawn on an undriven path | `import subprocess` |
| S3 | **F1 subprocess:** `PATH` = tmp dir with fake `ai-raccoon` and `pi` that write markers; serve-down and no-token runs → no marker | Spawn via any mechanism | shell out to `ai-raccoon` |

Cut from plan-tests: H18 (telemetry, C10), and H9 (covered by T9 at the `build` level plus I2's paired run).

### P5: `tests/test_memory_context_hermes.py` (+ extended `test_hermes_plugin_install.py`)

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| W7 | Real payload shape (`session_id`, `user_message`, …) and `message=` variant + fake → `context` contains the block; request `sessionId` = `"s"` | Kwarg mismatch | read only `user_message` |
| W7b | Block is the **last** part (after the MCP tool hint) | Untrusted text interleaved | insert first |
| W8 | Sibling missing → other parts returned, "missing" logged once | One feature kills all injection | early return |
| W9 | Serve down / `build` raises → other parts returned, no raise, warning logged | Same | let exception escape |
| W10 | Gate skip → no block, 0 requests | Hermes searches every call | bypass gate |
| M1 | Same (session, prompt) twice → 1 search, **both calls return the same block** | N × 1.3 s per tool loop; or block lost on continuations | remove memo; memo returns `None` on hit |
| M2 | Same session, new prompt → search again | Memo too sticky | key on session only |
| M3 | Failure outcome (serve down) is memoized: second identical call makes 0 requests | N × 5 s timeouts per loop | memoize only successes |
| M4 | `on_session_start` clears the memo → next identical call searches | Stale result across sessions | skip clear |
| M5 | Memo holds one entry per session (two prompts → size 1 for that session) | Unbounded growth in a gateway | append instead of replace |
| W14 | **F1 on Hermes:** spawn primitives patched to raise inside the memory arm only; block present, no spawn | In-process proxy fallback | proxy in Hermes arm |
| W6 | `adjust()` into tmp HOME → `memory_context.py` in project `.ai-badger/hooks/` **and** `~/.hermes/plugins/ai-badger/` | Arm inert | drop the tuple row |
| W11 | `LEGACY_FLAT_FILES` contains `memory_context.py` (derived) | Twin list | (derived; assert membership) |
| — | Existing `SHARED_SKILL_FILES` twin equality (`:205-208`) and sibling-load derive (`:405-436`) | Row mismatch | omit either row |

### P6: `tests/test_memory_context_integration.py`

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| W1 | Manifest `memory-context`: claude + hermes arms; copilot arm (A) or exemption (B); no `pi` key | Registered, never run | drop an arm → `test_hooks_manifest_agent_coverage.py` red (provoke once) |
| W2b | (Branch A) generated Copilot `timeoutSec` > `BUDGET_SECONDS` | Host kills hook | generator timeout 4 |
| W3 | `HookWiring.wire()` on real manifest with script scaffolded → settings `UserPromptSubmit` names it, `guarded()`, `timeout` kept; control: script absent → "not scaffolded — skipped" | Timeout stripped / missing file wired | drop timeout in rewrite |
| W4 | `config.exclude: [ai-raccoon-memory]` → not wired | Declined skill fires | skip `declined_skill` |
| W5 | (A) Copilot `userPromptSubmitted` ⊇ existing hooks + `memory_context_hook.py`; (B) `.github/hooks/ai-badger-hooks.json` does not name `memory_context` | Neighbour dropped / latency tax with dropped output | overwrite list / add arm |
| W12 | `sync_plugin_skills --check` passes; `skills/ai-raccoon-memory/scripts/` holds both new files (provoke: stale copy → exit 1) | Plugin users miss it | skip sync |
| W13 | `index_build --check` passes (provoke: skip regen) | Stale index | skip regen |
| W15 | `hooks_manifest_unresolved(ROOT) == []` after P6 | New arm resolves nowhere | typo script in manifest |
| V14 | Provocation on real data: deleting the `memory_context_hook.py` command → gaps for claude (+copilot in A); renaming Hermes method to `pre_llm_calls` → gap | New hook's wiring unprotected | (the provocation) |
| V-B | (Branch B) removing the copilot exemption → `hooks_manifest_agent_gaps` reports it | Exemption unenforced | (the provocation) |
| I1 | Full scaffold via `make_scaffolder`, agents `claude, copilot, hermes, pi`: Claude settings + Hermes dirs carry it (Copilot per branch); nothing under `.pi/`, pi-owned `.ai-badger/hooks/` copies, or the tmp-HOME pi extension dir names `memory_context` | Per-adjuster green, composed scaffold broken | drop Hermes `SHARED_SKILL_MODULES` row |
| I2 | **Fired in anger, Claude:** exact command string from `.claude/settings.json`, `${CLAUDE_PROJECT_DIR}` substituted, run via `sh -c` with stdin payload, `HOME=tmp`, sitecustomize shim → block on stdout, fake saw 1 request; paired run with `AI_BADGER_MEMORY_CONTEXT=0` → silent, 0 requests | Shipped, never ran | break path rewrite in `hook_wiring` |
| I3 | (Branch A) same for the generated Copilot `bash` string | Relative path wrong | wrong `hooks_rel` |
| I4 | **pi contract (R6):** (a) no `pi` arm; (b) `features/pi/adjustments/adapter/*.ts` never names `memory_context`, and `before_agent_start` spawns only `DELIVERY_SCRIPT` (regex over `index.ts`, technique of `test_pi_hook_arm_coverage_contract.py:48-63`); (c) pi's copy list lacks `memory_context.py` | Future generic `UserPromptSubmit` replay runs it under pi | add script to adapter or pi copy list |
| I5 | Scaffold twice → exactly one `memory_context_hook.py` and one `user_prompt_hook.py` entry per event | Double injection | break `_hook_key` |
| I6 | **Fired in anger, Hermes:** import `ai_badger_hooks` from the installed tmp-HOME plugin dir, call `pre_llm_inject_context` against the fake → block present | Source green, installed inert | ship to project dir only |
| I7 | No-live-serve meta-guard: `7721` appears in new test files only in T24 and the sitecustomize shim's redirect table | A test hits the live bank | add a live `urlopen` |

**Totals:** P1 15, P2 37, P3 34, P4 17, P5 14 + 2 existing, P6 16, which comes to about 133 rows. Compared
with plan-tests' ~123, 5 rows are cut (T27, H9, H18, V7 inverted, V14 moved) and new rows are added
(V15, V16, C0, B1–B5 regrouped, M1–M5, W7b, V-B).

---

## 7. Twin lists and registries

| Registry | Change | Enforcing check |
|---|---|---|
| `features/common/hooks/hooks-manifest.json` | `memory-context` entry | `validate --all` → schema, `hooks_manifest_agent_gaps` (`:418`), **new** `hooks_manifest_unresolved`; `test_hooks_manifest_agent_coverage.py`; `test_pi_hook_arm_coverage_contract.py` |
| `features/common/hooks/hooks.json` ↔ manifest `script` | `memory_context_hook.py` command (P4); `user_prompt_hook.py` command (P1) | **new** `hooks_manifest_unresolved` (P1); W3, V15, V16 |
| Copilot event map | Hoisted to `COPILOT_TO_SOURCE_EVENT`, imported by validate, never copied | V5 |
| `tooling/validate.py` `_report` list | +1 line | V12 |
| `tests/test_every_check_can_fail.py` REGISTRY | New check registered | the meta-test's own discovery (V13) |
| `HOOK_CAPABLE_AGENTS` | Unchanged | `test_pi_is_not_a_hook_capable_agent_today` |
| `HOOKS_MANIFEST_AGENT_EXEMPTIONS` | Branch B only: `memory-context.copilot` wall | `test_hooks_manifest_agent_coverage.py` (non-trivial reason); V-B |
| Hermes `SHARED_SKILL_MODULES` + `tests/test_hermes_plugin_install.py` `SHARED_SKILL_FILES` | +1 row each | `test_hermes_plugin_install.py:205-208`, `:405-436`; W6 |
| `LEGACY_FLAT_FILES` | Derived, no edit | W11 |
| Hermes `PLUGIN_YAML` description | Mention memory context | none (review) |
| `skills/ai-raccoon-memory/scripts/` plugin mirror | +2 files | `sync_plugin_skills.py --check`; W12 |
| `index.json` | Regenerate | `index_build.py --check`; W13 |
| Self-scaffold: `.ai-badger/**`, `.claude/settings.json`, `.github/hooks/ai-badger-hooks.json` | Re-scaffold (also absorbs P1's prompt-markers change) | `gates/scaffold_freshness_guard.py` |
| `VERSION` + `.claude-plugin/plugin.json` + `marketplace.json` + stamped JSON | 0.178.0 | `version_sync.py --check`; `gates/release_guard.py` |
| `docs/changelog/0.178.0-per-prompt-memory-context.md` + README row | New entry; generated row | `changelog_index.py --check`; `gates/docs_guard.py` |
| `docs/adr/0031-…` + `docs/adr/README.md` row | New ADR | `gates/docs_guard.py` (reference resolution; whether it checks the index row is UNVERIFIED) |
| `docs/work/README.md` | Research row present (`:144`); add only if a new `docs/work` file is committed | CI-only docs-work check, so run it locally |
| `SKILL.md`, `docs/skills.md`, `docs/dictionary.md:22,94`, `docs/hermes-claude-compatibility.md`, `README.md` | Prose rows | none mechanical; review |
| `badger_store.py` vendored copies | Reused, not edited | existing byte-equality test (ADR-0024) |

## 8. VERSION and changelog

- `VERSION` 0.177.3 → **0.178.0** (minor: a new user-visible feature). Run `$PY tooling/version_sync.py` to stamp plugin.json and marketplace.json.
- `docs/changelog/0.178.0-per-prompt-memory-context.md` must state:
  - The hook exists, on which agents, and the Copilot branch outcome.
  - It is on by default when the project-id and token are present.
  - The kill switch is `AI_BADGER_MEMORY_CONTEXT=0`.
  - Measured latency is ~1.3 s per gated prompt (S2), with a 5 s cap.
  - Each enriched prompt writes one search-log row (S10).
  - The new `validate.py` arm-resolution check.
  - prompt-markers is now wired explicitly, which changes its Copilot `timeoutSec` from 5 to 10.
  - The tests renamed or rewritten, per the memory note (e.g. any `test_context_enrichment_wiring_end_to_end.py` or `test_scaffold_hook_wiring.py` edits).
- Run `$PY tooling/changelog_index.py` for the README row, and rebase it last.
- Release tagging is automated by the workflow (memory note). `release_guard` needs fetched tags before push.

## 9. Risks and open questions

| # | Risk / question | Recommendation |
|---|---|---|
| R-a | Every gated prompt costs ~1.3 s (up to 5 s) on Claude, Hermes and possibly Copilot, and the hook is on by default | Accepted by the owner. Document the cost and the kill switch in SKILL.md and the changelog. A follow-up can offer a code-only leg (~65 ms). |
| R-b | Copilot may drop `userPromptSubmitted` output (READ, vendor docs) | P0 settles it. Branch B is an owner checkpoint. The issue on the existing inert arms is filed, not fixed. |
| R-c | The F2 check's Hermes rule differs from R1's count (C3) | Accept callback names. Flag this to the orchestrator before P1 merges. |
| R-d | Making prompt-markers explicit changes a working path: Copilot `timeoutSec` 5 → 10, and the exact-list order in `test_context_enrichment_wiring_end_to_end.py:57` may shift | V15/V16 prove there is exactly one entry. Run that e2e test in P1. If only the order changes, update the assertion and name the rewritten test in the PR. |
| R-e | Pure-core mistakes surface only as a byte diff against pi (rank formatting, Unicode tokenization) | C21/C35/C36 goldens. `_js_number` for int-valued floats. |
| R-f | `urlopen(timeout=)` is per-operation, so a slow-drip peer could hold the hook | One total deadline (R2). T26 is written first and watched red against the naive version. |
| R-g | Hermes `pre_llm_call` blocks the turn serially, bounded only by the transport deadline | Total deadline plus a memo that also caches failures (M3). |
| R-h | Retrieved snippets are untrusted text in the model context | The ported trust header byte-for-byte (C23), plus `one_line` so a snippet cannot forge block structure (C32). |
| R-i | Loading the `badger_store` sibling might have import-time side effects or cost | Verify in P3 that importing `badger_store` writes nothing under a tmp HOME (add it to H6's "tmp HOME unchanged" assertion). If it does write, inline a 15-line walk that follows the same stop rule and pin it against `badger_store` with a parity test. |
| R-j | The user-global Hermes plugin dir holds the last installer's version | Resolve everything per call. A missing sibling is inert and logged once. |
| R-k | Declining `ai-raccoon-memory` does not remove the Hermes copy (`SHARED_SKILL_MODULES` is copied unconditionally, UNVERIFIED) | The kill switch is the dependable off switch. Raise an issue if confirmed. |
| Q1 | The subprocess tests need a way to reach the fake without a URL env var (R3) | **Recommend** the test-only `sitecustomize` port-redirect shim plus a bogus token. The fallback, if the owner prefers it, is a test-only env override. That would be a second env var, so it needs the owner's approval. |
| Q2 | Should the *sent* query be capped (latency grows with query length, S2)? | **No cap** in v1, for pi parity. The deadline bounds latency. B5 pins the choice so a later change is deliberate. |
| Q3 | Hermes `pre_llm_call` frequency is contradicted in-repo (`ai_badger_hooks.py:640` vs `validate.py:199`) | The memo design is correct under both readings. Record the true answer during the P6 Hermes demo if one is run. |
| Q4 | Could a test assert that every `hooks.json` command is named by a manifest row, making P4's inert command red? | P4 precondition check. If so, move P4.2 into P6. |

## 10. Simpler shape?

What was cut, and why the rest stays:
- **Expanded mode and its mode env var.** It needs a 10-call fan-out that does not fit the 5 s budget, and the model can already fetch by hash (R3).
- **All tuning env vars** (min words, min chars, timeout, URL). They are function parameters for tests only. `AI_BADGER_MEMORY_CONTEXT` is the single switch.
- **Third module** (`raccoon_search.py`). One file with parameter seams replaces it.
- **`PI_SESSION_ID` guard.** pi exclusion is structural, and I4 is the tripwire.
- **Proxy-transport fallback, `initialize` handshake, retries.** F1/R2 forbid them.
- **Telemetry** (`debug_log` terminal states). The demo covers v1, and a follow-up adds it.
- **A new project-id resolver.** The code reuses `badger_store` (unless R-i forces a small inline walk).
- **Loopback-URL validation (T27).** There is no URL input left to validate.
- **Deleting the `SHARED_SKILL_FILES` twin.** It is out of scope.
- **Fixing the existing Copilot arms.** That is a filed issue only (R5).

Could it be smaller still?
- Dropping Hermes would contradict the brief.
- Dropping the F2 check contradicts F2.
- Merging P2 and P3 into one commit is possible. They stay split so each package has a gate that can go red on its own, and so P3a can run in parallel.
- The one addition beyond the three proposals is the Hermes memo caching failures (M3). It is one dict entry, and without it a serve outage costs 5 s per tool-loop call.

## Orchestrator rulings on the synthesis questions (binding, 2026-09-27)

- **Q-R1 (12 Hermes arms, 2 callback names):** accept. A Hermes `method` resolves when it equals
  the event name (first argument) or the callback name (second argument) of a
  `ctx.register_hook(...)` call in the entry file. A name matching neither is red. Manifest arms
  are not renamed.
- **Q1 (test route to the fake server):** no `sitecustomize` shim. Add one loopback-only port
  override, `AI_BADGER_MEMORY_CONTEXT_PORT` (integer 1–65535; garbage falls back to 7721). The host
  is hard-coded `127.0.0.1`, so an override can never send the token off-machine. This amends R3's
  "exactly one switch" by this single variable. Subprocess tests set it to the fake's ephemeral
  port together with a temporary HOME holding a fake token.
- **prompt-markers side effects:** accept Copilot `timeoutSec` 5 → 10 and any reordering in
  `tests/test_context_enrichment_wiring_end_to_end.py:57`. The test is edited deliberately and
  named in the PR description as a rewritten test.
