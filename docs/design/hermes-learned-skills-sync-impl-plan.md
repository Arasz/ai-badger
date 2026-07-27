# Hermes Learned-Skills Sync — TDD Implementation Plan

**Date:** 2026-07-26
**Status:** Implemented in 0.18.0 — kept as the design record, not a plan
**Re-verified:** 2026-07-27 against 0.27.0. All six stages confirmed landed, at the planned
signatures. Note that the shipped code is now **ahead of this plan**, not behind it: §5.2's secret
scan was hardened past its own spec by remediation WP5 (skills containing symlinks are refused)
and by Wave 10, which extracted the scanner into `scripts/unsafe_literals.py` and pointed both the
inbound and outbound paths at it.
**Issue:** #67
**Research:** `docs/research/hermes-learned-skills-sync.md` (read it first — this plan assumes
its corrections C1–C10)
**Version target:** 0.18.0 (minor — new feature)

---

## 0. Read this before writing code

The first-pass research proposed a design that does not work. Four things it got wrong are
now design constraints, and the plan below will not make sense without them:

1. **Do not use `skills.external_dirs`.** It was shipped in v0.7.1 and reverted in #58
   because it is a global flat namespace that collides across projects. (Research C1.)
2. **Do not scan `~/.hermes/skills/` in the hot path.** 154 skills, 36 categories, and the
   directory still contains leftover symlinks pointing back into `.ai-badger/skills/`. A
   naive walk re-imports ai-badger's own framework skills as "learned" and grows every run.
   (Research C2.)
3. **Nothing distributes `.ai-badger/skills/` to any agent today** — #58 removed the only
   mechanism. Stage 5 reverses #58 to restore it. Until that stage lands, do not assume a
   synced skill is loadable by anything. (Research C3.)
4. **Do not build a `~/.hermes/hooks/` handler or edit `~/.hermes/config.yaml`.** The
   mechanism is the Python plugin this repo already ships, which already registers
   `post_tool_call`. (Research C4, C10.)

### Non-negotiables from the project invariants

- **TDD is mandatory.** Every stage below starts with a named failing test. Write the test,
  watch it fail for the right reason, then implement. No production line without a test that
  demanded it.
- **One PR per stage-group** (see §7). Draft PR from the first commit; small commits.
- **Bump `VERSION`, run `python3 scripts/version_sync.py`, run
  `python3 scripts/index_build.py`, add `docs/changelog/0.18.0-<slug>.md`** before the PR
  goes ready.
- **Minimal comments** — 1–3 lines stating the contract, no essays. Point at this doc for
  the "why".
- **Guard clauses** at every boundary; fail fast rather than letting invalid state flow in.
- **No hardcoded secrets** in fixtures — use obviously-fake values.
- **Screaming architecture** — the new module is named for the domain concept
  (`learned_skills_sync`), not for a technical bucket.

### Commands

```
test   python3 -m pytest -q
lint   python3 -m pylint scripts features tests
build  python3 scripts/index_build.py --check
```

### Determinism rules for the new code

- Pure-stdlib, Python 3.8+ compatible (`from __future__ import annotations`, no walrus in
  public API signatures, `typing.Optional`/`List`/`Dict` rather than PEP 604 unions).
- **No `datetime.now()` inside logic.** Every function that stamps time takes a `now: str`
  parameter. Tests pass a fixed ISO string.
- **No `Path.home()` inside logic.** The Hermes skills root is a parameter
  (`skills_root: Path`) with a thin resolver at the edge. This is what makes the whole thing
  testable without touching the developer's real `~/.hermes/`.
- The hook body must **never raise into Hermes.** Wrap and log; a broken sync must not break
  the user's tool call.

---

## 1. Files this plan touches

| File | Change |
|---|---|
| `features/common/hooks/learned_skills_sync.py` | **new** — all sync logic, pure functions |
| `tests/test_learned_skills_sync.py` | **new** — Stages 1–3 |
| `features/common/hooks/ai_badger_hooks.py` | thin `skill_manage` branch on the existing `post_tool_call` registration |
| `tests/test_learned_skills_hook.py` | **new** — Stage 4 (hook wiring) |
| `features/hermes/adjustments/adjust_hooks.py` | install/refresh `~/.hermes/plugins/ai_badger_hooks.py` |
| `tests/test_scaffold.py` | Stage 4 additions (plugin install) |
| `schemas/learned-skills.schema.json` | **new** — schema for `learned.json` |
| `scripts/validate.py` | register `learned-skills` in `KIND_TO_SCHEMA` |
| `features/common/skills/feed-badger/scripts/detect_additions.py` | group `learned/**` per skill |
| `tests/test_detect_additions.py` | Stage 6 additions |
| `features/common/skills/welcome-ai-badger/scripts/scaffold.py` | Stage 5 — restore `symlink_hermes_skills()` (reverse #58), with the no-`rmtree` fix and a corrected docstring |
| `features/common/skills/den-refresh/scripts/refresh.py` | Stage 5 — re-link on refresh |
| `tests/test_den_refresh.py` | Stage 5 additions |
| `docs/adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md` | **new** — Stage 5 |
| `docs/audit-symlink-hermes-skills.md` | reconcile with the reversal |
| `docs/changelog/0.18.0-<slug>.md` | **new** |
| `VERSION`, `plugin.json`, `marketplace.json`, `index.json` | via `version_sync.py` / `index_build.py` |

---

## 2. Data contracts (fix these before Stage 1)

### 2.1 On-disk layout

```
.ai-badger/skills/learned/<category>/<name>/         # category omitted -> "uncategorized"
.ai-badger/skills-data/hermes/learned.json           # provenance + idempotence record
```

`skills-data/` already holds per-stack skill metadata (`skills-data/{common,python,github}/skills.json`);
learned skills arrive from the `hermes` stack, so `skills-data/hermes/learned.json` fits the
existing layout. It is deliberately **separate from `.ai-badger/manifest.json`** — manifest.json
means "the framework placed this and owns it", which a learned skill is not.

### 2.2 `learned.json`

```json
{
  "version": 1,
  "skills": [
    {
      "name": "apple-notes",
      "category": "apple",
      "target": ".ai-badger/skills/learned/apple/apple-notes",
      "sourcePath": "apple/apple-notes",
      "sourceHash": "<sha256 of the source dir content>",
      "syncedAt": "2026-07-26T20:00:00Z",
      "status": "synced"
    }
  ]
}
```

- `sourcePath` is **relative to the Hermes skills root**, never absolute — absolute paths
  leak the developer's home directory into a tracked file.
- `status` ∈ `synced` | `orphaned` | `conflict`.
- `sourceHash` uses `badger_lib.dir_content_hash` for consistency with the rest of the
  framework.
- **No `$schema` key.** A relative `$schema` would dangle — a scaffolded project has no
  `schemas/` directory. Validation is explicit:
  `python3 scripts/validate.py --kind learned-skills <file>`.
- The record carries no `hermesVersion`. Research D6 listed one, but the hook context does
  not expose a reliable Hermes version, and the schema is `additionalProperties: false`, so
  adding it later is a deliberate schema change rather than a silent extension.

### 2.3 `schemas/learned-skills.schema.json`

Draft 2020-12, `additionalProperties: false`, required: `version`, `skills`; each skill
requires `name`, `category`, `target`, `sourcePath`, `sourceHash`, `syncedAt`, `status`.
`sourcePath` must match `^[^/][^\\]*$` style relative-path constraint (no leading `/`, no
`..` segment).

---

## 3. Stage 1 — Gates (pure predicates, no filesystem writes)

**Goal:** the five gates from the research doc's architecture diagram, as independently
testable predicates. Nothing writes anything in this stage.

### 3.1 Write these tests first — `tests/test_learned_skills_sync.py`

| Test | Asserts |
|---|---|
| `test_target_project_returns_none_when_cwd_has_no_manifest` | `target_project(tmp_path)` is `None` — the gateway-cwd case (C6) |
| `test_target_project_returns_project_root_when_manifest_present` | with `.ai-badger/manifest.json` written, returns that dir |
| `test_target_project_returns_none_for_empty_or_missing_cwd` | `""` and a non-existent path both yield `None` |
| `test_resolve_source_dir_uses_category_segment` | `resolve_source_dir("apple-notes", "apple", root)` → `root/apple/apple-notes` |
| `test_resolve_source_dir_without_category_searches_one_level` | a skill at `root/misc/foo` is found by name alone |
| `test_resolve_source_dir_rejects_traversal_name` | `name="../../etc"` → `None`, never a path outside `root` |
| `test_is_syncable_rejects_symlinked_skill_dir` | a symlink at `root/ai-badger/task` → `(False, "symlink")` (C2) |
| `test_is_syncable_rejects_path_escaping_skills_root` | a dir whose `resolve()` lands outside `root` → `(False, ...)` |
| `test_is_syncable_rejects_dir_without_skill_md` | `(False, "no SKILL.md")` |
| `test_is_syncable_accepts_plain_skill_dir` | `(True, "")` |
| `test_is_framework_owned_true_for_manifest_target_name` | a skill named `task` when the manifest has `.ai-badger/skills/task` → `True` (C7) |
| `test_is_framework_owned_false_for_unknown_name` | `False` |

Every one of these must fail with `ModuleNotFoundError` / `AttributeError` first.

### 3.2 Then implement

```python
# features/common/hooks/learned_skills_sync.py
def target_project(cwd: str) -> Optional[Path]: ...
def resolve_source_dir(name: str, category: Optional[str], skills_root: Path) -> Optional[Path]: ...
def is_syncable(source_dir: Path, skills_root: Path) -> Tuple[bool, str]: ...
def is_framework_owned(project: Path, name: str) -> bool: ...
```

Implementation notes:

- `is_syncable` must use `Path.is_symlink()` on **every segment** between `skills_root` and
  `source_dir`, not just the leaf — the leftover namespace symlink is at the *parent* level
  in some layouts. Then `source_dir.resolve()` must still be relative to
  `skills_root.resolve()`; if `relative_to` raises, reject.
- `resolve_source_dir` rejects any `name` or `category` containing `/`, `\`, or `..` before
  touching the filesystem (guard clause, mirrors Hermes' own `_validate_name` /
  `_validate_category`).
- `is_framework_owned` reads `.ai-badger/manifest.json` and compares against the set of
  `entry["target"]` basenames under `.ai-badger/skills/`.

**Done when:** all Stage-1 tests pass; `pylint` clean.

---

## 4. Stage 2 — The write path

**Goal:** copy exactly one skill directory into `learned/`, record it, and be idempotent.

### 4.1 Tests first — same file

| Test | Asserts |
|---|---|
| `test_sync_skill_copies_into_learned_category_path` | files land at `.ai-badger/skills/learned/apple/apple-notes/SKILL.md` |
| `test_sync_skill_uses_uncategorized_when_category_missing` | `learned/uncategorized/<name>/` (D3) |
| `test_sync_skill_copies_subdirectories` | `scripts/`, `references/` come along |
| `test_sync_skill_writes_learned_manifest_entry` | `learned.json` gains one record with the fixed `now` and a relative `sourcePath` |
| `test_sync_skill_manifest_source_path_is_relative` | no `/Users/`, no `str(Path.home())` anywhere in the written JSON |
| `test_sync_skill_is_idempotent_when_source_unchanged` | second call with same `sourceHash` writes nothing new; `skills` list length stays 1 |
| `test_sync_skill_updates_in_place_when_source_changed` | changed content → files updated, `syncedAt` bumped, still one record |
| `test_sync_skill_reports_conflict_for_untracked_existing_path` | a pre-existing `learned/apple/apple-notes/` **not** in `learned.json` is left byte-identical and returns `status="conflict"` (D4) |
| `test_sync_skill_never_writes_outside_learned_root` | attempt with a crafted category → raises/returns error, and `.ai-badger/skills/task` is untouched |
| `test_sync_skill_refuses_framework_owned_name` | gate 5 wired into the write path |

### 4.2 Then implement

```python
def load_manifest(project: Path) -> Dict[str, Any]: ...
def save_manifest(project: Path, data: Dict[str, Any]) -> None: ...
def sync_skill(project: Path, source_dir: Path, name: str,
               category: Optional[str], *, now: str) -> Dict[str, Any]: ...
```

- `sync_skill` returns `{"action": "created"|"updated"|"skipped"|"conflict"|"refused",
  "target": <rel path>, "reason": str}`. Never raises for expected conditions.
- Confinement check: compute `dest.resolve()`, assert it is under
  `(project/".ai-badger"/"skills"/"learned").resolve()`; otherwise return `refused`.
- Copy with `shutil.copytree(..., dirs_exist_ok=True, symlinks=False)` after removing a
  tracked stale dest; **never** `symlinks=True`.
- `save_manifest` writes with `sort_keys` stable ordering and a trailing newline so repeated
  syncs produce no spurious diffs.

**Done when:** Stage-2 tests pass and a manual run against a temp fixture produces a byte-identical
`learned.json` on a second invocation.

---

## 5. Stage 3 — Orchestration, deletes, secrets, reconcile

**Goal:** the single entry point the hook calls, plus the backfill command.

### 5.1 Tests first

| Test | Asserts |
|---|---|
| `test_on_skill_manage_ignores_other_tools` | `tool_name="terminal"` → `None`, no writes |
| `test_on_skill_manage_ignores_failed_calls` | `status="error"` → `None` (gate 2) |
| `test_on_skill_manage_ignores_non_project_cwd` | gateway case → `None` (gate 3) |
| `test_on_skill_manage_syncs_on_create` | end-to-end: files present, manifest entry written |
| `test_on_skill_manage_syncs_on_patch_and_edit` | both actions trigger a sync |
| `test_on_skill_manage_marks_orphaned_on_delete` | `action="delete"` → record `status="orphaned"`, **files still on disk** (D4) |
| `test_on_skill_manage_ignores_unknown_action` | e.g. `action="view"` → `None` |
| `test_secret_scan_refuses_skill_with_api_key_literal` | a fixture `SKILL.md` containing an obviously-fake `sk-` style literal → `refused`, nothing written |
| `test_secret_scan_allows_placeholder_env_reference` | `${OPENAI_API_KEY}` / `$env:FOO` passes |
| `test_reconcile_syncs_all_eligible_and_skips_symlinks` | seeded root with 3 real skills + 1 symlinked project namespace → 3 synced, 1 skipped with reason |
| `test_reconcile_is_idempotent` | second run reports `0 created, 0 updated` |

### 5.2 Then implement

```python
SYNC_ACTIONS = frozenset({"create", "edit", "patch", "write_file", "remove_file"})
DELETE_ACTIONS = frozenset({"delete"})

def scan_for_secrets(source_dir: Path) -> List[str]: ...
def on_skill_manage(args: Dict[str, Any], status: str, cwd: str,
                    *, skills_root: Path, now: str) -> Optional[Dict[str, Any]]: ...
def reconcile(project: Path, skills_root: Path, *, now: str) -> Dict[str, Any]: ...
```

**Secret scan scope — keep it honest.** This is a guard, not a guarantee. Match only
high-confidence literal shapes (provider key prefixes, `-----BEGIN * PRIVATE KEY-----`,
`AWS_SECRET_ACCESS_KEY=<40+ chars>`, a `password=`/`token=` assignment with a 20+ char
literal). **Refuse and report — never redact and never partially copy.** Do not attempt
entropy heuristics; false positives on a refuse-path are cheap, false confidence is not.
Test fixtures use obviously-fake values (`sk-FAKE-not-a-real-key-000`).

`reconcile` is exposed as `python3 features/common/hooks/learned_skills_sync.py --reconcile
--target <dir>` with a `--dry-run` flag, and prints a JSON summary to stdout (same shape as
`detect_additions.py`, for consistency).

**Done when:** Stage-3 tests pass; `--reconcile --dry-run` against the real `~/.hermes/skills/`
reports plausible counts and writes nothing.

---

## 6. Stage 4 — Hook wiring and plugin installation

**Goal:** the logic actually runs. Without this stage the feature is inert (research C5).

### 6.1 Tests first — `tests/test_learned_skills_hook.py`

| Test | Asserts |
|---|---|
| `test_register_registers_post_tool_call_once` | the existing `register(ctx)` still wires `post_tool_call` exactly once (no double registration) |
| `test_post_tool_observer_delegates_skill_manage_to_sync` | monkeypatched `learned_skills_sync.on_skill_manage` is called with the tool args |
| `test_post_tool_observer_swallows_sync_exceptions` | `on_skill_manage` raising → `post_tool_observer` returns normally and logs |
| `test_post_tool_observer_does_not_call_sync_for_other_tools` | no call for `tool_name="terminal"` |

And in `tests/test_scaffold.py`:

| Test | Asserts |
|---|---|
| `test_scaffold_installs_hermes_plugin_to_user_dir` | with `Path.home` patched to `tmp_path`, scaffolding a hermes-agent project writes `<home>/.hermes/plugins/ai_badger_hooks.py` |
| `test_scaffold_refreshes_stale_hermes_plugin` | an existing older copy is overwritten with current content |
| `test_scaffold_skips_hermes_plugin_when_hermes_not_an_agent` | no write when `agents` excludes `hermes` |

### 6.2 Then implement

- In `ai_badger_hooks.py`, extend `post_tool_observer` with a guarded branch. Keep it thin —
  the plugin file is a wiring layer, the logic lives in `learned_skills_sync.py`:

  ```python
  if tool_name == "skill_manage":
      try:
          _sync_learned_skill(kwargs.get("args") or {}, kwargs.get("status", "ok"), cwd)
      except Exception:                      # never break the user's tool call
          logger.debug("learned-skill sync failed", exc_info=True)
  ```

  Import `learned_skills_sync` lazily inside the branch, resolved next to `__file__`, so the
  plugin still loads when the module is absent (older scaffold).

- In `adjust_hooks.py`, add the user-scope install: copy `ai_badger_hooks.py` **and**
  `learned_skills_sync.py` to `Path.home()/".hermes"/"plugins"/`, creating the directory.
  Follow the pattern documented in `docs/design/mcp-stack-declarations-impl-plan.md` §Change 1
  for user-scope writes, and patch `pathlib.Path.home` in tests
  (precedent: `test_scaffold_creates_hermes_skill_symlinks`).
- Record the install in the adjustment's returned `notes` so `welcome-ai-badger` surfaces it.

**Done when:** Stage-4 tests pass, and a real `hermes` CLI session in this repo that runs
`skill_manage(action="create", ...)` produces a `learned/` directory. Capture that transcript
in the PR description — this is the proof-of-concept the issue asks for.

---

## 7. Stage 5 — Reverse #58: restore Hermes skill discovery

**Decision (maintainer, 2026-07-26):** reverse #58 for **all** ai-badger skills, not just
`learned/`. This supersedes the three-option table that previously stood here.

### 7.1 Why the reversal is correct

`bafb952` ("fix: remove Hermes user-scoped skill symlinks (#58)") made
`Scaffolder.symlink_hermes_skills()` a no-op and justified it with this docstring:

> "Hermes discovers project skills via the project-local skill directory."

**That statement is false.** Hermes resolves skills from `~/.hermes/skills/` plus
`skills.external_dirs` and nothing else (`agent/skill_utils.py:432,515-523`). There is no
project-local discovery mechanism. #58's fix therefore did not fix the reported staleness — it
removed discovery, silently making every scaffolded ai-badger skill invisible to Hermes.

**Symlinks were never the cause of #58.** A relative symlink has no second copy that can go
stale. The drift #58 reported (`den-refresh/SKILL.md` content differs, `drift.py` content
differs) can only exist between real files, so it was not produced by the symlink code, which
wrote `os.path.relpath` symlinks. The removed implementation was already sound: gated on
`hermes` in `config.agents`, namespaced per project under
`~/.hermes/skills/<project-name>/` — which is precisely what makes it safe where the rejected
`external_dirs` flat list was not (research C1).

**Discovery depth is not a constraint.** `iter_skill_index_files` uses
`os.walk(skills_dir, followlinks=True)` with no depth bound
(`agent/skill_utils.py:810-832`), so `<namespace>/learned/<category>/<name>/SKILL.md` is
discovered through the symlink just as `<namespace>/task/SKILL.md` is.

**Consequence for Stages 1–3, and it is not optional.** `followlinks=True` plus a restored
project symlink means `~/.hermes/skills/<project>/learned/...` resolves back into
`.ai-badger/skills/learned/`. The Stage-1 containment gates (`is_syncable`) become
load-bearing: without them, `--reconcile` re-imports already-synced learned skills into
themselves, and framework skills round-trip in as "learned". Re-verify AC9 after this stage.

### 7.2 Tests first — `tests/test_scaffold.py`

The three tests `bafb952` inverted (they currently assert that *no* symlinks are created) must
be inverted back; do not delete them, restore their intent.

| Test | Asserts |
|---|---|
| `test_scaffold_creates_hermes_skill_symlinks` | with `Path.home` patched to `tmp_path` and `hermes` in `agents`, each scaffolded skill appears as a symlink under `<home>/.hermes/skills/<project>/` |
| `test_scaffold_hermes_symlinks_are_relative` | `os.readlink` returns a relative path — no absolute home path baked in |
| `test_scaffold_skips_hermes_symlinks_without_hermes_agent` | `agents` without `hermes` → namespace dir not created |
| `test_scaffold_preserves_foreign_dirs_in_namespace` | **the data-loss guard**: a real (non-symlink) directory in the namespace survives a re-scaffold untouched |
| `test_scaffold_removes_stale_managed_symlinks` | a symlink for a skill no longer in `config.skills` is unlinked on re-scaffold |
| `test_scaffold_replaces_broken_symlink` | a dangling symlink is relinked, not left broken |
| `test_scaffold_symlinks_learned_skills_dir` | `learned/` is reachable through the namespace (one symlink for the `learned` tree is sufficient given unbounded `os.walk`) |

And in `tests/test_den_refresh.py`:

| Test | Asserts |
|---|---|
| `test_refresh_relinks_hermes_skills` | after a refresh that adds a skill, the namespace has a symlink for it; after one that removes a skill, the stale symlink is gone |

### 7.3 Then implement

Restore `symlink_hermes_skills()` from `bafb952^` with **two mandatory changes**:

1. **Never `rmtree` the namespace directory.** The old code did
   `shutil.rmtree(namespace_dir)` when it existed as a real dir. `~/.hermes/skills/ai-badger/`
   currently contains `agent-skill-discovery/` — a real, Hermes-authored skill — proving the
   namespace accumulates content ai-badger did not place. Rebuild by unlinking **only entries
   that are symlinks whose target resolves inside this project's `.ai-badger/skills/`**, then
   re-linking. Anything else is left exactly as found. Losing a user's learned skill to a
   re-scaffold is unacceptable.
2. **Correct the docstring.** State what is true: Hermes discovers skills from
   `~/.hermes/skills/` and `skills.external_dirs` only; the per-project namespace directory
   avoids the cross-project name collisions that made `external_dirs` unusable.

Then wire the same call into `den-refresh` so a refresh re-links (this is #58's legitimate
half — its own option (b)).

### 7.4 Paper trail

- **ADR required** — this reverses a shipped decision. Add
  `docs/adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md` covering: what #58
  reported, why its chosen fix was based on a false premise, why symlinks are immune to the
  drift it described, the `rmtree` data-loss hazard found in the original implementation, and
  the rejected alternatives (`external_dirs`, project-local copies).
- **Reopen #58** (or file a follow-up referencing it) noting that the staleness it reported is
  addressed by symlinks-plus-relink rather than by removing discovery.
- Update `docs/audit-symlink-hermes-skills.md`, whose recommendation ("keep
  `symlink_hermes_skills()` as-is") was overtaken by `bafb952` and is now correct again for a
  different reason.

**Done when:** the Stage-5 tests pass, the ADR is written, `hermes skills list` in this repo
shows the ai-badger skills again, and AC9 has been re-verified against the restored symlinks.

---

## 8. Stage 6 — feed-badger grouping

**Goal:** a learned skill surfaces as **one** contribution candidate, not one per file
(research C9).

### 8.1 Tests first — `tests/test_detect_additions.py`

| Test | Asserts |
|---|---|
| `test_learned_skill_dir_yields_single_candidate` | `learned/apple/apple-notes/` with `SKILL.md` + `scripts/helper.py` + `references/api.md` → exactly 1 candidate |
| `test_learned_skill_candidate_is_named_for_the_skill` | `name == "apple-notes"`, not `"SKILL"` |
| `test_learned_skill_candidate_carries_learned_provenance` | candidate has `"origin": "hermes-learned"` and the `sourcePath` from `learned.json` |
| `test_non_learned_new_files_still_yield_per_file_candidates` | existing behavior for other unmanaged files is unchanged (regression guard) |

### 8.2 Then implement

In `detect_additions.py`, before the per-file loop, collect
`.ai-badger/skills/learned/*/*/` directories, emit one candidate each, and add their file
paths to a skip-set consumed by the existing `rglob` loop. Read `learned.json` when present
to attach provenance; degrade gracefully (still one candidate per directory) when it is
missing.

**Done when:** Stage-6 tests pass **and** the pre-existing `detect_additions` tests still pass
unchanged.

---

## 9. Sequencing and PR strategy

Per the *one PR per task* invariant, split into three PRs — each independently reviewable,
each green on its own:

| PR | Stages | Ships |
|---|---|---|
| **PR 1** | 1–3 | `learned_skills_sync.py` + schema + `validate.py` registration + `--reconcile` CLI. Pure logic, no wiring. Nothing fires yet. |
| **PR 2** | 4 | hook branch + scaffold plugin install. The feature becomes live; PR description carries the proof-of-concept transcript. |
| **PR 3** | 5–6 | reversal of #58 (+ADR 0003) and feed-badger grouping. |

PR 3's Stage 5 is a behavior reversal of a shipped decision, not an addition — it deserves its
own review attention and its own changelog line, separate from the sync feature.

Open each as a draft from the first commit. Bump `VERSION` once, in PR 1 (0.18.0), and add
one changelog entry per PR under `docs/changelog/`.

---

## 10. Out of scope

- Any change to `skills.external_dirs` (research C1).
- Two-way sync, or writing back into `~/.hermes/skills/`. The sync is one-way, always.
- Propagating Hermes deletions as project deletions (D4).
- Auto-importing the 154 existing skills. `--reconcile` exists, it is opt-in, and it is never
  run automatically.
- Generalizing learned skills for upstream contribution — that stays feed-badger's job and
  remains agent-driven.

---

## 11. Acceptance criteria

Every box must be independently checkable by a reviewer; "passes tests" alone is not enough.

### Functional

- [ ] **AC1** A successful `skill_manage(action="create", name=X, category=Y)` in a Hermes
      CLI session whose `cwd` is an ai-badger-scaffolded project results in
      `.ai-badger/skills/learned/Y/X/SKILL.md` existing with content identical to
      `~/.hermes/skills/Y/X/SKILL.md`.
- [ ] **AC2** The same call made with `cwd` outside any scaffolded project writes nothing
      anywhere, and logs at debug level only.
- [ ] **AC3** A failed `skill_manage` call (`status != "ok"`) writes nothing.
- [ ] **AC4** Running the same sync twice with an unchanged source produces a byte-identical
      `.ai-badger/skills-data/hermes/learned.json` (verified with `git diff --exit-code`).
- [ ] **AC5** `skill_manage(action="delete")` marks the record `orphaned` and leaves the
      project files on disk.
- [ ] **AC6** `--reconcile --dry-run` against the real `~/.hermes/skills/` (154 skills,
      36 categories) completes, writes nothing, and its report skips every symlinked entry
      under `~/.hermes/skills/ai-badger/` with an explicit reason.

### Safety

- [ ] **AC7** No file is ever written outside `.ai-badger/skills/learned/` and
      `.ai-badger/skills-data/hermes/learned.json`. Demonstrated by a test that crafts a
      traversal `category` and asserts `.ai-badger/skills/task/` is untouched.
- [ ] **AC8** A skill whose name collides with a framework-managed skill (`task`,
      `feed-badger`, …) is refused, and `.ai-badger/manifest.json` drift detection
      (`drift.py`) reports no new drift after a sync run.
- [ ] **AC9** No symlink is ever followed out of `~/.hermes/skills/`; framework skills never
      round-trip back in as learned. Demonstrated by the Stage-1 symlink test **and** by AC6's
      real-corpus dry run.
- [ ] **AC10** A skill containing a high-confidence secret literal is refused with a reported
      reason and nothing is written.
- [ ] **AC11** An exception anywhere in the sync does not propagate into Hermes: the tool call
      still returns normally. Demonstrated by
      `test_post_tool_observer_swallows_sync_exceptions`.
- [ ] **AC12** `learned.json` contains no absolute paths and no home-directory string.

### Integration

- [ ] **AC13** After `welcome-ai-badger` scaffolds a project with `hermes` in `agents`,
      `~/.hermes/plugins/ai_badger_hooks.py` and `learned_skills_sync.py` exist and match the
      framework copies. With `hermes` absent, neither is written.
- [ ] **AC14** A learned skill directory produces exactly **one** feed-badger candidate,
      named for the skill, carrying `origin: "hermes-learned"`.
- [ ] **AC15** Existing `detect_additions` behavior for non-learned files is unchanged — the
      pre-existing tests pass without modification.
- [ ] **AC16** `hermes skills list` run in a scaffolded project shows that project's
      ai-badger skills again, resolved through `~/.hermes/skills/<project>/`. Capture the
      output in the PR.
- [ ] **AC16a** Every created link is a **relative** symlink (`os.readlink` returns no
      absolute path), and none is created when `hermes` is absent from `config.agents`.
- [ ] **AC16b** **No data loss on re-scaffold**: a real (non-symlink) directory placed in
      `~/.hermes/skills/<project>/` — the `agent-skill-discovery` case — survives a
      re-scaffold and a den-refresh byte-identical. Only ai-badger-owned symlinks are
      removed.
- [ ] **AC16c** `docs/adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md` exists and
      states why #58's fix was based on a false premise; the false docstring in
      `scaffold.py` is corrected; `docs/audit-symlink-hermes-skills.md` is reconciled; #58 is
      reopened or superseded by a referencing follow-up.
- [ ] **AC16d** With symlinks restored, AC9 is **re-verified**: `--reconcile` over the real
      corpus still refuses every path that resolves back into `.ai-badger/skills/`, so no
      learned or framework skill round-trips into itself.

### Project hygiene

- [ ] **AC17** `python3 -m pytest -q` green; `python3 -m pylint scripts features tests` clean;
      `python3 scripts/index_build.py --check` passes.
- [ ] **AC18** `VERSION` bumped to 0.18.0, `python3 scripts/version_sync.py` run,
      `docs/changelog/0.18.0-<slug>.md` added.
- [ ] **AC19** `schemas/learned-skills.schema.json` exists, is registered in
      `scripts/validate.py`'s `KIND_TO_SCHEMA`, and
      `python3 scripts/validate.py --kind learned-skills <file>` validates a real
      `learned.json`.
- [ ] **AC20** `docs/research/hermes-learned-skills-sync.md` is updated to point at the
      shipped behavior, and the incorrect `symlink_hermes_skills()` docstring in `scaffold.py`
      is corrected.
- [ ] **AC21** Issue #67's own acceptance criteria are satisfied: research document (done),
      proof-of-concept syncing one learned skill (AC1, with transcript in PR 2), and a
      conflict-resolution decision doc (research doc §Decisions D4).
