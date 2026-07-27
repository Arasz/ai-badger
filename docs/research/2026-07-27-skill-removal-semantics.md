# How should a project say "I do not want this skill"?

**Date:** 2026-07-27
**Status:** Research — recommendation for a work package. Nothing implemented.
**Context:** #104 / `ef35fe3` made `den-refresh` deliver default-scope framework skills the
project never received. Correct fix; it exposed that manifest absence meant both "not wanted"
and "not yet known". This paper answers what "not wanted" should mean.

---

## 1. What is actually true today (verified, not read)

Every claim below was produced by running the shipped scripts against a scratch project at
`/tmp/skillrm1/proj`, scaffolded from this checkout at `0.33.0`.

### 1.1 A project cannot opt a skill out. At all.

The claim carried into the #104 changelog draft — *"the supported opt-out is
`badger_lib.SKILL_SCOPES` (`optIn` scope), not deleting the directory"* — **is false**.
`SKILL_SCOPES` is a module-level constant in `scripts/badger_lib.py`: framework source, shipped
read-only in the plugin cache. Nothing in a project's configuration reaches it.

Both plausible spellings of a project-side opt-out are rejected by the schema:

```
$ validate.py --kind config cfg-exclude.json    # {"skills": {"exclude": ["auto-wm"]}}
INVALID  - $: Additional properties are not allowed ('skills' was unexpected)

$ validate.py --kind config cfg-scope.json      # {"skillScope": {"auto-wm": "optIn"}}
INVALID  - $.skillScope: {'auto-wm': 'optIn'} is not one of ['default', 'local']
```

`config.schema.json` is `additionalProperties: false` and has no skill key of any kind.
`skillScope` is `default | local` — that is *install scope* (plugin vs. project), not selection.
There is no `skills`, no `exclude`, no per-skill anything. The workaround does not exist, and any
changelog sentence that names it must be rewritten.

### 1.2 Deleting the directory never worked, in either entry point

`welcome-ai-badger`: deleted `.ai-badger/skills/mcp-index`, re-ran `scaffold.py` with the
project's own config — restored. Expected; `--skills` defaults to every default-scope skill and
nothing passes it (`grep -rn -- "--skills"` finds one caller, a test).

`den-refresh`: deleted `.ai-badger/skills/call-behaviorist`, ran `refresh.py` — restored,
`refreshedSkills` lists all nine.

**And it would have been restored before #104 as well.** The pre-#104 list was the manifest's own
skill entries. Deleting a *directory* does not touch `manifest.json`, so the skill was still
named there and still re-copied. Reproduced with a probe that computes both lists:

```
manifest-only (pre-#104): [... call-behaviorist absent only after I also edited manifest.json ...]
union (post-#104)       : [... + call-behaviorist ...]
```

Removal-by-absence only ever "worked" if the user deleted the directory **and** hand-edited the
generated `manifest.json`. That is not a mechanism anyone was using; it is a way to corrupt
provenance. The #104 changelog's "removal-by-absence only ever worked in den-refresh" is
therefore also too generous to the old behaviour.

### 1.3 Deletion leaves the project *worse*, not skill-free

After `rm -r .ai-badger/skills/call-behaviorist`:

```
$ test -e .claude/skills/call-behaviorist && echo resolves || echo DANGLING
DANGLING
```

`features/{claude,copilot}/adjustments/adjust_skills.py` only *adds* links; nothing prunes a link
whose target is gone. So today, deleting a skill produces a broken discovery symlink that
survives until the skill is restored. Deletion is not a partial opt-out — it is a defect.

### 1.4 The hole is not skills-only, and the docs already promise the fix

`docs/getting-started.md:309` tells users, of invariants: *"Delete the ones you do not want
before committing."* Verified false:

```
$ rm .ai-badger/invariants/tdd-mandatory.md && refresh.py --target . …
$ ls .ai-badger/invariants/   # tdd-mandatory.md is back
```

The framework already made this promise in writing. That is the strongest single argument
against "document it as non-removable" (§3.4).

### 1.5 The two entry points still do not compute the same input

- `welcome-ai-badger` → `scaffold.DEFAULT_SKILLS = bl.default_skill_names()` — includes
  `auto-wm`, which lives in `features/claude/skills/`, while `scaffold_skills()` only resolves
  `common`. Every scaffold therefore prints
  `note: skill 'auto-wm' not in index common.skills — skipped`. Verified on a clean run.
- `den-refresh` → manifest ∪ `bl.default_skills_in(features/common/skills)` — no `auto-wm`.

The #104 fix aligned the *outcome*; the inputs are still two expressions. Any new mechanism must
not be a third.

---

## 2. Recommendation

> **Add an explicit exclusion list to `.ai-badger/config.json`, and enforce it in exactly one
> place: `Scaffolder.__init__`.**

```json
"exclude": {
  "skills": ["call-behaviorist", "mcp-index"]
}
```

New top-level `exclude` object in `config.schema.json`, `additionalProperties: false`, with
`skills` the only member for now (so `invariants` can be added later as a purely additive
change — see §6).

The enforcement point is the whole recommendation. `Scaffolder.__init__` receives `skills` and
every downstream consumer reads `self.skills`: `scaffold_skills`, `symlink_hermes_skills`,
`run_adjustments`' context, `_check_dependencies`. Filtering the list **once, inside the
Scaffolder**, means:

- `welcome-ai-badger` and `den-refresh` cannot disagree, because neither one applies the
  exclusion — they both hand their list to the same constructor that drops the excluded names.
  Their disagreement *was* the #104 bug; putting the filter in either caller re-creates it.
- Nothing needs to change in `refresh.py`.

**Semantics: an exclusion means "stop delivering", not "delete".** The first run after adding one
removes the discovery symlinks ai-badger placed (`.claude/skills/<n>`, `.github/skills/<n>`,
`~/.hermes/skills/<project>/<n>`), drops the manifest entry, and leaves
`.ai-badger/skills/<n>/` on disk with a note. Pruning the links is not a new power — it fixes
§1.3, where the framework already leaves dangling links today. Not deleting the directory is
deliberate: a config edit that silently `rm -rf`s project-visible content is a trap, and once the
links are gone the skill is invisible to the agent anyway, which is what the user asked for.

### The trade

**A second place decides which skills ship (ADR-0005 tension).** Accepted, on this reading:
ADR-0005 governs *supply* — which skills the framework offers and by which route — and its
failure mode is **omission**: a skill in no list ships to nobody, silently, forever.
An exclusion is *demand*: one project's answer to that offer. It cannot reproduce ADR-0005's
failure, because it is per-project, explicit, names its target, and never removes a skill from
the catalog's declaration. To keep that structurally true, exclusions are checked against the
catalog and reported when they match nothing (§4.2) — the offer stays the single source of what
exists.

**ADR-0006's test — "why is this not a fifth way to do one thing?"** The thing is *"the project
declines a framework-managed artifact."* There are currently **zero** ways to do it. This is the
first, not the fifth. Seed-once files and `ai-badger:keep-start` regions answer a different
question — "the project owns the *content* of a file the framework placed" — and neither can
express "do not place it."

---

## 3. Why the runners-up lose

### 3.1 A deletion/removal hook — *no trigger exists*

The maintainer's framing, and the one worth killing explicitly.

Nothing in ai-badger observes the filesystem between runs. There is no watcher, no daemon, and
no git hook installed over `.ai-badger/`. The framework's hooks are agent-session hooks
(`SessionStart`, `UserPromptSubmit`) — they fire on the agent's lifecycle, not on `rm`. The only
moment the framework can notice a deletion is the next scaffold or refresh, which is precisely
the moment that has to interpret absence — and cannot, without a record. A hook does not supply
the record; it needs one.

A hook the *user* runs (`den-refresh --forget foo`) is not a hook. It is a command that writes
persisted state, i.e. proposal 3.3 with a nicer front door — and it still has to write that state
somewhere, which returns the question to "config or manifest?"

The deeper objection: **deletion is not a declaration.** `.ai-badger/` is tracked in git.
Directories disappear from a working tree via `git checkout`, a revert, a bad merge, a stash pop,
a partial clone. Treating any of those as "the project has decided it does not want this skill"
converts routine VCS operations into silent policy changes, and the resulting state is invisible
in review — a diff that *removes* a directory and a diff that *declines* a skill would look
identical. A line in `config.json` shows up in the diff as an intention.

### 3.2 Tombstones in `manifest.json` — *right data, wrong file*

Works technically. Rejected on ownership.

`manifest.json` is generated provenance — ADR-0001 §4 defines it as the record of *what the
framework placed*, and `scaffold.py` rewrites it wholesale on every run. `feed-badger` diffs
project against framework through it. Recording non-placement inverts the file's meaning, and
un-excluding then requires hand-editing a generated file — the exact operation §1.2 shows is
already the only way to "remove" a skill and is already a way to corrupt provenance.

`config.json` is described in its own schema as *"the single machine-readable input the
scaffolded skills read."* A project decision belongs in the input, not the output. Tombstones
also fail the review test in §3.1: a regenerated manifest is noisy, so a tombstone appearing or
vanishing in a diff reads as machine churn.

### 3.3 Accept non-removable and document it — *cheaper, and false to the product*

The honest fallback, and I would recommend it if the framework were consistently authoritarian.
It is not. `agents`, `stacks`, `personaRouting`, `skillScope`, `mcpToolIndex.enabled`,
`statusLineCapture.enabled`, seed-once files, preserved regions and hand-authored-`CLAUDE.md`
preservation all say the same thing: **the project has a say.** Skills and invariants are the
only artifacts that say "you get what we ship".

And §1.4 is decisive: `docs/getting-started.md` already instructs users to delete what they do
not want. The repo has made the promise. Retracting it in documentation is a worse outcome than
making it true — especially for invariants, which are described in that same paragraph as
"non-negotiable rules you are agreeing to". A framework that re-imposes a rule you declined is
not a scaffolding tool.

---

## 4. Edge-case semantics, spelled out

### 4.1 Excluded, then re-included

Remove the name from `exclude.skills`. The next run delivers it fresh: `scaffold_skills` does
`rmtree` + `copytree`, so a stale directory left behind by the exclusion is fully replaced, the
manifest entry returns, and the discovery links are re-created. No residual state to clean, no
un-tombstoning.

Caveat, unchanged from today: project-local edits inside the skill directory are lost on
re-delivery. Seed-once files survive — `_stash_seed_once_skill_files` runs before the `rmtree`
and keys off the destination path, which the exclusion never touched.

### 4.2 Excluded, and the framework later stops shipping that skill

The exclusion goes inert. **It must not become a validation error.**
`refresh.py` validates `.ai-badger/config.json` and *refuses to refresh* when it is invalid — so
making an unknown name fatal would convert an upstream catalog deletion into a broken upgrade for
every project that had excluded it. Instead: `scaffold`/`refresh` emit
`exclusion 'foo' matches no catalog skill — safe to remove from config.json`. The same note
catches typos, which is the other reason to check.

This is ADR-0006's "detect, don't silently no-op" applied one notch softer, and the difference is
justified: `-extensions/` is a name nobody types by accident, so refusing costs nothing; a stale
exclusion is the *normal* consequence of upgrading, so refusing costs an upgrade.

### 4.3 An excluded skill something else depends on

Two real couplings exist in the catalog. One is a genuine constraint on the work package.

**Hooks — the constraint.** `features/common/hooks/hooks.json` wires
`${CLAUDE_PLUGIN_ROOT}/features/common/skills/task/scripts/session_start_hook.py`, and
`hook_wiring.py` rewrites `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` →
`${CLAUDE_PROJECT_DIR}/.ai-badger/skills/` **without checking the target exists**. Excluding
`task` would write two `SessionStart` commands in `.claude/settings.json` pointing at nothing.
The work package must skip rewritten commands whose script is absent, and note the skip.
(`prompt-markers` already degrades correctly — its branch globs the scaffolded skill dir and
emits `hook '<n>': no hook script found — skipped` when empty. The fix makes the other branch
behave like this one.)

**Extensions — not a coupling.** `extension.json.requires` holds config predicates
(`["agents=claude"]`), never skill names, across every extension in the catalog. There is no
skill-to-skill dependency graph, and none should be invented for this. If one ever appears, it
needs its own ADR.

**Self-exclusion — allowed.** `welcome-ai-badger` and `den-refresh` may be excluded. They are
also shipped by the plugin itself (`skills/` at the framework root), so a project that excludes
them keeps a working refresh path. No guard rail: a guard would be wrong for anyone driving
ai-badger purely from the plugin, which is the supported install.

### 4.4 An exclusion in a project whose manifest predates the mechanism

Nothing required. The exclusion lives in `config.json`, which `refresh.py` re-reads on every run;
`manifest.json` is rewritten wholesale each run and simply stops carrying the entry. No
migration, no version gate, no back-fill.

The reverse — an *older* framework reading a newer config — fails validation
(`additionalProperties: false`). That is correct and should not be softened: an exclusion silently
not applying is worse than a refusal that names the reason. Downgrades are not a supported path
(ADR-0001 §2).

---

## 5. Blast radius

| File | Change |
|---|---|
| `schemas/config.schema.json` | **schema change** — add `exclude: { skills: [string] }` |
| `scripts/badger_lib.py` | one helper (`excluded_skills(config)`) + catalog-membership check |
| `…/welcome-ai-badger/scripts/scaffold.py` | filter `self.skills` in `__init__`; emit notes |
| `…/welcome-ai-badger/scripts/hook_wiring.py` | skip rewritten commands whose script is absent (§4.3) |
| `…/welcome-ai-badger/scripts/drift.py` | `detect_new_items` must not report an excluded skill as new — otherwise every refresh nags about it |
| `features/claude/adjustments/adjust_skills.py` | prune owned links not in `skills` (`_ours`/`_manifest_targets` already exist for exactly this test) |
| `features/copilot/adjustments/adjust_skills.py` | same |
| `…/den-refresh/scripts/refresh.py` | **nothing** — that is the point |
| `schemas/manifest.schema.json` | **no change** — deliberate (§3.2) |
| docs | `getting-started.md`, both SKILL.mds, changelog entry, new ADR `0009-declining-a-framework-skill.md` |
| mirrors | `skills/` and `.ai-badger/skills/` copies regenerate via re-scaffolding the repo against itself + `sync_plugin_skills` (release ritual) |

**Version: minor — `0.34.0`.** ADR-0001 §3: `0.MINOR` is "anything that changes what scaffolding
*does* to a consumer repo". This adds a config surface, changes which skills are delivered, and
starts pruning symlinks. Not a patch.

**Do the two entry points agree?** Yes, by construction, *provided the filter lives in
`Scaffolder.__init__`*. Worth folding in as a small separate fix: `scaffold.DEFAULT_SKILLS`
should be `bl.default_skills_in(features/common/skills)` rather than `bl.default_skill_names()`,
so the two entry points agree on the *input* as well and the permanent `auto-wm` note (§1.5)
disappears. That is the last residue of the #104 bug.

**Tests that constrain the work.** `test_refresh_keeps_scaffolding_skills_recorded_only_in_the_manifest`
asserts a manifest-only skill (`auto-wm`) is retained; exclusion is explicit and must not break
manifest-only retention. `test_refresh_delivers_a_skill_added_to_the_catalog_after_the_project_was_scaffolded`
is the #104 regression test and must stay green with an empty `exclude`.

---

## 6. Follow-up, filed separately — not in this work package

Invariants have the identical hole (§1.4), and `docs/getting-started.md:309` documents a
behaviour that does not exist. The `exclude` object is shaped to take `invariants` as a second
member later, additively. Doing both at once doubles the surface for one decision; ship skills,
then decide whether an invariant a project can decline is still an invariant. (I suspect the
honest answer there is different from the one for skills — hence a separate decision.)

---

## 7. The changelog sentences

**For the #104 release (mechanism does not exist yet).** The drafted wording is false on two
counts — `SKILL_SCOPES` is framework source no project can set, and deleting a directory was
never an opt-out in either entry point. Replace with:

> **A framework skill you deleted comes back on the next `den-refresh`, as it already did on
> every `welcome-ai-badger` run.** Absence from the manifest meant both "not wanted" and "not yet
> known" and nothing could tell them apart; the two entry points now agree. There is currently no
> supported way for a project to decline a default-scope skill — deleting the directory is not
> one, and `badger_lib.SKILL_SCOPES` is framework source, not project configuration. A declared
> opt-out is tracked in #NNN.

**For the release that ships the mechanism:**

> **A project can now decline a framework skill.** Add it to `exclude.skills` in
> `.ai-badger/config.json`; neither `welcome-ai-badger` nor `den-refresh` will deliver it again,
> and the discovery symlinks ai-badger placed for it are removed. The copy under
> `.ai-badger/skills/` is left on disk for you to delete. Remove the name to get the skill back.
