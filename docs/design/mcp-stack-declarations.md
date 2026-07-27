# Design: MCP Server Declarations for Stack Features

**Status:** Implemented in 0.13.0 — kept as the design record, not a plan
**Author:** ai-badger subagent
**Date:** 2026-07-26
**Related:** `externalTools` in config.json, `features/mcp/` stack

---

## 1. Overview and Motivation

### Problem

Today, ai-badger has two mechanisms for MCP server integration, neither of which solves the "stack-needs-this-server" case well:

1. **`externalTools` in config.json** — User-declared. The user manually adds tool entries with command, instructions, and `generate_mcp_json` flag. This is for *ad-hoc* project-specific tools, not framework-curated stack requirements.

2. **`features/mcp/` stack** — Teaches agents how to *develop* MCP servers. Irrelevant to *consuming* them.

There is no way for `features/python/` to declare "Python projects benefit from the `pyright` MCP server" and have that automatically scaffolded into the project's agent configs. Users must discover, configure, and wire MCP servers manually per agent.

### Goal

Add a **`mcp-servers.json`** file to stack feature directories that declares which MCP servers a stack recommends. The scaffold and refresh pipelines read these declarations and produce agent-specific MCP config files automatically.

### Non-Goals

- Auto-installing MCP server packages (scaffold is config-only; install is advisory)
- Runtime health checks for MCP servers
- Replacing `externalTools` (they remain for user-declared project-specific tools)

---

## 2. `mcp-servers.json` Schema

### Location

```
features/{stack}/mcp-servers.json    # e.g. features/python/mcp-servers.json
features/common/mcp-servers.json     # servers needed by all projects
```

### Design Principles

- **Simpler than `externalTools`** — No `instructions` field (stack-declared servers don't need custom instruction injection; if they do, use `externalTools` instead)
- **Transport-agnostic** — Declare `command` + `args`; the scaffold maps to each agent's format
- **Optional per-agent overrides** — Most servers use the same command across agents; overrides are rare and supported
- **Merge-safe** — Multiple stacks can declare the same server without conflict

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/Arasz/ai-badger/schemas/mcp-servers.schema.json",
  "title": "Stack MCP Server Declarations",
  "description": "Declares MCP servers recommended by a stack feature. Scaffolded into agent-specific config files during welcome-ai-badger and den-refresh.",
  "type": "object",
  "required": ["servers"],
  "additionalProperties": false,
  "properties": {
    "$schema": { "type": "string" },
    "servers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "command"],
        "additionalProperties": false,
        "properties": {
          "name": {
            "type": "string",
            "minLength": 1,
            "description": "Unique MCP server identifier (e.g. 'pyright', 'code-review-graph'). Used as the key in agent config files."
          },
          "command": {
            "type": "string",
            "description": "Launch command (e.g. 'uvx mcp-server-pyright', 'npx -y @modelcontextprotocol/server-filesystem'). Split on whitespace for command + args."
          },
          "description": {
            "type": "string",
            "description": "Human-readable purpose (for docs/notes, not injected into agent instructions)."
          },
          "env": {
            "type": "object",
            "additionalProperties": { "type": "string" },
            "description": "Required environment variables. Scaffold includes them in agent configs."
          },
          "agentOverrides": {
            "type": "object",
            "description": "Per-agent command overrides when the default command doesn't work for a specific agent.",
            "additionalProperties": false,
            "properties": {
              "claude": { "$ref": "#/$defs/agentOverride" },
              "hermes": { "$ref": "#/$defs/agentOverride" },
              "copilot": { "$ref": "#/$defs/agentOverride" },
              "junie":  { "$ref": "#/$defs/agentOverride" }
            }
          },
          "scope": {
            "enum": ["project", "user"],
            "default": "project",
            "description": "project = repo-level config (.mcp.json, .github/). user = user-level config (~/.hermes/config.yaml, ~/.claude/settings.json)."
          }
        }
      }
    }
  },
  "$defs": {
    "agentOverride": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "command": { "type": "string", "description": "Agent-specific launch command override." },
        "args": { "type": "array", "items": { "type": "string" }, "description": "Agent-specific args override." }
      }
    }
  }
}
```

### Example: `features/python/mcp-servers.json`

```json
{
  "$schema": "../../../schemas/mcp-servers.schema.json",
  "servers": [
    {
      "name": "pyright",
      "command": "uvx mcp-server-pyright",
      "description": "Python type checking and language intelligence"
    }
  ]
}
```

### Example: `features/github/mcp-servers.json`

```json
{
  "$schema": "../../../schemas/mcp-servers.schema.json",
  "servers": [
    {
      "name": "github",
      "command": "npx -y @modelcontextprotocol/server-github",
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": ""
      },
      "description": "GitHub API access for repos, issues, PRs"
    }
  ]
}
```

### Example with agent override

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx -y @modelcontextprotocol/server-filesystem /tmp",
      "agentOverrides": {
        "hermes": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
      }
    }
  ]
}
```

---

## 3. Agent-Specific Scaffolding Strategy

### 3.1 Claude Code — `.mcp.json`

**Current state:** `_generate_mcp_json()` already writes `.mcp.json` from `externalTools`.

**Extension:** Add a second data source — stack-declared servers. Merge them into the same `.mcp.json`.

**Format:** `{ "mcpServers": { "name": { "command": "...", "args": [...], "env": {...} } } }`

**Implementation:** New method `_generate_stack_mcp_json()` that:
1. Collects all `mcp-servers.json` files from active stacks + common
2. Parses command into `{ command, args }` (split on whitespace)
3. Merges with existing `.mcp.json` (never overwrites entries the user already has)
4. Writes the result

**Key:** Stack-declared servers and `externalTools` servers merge into the same `.mcp.json`. If both declare the same name, `externalTools` wins (user intent > framework recommendation).

### 3.2 Hermes Agent — `~/.hermes/config.yaml`

**Current state:** No scaffolding for Hermes MCP servers.

**Extension:** New method `_scaffold_hermes_mcp()` that:
1. Reads merged stack + external MCP servers
2. Generates a YAML snippet for `~/.hermes/config.yaml` `mcp` section
3. Uses **merge semantics** — reads existing config, adds new servers, preserves existing ones

**Format:**
```yaml
mcp:
  servers:
    pyright:
      command: uvx
      args: ["mcp-server-pyright"]
```

**Scope decision:** For `scope: project`, write to `.mcp.json` in project root (Hermes reads it). For `scope: user`, append to `~/.hermes/config.yaml` — but scaffold should NOT modify user-global config without explicit consent. **Recommendation:** Stack declarations default to `scope: project` → write `.mcp.json`. Only `scope: user` servers get advisory notes telling the user what to add to their Hermes config.

**Implementation approach:** Hermes already reads `.mcp.json` from project root, so for project-scoped servers, writing `.mcp.json` is sufficient (same as Claude). For user-scoped servers, emit a note in the scaffold output with the YAML snippet the user should add manually.

### 3.3 GitHub Copilot — `.github/copilot/mcp-config.json`

**Current state:** No scaffolding for Copilot MCP servers.

**Extension:** New method `_scaffold_copilot_mcp()` that:
1. Reads merged stack + external MCP servers
2. Generates `.github/copilot/mcp-config.json`

**Format:**
```json
{
  "mcpServers": {
    "pyright": {
      "command": "uvx",
      "args": ["mcp-server-pyright"]
    }
  }
}
```

**Alternative:** Inject into `.github/agents/*.agent.md` frontmatter `mcp-servers` field. This is more granular (per-agent MCP servers) but more complex. **Recommendation:** Start with `.github/copilot/mcp-config.json` (global for all Copilot agents). Per-agent injection is a follow-up.

**Implementation:** Can be done as a new adjustment script (`features/copilot/adjustments/adjust_mcp.py`) following the existing pattern, OR directly in scaffold.py. **Recommendation:** Direct in scaffold.py since it's a simple file write, not a complex transformation.

### 3.4 Junie (JetBrains) — IDE Settings

**Current state:** `support.json` says "JetBrains MCP config" with `aiBadgerSupport: false`.

**Investigation needed:** JetBrains IDEs (2024.2+) support MCP servers via:
- **IDE-level:** Settings → Tools → MCP Servers (stored in IDE config, not project files)
- **Project-level:** `.idea/mcp.json` (project-scoped, similar to `.mcp.json`)

**Recommendation:** For V1, write `.mcp.json` in project root (Junie reads it from there). If `.idea/mcp.json` is confirmed as the canonical project-scoped format, switch to that in V2. **Document this as a known limitation.**

### Summary Table

| Agent | Target File | Format | Scope | Notes |
|-------|------------|--------|-------|-------|
| Claude | `.mcp.json` | `{ mcpServers: { name: { command, args, env } } }` | project | Extends existing `_generate_mcp_json()` |
| Hermes | `.mcp.json` | Same as Claude | project | Hermes reads `.mcp.json` from project root |
| Copilot | `.github/copilot/mcp-config.json` | `{ mcpServers: { name: { command, args } } }` | project | New file, new scaffold method |
| Junie | `.mcp.json` | Same as Claude | project | JetBrains reads `.mcp.json`; V2 may use `.idea/mcp.json` |

---

## 4. Relationship to `externalTools`

### Data Flow

```
features/{stack}/mcp-servers.json    config.json → externalTools
         │                                    │
         ▼                                    ▼
    stack_servers[]                    user_servers[]
         │                                    │
         └──────── merge (user wins) ────────┘
                        │
                        ▼
               merged_servers[]
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
        .mcp.json   copilot/    hermes notes
        (Claude+    mcp-config
         Hermes)    .json
```

### Merge Semantics

1. **Collect stack servers:** Read `mcp-servers.json` from every active stack + common
2. **Collect user servers:** Read `externalTools` from config.json (with `generate_mcp_json: true` for `.mcp.json`; always for instruction injection)
3. **Merge by name:**
   - Stack server + no user server → use stack server
   - User server + no stack server → use user server (existing behavior)
   - Both declare the same name → **user wins** (externalTools takes precedence)
4. **Dedup across stacks:** If `features/python/mcp-servers.json` and `features/github/mcp-servers.json` both declare `filesystem`, the last one processed wins (order: common first, then stacks in config.json order). Since the schema requires unique names within a file, conflicts only arise across stacks. Document this: "If two stacks declare the same server name with different commands, the stack listed later in config.json wins."

### Priority Order (highest wins)

1. `externalTools` entries in config.json (user intent)
2. Stack `mcp-servers.json` entries (framework recommendation)
3. Common `mcp-servers.json` entries (baseline)

---

## 5. Integration Points

### 5.1 `scaffold.py` Changes

**New method: `_collect_stack_mcp_servers()`**

```python
def _collect_stack_mcp_servers(self) -> List[Dict[str, Any]]:
    """Collect MCP server declarations from stack mcp-servers.json files."""
    servers = {}  # name → server dict (last writer wins for cross-stack dupes)
    stacks = self.config.get("stacks", [])
    # common first, then stacks in order
    stack_dirs = [self.root / "features" / "common"]
    stack_dirs.extend(self.root / "features" / s for s in stacks)
    for stack_dir in stack_dirs:
        mcp_file = stack_dir / "mcp-servers.json"
        if not mcp_file.exists():
            continue
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        for server in data.get("servers", []):
            servers[server["name"]] = server
    return list(servers.values())
```

**New method: `_merge_mcp_servers(stack_servers, user_tools)`**

```python
def _merge_mcp_servers(
    self,
    stack_servers: List[Dict[str, Any]],
    user_tools: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Merge stack-declared and user-declared MCP servers. User wins on name conflict."""
    merged = {}
    for s in stack_servers:
        merged[s["name"]] = s
    for t in user_tools:
        if t.get("generate_mcp_json"):
            merged[t["name"]] = t  # user overrides stack
    return merged
```

**Extend `_generate_mcp_json()`:**

Instead of only reading `externalTools`, call `_collect_stack_mcp_servers()` first, then merge. The existing merge-only semantics for `.mcp.json` (never overwrites existing file entries) still applies on top.

**New method: `_generate_copilot_mcp_config()`**

```python
def _generate_copilot_mcp_config(self, servers: Dict[str, Dict[str, Any]]) -> None:
    """Generate .github/copilot/mcp-config.json for Copilot agent."""
    if "copilot" not in self.config.get("agents", []):
        return
    mcp_config = {"mcpServers": {}}
    for name, server in servers.items():
        parts = server["command"].split()
        entry = {"command": parts[0], "args": parts[1:]}
        if server.get("env"):
            entry["env"] = server["env"]
        mcp_config["mcpServers"][name] = entry

    config_path = self.target / ".github" / "copilot" / "mcp-config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # Merge with existing
    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    existing.setdefault("mcpServers", {}).update(mcp_config["mcpServers"])
    config_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    self.notes.append(f"generated/copied .github/copilot/mcp-config.json with {len(mcp_config['mcpServers'])} server(s)")
```

**Updated `run()` flow:**

```python
def run(self, generated_at=None):
    # ... existing steps ...
    # After _generate_mcp_json() — extend it to also handle stack servers
    self._generate_mcp_json()           # now reads both stack + externalTools
    self._generate_copilot_mcp_config() # new: Copilot MCP config
    # ... manifest ...
```

### 5.2 `refresh.py` Changes

**No changes needed.** `refresh.py` calls `re_scaffold()` which re-runs `scaffold.py`. Since the new MCP logic lives in `scaffold.py`, it automatically applies during refresh. The drift detection already checks for file changes in features; if a stack's `mcp-servers.json` changes, it will be detected as drift and trigger re-scaffold.

### 5.3 `support.json` Updates

Update `aiBadgerSupport` to `true` for agents where scaffold now writes MCP configs:

```json
{
  "claude": {
    "mcpServers": {
      "supported": true,
      "mechanism": ".mcp.json (project-scoped)",
      "aiBadgerSupport": true,
      "scaffoldedBy": "scaffold.py _generate_mcp_json()"
    }
  },
  "copilot": {
    "mcpServers": {
      "supported": true,
      "mechanism": ".github/copilot/mcp-config.json",
      "aiBadgerSupport": true,
      "scaffoldedBy": "scaffold.py _generate_copilot_mcp_config()"
    }
  },
  "hermes": {
    "mcpServers": {
      "supported": true,
      "mechanism": ".mcp.json (project-scoped, reads from project root)",
      "aiBadgerSupport": true,
      "scaffoldedBy": "scaffold.py _generate_mcp_json() (shared with Claude)"
    }
  },
  "junie": {
    "mcpServers": {
      "supported": true,
      "mechanism": ".mcp.json (project-scoped, JetBrains 2024.2+)",
      "aiBadgerSupport": true,
      "scaffoldedBy": "scaffold.py _generate_mcp_json() (shared with Claude)"
    }
  }
}
```

### 5.4 Schema Registration

Add `mcp-servers.schema.json` to `schemas/` directory. The `config.schema.json` does NOT need changes — `mcp-servers.json` is a per-stack file, not part of `config.json`.

### 5.5 `stack.json` Detection

No changes to `stack.json` format. The presence of `mcp-servers.json` in a feature directory is sufficient — the scaffold scans for it explicitly.

---

## 6. Detection and den-refresh Integration

### Drift Detection

The existing drift system in `drift.py` compares file hashes from the manifest against current framework files. When a stack's `mcp-servers.json` changes upstream:
- It's a new file not yet tracked in manifest → detected as `newItems` in drift
- It causes re-scaffold → scaffold reads the updated `mcp-servers.json` → new MCP config is written

### New Stack Detection

When `den-refresh` detects a new stack (via `detect_new_stacks()`), the re-scaffold naturally picks up that stack's `mcp-servers.json`. No additional logic needed.

### Config Change Detection

If the user adds a new stack to `config.json` stacks array, the next scaffold/refresh reads the new stack's `mcp-servers.json`. This already works through the existing flow.

---

## 7. Test Strategy

### Unit Tests (in `tests/test_stack_mcp_servers.py`)

| Test | Description |
|------|-------------|
| `test_collect_stack_mcp_servers_from_common` | Common `mcp-servers.json` is read |
| `test_collect_stack_mcp_servers_from_multiple_stacks` | Multiple stacks contribute servers |
| `test_stack_mcp_servers_generates_mcp_json` | Stack servers produce `.mcp.json` |
| `test_stack_and_external_tools_merge` | Both sources merge; user wins on conflict |
| `test_stack_mcp_no_duplicate_in_mcp_json` | Same server from two stacks doesn't duplicate |
| `test_stack_mcp_generates_copilot_config` | `.github/copilot/mcp-config.json` is created for copilot agents |
| `test_stack_mcp_copilot_not_created_for_claude_only` | Copilot config not generated if copilot not in agents |
| `test_stack_mcp_env_propagated` | `env` field appears in generated configs |
| `test_stack_mcp_agent_override` | Per-agent overrides are applied correctly |
| `test_stack_mcp_merge_preserves_existing` | Existing `.mcp.json` entries not overwritten |
| `test_stack_mcp_schema_validation` | `mcp-servers.schema.json` validates correctly |

### Schema Tests (in `tests/test_mcp_servers_schema.py`)

| Test | Description |
|------|-------------|
| `test_valid_mcp_servers_json` | Valid file passes schema validation |
| `test_missing_required_fields` | Missing `name` or `command` fails |
| `test_unknown_fields_rejected` | `additionalProperties: false` enforced |
| `test_env_must_be_string_values` | `env` values must be strings |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_full_scaffold_with_stack_mcp` | End-to-end: config with python stack → `.mcp.json` has pyright |
| `test_refresh_picks_up_new_mcp` | Refresh after adding stack → new MCP servers appear |

---

## 8. Implementation Plan

### Phase 1: Schema + Collection (no scaffold changes)

1. **Create `schemas/mcp-servers.schema.json`** — the JSON schema from §2
2. **Create `features/python/mcp-servers.json`** — example with pyright (or a placeholder if no real server is ready)
3. **Create `features/common/mcp-servers.json`** — empty `{ "servers": [] }` initially
4. **Write schema tests** — validate the schema itself

### Phase 2: Scaffold Integration

5. **Add `_collect_stack_mcp_servers()` to `scaffold.py`** — reads `mcp-servers.json` from active stacks + common
6. **Add `_merge_mcp_servers()` to `scaffold.py`** — merge logic (user > stack > common)
7. **Extend `_generate_mcp_json()`** — use merged servers instead of only `externalTools`
8. **Add `_generate_copilot_mcp_config()` to `scaffold.py`** — writes `.github/copilot/mcp-config.json`
9. **Wire into `run()`** — call new methods after existing `_generate_mcp_json()`
10. **Write unit tests** — all tests from §7

### Phase 3: Support + Documentation

11. **Update `support.json`** — set `aiBadgerSupport: true` for all agents' `mcpServers`
12. **Update `config.schema.json`** — no changes needed (mcp-servers.json is per-stack, not in config)
13. **Write integration tests** — full scaffold + refresh flows
14. **Document in README / contributing guide** — how to add `mcp-servers.json` to a stack

### Phase 4: Real Server Declarations

15. **Add `mcp-servers.json` to stacks that have real MCP servers** — e.g., `features/github/`, `features/azure/`, `features/python/`
16. **Test with real agents** — verify `.mcp.json`, Copilot config, and Hermes all work

---

## 9. Open Questions

1. **Junie `.idea/mcp.json` vs `.mcp.json`** — Need to verify whether JetBrains MCP support reads `.mcp.json` from project root. If not, scaffold should write `.idea/mcp.json` instead.

2. **Hermes user-scoped servers** — Should scaffold emit advisory notes for `scope: user` servers, or silently skip them? Recommendation: advisory notes.

3. **Copilot per-agent MCP** — `.github/copilot/mcp-config.json` applies to all Copilot agents. Should we support per-agent `mcp-servers` in `.github/agents/*.agent.md` frontmatter? Recommendation: V2.

4. **Server package installation** — Should scaffold check if the MCP server package is installed and emit a warning? Recommendation: advisory note only (consistent with existing skill install behavior).

5. **`externalTools` overlap** — If a user has `externalTools` with `generate_mcp_json: true` and a stack declares the same server, the user entry wins. Should there be a warning/note about the override? Recommendation: yes, add to scaffold notes.
