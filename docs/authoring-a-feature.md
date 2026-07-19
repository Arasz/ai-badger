# Authoring a feature

A practical how-to for adding to the ai-badger catalog. Read
[`framework-architecture.md`](framework-architecture.md) first if you haven't — this doc assumes
you know the `features/{stack|common}/{feature}` model, the root-`skills/` exception, and the
`config.json`/`manifest.json` contracts.

**The rule that matters most:** after *any* change to the catalog tree, run

```bash
python3 scripts/index_build.py
python3 scripts/validate.py --all
```

`index_build.py` regenerates `index.json` (script-generated, never hand-edited) by scanning the
tree with the discovery rules below. `validate.py --all` then checks the schemas self-check,
`index.json`, and every stack's `plugins.json` + `marketplaces.json` against
`schemas/*.schema.json`. Both are mechanical — no LLM, no network — so there's no reason to skip
them; a PR against ai-badger with a stale `index.json` should be treated as broken.

Install the one dependency once:

```bash
python3 -m pip install -r scripts/requirements.txt   # jsonschema
```

## Discovery rules (how `index_build.py` finds things)

| feature | shape | rule |
|---|---|---|
| `skills` (installable) | directory | any subdir of the repo-root `skills/` containing a `SKILL.md` — the one feature *not* under `features/` (see the root-`skills/` exception in `framework-architecture.md` §1) |
| `personas` | file | any `*.md` in `features/<stack>/personas/` (excluding `README.md`); name = filename stem |
| `invariants` | file | any `*.md` in `features/<stack>/invariants/` (excluding `README.md`); name = filename stem |
| `instructions` | file | any `*.md` in `features/<stack>/instructions/` (excluding `README.md`); name = filename stem |
| `plugins` | single file | the `plugins` array inside `features/<stack>/plugins/plugins.json`, if present (at most one per stack) |
| `templates` (`common` only) | file/dir | every top-level entry under `features/common/templates/` |

Skill **extensions** use a directory-naming convention rather than a manifest field: a directory
at `features/<stack>/skills/<base>-extensions/<ext>/` attaches `<ext>` to the skill named
`<base>`, searched across all stacks (so a `github`-stack extension can attach to a base skill
living at the root `skills/`, as with `task`). Per-stack metadata — detection signals, implied
stacks, default commands — is read from an optional `features/<stack>/stack.json`, validated
against `schemas/stack.schema.json`, and folded into `index.json.stacks[stack].meta`.

## Adding a new stack

1. Create `features/<stack>/` with whichever feature subdirectories apply (`personas/`,
   `invariants/`, `instructions/`, `plugins/` — `templates/` is a `common`-only convention;
   `skills/` under a stack is only for task extensions, not standalone installable skills, which
   always live at the repo-root `skills/` regardless of stack — keep to the pattern used by
   existing stacks unless you have a reason not to).
2. Optionally add `features/<stack>/stack.json` (`schemas/stack.schema.json`) with
   `detectionSignals` (glob/filename hints `detect.py` uses to auto-propose this stack — e.g.
   `"*.tsx"` for `react`), `requires` (other stacks this one implies, e.g. `react` implies `ts`
   + `node`), and default `commands`.
3. Populate at least one feature so the stack isn't empty scaffolding.
4. Run `index_build.py` then `validate.py --all`.

## Adding a new persona, invariant, or instruction

1. Pick the owning stack (or `common` if it's genuinely stack-agnostic — see the generalization
   test in the design doc: no project-specific paths, no domain-coupled models).
2. Add a single `*.md` file under `features/<stack>/personas/`, `features/<stack>/invariants/`,
   or `features/<stack>/instructions/`. The filename stem becomes its `name` in `index.json` — choose it
   deliberately, it's a stable public identifier consumed by `config.json.personaRouting` and by
   `scaffold.py`'s template assembly.
3. Keep the content self-contained: these files get concatenated into a target project's
   assembled `CLAUDE.md` (or persona/instruction files), so avoid assuming surrounding context
   that only exists in this repo.
4. Run `index_build.py` then `validate.py --all`.

## Adding a new plugin entry

A plugin entry curates an external Claude Code plugin + the marketplace it comes from, so a
project scaffold can install it without the agent inventing marketplace URLs at scaffold time.
Plugins are **compact**: each stack has at most one `features/<stack>/plugins/plugins.json`
(a single list of plugin entries) and one sibling `marketplaces.json` — there are no per-plugin
subdirectories.

1. Open (or create) `features/<stack>/plugins/plugins.json` (`schemas/plugins.schema.json`) and
   append a new object to its `plugins` array:
   ```jsonc
   {
     "plugins": [
       // … existing entries …
       {
         "name": "plugin-name-to-install",
         "marketplace": "<name in marketplaces.json>",
         "scope": "default",          // "default" | "local" | "user" — default = inherit init-time scope
         "description": "…"
       }
     ]
   }
   ```
2. If the entry's `marketplace` isn't already declared, add it to the sibling
   `marketplaces.json` (`schemas/marketplaces.schema.json`):
   ```jsonc
   { "marketplaces": [ { "name": "…", "source": "https://github.com/Owner/repo" } ] }
   ```
   `source` is a full GitHub repo URL, not `github:Owner/repo` shorthand.
3. Run `index_build.py` then `validate.py --all` — this also re-validates every stack's
   `plugins.json` + `marketplaces.json`, so a schema-breaking change anywhere under `plugins/`
   surfaces immediately.

Remember the scope semantics: `"default"` on the entry means "whatever scope the project chose
at `welcome-ai-badger` time (`default` | `local-only`)"; `"local"` and `"user"` on the entry
force that specific scope regardless of the project's choice. `welcome-ai-badger` itself never
offers a user-only *prompt* — only individual entries can declare `"user"` — so a project is
never silently pointed at the user's global config unless a specific curated entry says so.

## Adding a new skill (or a `task` extension)

**A standalone, installable skill:**

1. Create `skills/<name>/` at the **repo root** (not under `features/`) with a `SKILL.md` (plus
   any `scripts/`, `references/` subdirs the skill needs — these are copied as-is by
   `scaffold.py`). This is the root-`skills/` exception — see `framework-architecture.md` §1:
   the Claude Code plugin loader only discovers skills at the plugin root's `skills/`, and
   ai-badger's plugin `source` is `"./"`.
2. Run `index_build.py` then `validate.py --all`.

**An extension to an existing skill** (e.g. a new `task` extension):

1. Decide which stack owns the extension — usually the stack the extension's capability
   requires (a GitHub-specific extension lives under
   `features/github/skills/task-extensions/github/`, not under `common`).
2. Create `features/<stack>/skills/<base>-extensions/<ext>/` where `<base>` is the target
   skill's name (e.g. `task-extensions/github` attaches to the `task` skill at the repo root).
3. Gate the extension's activation on `config.json` fields it genuinely needs — don't hardcode
   assumptions the base skill can't verify. See `docs/framework-architecture.md` §5 for the
   `task` base+extensions split and its "zero stack-specific literals in the base" rule.
4. Run `index_build.py` — the extension will show up under the base skill's `extensions` array
   in `index.json` (see `common.skills[].extensions` in the schema) — then `validate.py --all`.

## Checklist before opening a PR

- [ ] `python3 scripts/index_build.py` run, `index.json` diff committed.
- [ ] `python3 scripts/validate.py --all` passes.
- [ ] New content filed under the right stack (or genuinely `common`) — no project-specific
      paths or domain-coupled models leaked into `common`.
- [ ] If you touched `skills/task`, grep it for stack-specific literals (`dotnet`,
      `Cosmos`, `gh `, a hardcoded repo) — none should be present outside `task-extensions/`.
