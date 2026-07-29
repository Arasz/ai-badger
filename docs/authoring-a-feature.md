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
`index.json`, and every stack's `plugins.json` + `marketplaces.json` against
`schemas/*.schema.json`. Both are mechanical — no LLM, no network — so there's no reason to skip
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
| `plugins`                   | single file | the `plugins` array inside `features/<stack>/plugins/plugins.json`, if present (at most one per stack)         |
| `templates` (`common` only) | file/dir    | every top-level entry under `features/common/templates/`                                                       |

Two catalog files are deliberately **not** in that table, because `index_build.py` does not index
them and they have no entry in `index.json` — the scaffold reads them directly, so adding one
needs no index rebuild:

| file | rule |
|---|---|
| `external-tools` | `features/{common,stack}/external-tools.json` (`schemas/external-tools.schema.json`); last-writer-wins on name |
| `mcp-servers` | `features/{common,stack}/mcp-servers.json` (`schemas/mcp-servers.schema.json`); last-writer-wins on name |

Skill **extensions** use a directory-naming convention rather than a manifest field: a directory
at `features/<stack>/skills/<base>-extensions/<ext>/` attaches `<ext>` to the skill named
`<base>`, searched across all stacks (so a `github`-stack extension can attach to a base skill
living at `features/common/skills/`, as with `task`). Per-stack metadata — detection signals, implied
stacks, default commands — is read from an optional `features/<stack>/stack.json`, validated
against `schemas/stack.schema.json`, and folded into `index.json.stacks[stack].meta`.

## Adding a new stack

1. Create `features/<stack>/` with whichever feature subdirectories apply (`personas/`,
   `invariants/`, `instructions/`, `plugins/`, `skills/` — `templates/` is a `common`-only
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

An external tool injects *instructions*; an `mcp-servers.json` entry declares only a server a
stack recommends. Add `features/<stack>/mcp-servers.json`
(`schemas/mcp-servers.schema.json`) with `{"servers": [{"name": …, "command": …}]}`; optional
keys are `description`, `env`, `agentOverrides` (per-agent `command`/`args`) and
`scope` (`project`, the default, or `user`).

The scaffold reads common first, then stacks in `config.json` order, last-writer-wins on name;
a `config.externalTools` entry with `generate_mcp_json: true` overrides a stack entry of the
same name. Project-scoped servers land in `.mcp.json` (Claude and Hermes read it; Junie is
assumed to, never verified) and in `.github/copilot/mcp-config.json`; user-scoped ones are
written to the agent's own user config. No `index_build.py` run is needed — these files are read at scaffold time.

`targetAgents` validates against the schema but is **not read by any production code**: a
server scoped to one agent is still scaffolded for every active agent.

## Adding external tools

External tools are MCP servers whose **instructions** are injected into agent instruction
files (CLAUDE.md, HERMES.md) and whose **MCP server entries** are written to `.mcp.json`.
They follow the same common → stack → user merge pattern as `mcp-servers.json`.

1. Open (or create) `features/<stack>/external-tools.json`
   (`schemas/external-tools.schema.json`) and add a tool:
   ```jsonc
   {
     "tools": [
       {
         "name": "my-tool",
         "package": "my-tool-pypi-name",
         "command": "python3 -m my_tool serve",
         "instructions": "<!-- my-tool MCP tools -->\n## MCP Tools: my-tool\n\n...",
         "generate_mcp_json": true
       }
     ]
   }
   ```
2. The scaffold auto-merges: common first, then stacks (last-writer-wins on name),
   then `config.externalTools` from the consumer repo (user overrides).
3. No `index_build.py` run needed — these files are read at scaffold time, not indexed.

## Adding a new skill (or a `task` extension)

**A standalone, installable skill:**

1. Create `features/common/skills/<name>/` with a `SKILL.md` (plus any `scripts/`, `references/`
   subdirs the skill needs — these are copied as-is by `scaffold.py`). Skills are a regular
   feature under `features/common/` — see `framework-architecture.md` §1.
2. Run `index_build.py` then `validate.py --all`.

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
- [ ] New content filed under the right stack (or genuinely `common`) — no project-specific
      paths or domain-coupled models leaked into `common`.
- [ ] If you touched `skills/task`, grep it for stack-specific literals (`dotnet`,
      `Cosmos`, `gh `, a hardcoded repo) — none should be present outside `task/extensions/`.