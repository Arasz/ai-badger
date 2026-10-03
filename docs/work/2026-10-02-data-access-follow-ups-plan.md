# Data-access follow-ups: implementation plan

> **For agentic workers:** each task below runs as one `/task <taskId>` invocation (the
> ai-badger `task` skill), on its own worktree from fresh `origin/main`, ending in its own PR.
> The task skill does the research, `task-decomposition` into steps, TDD and review loops. This
> plan fixes **scope, grouping, order, interfaces and acceptance criteria**; it deliberately
> leaves bite-sized steps to each task's own decomposition, which the user chose as the
> execution method.

**Goal:** close the eleven follow-ups that 0.185.0 (PR #549, ADR-0034) listed as out of scope.
At the end, a corporate operator can run ai-badger with client data and point to a rule or a
documented gap for every byte that leaves the machine.

**Architecture:** the 0.185.0 egress rule lives in `openrouter_client.egress_allowed(url, env,
cwd)`. That is one predicate in two vendored copies, enforced in `post_json`. The tasks below
take three approaches:
- extend that predicate: proxy, allowlist, project-id binding;
- route more surfaces through it, or through its documented sibling `dataPolicy` lock: memory
  scoring, feed-badger, archify, pi;
- close the remaining gaps in text or docs.

No task adds a second policy mechanism.

**Tech stack:** Python 3.10+ stdlib-only hooks and scripts (`urllib`, `json`, `pathlib`). The
vendored archify skill is Node `.mjs`. pi-badger-integration is TypeScript. Tests use pytest with
`.venv/bin/python3` from the main checkout.

**Spec:**
- `docs/adr/0034-third-party-egress-is-opt-in-and-lockable.md`;
- `docs/reference/data-access.md`, including its "Not governed" list, which is this plan's backlog;
- `docs/work/2026-10-02-aib-local-only-data-access-hardening-research.md`, F4–F12 and "Still open".

## Global constraints

- Only the agent host's approved provider receives project data by default. A new surface is
  default-off or local.
- ai-raccoon is local and approved (owner, 2026-10-03). Its memory server, search, the
  single-search hook mode and its embeddings run on the machine, so it is not a third-party
  surface. Tasks use it freely, locked projects included, and T8 does not audit it. Only an
  explicitly configured `memory_sync` cloud target leaves the machine, and that stays opt-in.
- One egress predicate. Extend `egress_allowed` and `project_locked` in
  `features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py`, and re-copy them to
  `features/common/skills/task-decomposition/scripts/openrouter_client.py`, re-applying only the
  `TEST_BASE_ENV` line. `tests/test_jev_client_vendored.py` byte-compares the rest.
- Fail closed. An unreadable or unparseable policy input locks. A hook never raises and never
  blocks a prompt.
- Hooks and scripts stay stdlib-only. Model runtimes (torch, llama.cpp, TEI) live behind an HTTP
  endpoint, never in-process.
- Every task:
  - bumps `VERSION` and adds `docs/changelog/<version>-<slug>.md`;
  - updates `docs/reference/data-access.md` (its own row or "Not governed" line);
  - regenerates the copies: `tooling/sync_plugin_skills.py`, `tooling/index_build.py`,
    `tooling/changelog_index.py`, `tooling/version_sync.py`, then the command
    `gates/scaffold_freshness_guard.py` prints.
- No key-shaped strings in tests, even fakes. gitleaks scans every PR commit (`sk-or-v1-x` is fine).
- TDD with a red witness and at least one named mutation per behaviour. Rewritten tests are named
  in the PR.
- Tasks run **one at a time**, in the order below. `VERSION`, the changelog index and
  `data-access.md` conflict on every concurrent PR.

## Review focus

These are inputs no task's happy path exercises. Each is pinned by a test in the owning task.

1. **Proxy env set but empty, or `NO_PROXY` covering loopback.** Expect: loopback never goes
   through a proxy, and an empty `HTTPS_PROXY` means "no proxy", not a crash. Owner: T1.
2. **Allowlist entry with a trailing dot, upper case, a port or a wildcard.** Expect: exact,
   case-insensitive host match; port-insensitive unless the entry names a port; no wildcards; a
   malformed entry locks. Owner: T1.
3. **`AI_BADGER_PROJECT_ID` naming a locked project while cwd is unlocked.** Expect: refused.
   Owner: T1.
4. **Injected turns that look like user prompts.** A task notification, a subagent hand-back or
   a cross-session message (`<task-notification>`, `[Subagent hand-back]`,
   `<cross-session-message`) is skipped. A user prompt that merely *quotes* one of those markers
   mid-text is not. Owner: T2.
5. **feed-badger in a locked project with an explicit override.** Expect: refusal unless the
   operator passes the documented flag, with a message naming the lock's config path. Owner: T5.

---

### Task T1: `aib-egress-proxy-allowlist-project-binding` (high loop)

Covers follow-ups 1 (HTTPS_PROXY / DLP), 10 (host allowlist for company-cloud deciders) and 11
(`AI_BADGER_PROJECT_ID` vs the lock's cwd). All three change the same predicate and transport, so
they are one task.

**Files:**
- Modify: `features/common/skills/ai-raccoon-memory/scripts/openrouter_client.py`
  (`make_opener`, `egress_allowed`, `lock_reason` / `project_locked`, new allowlist reader), plus
  its vendored twin.
- Modify: `features/common/skills/ai-raccoon-memory/scripts/memory_context.py`
  (`pipeline_for`, `_project_id`). Bind the lock check to the resolved project root when the
  project id comes from the env.
- Modify: `schemas/config.schema.json`. `dataPolicy` widens from the string `"local-only"` to
  also accept an object `{"mode": "local-only", "allowHosts": ["decider.corp.example"]}`. The
  string form stays valid.
- Modify: `features/common/skills/task-decomposition/scripts/jev_choice.py`, only if
  `endpoint_target` needs the allowlist (it calls `egress_allowed`, so it should not).
- Test: `tests/test_memory_context_egress.py`, `tests/test_config_data_policy.py`,
  `tests/test_memory_context_pipeline_wiring.py`, `tests/test_memory_context_openrouter.py`.
- Docs: ADR-0035 (amends ADR-0034 D1/D2), `docs/reference/data-access.md`, the changelog.

**Interfaces:**
- **Produces:** `egress_allowed(url, env, cwd, *, project_root=None) -> bool`. The semantics:
  - loopback → True;
  - else, under a lock, the host must be in the union of every locking config's `allowHosts`
    (exact, case-insensitive, trailing dot stripped, https only);
  - else `AI_BADGER_ALLOW_THIRD_PARTY == "1"`.
- **Produces:** `allowed_hosts(cwd) -> frozenset[str]`. `lock_reason(cwd)` is unchanged.
- **Produces:** `make_opener(call)` honours `HTTPS_PROXY` / `https_proxy` and `NO_PROXY`
  (`urllib.request.getproxies()` plus `proxy_bypass`) for non-loopback hosts only. Loopback is
  always direct. The env must be passed explicitly so tests can scrub it.
- **Consumed by:** T3 (local scorer endpoint), T7 (the TypeScript mirror).

**Acceptance criteria:**
- [ ] With `HTTPS_PROXY=http://127.0.0.1:<capture>`, an opted-in POST to a non-loopback test
  host goes through the capture proxy as `CONNECT host:443`. Without the variable it dials
  directly. RED witness: today the proxy sees nothing. Mutation: `ProxyHandler({})` restored →
  red.
- [ ] A loopback POST never goes through the proxy, even with `HTTPS_PROXY` set. Mutation: proxy
  applied to all hosts → red.
- [ ] Locked project with `allowHosts: ["decider.corp.example"]`:
  - a custom Jev endpoint `https://decider.corp.example/v1/systemone` resolves without
    `AI_BADGER_ALLOW_THIRD_PARTY`;
  - `https://openrouter.ai` stays refused even with the opt-in.

  Mutations: allowlist ignored → red; allowlist matched by suffix (`evil-decider.corp.example`) → red.
- [ ] Every Review-focus 2 variant has a test.
- [ ] `AI_BADGER_PROJECT_ID` pointing at a project whose root holds a lock refuses the pipeline
  even when cwd is unlocked. Mutation: lock read from cwd only → red.
- [ ] `memory_context.ENV_NAMES` gains the proxy variables the client reads. The transport AST
  test stays green.
- [ ] Gates:
  - `pytest tests/test_memory_context_*.py tests/test_jev_*.py tests/test_config_data_policy.py tests/test_scaffold_config_version.py`;
  - pylint 10.00 on the changed modules;
  - the freshness and docs guards.

---

### Task T2: `aib-memory-hook-skips-injected-turns` (low loop)

Covers follow-up 8.

**Files:**
- Modify: `features/common/skills/ai-raccoon-memory/scripts/memory_context.py` (`should_enrich`,
  which returns `Decision`).
- Test: `tests/test_memory_context_core.py`. Add a fixture file
  `tests/fixtures/memory_context/injected_turns.json` with real shapes copied from a session
  transcript, redacted.
- Docs: `features/common/skills/ai-raccoon-memory/SKILL.md` (gate section), the changelog.

**Interfaces:**
- **Produces:** `should_enrich(prompt)` returns `Decision(enrich=False, reason="injected-turn")`
  when the prompt **starts** (after leading whitespace) with one of
  `<task-notification>`, `<cross-session-message`, `[Cross-session idle notice]`,
  `[SYSTEM NOTIFICATION`, or the `Another Claude session sent a message:` /
  `[Subagent hand-back]` preambles.
- Define the markers once, as a module tuple `INJECTED_PREFIXES`, and reference that tuple from
  the test. The tuple is not copied into the test.

**Acceptance criteria:**
- [ ] Each fixture shape is skipped. RED: today they enrich.
- [ ] A user prompt containing a marker mid-text still enriches (Review focus 4). Mutation:
  `startswith` → `in` → red.
- [ ] A prefix check that is case-sensitive or space-sensitive is pinned by a fixture row with
  leading newlines.
- [ ] Gates: `pytest tests/test_memory_context_*.py`; pylint; guards.

---

### Task T2b: `aib-injected-turn-predicate-shared` (low loop)

Found in T2's review: two more readers of user prompts still treat harness-injected turns as typed.

**Files:**
- Modify: `features/common/skills/mcp-index/scripts/context_enrichment_hook.py`. Load
  `memory_context.py` from the sibling `ai-raccoon-memory` skill (same `skills/<name>/scripts/`
  layout in the framework and in consumers). Skip an injected turn before any ranking or
  telemetry, and rank the text after leading `<system-reminder>` blocks. When the sibling is
  absent, behave as today.
- Modify: `tooling/fixture_harvest.py`. `is_machine_shaped` also drops what
  `memory_context.injected_turn` drops. The broad markup regex stays.
- Test: `tests/test_context_enrichment_hook*.py`, `tests/test_fixture_harvest.py`, both driven by
  `tests/fixtures/memory_context/injected_turns.json`.

**Interfaces:**
- **Consumes:** `memory_context.injected_turn(prompt) -> bool` and
  `memory_context.without_reminders(prompt) -> str`. There is no second marker list.

**Acceptance criteria:**
- [ ] Every fixture row recommends nothing and writes no query telemetry. RED: today it ranks.
- [ ] A reminder-prefixed real prompt is ranked on the text after the reminder.
- [ ] Without the sibling skill the hook still ranks: a fallback, not a crash.
- [ ] fixture_harvest drops the four plain-text shapes the regex misses. RED: today it keeps them.
- [ ] Gates: the touched suites; pylint; guards.

---

### Task T3: `aib-local-decider-memory-scoring` (high loop)

Covers follow-up 3. Depends on T1 (allowlist and proxy semantics for a company-cloud scorer).

**Phase A, verification. It must succeed before any code changes.**
1. Run `decider.serve` (`Mapika/decider-2b`, pinned revision and sha256) on loopback via a PEP
   723 `uv run --script tooling/decider_smoke.py`.
2. Run `jev_choice.py <fixture-plan> --both --json` with
   `AI_BADGER_JEV_ENDPOINT=http://127.0.0.1:<port>/v1/systemone`.
3. Record the answer shape, latency p50/p95 and any parser rejects in a research record.

Stop the task and report if the wire is incompatible. Do not adapt the parser to a model.

**Phase B, wiring.**
- **Files:**
  - `features/common/skills/ai-raccoon-memory/scripts/query_pipeline.py`: the score stage takes
    an injected `decisions_url`/`key`;
  - `memory_context.py`, `pipeline_for`: when `AI_BADGER_MEMORY_CONTEXT_SCORER` is set to a
    loopback or allowlisted URL, build a pipeline whose planner is **off** (single search) and
    whose scorer is the local endpoint.
- **New behaviour:** a "local pipeline" mode. One search on the prompt, then local Jev-wire
  scoring of the pooled hits, then pi's merge. No OpenRouter key required.
- **Optional reranker path:** `AI_BADGER_MEMORY_CONTEXT_RERANK_URL` (TEI `/rerank`), with
  scores mapped to 0–3 by fixed cut points. Only if Phase A finds the decider too slow for the
  8 s score stage on CPU.
- **Eval:** add `tests/fixtures/memory_context/relevance_pairs.json`, about 30
  prompt→relevant-doc pairs from this repo's bank. A gated eval script compares nDCG@5 for plain
  search against local scoring. Report the numbers; a regression blocks enabling by default, but
  the opt-in may still ship.

**Acceptance criteria:**
- [ ] Phase A record committed, with real measured numbers (never a planning agent's).
- [ ] With a loopback scorer and no OpenRouter key, `build()` produces a merged block. The fake
  scorer server records exactly one decisions POST per batch, and `net_attempts == []` for
  non-loopback hosts.
- [ ] With the scorer unset, behaviour is byte-identical to 0.185.0: the existing goldens in
  `tests/fixtures/memory_context/pipeline_goldens.json` pass unchanged.
- [ ] Gates: memory_context suites, pylint, guards; the nDCG eval output pasted in the PR.

---

### Task T4: `aib-registry-provider-neutral-model-ids` (high loop)

Covers follow-up 2.

**Files:**
- Modify:
  - `schemas/model-groups.schema.json:46`;
  - `features/common/skills/task/scripts/model_groups.py:25`;
  - `features/common/data/model-groups.json` (format only, not the pins);
  - `features/pi/adjustments/adjust_agents.py:30-34,119-127`;
  - `features/common/skills/ai-raccoon-memory/scripts/query_pipeline.py:373-383`, the planner id
    `removeprefix`.
- Test: the existing model-groups validator tests (find them with
  `grep -l model_groups tests/`), `tests/test_pi_adjustments.py`.

**Interfaces:**
- **Produces:** the id grammar `^<provider>/<vendor>/<name>$`, where `<provider>` is one of
  `openrouter`, `anthropic`, `bedrock`, `vertex`, `azure`, `local`.
- **Produces:** `model_groups.resolve(level, *, providers=None)`. It skips ids whose provider is
  not in `providers`.
- **Produces:** a project config `modelProviders: [..]` (schema), passed through to pi delivery.
  Under a `dataPolicy` lock with no `modelProviders`, pi `level:` routing strips third-party
  `openrouter/*` pins (and logs a scaffold note) instead of routing a client task to OpenRouter.

**Acceptance criteria:**
- [ ] `anthropic/anthropic/claude-sonnet-5` validates. `foo/bar` (two segments) is refused.
  Mutation: the old regex → red.
- [ ] A locked project's `.pi/agents/*.md` carries no `openrouter/` model pin after scaffold.
  RED: today it does.
- [ ] Unlocked projects scaffold byte-identically to before. The freshness guard proves this on
  this repo.
- [ ] Gates: the registry, pi adjustment and scaffold suites; guards.

---

### Task T5: `aib-feed-badger-client-data-guard` (low loop)

Covers follow-up 4.

**Files:**
- Modify: `features/common/skills/feed-badger/scripts/open_pr.py`. Before `git push` (`:240`),
  call `openrouter_client`-equivalent lock logic. Do **not** import across skills; copy the
  ~25-line `lock_reason` walk into a `feed_badger_policy.py` sibling, and add a twin-equality
  test against the client's function on a shared matrix.
- Modify: `features/common/skills/feed-badger/SKILL.md`. In a locked project, contributing back
  needs `--allow-locked-project`.
- Test: new `tests/test_feed_badger_lock.py`.

**Acceptance criteria:**
- [ ] In a tmp project with `dataPolicy`, `open_pr.py` exits non-zero before any `git push`/`gh`
  subprocess, and the error names the config path. A subprocess spy is empty. RED: today it
  pushes.
- [ ] `--allow-locked-project` proceeds (spy sees the push), and the PR body gains a line
  "contributed from a dataPolicy-locked project". Review focus 5.
- [ ] Twin test: `feed_badger_policy.lock_reason` == `openrouter_client.lock_reason` on the
  egress matrix's configs. Mutation: drift one branch → red.
- [ ] Gates: the new suite plus the existing feed-badger tests; guards.

---

### Task T6: `aib-archify-and-agent-text-egress` (low loop)

Covers follow-ups 5 (archify Google Fonts and update check) and 6 (third-party providers in
pi/Hermes text, "search externally").

**Files:**
- **archify is vendored** (`tooling/vendor_archify.py --check` sha-pins every file). Do not edit
  `features/common/skills/archify/**` by hand. Instead:
  - **Update check.** Add a scaffold adjustment, or an extension of the SKILL.md adaptation step
    in `vendor_archify.py`, so the adapted SKILL.md says "skip the update check when the project
    config has `dataPolicy`". Have archify's own `ARCHIFY_UPDATE_CHECK_DISABLED=1` set in the
    scaffolded hook env for locked projects, if a hook env surface exists. The task's research
    decides which.
  - **Google Fonts.** Font loading is an archify concern. Open an upstream issue or PR against
    archify for a system-font fallback flag. Here, document the font request as viewer-side and
    metadata-only in `data-access.md`. No local patch to a vendored file.
- Modify:
  - `features/pi/instructions/pi.instructions.md:52`;
  - `features/pi/stack.json:3`, `features/hermes/stack.json:3`: neutral wording ("any provider
    the operator configures").
  - `features/common/mcp/ai-raccoon/server.md:4-7` and
    `features/common/skills/ai-raccoon-memory/SKILL.md:50`: "no hit means search externally"
    becomes "…search externally with the host's own approved tools; in a `dataPolicy`-locked
    project, ask before searching the web".
- Test: the existing pin or instruction tests that assert these strings (find them with
  `grep -rn "OpenRouter, Anthropic" tests/`). Add a test that no `features/**/instructions/*.md`
  or `stack.json` description names a specific third-party provider list. The test is derived:
  a regex over the files, not a hand list of files.

**Acceptance criteria:**
- [ ] `vendor_archify.py --check` still passes. The adapted SKILL.md carries the locked-project
  rule.
- [ ] The provider-neutral text test is red first.
- [ ] The upstream archify issue or PR URL is recorded in the changelog.
- [ ] Gates: the vendor check, skill docs and catalog claims tests; guards.

---

### Task T7: `pbi-honour-ai-badger-egress-rule` (high loop, **repo `pi-badger-integration`**)

Covers follow-up 7. Depends on T1 (mirror the final rule, allowlist included). Run `/task` from
`/Users/arasz/RiderProjects/pi-badger-integration` (alias `pbi`; confirm via its config).

**Files** (confirm in that repo):
- `extensions/decision-router/decision-router-client.ts` / `jev-client.ts`;
- the `mem-based-rag` and `query-pipeline` extensions.

**Interfaces:**
- **Consumes:** the T1 rule as specified in ADR-0034 and ADR-0035: env
  `AI_BADGER_ALLOW_THIRD_PARTY`, any-ancestor `dataPolicy` (string or object form with
  `allowHosts`), loopback always allowed.
- **Produces:** one TS `egressAllowed(url, env, cwd)`, plus a cross-language conformance fixture
  `egress_matrix.json`. The ai-badger repo exports it from T1's test matrix, and pbi's tests read
  the same file, so the two implementations cannot drift silently.

**Acceptance criteria:**
- [ ] pi's planner and Jev calls to OpenRouter are refused by default. RED first.
- [ ] The conformance matrix passes in both repos.
- [ ] Shadow-mode routers stay shadow.

---

### Task T8: `aib-mcp-binary-egress-audit` (low loop, research-led)

Covers follow-up 9.

**Scope:** an evidence-first audit (`evidence-first-research` skill) of the network behaviour of
the following. ai-raccoon is out of scope because it is local and approved (see Global
constraints).
- semantica;
- code-review-graph (embedding model downloads);
- Playwright MCP (`npx -y @playwright/mcp@latest`, unpinned).

Method: read each binary's source or docs, and run each under a network-deny sandbox
(`sandbox-exec` on macOS) with a loopback capture to see what it attempts.

**Files:**
- Create: `docs/work/<date>-mcp-binary-egress-audit.md` (research record).
- Modify: `features/common/stack-mcp.json:38`. Pin `@playwright/mcp` to an exact version.
- Modify: `docs/reference/data-access.md` (rows per binary).
- Add `config.mcp.decline` guidance for locked projects.

**Acceptance criteria:**
- [ ] Each binary has a MEASURED row (sandboxed run) or an explicit UNVERIFIED with a reason.
- [ ] Playwright is pinned. The scaffold test asserting the command string is updated, and red
  first.
- [ ] Any binary found phoning home by default gets either a scaffolded opt-out env in the MCP
  declaration or a "Not governed" entry naming it.
- [ ] Gates: MCP scaffold tests; guards.

---

## Order and dependencies

| Order | Task | Loop | Depends on | Why this position |
|---|---|---|---|---|
| 1 | T1 egress proxy + allowlist + project binding | high | — | Corporate DLP blocker; defines the rule T3 and T7 consume |
| 2 | T2 skip injected turns | low | T1 (same file) | Cheap, stops needless per-turn work and surprise egress |
| 2b | T2b share the injected-turn predicate | low | T2 | Review follow-up; the MCP recommender and fixture harvest reuse it |
| 3 | T5 feed-badger guard | low | — | The one on-demand path to a **public** repo |
| 4 | T6 archify + agent text | low | — | Text and vendoring; independent |
| 5 | T4 provider-neutral registry | high | — | pi-only, larger blast radius (scaffold output) |
| 6 | T8 MCP binary audit | low | — | Research-led; may spawn its own follow-ups |
| 7 | T3 local decider scoring | high | T1 | Needs a live model run; longest |
| 8 | T7 pi-badger-integration mirror | high | T1 | Other repo; mirrors the final rule |

Before T1 starts, PR #549 (0.185.0) must be merged. Every task branches from the `origin/main`
that includes it.
