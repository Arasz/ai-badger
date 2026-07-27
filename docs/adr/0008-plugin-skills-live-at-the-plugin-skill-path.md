# ADR-0008 — Plugin Skills Live at the Plugin Skill Path, and Only There

**Date:** 2026-07-27
**Status:** Accepted
**Author:** Rafał Araszkiewicz (Arasz) with Claude Opus 5
**Supersedes:** None

## Context

The plugin shipped its skills to `.claude/skills/`. Claude Code never looked there, so an
installed, enabled `ai-badger` plugin contributed **zero** skills — `/den-refresh`,
`/welcome-ai-badger` and `/feed-badger` were not things a user could type, while the plugin
description promised all of them (issue #103).

The path is not a matter of interpretation. Claude Code 2.1.220's plugin loader reports, per
plugin, which directory it scans:

```
Checking plugin ai-badger: skillsPath=none, skillsPaths=0 paths
Checking plugin superpowers: skillsPath=exists, skillsPaths=0 paths
Attempting to load skills from plugin superpowers default skillsPath: …/superpowers/6.2.0/skills
```

A probe plugin built for this decision confirmed the rule in both directions: skills under
`<plugin-root>/skills/` loaded; a skill under the plugin's own `.claude/skills/` did not load at
all. `.claude/skills/` is the **project** skill path — how this repo dogfooded its own catalog —
and it is not a plugin skill path. `plugin.json` also accepts a `skills` array of explicit
directories, which would let the manifest point at the old location.

The same probe settled what two same-named skills do, since this repo has already been burned by
duplicate registration (`docs/changelog/0.28.1-plugin-hooks-load-again.md`, where a
double-declared hooks file aborted the plugin's entire hook load). A skill present in both a
project's `.claude/skills/` and an installed plugin appears **twice**, once bare and once
namespaced:

```
probeboth
probeprojonly
probeplug:probeboth
probeplug:probeplugonly
```

No error, no shadowing, no abort — but two entries, two descriptions, and an agent that has to
pick. That is a soft cost paid on every turn, and the more so because a stale copy under one of
the two names is exactly the failure #103 calls "a worse failure mode than an absent one".

## Decision

**`skills/` at the plugin root is the one place plugin skills live.** `sync_plugin_skills.py`
writes there; the ten default-scope copies moved out of `.claude/skills/` and none were left
behind.

That gives each directory exactly one owner:

- `skills/` — the plugin surface, generated from `features/` by `sync_plugin_skills.py`, checked
  by `--check` in pre-commit and CI.
- `.claude/skills/` — the *project* surface, in this repo as in any other: what the `claude`
  stack's scaffolding writes, plus skills managed by tools outside this catalog
  (`debug-issue`, `explore-codebase`, `refactor-safely`, `review-changes`).

`tests/test_plugin_manifest.py::TestPluginExposesItsSkills` asserts every default-scope skill has
a `SKILL.md` under `skills/`, that every skill the plugin *description* names is actually shipped,
that the sync target is that path, and that none of it is git-ignored. The bug shipped for
thirteen versions because nothing checked; this is what checks.

## Alternatives considered

**Point `plugin.json`'s `skills` array at `.claude/skills/`.** Works, and keeps the diff to one
manifest key. Rejected: it re-introduces the hand-maintained list ADR-0005 collapsed — a skill
absent from the array ships to nobody, silently, which is the exact failure that ADR made
impossible. It also opts out of the convention every other plugin follows, so the next reader has
to be told why.

**Keep both locations.** Rejected for what the probe showed: every session inside the checkout,
and every scaffolded project whose user also installs the plugin, would carry each skill twice.
Two copies also means two things to keep in sync — the shape ADR-0005 and ADR-0006 have each
already refused once.

**Symlink `.claude/skills/<name>` → `../../skills/<name>`** so in-repo sessions keep the skills
from a single copy. Rejected because `.claude/skills/` belongs to the scaffold now (#103's second
root cause makes the `claude` stack symlink `.ai-badger/skills/*` there), and a hand-made symlink
into `skills/` would be a second writer to a directory that just got its first.

**Enable the repo's own plugin from `.claude/settings.json`** (`extraKnownMarketplaces` +
`enabledPlugins` pointing at `./`), so contributors get the skills through the shipping path.
Tried; the probe session loaded no plugin from it, so it is not something to rely on.

## Consequences

- The plugin contributes its ten skills. Verified end to end against the real loader:
  `Loaded 10 skills from plugin ai-badger default directory`, invocable as `ai-badger:<name>`.
- A contributor working *inside this checkout* who has not installed the plugin sees no ai-badger
  skills in that session, until the `claude` stack's scaffolding populates `.claude/skills/` on
  the next self-scaffold. Content is unaffected: `.ai-badger/skills/` and `features/` both still
  hold it, and `--plugin-dir .` loads the checkout as the plugin it is.
- Anything that knew the old location is now wrong and was updated: `docs/scripts.md`,
  `docs/getting-started.md`, `CONTRIBUTING.md`, the README layout tree.
- `skills/` is a non-dot directory, so tools that skipped `.claude/` by convention now see ten
  copies of catalog code. It is listed in `.code-review-graphignore` for that reason.
- `MANAGED_EXTERNALLY` in the sync script no longer guards a directory the script writes to. It
  is kept as a filter on names the framework must never publish, not as a shield for someone
  else's files.
