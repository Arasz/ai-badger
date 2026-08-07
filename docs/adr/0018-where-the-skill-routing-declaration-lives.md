# ADR-0018 — Where the skill-routing declaration lives

**Date:** 2026-08-07
**Status:** Proposed — one half **owner-ruled** (see Ruling), one half still for decision
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code (architect lane)
**Supersedes:** ADR-0005's Alternatives section; ratifies and restates ADR-0010
**Scope:** `badger_lib.SKILL_SCOPES`, skill routing, the catalog-routing tests

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
| `_frontmatter_fields` | `tooling/validate.py:328` | `skills_lint` rule 10 — eight required keys on every catalog `SKILL.md`, run in CI |
| `duplicate_frontmatter_keys` | `tooling/validate.py:377` | rule 11 — a duplicate key is refused |
| `skill_description` | `engine/badger_lib.py:801` | the `description:` scalar, for rules 3–5 and for `available_opt_in` |
| `frontmatter_fields` | `features/common/skills/welcome-ai-badger/scripts/template_rendering.py:24` | persona `model:` lanes, at scaffold time |
| `_split_frontmatter` | `features/claude/adjustments/adjust_agents.py:92` | rebuilding a persona as a Claude subagent |
| `_split_frontmatter` | `features/copilot/adjustments/adjust_agents.py:36` | the same, via pyyaml |
| `declares_model` | `features/common/skills/task/scripts/dispatch_gate_hook.py:69` | denying an `Agent` dispatch that names no model |

The specific fear is also gone. ADR-0005 worried that a hand-rolled parser "buys a worse failure
mode than the constant it replaces" — a parse miss reading as a pass. That is now impossible by
construction: `_frontmatter_fields` returns `None` rather than a partial dict, and `skills_lint`
reports the `None` as a rule-10 violation (`tooling/validate.py:456-463`). An unparseable
frontmatter fails the build; it does not quietly route a skill to nowhere.

So ADR-0005's premise is dead, and the record misleads whoever reads it next. That much is
settled. What the rest of this ADR settles is whether the *conclusion* moves with the premise.

### What checking the code found that the review summary did not

The 2026-08-07 review (Theme D, item D2) put two costs on ADR-0005's account. Both shrink under
measurement.

- **"39 hand-kept entries."** There are **36** (14 `default`, 22 `optIn`), counted by importing
  the module.

- **"A `too-many-lines` pylint disable serves the same lapsed premise."** Measured, not inferred.
  `engine/badger_lib.py` is 1032 lines against pylint's default `max-module-lines=1000` (no
  override in `pyproject.toml`, no `.pylintrc`). Deleting the dict literal and its comment
  (lines 690–730, 41 lines) leaves **991** — **nine lines of headroom**, one feature's worth. The
  disable belongs to `badger_lib`'s size (D9); the comment on line 1 attributing it to ADR-0005
  sends the next reader to the wrong ADR.

A third fact, found while tracing call sites, cuts the other way:

- **`skill_scope()` and `default_skill_names()` have no production callers.** Every reference is
  a test (`tests/test_sync_plugin_skills.py:313,320,335,343,350`,
  `tests/test_skill_scope_declarations.py:34,39`, `tests/test_commit_reminder_wiring.py:81,82`,
  `tests/test_plugin_manifest.py:52,64,79`). Production reads the dict through
  `default_skills_in`, `opt_in_skills_in` and `stack_local_skills`, all of which use
  `SKILL_SCOPES.get(...)` and skip an undeclared directory silently.

  ADR-0005's Decision says `skill_scope()` "raises `UnknownSkillScope` rather than assuming a
  default". True of the function; not true of the system. The property that omission is an error
  is held entirely by
  `tests/test_sync_plugin_skills.py:286 test_every_catalog_skill_is_reachable_by_a_declared_route`,
  which diffs `index.json`'s common-stack skills against `set(SKILL_SCOPES)`. That test does work
  — it can fail, and it is the thing standing between us and another `code-review-checklist`. But
  it is a test, not a raise, and the ADR credits the wrong mechanism.

### Routing is by directory. That is now ruled, not merely observed

ADR-0005 rejected "derive from directory layout" outright: "Behaviour becomes invisible in
`git mv` and couples the decision to paths that other tooling resolves." ADR-0010, a day later,
routed stack-local skills by their stack directory anyway.

**The owner has ruled: directory-based routing is what this project uses.** ADR-0005's rejection
of it is superseded — obsolete in practice, not merely in tension with a later ADR. The tree has
routed this way since ADR-0010, and the code already argues the case in its own voice.
`catalog_skills_for_stack` (`engine/badger_lib.py:919`) says it outright:

> Membership here is the directory, not the scope, because that is what "this stack owns it"
> actually means.

That docstring exists because filtering by scope was tried and broke: an `optIn` skill a project
had asked for was delivered to `.ai-badger/skills/` and then linked into no discovery directory,
because the scope filter answered "does this ship by default" to a question that was actually
"does this stack own it" (#261). Scope is the wrong key for ownership. The directory is the right
one, and #261 is the evidence.

The routing rule itself is a two-line dispatch in `skills_for_stack`
(`engine/badger_lib.py:906-916`): the common stack yields its default-scope skills, and **every
other stack yields the skills its own directory holds**. Fifteen skills ship on that second arm:

| Stack | Skills |
|---|---|
| `claude` | `auto-wm` |
| `dotnet` | `dotnet-bdd-testing`, `dotnet-domain-modeling`, `dotnet-flaky-test-diagnosis`, `dotnet-hosted-service-review`, `dotnet-hosted-service-testing`, `dotnet-logger-message-design`, `dotnet-mcp-server`, `dotnet-sqlcipher-encryption`, `dotnet-system-commandline`, `dotnet-tool-publishing`, `observability-contract-review` |
| `hermes` | `cron-watchdog-authoring`, `hermes-plugin-development` |
| `mcp` | `mcp-tool-surface-testing` |

**"Routed by absence" was the wrong description, and this document used it in an earlier draft.**
Those fifteen skills are routed by **presence in a stack directory**. `stack_local_skills`'
`d.name not in SKILL_SCOPES` clause is not the routing rule — it is a filter that excludes a
universal skill which happens to sit in a stack directory. Measured at 0.93.1, that filter
**excludes nothing**: no non-common stack holds a `SKILL_SCOPES` key, and the 36 directories under
`features/common/skills/` are exactly the 36 keys. It is a guard against the case ADR-0010 fixed
(`auto-wm`, declared `default` while living under `features/claude/`), kept so the case cannot
come back silently. Describing a deliberate design as "absence" makes it read like a bug.

### What `SKILL_SCOPES` therefore is

Not a routing table. A **scope declaration for the universal set**: for the 36 skills under
`features/common/skills/`, does this ship unasked (`default`) or only when a project names it
(`optIn`)? Routing — which stack owns a skill, and therefore whether a project sees it at all —
is the directory's job, on both arms.

Read that way the dict answers one question about one set, which is a better artifact than the
one ADR-0005 described. It is also a smaller one than the review assumed, and the question below
is correspondingly narrower.

## Options

### Option A — keep ADR-0005 exactly as it stands

Change nothing, including the record.

- **Cost:** the ADR asserts a fact about the codebase that is false at 0.93.1, credits
  `skill_scope()` with a guarantee a test provides, and rejects directory-derived routing that the
  owner has now ratified and the tree has used for a fortnight. Three wrong things in the one
  document a future reader consults before re-litigating this.
- **Benefit:** zero work.

Rejected.

### Option B — move the scope declaration into `SKILL.md` frontmatter

Add `scope:` to each of the 36 common-stack `SKILL.md` files, require it there via a
directory-scoped `skills_lint` rule, and derive `default_skills_in` / `opt_in_skills_in` from it.

**The ruling makes this cheaper than the earlier draft costed it.** With routing settled as the
directory's job, a stack-local skill needs no scope at all — so there is no third `stackLocal`
value, no 51-file migration, and no dependency on the ADR-0010 question. It is 36 files and one
lint rule.

**What it buys**

- Locality: every fact about a skill lives with the skill. Under the ruling, the dict is the only
  thing about a skill stored somewhere else.
- `git rm -r` on a skill can no longer leave a stale key behind.
- The parser exists, is already gated, and already refuses ambiguity. The cost ADR-0005 priced is
  now zero.

**What it costs**

- **A generated artifact must not become the source.** If the scope answer is read from
  `index.json`, a routing-adjacent decision starts depending on a build product whose freshness is
  checked in CI and by nothing at runtime in a consumer's installed plugin. Read from each
  `SKILL.md` instead and this cost disappears entirely — the file is the source, so it cannot be
  stale. This is a constraint on how Option B is built, not an argument against it.
- **One-place legibility goes.** "What ships to every consumer unasked" is one hunk in a diff
  today. Under Option B, reviewing a change to the default set means reading 36 files or trusting
  a generated table.
- **`default_skill_names()` loses its no-argument form**, and `inclusion_notes`
  (`engine/badger_lib.py:848`) would need a root threaded to it from `scaffold.py:336`.
- **36 file edits, one lint rule, three test rewrites and a re-scaffold** — for a set that has had
  zero routing or scope defects since ADR-0005 landed.

**Evidence weighed:** a Wave 2 lane was asked to generate `docs/skills.md`'s table from
`SKILL_SCOPES` and declined, because the only machine-readable per-skill prose is each
`SKILL.md`'s `description:` — long second-person text written for a trigger matcher, not a reader.
It built a bidirectional consistency check instead (`tests/test_docs_match_the_catalog.py`).

That is evidence about what frontmatter can carry, and it does **not** argue against Option B:
`scope` is a two-value enum, not prose, and an enum is what a frontmatter key holds well. If
anything it argues mildly *for* B — it shows this project's instinct is to check agreement between
two sources rather than eliminate one, which the routing tests already do for `SKILL_SCOPES` and
would do just as well for a frontmatter key.

### Option C — keep one Python constant, narrowed to what it actually declares

`SKILL_SCOPES` stays, restated as a scope declaration for the universal set. ADR-0005's
Alternatives section is superseded, the frontmatter option is re-costed on facts true at 0.93.1,
and a fresh revisit condition is stated.

- **Cost:** one line per new common skill, forever; 41 lines of `badger_lib`; one fact about a
  skill continues to live away from the skill.
- **Benefit:** no migration, the ship-unasked set stays reviewable in one hunk, and the record
  stops lying.

## Decision — recommended, and weaker than the earlier draft claimed

**Option C, by a narrower margin than before.** The ruling removed the best argument on each side,
and the honest report is that this is now close rather than clear.

**What I got wrong, and am withdrawing.** The earlier draft rejected Option B first on "routing
must not gain I/O — every scope answer today is a dict lookup with no I/O and no failure path".
Checked against the code, that is not true, and it was the strongest thing I said:
`default_skills_in` (`engine/badger_lib.py:752-764`) already calls `skills_dir.iterdir()` and
stats a `SKILL.md` per entry. The dict is a **filter applied on top of a directory walk**, not a
substitute for one. What it saves is parsing 36 frontmatter blocks, not touching the disk. And a
scope read from `SKILL.md` cannot be stale, because the file is the source. Under the ruling that
argument does not survive at all, and I am not going to defend it because it was mine.

**What still holds, and is now doing most of the work:**

1. **The ship-unasked set must stay reviewable in one glance.** This is the property tied directly
   to the failure that produced ADR-0005 — `code-review-checklist` was complete, correct, in the
   catalog, and reached nobody for its entire life because no reviewer could see the set at once.
   Option B's mechanical protection is equal (a required key, checked in both directions); its
   *human* review property is worse. Nothing proposed replaces the reviewer.
2. **The hand-maintenance the move removes does not exist.** Frontmatter is hand-written too — the
   move relocates 36 lines into 36 files rather than deleting them. The review's framing of
   `SKILL_SCOPES` as a maintenance burden does not survive that observation.
3. **Cost for no observed defect.** 36 edits, a lint rule, three test rewrites and a re-scaffold,
   against zero scope defects since ADR-0005. Real cost, speculative benefit.

That is one substantive property plus a cost argument. It is enough to decline a migration nobody
is being hurt by, and it is not enough to call Option B wrong. If the owner prefers locality over
one-hunk review, Option B is a defensible call and this ADR should not be read as arguing
otherwise.

Two corrections ride along, neither a code change in this PR:

- **The enforcement is a test, and the ADR should say so.**
  `test_every_catalog_skill_is_reachable_by_a_declared_route`
  (`tests/test_sync_plugin_skills.py:286`) is what makes omission an error, together with
  `test_scope_declarations_name_only_real_skills` (line 303). `skill_scope()`'s
  `UnknownSkillScope` is a guard with no production caller — worth keeping as the right shape for
  a future caller, but it is not what protects the catalog today.
- **The `# pylint: disable=too-many-lines` comment at `engine/badger_lib.py:1` should stop citing
  ADR-0005.** Measured: removing `SKILL_SCOPES` entirely leaves the module at 991 of 1000 lines.

### Revisit condition

Stated as concretely as ADR-0005 stated its own. The earlier draft's "routing needs a third value"
trigger is retired — the ruling settled that, and `stackLocal` will never be needed. Any of these
makes the constant the wrong home, and each is a fact rather than a judgement:

1. **`SKILL.md` frontmatter gains another required enumerated key for any other reason.** At that
   point the template already carries the shape, the lint rule already enforces one, and the
   migration is a rider on work being done anyway — while the constant has become a second home
   for the same kind of fact.
2. **A non-Python consumer needs to read a skill's scope.** Every reader today is Python and
   imports `badger_lib` (`tooling/sync_plugin_skills.py:33-34`, `tooling/index_build.py:62-63`,
   `scaffold.py:158,266,618`, `skill_delivery.py:127`, `den-refresh/scripts/refresh.py:225`). The
   first `.mjs` validator, workflow step or downstream tool that needs it has no way in except the
   generated index — at which point the constant is not the source of truth in practice.
3. **A scope answer needs a qualifier the flat name→scope map cannot carry** — a condition, a
   version range, a per-agent answer. A dict of name to enum expresses exactly one unqualified
   fact per skill; the first qualified one belongs next to the skill it qualifies.

## Consequences

- **Directory-based routing is ratified.** ADR-0005's rejection of it is superseded outright.
  ADR-0010 is restated rather than merely tolerated: the stack directory decides ownership, the
  common stack's `SKILL_SCOPES` decides whether a universal skill ships unasked, and #261 is on
  the record as the evidence that scope is the wrong key for ownership.
- `stack_local_skills`' `not in SKILL_SCOPES` clause is a **guard, not the rule**. It excludes
  nothing at 0.93.1 and exists so a universal skill placed in a stack directory cannot be routed
  twice. Anyone reading it as the routing mechanism is reading the wrong line;
  `skills_for_stack` is the routing mechanism.
- `SKILL_SCOPES` stays hand-maintained at 36 entries, one line per new common skill, both
  directions checked by the two catalog-routing tests — narrowed in meaning from "which skills
  ship" to "which universal skills ship unasked".
- ADR-0005's Alternatives section is superseded in both its parts: "no script parses YAML
  frontmatter today" is false at 0.93.1, and "derive from directory layout" is what the project
  does. Its Decision — one declaration for the universal set, omission is an error,
  `code-review-checklist` is `default` — stands.
- A reader who finds a skill missing from `SKILL_SCOPES` should check which stack directory holds
  it before assuming an omission. For a skill under `features/common/skills/`, the omission is
  real and CI says so.

## Ruling

**Owner-ruled (2026-08-07): directory-based routing is what this project uses.** That half is
decided and recorded above; it ratifies what the code already does and already justifies.

**Still for decision: where the universal set's `default`/`optIn` scope is declared.** This ADR
stays **Proposed** on that question alone. Nothing in the tree changes until it is ruled on; no
production code is touched by the pull request that introduces it.

- **Accept Option C** (recommended, narrowly) — set Status to Accepted, add the forward-pointer
  line to ADR-0005 (the one edit an accepted ADR is allowed, per `docs/adr/README.md`), and file
  the `engine/badger_lib.py:1` comment correction as a follow-up.
- **Accept Option B instead** — a defensible call, not a mistake. Under the ruling the migration
  is 36 `SKILL.md` edits, one directory-scoped lint rule, three test rewrites and a re-scaffold.
  Build it reading each `SKILL.md` rather than `index.json`, so no generated artifact becomes the
  source of a shipping decision.
