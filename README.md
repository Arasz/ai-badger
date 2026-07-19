# ai-badger

**ai-badger** is the source of truth for custom Claude Code skills, personas, invariants, and
instructions used across projects. It is three things in one repo:

1. **A catalog** of reusable framework features (skills, personas, invariants, instructions,
   curated plugin bundles) organized by technology stack.
2. **A Claude Code marketplace** — install it once, and it hands you the tooling to use the
   catalog.
3. **A project scaffolder** — `welcome-ai-badger` reads a target repo, proposes a profile, and
   materializes a tailored slice of the catalog into it; `feed-badger` harvests generalizable
   improvements a project made back into the catalog via a draft PR.

Badger-themed name, professional-grade contents: the badger digs the framework into your repo
and digs improvements back out.

## The 3-layer model: `features/{stack | common}/{feature}`

Everything in the catalog is filed under a **stack** (a technology: `dotnet`, `azure`, `cosmos`,
`terraform`, `mcp`, `node`, `js`, `ts`, `react`, `css`, `github`, `angular`, or **`common`** for
stack-agnostic content) and a **feature** (a kind of asset: `personas`, `invariants`,
`instructions`, `plugins`, `templates` for `common` only, and stack-scoped skill *extensions*
under `plugins`'s sibling `skills/`).

```
features/<stack>/<feature>/<item>
```

- **personas**, **invariants**, and **instructions** are individual `*.md` files, named by
  filename stem.
- **plugins** is a single `plugins.json` (the list of plugins to install) plus a sibling
  `marketplaces.json` (where they come from) — at most one of each per stack.
- The **installable operational skills** (`welcome-ai-badger`, `feed-badger`, `task`, etc.) are
  the one exception: they live at the repo-root `skills/`, not under `features/` — see
  [`docs/framework-architecture.md`](docs/framework-architecture.md) for why.

A script-generated `index.json` at the repo root scans this tree and is the single source of
truth the scaffolder and feed tooling read — see
[`docs/framework-architecture.md`](docs/framework-architecture.md) for the full model.

## Install

```
/plugin marketplace add https://github.com/Arasz/ai-badger
/plugin install ai-badger
```

This installs the `skills` tooling: `welcome-ai-badger`, `feed-badger`, `task`,
`maintain-agent-instructions`, `auto-wm`, and `prompt-markers`.

## Quickstart

Run **`welcome-ai-badger`** inside a project you want to scaffold:

1. It detects stacks, present agents (`claude`, `copilot`, `junie`), and commands from the repo
   and asks you to confirm/refine a `.ai-badger/config.json` profile (project summary, domain,
   persona routing, plugin scope).
2. It materializes `.ai-badger/` — selected skills, personas, invariants, instructions, an
   assembled `CLAUDE.md`, and plugin installs — recording exactly what it wrote in
   `.ai-badger/manifest.json`.
3. Essential agent-discovery files (`CLAUDE.md`, `.github/copilot-instructions.md`,
   `.junie/AGENTS.md`) are copied into their conventional locations with a header pointing back
   at `.ai-badger/` as the source of truth, since some agent CLIs only look there.

Once you've customized things and want to contribute agnostic improvements back, run
**`feed-badger`**: it diffs the project's `.ai-badger/` tree against `manifest.json`, classifies
each change as project-specific or generalizable, generalizes the generalizable ones, and opens
a draft PR against `ai-badger` with the rationale.

See [`docs/authoring-a-feature.md`](docs/authoring-a-feature.md) for how to add new stacks,
personas, invariants, instructions, plugin entries, or skills to the catalog yourself.

## Architecture overview

```
ai-badger/
  index.json                     # SOURCE OF TRUTH: every feature for every stack, with paths (script-generated)
  README.md   LICENSE (MIT)   VERSION
  .claude-plugin/marketplace.json   # ai-badger is itself installable, plugin source "./"
  .claude-plugin/plugin.json        # the installable plugin wrapping the root skills
  schemas/                       # JSON Schema for every *.json model (index, config, manifest, plugins, marketplaces, stack…)
  scripts/
  docs/
    framework-architecture.md
    authoring-a-feature.md
    proxy-files-spike.md         # documented feature-plan, not built
    ai-badger-framework-design.md
  skills/                         # INSTALLABLE operational skills (root — the one exception, see below)
    task/ welcome-ai-badger/ feed-badger/ maintain-agent-instructions/ auto-wm/ prompt-markers/
  features/
    common/
      personas/{architect, test-engineer, code-reviewer}.md
      invariants/*.md              # agnostic invariant snippets
      instructions/*.md            # agnostic scoped instructions (e.g. documentation)
      plugins/plugins.json         # curated agnostic external plugins (single list)
      plugins/marketplaces.json    # marketplaces those plugins install from
      templates/                   # CLAUDE.md.tmpl, state.json skeleton, agent-instructions schema+validators
    dotnet/    {personas,invariants,instructions,plugins}/… + stack.json
    azure/     {personas,invariants,instructions,plugins}/…
    cosmos/    {invariants,instructions,plugins}/…
    terraform/ {instructions,plugins}/…
    mcp/       {instructions,plugins}/…
    github/    {plugins, skills/task-extensions/github}/…
    angular/ node/ js/ ts/ react/ css/  {personas,invariants,instructions,plugins}/…
```

Root `skills/` is the one exception to `features/<stack>/<feature>/`: Claude Code's plugin
loader only discovers skills at the plugin root's `skills/` directory, and ai-badger's plugin
`source` is `"./"` (the whole repo) — so the installable operational skills must sit at the repo
root, not nested under `features/`. Stack-scoped skill *extensions* (e.g.
`features/github/skills/task-extensions/github/`) still live under `features/`, since they are
not independently installed — `index_build.py` attaches them to their base skill by directory
convention.

### Framework overview — structure & data flow

```mermaid
flowchart TB
  subgraph FW["ai-badger repo (source of truth)"]
    IDX["index.json\n(script-generated)"]
    SCH["schemas/*.schema.json"]
    subgraph CAT["catalog: features/{stack|common}/{feature}"]
      COMMON["common/\npersonas·invariants·instructions·plugins·templates"]
      STACKS["dotnet · azure · cosmos · terraform · mcp\nnode · js · ts · react · css · github · angular"]
    end
    SKILLSDIR["skills/ (root — plugin-loader exception)\nwelcome · feed · task · maintain · auto-wm · prompt-markers"]
    MKT[".claude-plugin/marketplace.json\n+ installable plugin"]
  end
  IDXbuild["index_build.py"] -->|scans CAT + skills/| IDX
  CAT --> IDXbuild
  SKILLSDIR --> IDXbuild
  MKT -->|/plugin install| SKILLS["installed skills:\nwelcome · feed · task · maintain · auto-wm · prompt-markers"]
  IDX -. read .-> SKILLS
  CAT -. copied features .-> PROJ
  subgraph PROJ["target repo (.ai-badger/)"]
    CFG["config.json\n(agent-authored)"]
    MAN["manifest.json\n(script-written provenance)"]
    OUT[".ai-badger/ files\n+ CLAUDE.md / copilot / junie copies"]
  end
  SKILLS -->|welcome| PROJ
  PROJ -->|feed: manifest diff| PRD["draft PR → ai-badger"]
  PRD -. merges new features .-> CAT
```

### welcome-ai-badger — logic flow

```mermaid
flowchart TD
  A["run welcome-ai-badger"] --> B["detect.py: scan repo + user scope"]
  B --> C["proposed config\n(stacks, agents, commands, sourceControl)"]
  C --> D["AGENT: refine into config.json\n(summary, domain, persona routing)"]
  D --> E{"ambiguous?"}
  E -->|yes| F["ask clarifying question"] --> D
  E -->|no| G["ask plugin scope: default | local-only"]
  G --> H["validate.py config.json vs schema"]
  H -->|invalid| D
  H -->|valid| I["scaffold.py"]
  I --> J["validate outputs + agent-instruction validators"]
  J --> K["report files written + gaps"]
```

`feed-badger` mirrors this in reverse: it diffs the project's `.ai-badger/manifest.json`
against the current `.ai-badger/` tree to find candidate additions, has the agent classify and
generalize them, places them into the right `features/{stack}/{feature}`, regenerates `index.json`, and
opens a draft PR — see [`docs/framework-architecture.md`](docs/framework-architecture.md) for
the full diagram.

## Requirements

The framework scripts (`index_build.py`, `validate.py`, `detect.py`, `scaffold.py`, …) are
mechanical Python with one dependency:

```bash
python3 -m pip install -r scripts/requirements.txt   # jsonschema
```

## License

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 Rafał Araszkiewicz.
