# ADR-0003 — Hermes skill discovery via namespaced symlinks

**Status:** Accepted (2026-07-26) — reverses the decision shipped in `bafb952` for issue #58

> **Numbering note.** When this ADR was written, `docs/adr/` held two files numbered 0002.
> The collision was resolved in 0.22.0: the MCP tool index ADR became `0004-mcp-tool-index.md`
> and `0002-den-refresh-skill.md` kept its number. One number, one ADR.

## Context

### What Hermes actually does

Hermes resolves skills from exactly two places (`~/.hermes/hermes-agent/agent/skill_utils.py`):

- `get_skills_dir()` → `~/.hermes/skills/`
- `get_external_skills_dirs()` → the `skills.external_dirs` list in `~/.hermes/config.yaml`

`get_all_skills_dirs()` is the union of those two, and nothing else. **There is no project-local
skill discovery mechanism** — no `.hermes/skills/` in the project root, no walk up from `cwd`.

`iter_skill_index_files()` walks each root with `os.walk(skills_dir, followlinks=True)` and no
depth bound. Symlinks are followed, and a `SKILL.md` at any depth is discovered — verified
directly against the installed Hermes: a link `<namespace>/learned → .ai-badger/skills/learned`
yields `<namespace>/learned/apple/apple-notes/SKILL.md`. The only pruning is
`EXCLUDED_SKILL_DIRS` (VCS/venv/cache) and `SKILL_SUPPORT_DIRS` (`references/`, `templates/`,
`assets/`, `scripts/`) *inside a directory that already has a `SKILL.md`*.

### What #58 reported

Issue #58 ("user-scoped Hermes skills go stale after den-refresh") observed drift between
`.ai-badger/skills/` and `~/.hermes/skills/ai-badger/`: `den-refresh/SKILL.md` content differed,
`drift.py` content differed, `task/extensions/hermes` existed only in the project copy, and
`agent-skill-discovery` existed only in the user-scoped copy. It offered three options —
(a) delete the user-scoped copy, (b) have den-refresh sync it, (c) document a separate mechanism.

### Why the fix that shipped was wrong

`bafb952` chose option (a): it made `Scaffolder.symlink_hermes_skills()` a no-op, justified by
the docstring

> "Hermes discovers project skills via the project-local skill directory."

**That statement is false.** No such mechanism exists (see above). The change did not fix
staleness; it removed discovery, silently making every scaffolded ai-badger skill invisible to
Hermes.

**Symlinks were never the cause of the reported drift.** The removed implementation wrote
relative `os.path.relpath` symlinks. A symlink has no second copy of the content, so there is
nothing that can go stale — reading through the link always reads the project file. The
divergence #58 measured can only exist between two sets of real files, so it came from
*something other than* the symlink writer: on the reporting machine `~/.hermes/skills/ai-badger/`
held real directories from an earlier `hermes skills install`-style copy, alongside
`agent-skill-discovery`, which the framework has never produced. Option (a) was applied to a
mechanism that was not responsible for the symptom.

### A data-loss hazard in the original implementation

The pre-`bafb952` code rebuilt the namespace with:

```python
if namespace_dir.is_dir() and not namespace_dir.is_symlink():
    shutil.rmtree(namespace_dir)
```

`~/.hermes/skills/ai-badger/` on the maintainer's machine contains `agent-skill-discovery/` — a
real, Hermes-authored skill. The namespace directory demonstrably accumulates content ai-badger
did not place, and a plain revert would have deleted a user's learned skill on the next
re-scaffold. This is not acceptable, and it must be fixed as part of the restoration.

## Decision

**Restore `symlink_hermes_skills()`, namespaced per project, with two mandatory corrections.**

### 1. One relative symlink per skill under `~/.hermes/skills/<project-name>/`

The namespace directory stays a **real directory**; each scaffolded skill gets its own relative
symlink inside it, plus one symlink for the whole `learned/` tree when it exists. Per-skill links
(rather than one link for the entire `.ai-badger/skills/` tree) are what let Hermes-authored
content coexist in the same namespace: a namespace that is itself a symlink leaves Hermes nowhere
to write its own skills, and makes per-entry ownership undecidable.

One link is enough for `learned/` because `os.walk` is unbounded, so
`<namespace>/learned/<category>/<name>/SKILL.md` is discovered through it. A per-learned-skill
link would add churn on every sync for no discovery benefit.

### 2. Never `rmtree` the namespace — remove only what ai-badger owns

Ownership is decided per entry: an entry is ai-badger's if and only if it is a **symlink whose
target resolves inside this project's `.ai-badger/skills/`**. Those are unlinked and rebuilt;
every other entry — real directories, foreign symlinks — is left exactly as found. A real
directory that collides with a scaffolded skill name is skipped, never clobbered. If the
namespace path is itself a foreign symlink, the relink is abandoned rather than written through.

### 3. den-refresh re-links on every refresh

This is #58's legitimate half — its own option (b), implemented over links rather than copies.
`refresh.py` calls the relink unconditionally (not only when drift triggers a re-scaffold),
reading skill names from `.ai-badger/skills/` on disk, so a skill added upstream gains a link and
a skill removed upstream loses its stale one.

### 4. The false docstring is corrected

`symlink_hermes_skills()` now states what is true: Hermes discovers skills from
`~/.hermes/skills/` and `skills.external_dirs` only, and the per-project namespace directory is
what avoids the cross-project name collisions that made `external_dirs` unusable.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| **`skills.external_dirs` pointing at `.ai-badger/skills/`** | Shipped in v0.7.1 and reverted. It is a single global flat list: every project's `task`, `den-refresh`, … land in one namespace and collide. Adding a project is a config-file edit in the user's home, and removing one leaves a dangling entry. See `docs/audit-symlink-hermes-skills.md` §2. |
| **Copy skills into `~/.hermes/skills/<project>/`** | This is the mechanism that actually produced #58: two real copies that diverge on every framework bump. Fixing it means adding a sync step and a staleness check that symlinks make unnecessary. |
| **Project-local `.hermes/skills/`** | Hermes does not implement it. `get_all_skills_dirs()` has no project-relative root. |
| **Do nothing (leave `symlink_hermes_skills()` a no-op)** | Leaves every ai-badger skill undiscoverable by Hermes, which is the status quo since `bafb952` and the reason this ADR exists. |
| **A plain `git revert` of `bafb952`** | Restores the `shutil.rmtree(namespace_dir)` data-loss hazard and the now-known-false docstring. |

## Consequences

**Good.** `hermes skills list` in a scaffolded project shows that project's ai-badger skills
again. Skills are never duplicated, so they cannot go stale between copies — the staleness class
#58 reported becomes structurally impossible. `learned/` skills synced from Hermes are visible
through the same one link.

**Costs.** ai-badger writes into the user's home directory (`~/.hermes/skills/<project>/`) — a
side effect outside the target repo, gated on `hermes` being in `config.agents`. Links are
absolute-path-free but machine-local: they break if the project directory is moved, and are
repaired by the next scaffold or den-refresh (a dangling managed link is relinked, not left
broken).

**Load-bearing consequence for the learned-skills sync.** `followlinks=True` plus a restored
project link means `~/.hermes/skills/<project>/learned/…` resolves back into
`.ai-badger/skills/learned/`. The containment gates in
`features/common/hooks/learned_skills_sync.py` (`is_syncable`) are the only thing preventing
learned skills from re-importing themselves and framework skills from round-tripping in as
"learned". They must not be weakened. See
`docs/design/hermes-learned-skills-sync-impl-plan.md` §7 and research decision D9.

**Follow-up on #58.** The staleness it reported is addressed by symlinks-plus-relink rather than
by removing discovery. Its third question — what `agent-skill-discovery` is — is answered by
decision 2: it is not ours, and it is now explicitly preserved.
