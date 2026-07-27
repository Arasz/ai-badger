# MCP Stack Declarations — Refined Implementation Plan

**Date:** 2026-07-26
**Status:** Implemented in 0.13.0 apart from two items — kept as the design record, not a plan.
Re-verified 2026-07-27 against 0.27.0: every planned method exists in
`features/common/skills/welcome-ai-badger/scripts/mcp_tools.py`, the schema and both test files
landed (16 and 39 tests, against the 10 and 38 planned), and Change 5 / §6.6's merge-only file
semantics were later strengthened by remediation WP19 into explicit owner constants. **Two items
did not land:** Phase 4 step 15 — "add `mcp-servers.json` to the stacks that have real MCP servers
(`github`, `azure`, `python`)" — was never started, so the mechanism ships with zero declarations;
and §3 / Pitfall 7's `targetAgents` is schema-valid but behaviourally inert, read by no production
code. Both are candidates for Wave 12 of
[`../plans/2026-07-27-deferred-work-plan.md`](../plans/2026-07-27-deferred-work-plan.md), which is
already rewriting `mcp_tools.py`.
**Supersedes:** `docs/design/mcp-stack-declarations.md` §8 (implementation plan section)
**Version target:** 0.13.0

---

## 1. What Changed from the Original Design

### Change 1: Hermes user-scoped servers MUST write to `~/.hermes/config.yaml`

**Original design (§3.2, §9 Q2):** For `scope: user` servers, emit advisory notes
telling the user what to add manually. The scaffold should "NOT modify user-global
config without explicit consent."

**Refined approach:** The scaffold **must write** to `~/.hermes/config.yaml` for
`scope: user` servers. This is the primary use case — Hermes MCP servers are
universal (user-scoped), not per-project. Advisory notes are insufficient.

**Implementation:** New method `_scaffold_hermes_mcp_user()` that:
1. Reads `~/.hermes/config.yaml` (create if missing)
2. Merges `scope: user` servers into the `mcp.servers` YAML section
3. Preserves existing user entries (merge-only, never overwrite)
4. Uses string-based YAML editing (per `hermes-config-management` skill) to
   preserve comments and formatting — **never** `yaml.safe_dump` on the whole file

**Precedent:** `symlink_hermes_skills()` already writes to `~/.hermes/skills/`
(user home directory). The `hermes-config-management` skill documents the safe
pattern for editing `~/.hermes/config.yaml`.

**Test isolation:** Use `unittest.mock.patch("pathlib.Path.home")` (same pattern
as `test_scaffold_creates_hermes_skill_symlinks`).

### Change 2: Dual-mode Hermes scaffolding (project + user scope)

**Original design:** Hermes always writes `.mcp.json` (project-scoped).

**Refined approach:** Hermes scaffolding is scope-aware:

| Server `scope` | Target | Mechanism |
|---|---|---|
| `project` (default) | `.mcp.json` in project root | Same as Claude (Hermes reads `.mcp.json`) |
| `user` | `~/.hermes/config.yaml` `mcp.servers` | YAML merge into user config |

This matches the user's intent: Hermes MCP = user-scoped (universal).

### Change 3: Claude user-scoped servers write to `~/.claude/settings.json`

**Original design:** No mention of Claude user-scoped writes.

**Refined approach:** For `scope: user` + agent `claude`, write MCP server
entries to `~/.claude/settings.json` under `mcpServers`. Same merge-only
semantics. This is the correct Claude equivalent of user-scoped config.

### Change 4: Summary table update

| Agent | `scope: project` target | `scope: user` target | Format |
|---|---|---|---|
| Claude | `.mcp.json` | `~/.claude/settings.json` | `{ mcpServers: { name: { command, args, env } } }` |
| Hermes | `.mcp.json` | `~/.hermes/config.yaml` | YAML `mcp.servers` section |
| Copilot | `.github/copilot/mcp-config.json` | N/A (project-only) | `{ mcpServers: { name: { command, args } } }` |
| Junie | `.mcp.json` | N/A (project-only) | Same as Claude |

### Change 5: externalTools precedence confirmed preserved

The existing `_generate_mcp_json()` reads `externalTools` with
`generate_mcp_json: true`. The refined flow:
1. Collect stack servers from `mcp-servers.json` files
2. Merge with `externalTools` servers (user wins on name conflict)
3. Split by scope: `project` → `.mcp.json`, `user` → agent-specific user config
4. For `.mcp.json`: merge-only (never overwrite existing user entries)

**code-review-graph** is declared in `externalTools` with `generate_mcp_json: true`.
It continues to work exactly as before — stack servers are additive below it.

---

## 2. Files to Create or Modify

### 2.1 New Files

| File | Purpose |
|---|---|
| `features/common/mcp-servers.json` | Empty baseline: `{ "servers": [] }` |
| `tests/test_stack_mcp_servers.py` | All unit + integration tests for stack MCP |
| `tests/test_mcp_servers_schema.py` | Schema validation tests |
| `docs/changelog/0.13.0-stack-mcp-declarations.md` | Changelog entry |

### 2.2 Modified Files

| File | What changes |
|---|---|
| `VERSION` | `0.12.0` → `0.13.0` |
| `features/common/skills/welcome-ai-badger/scripts/scaffold.py` | New methods + modified `_generate_mcp_json()` + modified `run()` |
| `features/common/support.json` | `aiBadgerSupport: true` for all agents' `mcpServers` |
| `schemas/mcp-servers.schema.json` | Add `targetAgents` field (optional filter) |

### 2.3 Scaffold.py Method Changes (detailed)

#### New methods to add:

```python
def _collect_stack_mcp_servers(self) -> List[Dict[str, Any]]:
    """Collect MCP server declarations from stack mcp-servers.json files.

    Reads mcp-servers.json from features/common/ and each active stack.
    Common is read first, then stacks in config.json order (last writer wins
    on cross-stack name conflicts).
    """
```

```python
def _merge_mcp_servers(
    self,
    stack_servers: List[Dict[str, Any]],
    user_tools: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Merge stack-declared and user-declared MCP servers.

    Priority: externalTools (user) > stack mcp-servers.json (framework).
    Returns dict keyed by server name.
    """
```

```python
def _split_servers_by_scope(
    self,
    servers: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Split merged servers into project-scoped and user-scoped dicts.

    Returns (project_servers, user_servers).
    """
```

```python
def _scaffold_hermes_mcp_user(
    self,
    user_servers: Dict[str, Dict[str, Any]],
) -> None:
    """Write scope:user MCP servers into ~/.hermes/config.yaml.

    Uses string-based YAML editing to preserve comments and formatting.
    Merge-only: existing user entries are never overwritten.
    """
```

```python
def _scaffold_claude_mcp_user(
    self,
    user_servers: Dict[str, Dict[str, Any]],
) -> None:
    """Write scope:user MCP servers into ~/.claude/settings.json.

    Merge-only: reads existing, adds new mcpServers entries.
    """
```

```python
def _generate_copilot_mcp_config(
    self,
    servers: Dict[str, Dict[str, Any]],
) -> None:
    """Generate .github/copilot/mcp-config.json for Copilot agent.

    Only runs when 'copilot' is in config.agents.
    Merge-only with existing file.
    """
```

```python
def _parse_command(self, command: str) -> Tuple[str, List[str]]:
    """Split a command string into (executable, args_list).

    Shared utility for all MCP config generators.
    """
```

#### Modified methods:

**`_generate_mcp_json()`** — Extended to use merged servers (stack + externalTools)
instead of only externalTools. Still project-scoped only. Still merge-only with
existing `.mcp.json`.

**`run()`** — After `_generate_mcp_json()`, add calls to:
- `_scaffold_hermes_mcp_user()` (when hermes in agents + user-scoped servers exist)
- `_scaffold_claude_mcp_user()` (when claude in agents + user-scoped servers exist)
- `_generate_copilot_mcp_config()` (when copilot in agents)

#### Updated `run()` flow:

```python
def run(self, generated_at=None):
    # ... existing steps through run_adjustments() ...
    self._generate_mcp_json()              # extended: stack + externalTools → .mcp.json
    self._scaffold_hermes_mcp_user()       # new: scope:user → ~/.hermes/config.yaml
    self._scaffold_claude_mcp_user()       # new: scope:user → ~/.claude/settings.json
    self._generate_copilot_mcp_config()    # new: scope:project → .github/copilot/mcp-config.json
    # ... manifest ...
```

---

## 3. Schema Update

The existing `schemas/mcp-servers.schema.json` is mostly correct. One addition:

**Add optional `targetAgents` field** to allow a server to target only specific
agents (useful when a server only works with certain agents):

```json
"targetAgents": {
  "type": "array",
  "items": { "enum": ["claude", "hermes", "copilot", "junie"] },
  "description": "If set, only scaffold for these agents. Omit to scaffold for all active agents."
}
```

This is optional — omitting it means "scaffold for all active agents" (current
behavior). The `scope` field remains as-is.

**No changes needed to `config.schema.json`** — `mcp-servers.json` is per-stack,
not part of `config.json`.

---

## 4. TDD Implementation Order

### Phase 1: Schema + Collection (tests first, no scaffold changes yet)

#### Step 1.1: Write schema tests

**File:** `tests/test_mcp_servers_schema.py`

| Test name | What it verifies |
|---|---|
| `test_valid_mcp_servers_json_passes` | A well-formed `mcp-servers.json` passes `jsonschema.validate()` |
| `test_missing_name_fails` | Server without `name` is rejected |
| `test_missing_command_fails` | Server without `command` is rejected |
| `test_unknown_fields_rejected` | `additionalProperties: false` rejects extra fields |
| `test_env_must_be_string_values` | `env` values that aren't strings fail |
| `test_scope_defaults_to_project` | Missing `scope` is valid (defaults to "project") |
| `test_scope_accepts_user` | `"scope": "user"` is valid |
| `test_scope_rejects_invalid_value` | `"scope": "global"` fails |
| `test_agent_override_valid` | Valid `agentOverrides` with `command`/`args` passes |
| `test_empty_servers_array_valid` | `{ "servers": [] }` is valid |

#### Step 1.2: Write collection tests

**File:** `tests/test_stack_mcp_servers.py`

| Test name | What it verifies |
|---|---|
| `test_collect_from_common` | `_collect_stack_mcp_servers()` reads `features/common/mcp-servers.json` |
| `test_collect_from_multiple_stacks` | Servers from python + github stacks are both collected |
| `test_collect_cross_stack_dedup_last_writer_wins` | Same name in two stacks → later stack wins |
| `test_collect_missing_file_skipped` | Stack without `mcp-servers.json` is silently skipped |
| `test_collect_empty_servers` | `{ "servers": [] }` returns empty list |

#### Step 1.3: Write merge tests

| Test name | What it verifies |
|---|---|
| `test_merge_stack_only` | Stack server with no externalTool → appears in merged dict |
| `test_merge_user_only` | ExternalTool with no stack server → appears in merged dict |
| `test_merge_user_wins_on_conflict` | Same name in both → externalTools entry is used |
| `test_merge_empty_stacks` | No stack servers → only externalTools in result |
| `test_merge_empty_tools` | No externalTools → only stack servers in result |

#### Step 1.4: Write scope-split tests

| Test name | What it verifies |
|---|---|
| `test_split_default_scope_is_project` | Server without `scope` field goes to project dict |
| `test_split_project_scope` | `"scope": "project"` goes to project dict |
| `test_split_user_scope` | `"scope": "user"` goes to user dict |
| `test_split_mixed_scopes` | Mixed servers split correctly into two dicts |

#### Step 1.5: Run all tests — expect failures (RED)

```bash
cd /Users/arasz/RiderProjects/ai-badger
python -m pytest tests/test_mcp_servers_schema.py tests/test_stack_mcp_servers.py -v
```

All tests should fail because the production methods don't exist yet.

### Phase 2: Implement collection + merge + split (make tests pass)

#### Step 2.1: Add `_parse_command()` to `Scaffolder`

Simple utility: `command.split()` → `(parts[0], parts[1:])`.

#### Step 2.2: Add `_collect_stack_mcp_servers()` to `Scaffolder`

Read `mcp-servers.json` from `features/common/` and each stack in
`config.stacks`. Last-writer-wins on name conflict.

#### Step 2.3: Add `_merge_mcp_servers()` to `Scaffolder`

Merge stack servers with externalTools (user wins on conflict).

#### Step 2.4: Add `_split_servers_by_scope()` to `Scaffolder`

Split into `(project_servers, user_servers)` based on `scope` field.

#### Step 2.5: Run tests — expect passes (GREEN)

```bash
python -m pytest tests/test_stack_mcp_servers.py -v -k "collect or merge or split"
```

### Phase 3: Implement agent-specific scaffolding (tests first)

#### Step 3.1: Write .mcp.json generation tests (extend `test_stack_mcp_servers.py`)

| Test name | What it verifies |
|---|---|
| `test_stack_mcp_generates_mcp_json` | Stack servers with `scope: project` produce `.mcp.json` |
| `test_stack_and_external_tools_merge_in_mcp_json` | Both sources appear in `.mcp.json`; user wins on conflict |
| `test_mcp_json_no_duplicate_from_two_stacks` | Same server from two stacks → one entry in `.mcp.json` |
| `test_mcp_json_merge_preserves_existing` | Pre-existing `.mcp.json` entries not overwritten |
| `test_mcp_json_env_propagated` | `env` field from stack server appears in `.mcp.json` entry |
| `test_mcp_json_agent_override_applied` | `agentOverrides.claude` overrides command for Claude |
| `test_mcp_json_not_created_when_empty` | No project-scoped servers → no `.mcp.json` |

#### Step 3.2: Write Hermes user-scoped tests

| Test name | What it verifies |
|---|---|
| `test_hermes_user_server_writes_config_yaml` | `scope: user` server is written to `~/.hermes/config.yaml` `mcp.servers` |
| `test_hermes_user_server_merge_preserves_existing` | Existing entries in `config.yaml` `mcp.servers` are preserved |
| `test_hermes_user_server_creates_config_if_missing` | If `~/.hermes/config.yaml` doesn't exist, it's created |
| `test_hermes_user_server_no_write_without_hermes_agent` | If hermes not in `config.agents`, no config.yaml write |
| `test_hermes_project_server_writes_mcp_json` | `scope: project` server goes to `.mcp.json`, not config.yaml |
| `test_hermes_mcp_json_shared_with_claude` | Hermes and Claude share the same `.mcp.json` for project-scoped |

#### Step 3.3: Write Claude user-scoped tests

| Test name | What it verifies |
|---|---|
| `test_claude_user_server_writes_settings_json` | `scope: user` server written to `~/.claude/settings.json` `mcpServers` |
| `test_claude_user_server_merge_preserves_existing` | Existing `mcpServers` entries preserved |
| `test_claude_user_server_no_write_without_claude_agent` | If claude not in agents, no settings.json write |

#### Step 3.4: Write Copilot tests

| Test name | What it verifies |
|---|---|
| `test_copilot_config_generated` | `.github/copilot/mcp-config.json` created when copilot in agents |
| `test_copilot_config_not_created_for_claude_only` | No copilot config if copilot not in agents |
| `test_copilot_config_merge_preserves_existing` | Existing copilot config entries preserved |
| `test_copilot_env_propagated` | `env` field appears in copilot config |

#### Step 3.5: Write integration tests

| Test name | What it verifies |
|---|---|
| `test_full_scaffold_with_stack_mcp` | End-to-end: config with python stack → `.mcp.json` has pyright |
| `test_full_scaffold_user_scoped_hermes` | End-to-end: `scope: user` server → `~/.hermes/config.yaml` |
| `test_existing_external_tools_still_work` | Regression: code-review-graph from externalTools still generates `.mcp.json` |
| `test_no_mcp_json_when_no_servers` | No stack servers + no externalTools → no `.mcp.json` |

#### Step 3.6: Run tests — expect failures (RED)

```bash
python -m pytest tests/test_stack_mcp_servers.py -v
```

### Phase 4: Implement agent scaffolding methods (make tests pass)

#### Step 4.1: Extend `_generate_mcp_json()`

Modify to call `_collect_stack_mcp_servers()` + `_merge_mcp_servers()`,
then `_split_servers_by_scope()` to get project-scoped servers. Write only
project-scoped servers to `.mcp.json`. Preserve existing merge-only semantics.

Key detail: the existing `_generate_mcp_json()` adds `cwd` to each entry.
Stack-declared servers should also get `cwd: str(self.target)`.

#### Step 4.2: Implement `_scaffold_hermes_mcp_user()`

```python
def _scaffold_hermes_mcp_user(self, user_servers):
    if "hermes" not in self.config.get("agents", []):
        return
    if not user_servers:
        return
    config_path = Path.home() / ".hermes" / "config.yaml"
    # Read existing or create empty
    # Parse YAML, merge mcp.servers, write back
    # Use string-based editing to preserve comments
```

**Implementation detail:** Use `yaml.safe_load` to read, then `yaml.safe_dump`
for the `mcp` section only (not the whole file). Alternatively, use the
string-based approach from `hermes-config-management` skill's
`references/config-list-editing.md`.

**Recommended approach (string-based, comment-safe):**
1. Read file as text
2. Find or create the `mcp:` section
3. Find or create `  servers:` under `mcp:`
4. For each new server, insert YAML key-value block if name not already present
5. Write file back

**Fallback approach (simpler, loses comments):**
1. `yaml.safe_load` the whole file
2. Deep-merge `mcp.servers`
3. `yaml.safe_dump` back (will lose comments — document this as a known limitation)

**Recommendation:** Start with the fallback for V1. The string-based approach
is more robust but significantly more complex. Add a note that V2 will preserve
comments.

#### Step 4.3: Implement `_scaffold_claude_mcp_user()`

```python
def _scaffold_claude_mcp_user(self, user_servers):
    if "claude" not in self.config.get("agents", []):
        return
    if not user_servers:
        return
    config_path = Path.home() / ".claude" / "settings.json"
    # Read existing or create empty
    # Merge mcpServers
    # Write back
```

JSON is simpler — no comment preservation needed.

#### Step 4.4: Implement `_generate_copilot_mcp_config()`

As described in original design doc §3.3. Project-scoped only.

#### Step 4.5: Update `run()` method

Add new calls after `_generate_mcp_json()`.

#### Step 4.6: Run tests — expect passes (GREEN)

```bash
python -m pytest tests/test_stack_mcp_servers.py tests/test_external_mcp_tools.py -v
```

**Critical:** All existing `test_external_mcp_tools.py` tests must still pass.
This verifies externalTools behavior is preserved.

### Phase 5: Support + Documentation

#### Step 5.1: Update `support.json`

Set `aiBadgerSupport: true` and add `scaffoldedBy` for all agents' `mcpServers`:

- claude: `scaffoldedBy: "scaffold.py _generate_mcp_json() + _scaffold_claude_mcp_user()"`
- hermes: `scaffoldedBy: "scaffold.py _generate_mcp_json() + _scaffold_hermes_mcp_user()"`
- copilot: `scaffoldedBy: "scaffold.py _generate_copilot_mcp_config()"`
- junie: `scaffoldedBy: "scaffold.py _generate_mcp_json() (shared with Claude)"`

#### Step 5.2: Create `features/common/mcp-servers.json`

```json
{
  "$schema": "../../../schemas/mcp-servers.schema.json",
  "servers": []
}
```

#### Step 5.3: Update schema (`schemas/mcp-servers.schema.json`)

Add `targetAgents` optional field (see §3 above).

#### Step 5.4: Bump VERSION

`0.12.0` → `0.13.0`

#### Step 5.5: Create changelog

`docs/changelog/0.13.0-stack-mcp-declarations.md`

#### Step 5.6: Update design doc status

In `docs/design/mcp-stack-declarations.md`, change `Status: Proposed` →
`Status: Superseded by implementation plan` and link to this file.

---

## 5. Complete Test Case Inventory

### `tests/test_mcp_servers_schema.py` (10 tests)

1. `test_valid_mcp_servers_json_passes` — well-formed file validates
2. `test_missing_name_fails` — server without `name` rejected
3. `test_missing_command_fails` — server without `command` rejected
4. `test_unknown_fields_rejected` — `additionalProperties: false` enforced
5. `test_env_must_be_string_values` — non-string env values rejected
6. `test_scope_defaults_to_project` — missing scope is valid
7. `test_scope_accepts_user` — `"user"` scope validates
8. `test_scope_rejects_invalid_value` — `"global"` scope rejected
9. `test_agent_override_valid` — valid agentOverrides passes
10. `test_empty_servers_array_valid` — empty array is valid

### `tests/test_stack_mcp_servers.py` (28 tests)

#### Collection (5)
1. `test_collect_from_common` — reads common mcp-servers.json
2. `test_collect_from_multiple_stacks` — multiple stacks contribute
3. `test_collect_cross_stack_dedup_last_writer_wins` — dedup semantics
4. `test_collect_missing_file_skipped` — silent skip
5. `test_collect_empty_servers` — empty array returns empty list

#### Merge (5)
6. `test_merge_stack_only` — stack server appears
7. `test_merge_user_only` — externalTool appears
8. `test_merge_user_wins_on_conflict` — externalTools takes precedence
9. `test_merge_empty_stacks` — only externalTools in result
10. `test_merge_empty_tools` — only stack servers in result

#### Scope split (4)
11. `test_split_default_scope_is_project` — default goes to project
12. `test_split_project_scope` — explicit project goes to project
13. `test_split_user_scope` — user goes to user dict
14. `test_split_mixed_scopes` — mixed splits correctly

#### .mcp.json generation (7)
15. `test_stack_mcp_generates_mcp_json` — stack servers produce .mcp.json
16. `test_stack_and_external_tools_merge_in_mcp_json` — both merge; user wins
17. `test_mcp_json_no_duplicate_from_two_stacks` — dedup in output
18. `test_mcp_json_merge_preserves_existing` — existing entries preserved
19. `test_mcp_json_env_propagated` — env appears in output
20. `test_mcp_json_agent_override_applied` — overrides applied
21. `test_mcp_json_not_created_when_empty` — no file when no servers

#### Hermes user-scoped (6)
22. `test_hermes_user_server_writes_config_yaml` — writes to ~/.hermes/config.yaml
23. `test_hermes_user_server_merge_preserves_existing` — existing preserved
24. `test_hermes_user_server_creates_config_if_missing` — creates file
25. `test_hermes_user_server_no_write_without_hermes_agent` — gated on agent
26. `test_hermes_project_server_writes_mcp_json` — project scope → .mcp.json
27. `test_hermes_mcp_json_shared_with_claude` — shared .mcp.json

#### Claude user-scoped (3)
28. `test_claude_user_server_writes_settings_json` — writes to ~/.claude/settings.json
29. `test_claude_user_server_merge_preserves_existing` — existing preserved
30. `test_claude_user_server_no_write_without_claude_agent` — gated on agent

#### Copilot (4)
31. `test_copilot_config_generated` — .github/copilot/mcp-config.json created
32. `test_copilot_config_not_created_for_claude_only` — gated on agent
33. `test_copilot_config_merge_preserves_existing` — existing preserved
34. `test_copilot_env_propagated` — env in output

#### Integration (4)
35. `test_full_scaffold_with_stack_mcp` — end-to-end project-scoped
36. `test_full_scaffold_user_scoped_hermes` — end-to-end user-scoped
37. `test_existing_external_tools_still_work` — regression: code-review-graph preserved
38. `test_no_mcp_json_when_no_servers` — no spurious files

**Total: 48 tests** (10 schema + 38 scaffold)

---

## 6. Key Implementation Details

### 6.1 Command Parsing

```python
def _parse_command(self, command):
    # type: (str) -> Tuple[str, List[str]]
    """Split command string into (executable, args)."""
    parts = command.split()
    if not parts:
        return ("", [])
    return (parts[0], parts[1:])
```

### 6.2 `.mcp.json` Entry Format

```json
{
  "mcpServers": {
    "server-name": {
      "command": "uvx",
      "args": ["mcp-server-pyright"],
      "cwd": "/path/to/project",
      "env": { "KEY": "value" }
    }
  }
}
```

`cwd` is always set to `str(self.target)` for project-scoped servers.

### 6.3 Hermes `config.yaml` MCP Section

```yaml
mcp:
  servers:
    pyright:
      command: uvx
      args:
        - mcp-server-pyright
```

### 6.4 Claude `settings.json` MCP Section

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

### 6.5 Copilot `mcp-config.json` Format

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

### 6.6 Merge-Only Semantics (critical invariant)

Every config file write follows the same pattern:
1. Read existing file (or start with `{}` / empty YAML)
2. Merge new entries into existing (new entries don't overwrite existing keys)
3. Write back

For `.mcp.json`: `existing.setdefault("mcpServers", {}).update(new_servers)`
but only for keys NOT already in `existing["mcpServers"]`.

**Correction to existing code:** The current `_generate_mcp_json()` uses
`.update()` which DOES overwrite existing entries with the same name. The
refined version should check:

```python
for name, entry in new_servers.items():
    if name not in existing.get("mcpServers", {}):
        existing.setdefault("mcpServers", {})[name] = entry
```

Wait — the design says "user wins on conflict" for merge, but "never overwrite
existing entries" for file-level merge. These are two different merge layers:
1. **In-memory merge** (stack + externalTools): externalTools wins → produces `merged_servers`
2. **File-level merge** (merged_servers vs existing .mcp.json on disk): existing file wins

So the flow is:
1. Merge stack + externalTools in-memory (user wins) → `merged_servers`
2. Read existing `.mcp.json` from disk
3. Write `merged_servers` into existing file, but **skip entries already in the file**

This means: if the user manually added a server to `.mcp.json`, scaffold won't
overwrite it. If externalTools declares the same server as a stack, externalTools
wins in the in-memory merge. If the user already has it in `.mcp.json`, the
file-level merge preserves it.

### 6.7 Agent Override Application

When generating agent-specific configs, check for `agentOverrides.<agent>`:

```python
def _resolve_server_for_agent(self, server, agent_name):
    # type: (Dict[str, Any], str) -> Dict[str, Any]
    """Apply agent-specific overrides to a server declaration."""
    override = server.get("agentOverrides", {}).get(agent_name, {})
    if not override:
        return server
    result = dict(server)
    if "command" in override:
        result["command"] = override["command"]
    if "args" in override:
        result["args"] = override["args"]
    return result
```

### 6.8 Python 3.8+ Compatibility

- No walrus operator (`:=`)
- No `match`/`case`
- Use `Dict[str, Any]` from `typing` (already imported)
- Use `Tuple` from `typing` for return type annotations
- f-strings are fine (3.6+)

---

## 7. Pitfalls and Guards

1. **Temp path leakage in tests:** All tests using `Path.home()` mock must use
   `unittest.mock.patch("pathlib.Path.home", return_value=tmp_path / "home")`.
   This is already the established pattern.

2. **YAML corruption:** `yaml.safe_dump` strips comments and reformats. For V1,
   accept this limitation for `~/.hermes/config.yaml`. Document it. V2 can add
   comment-preserving string-based editing.

3. **Missing PyYAML:** `yaml` module may not be available. Guard with try/except
   and skip Hermes user-scoped scaffolding if unavailable (emit note).

4. **Missing `~/.claude/` directory:** Create with `mkdir(parents=True, exist_ok=True)`.

5. **Thread safety:** Not a concern — scaffold runs single-threaded.

6. **Existing `_generate_mcp_json()` regression:** The current implementation uses
   `.update()` which overwrites. The refined version must preserve existing file
   entries. This is a behavior change — the new tests must verify it.

7. **`targetAgents` filtering:** If a server declares `targetAgents: ["hermes"]`,
   it should only appear in Hermes configs, not Claude/Copilot. The
   `_split_servers_by_scope()` or the agent-specific methods must filter by this.

---

## 8. Verification Checklist

After implementation, verify:

- [ ] `python -m pytest tests/test_stack_mcp_servers.py -v` — all 38 tests pass
- [ ] `python -m pytest tests/test_mcp_servers_schema.py -v` — all 10 tests pass
- [ ] `python -m pytest tests/test_external_mcp_tools.py -v` — all existing tests still pass
- [ ] `python -m pytest tests/ -v` — full test suite passes
- [ ] `features/common/mcp-servers.json` exists with empty servers array
- [ ] `support.json` has `aiBadgerSupport: true` for all agents' mcpServers
- [ ] `VERSION` reads `0.13.0`
- [ ] `docs/changelog/0.13.0-stack-mcp-declarations.md` exists
- [ ] Schema validates correctly with `jsonschema`
- [ ] No Python 3.8 incompatible syntax in new code
