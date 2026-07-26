# Research: Sync Hermes Learned Skills into ai-badger Catalog

**Issue:** #67
**Status:** Research complete and **reviewed** — original findings corrected against source
**Reviewed:** 2026-07-26 (second pass; evidence re-derived from the Hermes source tree at
`~/.hermes/hermes-agent/` and from this repo)
**Implementation plan:** `docs/design/hermes-learned-skills-sync-impl-plan.md`

---

## Review summary

The first pass got the *shape* of the problem right — one-way Hermes → ai-badger sync, a
`learned/` namespace, feed-badger as the upstream path. Four of its load-bearing claims did
not survive verification:

| # | First-pass claim | Verdict |
|---|---|---|
| 1 | Phase 1: register `.ai-badger/skills/` in `skills.external_dirs` | **Rejected** — this exact approach was tried and reverted (#58, v0.7.1). See [C1](#c1). |
| 2 | The `~/.hermes/skills/ai-badger/` symlink namespace was "removed in #58" | **Half-true and dangerous** — the *writer* is a no-op, the *symlinks* still exist on developer machines. See [C2](#c2). |
| 3 | "The existing scaffold pipeline handles distribution" via `sync_plugin_skills.py` | **Wrong** — nothing distributes `.ai-badger/skills/` to any agent today. See [C3](#c3). |
| 4 | Hook into skill saves via a `~/.hermes/hooks/` post-session hook | **Wrong mechanism** — that hook system has no tool-level event. A better mechanism already ships in this repo. See [C4](#c4). |

Findings 1, 2 and 4 (of the original numbered questions) were confirmed with only minor
additions. The revised design is in [Revised architecture](#revised-architecture); the
decisions are in [Decisions](#decisions).

---

## Verified findings

### 1. Where does Hermes store learned skills? — CONFIRMED

Skills live at `~/.hermes/skills/<category>/<skill-name>/SKILL.md`, with optional
`references/`, `scripts/`, `templates/` subdirectories. Frontmatter is YAML:

```yaml
---
name: apple-notes
description: "Manage Apple Notes via memo CLI: create, search, edit."
version: 1.0.1
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [Notes, Apple, macOS, note-taking]
---
```

**Added by review — scale and shape of the corpus** (measured on this machine):

- **154 skills across 36 category directories.** A blanket directory sync is not a viable
  design; the sync must be scoped to a single skill per event.
- Frontmatter is **not uniform**: `name` 154/154, `description` 156, `version` 117,
  `author` 101, `platforms` 107, `license` 93. Any parser must treat everything except
  `name` as optional.
- `author:` is **not** a reliable agent-vs-human discriminator. Observed values include
  `Hermes Agent` (45), `community` (7), `Orchestra Research` (7), `Hermes` (5),
  `Hermes Agent + Teknium` (4), `Anthropic (adapted by Nous Research)` (4),
  `Hermes Agent (adapted from obra/superpowers)` (3), `hermes-agent` (2), and others. Do
  not build the "is this ours to sync?" gate on this field.

### 2. What triggers skill creation/update? — CONFIRMED, with the exact call signature

Skills are created and mutated through the `skill_manage` tool
(`~/.hermes/hermes-agent/tools/skill_manager_tool.py:1397`):

```python
def skill_manage(action, name, content=None, category=None, file_path=None,
                 file_content=None, old_string=None, new_string=None,
                 replace_all=False, absorbed_into=None) -> str
```

Relevant actions: `create`, `edit`, `patch`, `write_file`, `remove_file`, `delete`.
`name` + `category` fully determine the on-disk path
(`_resolve_skill_dir`, same file, line 640). This is what makes an **event-scoped** sync
possible: the hook is told exactly which skill changed, so it never has to scan 154 dirs.

Callers: foreground (user asks for a skill), and the background self-improvement review
fork, which is guarded (`_background_review_write_guard`, line 303) but still autonomous.
The curator prunes and consolidates agent-created skills.

### 3. Can we hook into the skill save event? — YES, but not the way the first pass said

<a id="c4"></a>**Correction C4.** Hermes has **three** extension points, and the first pass
picked the one that cannot do the job:

| Mechanism | Where | Events | Fit |
|---|---|---|---|
| Gateway event hooks | `~/.hermes/hooks/<name>/{HOOK.yaml,handler.py}` (`gateway/hooks.py`) | `gateway:startup`, `session:start/end/reset`, `agent:start/step/end`, `command:*` | **No** — no tool-level event, and it fires in the gateway process only. The directory does not even exist on this machine. |
| Shell hooks | `hooks:` block in `~/.hermes/config.yaml` (`agent/shell_hooks.py`) | incl. `pre_tool_call`, `post_tool_call` with a `matcher` regex on the tool name | Workable, but needs a config.yaml edit **and** allowlist consent. |
| **Python plugin hooks** | `~/.hermes/plugins/*.py` with a `register(ctx)` entry point | same `VALID_HOOKS` set, incl. `post_tool_call` | **Best** — ai-badger already ships one. |

**The decisive fact the first pass missed:** this repo already owns a Hermes plugin that
registers `post_tool_call`.

```python
# features/common/hooks/ai_badger_hooks.py:325-335
def register(ctx):
    ctx.register_hook("on_session_start", on_session_start_drift_notice)
    ctx.register_hook("pre_llm_call", pre_llm_inject_context)
    ctx.register_hook("post_tool_call", post_tool_observer)   # <-- already here
```

`post_tool_observer(tool_name, result, duration_ms, cwd, **kwargs)` already receives
everything the sync needs. Adding a `skill_manage` branch to this plugin means **no
`config.yaml` edit, no shell-hook allowlist prompt, no new installation path**.

For reference, the shell-hook route we are *not* taking would have looked like this
(`agent/shell_hooks.py:305-400` is the parser; `matcher` is a regex `fullmatch` on the tool
name and is only honored for `pre_tool_call`/`post_tool_call`):

```yaml
hooks:
  post_tool_call:
    - command: "python3 ~/.ai-badger/sync_learned_skill.py"
      matcher: "skill_manage"
      timeout: 60
```

<a id="c5"></a>**Correction C5 — the plugin route has one real blocker.** Hermes loads
plugins from `~/.hermes/plugins/`. `features/hermes/adjustments/adjust_hooks.py` copies
`ai_badger_hooks.py` into **`.ai-badger/hooks/`**, which Hermes never reads. The copy at
`~/.hermes/plugins/ai_badger_hooks.py` is manual — the module docstring says so outright
("copy/symlink this file to `~/.hermes/plugins/`"). Its content happens to be byte-identical
to the framework's copy right now, but nothing maintains that. **Any work that puts logic in
this plugin must also ship the install/refresh step, or the hook will never fire for a user
who did not hand-copy it.**

<a id="c6"></a>**Correction C6 — `cwd` does not reliably identify the target project, and for plugin
hooks it is not passed at all.** For *shell* hooks, `cwd` is `os.getcwd()` of the Hermes
process (`agent/shell_hooks.py:540-551`): in a CLI session that is the project; in a gateway
session (Telegram, Discord, Slack) it is wherever the gateway was launched — very often not a
project at all.

**Revised during implementation (verified 2026-07-26):** the *plugin* hook path — the one this
design uses — passes **no `cwd` whatsoever**. `model_tools.py:1049-1064` invokes
`post_tool_call` with `tool_name, args, result, task_id, session_id, tool_call_id, turn_id,
api_request_id, duration_ms, status, error_type, error_message, middleware_trace` and nothing
else. `conversation_loop.py:504-509` invokes `on_session_start` with only `session_id, model,
platform`. So a plugin callback must resolve the project itself via `os.getcwd()` and then
gate on it. The rule is unchanged and is now the *only* protection: **no-op unless
`Path(cwd)/.ai-badger/manifest.json` exists**, never guess a target.

<a id="c6b"></a>**Correction C6b — this reveals two pre-existing broken hooks, unrelated to
this feature.** `ai_badger_hooks.py` has always declared `cwd: str = ""` on both
`on_session_start_drift_notice` and `post_tool_observer` and used it to locate the project.
Since Hermes passes no `cwd` for either event, the Hermes-side drift notice and the MCP-index
hit/miss logging have **never fired in production**. Tracked separately — fixing them is not
in scope for the sync feature, and doing so silently would change untested behavior.

<a id="c10"></a>**Correction C10 — process constraints on `config.yaml`.** The project's own
`hermes.instructions.md` says *"Use `hermes config set <key> <value>` for configuration,
never hand-edit config.yaml."* The `hermes hooks` CLI offers only `list | test | revoke |
doctor` — there is no `hooks add`, so a shell hook can only be installed by writing YAML.
`~/.hermes/` currently holds **8 `config.yaml.corrupt.*` backups**, which is direct evidence
that programmatic rewrites of that file have gone wrong before. This is a third, independent
argument for the plugin route, which touches no config at all.

### 4. How do we avoid losing auto-learning? — CONFIRMED direction, unsafe as specified

One-way Hermes → ai-badger is right; Hermes keeps owning `~/.hermes/skills/` and keeps
learning. The conflict rules as written are not safe enough:

<a id="c7"></a>**Correction C7.** "Hermes owns the content; the Hermes version wins" grants an
*autonomous background curator* write authority over version-controlled project files. Two
concrete failure modes:

- The background review fork rewrites a skill; the sync silently overwrites the project's
  copy; the change lands in a commit nobody wrote.
- Combined with [C2](#c2), a framework skill round-trips through `~/.hermes/skills/` and gets
  written back into `.ai-badger/skills/` as "learned".

Revised rules (see [Decisions](#decisions)) confine every write to
`.ai-badger/skills/learned/`, make writes additive-and-recorded, and never let the sync touch
a path that the framework manifest owns.

<a id="c2"></a>**Correction C2 — the symlink namespace is not gone.** `symlink_hermes_skills()`
in `scaffold.py:345-353` is now an empty no-op (#58), so *new* scaffolds create nothing. But
the symlinks written by earlier versions are still on disk:

```
~/.hermes/skills/ai-badger/task        -> .../ai-badger/.ai-badger/skills/task
~/.hermes/skills/ai-badger/den-refresh -> .../ai-badger/.ai-badger/skills/den-refresh
... 6 total, plus a real dir `agent-skill-discovery/`
```

A scanner walking `~/.hermes/skills/**` will follow these back into `.ai-badger/skills/` and
re-import ai-badger's **own framework skills** as "learned" — a feedback loop that grows on
every run. Mitigations are mandatory, not optional: never follow symlinks, skip any path that
resolves outside `~/.hermes/skills/`, and skip the project-namespace directories entirely.

### 5. How do we make learned skills available to other agents? — PREMISE WRONG

<a id="c3"></a>**Correction C3.** The first pass claimed "the existing scaffold pipeline
handles distribution" and named `sync_plugin_skills.py`. Verified against the code, **nothing
distributes `.ai-badger/skills/` to any agent**:

- `scripts/sync_plugin_skills.py` is a **framework-repo build script**. `ROOT` is the
  ai-badger repo; it copies `features/common/skills/` and `features/claude/skills/` into
  *this repo's* `.claude/skills/` so the Claude plugin can ship them. It never reads
  `.ai-badger/skills/` and never runs in a scaffolded project.
- No scaffolding step writes `.claude/skills/` or `.github/skills/` in a target project.
  `features/*/scaffolding.json` declare only `CLAUDE.md`, `HERMES.md` + `.hermes.md`, and the
  Copilot instruction files. A grep for `.claude/skills` across the welcome-ai-badger scripts
  and every `scaffolding.json` returns nothing.
- Claude Code sees ai-badger's skills because ai-badger is **installed as a plugin**, not
  because a project scaffolded them.
- Hermes discovers skills from `~/.hermes/skills/` plus `skills.external_dirs`
  (`agent/skill_utils.py:432,515-523`) and nothing else. **There is no project-local skill
  discovery in Hermes.** The docstring at `scaffold.py:348` — "Hermes discovers project
  skills via the project-local skill directory" — is factually incorrect and should be fixed.

**Consequence, and it is the important one:** since #58 removed the symlinks, project-scoped
skills in `.ai-badger/skills/` are invisible to *every* agent on a clean machine. So "make
learned skills available to other agents" is not a free byproduct of landing them in
`.ai-badger/skills/` — it is **unsolved, for all agents, today**. A sync feature that stops at
writing files into `.ai-badger/skills/learned/` produces no observable behavior change for
anyone. This is tracked as a separate, sequenced work item in the implementation plan
(Stage 5), not as an assumption.

<a id="c1"></a>**Correction C1 — `external_dirs` is a reverted approach, not a new idea.**
The first-pass Phase 1 ("add `.ai-badger/skills/` to `skills.external_dirs`") re-proposes
exactly what v0.7.1 shipped and #58 removed. Per `docs/audit-symlink-hermes-skills.md` §2 and
the scaffold's own comment, it was rejected because `external_dirs` is *a shared global flat
list* — two projects each exporting a `task` skill collide, and the loser silently wins or
loses depending on config order. `~/.hermes/config.yaml:118-119` still reads
`skills.external_dirs: []`. Re-proposing it needs to answer the collision problem first;
this plan does not re-propose it.

<a id="c9"></a>**Correction C9 — feed-badger integration is not free.**
`features/common/skills/feed-badger/scripts/detect_additions.py:118-136` walks
`.ai-badger/skills/` with `rglob("*")` and emits **one candidate per file** for anything not
covered by a manifest directory entry, naming each candidate `f.stem`. A learned skill with
`SKILL.md` + `scripts/helper.py` + `references/api.md` therefore surfaces as three unrelated
candidates called `SKILL`, `helper`, and `api`. Phase 3 needs an explicit grouping rule that
treats a learned-skill directory as one unit.

---

## Revised architecture

```
   Hermes CLI or gateway session
              │
              │ skill_manage(action=create|edit|patch|…, name=…, category=…)
              ▼
   post_tool_call  ──►  ai_badger_hooks.py  (already registered; ~/.hermes/plugins/)
                             │
                             │ gate 1: tool_name == "skill_manage"
                             │ gate 2: extra.status == "ok"
                             │ gate 3: (cwd)/.ai-badger/manifest.json exists      [C6]
                             │ gate 4: skill path resolves inside ~/.hermes/skills/,
                             │         is not a symlink, is not a project namespace  [C2]
                             │ gate 5: name not owned by the framework manifest    [C7]
                             ▼
                  copy one skill dir, one event
                             ▼
              .ai-badger/skills/learned/<category>/<name>/
                             +
              .ai-badger/skills-data/hermes/learned.json   (provenance + idempotence)
                             │
                             ├──►  feed-badger: grouped, one candidate per skill  [C9]
                             └──►  agent distribution — UNSOLVED for all agents   [C3]
                                   (separate work item, plan Stage 5)
```

The sync is **event-scoped**: one `skill_manage` call syncs exactly the one skill it named.
There is no directory crawl in the hot path. A separate explicit `--reconcile` entry point
exists for backfill, and that one *does* crawl — under the same five gates.

---

## Decisions

**D1 — Mechanism: extend the existing Python plugin hook.** Add a `skill_manage` branch to
`features/common/hooks/ai_badger_hooks.py` on the already-registered `post_tool_call`. No
`config.yaml` write, no shell-hook allowlist, no new install surface. Supersedes the
first pass's Phase 1 (`external_dirs`) and Phase 2 (`~/.hermes/hooks/`). Rationale: [C1],
[C4], [C10].

**D2 — Plugin installation becomes a scaffold responsibility.** `adjust_hooks.py` must also
install/refresh `~/.hermes/plugins/ai_badger_hooks.py`, with the user-scope write handled the
same way the MCP work handles `~/.hermes/config.yaml`. Without this the feature is inert.
Rationale: [C5].

**D3 — Naming: `learned/<category>/<name>/`, keeping Hermes' category segment.** The first
pass chose a flat `learned/<name>/`. Hermes' own layout is category-first and `category` is a
first-class `skill_manage` argument, so preserving it costs nothing and prevents collisions
between same-named skills in different categories. Skills with no category go to
`learned/uncategorized/<name>/`.

**D4 — Writes are confined, additive, and recorded.** Replaces "the Hermes version wins":
- The sync may only ever write under `.ai-badger/skills/learned/`.
- It never writes a path that appears as a manifest `target` (framework-owned).
- Re-sync of an already-tracked skill updates in place *and* bumps its manifest record; a
  path that exists but is **not** in `learned.json` is left alone and reported as a conflict.
- Deletes in Hermes do **not** delete in the project; they mark the entry `orphaned`. Git
  history is the project's undo, and a background curator must not be able to remove
  version-controlled files.
Rationale: [C7], [C2].

**D5 — Open question 1 (auto vs explicit): both, but event-driven by default.** Sync fires on
each successful `skill_manage`, which is cheap because it is event-scoped. An explicit
`--reconcile` pass exists for backfilling the 154 pre-existing skills and for machines where
the plugin was not installed. Blanket auto-import of the whole corpus is never the default.

**D6 — Open question 2 (manifest): yes —
`.ai-badger/skills-data/hermes/learned.json`.** `skills-data/` is already the per-stack skill
metadata area (`skills-data/{common,python,github}/skills.json`), and learned skills arrive
from the `hermes` stack, so the path fits the existing layout. It must stay **separate from
`.ai-badger/manifest.json`**: manifest.json means "the framework placed this and owns it",
which is exactly what a learned skill is not. Records: `name`, `category`, `target`,
`sourcePath`, `sourceHash`, `syncedAt`, `status`. (An earlier draft of this decision listed
`hermesVersion`; it was dropped because the hook context exposes no reliable Hermes version.)

**D7 — Open question 3 (hand-authored skills in `.ai-badger/skills/`): not learned.** The
discriminator is presence in `learned.json`, not heuristics on `author:` frontmatter — which
[finding 1](#1-where-does-hermes-store-learned-skills--confirmed) shows is unreliable. A
hand-authored skill is simply a project addition and feed-badger already treats it as one.

**D8 — Distribution: reverse #58 and restore namespaced Hermes symlinks, for all skills.**
(Maintainer decision, 2026-07-26.) Per [C3] the gap affects every project-scoped skill, not
just learned ones, so the fix is scoped the same way. The justification is that `bafb952`'s
stated rationale — "Hermes discovers project skills via the project-local skill directory" —
is false: discovery is `~/.hermes/skills/` + `skills.external_dirs` only
(`agent/skill_utils.py:432,515-523`). #58 reported *staleness between copies*; a relative
symlink has no second copy to go stale, so the symlink mechanism was never its cause. The
restoration carries two mandatory corrections: never `rmtree` the namespace directory (the
original code would have destroyed `agent-skill-discovery`, a real Hermes-authored skill
living there), and den-refresh must re-link. Requires an ADR — see plan Stage 5.

**D9 — The containment gates become load-bearing.** `iter_skill_index_files` walks with
`os.walk(..., followlinks=True)` and no depth bound (`agent/skill_utils.py:810-832`). Once D8
restores the project symlink, `~/.hermes/skills/<project>/learned/...` resolves back into
`.ai-badger/skills/learned/`, so the [C2] loop is live rather than hypothetical. The Stage-1
`is_syncable` gates are the only thing preventing learned skills from re-importing themselves
and framework skills from round-tripping in as learned.

---

## Residual risks

| Risk | Mitigation | Where |
|---|---|---|
| Symlink feedback loop re-importing framework skills | never follow symlinks; resolve-and-contain under `~/.hermes/skills/`; skip project-namespace dirs | plan Stage 2 |
| Hook fires with a `cwd` that is not a project (gateway sessions) | require `.ai-badger/manifest.json` under `cwd` | plan Stage 2 |
| Plugin not installed at `~/.hermes/plugins/` → silent no-op | scaffold installs/refreshes it; `hermes doctor`-style check surfaces it | plan Stage 4 |
| Background curator writes reaching git-tracked files | writes confined to `learned/`; deletes never propagate | plan Stage 3 |
| A hook exception breaking a Hermes tool call | hook body fully wrapped; log-and-continue, never raise | plan Stage 2 |
| Secrets inside a learned skill landing in a tracked file | content scan before write; refuse and report | plan Stage 3 |
| feed-badger emitting per-file noise | group `learned/**` by skill directory | plan Stage 6 |

---

## Files examined

Framework: `features/common/hooks/ai_badger_hooks.py`,
`features/hermes/adjustments/{adjust_hooks.py,adjustment.json}`,
`features/hermes/{stack.json,skills.json,scaffolding.json,instructions/hermes.instructions.md}`,
`features/common/skills/welcome-ai-badger/scripts/{scaffold.py,agent_files.py,drift.py}`,
`features/common/skills/feed-badger/scripts/detect_additions.py`,
`scripts/sync_plugin_skills.py`, `.ai-badger/{manifest.json,skills-data/}`,
`docs/audit-symlink-hermes-skills.md`, `docs/design/mcp-stack-declarations-impl-plan.md`.

Hermes (`~/.hermes/hermes-agent/`): `agent/shell_hooks.py`, `agent/skill_utils.py`,
`gateway/hooks.py`, `hermes_cli/{hooks.py,plugins.py}`, `tools/skill_manager_tool.py`.

Machine state: `~/.hermes/config.yaml`, `~/.hermes/skills/` (154 skills / 36 categories),
`~/.hermes/plugins/`, `~/.hermes/hooks/` (absent).
