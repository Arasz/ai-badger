# Known Gaps Resolution Plan (v2 — post-review)

## Gap Status Matrix

| # | Gap | Status | Action |
|---|-----|--------|--------|
| 1 | Plugin-level hooks not auto-wired | STILL VALID | FIX — wire hooks into .claude/settings.json during scaffold |
| 2 | schema.json vs $schema | PARTIALLY FIXED (3/9 schemas) | FIX — add $schema to remaining 9 schemas |
| 3 | Agent files full copies not proxies | STILL VALID, spike doc exists | DEFER — complex, low ROI vs full copies |
| 4 | Non-standard agent files not merged | PARTIALLY FIXED (preserves) | DEFER — merge logic is complex edge case |
| 5 | task skill scripts not e2e tested | STILL VALID | FIX — write integration test |
| 6 | Plugin install is advisory | STILL VALID | FIX — add --execute flag to scaffold |
| 7 | Catalog is MVP-sized | GROWTH ITEM | SKIP — ongoing via feed-badger |
| 8 | job-search migration deferred | PROJECT-SPECIFIC | SKIP |

## Task 1: Wire hooks into .claude/settings.json during scaffold

**Problem:** prompt-markers bundles a UserPromptSubmit hook script, but scaffold.py
never registers it in the target project's `.claude/settings.json`.

**Design (revised per review):**
- Add `wire_hooks()` step in `scaffold.run()` between `write_agent_files()` and `install_plugins()`
- Read `features/common/hooks/hooks-manifest.json` for hook declarations
- For each hook with a `claude` agent entry of type `hooks-json`:
  - Read the source `hooks.json` from the framework
  - Generate a TARGET-specific hooks.json at `.ai-badger/hooks/hooks.json`
    with paths rewritten to `.ai-badger/skills/...` (NOT `${CLAUDE_PLUGIN_ROOT}`)
  - Merge the hook registration into `.claude/settings.json`
  - Use deep-merge for hooks arrays (don't clobber existing hooks)
- Idempotent: match by event+hook name, skip if already registered
- Only wire hooks for agents in config.agents
- Record in manifest entries
- Test: `test_scaffold_wires_claude_hooks_into_settings_json`

**Files:**
- `features/common/skills/welcome-ai-badger/scripts/scaffold.py`
- `tests/test_scaffold_hooks.py` (new)

## Task 2: Add $schema to remaining JSON schemas

**Problem:** 9 schemas have `additionalProperties: false` without allowing `$schema`.

**Design:**
- Add `"$schema": { "type": "string" }` to `properties` in ALL 9 schemas:
  - agents.schema.json
  - skills-source.schema.json
  - plugins-instructions.schema.json
  - skills.schema.json
  - hooks-manifest.schema.json
  - adjustment.schema.json
  - mcp-tools.schema.json
  - scaffolding.schema.json
  - stack.schema.json

**Files:** 9 schema files under `schemas/`

## Task 3: Write e2e test for task skill lifecycle

**Problem:** task skill scripts have unit tests but no integration test.

**Design (revised per review):**
- Create `tests/test_task_e2e.py`
- Test: scaffold minimal project → task_tracker `start` → touch state.json →
  `finish` (verify exit 0) → `grade`
- Negative test: `start` → `finish` without state.json → verify exit code 3
- Depends on Tasks 1 & 4 being complete (scaffold must work correctly)
- Use tmp_path fixture for isolation

**Files:** `tests/test_task_e2e.py` (new)

## Task 4: Add --execute flag to scaffold

**Problem:** scaffold.py prints plugin install commands but doesn't execute them.

**Design (revised per review):**
- Add `--execute` flag (not `--auto-install` — avoids confusion with `--no-install`)
- Semantics: `--no-install` = don't even generate commands; `--execute` = run them
- When set, `install_plugins()` executes collected commands via subprocess
- Add subprocess timeout (30s per command), error handling, log output to notes
- Default behavior unchanged (advisory/prints only)
- Test: `test_scaffold_execute_flag_runs_install_commands`

**Files:**
- `features/common/skills/welcome-ai-badger/scripts/scaffold.py`
- `tests/test_scaffold_install.py` (new)

## Execution Order

1. Task 2 (schema fix) — quick, no risk
2. Task 1 (hook wiring) — medium complexity, high value
3. Task 4 (execute flag) — medium complexity
4. Task 3 (e2e test) — validates the whole system

After all tasks: update `docs/known-gaps.md` to reflect resolved items.
