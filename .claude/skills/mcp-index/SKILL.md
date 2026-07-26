---
name: mcp-index
description: "Use when managing MCP tool index: init, update, validate, tag, or list MCP server tools. After adding/removing MCP servers, run update to sync the index. When the agent struggles to pick the right tool or you want to reduce prompt bloat, init the index and curate tool tags."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [mcp, indexing, tool-discovery, prompt-compression]
    related_skills: [hermes-mcp-setup]
---

# MCP Tool Index

Manage `.ai-badger/mcp-tools.yaml` — a machine-readable index that maps every MCP server tool to tags (for filtering) and intent (for semantic matching). The index feeds the `ai_badger_hooks.py` plugin's `pre_llm_call` hook, which injects relevant tool recommendations into every LLM turn.

## Overview

MCP servers expose 40+ tools per server. Agents scan ALL tool definitions in the system prompt, wasting tokens and sometimes picking the wrong tool (e.g., `search_text` when `search_in_files_by_text` is faster). The index solves this by:

1. **Tagging** each tool with category labels (`[dotnet, build]`, `[database, sql]`, `[diagnostic]`)
2. **Intent description** for semantic disambiguation ("Compile the solution" vs "List project run configs")
3. **Hook-driven recommendation** — the `pre_llm_call` hook loads the index, extracts domain keywords from the user's message, and injects top-N matching tools as a context hint

## When to Use

- **After `hermes mcp add`** — run `mcp-index update` to index new tools
- **Before complex multi-tool tasks** — run `mcp-index validate` to ensure the index is complete
- **When the agent picks the wrong tool** — run `mcp-index tag <tool> <correct-tags...>` to fix tagging
- **After removing MCP servers** — run `mcp-index update` to mark stale tools

## Tag Taxonomy

Tags come from a closed set in `features/common/mcp-tags.json`:

| Category | Tags |
|---|---|
| Language | `csharp`, `typescript`, `javascript`, `python`, `sql`, `css`, `html` |
| Action | `navigation`, `diagnostic`, `build`, `run`, `refactoring`, `search`, `read`, `write`, `terminal` |
| Domain | `database`, `tracing`, `opentelemetry`, `browser`, `dotnet`, `semantic`, `files` |
| Meta | `batch`, `slow`, `unsafe` |

Tools auto-tagged as `[general]` need manual curation.

## Commands

### `init` — create the index

```bash
python3 skills/mcp-index/scripts/mcp_index.py init --target <project-root>
```

Reads `hermes mcp list --json` (or `--from-json` for testing), auto-tags tools by name heuristics, and writes `.ai-badger/mcp-tools.yaml`. Reports how many tools were tagged as `general`.

**Completion criterion:** `.ai-badger/mcp-tools.yaml` exists with all current MCP tools indexed.

### `update` — sync index with current MCP state

```bash
python3 skills/mcp-index/scripts/mcp_index.py update --target <project-root>
```

Adds new tools (auto-tagged), marks removed tools with `status: removed` (preserving manual tags), and adds new MCP servers. **Preserves manually-set tags and intents on existing tools.**

**Completion criterion:** All current MCP tools appear in the index; removed tools have `status: removed`.

### `validate` — check index quality

```bash
python3 skills/mcp-index/scripts/mcp_index.py validate --target <project-root>
```

Fails (exit code 1) if any tool has `[general]` tags, empty tags, missing intent, or invalid tags.

**Completion criterion:** Exit 0 with "OK: N tool(s) validated".

### `tag` — set tags for a tool

```bash
python3 skills/mcp-index/scripts/mcp_index.py tag rider:search_symbol semantic search --target <project-root>
```

Validates tags against the taxonomy. Rejects unknown tags.

**Completion criterion:** `mcp-index list` shows the tool with the new tags.

### `intent` — set intent for a tool

```bash
python3 skills/mcp-index/scripts/mcp_index.py intent rider:get_file_problems "Check a file for Rider code analysis errors and warnings" --target <project-root>
```

Requires ≥10 characters. Use a concise one-sentence description that would help an agent pick this tool from a list of candidates.

**Completion criterion:** `mcp-index list` shows the tool with the new intent.

### `list` — display tools

```bash
python3 skills/mcp-index/scripts/mcp_index.py list --target <project-root>
python3 skills/mcp-index/scripts/mcp_index.py list --tag diagnostic --target <project-root>
python3 skills/mcp-index/scripts/mcp_index.py list --untagged --target <project-root>
```

**Completion criterion:** All matching tools are displayed with server, tags, and intent.

## Auto-tagging Heuristics

| Tool name pattern | Assigned tags |
|---|---|
| Contains `sql`, `database`, `schema`, `db` | `[database, sql]` |
| Contains `build`, `solution` | `[dotnet, build]` |
| Contains `search`, `find` | `[search]` |
| Contains `symbol` | `[semantic, search]` |
| Contains `problem`, `error`, `diagnostic` | `[diagnostic]` |
| Contains `span`, `trace`, `log`, `service` | `[tracing, opentelemetry]` |
| Contains `browser`, `navigate`, `screenshot` | `[browser]` |
| Contains `run`, `execute` | `[run]` |
| Contains `refactor`, `rename`, `reformat` | `[refactoring]` |
| Server is `playwright` | adds `[browser]` |
| No match | `[general]` |

## Common Pitfalls

1. **Auto-tagging covers only ~60% of tools.** Expect 10-20 tools tagged as `[general]` after `init`. Curate them with `mcp-index tag`.
2. **Index goes stale after adding MCP servers.** Run `mcp-index update` after every `hermes mcp add` or `hermes mcp remove`.
3. **Tags aren't free-form.** Use only tags from the taxonomy. `mcp-index tag` rejects unknown tags.
4. **Intent field is for disambiguation, not documentation.** A 10-30 word sentence beats a paragraph. Write it to answer: "why would I pick this tool over a sibling with the same tags?"
5. **The `list` filter uses substring matching on tool names.** Avoid naming tools with names that are substrings of each other in tests.
6. **`--target` is required.** The script does not default to `.` — always pass `--target <path>`.

## Verification Checklist

- [ ] `mcp-index init` produces `.ai-badger/mcp-tools.yaml` with all current MCP servers
- [ ] `mcp-index validate` exits 0
- [ ] No tools are tagged `[general]` (all manually curated)
- [ ] Every tool has a meaningful intent (≥10 chars, describes what it does)
- [ ] `mcp-index list` shows all expected tools
- [ ] All 23 tests pass: `python3 -m pytest tests/test_mcp_index.py -q`
