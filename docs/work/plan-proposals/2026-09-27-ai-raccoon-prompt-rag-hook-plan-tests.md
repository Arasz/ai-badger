# Plan proposal (test-design lens): ai-raccoon prompt RAG hook

Task `aib-ai-raccoon-prompt-rag-hook`. Lens: design-tests. Every behaviour the rulings demand gets a
test row before code exists. Each row says what it pins, the failure mode it targets, the mutation
that turns it red, and how the check is watched failing first.

Read at commit `4abf5ade`. The task worktree has zero commits beyond `main` (research, Lane A intro).
Paths are repo-relative. Grades: READ (opened the file), MEASURED (ran it), INFERRED, UNVERIFIED.

**Mid-flight owner rulings folded in (binding):**
- **F1: direct HTTP only, spawn nothing.** No proxy child and no process of any kind. It is covered by the new rows S1–S3 (P3) and the Hermes variant W14.
- **F2: `validate.py` check that every manifest arm resolves.** It is a new package, **P0**, with rows V1–V14.
- **Measured by the owner: `scope: "project"` is required.** With an unknown projectId it returns zero hits; without `scope`, other projects' shared-tier hits leak in. T12 already pins `scope`. H5 now also pins the consequence: a wrong id means an empty result, which means silence.

---

## 0. Test conventions this plan builds on (READ)

| Convention | Where | What it means for this plan |
|---|---|---|
| `$HOME` redirected for the whole session, `HERMES_HOME` deleted | `tests/conftest.py:174-189` (`_home_off_limits`) | The real `~/.ai-raccoon/mcp-token` can't be read. A test that wants a token writes one under a per-test `tmp_path` HOME with `monkeypatch.setenv("HOME", ...)`. |
| cwd moved to a scratch dir with no `.ai-badger/config.json` above it | `tests/conftest.py:192-205` | A project-id walk from the cwd finds nothing unless the test builds a project. |
| `CLAUDE_PROJECT_DIR` set to a scratch project that has `config.json` and **no** `project-id` | `tests/conftest.py:112-119` | **False-green trap.** A hook that falls back to `CLAUDE_PROJECT_DIR` finds no id and stays silent, so every "stays silent" test passes whether or not the rule it names works. Mitigation: see "Paired controls" below. |
| `_test_write` refuses writes into the real checkouts and the real home | `tests/conftest.py:87-104` | All fixture files (project-id, token) go through `_test_write`. |
| Real `~/.ai-badger/hook-errors.log` is watched for suite-caused lines | `tests/conftest.py:219-260` | A hook that logs expected failures (serve down) would trip this. P3 pins that it doesn't. |
| Scripts are loaded by repo-relative path | `load_script`, `tests/conftest.py:537-560` | Unit tests load `features/common/skills/ai-raccoon-memory/scripts/*.py` this way (mutmut-compatible module names, per the fixture docstring). |
| In-process hook test: stdin monkeypatched, `main()` called, `capsys` read | `tests/test_context_enrichment_hook.py:77-79,105-117` | Template for P3's in-process tests. |
| Deployment-shape test: `subprocess.run([sys.executable, script], input=payload, env=...)` | `tests/test_message_delivery_hook.py:690-708` | Template for P3/P6 subprocess tests (vendored sibling imported by path). |
| Real manifest and real `hooks.json`, no synthetic fixture | `tests/test_context_enrichment_wiring_end_to_end.py:1-12,39-87` | Template for P4/P6 wiring tests. Its Claude assertion is an exact list (`:57`), but it scaffolds only mcp-index and prompt-markers scripts, and `hook_wiring.py` skips a script that isn't on disk (`hook_wiring.py:317-322`). So it stays green. |
| Local HTTP stub started on port 0 and driven over urllib | `tests/test_poison_embedding_stub.py:26-45` (subprocess stub) | Precedent for a hermetic HTTP peer. This plan uses an in-process `ThreadingHTTPServer` instead, because the tests must record the requests they receive. |
| Every check needs a proven failure path | `tests/test_every_check_can_fail.py:1-25` | New gates or guards added here must register a provocation there, or get a reasoned exemption. |
| pi is not a manifest arm and not hook-capable | `tests/test_pi_hook_arm_coverage_contract.py:144-175`, `tooling/validate.py:180` | Part of the pi-exclusion proof comes free. P6 adds the missing part. |

### Cross-cutting test disciplines (these apply to every package)

1. **Hermetic transport, two layers.**
   - (a) An **injected opener** (a function parameter defaulting to the module's own opener). Unit tests use it to capture the `Request` (URL, headers, body) with no socket. The default-URL check (`127.0.0.1:7721`) happens here and only here.
   - (b) A **fake local MCP server**: `tests/raccoon_fake.py`, a helper module like `tests/scaffold_helpers.py`.
     - It is an in-process `http.server.ThreadingHTTPServer(("127.0.0.1", 0))` running on a daemon thread.
     - Behaviour is scripted per test: `sse`, `json`, `status(401|406|500)`, `hang`, `drip`, `oversize`, `garbage`.
     - It records every request as `(method, path, headers, json_body)`.
     - Teardown sets a release `Event` so a `hang` handler returns, then calls `shutdown()` and `server_close()`.
     - A "dead port" helper binds port 0, reads the port and closes the socket, which gives connection-refused.
2. **The live serve is unreachable by construction.** An autouse fixture in every new test module sets `AI_BADGER_MEM_RAG_URL` to a dead-port URL. A test that forgets to set up the fake gets connection-refused, never 7721. The meta-row in P6 (I7) is a grep-based test: `7721` may appear in exactly one test, the default-URL row, and that row uses the injected opener.
3. **Paired controls against the false-green trap.** Every "stays silent" row has a sibling that uses the same fixture with the one variable flipped and does produce output. Every silence row also asserts a secondary observable: **fake-server request count == 0**, which proves the skip happened before the transport. Without the pair, a test passes because `conftest.py:112-119` left no project-id.
4. **Timing rows assert upper bounds only, with wide slack.**
   - Use a budget of 0.3 s and assert the call returns in under 2 s.
   - Each timing row runs under a watchdog thread (`join(timeout)` then `assert not t.is_alive()`), so a regression shows up as a red assertion rather than a hung suite.
5. **"Watch it fail first" protocol.**
   - Red has to be an **assertion** failure, not an `ImportError`. The first commit of each package adds the module with typed stubs (for example `should_enrich` returns `Decision(False, "empty", "", 0)`, `search` returns `None`), and the tests go red against the stubs.
   - After green, the mutation in each row's "Mutation" column is applied by hand. Run the narrowest test, see it go red, then revert. (This is the `review-tests` ruleset: never report a survivor from reasoning alone.)
   - Rows backed by an existing gate get provoked by breaking the thing the gate checks (for example, leave `skills/` stale and watch `sync_plugin_skills --check` fail).

---

## 1. Design (summary; the other two lanes go deeper)

**Placement: `features/common/skills/ai-raccoon-memory/scripts/`.**
- The skill is `scope: default` (`features/common/skills/ai-raccoon-memory/SKILL.md:1-15`) and already ships the other ai-raccoon hooks: memory-first gate and follow-through (`features/common/hooks/hooks.json:97-106,179-199`).
- `features/ai-raccoon/` is a different thing: a stack for developing AiRaccoon itself (`features/ai-raccoon/stack.json:3`). It is the wrong home.

**Module split.** The split is chosen so the test files and the parallel lanes line up.

| File | Content | Pure? |
|---|---|---|
| `memory_rag.py` | `unique_long_words`, `should_enrich`, `prune_hits`, `one_line`, `to_memory_context`, constants (`CONTROL_WORDS`, `NOISE_WORDS`) | Pure: no I/O, no env reads (mirrors `rag-core.ts:1-20`) |
| `raccoon_search.py` | `enabled(env)`, `resolve_project_id(cwd, env)`, `read_token(home)`, `search(url, token, args, budget, opener=...)` with a **total** deadline, SSE/JSON parsing | I/O |
| `memory_rag_hook.py` | stdin/stdout entry: `enrich(prompt, cwd, session_id, env) -> str or None`, `main()`, `guarded_main()` (template `context_enrichment_hook.py:118-199`) | Entry |

**Per-agent delivery.**
- **Claude** gets a `hooks-manifest.json` entry `memory-rag` whose `claude` arm is `hooks-json` / `UserPromptSubmit` / `memory_rag_hook.py`. `features/common/hooks/hooks.json` gets a `UserPromptSubmit` command with `"timeout": 8`. It is wired by `hook_wiring.py:245-330`, which keeps the `timeout` key (`new_h = dict(h)`).
- **Copilot** gets the arm `userPromptSubmitted` / `memory_rag_hook.py`, wired by `features/copilot/adjustments/adjust_hooks.py:99-150`, which hard-codes `timeoutSec: 10` at `:147`.
- **Hermes** gets the arm `plugin` / `ai_badger_hooks.py` / `pre_llm_call`:
  - Add `("ai-raccoon-memory", "memory_rag.py")` and `("ai-raccoon-memory", "raccoon_search.py")` to `SHARED_SKILL_MODULES` (`features/hermes/adjustments/adjust_hooks.py:34-42`).
  - In `pre_llm_inject_context` (`features/common/hooks/ai_badger_hooks.py:634-729`), load both through `_load_sibling_module` (`:63-99`) and append the block to `parts`.
  - This works because Hermes passes `session_id` in `kwargs` (`:665`).

**pi stays excluded structurally.** Four facts, all READ:
- The manifest gets no `pi` arm.
- `HOOK_CAPABLE_AGENTS` excludes pi (`tooling/validate.py:180`).
- pi's `before_agent_start` spawns only `DELIVERY_SCRIPT = .ai-badger/hooks/message_delivery_hook.py` (`features/pi/adjustments/adapter/index.ts:68,324`).
- pi's own copy list omits the new modules (`features/pi/adjustments/adjust_hooks.py:83-91`).

Proof is test I4 in P6. I recommend **against** an in-script `PI_SESSION_ID` guard, because a Claude session launched from inside a pi shell inherits that variable and would go silent for the wrong reason (INFERRED). See Risk R6.

**Mode.** I recommend no expanded mode and no mode env var:
- Expanded mode adds one `memory_get`/`code_get` per hit on top of a search already measured at 1.2–1.7 s (research S2).
- It adds four test rows (pi `:149-160`, `:240-246`, `:291-302`).
- The model can already fetch full content itself with the hashes the default block prints.

**Env surface** (three variables):

| Variable | Rule |
|---|---|
| `AI_BADGER_MEM_RAG` | Kill switch. Disabled only by the literal `"0"`, matching pi's `!== "0"` (research §3.1). |
| `AI_BADGER_MEM_RAG_URL` | Loopback-only override of `http://127.0.0.1:7721/mcp`. Needed for a non-default serve port, and for hermetic subprocess tests. |
| `AI_BADGER_PROJECT_ID` | Existing override (`badger_store.py:2116-2118`). |

The script budget is a module constant (5 s), not an env var.

---

## 2. Packages

All packages land as commits in **one task PR** (see `pr-per-task`), and VERSION moves once, in P5. Separate PRs would each be a release, and each would collide on the changelog README row, which the user's memory records as a known cost.

| Pkg | Scope | Depends on | Parallel with | Files it owns / shares |
|---|---|---|---|---|
| **P0** | F2: `hooks_manifest_unresolved(root)` in `tooling/validate.py`, reported next to agent coverage (`validate.py:650`), plus registration in `tests/test_every_check_can_fail.py` | — | P1, P2 | Owns `tooling/validate.py` (new function + one `_report` line), `tests/test_hooks_manifest_resolution.py`; touches the `test_every_check_can_fail.py` REGISTRY. Lands **first**, so P4's new manifest entry is checked by it. |
| **P1** | Port core: `memory_rag.py` | — | P0, P2 | Owns `memory_rag.py`, `tests/test_memory_rag_core.py`; adds `skills/ai-raccoon-memory/scripts/memory_rag.py` via `sync_plugin_skills` |
| **P2** | Transport + detection: `raccoon_search.py`, `tests/raccoon_fake.py` | — | P1 | Owns `raccoon_search.py`, `tests/test_raccoon_search.py`, `tests/raccoon_fake.py`; plugin copy |
| **P3** | Hook entry + orchestration: `memory_rag_hook.py` | P1, P2 | — | Owns `memory_rag_hook.py`, `tests/test_memory_rag_hook.py` |
| **P4** | Delivery wiring (Claude, Copilot, Hermes) | P3 | P5-docs | **Shared:** `features/common/hooks/hooks-manifest.json`, `features/common/hooks/hooks.json`, `features/hermes/adjustments/adjust_hooks.py`, `features/common/hooks/ai_badger_hooks.py`; tests `tests/test_memory_rag_wiring.py` |
| **P5** | Docs + release | P4 (for VERSION only) | P4 (doc rows) | `docs/skills.md`, `docs/hermes-claude-compatibility.md`, `docs/dictionary.md`, `README.md`, `features/common/skills/ai-raccoon-memory/SKILL.md`, `VERSION`, `docs/changelog/0.178.0-*.md`, `docs/changelog/README.md`, `docs/work/README.md` |
| **P6** | **Integration** (last) | all | — | `tests/test_memory_rag_integration.py`; re-scaffold of the repo against itself (`.ai-badger/`, `.claude/settings.json`) |

Parallel lanes P1 and P2 each get their own worktree (`isolation: worktree`). They touch disjoint files. Each runs `tooling/sync_plugin_skills.py`, which writes only its own file under `skills/ai-raccoon-memory/scripts/`.

### Acceptance criteria and gates per package

| Pkg | Acceptance criteria | Gate (command) |
|---|---|---|
| P0 | Every arm of the real manifest resolves. The check was seen **red on a deleted command** (a tmp copy of the real `hooks.json` with the `memory_rag_hook.py` command, or today's `context_enrichment_hook.py` command, removed) before going green. It is registered with a provocation in `test_every_check_can_fail.py`. | `.venv/bin/python3 -m pytest -q tests/test_hooks_manifest_resolution.py tests/test_hooks_manifest_agent_coverage.py tests/test_every_check_can_fail.py`; `python3 tooling/validate.py` (the flag that runs `_report` at `:650`) |
| P1 | Every P1 row is green, and each mutation was applied and seen red once. The module imports nothing outside the stdlib and reads no env or file. | `.venv/bin/python3 -m pytest -q tests/test_memory_rag_core.py` and `.venv/bin/python3 -m pylint features/common/skills/ai-raccoon-memory/scripts/memory_rag.py` |
| P2 | Every P2 row is green. No test opens a socket to 7721. The total deadline holds against a drip server. | `pytest -q tests/test_raccoon_search.py` + pylint on the file |
| P3 | Every P3 row is green. Exit code is 0 on every path. `hook-errors.log` gets a line only for an unexpected exception. | `pytest -q tests/test_memory_rag_hook.py tests/test_context_enrichment_hook.py` (a neighbour on the same event) |
| P4 | Manifest, hooks.json and Hermes arm wired. The timeout ordering is derived, not typed as a literal. Existing contract tests stay green. | `pytest -q tests/test_memory_rag_wiring.py tests/test_hooks_manifest_agent_coverage.py tests/test_pi_hook_arm_coverage_contract.py tests/test_context_enrichment_wiring_end_to_end.py tests/test_scaffold_hook_wiring.py tests/test_hermes_plugin_install.py tests/test_adjust_hooks_copilot.py`; `python3 tooling/sync_plugin_skills.py --check`; `python3 tooling/index_build.py --check` |
| P5 | Doc rows present, VERSION bumped to 0.178.0 (minor, new feature), changelog entry plus index row | `python3 tooling/version_sync.py --check`; `python3 tooling/changelog_index.py --check` (`.lefthook/pre-push/verify.sh:232,273`) |
| P6 | A scaffolded temp repo gets the hook wired for Claude, Copilot and Hermes, and not for pi. The **wired command strings actually run** against the fake server and print the block. | `pytest -q tests/test_memory_rag_integration.py` plus the P4 gate list; the pre-push gate runs the full suite |

---

## 3. Test lists (design-tests shape)

Row format is **behaviour | failure mode targeted | mutation that turns it red**. "Watch fail first" appears only where it differs from the default protocol in §0.5. The pi source is `pi-badger-integration/tests/mem-based-rag/rag-core.test.ts` (READ, line numbers from `grep -n "test("`). The pi suite has 43 tests (research §2.1, MEASURED there). Rows marked **[pi :N]** re-express that case. Everything else is new to the port.

### P0: manifest arm resolution (F2) (`tests/test_hooks_manifest_resolution.py`), 14 rows

**What today's manifest actually looks like** (MEASURED, a read-only probe over the 51 arms at `4abf5ade`):
- Claude has 24 `hooks-json` arms and 1 `plugin-hooks-json` arm (drift-notice). Copilot has 14 `hooks-json` arms. Hermes has 12 `plugin` arms, all on `ai_badger_hooks.py`.
- The literal rule from F2 would start **red on pre-existing data** in two places:
  1. **`prompt-markers` (Claude and Copilot):** `user_prompt_hook.py` has no command in `features/common/hooks/hooks.json`. Both wirers find it through the skill-discovery fallback, `features/common/skills/<hook-name>/scripts/<script>` (`hook_wiring.py:262-293`, `features/copilot/adjustments/adjust_hooks.py:153-177`). The file exists.
  2. **Hermes `method`:** 11 of the 12 values are Hermes **event names** (`pre_llm_call`, `post_tool_call`, `on_session_start`, `on_session_end`), not Python `def` names. Only `pre_tool_call_memory_gate` is a `def`. All of them resolve through `register()` (`ai_badger_hooks.py:1178-1183`): `ctx.register_hook("<event>", <callback>)`.
- The rule that is both correct and green today:
  - A script resolves through a same-event command in the right `hooks.json`, **or** through the discovery path.
  - A Hermes method resolves when it names a `register_hook` event **or** a registered callback.
  - Q6 asks the owner whether to keep the discovery branch or make prompt-markers explicit instead.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| V1 | **Real manifest resolves**: `hooks_manifest_unresolved(ROOT) == []`. **Watch fail first (owner-required):** copy the real `features/common/hooks/` and `hooks/` into `tmp_path`, delete the `context_enrichment_hook.py` command from the copy's `UserPromptSubmit`, and see exactly two gaps (claude and copilot arms of `context-enrichment`). Restore it and see green. | A manifest arm that wires nothing, which the agent-coverage check (`validate.py:418-449`) can't see | Make the function `return []` |
| V2 | A synthetic Claude `hooks-json` arm whose script appears under no command → one gap message that names the manifest file, hook, agent, event and script | Silent pass | Skip arms with a `script` |
| V3 | The script's command exists, but under a **different event** (e.g. `PostToolUse`) → gap | Wired on the wrong event, so it never fires | Search every event instead of the arm's own |
| V4 | Command `.../not_memory_rag_hook.py` does **not** satisfy script `memory_rag_hook.py`; the match is on basename equality | False resolution through the suffix match the wirers use (`adjust_hooks.py:127` `endswith`) | Use `endswith(script)` |
| V5 | A Copilot arm with `userPromptSubmitted` resolves against `UserPromptSubmit` through **the same map the Copilot wirer uses**, hoisted from the local `event_map` (`adjust_hooks.py:112-118`) to a module constant and imported. An unmapped Copilot event → gap. | A twin event map drifts from the wirer's | Copy the map as a literal in `validate.py`; drop an entry |
| V6 | A `plugin-hooks-json` arm resolves against **repo-root `hooks/hooks.json`** (the documented drift-notice exception, `features/common/hooks/hooks.json:2` description). A `hooks-json` arm whose command exists only in the root file → gap. | Exception honoured by accident or widened | Resolve both types against one file (drift-notice goes red on the real manifest) |
| V7 | Discovery fallback: script absent from `hooks.json` but present at `features/common/skills/<hook name>/scripts/<script>` → resolves (prompt-markers). Absent from both → gap. *If Q6 goes strict, this row flips to a gap and P0 adds prompt-markers commands to `hooks.json`.* | prompt-markers flagged falsely, or a missing discovery script passes | Drop the fallback (real manifest red); accept any file under `skills/` |
| V8 | A Hermes method equal to a `register_hook` **event** (`pre_llm_call`) resolves, and so does a method equal to a registered **callback** (`pre_tool_call_memory_gate`). A `def` that exists but is never registered → gap. A name that is neither → gap. | A method the plugin never registers | Accept any `def` name |
| V9 | `register()` is parsed with `ast`, so a `register_hook("x", f)` inside a comment or string doesn't count → gap | Commented-out registration passes | Regex over the source text |
| V10 | An arm with an unknown `type` → gap ("checking nothing and finding nothing are not the same answer", `validate.py:425-427`) | A new arm type silently unchecked | `continue` on unknown types |
| V11 | A missing or unreadable `entry` file → gap, not a crash | Crash hides every other gap | Let `OSError` propagate |
| V12 | `validate.py`'s entry point reports it next to agent coverage and **exits non-zero** on a gap (pattern `test_hooks_manifest_agent_coverage.py:84`) | Detected but not failing (the 0.35.3 `release_guard` shape, `test_every_check_can_fail.py:8-9`) | Drop the `ok &=` |
| V13 | Registered in `test_every_check_can_fail.py` REGISTRY: the provocation is V1's deleted command, and the clean control is the same copy intact | Unregistered check fails that module's discovery | (Existing meta-gate; provoke by omitting the registration) |
| V14 | **New arm covered:** after P4, deleting `memory_rag_hook.py` from `hooks.json` makes P0 report `memory-rag` for claude and copilot, and renaming the Hermes arm's method to `pre_llm_calls` reports it for hermes | The new hook's own wiring is unprotected | (Provocation on the real P4 data, run once in P4) |

### P1: port core (`tests/test_memory_rag_core.py`), 36 rows

**Gate: `should_enrich`.** The ported order is empty → control-word → command → too-short → too-thin → ok (research §5.3).

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| C1 | A long IDEA-shaped prompt gives `enrich=True, reason="ok"`, `query == prompt.strip()`, and the right `unique_words` [pi :23] | Gate rejects real prompts | Default `enrich=False`; drop `.strip()` |
| C2 | Each of the 7 `CONTROL_WORDS` (`stop, continue, exit, quit, clear, help, ping`) gives `control-word`. Parametrized, one case per word. [pi :32; `ping` is in `rag-core.ts:54-62` but not in the pi test] | A word lost in porting | Delete any one word from the set |
| C3 | `"stop"` reports `control-word`, **not** `too-short` (4 chars). This is the port's ordering pin and replaces pi's bare-skill pin at :47. | Gate order reshuffled | Move the length gate above the control-word gate |
| C4 | Control words match exactly and case-insensitively: `"STOP"` and `"  Stop  "` skip, while `"stop! please halt the build runner now"` and `"STOP now please continue the migration work"` enrich [pi :202] | Substring or token matching | Swap `==` for `startswith` or `in words` |
| C5 | `"/delegations"` and `"/monitors"` give `command` [pi :38] | Slash turns reach the bank | Delete the command gate |
| C6 | `"/delegate some long task with many words here"` gives `command`. It clears both length and thinness, so only the command gate stops it. Also `"/compact foo"` and `"/rag status"` [pi :163] | The command gate runs after the length gates and is never reached for long slash turns | Move the command gate below too-thin |
| C7 | **Port divergence:** `"/skill:task"` and `"/skill:task extend the delegation timeout because CI runners are slow"` both give `command`, and `"bare-skill-call"` is not in the reason set [pi :47, :54, :175 inverted] | The skill carve-out gets ported by accident (research S6) | Port `SKILL_PREFIX_RE` exclusion into the command gate |
| C8 | `""` and `"   \n\t"` give `empty` [pi :74] | Whitespace prompt searched | Skip `.strip()` before the empty check |
| C9 | Boundary for too-short, with `min_words=1`: a 20-char query → `ok`, a 19-char query → `too-short` | Off-by-one | `<` → `<=` |
| C10 | `"prompt context injection extension filter"` gives `too-thin` with `unique_words == 5` [pi :60] | Thin prompts searched | Default `min_words` 6 → 5 |
| C11 | A 6-unique-word probe enriches at the default and gives `too-thin` at `min_words=7` [pi :68, :191] | Off-by-one at the floor | `<` → `<=` in the thinness gate |
| C12 | `"f: please explain why the delegation router drops fallback models"` enriches, and the query still contains `"f:"` [pi :218] | Marker stripped, so the query diverges from what the user typed | Strip a leading marker |
| C13 | The query is the trimmed prompt, identity otherwise. There is no prefix strip. [pi :86] | A dead `extract_query` strips text | Add a `re.sub` of any leading `/\w+:` |

**`unique_long_words`**

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| C14 | `"Stop the router Router fallback"` → `{stop, router, fallback}` [pi :96] | Case not folded | Drop `.lower()` |
| C15 | `"a an the it is on"` → size 0 [pi :98] | Short tokens counted | `>= 3` → `>= 2` |
| C16 | `"fix EPIPE ENOENT SIGTERM in stdio child"` → 6. Three-letter signal words count. [pi :101] | Short content words dropped | `>= 3` → `> 3` |
| C17 | `"the and for are you can"` → 0 [pi :104] | Noise set incomplete | Remove `"the"` |
| C18 | `"use the api key for env bus"` → 5 [pi :105] | Short signal words treated as noise | Add `"api"` to the noise set |
| C19 | `"wasn't isn't"` → 0. The contraction stubs `wasn`/`isn` are in the set. `len(NOISE_WORDS) == 35` (`rag-core.ts:92-97`). | The port "fixes" the 4-char members out of a "3char" set | Delete `"wasn"` |
| C20 | `"memory_search tool"` → `{memory_search, tool}`. Underscore stays inside a token (the split class is `[^a-z0-9_]`). | Tokenizer drift from pi | Split on `[^a-z0-9]+` |
| C21 | `"café résumé"` → `{caf, sum}`. Non-ASCII letters act as separators, the same as JS `[^a-z0-9_]`. | Python `\w` is Unicode-aware, so a `\W` regex would diverge from pi | Use `re.split(r"\W+")` |

**Hit shaping and block formatting.** The golden strings are copied byte-for-byte from `rag-core.ts:412-435`.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| C22 | **Golden block**: header `Memory context (ai-raccoon memory_search, snippets — query: "...")`, the 2 trust lines, both section labels, `[m1] shared/x.md (rank 1) :: first memory snippet`, `[c1] src/a.ts:10-20 (rank 1) :: some code`, and the footer, all compared with `==` against the whole string [pi :116] | Any wording drift | Change one character of the header |
| C23 | The trust header has all four phrases and contains neither `"you must fetch"` nor `"always fetch"` [pi :228] | Hardened or softened wording regresses | Replace "Fetch full content only if needed" |
| C24 | Empty mem and empty code render `(no memory hits)` and `(no code hits)` [pi :126]. **Intersection:** mem present with code empty gives `(no code hits)` only under the code heading. | Empty section vanishes, or the label lands in the wrong section | Emit a single "(no hits)" line |
| C25 | 7 mem + 7 code: `[m5]` and `[c5]` present, `[m6]` and `[c6]` absent [pi :132] | Cap missing or wrong | Cap 5 → 6 |
| C26 | A hit with only `sourceFile` renders the sourceFile as its path, never `?` [pi :141] | Path fallback lost | `path = hit.get("path") or "?"` |
| C27 | Hits drop when path is missing or `"?"` **and** the snippet is empty or whitespace-only. Path-only and snippet-only hits are kept. [pi :248] | Useful hits dropped, or empty ones kept | `and` → `or` in the droppable check |
| C28 | A duplicate hash renders once [pi :267]. The first occurrence wins: the surviving line carries the first hit's path. | Dedupe keeps the last | Iterate reversed |
| C29 | Same snippet with a different hash is deduped (the two seen-sets are ORed, `rag-core.ts:191-206`) | Snippet dedupe lost | Require hash **and** snippet |
| C30 | A 301-char snippet renders as 300 chars + `…` (length ≤ 301). An exactly-300-char snippet is **not** truncated. [pi :279] | Cap or boundary | `>` → `>=` |
| C31 | The query echo in the header is capped at 80 chars [pi :304] | Header bloat | Echo 300 |
| C32 | `one_line` collapses `\n`, `\t` and runs of spaces. A snippet containing `"\n- code (snippets"` cannot start a new block line. (Injection hardening; untrusted text stays on one line.) | A snippet forges block structure | Remove the whitespace collapse |
| C33 | Prune runs before the cap. With 5 duplicates of hit A followed by B and C, both B and C render. | Slicing before dedupe loses real hits | Slice `[:5]` before `prune_hits` |
| C34 | `prune_hits([empty, dup, dup], [])` → one mem hit, `[]` code. `prune_hits` makes no enrich or skip decision [pi :314, :328] | The no-hits decision leaks into the core | Make `prune_hits` raise or return None on empty |
| C35 | `ranking` 1.0 renders `(rank 1)` and 0.8123 renders `(rank 0.8123)`. A missing rank renders `(rank ?)`. A code hit without `lineEnd` gets no `:a-b` suffix. | **Parity trap:** Python `str(1.0)` is `"1.0"` where JS gives `"1"`; the serve sends JSON numbers (research §C field notes) | `str(rank)`; always add the suffix |
| C36 | **Intersection golden:** one fixture combines an empty hit, a snippet-duplicate, a sourceFile-only hit, a missing rank, a multi-line snippet over 300 chars, and 7 hits per side → one full-string golden | Bugs that live where the rules meet | Any of C26–C35's mutations |

**Deferred, not ported** (expanded mode, per §1): pi :149-160, :240-246, :291-302.
**Not portable** (pi TUI cards or `/skill:` helpers): pi :337-424 and :426-487. C7 covers the inverse.
The pi case count ported is 26 of 43, plus 3 inverted (C7). That matches research S6's "~30".

### P2: transport + detection (`tests/test_raccoon_search.py`, `tests/raccoon_fake.py`), 30 rows

**Detection and default-on**

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| T1 | From `proj/a/b` the id comes from `proj/.ai-badger/project-id`, trimmed | Walk stops too early | Look only at cwd |
| T2 | `AI_BADGER_PROJECT_ID=" X "` → `"X"`. It beats the file. A blank env value is ignored. | Override lost, or blank env wins | Ignore env; don't strip |
| T3 | No project-id anywhere → `None`. **Paired control:** add the file and the id is found. | Wrong-project search (S5) | Return `"unknown"` or the basename |
| T4 | Nested `.ai-badger/` without `project-id`, under a parent that has one → `None`. This follows `badger_store`'s rule (`badger_store.py:2062-2084`); pi keeps walking (`index.ts:150-151`). **Open question Q1.** | A nested project searches its parent's memory | Continue the walk |
| T5 | A blank `project-id` file → `None` | An empty projectId gets sent, and the server falls back to its cwd (research §C errors) | Return `""` |
| T6 | The token path resolves **at call time**: load the module, then set `HOME` → the new HOME's token is read | A module constant captured the developer's real home during collection (the `conftest.py:33-36` class of leak) | Hoist `Path.home()` to module scope |
| T7 | A token file holding `"abc\n"` sends the header `X-AiRaccoon-Token: abc` | 401 from the trailing newline | Drop `.strip()` |
| T8 | Token missing, empty, or a directory → disabled, and fake requests == 0. **Paired control:** add a valid token and requests == 1. | Default-on fires without ai-raccoon | Treat missing as "try anyway" |
| T9 | `AI_BADGER_MEM_RAG="0"` with id and token present → disabled, requests == 0 | Kill switch ignored | Delete the check |
| T10 | `AI_BADGER_MEM_RAG` set to each of `""`, `"false"`, `"off"`, `"no"`, `"00"` and `" 0"` → **enabled**. Only the literal `"0"` disables (ruling; pi `!== "0"`). | A truthiness parse widens the kill switch | `value.strip().lower() in {"0","false","off"}` |
| T11 | No env var, id and token present → enabled, and exactly one request (default-on) | Accidentally opt-in | Default the env to `"0"` |

**Wire shape.** Uses the fake server, except T24.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| T12 | A POST to `/mcp` has headers `Content-Type: application/json`, `Accept: application/json, text/event-stream` and the token. The body **equals** `{"jsonrpc":"2.0","id":<int>,"method":"tools/call","params":{"name":"memory_search","arguments":{"projectId","sessionId","query","limit":5,"scope":"project","kind":"both"}}}`. | Dropping `scope` leaks cross-project hits (S5); dropping `sessionId` gives isError | Remove `scope`; `limit` → 8 |
| T13 | Exactly one request per search, and no `initialize` | Latency doubled (research T7: stateless) | Add an initialize round-trip |
| T14 | An SSE reply `event: message\ndata: {json}\n\n` parses to results and code | Parse failure means permanent silence | Parse the body as JSON |
| T15 | SSE with `\r\n` line endings, and a `data:` payload split over two `data:` lines (joined with `\n` per the SSE spec), both parse | Fragile framing | `split("\n")` only; take the first `data:` |
| T16 | An `application/json` reply (no SSE) parses too. The streamable-HTTP spec allows either form. | The serve changes framing and silence follows | SSE-only parser |
| T17 | `result.isError: true` → `None` | Error text rendered as memory | Ignore `isError` |
| T18 | A JSON-RPC `error` object → `None` | KeyError path | Read `result` unguarded, expecting `guarded_main` to catch it (P3 H7 would then log it) |
| T19 | Content without a text part, or text that isn't JSON → `None` | Crash | `json.loads` unguarded |
| T20 | An envelope without `data.results` or `data.code` → treated as empty lists | Crash on shape drift | Index `data["code"]` directly |
| T21 | HTTP 401 → `None`, no exception escapes `search` | Bad token surfaces as an exception | Let `HTTPError` propagate |
| T22 | HTTP 406 and 500 → `None` | Same | Same |
| T23 | Dead port (connection refused) → `None` in under 0.5 s (research T10 measured 0.2 ms) | Serve down blocks the prompt | Retry loop |
| T24 | **Default URL** is `http://127.0.0.1:7721/mcp`, asserted through the injected opener with **no socket** | A wrong port means silently never working | Change the port |

**Deadline and hardening**

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| T25 | **Hang:** the server accepts and never answers; `budget=0.3` → returns `None` within 2 s (watchdog) | The prompt blocks until the host kills the hook | Drop `timeout=` |
| T26 | **Drip:** the server sends headers, then one byte every 0.1 s for 30 s; `budget=0.3` → returns within 2 s | `urlopen(timeout=)` is a per-socket-operation timeout, so a trickling peer never trips it (INFERRED from urllib/socket semantics; **this row proves it**) | Replace the total deadline with plain `urlopen(timeout=budget)`. Watch fail first: write this row against a naive `urlopen(timeout)` implementation and see the watchdog fire. |
| T27 | `AI_BADGER_MEM_RAG_URL` pointing at a loopback fake is honoured. A non-loopback URL (`http://10.0.0.1/mcp`, `http://example.com/mcp`, `http://127.0.0.1.evil/mcp`) is **refused before any I/O**: the injected opener records 0 calls, so the token is never sent. | An env var ships the bearer token off-box | Delete the host check; use `startswith("http://127.0.0.1")` (the `.evil` case catches that one) |
| T28 | With `http_proxy`/`HTTP_PROXY` set to a second fake server, the proxy gets 0 requests and the real fake gets 1 | urllib's default opener honours proxy env and, on macOS, system proxy config; the token goes to a proxy | Use the default `urlopen` instead of `build_opener(ProxyHandler({}))` |
| T29 | A body over the cap (e.g. 1 MB) → `None`, and it is read no further | Memory blow-up on a misbehaving peer | Remove the read cap |
| T30 | `search` never raises, whatever the peer does. This is a parametrized sweep over every fake mode, asserting `None` or a result and no exception. | The fail-silent contract is kept per-row but broken in general | Remove the outer `except` in `search` |

### P3: hook entry (`tests/test_memory_rag_hook.py`), 21 rows

In-process via `_run_main` (as `test_context_enrichment_hook.py:77-79`), except where marked subprocess.

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| H1 | **Happy path:** payload `{prompt, session_id, cwd}`, project with id, token, and a fake with hits → stdout is **exactly one** JSON line `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":<block>}}`, and the block equals `to_memory_context(query, hits)`. Exit 0. | Envelope drift means Claude ignores the output | Rename `additionalContext`; print twice |
| H2 | The Copilot spelling `sessionId` is accepted, and the request carries it | Copilot is always silent (S5: missing sessionId gives isError) | Read only `session_id` |
| H3 | No session id → silent, requests == 0. **Paired control:** H1. | isError is round-tripped every prompt | Send `"unknown"` |
| H4 | Every gate skip (`empty`, `control-word`, `command`, `too-short`, `too-thin`) → silent, requests == 0. Parametrized. | Search runs before the gate: latency cost on every prompt | Call `search` before `should_enrich` |
| H5 | The fake returns only droppable or empty hits → silent (the no-hits skip) | An empty block that says only "(no memory hits)" gets injected | Format even when both are empty |
| H6 | Serve down → silent, exit 0, **stderr empty**, and `hook-errors.log` under the tmp HOME unchanged | Expected states logged as failures; the log grows every prompt when the serve is off (and trips `conftest.py:239-260`) | Route `URLError` to `record_hook_failure` |
| H7 | `raccoon_search.search` monkeypatched to raise `RuntimeError` → exit 0, silent stdout, and `hook-errors.log` gains exactly one line with **no prompt text** in it | Unexpected bugs invisible; privacy leak | Log `repr(payload)`; swallow without logging |
| H8 | stdin that is not JSON, a JSON array, or empty → exit 0, silent | Crash on odd hosts | `payload.get` on a list |
| H9 | `AI_BADGER_MEM_RAG=0` → silent, requests == 0. **Paired control:** unset gives H1. | Kill switch not reaching the entry | Check the switch after `search` |
| H10 | Payload `cwd` = project A (id A) and `CLAUDE_PROJECT_DIR` = project B (id B) → the request carries A. With the payload cwd absent it carries B. | Worktree or main-checkout confusion (the user's memory: hooks resolve against the main checkout) | Prefer `CLAUDE_PROJECT_DIR` |
| H11 | A marker prompt `"f: …"` → the request `query` contains `"f:"` (wire-level echo of C12) | Two hooks on one event interfere | Strip markers in the entry |
| H12 | A prompt of 10 000 chars → the query sent is whatever Q3 decides (capped or not) and pinned. | Unbounded query length means unbounded latency (S2: latency scales with query) | Flip the cap |
| H13 | **Subprocess:** `[sys.executable, memory_rag_hook.py]` with env `HOME=tmp`, `AI_BADGER_MEM_RAG_URL=fake`, and cwd elsewhere → rc 0, stdout JSON with the block (siblings load by path, as `test_message_delivery_hook.py:690-708`) | Works in-process and breaks when spawned | Import siblings by package name |
| H14 | **Subprocess:** the hook copied alone into a tmp dir (sibling missing) → rc 0, silent | A broken sibling blocks the prompt | Import at module top without a guard |
| H15 | The budget constant `BUDGET_SECONDS <= 5`. P4 W2 derives the ordering against host timeouts. No test-only env override is added (see Q5). | Budget creeps above the host timeout and the host kills the hook mid-write | `BUDGET_SECONDS = 9` |
| H16 | Nothing but the one JSON object reaches stdout on the happy path, and nothing at all on skip paths | Stray `print` corrupts the hook protocol | Add a debug print |
| H17 | The block goes out on stdout and the prompt is never rewritten: no `decision`/`prompt` keys in the output | The hook rewrites user input | Add `"prompt": query` |
| S1 | **F1, no spawn, in-process:** patch `subprocess.Popen`, `subprocess.run`, `os.system`, `os.popen`, `os.fork`, `os.posix_spawn`, `os.posix_spawnp`, every `os.exec*` and every `os.spawn*` to raise `AssertionError`. Then drive the hook through happy path (H1), serve down (H6), no token (T8), 401 (T21) and hang (T25). Each path gives its expected output, and no patched callable is ever reached. | A "helpful" proxy fallback (`ai-raccoon` child) that may start a serve (research T9/T11); anything that could launch pi | Add `subprocess.Popen([bin])` on the token-missing path |
| S2 | **F1, no spawn, static:** an `ast` scan of `memory_rag.py`, `raccoon_search.py` and `memory_rag_hook.py` finds no import of `subprocess` or `multiprocessing` and no attribute call to `os.system`/`popen`/`fork`/`exec*`/`spawn*`/`posix_spawn*`. The transitive sibling `debug_log.py` imports none of these (READ, `features/common/hooks/debug_log.py:13-18`), and neither does `badger_store.py` (grep: no hits). | A spawn on a path no dynamic row drives | `import subprocess` in any of the three |
| S3 | **F1, no spawn, subprocess:** run the hook with `PATH` set to a tmp dir holding fake `ai-raccoon` and `pi` executables that each write a marker file. After the serve-down run and the no-token run, neither marker exists. | A spawn through any mechanism, including `os.system` inside a transitive import S2 didn't scan | Shell out to `ai-raccoon` when the token is absent |
| H18 | *(Cuttable, only if telemetry is kept)* With `debug_log` enabled, each terminal state (`gate:<reason>`, `disabled`, `no_project`, `no_session`, `no_hits`, `error`, `hit`) records one distinct event under component `ai_badger_hooks/memory_rag`, following `docs/retrieval.md:457-497` | "Correctly silent" can't be told apart from "not running" (the user's memory: *Shipped and running are different claims*) | Collapse two states into one event name |

### P4: delivery wiring (`tests/test_memory_rag_wiring.py`, plus existing), 15 rows

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| W1 | The manifest entry `memory-rag` has `claude` (`hooks-json`/`UserPromptSubmit`/`memory_rag_hook.py`), `copilot` (`userPromptSubmitted`) and `hermes` (`plugin`/`ai_badger_hooks.py`/`pre_llm_call`), and no `pi` key | A registered component that no agent runs | Drop the copilot arm → `test_hooks_manifest_agent_coverage.py:18` goes red (existing gate; provoke once) |
| W2 | **Derived timeout ordering:** the `hooks.json` `timeout` for the `memory_rag_hook.py` command is greater than `memory_rag_hook.BUDGET_SECONDS` (loaded from the module, not a literal), and the Copilot `timeoutSec` in the generated file is greater than it too | The host kills the hook before its own deadline; the "accept the full wait" ruling breaks silently | `"timeout": 4`, or no timeout at all (Claude's default is 60 s, UNVERIFIED) |
| W3 | Claude `HookWiring.wire()` over the real manifest, with `ai-raccoon-memory/scripts/memory_rag_hook.py` scaffolded → `settings.json` `UserPromptSubmit` names it, `guarded()`, `timeout` kept. **Paired control:** without the script, the note says "not scaffolded — skipped" (`hook_wiring.py:317-322`). | Wired to a missing file; timeout stripped | Drop `timeout` in the rewrite |
| W4 | `config.exclude` containing `ai-raccoon-memory` → not wired (`declined_skill`, `hook_wiring.py:311-316`) | Declined skill still fires on every prompt | Skip the declined check |
| W5 | Copilot `adjust()` over the real manifest → `userPromptSubmitted` includes `memory_rag_hook.py` alongside the existing hooks (superset, as `test_context_enrichment_wiring_end_to_end.py:84-87`) | Collision drops a neighbour | Overwrite the event list |
| W6 | Hermes `adjust()` into the tmp HOME → `memory_rag.py` and `raccoon_search.py` present in **both** the project `.ai-badger/hooks/` and `~/.hermes/plugins/ai-badger/` (pattern `tests/test_hermes_plugin_install.py:72-77`) | Hermes arm inert ("<label> missing") | Omit one `SHARED_SKILL_MODULES` entry |
| W7 | Hermes `pre_llm_inject_context(cwd=proj, message=<long prompt>, session_id="s")` with the fake → returned `context` contains the block, and the request carries `sessionId "s"` | Hermes kwargs mismatch (the prompt arrives as `message` **or** `user_message`, `ai_badger_hooks.py:635,652`) | Read only `user_message` |
| W8 | Hermes, sibling module missing → the other parts (e.g. usage hint) are still returned, and a "missing" warning is logged once (`ai_badger_hooks.py:79-83`) | One failing feature drops every injection (behaviour radius) | Return early on a missing sibling |
| W9 | Hermes, serve down or search raises → the other parts are still returned, no exception | Same | Let the exception escape |
| W10 | Hermes, gate skip → no block, requests == 0 | Hermes searches on every turn | Skip the gate in the Hermes arm |
| W11 | `LEGACY_FLAT_FILES` picks up the new modules automatically (it is derived at `adjust_hooks.py:56-58`), so a stale flat copy is cleaned | A twin list | (Derived. Assert membership; no hand edit expected) |
| W12 | `sync_plugin_skills --check` passes, and `skills/ai-raccoon-memory/scripts/` holds the three new files | Plugin users never receive the hook | Provoke: leave the copy stale → exit 1 |
| W13 | `index_build --check` passes | index.json stale | Provoke: skip the regeneration → exit 1 |
| W14 | **F1 on Hermes:** during `pre_llm_inject_context`, spawn primitives are patched to raise **only around the memory arm** (patch `raccoon_search`'s module globals, since other Hermes parts may legitimately run git). The block is present and no spawn happens. | The in-process Hermes path spawns a proxy | Proxy fallback in the Hermes arm |
| W15 | P0's `hooks_manifest_unresolved(ROOT)` stays `[]` after the P4 manifest and `hooks.json` edits, and V14's provocation is run once on this data | P4 wires an arm that resolves nowhere | Typo the script name in the manifest |

### P5: docs + release, 0 new tests

This package uses the existing gates only. Each gate gets provoked once by leaving its twin out:
- `version_sync --check` and `changelog_index --check` (`verify.sh:232,273`).
- The docs/work README row check. It is CI-only, per the user's memory, so it has to be run locally on purpose.

### P6: integration (`tests/test_memory_rag_integration.py`), 7 rows

| # | Behaviour | Failure mode | Mutation → red |
|---|---|---|---|
| I1 | A full scaffold via `make_scaffolder` (`conftest.py:484-507`) with agents `claude, copilot, hermes, pi`: Claude settings, Copilot hooks file and the Hermes plugin dir all carry the hook. Nothing under pi's outputs (`.ai-badger/hooks/`, `.pi/`, the user-global pi extension dir under the tmp HOME) contains `memory_rag`. | Wiring works per adjuster and fails in the composed scaffold | Remove the Hermes `SHARED_SKILL_MODULES` entries |
| I2 | **Fired in anger, Claude:** take the exact command string written to `.claude/settings.json`, substitute `${CLAUDE_PROJECT_DIR}`, run it through `bash -c` with a payload on stdin, `HOME=tmp` (token) and the fake URL → stdout holds the block | "Shipped but never ran": the repo's recurring defect (the user's memory) | Break the path rewrite in `hook_wiring` |
| I3 | **Fired in anger, Copilot:** the same with the generated `bash` string from `.github/hooks/ai-badger-hooks.json` | Copilot's unprefixed relative path is wrong | Wrong `hooks_rel` |
| I4 | **pi exclusion contract:** (a) no `pi` arm in the manifest entry; (b) `features/pi/adjustments/adapter/*.ts` never names `memory_rag`, and the `before_agent_start` router spawns only `DELIVERY_SCRIPT` (regex over `index.ts:68`, same technique as `test_pi_hook_arm_coverage_contract.py:48-63`); (c) pi's copy list (`features/pi/adjustments/adjust_hooks.py:83-91`) lacks the new modules. Even though pi ships `ai_badger_hooks.py`, the Hermes arm there is inert because its siblings are absent. | A future generic `UserPromptSubmit` replay in the pi bridge silently starts firing the hook under pi | Add `memory_rag_hook.py` to the adapter or to pi's copy list |
| I5 | Scaffolding twice gives exactly one `memory_rag_hook.py` entry per event (pattern `test_scaffold_hook_wiring.py:96`) | Duplicate injection, double latency | Break `_hook_key` dedupe |
| I6 | **Hermes fired in anger:** import `ai_badger_hooks` from the installed tmp-HOME plugin dir (not the source tree) and call `pre_llm_inject_context` against the fake → block present | Source-tree test green while the installed plugin is inert | Ship only to the project dir |
| I7 | **No-live-serve meta-guard:** grep `tests/test_memory_rag*.py`, `tests/test_raccoon_search.py` and `tests/raccoon_fake.py` for `7721`; the only hit is T24, and T24 uses the injected opener | A future test quietly hits the live bank, adding search-log rows (S10) and flaking when the serve is down | Add `urlopen("http://127.0.0.1:7721/mcp")` to any test |

**Manual smoke (not in the suite).** Before merge, run one hand invocation of the scaffolded Claude command against the real serve, with `session_id="ai-badger-smoke"`, and paste the output into the PR. It adds one search-log row (S10), which is acceptable for a single, labelled run. This is the owner-visible demonstration the user's memory asks for.

**Totals:** P0 14, P1 36, P2 30, P3 21 (20 without telemetry), P4 15, P5 0, P6 7. That is about **123 rows**, and the parametrized cases expand past 150.

---

## 4. Twin lists and registries, each with its enforcing check

| Registry | Change | Enforced by |
|---|---|---|
| `features/common/hooks/hooks-manifest.json` | New `memory-rag` entry, 3 arms | `validate.hooks_manifest_agent_gaps` (`tooling/validate.py:418`) via `tests/test_hooks_manifest_agent_coverage.py:18`; `tests/test_pi_hook_arm_coverage_contract.py:144`; W1 |
| `features/common/hooks/hooks.json` `UserPromptSubmit` | New command, `timeout: 8` | W2 (derived ordering), W3 |
| `tooling/validate.py` `HOOK_CAPABLE_AGENTS` / `HOOKS_MANIFEST_AGENT_EXEMPTIONS` | **No change** (all 3 arms present, no exemption needed) | `test_pi_is_not_a_hook_capable_agent_today` (`:163`) |
| `features/hermes/adjustments/adjust_hooks.py` `SHARED_SKILL_MODULES` | +2 entries; `LEGACY_FLAT_FILES` derives | W6, W11 |
| Hermes `PLUGIN_YAML` description (`adjust_hooks.py:62-68`) | Mention memory context in `pre_llm_call` | Prose only. Nothing enforces it (flag in review). |
| `skills/ai-raccoon-memory/scripts/` plugin copies | +3 files | `tooling/sync_plugin_skills.py --check` (`verify.sh:234`) |
| `.ai-badger/skills/ai-raccoon-memory/scripts/` and `.claude/settings.json` of this repo | Re-scaffold against itself (user's memory, release ritual) | drift check / `den-refresh`; manual in P6 |
| `index.json` | Regenerate | `tooling/index_build.py --check` (`verify.sh:233`) |
| `VERSION` 0.177.3 → 0.178.0 | minor | `tooling/version_sync.py --check` |
| `docs/changelog/0.178.0-*.md` + README index row | New | `tooling/changelog_index.py --check` (`verify.sh:273`) |
| `docs/skills.md:565` section, `README.md:204` row, `docs/dictionary.md:22,94` tables, `docs/hermes-claude-compatibility.md:11-16` hook list, `SKILL.md` body (env vars) | Doc rows | No mechanical check for most (UNVERIFIED whether a docs-drift gate covers them). Review-time only. |
| `docs/work/README.md` row for the research record and this plan | Row | CI-only check (user's memory: *docs/work README is a twin list CI only checks*). Run it locally. |
| `tests/test_every_check_can_fail.py` REGISTRY | **P0's new check (required).** Also P6 I7, but only if it becomes a gate rather than a test. | That module's own discovery |
| Copilot event map (`features/copilot/adjustments/adjust_hooks.py:112-118`, a local variable today) | Hoist it to a module constant that both the wirer and P0 read. **Never** a second copy in `validate.py`. | V5 |
| `tooling/validate.py` `_report` list (`:650`) | +1 line for arm resolution | V12 |

---

## 5. Risks and open questions

| # | Risk / question | Recommendation |
|---|---|---|
| **R1** | **The timeout isn't a total timeout.** `urlopen(timeout=)` bounds each socket operation, so a slow-drip peer holds the hook until the host kills it (INFERRED; T26 settles it by running). | Enforce one wall-clock deadline: run the request on a daemon thread and `join(budget)`, or read in chunks and check the deadline between reads. Make T26 the first transport test written. |
| **R2** | **Copilot may ignore `additionalContext` on `userPromptSubmitted`** (UNVERIFIED; no repo doc confirms Copilot consumes it, and `docs/dictionary.md:22` only asserts the mapping). The existing `context_enrichment_hook.py` makes the same assumption. I3 proves the script prints; it can't prove Copilot reads it. | Before claiming Copilot delivery, check the Copilot CLI hooks documentation or run one hand test. If it's ignored, keep the arm (harmless) and say so in the changelog and in a manifest `description`, or record an exemption with the reason. |
| **R3** | **False-green from ambient test state.** `conftest.py:112-119` points `CLAUDE_PROJECT_DIR` at an id-less project, so every silence assertion can pass for the wrong reason. | Paired controls plus a request-count observable on every silence row (§0.3). Review with `review-tests` specifically for unpaired silence rows. |
| R4 | JS vs Python number rendering (`rank 1` vs `rank 1.0`) and the Unicode `\w` difference break byte parity with the pi block | C35 and C21. Implement `_js_number()` (int-valued float → int). |
| R5 | Proxy environment or macOS system proxy routes the loopback call and leaks the token | `build_opener(ProxyHandler({}))`; T28 |
| R6 | A `PI_SESSION_ID` guard would false-silence Claude sessions started from inside pi | Don't add it. Rely on structural exclusion plus the I4 contract, which goes red the day the pi bridge starts replaying `UserPromptSubmit`. |
| R7 | Hermes runs `pre_llm_call` in-process, so a hang blocks the turn for up to the 5 s budget; Hermes's own hook timeout is unknown (UNVERIFIED) | Same total deadline (R1); W9 proves the other parts survive |
| Q1 | Nested `.ai-badger/` without `project-id`: stop (badger_store) or keep walking (pi)? | **Stop.** It is id-absent, which means skip. Searching a parent project's memory is the cross-project failure S5 warns about. Pinned by T4. |
| Q2 | Carry expanded mode and a mode env var? | **No** (see §1). Revisit with its three deferred pi rows if asked. |
| Q3 | Cap the query length sent (S2: latency scales with the query)? | Recommend a cap of about 1 000 chars on the *sent* query; the gate still sees the full prompt. The owner decides; H12 pins either answer. |
| Q4 | Keep telemetry (H18)? | Keep it if cheap: `debug_log` is already beside the other hooks. It is the only way to tell "silent by design" from "not running". It can be cut for the simpler shape. |
| Q6 | F2 read literally ("a command naming it under the same event in its entry hooks.json") is **red today** on `prompt-markers`. That hook is wired through skill discovery (MEASURED probe; `hook_wiring.py:262-293`). | **Accept the discovery path as a second resolution branch** (V7), because both wirers implement it. The alternative is to add explicit prompt-markers commands to `hooks.json` and make the check strict. That is cleaner, but it changes a working wiring path outside this task's scope. The owner picks; V7 pins either answer. |
| Q7 | Hermes `method` values are mostly event names, not `def`s (MEASURED: 11 of 12) | Resolve through `register()`'s `register_hook` pairs, parsed with `ast` (V8/V9). Note the limit: this proves the event is registered, not that the hook's own logic is reached inside that callback (e.g. commit-reminder inside `post_tool_observer`). The fired-in-anger rows (W7, I6) cover that for this hook only. |
| R8 | P0's rule could itself be a check that only ever passes: every arm is resolvable today, so green proves nothing | V1's owner-required red-first provocation, plus the REGISTRY entry (V13) that re-runs it on every suite |
| Q5 | Test-time `BUDGET_SECONDS` override for subprocess timing tests? | Don't add an env var for tests alone. Timing rows run in-process with a `budget=` argument (T25/T26); subprocess rows use fast fakes only. |

---

## 6. Simpler shape?

The smallest version that still meets every ruling:

- **Two files, not three.** Put `memory_rag.py` (gate, prune, format **and** transport) beside `memory_rag_hook.py`.
  - Hermes then needs one `SHARED_SKILL_MODULES` entry.
  - The cost is losing the P1 ∥ P2 parallel lane, since both edit one file. For roughly 250 lines of code that is a fair trade. Test files stay split by concern either way.
- **Cut:** expanded mode and its mode env var, the `minWords`/`minChars`/timeout env knobs (kept as function parameters for tests), telemetry (H18), any `badger_store` state, and the `PI_SESSION_ID` guard. The proxy-transport fallback is no longer a choice: F1 forbids it.
- **Keep, because they carry the rulings and the top risks:** the total deadline (T26), `scope: "project"` (T12), the literal-`"0"` kill switch (T10), default-on detection (T8/T11), fail-silent without error-log spam (H6/H7), the no-spawn proof (S1; S2/S3 are cheap belts), P0's arm-resolution check (F2, V1–V13), the derived timeout ordering (W2), the pi contract (I4), and fired-in-anger (I2/I3).
- **Cutting what's listed above saves about 12 rows** (H18, Q-related, T29 oversize could also go), which brings the total to about 90.
