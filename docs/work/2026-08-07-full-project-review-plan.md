# Full-project review — the integrated plan

One plan built from seven expert reports plus the orchestrator's own findings. Charter:
`2026-08-07-full-project-review-charter.md`. Evidence per finding:
`2026-08-07-full-project-review-findings.md`.

Base: `main` at `6a3d9e5`. Panel: E1 architecture, E2 dotnet catalog, E3 this week's diff,
E4 test honesty, E5 docs, E6 hooks/gates/CI, E7 catalog integrity.

## The one sentence

ai-badger's gates are extensive, fast-growing, and a surprising number of them do not gate: the
plugin-sync check grades its own homework, the shape assertion stops one directory deep, the
skills lint validated a string no YAML parser reads, `--risk` and the secret scanner and the two
`.mjs` validators are wired to nothing, and the freshness guard writes into `$HOME`. The catalog
those gates protect shipped a real vault identifier and one private project's business rules to
every .NET consumer. Nothing here is a crisis of code quality — the code is good — it is a crisis
of **verification**, which is the harder thing to notice, because everything is green.

## What the week actually shipped

93 commits, 646 files, +51,883/−4,128, releases 0.62.0 → 0.87.1 in seven days. Measured, not
inferred. That pace is the context for every finding below: three of the four highest-severity
defects were introduced *by gates added this week*, and the fourth by the harvest they were added
to police.

## Already shipped from this review

| PR | What | Gate evidence |
|---|---|---|
| #326 | Vault identifiers purged; standing check for UUID/credential shapes across `features/` | 12 lanes, 497s; could-fail tests use the two identifiers 0.86.0 shipped |
| #327 | AWM denylist normalises before matching; unreadable arguments to destructive verbs denied | RED 9/20 → GREEN 108; 12 lanes, 536s |
| #328 | `skills_lint` rule 11 rejects duplicate frontmatter keys; 20 SKILL.md deduped | RED naming 20 files → GREEN 24; rule-11 mutant verified RED |

Also done: the operator's Hermes plugin was repaired (`frameworkRoot` repointed from a deleted
temp directory to the real checkout, verified `exists: True`).

**Still owed and not doable from here: rotate the Bitwarden secret.** #326 removes the pointer; it
cannot un-publish it.

## Theme A — Gates that do not gate

The through-line of the review. Each item is a check that exists, runs, reports success, and
cannot fail for the reason it was written.

| ID | Finding | Severity | Source |
|---|---|---|---|
| A1 | `check_skill` builds its expected value with the same `render_into` it is checking; a renderer bug is green by construction. Proved: point `PLUGIN_EXTRA_FILES` at a missing source and `--check` still prints "15 skill(s) in sync" while the shipped `task` skill loses its session source | HIGH | E3 F-2 |
| A2 | The shape assertion added in #325 uses `iterdir()`, so `scripts/tests/payload.py` is invisible to both the hash and the shape check. 20 nested directories exist in the shipped tree | HIGH | E3 F-3 |
| A3 | The shape loop can be **deleted from `check_all()` with 134 tests green** — its only test's fixture also trips `check_skill`, so the `1` comes from the content path. None of the 7 excluded patterns is exercised | HIGH | E4 F1 |
| A4 | `tooling/validate.py` is invisible to `test_every_check_can_fail` (discovery matches `--check`, not `--all`), and out of mutmut's 418-LOC scope. Five CI-enforced sub-checks sit in that blind spot | HIGH | E4 F2 |
| A5 | 8 of 26 `skills_lint` mutants survive. Rule 1's length cap, rule 5's word "when", and rule 9's note-only path have **no test that can fail**. The lint's file scope is unpinned — narrowing the glob leaves 22 tests green while 15 of 51 skills go unlinted | HIGH | E4 F3 |
| A6 | `gitleaks` is **not a required check**. PR #325 merged with it red; the workflow comment claims "the gate blocks from its first run" | HIGH | E6 F4 |
| A7 | The two `.mjs` agent-instruction validators run in **no** gate — only their tests do. The skill's description advertises "when validation/drift checks fail in CI"; there is no such check | HIGH | E6 F5 |
| A8 | `--risk` is parsed, persisted and printed, and consumed by nothing. Zero references in `gates/`, `tooling/`, workflows, `.lefthook/`. An operator trading coverage for speed gets neither | MED | E3 F-6 |
| A9 | The hook-coverage gate reports only when gaps are non-empty; an empty root and a corrupt manifest both yield silence — the defect class the gate was written to catch | MED | E3 F-7 |
| A10 | `validate.py` validates `model.schema.json` against a glob matching **zero** files while claiming to validate | MED | E7 #5 |
| A11 | `bl.SIBLING_REFERENCE_RE` has zero callers; the guard keeps a diverged copy that scans only `SKILL.md` and misses 15 of 152 reference filenames | MED | E3 F-5 |
| A12 | Rule 8's only exemption is keyed to `scaffold-documentation:84`, a line that is now blank. The corpus is green by luck | MED | E3 F-4 |
| A13 | Nothing checks that the catalog and its own documentation agree — `docs/skills.md` documents 23 of 37 skills | HIGH | E5 F1 |
| A14 | `docs/work/README.md` gets no automated staleness check, unlike `docs/changelog/README.md`. Two indexed files never merged | MED | E5 F2 |
| A15 | The project's own `ai-raccoon` bank is empty and watching was never enabled, while four releases of memory-first enforcement point every agent at it | HIGH | orchestrator O-1 |
| A16 | 21 JSON catalog files under `features/` are unschema'd, including `hooks.json`, which feeds `.claude/settings.json` | MED | E7 #4 |
| A17 | `shape_violations`' missing-destination early return is unverified — the exact state of a newly added skill | LOW | E4 F7 |

## Theme B — Automation that damages, misleads, or hides

| ID | Finding | Severity | Source |
|---|---|---|---|
| B1 | **`gates/scaffold_freshness_guard.py`, a read-only gate, writes into `$HOME`.** It re-scaffolds into a temp dir; `adjust_hooks._install_user_plugins` hardcodes `~/.hermes/plugins` with no `--target` derivation and no `--no-install` gate, overwrites the operator's plugin, and records the temp dir as `frameworkRoot`. Runs in pre-commit, pre-push and CI | CRITICAL | E6 F1 |
| B2 | `ai_badger_hooks.py:156-159` discards the resulting `RuntimeError`'s actionable message with zero output. The plugin loads, registers four hooks, and silently does nothing | HIGH | E6 F6 |
| B3 | **The guard's printed remediation command is not the command the guard runs.** Following it verbatim drops `hermes` and `ai-raccoon` from `.github/mcp.json`, because the guard sets `AI_BADGER_MCP_AVAILABILITY=all` internally and the printed command omits it. The guard then rejects the tree its own instructions produced | HIGH | orchestrator, reproduced twice |
| B4 | The pre-push chain runs 8–10 minutes against a comment claiming 75s. Measured three times today: 497s, 536s, and pytest alone at 608s. **Peak RSS 96 MB, so the recorded SIGKILL is wall-clock, not memory** — which retires the OOM hypothesis and reframes the fix | HIGH | E6 F3 + correction |
| B5 | `tests/test_verify_gate.py` writes a sentinel into the **real** cited log directory and never restores it, so a developer following a failure's `logs:` path reads a test fixture. This blocked E6's own lane-timing measurement | MED | E6 F9 |
| B6 | `logs/lefthook.log` is not redirectable, so test runs append real-looking PASS/FAIL rows no push produced | MED | E6 F10 |
| B7 | 241 hook exceptions silently swallowed into `~/.ai-badger/hook-errors.log`, unread by anything. Entries name test files, confirming the suite writes into the operator's real HOME | MED | E6 F11 |
| B8 | Sibling-module loaders fail open on a **corrupt** module, not just an absent one — a syntax error in `memory_first_gate.py` silently disables enforcement | MED | E6 F12 |
| B9 | `memory_first_gate.project_id` is the **cwd basename**, not the repo, so every worktree session is aimed at a bank that cannot exist. Worktree-per-task is this project's standard workflow | HIGH | E6 F2 |
| B10 | The drift notice and the freshness guard disagree on what drift means: the guard tolerates stamp-only diffs by design, the notice fires on every patch release with nothing to do | MED | E6 F8, E7 #11 |
| B11 | Repo-structure tests read the **live working tree** during a 10+ minute suite, so any concurrent write turns them red for an unrelated reason. Observed live in this session | MED | E4 F4, E3 F-9 |
| B12 | `task_tracker.py` resolves its state directory from cwd while the skill orders all work into the worktree. **Eleven consecutive tasks recorded `tokens=0`**; the skill's own grading criterion has been unmeasurable since 0.69.0 | HIGH | orchestrator O-5 |
| B13 | Six tracker entries stuck `IN_PROGRESS` since 1–5 August, none owning a worktree, with no open PRs or issues | LOW | orchestrator O-3 |
| B14 | `scaffold.py` writes `.claude/settings.json` twice per run, stamping a `.bak-*` even on a fresh target — no two scaffolds are byte-identical | LOW | E7 #10 |
| B15 | `superseded_prune` exempts `templates`/`hooks`/`adjustments` from pruning as a side effect of a drift-reporting flag, so any renamed destination is permanently orphaned. One live orphan since v0.1.0 | MED | E7 #3 |
| B16 | ReDoS in both `.mjs` validators: `^(a+)+$` under the 500-char cap hangs until SIGKILL. `0.25.0`'s changelog claims this was fixed | MED | E6 F7 |

## Theme C — The harvest shipped unreviewed content to consumers

`features/dotnet/` auto-installs on any repo containing a `.csproj` — no opt-in. Leakage severity
here is distribution-weighted, and instruction files outrank skills for blast radius because they
are always-on.

| ID | Finding | Severity | Source |
|---|---|---|---|
| C1 | ~~Live Bitwarden project + secret identifiers~~ | ~~CRITICAL~~ | **shipped, #326** |
| C2 | `csharp.instructions.md` (`applyTo: '**/*.cs'`, always-on) lines 15-18 impose one app's business rules on every consumer: a specific state-machine design, `409`/`202` HTTP contracts, and mandatory multi-tenancy. Line 18 also duplicates a `features/cosmos/` invariant that is correctly stack-gated, leaking it into the ungated layer | HIGH | E2 #2 |
| C3 | `dotnet-domain-modeling/references/` is substantially another company's source tree — `JobSearchAiAssistant.*` namespaces, "when adding a new entity to **this project**", ATS domains, LinkedIn sender addresses, tuned confidence thresholds. Four files are orphans: present, referenced from no SKILL.md, shipped and unreachable | HIGH | E2 #5 |
| C4 | The redaction pass was find/replace and broke: `class the config dispatcher`, `interface the encryption command interface`, `~/RiderProjects/ai-raccon/the project`, `the the MCP server`. Independently confirmed — 19 hits across 8 files | MED | E2 #6 |
| C5 | A reference recommends upgrading FluentAssertions 6→8 with no license note. v8 moved to the Xceed Community License at **$130/developer/year**; v7 is the last free version. (FluentValidation is unaffected — still Apache 2.0. Do not conflate them) | MED | E2 #4 |
| C6 | `csharp.instructions.md:17` prescribes RFC 7807, obsoleted by **RFC 9457** in 2023; current Microsoft guidance has moved | MED | E2 #3 |
| C7 | Two skills instruct deleting constructor guards because "NRT + DI guarantee non-null", contradicting `features/common/invariants/guard-clauses.md` without citing it. The premise is wrong — NRT is compile-time advisory and does not stop null from deserialization or reflection | MED | E2 #7 |
| C8 | `features/dotnet` declares `"requires": []` but treats Cosmos DB and Durable Functions as defaults, and its persona refers readers to `cloud-infra-engineer`, which lives in `features/azure/` and will not exist in a dotnet-only scaffold | MED | E2 #10 |
| C9 | `clean-architecture-layering.md` is not enforceable as written — an agent holding only it cannot decide which project is the domain layer, what counts as "framework", or what to do with no ADR process. The missing detail exists in the skill but the linkage is accidental | MED | E2 #8 |
| C10 | `.NET 11` changed the hosted-service failure contract (`RunAsync`/`StopAsync` now throw); the review checklist does not say so | LOW | E2 #11 |
| C11 | Mainstream .NET is absent: **EF Core, minimal APIs, DI lifetimes, Options/configuration, authn/authz, HttpClientFactory, async correctness, AOT/trimming.** Heavy SQLCipher/Cosmos/MCP coverage instead — the fingerprint of the source project, not the ecosystem | MED | E2 #12 |
| C12 | Three dangling skill-name references that no rule catches; one `references/` file about C# string interpolation filed under `worktree-agent-isolation` | LOW | E7 #6, #9 |
| C13 | `mcp-stdio-probe.py` (91 LOC) has zero tests, and its hyphenated filename makes it un-importable | LOW | E4 §5 |
| C14 | `features/github` is a one-file shell stack, absent from `index.json.stacks`, yet selected by this repo's own config and advertised in `CLAUDE.md` | HIGH | E7 #2 |

## Theme D — Architecture and refactor

E1's ranking, preserved. Note E1 argued **against** the largest item until the cheapest one lands.

| ID | Item | Severity | Note |
|---|---|---|---|
| D1 | Lazy-import `jsonschema` — ~470 ms of `badger_lib`'s ~500 ms import, paid by 11 of 13 entry points that never validate, on every pre-push run. ~5 lines. **Must still raise, never degrade** | HIGH | E1 F2 |
| D2 | Supersede ADR-0005: its stated revisit condition ("if anything else ever needs frontmatter at build time") fired this week. `SKILL_SCOPES` (39 hand-kept entries) and a `too-many-lines` disable both serve a lapsed premise | HIGH | E1 F1 |
| D3 | Decide the retrieval eval: **672 LOC wired into no lane**. ADR-0012 ratified "a falsifiable eval"; it has never run against the real corpus. Wire it with a threshold, or delete `fixture_harvest.py` and call it a manual tool | MED | E1 F10 |
| D4 | Extract `skills_lint` from `validate.py` into `gates/` — it is a repo gate living in a schema validator, +187 lines in one commit, parsing the same file three ways | MED | E1 F3 |
| D5 | One `Problem` + `report()` for the gates; the copy-pasted shape has already drifted so `deps_guard` prints `path:0` | MED | E1 F6 |
| D6 | One frontmatter extractor returning `(fields, body)` — currently four | MED | E1 F9 |
| D7 | Guarded `read_version`; two of eight readers raise `FileNotFoundError` where six degrade | MED | E1 F8 |
| D8 | PreToolUse guard refusing edits under the derived trees, pointing at `features/` — enforcement moves from push-time to edit-time | MED | E1 F5 |
| D9 | Split `badger_lib` on its four seams — **conditional on D1 and D2 landing first and the file still sprawling.** Touches 13 import sites | LOW | E1 F4 |
| D10 | Split the doc-budget checker out of `tracker_lib`, and cron out of `task_tracker` — **blocked on an owner ruling** on what "lockstep with the originating repo" obligates | BLOCKED | E1 F11, F12 |

**Do not "fix":** the 12× `--root` idiom, the 13× sys.path bootstrap, and the five identical
`debug_log.py` copies are ratified at `pyproject.toml:23-28` as a deliberate deployability
property. E1 flagged these expressly so the next reviewer does not spend a day on them.

## Theme E — Documentation truth

E1 doc drift is cheap to fix and cheap to re-break; the gate work in A13/A14 is what makes it stick.

| ID | Item | Source |
|---|---|---|
| E1d | Document the 14 missing skills; fix the self-contradicting count. Better: generate the table from `SKILL_SCOPES` | E5 F1 |
| E2d | Resolve the two dangling `docs/work/README.md` rows — delete, or restore from `feat/memory-first-gate` | E5 F2 |
| E3d | `docs/plans/memory-grade-hook.md` still says `Status: proposed` for something shipped eight releases ago, in a directory declared removed in PR #111 | E5 F3 |
| E4d | `docs/scripts.md` lists 6 of 8 `tooling/` scripts | E5 F4 |
| E5d | ADR-0016's body says 0.83.0; its README row says 0.82.0 | E3 |

## Work items, chunked

Each item names its acceptance criteria and the gate that proves them. Chunks are the unit of
dispatch; an item without chunks is one dispatch.

### W1 — Stop the freshness guard writing to `$HOME` `[CRITICAL]`
- **W1.a** Derive the Hermes plugin install root from an env-overridable base; make
  `_install_user_plugins` a no-op under `--no-install`; have the guard set the lever.
- **W1.b** Print the bootstrap `RuntimeError` once to stderr before `FRAMEWORK_ROOT = None` (B2).
- **W1.c** Make the guard's printed remediation command identical to the one it runs, including
  `AI_BADGER_MCP_AVAILABILITY=all` (B3).
- **Acceptance:** a guard run with `HOME` snapshotted leaves `~/.hermes` byte-identical; an
  isolated run with no framework prints the diagnostic; copy-pasting the remediation produces a
  tree the guard then passes.
- **Gate:** new `tests/test_hermes_plugin_install.py` + a test that runs the printed command.
- **Files:** `adjust_hooks.py`, `scaffold_freshness_guard.py`, `ai_badger_hooks.py`.

### W2 — Give the plugin-sync gate an oracle `[HIGH]`
- **W2.a** `_ship_extra_files` raises on a missing declared source; independent assertion in
  `check_all` derived from the declaration, not the renderer (A1).
- **W2.b** Shape assertion compares `rglob` relative-path sets, not `iterdir` (A2).
- **W2.c** Rewrite the wiring test's fixture to leave a `__pycache__`/`.DS_Store` so `check_skill`
  returns `None` and only the shape path can fail the gate (A3); cover the missing-dest return (A17).
- **Acceptance:** renaming a `PLUGIN_EXTRA_FILES` source makes `--check` exit 1; a file at
  `skills/<n>/scripts/tests/x.py` is reported; deleting the shape loop turns a test RED.
- **Gate:** re-run E4's exact mutations — each must go RED.
- **Files:** `tooling/sync_plugin_skills.py`, `tests/test_shape_violations.py`. **W2.a/b/c serialise.**

### W3 — Make the meta-gate see every gate `[HIGH]`
- **W3.a** Extend `discovered_checks()` to `--all`; register `validate.py`'s five sub-checks with
  provocations or reasoned exemptions (A4).
- **W3.b** Close the 8 `skills_lint` survivors: rule-1 fixtures (`name-With-Caps`, >64 chars),
  rule-5 (`"Use this skill to…"`), rule-9 note-only, and ≥1 fixture under a non-`common` stack to
  pin the scope (A5). Delete the dead `-extensions` clause.
- **W3.c** Re-key `REFERENCES_EXEMPT` off line numbers (A12); fix the inert `model.schema.json`
  glob (A10); report hook-coverage and schema-coverage unconditionally (A9).
- **Acceptance:** the 26-mutant harness reports 0 survivors; an empty manifest glob is a violation.
- **Gate:** `test_every_check_has_a_provocation`, then E4's mutation harness re-run.
- **Files:** `tooling/validate.py`, `tests/test_skills_lint.py`, `tests/test_every_check_can_fail.py`.
  **W3.a/b/c serialise** — all touch `validate.py`.

### W4 — Enforce the gates that exist but do not block `[HIGH]`
- **W4.a** Add `gitleaks` to required status checks; drop the duplicate push/PR trigger (A6).
- **W4.b** Run both `.mjs` validators in the `validate` lane and in CI; fix the ReDoS by rejecting
  nested quantifiers or running under a worker timeout (A7, B16).
- **W4.c** Decide `--risk`: branch `verify.sh`'s lane list on the stored flag, or remove flag and
  prose together (A8).
- **Acceptance:** a seeded secret fails a PR; seeded instruction drift fails the lane; `--risk`
  either changes which lanes run or no longer exists.
- **Gate:** ruleset diff; `tests/test_every_check_can_fail.py`.
- **Files:** `.github/`, `.lefthook/pre-push/verify.sh`, `skills/task/scripts/task_tracker.py`.

### W5 — Purge the harvest's consumer-facing leakage `[HIGH]`
- **W5.a** Cut `csharp.instructions.md:15-18`; move the tenant rule to `features/cosmos/` where it
  already lives; RFC 9457 (C2, C6).
- **W5.b** De-leak `dotnet-domain-modeling/references/`: namespaces → `MyApp`, "this project" →
  generic, delete or wire the four orphans, keep the versioned-rate-table pattern and drop the
  Polish payroll specifics (C3).
- **W5.c** Repair the botched redaction across the 8 files (C4); fix the three dangling skill
  references and relocate the misfiled C# reference (C12).
- **W5.d** FluentAssertions license note; guard-clause contradiction scoped and cited; .NET 11
  hosted-service contract (C5, C7, C10).
- **Acceptance:** `grep -rn "JobSearchAiAssistant\|this project\|the the \|ai-raccon" features/`
  returns empty; no `references/` file is unreferenced.
- **Gate:** new corpus test for harvest-artifact strings and orphaned references.
- **Files:** `features/dotnet/**`. **W5.a–d are independent of each other** (different files).

### W6 — Make the catalog's claims checkable `[HIGH]`
- **W6.a** Resolve `features/github`: populate and index it, or remove it from `config.json` and
  `CLAUDE.md`. Machine-enforce config↔`index.json` stack membership (C14).
- **W6.b** Gate the dotnet stack's Azure/Cosmos assumptions via `requires`, or move that content
  (C8); condition the persona reference (C8).
- **W6.c** Schema-cover `hooks.json`, `mcp-tags.json` and the 13 `extension.json` (A16).
- **W6.d** Make `clean-architecture-layering.md` enforceable and link the ArchUnitNET reference (C9).
- **Acceptance:** selecting an out-of-catalog stack fails validation; every JSON under `features/`
  matches a schema entry or an explicit exemption.
- **Gate:** `validate.py --all` with new rules; a test that no `features/dotnet/**` file assumes an
  undeclared stack.

### W7 — Fix the tracking and isolation floor `[HIGH]`
- **W7.a** Resolve the tracker's state dir from `git rev-parse --git-common-dir` so a worktree and
  its checkout share one store (B12). Backfill or annotate the 11 zero-token tasks.
- **W7.b** Derive `memory_first_gate`'s `project_id` from the repo, not the cwd; fix the docstring
  (B9). Enable the ai-raccoon watch and seed the bank (A15).
- **W7.c** Add a session-autouse `chdir` to the isolation floor (E4 F12); surface
  `~/.ai-badger/hook-errors.log` (B7); distinguish absent from corrupt sibling modules (B8).
- **W7.d** Close the six stale `IN_PROGRESS` tracker entries (B13).
- **Acceptance:** `task_tracker.py status` finds the task from any worktree; the gate names
  `ai-badger` from any worktree; `memory_stats` is non-zero with a healthy watch.
- **Gate:** a test registering from the checkout and reading from a worktree — must fail today.

### W8 — Make the gate chain honest about itself `[HIGH]`
- **W8.a** Restore the cited log in a `finally`; make `LOG_SUMMARY` overridable (B5, B6). **Do this
  first** — it is cheap and it restores the instrument everything else is measured with.
- **W8.b** Re-measure and correct the timing comment with a number from a run in the PR; split or
  parallelise lanes, or move the slow ones off the push path. **The mechanism is wall-clock, not
  memory — peak RSS is 96 MB, so memory tuning is not the fix** (B4).
- **W8.c** Make repo-structure tests hermetic — read `git ls-tree HEAD`, not the working tree (B11).
- **W8.d** Reconcile the drift notice with the guard's stamp tolerance (B10).
- **Acceptance:** the full suite leaves both logs unchanged; the suite stays green while `docs/` is
  written concurrently; a patch bump alone produces no drift notice.
- **Gate:** `tests/test_verify_gate.py`; a concurrent-write test.

### W9 — Documentation truth `[MED]`
- **W9.a** `docs/skills.md` — all 37 skills, count fixed, table generated from `SKILL_SCOPES`, plus
  the coverage test that makes A13 stick.
- **W9.b** The two dangling `docs/work/README.md` rows; bidirectional index check (E2d, A14).
- **W9.c** `docs/plans/` residue; `docs/scripts.md` two missing scripts; ADR-0016 version (E3d, E4d, E5d).
- **Gate:** new pytest asserting every `SKILL_SCOPES` key appears in `docs/skills.md`.

### W10 — Architecture `[MED]`
- **W10.a** D1 lazy jsonschema — **highest value-to-cost in the review.** Re-measure after.
- **W10.b** D5 shared gate `Problem`/`report()`; D7 guarded `read_version`.
- **W10.c** D6 one frontmatter extractor; then D4 extract `skills_lint` to `gates/`.
- **W10.d** D2 supersede ADR-0005 (ADR first, code only if accepted).
- **W10.e** D8 PreToolUse guard on derived trees — **demo it in anger**, per the standing rule.
- **W10.f** D3 decide the retrieval eval; D9 `badger_lib` split **only if** D1+D2 leave it sprawling.
- **Gate:** per E1's table; full suite + `sync --check` + freshness guard on anything touching
  `features/` or `skills/`.

## Parallel execution schedule

Constraint measured this session: **the concurrent-agent pool is 20 slots and the panel saturated
it** — E5 could not use its three sub-agent slots at all. Waves are sized to that, not to the
number of items.

**Wave 0 — unblock measurement (serial, one agent, do first)**
`W8.a`. Everything downstream is measured with instruments this repairs. Cheap.

**Wave 1 — five parallel lanes, no shared files**

| Lane | Items | Files touched |
|---|---|---|
| L1 | W1.a–c | `adjust_hooks.py`, `scaffold_freshness_guard.py`, `ai_badger_hooks.py` |
| L2 | W2.a→b→c *(internally serial)* | `sync_plugin_skills.py`, `test_shape_violations.py` |
| L3 | W3.a→b→c *(internally serial)* | `validate.py`, `test_skills_lint.py`, `test_every_check_can_fail.py` |
| L4 | W5.a, W5.b, W5.c, W5.d *(mutually parallel)* | `features/dotnet/**` |
| L5 | W7.a, W7.b, W7.c, W7.d *(mutually parallel)* | tracker, memory gate, conftest |

L2 and L3 must not overlap with W10.c/W10.d, which also touch `validate.py`.

**Wave 2 — after Wave 1's gates are green**

| Lane | Items |
|---|---|
| L6 | W4.a–c (CI/ruleset; needs W3 landed so the meta-gate is trustworthy) |
| L7 | W6.a–d (needs W3's validation rules) |
| L8 | W8.b–d |
| L9 | W9.a–c |
| L10 | W10.a → W10.b → W10.c (serial on `badger_lib`/`validate.py`) |

**Wave 3 — sequenced or gated on decisions**
W10.d (ADR), W10.e, W10.f, D9, D10.

**Release serialisation.** Every item bumps `VERSION` and writes a changelog entry, and all of them
collide on `VERSION`, `index.json`, `.claude-plugin/*` and `docs/changelog/README.md`. Assign
version numbers **at dispatch**, not at commit — this session lost time to exactly that when three
concurrent fixes each assumed the next patch number.

## Decisions only the owner can make

1. **Rotate the Bitwarden secret.** #326 removed the pointer; the exposure stands until rotation.
2. **History rewrite for `bfbf1be`?** One commit carries the strings; the PR is merged and the
   forge may retain the blob regardless.
3. **The retrieval eval** — wire it to a threshold, or delete 672 LOC (D3).
4. **`--risk`** — wire it or remove it (W4.c).
5. **The lockstep clause.** `task_tracker.py`, `tracker_lib.py` and `awm_gate.py` claim lockstep
   with an upstream `job-search-ai-assistant` repo. #327 already diverges deliberately. What does
   the clause oblige, and should the AWM fix be carried upstream? (D10)
6. **Allowlist vs denylist for AWM** long-term (filed by #327).
7. **`features/github`** — populate or remove (W6.a).
8. **The drift notice on a patch-only bump** — product call, not a defect (B10).
9. **Scope of `features/dotnet`.** C11 says the modal .NET consumer — ASP.NET Core + EF Core — gets
   almost nothing. Is this catalog meant to be general, or is it honestly a harvest from one
   project that others may borrow? The answer changes whether C11 is a gap or a non-goal.

## What this review did not cover

- **Order dependence is sampled, not established** — 6 of 186 test files, no randomiser installed.
- **The suite measured locally is not the suite CI measures** — CI runs Python 3.8/3.9/3.10; the
  local venv is 3.14 with pytest 9.1.1.
- The System.CommandLine "GA 2.0.10" claim needs a NuGet check, not a docs check — E2 marked it
  unverified rather than guessing.
- No runtime/performance profiling of the scaffolder beyond import cost, and no consumer-side
  testing of the catalog against a real .NET repo.
