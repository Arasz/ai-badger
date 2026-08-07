# ADR-0018 — Where the skill-routing declaration lives

**Date:** 2026-08-07
**Status:** Proposed — recommends **reaffirming** ADR-0005's mechanism on new grounds
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code (architect lane)
**Supersedes:** ADR-0005, on acceptance
**Scope:** `badger_lib.SKILL_SCOPES`, the catalog-routing tests, ADR-0010's stack-local rule

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

So the premise ADR-0005 rested on is dead, and the record now misleads whoever reads it next.
That much is settled. What the rest of this ADR settles is whether the *conclusion* should move
with the premise.

### What checking the code found that the review summary did not

The 2026-08-07 review (Theme D, item D2) put two costs on ADR-0005's account. Both shrink under
measurement.

- **"39 hand-kept entries."** There are **36** (14 `default`, 22 `optIn`), counted by importing
  the module. All 36 keys resolve to a directory under `features/common/skills/`, and all 36 of
  those directories are keys — the set is exactly closed in both directions today.

- **"A `too-many-lines` pylint disable serves the same lapsed premise."** Measured, not inferred.
  `engine/badger_lib.py` is 1032 lines against pylint's default `max-module-lines=1000` (no
  override in `pyproject.toml`, no `.pylintrc`). Deleting the dict literal and its comment
  (lines 690–730, 41 lines) leaves **991**. Removing the whole of `SKILL_SCOPES` buys **nine
  lines of headroom** against the limit — one feature's worth. The disable is a symptom of
  `badger_lib`'s size, which is D9's problem, not ADR-0005's; the comment on line 1 that
  attributes it to ADR-0005 is a misattribution that should be corrected whichever way this goes.

A third fact, found while tracing call sites, cuts the other way and is the most interesting
thing here:

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

### The tension ADR-0005 and ADR-0010 left unresolved

ADR-0005 rejected "derive from directory layout" outright: "Behaviour becomes invisible in
`git mv` and couples the decision to paths that other tooling resolves."

ADR-0010, a day later, adopted exactly that for stack-local skills.
`badger_lib.stack_local_skills` (line 891) defines stack-local as *"directory name **not in**
`SKILL_SCOPES`"*, and routing then follows the stack directory that holds it. Fifteen shipped
skills are routed today by absence from a dict:

| Stack | Skills |
|---|---|
| `claude` | `auto-wm` |
| `dotnet` | `dotnet-bdd-testing`, `dotnet-domain-modeling`, `dotnet-flaky-test-diagnosis`, `dotnet-hosted-service-review`, `dotnet-hosted-service-testing`, `dotnet-logger-message-design`, `dotnet-mcp-server`, `dotnet-sqlcipher-encryption`, `dotnet-system-commandline`, `dotnet-tool-publishing`, `observability-contract-review` |
| `hermes` | `cron-watchdog-authoring`, `hermes-plugin-development` |
| `mcp` | `mcp-tool-surface-testing` |

ADR-0010 was right about its immediate problem: `default` genuinely could not express "ships
automatically, but only for one stack". It solved it by making the *absence* of a declaration
meaningful — which is the shape ADR-0005 was written to abolish, one directory over. Nobody has
been bitten by it, because a stack directory is a strong signal and the routing test covers the
common stack. But it means the catalog has two routing mechanisms with an implicit boundary
between them, and neither ADR admits the other exists.

Any answer to D2 has to say what happens to those fifteen skills. That is what makes this a
harder question than "the parser exists now, so move the key".

## Options

### Option A — keep ADR-0005 exactly as it stands

Change nothing, including the record.

- **Cost:** the ADR's Alternatives section asserts a fact about the codebase that is false at
  0.93.1, in the one document a future reader consults before re-litigating this. Its Decision
  section credits `skill_scope()` with a guarantee a test actually provides. An ADR that misstates
  the tree is worse than no ADR, because it is read as authoritative.
- **Benefit:** zero work.

Rejected. Not because the mechanism is wrong, but because leaving a stale premise in the record is
how a decision gets reversed for bad reasons later.

### Option B — move the declaration into `SKILL.md` frontmatter

Add `scope:` to each `SKILL.md`, make it a rule-10 required key, have `index_build.py` stamp it
onto each index entry as it already does, and derive the routing helpers from that.

**What it buys**

- Locality. A skill is a directory; its routing becomes a property of the directory. `git rm -r`
  or `git mv` on a skill can no longer leave a stale key behind, and a new skill's author meets
  the field in the template rather than in a file 1000 lines away.
- It would let stack-local routing become explicit — a third value, `stackLocal`, declared on all
  fifteen skills above, retiring ADR-0010's absence-semantics and leaving one mechanism instead of
  two. This is the strongest thing in favour, and it is available *only* under this option.
- The parser exists, is already gated, and already refuses ambiguity. The cost ADR-0005 priced is
  now zero.

**What it costs**

- **Routing gains I/O.** `SKILL_SCOPES` is a constant: no root argument at the call site, no
  read that can fail, no value that can be stale. Under Option B every routing answer is either 51
  file reads or a lookup into generated `index.json`. The index route makes a
  *generated* artifact load-bearing for which skills reach a user — `index_build.py --check`
  guards its freshness in CI, but nothing does at runtime in a consumer's installed plugin.
  Production already has one such reader (`drift.py:204` consults `item.get("scope")`), so the
  path exists; making it the only path is a different risk.
- **`default_skill_names()` loses its no-argument form**, and `inclusion_notes`
  (`badger_lib.py:848`) would need a root threaded to it from
  `scaffold.py:336`.
- **One-place legibility goes.** "What ships to every consumer by default" is one hunk in a diff
  today. Under Option B, reviewing a change to the default set means reading 51 files or trusting
  a generated table. Given that this ADR family exists *because* a complete, correct skill shipped
  to nobody for its entire life and no reviewer noticed, the property of being reviewable in one
  glance is not decoration.
- **A 51-file migration**, plus the rule-10 change, plus rewriting three tests, plus a
  re-scaffold — for a set that has had zero routing defects since ADR-0005 landed.

**Evidence weighed:** a Wave 2 lane was asked to generate `docs/skills.md`'s table from
`SKILL_SCOPES` and declined, because the only machine-readable per-skill prose is each
`SKILL.md`'s `description:` — long second-person text written for a trigger matcher, not a reader.
It built a bidirectional consistency check instead (`tests/test_docs_match_the_catalog.py`).

That is evidence about what frontmatter can carry, and it does **not** argue against Option B:
`scope` is a two-value enum, not prose, and an enum is precisely what a frontmatter key holds well.
If anything it argues mildly *for* B — it shows this project's working instinct is to check
agreement between two sources rather than eliminate one, which is what the routing tests already
do for `SKILL_SCOPES` and would do just as well for a frontmatter key. It is not enough on its own
to move the decision.

### Option C — keep one Python constant; supersede the record, not the mechanism

`SKILL_SCOPES` stays where it is and keeps its shape. ADR-0005 is superseded so the file no longer
asserts a dead premise, the frontmatter alternative is re-rejected on grounds that are true at
0.93.1, and a fresh revisit condition is stated.

- **Cost:** one line per new skill, forever; 41 lines of `badger_lib`; the ADR-0010 tension
  survives, documented rather than resolved.
- **Benefit:** no migration, no I/O in the routing path, the default set stays reviewable in one
  hunk, and the record stops lying.

## Decision — recommended

**Option C. The declaration stays one Python constant in `badger_lib`. ADR-0005 is superseded for
its reasoning, not for its mechanism.**

The revisit condition firing obliges a re-examination; it does not oblige a reversal. Re-examined,
the case for moving rests on locality and on retiring ADR-0010's absence-semantics — both real,
neither urgent — and is paid for by turning a constant that cannot be stale into a read that can
be, in the one code path whose failure mode is "a skill silently reaches nobody". That is the exact
defect ADR-0005 exists to prevent, so it is the wrong trade to make speculatively.

The frontmatter alternative is therefore rejected again, on these grounds instead of the obsolete
one:

1. Routing must not depend on a generated artifact or on filesystem reads. Every scope answer
   today is a dict lookup with no I/O and no failure path — the value is decided at import, not
   at call time, so there is nothing to be stale and nothing to handle.
2. The default set must stay reviewable in one diff hunk. The failure this ADR family exists to
   prevent is an omission nobody noticed; a 51-file declaration is not reviewable by eye, and
   nothing proposed replaces the reviewer.
3. The hand-maintenance the move would remove does not exist. Frontmatter is hand-written too —
   the move relocates 36 lines into 36 files rather than deleting them.

Two things are corrected while the record is open, neither of which is a code change in this PR:

- **The enforcement is a test, and the ADR should say so.**
  `test_every_catalog_skill_is_reachable_by_a_declared_route`
  (`tests/test_sync_plugin_skills.py:286`) is what makes omission an error, together with
  `test_scope_declarations_name_only_real_skills` (line 303). `skill_scope()`'s
  `UnknownSkillScope` is a guard with no production caller — worth keeping as the correct shape for
  a future caller, but it is not what is protecting the catalog today, and ADR-0005 implied it was.
- **The `# pylint: disable=too-many-lines` comment at `engine/badger_lib.py:1` should stop citing
  ADR-0005.** Measured: removing `SKILL_SCOPES` entirely leaves the module at 991 of 1000 lines.
  The disable belongs to `badger_lib`'s size (D9), and saying otherwise sends the next reader to
  the wrong ADR.

### Revisit condition

Stated as concretely as ADR-0005 stated its own. Either of these makes the constant the wrong home,
and both are facts rather than judgements:

1. **Routing needs a third value.** The moment a skill's scope is not one of `default` / `optIn` —
   `stackLocal`, or "default for stack X" — the flat name→scope dict stops expressing the decision,
   and ADR-0010's absence-semantics has to be replaced by something explicit. Solving it by absence
   a second time is not an option; solving it in frontmatter, where each skill can carry its own
   qualified answer, is the natural shape.
2. **A non-Python consumer needs to read a skill's scope.** Every reader today is Python and
   imports `badger_lib` (`tooling/sync_plugin_skills.py:33-34`, `tooling/index_build.py:62-63`,
   `scaffold.py:158,266,618`, `skill_delivery.py:127`, `den-refresh/scripts/refresh.py:225`). The
   first `.mjs` validator, workflow step, or downstream tool that needs the scope has no way in
   except the generated index — at which point the constant is no longer the source of truth in
   practice, and should stop pretending to be.

## Consequences

- `SKILL_SCOPES` stays hand-maintained at 36 entries, one line per new skill, with both directions
  checked by the two catalog-routing tests. Unchanged from ADR-0005, and that is the point.
- ADR-0005's Alternatives section is superseded: its "no script parses YAML frontmatter today" is
  false at 0.93.1 and must not be cited again. Its Decision — one declaration, omission is an
  error, `code-review-checklist` is `default` — stands.
- The catalog keeps **two** routing mechanisms: `SKILL_SCOPES` for the 36 universal
  skills, and the stack directory for the 15 stack-local ones (ADR-0010). This ADR documents
  the boundary rather than removing it. A reader who finds a skill missing from `SKILL_SCOPES`
  should check which stack directory holds it before assuming an omission.
- **Open question, deliberately not decided here:** whether ADR-0010's "stack-local means absent
  from `SKILL_SCOPES`" should become an explicit declaration. It is the one thing Option B buys
  that Option C cannot, and it is a real weakness — a skill added under `features/common/skills/`
  fails CI when undeclared, while a skill added under `features/dotnet/skills/` cannot be
  undeclared, so the two halves of the catalog have different standards of proof. Resolving it
  needs its own ADR and its own decision, and it does not depend on this one.

## Ruling

This ADR is **Proposed**. Nothing in the tree changes until it is accepted; no production code is
touched by the pull request that introduces it.

- **Accept Option C** — set Status to Accepted, add the forward-pointer line to ADR-0005 (the one
  edit an accepted ADR is allowed, per `docs/adr/README.md`), and file the two corrections above as
  follow-ups (the `badger_lib.py:1` comment; ADR-0005's enforcement claim is corrected by this
  document itself).
- **Accept Option B instead** — this ADR is rewritten around it before any code moves; the
  migration is 51 `SKILL.md` edits, a rule-10 change, three test rewrites and a re-scaffold, and it
  should be taken together with the ADR-0010 question rather than before it.
- **Reject** — ADR-0005 stands unamended and its stale premise stays on the record; see Option A
  for why that is the worst of the three.
