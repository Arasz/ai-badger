# Plan: Auto-scaffold external tools from stack catalog

## Problem

External tools (like code-review-graph) require manual `externalTools` declaration
in each consumer repo's `config.json`. Skills, hooks, instructions, and MCP servers
are all auto-scaffolded from the `features/` catalog — external tools should follow
the same pattern.

## Approach

Mirror the `mcp-servers.json` pattern exactly:

1. **Catalog file**: `features/{common,stack}/external-tools.json`
2. **Collection**: read common → stacks (last-writer-wins on name)
3. **Merge**: catalog tools + user `config.externalTools` (user overrides)
4. **Inject**: merged list feeds instructions into agent files + `.mcp.json`

## Schema

`features/common/external-tools.json`:
```json
{
  "$schema": "../../schemas/external-tools.schema.json",
  "tools": [
    {
      "name": "code-review-graph",
      "package": "code-review-graph",
      "command": "python3 -m code_review_graph serve",
      "instructions": "<!-- code-review-graph MCP tools -->\n## MCP Tools: ...",
      "generate_mcp_json": true
    }
  ]
}
```

Same shape as `config.externalTools[]` entries. Per-stack files optional.

## Changes

### 1. `features/common/external-tools.json` (new)
Move code-review-graph from ai-badger's config.json `externalTools` into the
common catalog. Empty `tools: []` initially; code-review-graph entry moved here.

### 2. `features/common/skills/welcome-ai-badger/scripts/scaffold.py`

Add `_collect_external_tools()` — mirrors `_collect_stack_mcp_servers()`:
- Read `features/{stack}/external-tools.json` for each stack in `self.stacks`
- Last-writer-wins on name (common first, stacks override)
- Return list of tool dicts

Add `_merge_external_tools(catalog_tools, user_tools)` — merges catalog with
`config.externalTools`. User wins on name conflict.

Update `_compute_doc_slots()`:
- Call `_collect_external_tools()` + `_merge_external_tools()`
- Pass merged list to `_render_external_mcp_instructions()`

Update `_generate_mcp_json()`:
- Use merged external tools (not just config ones) for `generate_mcp_json` filtering

Update `_merge_mcp_servers()`:
- Use merged external tools (not just config ones)

Update `run()`:
- Collect + merge external tools once, reuse across all consumers

### 3. `ai-badger/config.json`
Remove `externalTools` section (now in catalog).

### 4. Tests
- `test_collect_external_tools_reads_common_catalog`
- `test_collect_external_tools_stack_overrides_common`
- `test_merge_external_tools_user_overrides_catalog`
- `test_scaffold_injects_catalog_tool_instructions_into_claude_md`
- Existing tests still pass

### 5. Version bump
VERSION → 0.14.0 (minor: new feature)
Changelog entry.

## Verification
- `python3 -m pytest -q` — all tests pass
- `python3 -m pylint` — no regressions
- Manual: scaffold a test repo without `externalTools` in config → verify
  code-review-graph instructions appear in CLAUDE.md
