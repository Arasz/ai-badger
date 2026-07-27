# Remediation & refactor plan — ai-badger 0.18.1

**Source review:** [`docs/reviews/2026-07-26-full-project-review.md`](../reviews/2026-07-26-full-project-review.md)
**Baseline commit:** `86457cf` · branch `task/full-project-code-review`
**Date:** 2026-07-26

## Binding constraints

These are project invariants, not preferences. Every work package below is shaped by them.

| Constraint                                     | Consequence for this plan                                                                                                                             |
|------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| **TDD is mandatory**                           | Every package names the *exact* failing test to write first, and the assertion that must fail before the fix. No package starts with production code. |
| **Small commits, early draft PR**              | Each package is one or two commits. Open the draft PR from the first commit of each wave.                                                             |
| **One PR per task**                            | Each **wave** is one PR. Packages within a wave are commits within it.                                                                                |
| **Version bump + changelog per release**       | Each wave bumps `VERSION` and adds exactly one `docs/changelog/{version}-{slug}.md`. `release_guard.py` and `version_sync.py --check` enforce it.     |
| **Guard clauses over hand-rolled null checks** | The F-02/F-04 fixes must read as guards that abort, not as `if x is None: …` ladders.                                                                 |
| **Screaming architecture**                     | Do **not** open the `scripts/` → `catalog/`/`distribution/`/`release/` rename in any of these waves. It is out of scope (see §7).                     |

## Quality gates that must stay green after every commit

```
.venv/bin/python -m pytest -q            # 691 passing at baseline; must only go up
pylint $(git ls-files '*.py' | grep -v '^tests/')   # 10.00/10 — CI scope excludes tests/
python3 scripts/index_build.py --check
python3 scripts/validate.py --all
python3 scripts/version_sync.py --check
python3 scripts/release_guard.py
```

CI matrix is **Python 3.8 / 3.9 / 3.10** (`.github/workflows/pylint.yml`). No package
may introduce `X | Y` unions, PEP-585 builtin generics in *evaluated* positions,
`match`, `functools.cache`, `str.removeprefix/suffix`, `zoneinfo`, or `graphlib`
without `from __future__ import annotations` — and never in a runtime-evaluated
expression. This is verified clean at baseline and must stay that way (see review
"Rejected claims" — the 3.8 leg is currently safe and easy to break).

---

# 1 · Wave structure

## Wave 1 — "No ai-badger command may destroy state it did not create"

One PR. Five packages. Every one is a confirmed Critical, every one has an obvious
failing test, and none requires a design decision that has not already been made in
this document.

| WP | Finding | Severity | Files owned |
|---|---|---|---|
| **WP1** | F-01 — `--dry-run` `rmtree`s before the guard; success printed unconditionally | Critical | `scripts/sync_plugin_skills.py`, `tests/test_sync_plugin_skills.py` *(new)* |
| **WP2** | F-02 — unparseable settings file treated as empty, then replaced | Critical | `features/common/skills/welcome-ai-badger/scripts/hook_wiring.py`, `.../mcp_tools.py`, `tests/test_settings_preservation.py` *(new)* |
| **WP3** | F-03 — user-scope hook execs a `cwd`-derived path the framework never creates | Critical | `features/common/hooks/mcp_index_hook.py`, `features/common/hooks/hooks-manifest.json`, `tests/test_mcp_index_hook_exec.py` *(new)* |
| **WP4** | F-04 — `install_cron` can replace the whole crontab, and runs by default | Critical | `features/common/skills/task/scripts/task_tracker.py`, `tests/test_task_tracker_cron.py` *(new)* |
| **WP5** | F-05 — secret scanner skips symlinks; the copy dereferences them | Critical | `features/common/hooks/learned_skills_sync.py`, `tests/test_learned_skills_sync.py` *(extend)* |

**Release:** `VERSION` → `0.19.0`, `docs/changelog/0.19.0-destructive-write-guards.md`.
Minor, not patch: WP4 inverts a CLI default and WP3 removes two advertised hooks.

### Why this cut line, and why these five and not others

The cut is not "the seven Criticals". It is **the subset where the failing test is
unambiguous and the fix requires no design decision.** Three Criticals are excluded
on purpose:

- **F-06 (inert install layer)** is excluded because the fix changes emitted
  commands for every user and needs a decision — does `install_skills` warn, or
  fail, when an agent has no `{name}` template? That decision belongs to the
  architect persona and to its own changelog narrative. Wave 2.
- **F-07 (`session_start_hook` unwired)** is excluded for a hard safety reason, not
  a sizing one: **wiring it arms the `poll_limit` → `run_auto_wm` self-enable chain
  that F-12 shows is currently dead only by accident.** F-12's denylist and opt-in
  gate must land first. Wave 2, ordered after WP7.
- **F-08 (managed headers)** is excluded because it is Important after verification,
  not Critical, and because its test (`assert every managed header's referenced path
  exists post-scaffold`) belongs with the other agent-file work in Wave 2.

The five that remain share one property: **each one destroys or executes something
the user owns, and each is fixable by making a guard fire earlier or by deleting
code.** That is a coherent PR a reviewer can hold in their head, and the changelog
entry writes itself.

Wave 1 diff estimate: ~120 lines of production change (mostly deletions and moved
guards) + ~350 lines of new test. Reviewable.

## Wave 2 — "Shipped features must actually be shipped"

One PR. Every finding here is a feature that is advertised and does nothing, plus
the one hardening gate that must precede the riskiest of them.

| WP       | Finding                                                                                                                                | Severity                        | Files owned                                                                                                                                                                         |
|----------|----------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **WP6**  | F-17 — add `sync_plugin_skills.py --check` + pre-commit hook + CI step + parity test                                                   | Important                       | `scripts/sync_plugin_skills.py`, `.pre-commit-config.yaml`, `.github/workflows/pylint.yml`, `tests/test_sync_plugin_skills.py`                                                      |
| **WP7**  | F-12 — auto-wm tool denylist, project-scoped state, partner-mode max lifetime, remove/gate `run_auto_wm`                               | Important **(blocker for WP8)** | `features/claude/skills/auto-wm/hooks/awm_gate.py`, `.../scripts/awm.py`, `features/common/skills/task/scripts/poll_limit.py`, `tests/test_awm_gate.py`, `tests/test_poll_limit.py` |
| **WP8**  | F-07 — wire `session_start_hook.py`; stop wiring `drift_notice_hook.py` through consumer settings                                      | Critical                        | `features/common/hooks/hooks-manifest.json`, `features/common/hooks/hooks.json`, `features/common/skills/welcome-ai-badger/scripts/hook_wiring.py`, `tests/test_scaffold.py`        |
| **WP9**  | F-06 — `{name}` install templates, warn instead of silently falling back, include `common` in the resolver's stacks, real-catalog test | Critical                        | `features/claude/plugins-instructions.json`, `features/*/plugins-instructions.json`, `scripts/install_plugins.py`, `tests/test_install_plugins.py`                                  |
| **WP10** | F-08 — managed headers reference `aibCopy`; fix the copilot template's self-reference                                                  | Important                       | `features/common/skills/welcome-ai-badger/scripts/agent_files.py`, `features/copilot/templates/copilot-instructions.md.tmpl`, `tests/test_scaffold.py`                              |

**Release:** `VERSION` → `0.20.0`, `docs/changelog/0.20.0-inert-features-activated.md`.
Minor: WP8 and WP9 both change observable behaviour for every consumer.

**Regeneration duty:** WP8, WP9, and WP10 all change `features/`, which is the source
of truth for `.ai-badger/` and `.claude/`. After WP6 lands, `--check` will *fail the
build* until `sync_plugin_skills.py` and `welcome-ai-badger` are re-run. That is the
point — but it means WP6 must be the **first** commit of Wave 2, not the last.

## Wave 3 — "A gate that cannot fail is not a gate"

One PR.

| WP       | Finding                                                                                                                                                                                                                                     | Severity  | Files owned                                                                                                                                                                                                                                          |
|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **WP11** | F-11 + F-10 — cut the missing release tag(s) or document the batching policy; make `_git` distinguish failure from empty and emit its own sentinel                                                                                          | Important | `scripts/release_guard.py`, `RELEASING.md`, `docs/adr/0001-versioning-and-release-model.md`, `tests/test_release_guard.py`                                                                                                                           |
| **WP12** | F-09 — split `find_root()` (pure lookup, raises) from `ensure_root()` (explicit, pinned, opt-in network); correct the `badger_lib` docstring; add `TestEnsureFrameworkCache`                                                                | Important | `scripts/badger_lib.py`, `tests/test_badger_lib.py`                                                                                                                                                                                                  |
| **WP13** | F-23 — hoist `tracker_lib.save_json`'s atomic write into `badger_lib`; route `dump_json`, `save_manifest`, `_write_index`, the four `mcp_tools.py` sites and `hook_wiring.py` through it; fix `load_manifest`'s silent-empty-on-parse-error | Important | `scripts/badger_lib.py`, `features/common/hooks/learned_skills_sync.py`, `features/common/skills/mcp-index/scripts/mcp_index.py`, `tests/test_badger_lib.py`, `tests/test_learned_skills_sync.py`                                                    |
| **WP14** | F-13 — one durable log line before every top-level `except Exception: pass`; raise real hook failures from DEBUG to WARNING                                                                                                                 | Important | `features/claude/skills/auto-wm/hooks/awm_gate.py`, `.../awm_context.py`, `features/common/skills/prompt-markers/scripts/user_prompt_hook.py`, `features/common/skills/task/scripts/user_prompt_hook.py`, `features/common/hooks/ai_badger_hooks.py` |
| **WP15** | F-16 — manifest-ownership guard + plain-file branch in `adjust_skills.py`; new `tests/test_adjust_skills.py` mirroring `test_scaffold.py:338-499`                                                                                           | Important | `features/copilot/adjustments/adjust_skills.py`, `tests/test_adjust_skills.py` *(new)*                                                                                                                                                               |
| **WP16** | F-24 — drive `validate_all` from the schemas directory; replace `mcp_tools.py`'s two silent `continue`s with notes; **+ F-49** (see below)                                                                                                   | Important | `scripts/validate.py`, `features/common/skills/welcome-ai-badger/scripts/mcp_tools.py`, `schemas/support.schema.json` *(new)*, `features/common/support.json`, `tests/test_validate.py`                                                              |

> **F-49 (found 2026-07-27, not in the original review).** `features/common/support.json`
> declares `"$schema": "./schemas/support.schema.json"` — a path that resolves to
> `features/common/schemas/` and, either way, names a file that **does not exist**. There is no
> support schema at all, so unlike F-24's seven uncovered files, driving `validate_all` from the
> schemas directory would still not reach it. The agent capability matrix — which decides what
> gets scaffolded for each agent — is validated by nothing. WP16 must author
> `schemas/support.schema.json`, correct the `$schema` pointer, and cover it in `validate_all`.
| **WP17** | F-25 — `manifest.json.partial` progress marker + unconditional `.ai-badger.bckp/` before re-scaffold; wrap user-scope writes so they degrade to notes                                                                                       | Important | `features/common/skills/welcome-ai-badger/scripts/scaffold.py`, `features/common/skills/den-refresh/scripts/refresh.py`, `tests/test_scaffold.py`, `tests/test_den_refresh.py`                                                                       |

**Release:** `VERSION` → `0.21.0`, `docs/changelog/0.21.0-gates-and-atomicity.md`.

## Wave 4 — Portability, correctness details, and the doc/product truth pass

One PR (or two, split at the marked line if the diff exceeds ~600 lines).

| WP                         | Finding                                                                                                                                                                                                                                                                                   | Severity             | Files owned                                                                                                                                                                                                                                                                              |
|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **WP18**                   | F-21 — require whitespace/EOS after bare `h:`/`f:`/`e:` prefixes                                                                                                                                                                                                                          | Important            | `features/common/skills/prompt-markers/scripts/user_prompt_hook.py`, `tests/test_user_prompt_hook.py`                                                                                                                                                                                    |
| **WP19**                   | F-22 — replace the `for … break` with an explicit `.mcp.json` override policy                                                                                                                                                                                                             | Important            | `features/common/skills/welcome-ai-badger/scripts/mcp_tools.py`, `tests/test_stack_mcp_servers.py`                                                                                                                                                                                       |
| **WP20**                   | F-14 + F-15 + F-20 — guard `import yaml` in `mcp_index.py`/`adjust_agents.py`; declare `platforms:` on `task/SKILL.md`; drop the hardcoded `/Users/arasz/...` default                                                                                                                     | Important            | `features/common/skills/mcp-index/scripts/mcp_index.py`, `features/copilot/adjustments/adjust_agents.py`, `features/common/skills/task/SKILL.md`, `features/common/skills/task/scripts/statusline_capture.py`, + 3 test files                                                            |
| **WP21**                   | F-26 + F-31 + F-32 — real `--execute` on `install_plugins`'s CLI (or an honest docstring); complete `scaffold.py`'s Usage synopsis; correct CLAUDE.md's "pure-stdlib 3.8+" and pin `requires-python` in `pyproject.toml`                                                                  | Suggestion→Important | `scripts/install_plugins.py`, `features/common/skills/welcome-ai-badger/scripts/scaffold.py`, `.ai-badger/CLAUDE.md` + template, `pyproject.toml`                                                                                                                                        |
| — *split here if needed* — |                                                                                                                                                                                                                                                                                           |                      |                                                                                                                                                                                                                                                                                          |
| **WP22**                   | F-18 · F-19 · F-27 · F-28 · F-29 · F-30 · F-33 · F-34 · F-35 — the whole doc-sync worklist                                                                                                                                                                                                | Important/Suggestion | `RELEASING.md`, `docs/framework-architecture.md`, `docs/ai-badger-framework-design.md`, `docs/scripts.md`, `docs/index.md`, `docs/dictionary.md`, `docs/specs/*`, `docs/design/*`, `docs/changelog/README.md`, `schemas/manifest.schema.json`, `docs/adr/` (renumber the 0002 collision) |
| **WP23**                   | F-36 · F-37 · F-38 · F-39 — agent-product quality: budget-check `HERMES.md`/`copilot-instructions.md`; show the Hermes usage hint once per session; populate `personaRouting` or render the empty case honestly; condition `python.instructions.md` on the project's real `commands.lint` | Important            | `features/common/skills/task/scripts/tracker_lib.py`, `features/common/hooks/ai_badger_hooks.py`, `.ai-badger/config.json`, `features/common/skills/welcome-ai-badger/scripts/template_rendering.py`, `features/python/instructions/`                                                    |
| **WP24**                   | F-48 + the `W0404` reimport — fix the mis-named/under-asserted test; delete two local `import json`                                                                                                                                                                                       | Suggestion           | `tests/test_mcp_index_hooks.py`, `tests/test_external_mcp_tools.py`                                                                                                                                                                                                                      |

**Release:** `VERSION` → `0.22.0` (`0.22.x` if split), changelog per PR.

## Wave 5 — Skill engineering & the JS test gap *(schedule after Wave 4; not urgent)*

| WP       | Finding                                                                                                                                                                                                                                                        | Files owned                                                                                                     |
|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| **WP25** | F-47 — a `node --test` suite for both `.mjs` scripts (built into Node ≥18, no new dependency) + a CI step                                                                                                                                                      | `features/common/skills/maintain-agent-instructions/scripts/*.test.mjs` *(new)*, `.github/workflows/pylint.yml` |
| **WP26** | F-43 · F-44 · F-45 · F-46 — `bun`→`node`; anchor `mcp-index`'s script paths and scrub its Hermes-only frontmatter; rewrite all 8 SKILL.md descriptions to lead with "Use when…"; extract the ~190 duplicated GitHub-issue-recovery lines to a shared reference | 8 `SKILL.md` files + a new shared reference                                                                     |
| **WP27** | F-40 · F-42 — author a `copilot` extension for `task` (even a short honest one); reconcile `auto-wm`'s two contradictory installation stories                                                                                                                  | `features/common/skills/task/extensions/copilot/`, `features/claude/skills/auto-wm/SKILL.md`                    |
| **WP28** | F-41 — a lightweight TDD signal: fail CI when a PR touches `scripts/`/`features/` without touching `tests/`                                                                                                                                                    | `.github/workflows/`                                                                                            |

---

# 2 · Dependency graph

```
                    ┌──────────────────────── WAVE 1 (one PR) ────────────────────────┐
    WP1 ─────┐      │  all five are file-disjoint; no ordering constraint between them │
    WP2 ─────┤      └─────────────────────────────────────────────────────────────────┘
    WP3 ─────┼──────► Wave 1 merged
    WP4 ─────┤
    WP5 ─────┘
                 │
                 ▼
    ┌───────────────────────── WAVE 2 (one PR) ─────────────────────────┐
    │  WP6 (sync --check gate)  ── MUST BE THE FIRST COMMIT OF WAVE 2    │
    │        │                                                          │
    │        ├──► WP9  (install templates)   ─┐                         │
    │        ├──► WP10 (managed headers)     ─┼─► all three regenerate  │
    │        │                                │   .ai-badger/ + .claude/│
    │        └──► WP7  (auto-wm denylist)    ─┘   under WP6's new gate  │
    │                   │                                               │
    │                   ▼  ⚠ HARD ORDER — see below                     │
    │                 WP8  (wire session_start_hook)                    │
    └───────────────────────────────────────────────────────────────────┘
                 │
                 ▼
    ┌───────────────────────── WAVE 3 (one PR) ─────────────────────────┐
    │  WP11 (release tags) ──► WP11b (harden release_guard._git)        │
    │  WP13 (atomic writes) ──► must land BEFORE WP17 (scaffold rollback)│
    │  WP12, WP14, WP15, WP16 — independent                             │
    └───────────────────────────────────────────────────────────────────┘
                 │
                 ▼
              WAVE 4  (WP18–WP24, all independent)
                 │
                 ▼
              WAVE 5  (WP25–WP28, all independent)
```

## Hard ordering constraints (violating this introduces a defect)

1. **WP7 → WP8. Non-negotiable.** F-12 established that `poll_limit.run_auto_wm()`
   shells out to `claude -p "/auto-wm away 4h"` on every limit-lift, and that
   `session_start_hook.start_poll_limit_background()` is its only launcher. That
   launcher is dead today only because `session_start_hook.py` is wired by nothing.
   **WP8 wires it.** If WP8 lands before WP7's gate, ai-badger ships a machine that
   can silently transition itself into "auto-approve every tool call for 4 hours"
   with no human present. Wave 2's PR description must state this ordering.

2. **WP6 first in Wave 2.** WP6 introduces `--check`, which fails on any
   `features/` ↔ `.claude/` divergence. WP8/WP9/WP10 all modify `features/`. Landing
   WP6 last means the gate goes green on already-synced output and proves nothing;
   landing it first means the three subsequent packages are *forced* to regenerate,
   which is the behaviour we want to lock in.

3. **WP13 → WP17.** WP17 (scaffold checkpointing/rollback) should be written against
   the atomic-write helper WP13 introduces, not against `dump_json`'s current
   non-atomic `open(…, "w")`. Doing WP17 first means writing it twice.

4. **WP11 (cut tags) → WP11b (harden `_git`).** With the tag baseline still at
   `v0.2.0`, `release_guard` structurally always passes, so no test of the hardened
   `_git` proves anything about the real gate. Cut the tag, *then* harden.

5. **F-03's fix must delete, not rename.** Do **not** "fix the filename" in WP3.
   `mcp_index_build.py` not existing is the only reason the user-scope
   exec-a-cwd-derived-path is inert. Correcting the name arms it. Delete the exec and
   the two `hooks-manifest.json` entries; re-introduce the feature behind a manifest
   hash check and explicit opt-in only if someone wants it, as its own task.

## Same-file collisions (matter for parallel agents)

| File                                                | Claimed by                                            | Resolution                                                                                                                                                                        |
|-----------------------------------------------------|-------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `scripts/sync_plugin_skills.py`                     | WP1 (Wave 1), WP6 (Wave 2)                            | Different waves. Never parallel.                                                                                                                                                  |
| `.../welcome-ai-badger/scripts/mcp_tools.py`        | WP2 (Wave 1), WP16 (Wave 3), WP19 (Wave 4)            | Different waves. Never parallel.                                                                                                                                                  |
| `.../welcome-ai-badger/scripts/hook_wiring.py`      | WP2 (Wave 1), WP8 (Wave 2), WP13 (Wave 3)             | Different waves. Never parallel.                                                                                                                                                  |
| `scripts/badger_lib.py` <br/>                            | WP12, WP13 (both Wave 3)                              | **Serialise WP12 → WP13** inside Wave 3, or give one agent both.                                                                                                                  |
| `tests/test_scaffold.py` (1151 lines)               | WP8, WP10 (Wave 2), WP17 (Wave 3)                     | WP8 and WP10 must **not** run in parallel. Assign both to one agent, or serialise.                                                                                                |
| `tests/test_sync_plugin_skills.py`                  | WP1 creates it, WP6 extends it                        | Different waves. Fine.                                                                                                                                                            |
| `features/common/hooks/hooks-manifest.json`         | WP3 (Wave 1, removes 2 entries), WP8 (Wave 2, adds 1) | Different waves. Fine.                                                                                                                                                            |
| `features/common/skills/task/scripts/poll_limit.py` | WP7 (Wave 2) only                                     | No collision.                                                                                                                                                                     |
| `.ai-badger/` and `.claude/` (generated)            | WP8, WP9, WP10, WP20, WP23, WP26                      | **Regenerated, never hand-edited.** One agent per wave runs `welcome-ai-badger` + `sync_plugin_skills.py` as the wave's *final* commit. Parallel agents must not each regenerate. |
| `VERSION`, `docs/changelog/`                        | Every wave                                            | **One commit per wave, authored last, by the arbitration agent.** Never a parallel agent's job.                                                                                   |

---

# 3 · Execution order and rationale

1. **Wave 1 first**, because it is the only wave where a defect is actively
   destroying user state on a command the docs describe as safe. Nothing in Wave 1
   depends on anything else, so it can start immediately.
2. **Wave 2 second**, because F-06 and F-07 mean the framework's two headline
   promises — "installs your skills" and "recovers your task session" — do not
   happen, and every day they stay broken is a day of user-visible dysfunction that
   no gate reports. WP7 is pulled into this wave purely as WP8's safety prerequisite.
3. **Wave 3 third**, because it is the wave that stops the next Wave 1 from
   happening: a working release gate (WP11), a single atomic-write path (WP13), and
   hooks that leave a breadcrumb (WP14) are the *process* fixes. They are third, not
   first, because they buy safety for future changes rather than fixing present harm.
4. **Wave 4 fourth** — real defects, but each is bounded and none destroys or
   silently disables anything. The doc pass (WP22) is deliberately batched here so
   it can be verified against the *fixed* behaviour rather than documenting a moving
   target.
5. **Wave 5 last** — skill-engineering polish and the JS test gap. Genuine invariant
   debt (F-47 violates "TDD is mandatory" for the only JS in the repo) but zero
   runtime risk.

**One deviation worth considering:** if only one wave will realistically get done,
do Wave 1 and then **WP6 alone** (the sync `--check` gate). WP6 is the single highest
leverage item in the whole plan — it is the gate that would have caught F-01's blast
radius, and it converts an entire class of "shipped copy diverged" defects from
undetectable to build-breaking, for about 60 lines.

---

# 4 · Team size, agent dispatch queue, and concurrency

**Recommended max concurrency: 3 implementation agents + 1 arbitration agent.**

Rationale, not a guess: Wave 1 has five file-disjoint packages, so five could run in
parallel — but they all land in **one PR**, and a five-way parallel diff is harder to
review than it is to produce. Three is the point where the wave finishes in roughly
the time of its slowest package while the diff still reads as a coherent story. Waves
2 and 3 have genuine same-file collisions (`test_scaffold.py`, `badger_lib.py`) that
cap useful parallelism at 3 anyway.

**Model lanes**

| Lane | Model | Used for |
|---|---|---|
| Planning / arbitration / security reasoning | **Opus** | Wave planning, the WP7 threat model, the WP11 release-policy decision, final cross-package review, the VERSION+changelog commit |
| Implementation | **Sonnet** | Every red→green→refactor package |
| Mechanical / doc | **Haiku** | Doc-sync worklist, dead-import deletions, status-header updates |

## Wave 1 dispatch queue

| WP | Persona / lens | Model | Parallel? | Files owned (exclusive) | Acceptance criteria |
|---|---|---|---|---|---|
| **WP1** | `test-engineer` | Sonnet | ✅ parallel slot 1 | `scripts/sync_plugin_skills.py`; `tests/test_sync_plugin_skills.py` *(new)* | `tests/test_sync_plugin_skills.py` exists and passes. A pre-populated `dest` is **byte-identical** after `sync_skill(src, dest, dry_run=True)`. The per-skill print is emitted only when `sync_skill` returns non-zero. `MANAGED_EXTERNALLY` names are never touched. Pytest count ≥ 691 + 4. |
| **WP2** | `code-reviewer` (security lens) | **Opus** | ✅ parallel slot 2 | `.../welcome-ai-badger/scripts/hook_wiring.py`; `.../mcp_tools.py`; `tests/test_settings_preservation.py` *(new)* | A `.claude/settings.json` containing `{"permissions":{"deny":["Bash"]}}` **followed by a syntax error** is byte-identical after `wire_hooks()`, and a note is appended. A valid `~/.claude/settings.json` with `permissions` survives `_scaffold_claude_mcp_user` with `permissions` intact and a `.bak-*` copy present. A malformed `~/.hermes/config.yaml` makes `_scaffold_hermes_mcp_user` append a note and return — **no `yaml.YAMLError` escapes `Scaffolder.run()`**. A YAML file parsing to a *list* does not raise `AttributeError`. |
| **WP3** | `architect` | **Opus** | ✅ parallel slot 3 | `features/common/hooks/mcp_index_hook.py`; `features/common/hooks/hooks-manifest.json`; `tests/test_mcp_index_hook_exec.py` *(new)* | With a temp project containing `.ai-badger/skills/mcp-index/scripts/mcp_index_build.py` that writes a sentinel, `on_session_start()` **does not create the sentinel** and `post_tool_call(...)` does not either. `hooks-manifest.json` no longer advertises `mcp-index-init`/`mcp-index-update`. `validate.py --all` still passes (the manifest must stay schema-valid). No `subprocess` import remains in the module. |
| **WP4** | `test-engineer` | Sonnet | ⏸ serial after WP1 frees slot 1 | `.../task/scripts/task_tracker.py`; `tests/test_task_tracker_cron.py` *(new)* | With `crontab -l` stubbed to exit 1 **while a crontab exists**, `install_cron()` returns non-zero and **never invokes `crontab -`**. `cmd_start` with no flags does **not** call `install_cron` (flag inverted to opt-in `--cron`; `--no-cron` retained as a deprecated no-op or removed with a changelog note). A missing `crontab` binary yields a reported condition, not a traceback, and does not follow a printed success JSON. `_desired_cron_line` quotes interpolated paths and escapes `%`. |
| **WP5** | `code-reviewer` (security lens) | **Opus** | ⏸ serial after WP2 frees slot 2 | `features/common/hooks/learned_skills_sync.py`; `tests/test_learned_skills_sync.py` | A Hermes skill containing a symlink whose target holds `ghp_` + 36 chars → `sync_skill` returns `action == "refused"` with reason `"symlink"`, and **no file under `learned/` contains the secret bytes**. `is_syncable` returns `(False, "symlink")` for a skill containing a symlink pointing outside `skills_root`. **The fixed-vocabulary finding format is unchanged** — no scanned byte may reach any returned or logged string. Every existing test in the file still passes. |
| **ARB** | arbitration | **Opus** | 🔒 serial, last | `VERSION`; `docs/changelog/0.19.0-destructive-write-guards.md` | All six gates green. Cross-package read of the full diff. `VERSION` → `0.19.0`; one changelog entry naming F-01…F-05 and the two behaviour changes (WP3 removes advertised hooks; WP4 inverts a default). `version_sync.py --check` and `release_guard.py` pass. |

## Wave 2 dispatch queue

| WP | Persona | Model | Parallel? | Acceptance criteria |
|---|---|---|---|---|
| **WP6** | `architect` | Sonnet | 🔒 **serial, first** | `sync_plugin_skills.py --check` exits 1 on any content divergence (using `badger_lib.dir_content_hash` + `SKILL_EXCLUDE_PATTERNS`, honouring `MANAGED_EXTERNALLY`) and 0 when synced. Wired into `.pre-commit-config.yaml` as a third `always_run` hook **and** into `.github/workflows/pylint.yml`. A test asserts `--check` fails after mutating one file under `.claude/skills/`. |
| **WP7** | `code-reviewer` (security lens) | **Opus** | ✅ parallel (after WP6) | With AWM enabled, a `PreToolUse` payload for `Bash` with `rm -rf /` and one for `WebFetch` produce **no `"allow"` decision**. With state recording `project: /a`, a payload with `cwd: /b` produces no `"allow"`. Partner mode has a maximum lifetime. `poll_once` never invokes `run_auto_wm` without an explicit opt-in flag in state. `tests/test_awm_gate.py`'s existing safety-invariant docstring pattern is preserved. |
| **WP8** | `architect` | **Opus** | 🔒 **serial, after WP7 merges** | `hooks-manifest.json` + `hooks.json` register `session_start_hook.py` for `SessionStart`. A scaffold test asserts the wired command path **ends in `session_start_hook.py`**, not merely that some SessionStart hook exists. `drift_notice_hook.py` is no longer written into a consumer's `.claude/settings.json`. Owns `tests/test_scaffold.py` for this wave — coordinate with WP10. |
| **WP9** | `architect` | Sonnet | ✅ parallel (after WP6) | A new test runs `install_skills` against the **real** `features/` tree and asserts every skill name declared in `features/*/skills.json` appears in some emitted command. An agent with no `{name}` template produces a **warning**, not a silent duplicate. `install_skills` uses `["common"] + config["stacks"]`. The existing fixture tests still pass. |
| **WP10** | `test-engineer` | Sonnet | ⏸ serial with WP8 (shared `tests/test_scaffold.py`) | A post-scaffold test asserts **every** managed header's referenced `.ai-badger/` path exists on disk. `.hermes.md` references `.ai-badger/HERMES.md`; `.github/copilot-instructions.md` references `.ai-badger/copilot-instructions.md`; the copilot template's line 7 references its own file, not CLAUDE.md. |
| **ARB** | arbitration | **Opus** | 🔒 last | Gates green; `.ai-badger/` and `.claude/` regenerated **once** by this agent; `VERSION` → `0.20.0`; one changelog entry. |

**Waves 3–5** follow the same shape: `architect`/Opus for anything that changes a
contract (WP11, WP12, WP16, WP17), `test-engineer`/Sonnet for coverage packages
(WP15, WP24), `code-reviewer`/Opus for WP7-class security reasoning, and **Haiku for
WP22 and WP24 only** — the doc worklist and the two-line reimport deletion are
mechanical and fully specified by the review's worklist table.

**Never dispatch to Haiku:** WP2, WP3, WP5, WP7, WP8, WP11, WP12, WP17. Each requires
judgement about what *not* to do (WP3's "delete, do not rename" is the clearest case).

---

# 5 · Per-package TDD entry points

Each row is the **first** thing the agent writes. It must fail for the stated reason
before any production line is touched.

| WP | Test to write first | Assertion that must fail today |
|---|---|---|
| WP1 | `tests/test_sync_plugin_skills.py::test_dry_run_leaves_dest_byte_identical` | Hash the tree under a pre-populated `dest`, call `sync_skill(src, dest, dry_run=True)`, re-hash. **Fails: `dest` no longer exists.** |
| WP1b | `…::test_print_reflects_actual_result_not_the_dry_run_flag` | `main()` with a `COMMON_SKILLS` entry whose source dir is absent must not print `synced:`/`would sync:` for it. **Fails: printed unconditionally.** |
| WP2 | `tests/test_settings_preservation.py::test_wire_hooks_aborts_on_unparseable_settings` | Write `{"permissions":{"deny":["Bash"]}},,,` to `.claude/settings.json`, run `wire_hooks()`, assert the file bytes are unchanged and a note mentions it. **Fails: file is replaced with `{"hooks": …}`.** |
| WP2b | `…::test_hermes_user_config_yaml_error_does_not_escape_run` | Write invalid YAML to a monkeypatched `~/.hermes/config.yaml`; assert `_scaffold_hermes_mcp_user` returns and appends a note. **Fails: `yaml.parser.ParserError` propagates.** |
| WP3 | `tests/test_mcp_index_hook_exec.py::test_session_start_never_executes_a_project_supplied_script` | Temp project with `.ai-badger/skills/mcp-index/scripts/mcp_index_build.py` writing `sentinel.txt`; call `on_session_start(ctx)`; assert `not sentinel.exists()`. **Fails only after the file is planted — write it as the guard against re-arming, and pair it with a test that `_rebuild_index` no longer exists.** |
| WP4 | `tests/test_task_tracker_cron.py::test_install_cron_aborts_when_crontab_l_fails` | Stub `subprocess.run` so `crontab -l` returns rc=1 with a non-empty stderr; assert `install_cron()` != 0 **and that no call with argv `["crontab", "-"]` was made**. **Fails: the replacement write happens.** |
| WP4b | `…::test_cmd_start_does_not_install_cron_by_default` | Run `cmd_start` with default args; assert `install_cron` was never called. **Fails: called unless `--no-cron`.** |
| WP5 | `tests/test_learned_skills_sync.py::test_skill_containing_symlink_is_refused` | Skill dir with `SKILL.md` + `creds.txt -> <file containing ghp_ + 36 chars>`; assert `sync_skill(...)["action"] == "refused"` and reason `"symlink"`, and that no file under `learned/` contains the secret bytes. **Fails: action is `"created"` and the secret is copied.** |
| WP6 | `tests/test_sync_plugin_skills.py::test_check_mode_fails_when_claude_copy_diverges` | Sync, mutate one byte under `.claude/skills/task/SKILL.md`, run `main(["--check"])`; assert return 1. **Fails: `--check` does not exist.** |
| WP7 | `tests/test_awm_gate.py::test_denylisted_bash_is_never_auto_approved` | AWM enabled; `PreToolUse` payload `{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}`; assert no `"allow"` in stdout. **Fails: allow emitted.** |
| WP7b | `tests/test_poll_limit.py::test_poll_once_does_not_self_enable_auto_wm` | Limited→unlimited transition with no opt-in flag in state; assert `auto_wm_runner` was not called. **Fails: called unconditionally.** |
| WP8 | `tests/test_scaffold.py::test_session_start_hook_is_the_wired_session_start_command` | Scaffold to `tmp_path`; assert some `hooks.SessionStart[*].hooks[*].command` **ends with `session_start_hook.py`**. **Fails: only `drift_notice_hook.py` is wired.** |
| WP9 | `tests/test_install_plugins.py::test_real_catalog_emits_an_install_command_per_declared_skill` | `install_skills(repo_root, real_config)`; for every skill name in `features/*/skills.json`, assert it appears in some emitted command. **Fails: four identical marketplace-add commands, zero skill names.** |
| WP10 | `tests/test_scaffold.py::test_every_managed_header_points_at_an_existing_file` | Scaffold; for each managed file, parse the `Source of truth: <path>` from line 1 and assert `(target / path).exists()`. **Fails for `.hermes.md` and `.github/copilot-instructions.md`.** |
| WP11 | `tests/test_release_guard.py::test_git_failure_is_not_reported_as_no_changes` | Stub `_git` to simulate rc≠0 on `diff`; assert `check()` returns 1 with a distinguishable sentinel. **Fails: returns 0, "no shipped-surface changes — PASS".** |
| WP12 | `tests/test_badger_lib.py::test_find_root_never_touches_the_network` | No local framework, no cache, no allow-network flag; assert `find_root()` raises and `subprocess.run` was never called. **Fails: clones from GitHub.** |
| WP13 | `tests/test_badger_lib.py::test_dump_json_is_atomic_under_write_failure` | Patch the serializer to raise mid-write; assert the pre-existing file is intact. **Fails: truncated.** |
| WP14 | `tests/test_awm_gate.py::test_internal_error_is_recorded_somewhere` | Force `main()` to raise; assert exit 0 **and** a log line exists. **Fails: nothing is recorded.** |
| WP15 | `tests/test_adjust_skills.py::test_foreign_github_skills_dir_is_preserved` | Pre-create a real `.github/skills/task/` with a user file; run `adjust()`; assert the file survives and a note is returned. **Fails: `rmtree`d.** |
| WP16 | `tests/test_validate.py::test_all_validates_mcp_servers_and_stack_json` | Corrupt `features/<stack>/mcp-servers.json` in a temp copy; assert `validate_all` returns 1. **Fails: returns 0.** |
| WP17 | `tests/test_scaffold.py::test_failed_run_leaves_a_detectable_partial_marker` | Force a mid-`run()` raise; assert `manifest.json.partial` exists naming the last completed step. **Fails: no manifest of any kind.** |
| WP18 | `tests/test_user_prompt_hook.py::test_windows_drive_path_is_not_a_marker` | `match_marker("H:\\Projects\\foo.py, check this", markers)` → `None`. **Fails: matches the `hint` marker.** |
| WP19 | `tests/test_stack_mcp_servers.py::test_mcp_json_override_policy_is_explicit` | `agents: ["copilot","claude"]` with divergent overrides; assert the documented policy, not list order. **Fails: copilot wins silently.** |
| WP20 | `tests/test_mcp_index.py::test_missing_pyyaml_degrades_with_a_message` | Simulate `ImportError` on `yaml`; assert a clear message, not a bare traceback. **Fails: `ModuleNotFoundError` at import time.** |
| WP20b | `tests/test_statusline_capture.py::test_no_user_statusline_configured_by_default` | Unset `CLAUDE_USER_STATUSLINE`; assert `USER_STATUSLINE` is `None`/unset and no personal path appears in the module source. **Fails: `/Users/arasz/...`.** |
| WP25 | `node --test .../validate-agent-instructions.test.mjs` | Missing `model.json` → the returned error list contains the expected message. **Fails: no test runner and no test exists.** |

---

# 6 · Risk register

| Risk | Wave | Behaviour-preserving? | Mitigation | Changelog / version note needed |
|---|---|---|---|---|
| **WP4 inverts `--no-cron` to `--cron`** — existing users scripting `task start --no-cron` break | 1 | ❌ **behaviour-changing** | Accept `--no-cron` as a deprecated no-op for one minor version; print a deprecation line | **Yes.** Minor bump. Call out the flag change explicitly. |
| **WP3 removes two advertised hooks** from `hooks-manifest.json` | 1 | ❌ behaviour-changing (removes a feature that never worked) | State plainly that the feature was inert since introduction; point at the re-introduction conditions | **Yes.** |
| **WP2 changes scaffold from "always writes" to "may abort a write"** — a scaffold can now complete with an un-wired hook | 1 | ❌ behaviour-changing | The abort is per-file and always produces a note; `Scaffolder.run()` continues | **Yes.** This is the intended trade: a missing hook beats a destroyed `permissions` block. |
| **WP5 refuses skills it previously synced** — any Hermes skill containing *any* symlink now refuses | 1 | ❌ behaviour-changing | Refusal reason is explicit (`"symlink"`); document the escape hatch (de-symlink the skill) | **Yes.** |
| **WP1** | 1 | ✅ preserving (restores documented behaviour) | — | Mention only. |
| **WP6's `--check` will fail the build immediately** if any current divergence exists | 2 | ✅ additive gate | Run `sync_plugin_skills.py` (no `--dry-run`!) as the first act of the wave. Two reviewers independently verified the copies are identical today, so this should be a no-op | No version implication beyond the wave's bump |
| **WP8 arms the `run_auto_wm` self-enable chain** | 2 | ❌ behaviour-changing, **and safety-relevant** | **WP7 must merge first.** Named as a hard ordering constraint in §2 and in the PR body | **Yes — the most important note in the whole plan.** |
| **WP9 changes emitted install commands for every user**; `--execute` users will see real installs for the first time | 2 | ❌ behaviour-changing (that is the point) | Keep dry-run as the default; the new commands only run under `--execute` | **Yes.** Minor bump. |
| **WP9 may surface latent catalog errors** — with `common` now in the resolver's stacks, `features/common/skills.json` becomes live | 2 | ❌ | Validate the catalog entries before enabling; add warnings, not silent fallbacks | Yes |
| **WP10 changes generated file content** in every consumer's `.hermes.md` / copilot files | 2 | ❌ (header text only) | Header-only change; body untouched | Yes |
| **WP11 cutting release tags changes `release_guard`'s baseline** from `v0.2.0` to current — the guard becomes *able to fail* for the first time | 3 | ✅ (restores intended behaviour) | Expect the first post-tag PR to require a VERSION bump. That is correct | **Yes.** Document the decision in ADR-0001. |
| **WP12 makes `find_root()` raise where it previously cloned** — any workflow relying on the implicit clone breaks | 3 | ❌ behaviour-changing | The raise carries an actionable message naming `ensure_root()`/`--allow-network` | **Yes.** |
| **WP13 touches every JSON write path** in the framework | 3 | ✅ preserving | Route through one helper; the 691 existing tests are the regression net; verify `index.json` byte-identical after `index_build --check` | Mention |
| **WP17 changes `manifest.json` write ordering** and adds `.ai-badger.bckp/` on every refresh | 3 | ❌ (adds a backup dir) | Add `.ai-badger.bckp/` to the scaffolded `.gitignore` in the same commit | Yes |
| **WP18 narrows marker matching** — a user who typed `h:do this` (no space) stops getting the hint | 4 | ❌ | Accept whitespace **or** end-of-string; document in `prompt-markers/SKILL.md` | Yes |
| **WP23 populating `personaRouting`** changes `/task` Phase 2 dispatch for this repo | 4 | ❌ | Dogfood change only; validate against `schemas/config.schema.json` | Yes |
| **Python 3.8 CI leg** — any package adding a runtime-evaluated PEP-585/604 annotation breaks the 3.8 matrix job silently on a local dev machine (3.14 here) | all | — | Every agent must run the gates; the arbitration agent must confirm CI green on all three legs before merge | — |
| **`.ai-badger/` / `.claude/` regeneration races** between parallel agents | 2, 4, 5 | — | Only the arbitration agent regenerates, as the wave's final commit | — |
| **`tests/test_scaffold.py` (1151 lines) and `test_drift.py` (1006) are C0302-over-threshold** and touched by several packages | 2, 3 | — | Do **not** split them inside a remediation wave — a split plus a behaviour change in one PR is unreviewable. Split is out of scope (§7) | — |

---

# 7 · Explicitly out of scope for these PRs

Each of these is a real, agreed improvement. Each is excluded with a reason.

| Item | Source | Why out of scope |
|---|---|---|
| **Split `Scaffolder`'s five mixins into composed collaborators** (`ScaffoldContext` dataclass) | architecture I1 / R10 | ~2,900 lines of test construct `Scaffolder` directly. Mechanically safe but *wide*, and mixing it with any behaviour change makes the diff unreviewable. Needs its own PR after Wave 3, with WP6's sync gate and WP13's atomic writes already in place. |
| **Package `badger_lib` + the scaffold engine as an installable `ai_badger` distribution** | architecture I6 / R11 | Changes how the plugin ships and how scaffolded projects resolve the engine. **Needs its own ADR.** Would retire the nine `_bootstrap_lib` copies and most of F-17's root cause — high value, wrong time. |
| **De-duplicate the nine `_bootstrap_lib()` copies / unify the three "framework root" predicates** | architecture I6 / R9 | The shim must work in three deployment shapes (framework checkout, `.ai-badger/` scaffold, `~/.hermes/plugins/`). Needs an integration test per shape written *first*. Highest-risk refactor in the review; do it after WP12 has already split `find_root`. |
| **Collapse the 3+1 MCP config writers into one table-driven writer** | architecture I3 / R5 | ~215 lines → ~90, no test names the module, and the `.mcp.json` command-splitting heuristic diverges from `_parse_command` and must be preserved verbatim or deliberately unified. WP19 fixes only the `for … break` correctness bug; the consolidation is a separate PR. |
| **Single feature-type registry** replacing the four hardcoded lists (`badger_lib.FEATURES`, `index_build`'s if-chain, `drift.py:100`'s tuple, `validate.py`'s if-chain) | architecture I11 / R6 | The four already disagree about `templates`, so unifying them will *change drift output*. That is an intentional correction that deserves its own PR and changelog, not a side effect of WP16. |
| **Derive `DEFAULT_SKILLS` / `COMMON_SKILLS` from catalog metadata** and decide `code-review-checklist`'s status | architecture I8 / R7 | Changes the default skill set — a product decision, not a bug fix. Note that `code-review-checklist` is currently in the catalog, indexed, tested, and reachable by **neither** default path; somebody has to *decide*, not just refactor. |
| **Pick one extension mechanism** (delete `_embed_extensions` + `index_build.py:110-125`, or fix its ordering) | architecture I5 / R8 | Zero catalog instances exist, so "delete" is behaviour-preserving today — but it removes a schema field, which is a compatibility decision. Small PR, own changelog. |
| **Split `test_drift.py` (1006 lines) and `test_scaffold.py` (1151 lines)** along their existing `# ---` domain boundaries | python I6, tests suggestion | Purely mechanical, and both files are touched by Waves 2–3. Splitting them mid-remediation guarantees merge conflicts. Do it as a standalone PR once the waves land. Only C0302 lint debt; CI's pylint scope excludes `tests/`. |
| **Rename top-level `scripts/` to `catalog/` / `distribution/` / `release/`** | architecture S1 | The screaming-architecture invariant genuinely applies. But this renames every entry point, every `_bootstrap_lib` path, and every doc reference. Own PR, own ADR, after packaging is decided. |
| **Split `badger_lib.py` into `catalog.py` / `fingerprint.py` / `versioning.py`** | architecture S2 | Same reason; WP12 and WP13 both touch this file and should land first. |
| **Add gitleaks/trufflehog to CI** | security suggestion 6 | Cheap and sensible, but it is a new external dependency in CI and will produce an initial finding backlog. Separate task. |
| **Path-traversal hardening of `project.name`, `shell=True` in the skill installer, dependency auto-install consent, `.mjs` ReDoS caps, manifest absolute-path containment** | security I1, I2, I7, suggestions 1 & 3 | All confirmed by the security reviewer as **defence-in-depth, not exploitable from a hostile repo today** (catalog-controlled inputs, pattern-constrained `config.stacks`). Real work; belongs in a dedicated hardening PR after Wave 3, sized as one wave of its own. |
| **`feed-badger` outbound secret scan + replacing `git add -A` with an explicit pathspec** | security I4 | Genuinely important — it is the path that *publishes* — but the fix depends on extracting `scan_for_unsafe_literals` into a shared module, which WP5 and WP13 both touch. Schedule immediately after Wave 3. |
| **Prompt-marker state and AWM decision-log privacy** (`0600` mode, gitignore entries, size caps) | security I5 | Same hardening PR as above. |

---

## Appendix — finding → work package index

| Finding | WP | Wave |
|---|---|---|
| F-01 | WP1 | 1 |
| F-02 | WP2 | 1 |
| F-03 | WP3 | 1 |
| F-04 | WP4 | 1 |
| F-05 | WP5 | 1 |
| F-17 | WP6 | 2 |
| F-12 | WP7 | 2 |
| F-07 | WP8 | 2 |
| F-06 | WP9 | 2 |
| F-08 | WP10 | 2 |
| F-10, F-11 | WP11 | 3 |
| F-09 | WP12 | 3 |
| F-23 | WP13 | 3 |
| F-13 | WP14 | 3 |
| F-16 | WP15 | 3 |
| F-24 | WP16 | 3 |
| F-25 | WP17 | 3 |
| F-21 | WP18 | 4 |
| F-22 | WP19 | 4 |
| F-14, F-15, F-20 | WP20 | 4 |
| F-26, F-31, F-32 | WP21 | 4 |
| F-18, F-19, F-27–F-30, F-33–F-35 | WP22 | 4 |
| F-36–F-39 | WP23 | 4 |
| F-48 | WP24 | 4 |
| F-47 | WP25 | 5 |
| F-43–F-46 | WP26 | 5 |
| F-40, F-42 | WP27 | 5 |
| F-41 | WP28 | 5 |