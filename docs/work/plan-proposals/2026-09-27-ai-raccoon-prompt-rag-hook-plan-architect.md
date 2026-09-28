# Plan proposal (architect lens): per-prompt ai-raccoon memory context hook

Task `aib-ai-raccoon-prompt-rag-hook` · worktree base `4d8ed33b` · VERSION today `0.177.3` (`VERSION:1`).
Lens: module boundaries, feature placement, per-agent delivery, the smallest design the rulings allow.
Grades: READ = read in the cited file this session; MEASURED = from the research record's runs;
INFERRED; UNVERIFIED. Paths are relative to the worktree root unless absolute.

---

## 1. Design

### 1.1 Feature placement: `features/common/skills/ai-raccoon-memory/scripts/`

The hook belongs to the **ai-raccoon-memory** skill, not to `mcp-index`, not to
`features/common/hooks/`, and not to a new skill.

- Screaming architecture: the concept is "the project's ai-raccoon memory". That skill already
  owns every other ai-raccoon hook — `memory_first_gate_hook.py`, `memory_first_gate_post_hook.py`,
  `memory_grade_hook.py` (READ, `ls features/common/skills/ai-raccoon-memory/scripts`), wired from
  `features/common/hooks/hooks.json:99-105,179-199` and `hooks-manifest.json:262-356` (READ).
- It ships by default (`SKILL.md:9` `scope: default`, READ), so a runtime presence check (project-id
  + token file) is the only on/off gate the rulings need. No new scope, no config key.
- It already carries a vendored `badger_store.py` byte-identical to `features/common/hooks/badger_store.py`
  (READ, `cmp` returned same), which gives us project-id resolution for free (§1.2).
- A new skill would add a SKILL.md, index row, docs rows and a routing decision for no behaviour.
  `mcp-index` is the wrong concept (it recommends MCP tools; it does not retrieve memory).

### 1.2 Module split: two files, not three

| File (new) | Role | Imports |
|---|---|---|
| `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` | **Core + transport + orchestration.** Pure section: `should_enrich`, `unique_long_words`, `one_line`, `prune_hits`, `format_block`. Transport section: `search(url, token, arguments, timeout)` (one `urllib` POST, SSE `data:` parse). Orchestration: `build(prompt, cwd, session_id, env=os.environ, home=Path.home(), post=search) -> str \| None` — kill switch, pi guard, project id, token, session, gate, search, prune, both-empty, format. | stdlib + lazy sibling `badger_store` (for `resolve_project_id`) |
| `features/common/skills/ai-raccoon-memory/scripts/memory_context_hook.py` | **Claude/Copilot entry.** stdin JSON → `memory_context.build(...)` → one `hookSpecificOutput` line → exit 0. Loads the sibling by path under a distinctive `sys.modules` key, the `context_enrichment_hook.py:41-68` pattern (research Lane A §1, READ there). | stdlib |

Hermes gets **no third file**: `ai_badger_hooks.pre_llm_inject_context` (`features/common/hooks/ai_badger_hooks.py:634-729`, READ)
loads `memory_context.py` through the existing `_load_sibling_module` (`ai_badger_hooks.py:63`, READ)
exactly like `_load_memory_first_gate` does (`:338-345`, READ), and appends the string `build()` returns.

Why transport is a section of `memory_context.py` and not its own file: every extra sibling module
costs an entry in Hermes's `SHARED_SKILL_MODULES` (`features/hermes/adjustments/adjust_hooks.py:35-43`, READ),
its test twin (`tests/test_hermes_plugin_install.py:20-28`, READ), a second path-load in the hook, and a
second vendored copy in `skills/` and `.ai-badger/skills/`. The seam tests need is the `post=` parameter on
`build()` plus a stdlib `http.server` fake for `search()` itself — both exist without a file split. Split
later if a second consumer of the transport appears.

Why Hermes does not inline the logic (as it did for `context_enrichment`, per Lane A §1): the inline copy is
the twin the repo has had to police ever since. One module, three callers.

**Project id:** `badger_store.resolve_project_id(cwd)` (`features/common/hooks/badger_store.py:2105-2119`, READ):
`AI_BADGER_PROJECT_ID` wins, else nearest `.ai-badger/project-id`. This is the id the bank answers to (S4,
MEASURED) and the message bus already uses it — no third resolver. If `badger_store` fails to load, skip.
`memory_first_gate.project_id()` (the basename heuristic) is *not* used (S4).

**Session id:** Claude `session_id`, Copilot `sessionId` (same duck-typing as `context_enrichment_hook.py:140`,
READ via research), Hermes `kwargs["session_id"]` (`ai_badger_hooks.py:665`, READ). Blank → skip
(a missing sessionId is an `isError`, S5).

**Request (fixed by ruling):** `POST http://127.0.0.1:7721/mcp`, header `X-AiRaccoon-Token: <~/.ai-raccoon/mcp-token>`,
`Content-Type: application/json`, `Accept: application/json, text/event-stream`, body
`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_search","arguments":{"projectId","sessionId","query","kind":"both","scope":"project","limit":5}}}`.
No `initialize` (T7, MEASURED). Reply: first `data:` line of the SSE body, else the whole body as JSON;
`result.content[type=text].text` → `{"data":{"results","code"}}`; `isError`, JSON-RPC `error`, 401, refused,
timeout, or any exception → `None`.

**Gate (ruling S6):** empty → control-word → command (leading `/`, no carve-out) → too-short (`<20` chars) →
too-thin (`<6` unique ≥3-char words outside the 35-word noise set). `extract_query` is dropped: with no
`/skill:` prefix it is the identity on the trimmed prompt. Constants, not env knobs.

**Block:** byte-for-byte `toMemoryContext` (Lane B §1.10): header, three-line trust header, memories section,
code section, footer; snippets `one_line` to 300 chars + `…`, query echo to 80, top 5 per corpus after prune.

**Modes — decision: default only; no mode env var.** Expanded mode needs `memory_get`/`code_get` fan-out,
a second formatter, a per-hit fallback path and ~6 more tests, for a benefit the default block already
offers on demand (every line carries the hash and names `memory_get`/`code_get`). The ruling makes the mode
var optional; ask-if-simpler says cut it. If it is added later, it is additive (`AI_BADGER_MEMORY_CONTEXT=expanded`
can reuse the same variable, so no second env name is spent now).

**Env surface (one variable):** `AI_BADGER_MEMORY_CONTEXT` — literal `"0"` disables; anything else, or unset,
leaves the default. Follows the `AI_BADGER_*` literal-`"0"`/`"1"` convention (S9, READ via research §6).

**Failure visibility:** skips are silent (no stdout, exit 0). Errors (exception, `isError`, HTTP error) print
one reason line to **stderr** and still exit 0 — nothing written to `$HOME`, nothing that tests must redirect,
and a broken token read is not invisible forever (memory note "shipped and running are different claims").
No `debug_log`/audit integration in v1 (follow-up).

**Timeouts:** `search()` uses `urlopen(timeout=5.0)`. Claude: `"timeout": 10` on the new `hooks.json` command
— the same value `memory_first_gate_hook.py` carries (`hooks.json:103`, READ) and preserved into
`.claude/settings.json` (`.claude/settings.json:207-208`, READ). Copilot: `adjust_hooks.py:145-149` hardcodes
`"timeoutSec": 10` (READ) — already above 5 s, no change. Hermes: in-process, bounded only by the 5 s urlopen.

### 1.3 Per-agent delivery (exact files)

| Agent | Mechanism | Files to touch |
|---|---|---|
| Claude | `hook_wiring.py` reads the manifest's `claude` arm `type: hooks-json` (`skills/welcome-ai-badger/scripts/hook_wiring.py:253`, READ), selects the command from `hooks.json` by script-name suffix, rewrites `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` → `${CLAUDE_PROJECT_DIR}/.ai-badger/skills/`, merges into `.claude/settings.json`, and writes `.ai-badger/hooks/hooks.json` (`:352`, READ). | `features/common/hooks/hooks-manifest.json` (new `memory-context` entry), `features/common/hooks/hooks.json` (new `UserPromptSubmit` command with `"timeout": 10`) |
| Copilot | `features/copilot/adjustments/adjust_hooks.py` maps `userPromptSubmitted`→`UserPromptSubmit` (`:112-119`, READ), filters the source command by `script` (`:121-128`), rewrites the skills path via `_rewrite_command` (`:31-55`, READ) into `.github/hooks/ai-badger-hooks.json`. | none beyond the two catalog files above |
| Hermes | `pre_llm_call` → `pre_llm_inject_context` (`ai_badger_hooks.py:1179`, READ). New `_load_memory_context()` via `_load_sibling_module`; append `build(prompt, project, kwargs.get("session_id"))` to `parts`. Hermes adjust copies it beside the plugin. | `features/common/hooks/ai_badger_hooks.py`, `features/hermes/adjustments/adjust_hooks.py` (`SHARED_SKILL_MODULES` += `("ai-raccoon-memory","memory_context.py")`), `tests/test_hermes_plugin_install.py:20-28` twin |
| pi | Nothing. See §1.4. | none |

**Critical twin:** a manifest entry whose script has no `hooks.json` command falls back to discovery in
`.ai-badger/skills/<hook-name>/scripts/*_hook.py` (Claude, `hook_wiring.py` per Lane A §2; Copilot
`adjust_hooks.py:155-177`, READ). With hook name `memory-context` that directory does not exist, so the hook
would be **silently unwired**. The manifest entry names `"script": "memory_context_hook.py"` on both arms and
`hooks.json` carries the command; the integration test (P4) is what proves the pair agrees.

### 1.4 How pi stays excluded, and what proves it

1. **Structural (primary).** The manifest entry has no `pi` arm; pi is not in `HOOK_CAPABLE_AGENTS`
   (`tooling/validate.py:180`, READ). pi's adapter runs only `message_delivery_hook.py` at
   `before_agent_start` (`features/pi/adjustments/adapter/index.ts:729`, READ; zero `pre_llm|context_enrichment`
   hits in the adapter, MEASURED in research), and reads `.ai-badger/hooks/hooks.json` (`index.ts:67,101`, READ)
   for Pre/PostToolUse only. pi copies `ai_badger_hooks.py` (`features/pi/adjustments/adjust_hooks.py:83-91`,
   READ) but never calls `pre_llm_inject_context`, and never copies `memory_context.py`.
2. **Defensive (secondary).** `build()` returns `None` when `PI_SESSION_ID` is non-blank. Needed because the new
   command **will** appear in `.ai-badger/hooks/hooks.json`'s `UserPromptSubmit` array (the file already holds
   three such commands — READ, parsed this session), so any future generic `UserPromptSubmit` replay in the pi
   adapter would start running it next to pi's own `mem-based-rag` extension (double injection).
   Evidence the env var reaches children: pi-badger-integration pins it (`extensions/message-bus/index.ts:740`, READ);
   ai-badger's adapter treats it as a fallback (`hook-bridge.ts:552`, READ); but `bus-prefilter.ts:78` says it is
   "injected only into shell-tool subprocesses" (READ) — so whether a hook spawn carries it is **UNVERIFIED**.
3. **Proof.** (a) existing `tests/test_pi_hook_arm_coverage_contract.py` keeps pi out of both manifest arms and
   `HOOK_CAPABLE_AGENTS`; (b) P4's scaffold test with `agents=[claude,copilot,hermes,pi]` asserts no pi-owned output
   (pi adjust's copied file list, `~/.pi/agent/extensions/ai-badger/` under a redirected HOME) names
   `memory_context`; (c) a P2 unit test: `PI_SESSION_ID` set + a fake bank that returns hits → `None`.

---

## 2. Packages

Ship as **one PR, one commit per package** (invariant pr-per-task). Every package is mergeable on its own
(green suite, no dead wiring), but only P4 bumps VERSION: if a package is merged alone, `release_guard`
will require its own patch bump + changelog entry (INFERRED from `tooling/version_sync.py` docstring naming
release_guard's shipped roots; not run).

| Pkg | Title | Depends on | Parallel with | Shared files |
|---|---|---|---|---|
| P1 | Gate + formatter core, ADR | — | P3-docs half | `memory_context.py` (with P2) |
| P2 | Transport + orchestration + Claude/Copilot entry | P1 | — | `memory_context.py` |
| P3 | Per-agent wiring (catalog + Hermes) | P2 | — | `hooks-manifest.json`, `hooks.json`, `ai_badger_hooks.py`, hermes `adjust_hooks.py` |
| P4 | Integration: scaffold e2e, self-rescaffold, registries, docs, release | P3 | — | `VERSION`, `index.json`, `skills/`, `.ai-badger/`, `.claude/settings.json`, `.github/hooks/` |

Honest parallelism: the code is ~250 lines in one module; P1→P2→P3 are sequential by design. The only
parallel lane is the prose (SKILL.md section, `docs/skills.md`, `docs/dictionary.md`, changelog draft), which a
docs agent can write in its own worktree once §1 is agreed, merged into P4.

### P1 — Gate and formatter core (+ ADR)
Files: new `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` (pure section only);
new `tests/test_memory_context_core.py`; new `docs/adr/0031-per-prompt-memory-context-over-ai-raccoon-http.md`
(next free number: `docs/adr/` ends at `0030-…`, READ) + its `docs/adr/README.md` row.

Acceptance:
- `should_enrich(prompt)` returns `(enrich, reason, query, unique_words)` with reasons exactly
  `empty|control-word|command|too-short|too-thin|ok`, in that gate order.
- `format_block(query, mem, code)` reproduces the pi `toMemoryContext` block byte-for-byte for the fixtures
  ported from `rag-core.test.ts:109-147,227-311`.
- Module imports nothing outside stdlib at module level.
Gate: `.venv/bin/python3 -m pytest -q tests/test_memory_context_core.py` and
`.venv/bin/python3 -m pylint features/common/skills/ai-raccoon-memory/scripts/memory_context.py`.

### P2 — Transport, orchestration, hook entry
Files: `memory_context.py` (+ `search`, `build`); new `memory_context_hook.py`;
new `tests/test_memory_context_transport.py`, `tests/test_memory_context_hook.py`.

Acceptance:
- `build()` returns the block for an enrichable prompt when a fake bank returns hits; `None` for every skip.
- The request body carries `kind:"both"`, `scope:"project"`, `limit:5`, `projectId`, `sessionId`, the header token.
- The hook prints exactly one JSON line `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":…}}`
  or nothing, and exits 0 on every path including malformed stdin.
- No test opens port 7721 or reads the real `~/.ai-raccoon` (fake server on an ephemeral port; `home=`/`HOME` → `tmp_path`).
Gate: `.venv/bin/python3 -m pytest -q tests/test_memory_context_transport.py tests/test_memory_context_hook.py` + pylint on both scripts.

### P3 — Per-agent wiring
Files: `features/common/hooks/hooks-manifest.json` (entry `memory-context`: claude `hooks-json`/`UserPromptSubmit`,
hermes `plugin`/`ai_badger_hooks.py`/`pre_llm_call`, copilot `hooks-json`/`userPromptSubmitted`, both script arms
`memory_context_hook.py`); `features/common/hooks/hooks.json` (UserPromptSubmit command, `"timeout": 10`);
`features/common/hooks/ai_badger_hooks.py` (loader + append); `features/hermes/adjustments/adjust_hooks.py`
(`SHARED_SKILL_MODULES`); `tests/test_hermes_plugin_install.py` (`SHARED_SKILL_FILES` twin);
new `tests/test_memory_context_hermes.py`.

Acceptance:
- `python3 tooling/validate.py --all` passes (manifest schema + `hooks_manifest_agent_gaps`, `validate.py:418,650`).
- Hermes `pre_llm_inject_context` includes the block when the loaded module's `build` returns one, and is
  unchanged (still returns its other parts or `None`) when it returns `None` or raises.
- `tests/test_hermes_plugin_install.py`'s derived sibling-load check (`:405-436`, READ) passes with the new loader.
Gate: `.venv/bin/python3 -m pytest -q tests/test_memory_context_hermes.py tests/test_hermes_plugin_install.py tests/test_hooks_manifest_agent_coverage.py tests/test_pi_hook_arm_coverage_contract.py tests/test_hook_wiring_claude.py tests/test_adjust_hooks_copilot.py` and `python3 tooling/validate.py --all`.

### P4 — Integration (last)
Files: new `tests/test_memory_context_wiring_end_to_end.py` (real manifest + real hooks.json, the
`tests/test_context_enrichment_wiring_end_to_end.py:1-11` philosophy, READ); `python3 tooling/sync_plugin_skills.py`
(refreshes `skills/ai-raccoon-memory/scripts/`); `python3 tooling/index_build.py`; self-rescaffold of this repo
(`.ai-badger/skills/…`, `.ai-badger/hooks/hooks.json`, `.claude/settings.json`, `.github/hooks/ai-badger-hooks.json`);
`features/common/skills/ai-raccoon-memory/SKILL.md` (a short "Per-prompt memory context" section + kill switch);
`docs/skills.md:565-585`; `docs/dictionary.md:22` area (context-injection row mention); `VERSION` → `0.178.0`;
`python3 tooling/version_sync.py`; `docs/changelog/0.178.0-per-prompt-memory-context.md`; `python3 tooling/changelog_index.py`.

Acceptance:
- Scaffolding a fresh target with `agents=[claude,copilot,hermes,pi]` yields: a `UserPromptSubmit` command naming
  `.ai-badger/skills/ai-raccoon-memory/scripts/memory_context_hook.py` with `timeout: 10` in `.claude/settings.json`;
  a `userPromptSubmitted` entry naming it in `.github/hooks/ai-badger-hooks.json`; `memory_context.py` beside
  `ai_badger_hooks.py` in `.ai-badger/hooks/` and in the (redirected-HOME) Hermes plugin dir; and no pi-owned
  artefact naming `memory_context`.
- Running the scaffolded Claude command (the literal string from settings.json, via `sh -c`) with a real stdin
  payload against a fake bank on an ephemeral port produces the block — proves the path rewrite and the
  existence guard, not just the JSON.
- Existing `prompt-markers`, `context-enrichment`, `message-delivery-per-turn` UserPromptSubmit commands are all still present.
- **Fired-in-anger demo (manual, recorded in the PR, not a test):** in a live Claude session in this repo, one
  enrichable prompt shows the Memory context block in the transcript; `AI_BADGER_MEMORY_CONTEXT=0` removes it.
Gate: `.venv/bin/python3 -m pytest -q tests/test_memory_context_wiring_end_to_end.py tests/test_sync_plugin_skills.py tests/test_scaffold_hook_wiring.py`,
`python3 tooling/index_build.py --check`, `python3 tooling/version_sync.py --check`, `python3 tooling/changelog_index.py --check`,
`python3 tooling/validate.py --all`, `python3 gates/docs_guard.py`, `python3 gates/scaffold_freshness_guard.py` (UNVERIFIED CLI shape for the two gates; read each `--help` first).

---

## 3. Test lists (design-tests shape)

### P1 — `tests/test_memory_context_core.py` (port of ~30 pi cases, `rag-core.test.ts`)
| # | Behaviour | Failure mode targeted | Mutation that turns it red |
|---|---|---|---|
| 1 | Long IDEA-shaped prompt → `ok`, query == trimmed prompt (`:23-30`) | gate rejects real prompts | change `>=` to `>` in the word floor; drop `.strip()` |
| 2 | Each of `stop continue exit quit clear help ping` → `control-word` (`:32-36`) | control words searched | remove a word from the set |
| 3 | `STOP` → control-word; `stop! please halt …`/`STOP now please …` → enrich (`:202-216`) | exact-match turned into prefix/contains match | `startswith` instead of set membership |
| 4 | `/delegations`, `/compact foo`, `/delegate some long task …` → `command` (`:38-45,163-173`) | slash commands searched | remove the leading-`/` gate |
| 5 | `/skill:task extend the delegation timeout …` → `command` (ai-badger has no carve-out) | pi skill carve-out ported by mistake | re-add `SKILL_PREFIX_RE` exception |
| 6 | Short slash prompt reports `command`, not `too-short` | gate order swapped | move length check before command check |
| 7 | 19-char prompt → too-short; 20 chars with 6 words → ok | off-by-one on `min_chars` | `<=` for `<` |
| 8 | `prompt context injection extension filter` → too-thin, 5 (`:60-66`) | thinness floor wrong | `min_words = 5` |
| 9 | 6-word probe enriches at default (`:191-200`) | floor at v1 value 8 | `min_words = 8` |
| 10 | `""`, `"   "` → empty (`:74-77`) | whitespace treated as content | drop strip before emptiness test |
| 11 | `f: please explain …` enriches, query keeps `f:` (`:218-224`) | marker stripping leaks in | strip a leading marker |
| 12 | `unique_long_words` cases: sizes 3,0,6,0,5 (`:95-107`) | tokenizer/noise-set drift | length floor `> 3` (drops `fix`, `api`); lowercase after split (case-split `Router`); drop `the` from the noise set |
| 13 | Noise set equals the 35 pi words exactly | silent dictionary edit | delete one word (assert on the literal set length+members) |
| 14 | Block golden: header, trust lines, `[m1] shared/x.md (rank 1) :: …`, `[c1] src/a.ts:10-20 (rank 1) :: …`, footer (`:109-124`) | format drift breaks the model contract | change any literal character |
| 15 | Empty mem+code → `(no memory hits)` and `(no code hits)` (`:126-130`) | empty section omitted | skip the placeholder |
| 16 | 7+7 hits → `[m5]`,`[c5]` present, `[m6]`,`[c6]` absent (`:132-139`) | cap missing | slice `[:6]` |
| 17 | `sourceFile`-only hit renders the sourceFile (`:141-146`) | path fallback lost | drop `or sourceFile` |
| 18 | Code line without lineStart/lineEnd has no `:a-b` suffix | `None-None` rendered | always append suffix |
| 19 | Trust header has all phrases and none of `you must fetch`/`always fetch` (`:228-238`) | softened wording regresses | edit a trust line |
| 20 | Hit with neither path nor snippet (incl. `path:""`, `snippet:"   "`) dropped; path-only and snippet-only kept (`:248-265`) | droppable rule inverted to AND/OR | `and`→`or` |
| 21 | Duplicate hash renders once; duplicate snippet with different hash renders once (`:267-277`) | only one dedupe key | remove snippet set |
| 22 | Snippet capped at 300 + `…`, length ≤ 301 (`:279-289`) | unbounded context size | cap 3000 / drop ellipsis |
| 23 | Query echo capped at 80 (`:304-310`) | huge prompt echoed | cap removed |
| 24 | `one_line` collapses newlines/tabs to single spaces | multi-line snippets break the list shape | `split(" ")` instead of `split()` |
| 25 | `prune_hits` never decides enrichment: both-empty after prune, `should_enrich` still `ok` (`:328-334`) | core coupling | make prune return a skip reason |
| 26 | Ranking missing → `rank ?` | KeyError on partial hits | index `hit["ranking"]` |

### P2 — `tests/test_memory_context_transport.py`, `tests/test_memory_context_hook.py`
| # | Behaviour | Failure mode | Mutation |
|---|---|---|---|
| 1 | Fake server records one POST to `/mcp` with header `X-AiRaccoon-Token` = token file content (stripped) | auth header wrong → 401 forever, silently | rename header / drop strip |
| 2 | Body `arguments` == `{projectId, sessionId, query, kind:"both", scope:"project", limit:5}` | cross-project leak (S5) | drop `scope` |
| 3 | SSE reply `event: message\ndata: {...}` parsed; plain JSON reply parsed | SSE assumption breaks on a JSON reply | parse only `data:` |
| 4 | `isError: true` → `None` | error text injected as memory | ignore `isError` |
| 5 | JSON-RPC `error` → `None`; HTTP 401 → `None` + stderr line | same | swallow without check |
| 6 | Connection refused (unbound ephemeral port) → `None` within 1 s | hook blocks prompt when serve down | retry loop |
| 7 | Server that sleeps past a small injected timeout → `None` | hang | remove `timeout=` |
| 8 | `AI_BADGER_MEMORY_CONTEXT=0` → `None`, fake server sees zero requests | kill switch leaks a request | check after search |
| 9 | `AI_BADGER_MEMORY_CONTEXT=1`/unset → enriched | inverted switch | `!= "1"` |
| 10 | `PI_SESSION_ID` set → `None`, zero requests | pi double injection | delete guard |
| 11 | No `.ai-badger/project-id` in tmp tree → `None`, zero requests | cross-project search with blank id | send `""` |
| 12 | `AI_BADGER_PROJECT_ID` override used | override ignored | read file first |
| 13 | Token file missing (tmp HOME) → `None`, zero requests | 401 request per prompt | skip the existence check |
| 14 | Blank session id → `None`, zero requests | isError per prompt | default `"default"` |
| 15 | Gate skip (`stop`) → zero requests | every prompt pays 1.3 s | search before gate |
| 16 | Both corpora empty after prune → `None` | empty block injected | format even when empty |
| 17 | Hook: valid payload + fake bank → one JSON line, `hookEventName` `UserPromptSubmit`, block in `additionalContext` | envelope drift | rename key |
| 18 | Hook: `sessionId` (Copilot spelling) accepted | Copilot never enriches | read only `session_id` |
| 19 | Hook: malformed stdin / sibling missing → no stdout, exit 0 | broken hook blocks prompt | let exception escape |
| 20 | Hook subprocess run with `HOME=tmp_path` never creates files under it | a writer to `$HOME` sneaks in | add an error log under `~/.ai-badger` |

### P3 — wiring
| # | Behaviour | Failure mode | Mutation |
|---|---|---|---|
| 1 | Hermes: `pre_llm_inject_context(message=…, session_id=…)` includes the block from a stub `build` | Hermes arm registered, never runs | forget to append |
| 2 | Hermes: stub `build` raises → other parts still returned, no raise | one bad module kills every Hermes turn | no try/except |
| 3 | Hermes: module absent → unchanged output | older scaffold crashes | unguarded import |
| 4 | Hermes passes `kwargs["session_id"]` and the project cwd | wrong id → skip forever | pass `""` |
| 5 | `validate --all` fails when the `copilot` arm is removed from the new entry (prove-the-check-fails, run once by hand) | coverage gate never fires for this entry | — (manual red/green) |
| 6 | `SHARED_SKILL_FILES` twin equality and derived sibling-load test pass | Hermes plugin dir lacks the module | omit the tuple entry |

### P4 — integration
| # | Behaviour | Failure mode | Mutation |
|---|---|---|---|
| 1 | Scaffold 4 agents → Claude settings has the command, `timeout: 10` | manifest/hooks.json twin mismatch → silently unwired | delete the hooks.json command |
| 2 | Copilot hooks file has `userPromptSubmitted` entry naming the script | event-name typo | manifest event `userPromptSubmit` |
| 3 | Hermes dirs hold `memory_context.py` | not copied | drop SHARED_SKILL_MODULES entry |
| 4 | No pi-owned artefact names `memory_context` | pi wiring added by accident | add `memory_context.py` to pi's `hook_scripts` |
| 5 | Executing the scaffolded Claude command string produces the block against a fake bank | path rewrite wrong (`${CLAUDE_PROJECT_DIR}` → missing file → systemMessage skip) | break the rewrite prefix |
| 6 | The other three UserPromptSubmit hooks survive | merge clobbers siblings | replace instead of merge |
| 7 | `skills/` copy in sync (`test_sync_plugin_skills.py:262-270`) | plugin users get no hook | skip the sync |

---

## 4. Twin lists and registries to update

| Registry | Change | Enforced by |
|---|---|---|
| `features/common/hooks/hooks-manifest.json` | new `memory-context` entry, three arms | `tooling/validate.py --all` → schema + `hooks_manifest_agent_gaps` (`validate.py:418,650`); `tests/test_hooks_manifest_agent_coverage.py` |
| `features/common/hooks/hooks.json` ↔ manifest `script` | UserPromptSubmit command for `memory_context_hook.py` | **Nothing today** checks the pair; P4 test #1/#5 does. Recommend (follow-up, not this task) a generic validate check: every `hooks-json` arm's `script` has a matching command in `hooks.json`. |
| `validate.py` `HOOK_CAPABLE_AGENTS` | unchanged (pi stays out) | `tests/test_pi_hook_arm_coverage_contract.py` |
| `HOOKS_MANIFEST_AGENT_EXEMPTIONS` | none needed (all three arms present) | same validate check |
| Hermes `SHARED_SKILL_MODULES` (`adjust_hooks.py:35-43`) + test twin `SHARED_SKILL_FILES` (`tests/test_hermes_plugin_install.py:20-28`) | add `("ai-raccoon-memory","memory_context.py")` to both | `test_hermes_plugin_install.py:206-208` (twin equality) and `:405-436` (derived from `_load_sibling_module` calls) |
| `skills/ai-raccoon-memory/scripts/` (plugin copy) | two new files | `tooling/sync_plugin_skills.py --check` via `tests/test_sync_plugin_skills.py:262-270` |
| `.ai-badger/` self-scaffold, `.claude/settings.json`, `.github/hooks/ai-badger-hooks.json`, `.ai-badger/hooks/hooks.json` | re-scaffold this repo | `gates/scaffold_freshness_guard.py` (memory: release ritual) |
| `index.json` | regenerate | `python3 tooling/index_build.py --check` |
| `VERSION` + `.claude-plugin/plugin.json` + `marketplace.json` + stamped JSON | `0.178.0` (minor: new feature) | `python3 tooling/version_sync.py --check`; `gates/release_guard.py` |
| `docs/changelog/0.178.0-per-prompt-memory-context.md` + README index row | new entry; row generated | `python3 tooling/changelog_index.py --check`; `gates/docs_guard.py` |
| `docs/adr/0031-…md` + `docs/adr/README.md` row | new ADR | `gates/docs_guard.py` RECORD_DIRS (`:74`, READ) — UNVERIFIED whether it checks the ADR index row |
| `docs/skills.md` ai-raccoon-memory section, `features/common/skills/ai-raccoon-memory/SKILL.md`, `docs/dictionary.md` | prose rows | no mechanical check (review) |
| `docs/work/README.md` | row already present (`:144`, READ) | CI docs check (memory note) |
| badger_store vendored copies | unchanged (reused, not edited) | existing byte-equality test (ADR-0024) |

---

## 5. Risks and open questions

| # | Risk / question | Recommendation |
|---|---|---|
| R1 | **Latency on every gated prompt (~1.3 s, up to 2.1 s seen; S2 MEASURED).** Accepted by ruling, but it is per prompt, in Claude, Copilot *and* Hermes, and on by default wherever the token exists. | Ship as ruled; state the cost and the kill switch in the changelog and SKILL.md. Follow-up: code-only leg (~65 ms) as a latency option if users complain. |
| R2 | **manifest ↔ hooks.json pair is an unchecked twin**; a missing command is silently unwired (discovery fallback finds nothing). | P4 e2e test covers this hook; file an issue for a generic validate check. |
| R3 | **`PI_SESSION_ID` guard may be dead or over-broad.** Unverified that pi's hook spawns carry it (`bus-prefilter.ts:78`); a Claude session launched from a pi shell would inherit it and lose enrichment. | Keep the guard (cheap, protects against a future generic replay); primary exclusion stays structural. Verify once against a live pi session in the P4 demo and record the result. |
| R4 | Copilot `userPromptSubmitted` honouring `hookSpecificOutput.additionalContext` and sending `sessionId`: asserted by `docs/dictionary.md:22,94` but UNVERIFIED against Copilot itself. | Same trust level as `context_enrichment_hook` today; note it; no extra work. |
| R5 | HTTP `/mcp` contract (no `initialize`, SSE single frame, `Accept` header requirements) is ai-raccoon-internal, not the documented proxy entry. | Accept per ruling; parse both SSE and plain JSON; any mismatch degrades to silence + stderr line. No proxy fallback. |
| R6 | Every enriched prompt writes a `search_quality` row (S10). | Expected; tests never hit the live serve. Mention in changelog. |
| R7 | Retrieved snippets are untrusted text injected into the model's context (prompt-injection vector). | The ported trust header is the mitigation; pin it byte-for-byte (P1 #19). |
| R8 | Hermes `pre_llm_call` blocks the turn in-process up to 5 s. | Accept per ruling; the 5 s urlopen bounds it. |
| Q1 | Expanded mode? | Not in v1 (§1.2). |
| Q2 | Telemetry via `debug_log`/call-behaviorist? | Not in v1; `build()` exposes skip reasons internally so wiring it later is a small change. |

---

## 6. Simpler shape?

The smallest version that meets every ruling is what §1–§2 already describe, and it was reached by cutting:

- **No expanded mode, no mode env var** — one env var (`AI_BADGER_MEMORY_CONTEXT`) instead of two; one formatter.
- **No min-words/min-chars/timeout/snippet env knobs** (pi has six) — constants.
- **No proxy transport fallback, no `initialize` handshake** — one POST.
- **No new skill, no new stack, no adjustment script** — two files in an existing default skill, reached through
  existing wiring (manifest + hooks.json for Claude/Copilot, one loader for Hermes).
- **No separate transport file** — one module, three callers; Hermes does not get an inline copy.
- **No new project-id resolver** — reuse `badger_store.resolve_project_id`, already vendored beside the script.
- **No state, no counters, no `/rag status`, no telemetry, no writes to `$HOME`.**
- **No card rendering, `/ask`, query-pipeline, skill-prefix rules** (Lane B §5).

Could it be smaller still? Dropping the Hermes arm would remove P3's Hermes half, but the ruling names Hermes,
and `HOOK_CAPABLE_AGENTS` would then demand an exemption reason — not simpler. Dropping the `PI_SESSION_ID`
guard saves two lines and one test; kept because the command lands in a file pi's adapter already reads (§1.4).
Collapsing P1–P3 into one commit is possible; the split is kept only so each commit has a gate that can go red
on its own.
