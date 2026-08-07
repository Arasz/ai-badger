# Authoring a feature

A practical how-to for adding to the ai-badger catalog. Read
[`framework-architecture.md`](framework-architecture.md) first if you haven't — this doc assumes
you know the `features/{stack|common}/{feature}` model and the `config.json`/`manifest.json`
contracts.

**The rule that matters most:** after *any* change to the catalog tree, run

```bash
python3 tooling/index_build.py
python3 tooling/validate.py --all
```

`index_build.py` regenerates `index.json` (script-generated, never hand-edited) by scanning the
tree with the discovery rules below. `validate.py --all` then checks the schemas self-check,
`index.json`, and every catalog JSON that `SCHEMA_INSTANCES` in `tooling/validate.py` maps —
each stack's `skills-source.json`, `skills.json`, `stack.json`, `stack-mcp.json`,
`mcp/*/meta.json` and the rest — against `schemas/*.schema.json`, then runs the catalog
cross-checks and `gates/skills_lint.py`. Both are mechanical — no LLM, no network — so there's no reason to skip
them; a PR against ai-badger with a stale `index.json` should be treated as broken.

Install the one dependency once:

```bash
python3 -m pip install -r engine/requirements.txt   # jsonschema
```

## Discovery rules (how `index_build.py` finds things)

| feature                     | shape       | rule                                                                                                           |
|-----------------------------|-------------|----------------------------------------------------------------------------------------------------------------|
| `skills` (installable)      | directory   | any subdir of `features/common/skills/` containing a `SKILL.md`                                                |
| `personas`                  | file        | any `*.md` in `features/<stack>/personas/` (excluding `README.md`); name = filename stem                       |
| `invariants`                | file        | any `*.md` in `features/<stack>/invariants/` (excluding `README.md`); name = filename stem                     |
| `instructions`              | file        | any `*.md` in `features/<stack>/instructions/` (excluding `README.md`); name = filename stem                   |
| `templates` (`common` only) | file/dir    | every top-level entry under `features/common/templates/`                                                       |
| `mcp`                       | directory   | any subdir of `features/<stack>/mcp/` containing a `meta.json`; one MCP server each. `server.md` beside it is injected into every agent file; `tools.json` carries curated tool intents |

These catalog files are deliberately **not** in that table, because `index_build.py` does not index
them and they have no entry in `index.json` — the scaffold reads them directly, so adding one
needs no index rebuild:

| file | rule |
|---|---|
| `stack-mcp` | `features/{common,stack}/stack-mcp.json` (`schemas/stack-mcp.schema.json`); last-writer-wins on name. Which servers a stack wants; the servers themselves are indexed catalog items under `features/<stack>/mcp/` |

The retired `mcp-servers.json` and `external-tools.json` are read by nothing
([ADR-0014](adr/0014-mcp-support-is-configuration-not-retrieval.md) decisions 2 and 3 — that
ADR's Decision section has seven items, not eight).
A stack still shipping either one gets a scaffold note naming it and pointing at
`stack-mcp.json`; its servers are not declared.

Skill **extensions** use a directory-naming convention rather than a manifest field: a directory
at `features/<stack>/skills/<base>-extensions/<ext>/` attaches `<ext>` to the skill named
`<base>`, searched across all stacks (so a `github`-stack extension can attach to a base skill
living at `features/common/skills/`, as with `task`). Per-stack metadata — detection signals, implied
stacks, default commands — is read from an optional `features/<stack>/stack.json`, validated
against `schemas/stack.schema.json`, and folded into `index.json.stacks[stack].meta`.

## Adding a new stack

1. Create `features/<stack>/` with whichever feature subdirectories apply (`personas/`,
   `invariants/`, `instructions/`, `skills/`, `mcp/` — `templates/` is a `common`-only
   convention). Keep to the pattern used by existing stacks unless you have a reason not to.
2. Optionally add `features/<stack>/stack.json` (`schemas/stack.schema.json`) with
   `detectionSignals` (glob/filename hints `detect.py` uses to auto-propose this stack — e.g.
   `"*.tsx"` for `react`), `requires` (other stacks this one implies, e.g. `react` implies `ts`
   + `node`), and default `commands`.
3. Populate at least one feature so the stack isn't empty scaffolding.
4. Run `index_build.py` then `validate.py --all`.

## Adding a new persona, invariant, or instruction

1. Pick the owning stack (or `common` if it's genuinely stack-agnostic — see the generalization
   test in the design doc: no project-specific paths, no domain-coupled models). An invariant
   that asserts a concrete file layout exists in the target repo belongs in an evidence-gated
   stack, never `common` — `features/changelog/` (detected from a `docs/changelog/*.md` tree,
   #130) is the worked example.
2. Add a single `*.md` file under `features/<stack>/personas/`, `features/<stack>/invariants/`,
   or `features/<stack>/instructions/`. The filename stem becomes its `name` in `index.json` — choose it
   deliberately, it's a stable public identifier consumed by `config.json.personaRouting` and by
   `scaffold.py`'s template assembly.
3. Keep the content self-contained: these files get concatenated into a target project's
   assembled `CLAUDE.md` (or persona/instruction files), so avoid assuming surrounding context
   that only exists in this repo.
4. Run `index_build.py` then `validate.py --all`.

Project-local invariants are NOT catalog items — no index rebuild, no stack, no exclusion by
name; a single-repo rule belongs in the project's `.ai-badger/invariants/local/` instead.

## Adding external skills (skill sources)

External skills are installed from sources declared in `skills-source.json`. Each stack has at
most one `features/<stack>/skills-source.json` and one `features/<stack>/skills.json`.

1. Open (or create) `features/<stack>/skills-source.json` (`schemas/skills-source.schema.json`)
   and add a source:
   ```jsonc
   {
     "sources": [
       // … existing sources …
       {
         "name": "my-source",
         "type": "marketplace",     // "marketplace" | "hub" | "tap" | "url" | "well-known"
         "source": "https://github.com/Owner/repo",
         "support": "common"        // "common" = all agents, or ["claude", "hermes"]
       }
     ]
   }
   ```
2. Open (or create) `features/<stack>/skills.json` (`schemas/skills.schema.json`) and add
   the skill entry:
   ```jsonc
   {
     "skills": [
       // … existing entries …
       {
         "name": "skill-name",
         "source": "my-source",     // references name in skills-source.json
         "scope": "default",        // "default" | "local" | "user"
         "description": "…"
       }
     ]
   }
   ```
3. Ensure the target agent has an instruction for this source type in its
   `features/<agent>/plugins-instructions.json`. If missing, add it.
4. Run `index_build.py` then `validate.py --all`.

Scope semantics: `"default"` means "whatever scope the project chose at scaffold time";
`"local"` and `"user"` force that specific scope. Use `{"skills": []}` for extension-only
stacks that have no external skills.

## Adding a stack-recommended MCP server

A server is two files. The **catalog directory** says what it is for; the **declaration** says
whether ai-badger may launch it (ADR-0014).

1. Create `features/<stack>/mcp/<server>/meta.json` (`schemas/mcp-server.schema.json`), plus
   `server.md` for the prose injected into every agent file and `tools.json`
   (`schemas/mcp-server-tools.schema.json`) for curated per-tool intents and tags. Keep
   `server.md` under 15 lines — it lands verbatim in every agent file, every session.
2. Add the server to `features/<stack>/stack-mcp.json` (`schemas/stack-mcp.schema.json`):
   ```jsonc
   {
     "servers": [
       {
         "name": "my-server",              // must name a features/*/mcp/<name>/ directory
         "command": "python3 -m my_server serve",
         "declare": true,                   // false (the default) = describe only
         "scope": "project",                // or "user"
         "env": { },
         "agentOverrides": { "hermes": { "command": "…" } }
       }
     ]
   }
   ```
3. Run `index_build.py` (the catalog directory is indexed) then `validate.py --all`.

Naming a server without `declare` says only that it is relevant to the stack; writing its launch
config is the louder claim and must be opted into. The scaffold reads common first, then stacks in
`config.json` order, last-writer-wins on name.

**Where a declared server lands.** ai-badger writes two files and proposes the rest (ADR-0014
decision 6):

| host | ai-badger writes | ai-badger proposes |
|---|---|---|
| Claude Code | `.mcp.json`, plus approvals in `.claude/settings.json` | `~/.claude/settings.json` for a `scope: user` server |
| Copilot CLI | `.github/mcp.json` — and `.mcp.json`, which it reads too | — |
| Copilot coding agent | nothing — its config lives in the repository settings UI | the JSON snippet, with `COPILOT_MCP_*` secret references |
| Hermes | nothing — `~/.hermes/config.yaml` is user-global and there is no project route | the `mcp_servers:` YAML snippet |

`.vscode/mcp.json` is VS Code Copilot Chat's own file and a different schema (top-level
`servers`, `inputs`, no per-server `tools`); ai-badger does not write it.

A server named in `config.mcp.decline` is not declared at all, and is removed from `.mcp.json`
and `.github/mcp.json` if an earlier run wrote it.

## Adding a new skill (or a `task` extension)

**A standalone, installable skill:**

1. Create `features/common/skills/<name>/` with a `SKILL.md` (plus any `scripts/`, `references/`
   subdirs the skill needs — these are copied as-is by `scaffold.py`). Skills are a regular
   feature under `features/common/` — see `framework-architecture.md` §1.
2. **Declare its scope in `engine/badger_lib.py`'s `SKILL_SCOPES`** — `default` or `optIn`.
   There is no fallback: an undeclared common-stack skill fails CI and, if it somehow did not,
   would ship to nobody ([ADR-0005](adr/0005-default-skill-set.md)).
3. Run `index_build.py` then `validate.py --all`, and `sync_plugin_skills.py` if the skill is
   `default` (that is what puts a copy under `skills/`, the only place Claude Code loads a
   plugin's skills from).

### `default` or `optIn`

- **`default`** — broadly applicable, no prerequisite: it ships to every scaffolded project and
  into the plugin copy without anyone asking.
- **`optIn`** — a specialised set a project chooses: it stays in the catalog, is not scaffolded,
  is not copied into `skills/`, and drift never reports it as a missing item.

An `optIn` skill is not invisible. Every `welcome-ai-badger` scaffold and every `den-refresh`
report carries an `availableOptIn` section naming each one the project has not installed, its
description (read from the skill's own `SKILL.md` frontmatter, so it cannot drift), and the
literal edit that adds it. A project opts in by adding the name to `config.json`:

```jsonc
{
  "include": { "skills": ["update-documentation"] }
}
```

`include` is the mirror of `exclude`, enforced at the same single point
(`Scaffolder.__init__`), so `welcome-ai-badger` and `den-refresh` cannot disagree — a
`config.json` edit is drift, so the next refresh delivers the skill on its own. **`exclude`
wins** if a name appears in both. Only `optIn` skills can be named: a name matching nothing, or
naming a skill that already ships by `default`, is reported as a note and never fails the run.

**An extension to an existing skill** (e.g. a new `task` extension):

1. Create `features/common/skills/<base>/extensions/<ext>/` where `<base>` is the target
   skill's name (e.g. `task/extensions/github` attaches to the `task` skill).
2. Add an `extension.json` with `requires` conditions gating activation on `config.json`
   fields the extension genuinely needs — don't hardcode assumptions the base skill can't
   verify. See `docs/framework-architecture.md` §5 for the `task` base+extensions split
   and its "zero stack-specific literals in the base" rule.
3. Run `index_build.py` then `validate.py --all`.

## Checklist before opening a PR

- [ ] `python3 tooling/index_build.py` run, `index.json` diff committed.
- [ ] `python3 tooling/validate.py --all` passes.
- [ ] A new common-stack skill is declared in `badger_lib.SKILL_SCOPES` — without it the skill
      ships to nobody, which is exactly how `code-review-checklist` lived its whole life
      unreachable ([ADR-0005](adr/0005-default-skill-set.md) §Context).
- [ ] New content filed under the right stack (or genuinely `common`) — no project-specific
      paths or domain-coupled models leaked into `common`.
- [ ] If you touched `skills/task`, grep it for stack-specific literals (`dotnet`,
      `Cosmos`, `gh `, a hardcoded repo) — none should be present outside `task/extensions/`.