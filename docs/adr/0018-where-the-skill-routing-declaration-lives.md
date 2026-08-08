# ADR-0018 — One mechanism: a skill declares its own stack and its own scope

**Date:** 2026-08-07
**Status:** Accepted (2026-08-08, 0.104.0) — two halves **owner-ruled** (see Ruling)
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code (architect lane)
**Supersedes:** ADR-0005; ratifies and restates ADR-0010
**Scope:** `badger_lib.SKILL_SCOPES`, skill routing and scope, `skills_lint`, the catalog-routing tests

## Context

ADR-0005 set a revisit condition, and it fired.

That ADR collapsed two hand-maintained skill lists into `badger_lib.SKILL_SCOPES`, and rejected
the more natural home — a `scope:` key in each `SKILL.md`'s frontmatter — on one cost, stated
with its own trigger for reopening:

> no script in `scripts/` parses YAML frontmatter today, and pyyaml is a guarded optional import
> that degrades to a note. Adding a parser — or hand-rolling one — to read a single scalar buys a
> worse failure mode than the constant it replaces. **Worth revisiting if anything else ever
> needs frontmatter at build time.**

Something else does, several times over. Verified at 0.93.1:

| Reader | Where | What it reads frontmatter for |
|---|---|---|
| `frontmatter_fields` | `gates/skills_lint.py` | rule 10 — eight required keys on every catalog `SKILL.md`, run in CI |
| `Frontmatter.duplicate_keys` | `engine/frontmatter.py` | rule 11 — a duplicate key is refused |
| `skill_description` | `engine/badger_lib.py` | the `description:` scalar, for rules 3–5 and for `available_opt_in` |
| `frontmatter_fields` | `features/common/skills/welcome-ai-badger/scripts/template_rendering.py` | persona `model:` lanes, at scaffold time |
| `_split_frontmatter` | `features/claude/adjustments/adjust_agents.py` | rebuilding a persona as a Claude subagent |
| `_split_frontmatter` | `features/copilot/adjustments/adjust_agents.py` | the same, via pyyaml |
| `declares_model` | `features/common/skills/task/scripts/dispatch_gate_hook.py` | denying an `Agent` dispatch that names no model |

**Line numbers are deliberately absent above.** The draft of this ADR carried them and they
rotted within one release: PR #350 (L11) landed after it was written, extracting the frontmatter
reader into `engine/frontmatter.py` and lifting the lint out of `tooling/validate.py` into
`gates/skills_lint.py`. Symbol plus file survives a refactor; `file:line` does not, and a citation
that silently rots is the defect this document exists to close, not one to reproduce.

The specific fear is gone too. ADR-0005 worried a hand-rolled parser "buys a worse failure mode
than the constant it replaces" — a parse miss reading as a pass. That is now impossible by
construction: `frontmatter_fields` returns `None` rather than a partial dict, and `skills_lint`
reports the `None` as a rule-10 violation.

### What checking the code found that the review summary did not

The 2026-08-07 review (Theme D, item D2) put two costs on ADR-0005's account. Both shrink under
measurement.

- **"39 hand-kept entries."** There are **36** (14 `default`, 22 `optIn`), counted by importing
  the module.
- **"A `too-many-lines` pylint disable serves the same lapsed premise."** `engine/badger_lib.py`
  is 1032 lines against pylint's default `max-module-lines=1000` (no override in
  `pyproject.toml`, no `.pylintrc`). Deleting the dict literal and its comment (lines 690–730)
  leaves **991** — nine lines of headroom, one feature's worth. The disable belongs to
  `badger_lib`'s size (D9); the comment on line 1 attributing it to ADR-0005 misdirects.

A third fact, found while tracing call sites, does most of the work below:

- **`skill_scope()` and `default_skill_names()` have no production callers.** Every reference is
  a test (`tests/test_sync_plugin_skills.py`,
  `tests/test_skill_scope_declarations.py`, `tests/test_commit_reminder_wiring.py`,
  `tests/test_plugin_manifest.py`). Production reads the dict through
  `default_skills_in`, `opt_in_skills_in` and `stack_local_skills`, all of which use
  `SKILL_SCOPES.get(...)` and **skip an undeclared directory silently**.

  ADR-0005's Decision says `skill_scope()` "raises `UnknownSkillScope` rather than assuming a
  default". True of the function; not true of the system.

### Two mechanisms, and the owner wants one

Stripped of framing, the catalog answers two questions about a skill, in two different places:

| Question | Answered by | Kind |
|---|---|---|
| Which stack owns this skill? | its directory under `features/<stack>/skills/` | the filesystem |
| Does it ship unasked, or only when named? | `badger_lib.SKILL_SCOPES` | a 36-entry hand-kept dict |

The first was proved end to end by the coordinator: a config naming only `stacks: ["dotnet"]`,
with no `--skills` flag and no skill named anywhere, delivered all 11 `features/dotnet/skills/`
skills. Routing is the directory, and has been since ADR-0010.

`SKILL_SCOPES` **is** still used — just not for routing. Its production surface is
`default_skills_in()`, `opt_in_skills_in()`, `inclusion_notes()`, and an *exclusion* clause inside
`stack_local_skills()`; `tooling/sync_plugin_skills.py` and `scaffold.py` derive from
those at import time. What it declares is scope, for one set of 36 skills.

## Decision — recommended

**Collapse to one mechanism: a skill declares itself, in its own directory and its own
frontmatter.**

- **Which stack owns it** → the directory it lives in. Already true, now ratified.
- **`default` or `optIn`** → a `scope:` key in its own `SKILL.md` frontmatter.
- **`badger_lib.SKILL_SCOPES` is deleted.**
- **A missing or invalid `scope:` is a `skills_lint` failure**, in the same linter that already
  reads and validates every `SKILL.md`.

### Why my earlier objection does not survive, and I am withdrawing it

An earlier draft of this ADR recommended keeping the constant, and rejected frontmatter first on
this: *"routing must not depend on a generated artifact or on filesystem reads — every scope
answer today is a dict lookup with no I/O and no failure path, in the one code path whose failure
mode is a skill silently reaching nobody."*

Every clause of that is wrong, and the facts were available when I wrote it:

1. **It adds no new I/O.** Every `SKILL.md` already carries frontmatter, and `skills_lint` already
   parses **all 51 of them** on every gate run (`SKILLS_GLOB = "features/*/skills/*/SKILL.md"`,
   `gates/skills_lint.py`) and enforces five rules on the result — rule 2 already compares the
   frontmatter `name` against the parent directory. These files are read anyway.
2. **The dict never avoided the filesystem.** `default_skills_in`
   (`engine/badger_lib.py`) already calls `skills_dir.iterdir()` and stats a `SKILL.md`
   per entry. It is a filter on a directory walk, not a substitute for one.
3. **Measured, the delta is noise.** Deriving the default set from the dict plus a stat walk is
   **1.17 ms**; reading and parsing all 36 frontmatter blocks is **8.16 ms** — 20 iterations each,
   warm page cache, this tree. A ~7 ms one-time import cost, in the same release series that just
   removed ~470 ms of `jsonschema` import (D1).
4. **Routing is already the filesystem** for 15 of the 51 shipped skills, and has worked that way
   since ADR-0010.

The "silently reaching nobody" risk I invoked is real. It just points the other way.

### The strongest argument: ADR-0005's guarantee gets stronger, not weaker

ADR-0005 exists because `code-review-checklist` was complete, correct, catalogued and reached
nobody for its entire life. Its fix was "omission is an error". Today that property is thinner
than the ADR claims:

- At runtime, an undeclared skill is **silently not offered** — `default_skills_in` and
  `opt_in_skills_in` both use `SKILL_SCOPES.get(...)` and drop it.
- The hard failure comes from `test_every_catalog_skill_is_reachable_by_a_declared_route`
  (`tests/test_sync_plugin_skills.py`), a test that diffs generated `index.json` against the
  dict and covers **only the common stack**.
- `skill_scope()`'s `UnknownSkillScope` — the raise ADR-0005 credits — is called by nothing in
  production.

Under the collapse, a missing `scope:` is a **hard `skills_lint` failure at the point of
authorship**, in the linter that already reads the file, under the glob that already covers every
stack. The declaration and the thing declared cannot be separated by a `git mv`, a delete, or a
forgotten second edit, because they are the same file. That inverts the concern I raised: the
mechanism ADR-0005 wanted is more nearly delivered by frontmatter than by the constant it chose.

### Costs, honestly

- **The migration touches 36 `SKILL.md` files and every reader.** `default_skills_in`,
  `opt_in_skills_in`, `inclusion_notes` (`engine/badger_lib.py`), `stack_local_skills`,
  `index_build.py`, `tooling/sync_plugin_skills.py`, `scaffold.py`,
  `den-refresh/scripts/refresh.py`, plus the tests listed above.
- **`sync_plugin_skills.py` and `scaffold.py` derive their lists at module import.** Both already
  do filesystem work there; both would now read and parse 36 files instead of stat-ing 36
  directories. Measured above at ~7 ms. It is a real change in kind — import-time I/O grows — and
  the number says it does not matter. If it ever does, the fallback is `index.json` with
  `--check` freshness as its guard, not a return to a constant.
- **One-place legibility is genuinely lost.** "What ships to every consumer unasked" is one hunk
  in a diff today; afterwards it is a generated table or a grep. This was the last argument for
  the constant and it does not outweigh a guarantee that moves from a test-plus-silent-skip to a
  lint rule. `docs/skills.md`'s generated table and its bidirectional check
  (`tests/test_docs_match_the_catalog.py`) are where the one-glance view should live.
- **`index.json` keeps carrying `scope`**, derived by `index_build.py` from frontmatter instead of
  from the dict, so `drift.py`'s `item.get("scope")` consumer is unaffected. The index stays a
  derived view; it does not become a source.

### Two dispositions the implementation must settle, with recommendations

- **`skill_scope()` and `UnknownSkillScope` should disappear, not be ported.** Zero production
  callers, per the finding above. The "undeclared is an error" property moves to the lint rule,
  where it fires for real. Porting a raise that nothing calls would keep exactly the shape this
  review exists to find: a guard that cannot fail for the reason it was written.
  `default_skill_names()` is in the same position — tests only — and should either take a root or
  go, with its callers using `default_skills_in(root / "features" / "common" / "skills")`.
- **Which files must declare `scope:`.** Recommend **common-stack skills only**
  (`features/common/skills/*/SKILL.md`), because that is the only set whose answer is consulted:
  `stack_local_skills` returns every skill in a stack directory regardless of scope, so a required
  key on the 15 stack-local skills would be ceremony, and ceremony rots. A directory-scoped rule
  keeps the check honest about what it protects.
- **`stack_local_skills`' exclusion clause has nothing left to test** once the dict is gone.
  Measured at 0.93.1 it already excludes nothing — no non-common stack holds a `SKILL_SCOPES` key,
  and the 36 directories under `features/common/skills/` are exactly the 36 keys. Recommend
  deleting the clause and replacing the hazard it guarded with a test: **no skill name may appear
  in two stack directories** (verified clean today — 51 directories, no duplicate names). A test
  says what a silent filter did not.

### Revisit condition

Stated as concretely as ADR-0005 stated its own. Either of these means frontmatter has stopped
being the right home:

1. **The frontmatter read becomes a measured import cost.** Baseline recorded here: 1.17 ms via
   the dict, 8.16 ms via 36 frontmatter reads, warm cache. If a gate lane's import budget makes
   that delta matter — the way `jsonschema`'s ~470 ms did in D1 — move `scope` to `index.json`
   with `index_build.py --check` as its freshness guard. Do not move it back to a constant; that
   reintroduces the split this ADR closes.
2. **`skills_lint`'s glob stops covering a directory that ships.** The rule is only a guarantee
   over the files it reads. This has already happened once: narrowing the glob left 15 of 51
   skills unlinted with 22 tests still green (review finding A5, now pinned by
   `gates/skills_lint.py`'s own `skill_files()`). If that pin is ever loosened, a missing
   `scope:` goes silent again and the guarantee is back to where ADR-0005 found it.

## Consequences

- **ADR-0005 is superseded.** Its Alternatives section is wrong in both parts at 0.93.1: "no
  script parses YAML frontmatter today" is false, and "derive from directory layout" is what the
  project does. Its *intent* — one declaration, omission is an error — is carried forward and
  better served.
- **ADR-0010 is ratified and restated.** The stack directory decides ownership. The fifteen
  stack-local skills are routed by **presence in a stack directory**, not by absence from
  `SKILL_SCOPES` — a framing this document used in an earlier draft and now retires, because it
  made a deliberate design read like a bug.
- One mechanism replaces two: a skill's directory says who owns it, its frontmatter says how it
  ships, and both travel with the skill through `git mv`, a delete, or a new author's first PR.
- An undeclared skill becomes a lint failure instead of a silent skip plus a common-stack-only
  test.
- `engine/badger_lib.py` loses 41 lines, landing at 991 of pylint's 1000. The
  `# pylint: disable=too-many-lines` on line 1 can go with it — but it should stop citing
  ADR-0005 either way, because nine lines of headroom is not what that disable is for.

## Ruling

Two halves are decided by the owner and recorded above; one thing remains, and it is execution,
not decision.

- **Ruled (2026-08-07): the project routes skills by stack directory.** Proved end to end with a
  `stacks: ["dotnet"]` config that delivered all 11 dotnet skills with none named. ADR-0005's
  rejection of directory-derived routing is superseded; ADR-0010 is ratified.
- **Ruled (2026-08-07): collapse to one mechanism.** *"We need to clean up and leave one clear
  mechanism if `SKILL_SCOPES` is not used."* It is used, but only for scope — so the split stands
  until scope moves to where the skill already declares everything else about itself.
- **Recommended implementation, for a separate lane** once L11 (#350) releases `engine/` and
  `tooling/` — it lands `engine/frontmatter.py` and `gates/skills_lint.py`, which is the extractor
  and the linter this recommendation builds on, so it must land first:
  add `scope:` to the 36 common-stack `SKILL.md` files, add the `skills_lint` rule that makes its
  absence a failure, repoint `default_skills_in` / `opt_in_skills_in` / `inclusion_notes` /
  `index_build` at frontmatter, delete `SKILL_SCOPES`, `skill_scope()` and `UnknownSkillScope`,
  and replace `stack_local_skills`' exclusion clause with a duplicate-name test.

## Implementation (0.104.0)

Landed as recommended, with one correction the implementation lane had to make.

- 36 common `SKILL.md` files gained `scope:`; `SKILL_SCOPES`, `skill_scope()`,
  `UnknownSkillScope` and `default_skill_names()` are deleted. `badger_lib.skill_scope_in()`
  reads the key; `skills_lint` rule 12 refuses a common-stack skill that declares neither value.
- Verified identical before and after: the delivered `.ai-badger/skills/` tree for three configs
  (bare defaults → 14, an `optIn` skill named explicitly → 19, `stacks: ["dotnet"]` with nothing
  named → 25), and every `scope` value in `index.json` for all 51 skills.
- `inclusion_notes` takes the default set as an argument rather than consulting a module
  constant. `drift.py` is untouched, as predicted.

**One claim in this document was wrong and the lane measured it.** The disposition above says
`stack_local_skills`' `not in SKILL_SCOPES` clause "already excludes nothing". It excludes 36
things, at the one call site nobody traced: `resolve_stacks` always puts `common` first, and
`SkillDelivery.discover_stack_local` walks *every* stack in that list. The clause was the only
thing keeping the common catalog's 22 `optIn` skills out of every scaffold. Deleting it as
recommended and rerunning the three configs delivers **36, 36 and 47** skills where 14, 19 and 25
belong. The clause is gone as recommended, but the caller now skips `DEFAULT_COMMON_STACKS`, and
`test_stack_local_discovery_never_reaches_into_the_common_catalog` fails without that guard.

The recommended duplicate-name test landed too: no name appears in two of the 51 stack
directories, and planting one fails it.

This ADR is **Accepted** with that change, because an ADR is accepted with the change it
justifies, not before it (`docs/adr/README.md`).
