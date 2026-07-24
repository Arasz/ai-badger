# Specification: Skills Sources, Hooks, and Adjustments Refactor

**Status:** Ready for implementation  
**Date:** 2026-07-24  
**Spec review:** Completed — all critical/medium/low findings addressed (see §14).

---

## 1. Problem Statement

1. **Plugin/skill split is artificial.** Claude Code treats plugins and skills as the same thing. ai-badger maintains a separate `plugins/` feature alongside `skills/`, creating confusion. The `plugins` feature should merge into `skills`.

2. **Skill sources are Claude-specific.** `marketplaces.json` only knows Claude Code marketplace URLs. Hermes has its own ecosystem (Hub, taps, well-known endpoints) with no representation.

3. **No per-agent skill installation logic.** Each agent installs skills differently, but the framework hardcodes Claude's `claude plugin install` commands.

4. **Hooks are scattered.** `hooks/hooks.json` at repo root, `ai_badger_hooks.py` buried in task-extensions — no unified structure.

5. **No adjustment mechanism.** The extension.json/extension.md pattern in task-extensions is ad-hoc. Need a schema-driven way to express agent-level adaptations.

---

## 2. Design Decisions

| # | Question | Decision |
|---|---|---|
| D1 | Filename | `skills-source.json` (plural), `skills.json` |
| D2 | Support field | Explicit `"common"` string = all agents |
| D3 | Adjustment scripts | Separate files per feature: `adjust_hooks.py`, `adjust_task.py`, etc. |
| D4 | Plugin→skill merge | Replace `features/{stack}/plugins/` with `features/{stack}/skills-source.json` + `features/{stack}/skills.json`. Extension-only features (e.g. github) use `{"skills": []}`. |
| D5 | Migration | Clean cut — remove old files, no backward compat |
| D6 | Naming | Keep `plugins-instructions.json` — "plugins" describes the installation mechanism, not the content type |

---

## 3. Proposed Structure

### 3.1 Feature catalog after refactor

```
features/
  common/
    skills/                    # In-repo skill catalog (unchanged)
      task/
        SKILL.md
        scripts/
        extensions/            # Skill-level extensions only
      welcome-ai-badger/
      feed-badger/
      ...
    skills-source.json         # External skill sources (NEW — replaces plugins/marketplaces.json)
    skills.json                # External skills to install (NEW — replaces plugins/plugins.json)
    hooks/                     # First-class hooks feature (NEW)
      hooks.json               # Claude Code hooks (moved from repo root)
      ai_badger_hooks.py       # Hermes plugin hooks (moved from task-extensions)
      mcp_index_hook.py        # MCP index auto-update hook (NEW)
      hooks-manifest.json      # Hook → agent mapping
    instructions/              # Unchanged
    invariants/                # Unchanged
    personas/                  # Unchanged
    templates/                 # Unchanged

  hermes/
    skills-source.json         # Hermes-specific skill sources (NEW)
    skills.json                # Hermes skills to install (NEW)
    adjustments/               # Agent-level adjustments (NEW)
      adjustment.json
      adjust_hooks.py
      adjust_task.py
    plugins-instructions.json  # How Hermes installs skills (NEW)
    scaffolding.json           # Unchanged
    instructions/              # Unchanged
    personas/                  # Unchanged

  claude/
    plugins-instructions.json  # How Claude installs skills (NEW)
    scaffolding.json           # Unchanged

  python/
    skills-source.json         # Python-specific sources (NEW — replaces plugins/)
    skills.json                # Python skills to install (NEW — replaces plugins/)

  github/
    skills/
      task-extensions/         # Skill-level extensions only (unchanged)
    skills.json                # {"skills": []} — extension-only marker

  copilot/
    plugins-instructions.json  # Empty instructions = nop (NEW)
    scaffolding.json

  junie/
    plugins-instructions.json  # Empty instructions = nop (NEW)
    scaffolding.json
```

### 3.2 Removed

```
features/common/plugins/       # Removed (merged into skills-source.json + skills.json)
features/python/plugins/       # Removed (merged)
features/hermes/skills/task-extensions/hermes/extension.json  # Removed (→ adjustments)
schemas/marketplaces.schema.json  # Removed (→ schemas/skills-source.schema.json)
schemas/plugins.schema.json       # Removed (→ schemas/skills.schema.json)
hooks/hooks.json                  # Moved to features/common/hooks/
```

### 3.3 Not removed (clarified)

- `features/github/skills/task-extensions/github/extension.json` — **STAYS**. This is a skill-level extension (per-stack, not per-agent). It has `requires` conditions that gate extension embedding. Adjustments are per-agent; GitHub extensions are per-stack. They serve different purposes.
- `features/hermes/skills/task-extensions/hermes/extension.md` — **STAYS**. Skill-level docs about delegation model.
- `features/hermes/skills/task-extensions/hermes/ai_badger_hooks.py` — **MOVES** to `features/common/hooks/`.

### 3.4 Kept (clarified)

```
features/hermes/skills/task-extensions/hermes/extension.md  # STAYS — skill-level docs
features/hermes/skills/task-extensions/hermes/ai_badger_hooks.py  # MOVES to features/common/hooks/
```

---

## 4. Schemas

### 4.1 `schemas/skills-source.schema.json` (replaces marketplaces.schema.json)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Arasz/ai-badger/schemas/skills-source.schema.json",
  "title": "ai-badger skill sources",
  "description": "Declares the external skill sources for a stack. Lives at features/<stack>/skills-source.json.",
  "type": "object",
  "required": ["sources"],
  "additionalProperties": false,
  "properties": {
    "sources": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["name", "type", "support"],
        "additionalProperties": false,
        "properties": {
          "name": { "type": "string", "minLength": 1 },
          "type": {
            "enum": ["marketplace", "hub", "tap", "url", "well-known"],
            "description": "marketplace = Claude plugin marketplace; hub = Hermes skills hub; tap = Hermes GitHub tap; url = direct URL; well-known = /.well-known/skills/ endpoint."
          },
          "source": { "type": "string", "minLength": 1, "description": "URL, repo path, or identifier." },
          "support": {
            "oneOf": [
              { "const": "common" },
              {
                "type": "array",
                "items": { "enum": ["claude", "copilot", "hermes", "junie"] },
                "minItems": 1
              }
            ],
            "description": "\"common\" = all agents; or array of specific agent names. Keep in sync with AGENT_NAMES in badger_lib.py."
          }
        }
      }
    }
  }
}
```

### 4.2 `schemas/skills.schema.json` (replaces plugins.schema.json)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Arasz/ai-badger/schemas/skills.schema.json",
  "title": "ai-badger external skills list",
  "description": "External skills to install from sources declared in sibling skills-source.json. Lives at features/<stack>/skills.json. Use {\"skills\":[]} for extension-only stacks.",
  "type": "object",
  "required": ["skills"],
  "additionalProperties": false,
  "properties": {
    "skills": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "source"],
        "additionalProperties": false,
        "properties": {
          "name": { "type": "string", "minLength": 1 },
          "source": { "type": "string", "minLength": 1, "description": "Name of a source in the sibling skills-source.json." },
          "scope": {
            "enum": ["default", "local", "user"],
            "default": "default"
          },
          "description": { "type": "string" }
        }
      }
    }
  }
}
```

Note: `minItems` is omitted so `{"skills": []}` is valid for extension-only stacks.

### 4.3 `schemas/plugins-instructions.schema.json` (NEW)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Arasz/ai-badger/schemas/plugins-instructions.schema.json",
  "title": "Agent skill installation instructions",
  "description": "Describes how an agent installs external skills. Lives at features/<agent>/plugins-instructions.json.",
  "type": "object",
  "required": ["agent", "instructions"],
  "additionalProperties": false,
  "properties": {
    "agent": { "type": "string" },
    "instructions": {
      "type": "object",
      "description": "Map of source type → installation commands. Keys must match skills-source.schema.json type enum.",
      "propertyNames": {
        "enum": ["marketplace", "hub", "tap", "url", "well-known"]
      },
      "additionalProperties": {
        "type": "object",
        "required": ["commands"],
        "additionalProperties": false,
        "properties": {
          "description": { "type": "string" },
          "commands": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Shell commands with {source}, {name}, {scope} placeholders."
          }
        }
      }
    }
  }
}
```

Note: `propertyNames` constraint (L7 fix) ensures instruction keys match source types.

### 4.4 `schemas/adjustment.schema.json` (NEW)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Arasz/ai-badger/schemas/adjustment.schema.json",
  "title": "Agent adjustment descriptor",
  "type": "object",
  "required": ["agent", "adjustments"],
  "additionalProperties": false,
  "properties": {
    "agent": { "type": "string" },
    "adjustments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["feature", "script"],
        "additionalProperties": false,
        "properties": {
          "feature": { "type": "string", "description": "Feature being adjusted (e.g. 'hooks', 'task')." },
          "description": { "type": "string" },
          "script": { "type": "string", "description": "Filename in the adjustments/ directory." }
        }
      }
    }
  }
}
```

### 4.5 `schemas/hooks-manifest.schema.json` (NEW — C2 fix)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Arasz/ai-badger/schemas/hooks-manifest.schema.json",
  "title": "ai-badger hooks manifest",
  "description": "Maps hooks to agents and their implementation. Lives at features/common/hooks/hooks-manifest.json.",
  "type": "object",
  "required": ["hooks"],
  "additionalProperties": false,
  "properties": {
    "hooks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "agents"],
        "additionalProperties": false,
        "properties": {
          "name": { "type": "string", "minLength": 1 },
          "description": { "type": "string" },
          "agents": {
            "type": "object",
            "additionalProperties": {
              "type": "object",
              "required": ["type", "entry"],
              "additionalProperties": false,
              "properties": {
                "type": { "enum": ["hooks-json", "plugin"] },
                "entry": { "type": "string", "description": "Filename in the hooks/ directory." },
                "method": { "type": "string", "description": "Plugin method name (for type=plugin)." },
                "event": { "type": "string", "description": "Hook event name (for type=hooks-json)." }
              }
            }
          }
        }
      }
    }
  }
}
```

### 4.6 Updated `schemas/index.schema.json` (C3 fix)

Add `hooks` and `adjustments` as valid feature keys, remove `plugins`. See §8.3.

---

## 5. Plugin Instructions (per agent)

### 5.1 `features/claude/plugins-instructions.json`

```json
{
  "agent": "claude",
  "instructions": {
    "marketplace": {
      "description": "Add Claude Code marketplace",
      "commands": ["claude plugin marketplace add {source}"]
    },
    "url": {
      "description": "Install from URL",
      "commands": ["claude plugin install {source}"]
    }
  }
}
```

### 5.2 `features/hermes/plugins-instructions.json`

```json
{
  "agent": "hermes",
  "instructions": {
    "hub": {
      "description": "Install from Hermes Skills Hub",
      "commands": ["hermes skills install {source}"]
    },
    "tap": {
      "description": "Add GitHub tap for skills",
      "commands": ["hermes skills tap add {source}"]
    },
    "url": {
      "description": "Install from direct URL",
      "commands": ["hermes skills install {source}"]
    },
    "well-known": {
      "description": "Install from well-known endpoint",
      "commands": ["hermes skills install well-known:{source}"]
    }
  }
}
```

### 5.3 Copilot / Junie

```json
{
  "agent": "copilot",
  "instructions": {}
}
```

Empty instructions = nop. These agents have no external skill system.

### 5.4 Scope resolution (M3, M5 fixes)

- `config.json`'s `pluginScope` is renamed to `skillScope` (still `"default" | "local"`)
- `{scope}` placeholder resolves per-entry from `skills.json`'s `scope` field, falling back to `config.skillScope`
- When a source type in `skills-source.json` has no matching instruction in `plugins-instructions.json`, the script **skips with a warning** (not an error) — e.g., a `"tap"` source for Claude gets a warning and moves on

---

## 6. Hooks Feature

### 6.1 Structure: `features/common/hooks/`

```
features/common/hooks/
  hooks.json                 # Claude Code hooks (moved from repo root)
  ai_badger_hooks.py         # Hermes plugin hooks (moved from task-extensions)
  mcp_index_hook.py          # MCP index auto-update (NEW)
  hooks-manifest.json        # Hook → agent mapping (executable, read by scaffold)
```

### 6.2 `hooks-manifest.json` (executable — L4 fix)

The manifest is **executable**: `scaffold.py` reads it to determine which hooks to install for which agents. For Claude, it merges hook entries into `hooks.json`. For Hermes, it copies the `.py` plugin files to the scaffolded project's plugin directory.

### 6.3 `ai_badger_hooks.py` placement (L1 fix)

The file is Hermes-specific (uses `yaml`, `ctx.register_hook()`). However, placing it in `features/common/hooks/` is correct because:
- The **logic** (drift detection, MCP index) is common
- The **registration API** is Hermes-specific
- The hooks-manifest maps it to the hermes agent only

This matches the pattern of common skills that contain agent-specific code (e.g., `task` skill has Hermes-specific extensions).

### 6.4 `mcp_index_hook.py` design

```python
def on_session_start(ctx):
    """Initialize MCP index if .ai-badger/mcp-tools.yaml doesn't exist."""
    ...

def post_tool_call(tool_name, args, result, duration_ms, ctx):
    """Detect mcp tool usage, trigger index rebuild if stale."""
    ...
```

---

## 7. Adjustments

### 7.1 `features/hermes/adjustments/adjustment.json`

```json
{
  "agent": "hermes",
  "adjustments": [
    {
      "feature": "hooks",
      "description": "Install ai_badger_hooks.py as Hermes plugin",
      "script": "adjust_hooks.py"
    },
    {
      "feature": "task",
      "description": "Embed Hermes delegation model into task skill",
      "script": "adjust_task.py"
    }
  ]
}
```

### 7.2 Script interface

Each `adjust_*.py`:

```python
def adjust(context: dict) -> dict:
    """Adjust feature for this agent.
    
    Args:
        context: {
            'framework_root': Path,
            'config': dict,
            'feature_dir': Path,    # source feature dir
            'target_dir': Path,     # scaffold target dir
        }
    Returns:
        {'applied': bool, 'files': list[str], 'notes': str}
    """
    return {'applied': False, 'files': [], 'notes': 'nop'}
```

### 7.3 Adjustment execution in scaffold pipeline (M2 fix)

`scaffold.py.run()` executes adjustments at this position:

```
1. scaffold_skills()        # Copy skills to .ai-badger/skills/
2. scaffold_hooks()         # Copy hooks to .ai-badger/hooks/ (NEW)
3. run_adjustments()        # Execute adjustments (NEW) — after hooks, before CLAUDE.md assembly
4. assemble_claude_md()     # Build CLAUDE.md from template + invariants + instructions
5. install_skills()         # Run plugins-instructions commands (replaces install_plugins)
6. write_manifest()
```

Adjustments run after hooks are scaffolded but before the final CLAUDE.md assembly, so `adjust_task.py` can modify the task skill's content before it's referenced in the assembled instructions.

### 7.4 Skill extensions vs adjustments

| Concept | Scope | Location | Purpose |
|---|---|---|---|
| **Skill extension** | Per-skill, per-stack | `features/{stack}/skills/{base}-extensions/{ext}/` | Extend a skill's content for a specific stack (e.g. GitHub PR workflow for `task`) |
| **Adjustment** | Per-agent | `features/{agent}/adjustments/` | Agent-level adaptations during scaffold (e.g. install Hermes hooks) |

---

## 8. Script Changes

### 8.0 `schemas/manifest.schema.json` (pluginScope → skillScope)

`manifest.schema.json` also has `"pluginScope": {"enum": ["default", "local"]}` at line 23. Rename to `skillScope` alongside the config schema change.

### 8.1 `scripts/badger_lib.py`

Update `FEATURES` list:
```python
FEATURES = ["skills", "personas", "invariants", "instructions", "templates", "hooks", "adjustments"]
```

Remove "plugins" — it's now part of "skills".

### 8.2 `scripts/index_build.py`

Discovery rules for new features:

| Feature | Shape | Discovery rule |
|---|---|---|
| `hooks` | JSON manifest + Python files | `features/{stack}/hooks/hooks-manifest.json` + all `.py` and `.json` files in the directory |
| `adjustments` | JSON descriptor + Python scripts | `features/{agent}/adjustments/adjustment.json` + all `.py` files referenced in it |
| `skills-source` | Single JSON file | `features/{stack}/skills-source.json` — indexed under the stack's `skills` feature as a `sources` sub-entry |
| `skills` (external) | Single JSON file | `features/{stack}/skills.json` — indexed under the stack's `skills` feature as an `external` sub-entry |

Index shape for a stack with both in-repo and external skills:
```json
{
  "common": {
    "skills": [
      {"name": "task", "path": "features/common/skills/task", "extensions": ["github", "hermes"]},
      {"name": "superpowers", "path": "features/common/skills.json", "external": true}
    ],
    "hooks": [
      {"name": "hooks-manifest", "path": "features/common/hooks/hooks-manifest.json"}
    ]
  },
  "hermes": {
    "adjustments": [
      {"name": "adjustment", "path": "features/hermes/adjustments/adjustment.json"}
    ]
  }
}
```

### 8.3 `scripts/validate.py`

Update `KIND_TO_SCHEMA`:
```python
KIND_TO_SCHEMA = {
    "config": "config.schema.json",
    "manifest": "manifest.schema.json",
    "index": "index.schema.json",
    "skills-source": "skills-source.schema.json",
    "skills": "skills.schema.json",
    "plugins-instructions": "plugins-instructions.schema.json",
    "adjustment": "adjustment.schema.json",
    "hooks-manifest": "hooks-manifest.schema.json",
}
```

Update `validate_all()`:
- Validate `skills-source.json` + `skills.json` per stack
- Validate `plugins-instructions.json` per agent
- Validate `adjustment.json` per agent with adjustments
- Validate `hooks-manifest.json`
- Runtime cross-reference check: every `skills.json` entry's `source` must exist in sibling `skills-source.json` (L3 fix)
- Remove old `plugins.json` / `marketplaces.json` validation

### 8.4 `schemas/index.schema.json` update (C3 fix)

- Remove `"plugins"` from the valid feature keys
- Add `"hooks"` and `"adjustments"` as valid feature keys
- Skills entries can have `"external": true` boolean

### 8.5 `scripts/install_plugins.py` (NEW)

**Relationship to scaffold.py:** `install_plugins.py` is a **library module** imported by `scaffold.py`, not a standalone CLI. The `scaffold.py.install_plugins()` method gets refactored to call `install_plugins.install_skills(config, framework_root, dry_run)`. The library owns scope resolution and command execution; `scaffold.py` owns the pipeline ordering.

```
Usage: import install_plugins; install_plugins.install_skills(config, root, dry_run)

For each agent in config.agents:
  1. Read features/{agent}/plugins-instructions.json
  2. For each stack's features/{stack}/skills-source.json:
     a. Filter sources by agent support (common = all, or agent in array)
     b. For each matching source type:
        - Look up instruction in plugins-instructions.json
        - If no matching instruction → warn and skip (M5 fix)
        - Run commands with {source} substitution
  3. For each stack's features/{stack}/skills.json:
     a. For each skill entry:
        - Resolve {scope}: entry.scope if set, else config.skillScope (M3 fix)
        - Look up instruction for the source's type
        - Run commands with {source}, {name}, {scope} substitution
```

Error behavior (M5 fix):
- Missing instruction for a source type → **warn and skip** (not error)
- Missing `skills-source.json` for a stack that has `skills.json` → **error**
- Missing referenced source name in `skills-source.json` → **error**

---

## 9. `config.json` Changes (M3 fix)

- Rename `pluginScope` → `skillScope`
- Update `schemas/config.schema.json` accordingly
- Same values: `"default" | "local"`

---

## 10. Implementation Order (revised — C4 fix)

Phase ordering ensures validation works at every step.

### Phase 1: Schemas + framework plumbing
1. Create `schemas/skills-source.schema.json`
2. Create `schemas/skills.schema.json`
3. Create `schemas/plugins-instructions.schema.json`
4. Create `schemas/adjustment.schema.json`
5. Create `schemas/hooks-manifest.schema.json`
6. Update `schemas/index.schema.json` — add hooks/adjustments, remove plugins
7. Update `schemas/config.schema.json` — pluginScope → skillScope
8. Update `schemas/manifest.schema.json` — pluginScope → skillScope
9. Update `scripts/badger_lib.py` — FEATURES list
10. Remove `schemas/marketplaces.schema.json` and `schemas/plugins.schema.json`
11. Remove `features/common/plugins/` and `features/python/plugins/` (before validation)
12. Update `scripts/validate.py` — KIND_TO_SCHEMA, validate_all()
13. Update `scripts/index_build.py` — discovery for new features
14. **Run `index_build.py` + `validate.py --all` — must pass**

### Phase 2: Plugin→skills data migration
1. Create `features/common/skills-source.json`
2. Create `features/common/skills.json`
3. Create `features/hermes/skills-source.json`
4. Create `features/hermes/skills.json`
5. Create `features/python/skills-source.json`
6. Create `features/python/skills.json`
7. Create `features/github/skills.json` (empty: `{"skills": []}`)
8. **Run `index_build.py` + `validate.py --all` — must pass**

### Phase 3: Per-agent plugin instructions
1. Create `features/{agent}/plugins-instructions.json` for each agent
2. Create `scripts/install_plugins.py` + tests
3. **Run tests + validation**

### Phase 4: Hooks extraction
1. Create `features/common/hooks/` directory
2. Move `hooks/hooks.json` → `features/common/hooks/hooks.json`
3. Move `ai_badger_hooks.py` → `features/common/hooks/ai_badger_hooks.py`
4. Create `features/common/hooks/hooks-manifest.json`
5. Create `features/common/hooks/mcp_index_hook.py` + tests
6. Remove `hooks/` directory at repo root
7. Update `.claude-plugin/plugin.json` hooks path if needed
8. **Run tests + validation**

### Phase 5: Adjustments
1. Create `features/hermes/adjustments/` structure
2. Create `adjust_hooks.py` + `adjust_task.py` + tests
3. Remove `features/hermes/skills/task-extensions/hermes/extension.json`
4. `extension.md` stays (explicitly — L8 fix)
5. **Run tests + validation**

### Phase 6: scaffold.py integration

> **Note:** `scaffold.py` lives at `features/common/skills/welcome-ai-badger/scripts/scaffold.py`, not `scripts/`. All references below are to this file.

1. Refactor `scaffold.py.install_plugins()` → generic `install_skills()` reading `plugins-instructions.json`
2. Add `scaffold_hooks()` method reading `hooks-manifest.json`
3. Add `run_adjustments()` method executing `adjust_*.py` scripts
4. Wire into `run()` pipeline per §7.3
5. Update `config.json` references: `pluginScope` → `skillScope`
6. **Run integration tests**

### Phase 7: Documentation
1. Update `docs/framework-architecture.md`
2. Update `docs/authoring-a-feature.md`
3. Update `docs/hermes-claude-compatibility.md`
4. Update README.md
5. Update task skill extension.md path references

### Phase 8: Integration verification
1. Run full test suite
2. Run `index_build.py` + `validate.py --all`
3. Verify scaffold round-trip on a test project

### Phase 9: Code and documentation consistency + quality review
Delegate a review sub-agent to verify the completed implementation:
1. **Schema consistency**: all new schemas validate, cross-references resolve, enums match `agents.schema.json`
2. **Script pipeline**: `badger_lib.py` FEATURES ↔ `index_build.py` discovery ↔ `validate.py` KIND_TO_SCHEMA ↔ `index.schema.json` — all aligned
3. **Doc accuracy**: every claim in `framework-architecture.md`, `authoring-a-feature.md`, `dictionary.md`, and the spec itself matches the actual code
4. **Test coverage**: every new schema has validation tests, every new discovery rule has index_build tests, every new script has unit tests
5. **Quality**: no dead code, no orphaned files, no stale references to removed `plugins/` or `marketplaces.json`
6. **Regression check**: existing tests still pass, `validate.py --all` clean, `index_build.py --check` clean

Fix findings before merging.

---

## 11. Risks

1. **index.json regeneration**: Every schema change means index.json needs rebuilding. Mitigated by running `index_build.py` after each phase.

2. **Test impact** (L10 fix — expanded): Tests needing updates:
   - `test_index_build.py` — new fixture data for hooks/adjustments
   - `test_scaffolding.py` / `test_scaffold.py` — new install_skills flow
   - `test_validate.py` — 5 new schemas + removed schemas
   - `test_mcp_index_hooks.py` — hardcoded path to `ai_badger_hooks.py` at `features/hermes/skills/task-extensions/hermes/` must change to `features/common/hooks/`
   - `conftest.py` — fixture updates for new directory structure
   - `test_detect.py` / `test_detect_additions.py` — if they reference plugins paths

3. **Task skill references**: `extension.md` references `ai_badger_hooks.py` at old path. Must update.

4. **Claude Code plugin.json**: `.claude-plugin/plugin.json` may reference `hooks/hooks.json`. Must update.

---

## 12. Discovery Rules (updated)

For `docs/authoring-a-feature.md`:

| Feature | Shape | Rule |
|---|---|---|
| `skills` (in-repo) | directory | any subdir of `features/{stack}/skills/` containing `SKILL.md` |
| `skills` (external) | single file | `features/{stack}/skills.json` entries, with sources from sibling `skills-source.json` |
| `personas` | file | any `*.md` in `features/{stack}/personas/` (excluding README.md) |
| `invariants` | file | any `*.md` in `features/{stack}/invariants/` (excluding README.md) |
| `instructions` | file | any `*.md` in `features/{stack}/instructions/` (excluding README.md) |
| `templates` (common only) | file/dir | every top-level entry under `features/common/templates/` |
| `hooks` | manifest + files | `features/{stack}/hooks/hooks-manifest.json` + referenced `.py`/`.json` files |
| `adjustments` | manifest + scripts | `features/{agent}/adjustments/adjustment.json` + referenced `.py` scripts |

---

## 13. Review Findings Tracker

| # | Severity | Finding | Status |
|---|---|---|---|
| C1 | Critical | `plugins-instructions.json` naming | **Accepted** — "plugins" = installation mechanism (D6) |
| C2 | Critical | Missing hooks-manifest schema | **Fixed** — §4.5 |
| C3 | Critical | index.schema.json not updated | **Fixed** — §8.4 |
| C4 | Critical | Phase ordering | **Fixed** — §10 reordered |
| M1 | Medium | scaffold.py integration | **Fixed** — §8.5, §10 Phase 6 |
| M2 | Medium | Adjustments in scaffold pipeline | **Fixed** — §7.3 |
| M3 | Medium | pluginScope rename | **Fixed** — §9 |
| M4 | Medium | Discovery rules for new features | **Fixed** — §8.2, §12 |
| M5 | Medium | install_plugins.py scope resolution | **Fixed** — §8.5 error behavior |
| L1 | Low | ai_badger_hooks.py in common/ | **Accepted** — §6.3 rationale |
| L2 | Low | Agent enum hardcoded | **Fixed** — shared `AGENT_NAMES` in `badger_lib.py` + `schemas/agents.schema.json` as canonical reference |
| L3 | Low | Cross-file reference | **Fixed** — §8.3 runtime check |
| L4 | Low | hooks-manifest executable vs docs | **Fixed** — §6.2 executable |
| L5 | Low | features/hermes dual role | **Noted** — existing pattern, no change |
| L6 | Low | Extension-only convention | **Fixed** — D4: `{"skills": []}` |
| L7 | Low | Instruction keys unconstrained | **Fixed** — §4.3 propertyNames |
| L8 | Low | extension.md fate | **Fixed** — §3.3, §10 Phase 5 step 4 |
| L9 | Low | validate.py --kind entries | **Fixed** — §8.3 |
| L10 | Low | Test impact underestimated | **Fixed** — §11 expanded |
| R1 | Critical | scaffold.py path wrong in spec | **Fixed** — §10 Phase 6 note |
| R2 | Medium | manifest.schema.json has pluginScope | **Fixed** — §8.0, §10 Phase 1 step 8 |
| R3 | Medium | github/extension.json fate unspecified | **Fixed** — §3.3 explicit stay |
| R4 | Medium | Phase ordering validation conflict | **Fixed** — plugins/ removal moved to Phase 1 step 11 |
| R5 | Low | test_mcp_index_hooks.py hardcoded path | **Fixed** — §11 test impact list |
| R6 | Medium | install_plugins.py/scaffold.py relationship | **Fixed** — §8.5 library module clarification |
