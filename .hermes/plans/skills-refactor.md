# Refactoring Plan: Move Skills to features/common + Add Claude Scaffolding

## Goal
1. Move root `skills/` into `features/common/skills/` — eliminating the special-case code path
2. Add `features/claude/` with a `scaffolding.json` concept that declaratively specifies what paths an agent needs scaffolded
3. TDD throughout, all tests green, docs updated

## Context gathered

### Current state
- Skills live at repo root `skills/` (8 skill dirs)
- `index_build.py` has a hardcoded second pass (lines 95-100) to inject root skills into `common.skills`
- `badger_lib.py:iter_feature_dirs` explicitly documents this as a "plugin-loader exception"
- `release_guard.py` SHIPPED_PATHS includes `"skills"` as a top-level dir
- `features/hermes/` and `features/github/` already exist as stack dirs with `stack.json`, instructions, personas, and skill-extensions
- `features/claude/` does NOT exist yet
- `manifest.schema.json` agents enum: `["claude", "copilot", "junie"]` — missing `"hermes"`
- `config.schema.json` agents enum: `["claude", "copilot", "junie", "hermes"]` — has hermes

### What changes when skills move
- `index_build.py`: remove lines 95-100 (root skills special case); `iter_feature_dirs` will find them at `features/common/skills/` automatically
- `badger_lib.py`: update comment on lines 100-102
- `release_guard.py`: keep `"skills"` in SHIPPED_PATHS — after the move, `git diff <old-tag> -- skills` shows deletions forcing a VERSION bump (desired). Harmless after that release.
- `hooks/hooks.json`: update hook path from `${CLAUDE_PLUGIN_ROOT}/skills/...` to `${CLAUDE_PLUGIN_ROOT}/features/common/skills/...`
- Tests: update all `load_script("skills/...")` → `load_script("features/common/skills/...")`
- `den-refresh/scripts/refresh.py`: update `_load_script` paths
- Docs: update 6 documentation files
- `manifest.schema.json`: add `"hermes"` to agents enum

---

## Step-by-step tasks

### Step 0: Baseline verification
- Run `python3 -m pytest -q` in the worktree to confirm GREEN state before any changes

### Step 1: Move skills directory
- `git mv skills/ features/common/skills/`
- Verify all 8 skill dirs moved correctly

### Step 2: Update index_build.py (TDD)
- **RED**: Write test `test_index_build_finds_skills_under_features_common_skills` — create a minimal framework tree with `features/common/skills/test-skill/SKILL.md`, run `build_index`, assert `common.skills` contains `test-skill`
- **GREEN**: Remove the root skills special case (lines 95-100). The existing `iter_feature_dirs` loop already handles `features/common/skills/` — no new code needed, just delete the special case
- **REFACTOR**: Update the docstring (line 7-8) to remove the "skills -> each subdir" exception note

### Step 3: Update badger_lib.py comment
- Update `iter_feature_dirs` docstring (lines 100-102) to remove the "plugin-loader exception" language

### Step 4: Update hooks/hooks.json (CRITICAL)
- Update hook path: `${CLAUDE_PLUGIN_ROOT}/skills/task/scripts/drift_notice_hook.py` → `${CLAUDE_PLUGIN_ROOT}/features/common/skills/task/scripts/drift_notice_hook.py`

### Step 5: Update all test file paths
- Run `pytest` — tests will fail because paths are broken (RED)
- Update `load_script("skills/...")` → `load_script("features/common/skills/...")` in:
  - `tests/test_scaffold.py` (many references)
  - `tests/test_awm.py` (many references)
  - `tests/test_awm_context.py` (5 references)
  - `tests/test_drift.py` (8 references)
- Update assertion paths in `tests/test_scaffold.py`:
  - Line 152: `entry["source"].startswith("skills/")` → `entry["source"].startswith("features/common/skills/")`
  - Line 305: `root / "skills" / ...` → `root / "features" / "common" / "skills" / ...`
  - Line 429: same pattern
- Note: `tests/test_release_guard.py` creates `repo / "skills"` dirs in throwaway test repos — these test `release_guard.SHIPPED_PATHS` logic and do NOT need changing

### Step 6: Update den-refresh/scripts/refresh.py
- Lines 76, 89: `_load_script("skills/welcome-ai-badger/scripts/...")` → `_load_script("features/common/skills/welcome-ai-badger/scripts/...")`

### Step 7: Update maintain-agent-instructions/SKILL.md
- Lines 34, 40: Update repo-relative commands from `skills/maintain-agent-instructions/scripts/...` to `features/common/skills/maintain-agent-instructions/scripts/...`

### Step 8: Update manifest.json agents enum
- `schemas/manifest.schema.json` line 22: add `"hermes"` to the agents enum

### Step 9: Add features/claude/ with scaffolding.json (TDD)
- **RED**: Write test `test_scaffolding_schema_valid` — validate a sample `scaffolding.json` against the new schema
- **GREEN**:
  - Create `schemas/scaffolding.schema.json`:
    ```json
    {
      "type": "object",
      "required": ["agent", "files"],
      "properties": {
        "agent": { "type": "string" },
        "description": { "type": "string" },
        "files": {
          "type": "array",
          "items": {
            "required": ["source", "target", "managed"],
            "properties": {
              "source": { "type": "string", "description": "Path relative to the feature dir" },
              "target": { "type": "string", "description": "Path in the scaffolded project" },
              "managed": { "type": "boolean", "default": true },
              "seedOnce": { "type": "boolean", "default": false }
            }
          }
        }
      }
    }
    ```
  - Create `features/claude/stack.json` (detection signals: CLAUDE.md, .claude/)
  - Create `features/claude/scaffolding.json`:
    ```json
    {
      "agent": "claude",
      "description": "Claude Code agent discovery files",
      "files": [
        { "source": "templates/CLAUDE.md", "target": "CLAUDE.md", "managed": true }
      ]
    }
    ```
    Note: copilot-instructions.md belongs to copilot, not claude. A separate `features/copilot/scaffolding.json` would handle that.

### Step 10: Update scaffold.py to read scaffolding.json (TDD)
- **RED**: Write test `test_scaffolder_reads_scaffolding_json` — scaffold with a mock feature that has scaffolding.json, assert the declared files are written
- **GREEN**:
  - Add `scaffold_agent_from_scaffolding(agent_name, config)` method to Scaffolder
  - For each agent in `config.agents`, look for `features/<agent>/scaffolding.json`
  - If found, read it and write each declared file (with managed header if `managed: true`)
  - Fall back to existing hardcoded behavior for agents without scaffolding.json (backward compat)
- **REFACTOR**: Eventually migrate claude/copilot/junie/hermes to use scaffolding.json, removing hardcoded agent file writing

### Step 11: Update documentation
- `CLAUDE.md`: update framework description (line 5, skills/ reference)
- `docs/framework-architecture.md`: update skills location references (lines 66, 141)
- `docs/ai-badger-framework-design.md`: update skills location references (lines 76, 146, 297)
- `docs/hermes-claude-compatibility.md`: update hook path reference (lines 41, 222)
- `docs/scripts.md`: update script path references (lines 11, 21, 27)
- `README.md`: update the SKILLSDIR diagram (line 126)
- `features/hermes/instructions/hermes.instructions.md`: update glob pattern (line 3)
- `features/hermes/skills/task-extensions/hermes/extension.md`: update prose reference (line 3)
- `features/github/skills/task-extensions/github/extension.md`: update prose reference (line 3)

### Step 12: Final verification
- `python3 -m pytest -q` — all tests green
- `python3 scripts/index_build.py` — index rebuilt with new paths
- `python3 scripts/index_build.py --check` — confirms index is up to date
- Verify `features/common/skills/` contains all 8 skills
- Verify no stale `skills/` directory at root
- Verify `features/claude/` exists with scaffolding.json

---

## Files to create
- `schemas/scaffolding.schema.json`
- `features/claude/stack.json`
- `features/claude/scaffolding.json`

## Files to move
- `skills/*` → `features/common/skills/*`

## Files to modify (complete list — 20 files)
- `scripts/index_build.py` (remove root skills special case)
- `scripts/badger_lib.py` (update comment)
- `hooks/hooks.json` (update hook path — CRITICAL)
- `features/common/skills/maintain-agent-instructions/SKILL.md` (update repo-relative commands)
- `tests/test_scaffold.py` (update all paths)
- `tests/test_awm.py` (update all paths)
- `tests/test_awm_context.py` (update all paths)
- `tests/test_drift.py` (update all paths)
- `features/common/skills/den-refresh/scripts/refresh.py` (update paths)
- `features/common/skills/welcome-ai-badger/scripts/scaffold.py` (add scaffolding.json support)
- `schemas/manifest.schema.json` (add hermes to agents enum)
- `docs/framework-architecture.md`
- `docs/ai-badger-framework-design.md`
- `docs/hermes-claude-compatibility.md`
- `docs/scripts.md`
- `README.md`
- `CLAUDE.md`
- `features/hermes/instructions/hermes.instructions.md` (glob pattern)
- `features/hermes/skills/task-extensions/hermes/extension.md` (prose)
- `features/github/skills/task-extensions/github/extension.md` (prose)

## Files NOT modified (acknowledged)
- `scripts/release_guard.py` — `"features"` already covers new location; keep `"skills"` in SHIPPED_PATHS for the transition release
- `tests/test_release_guard.py` — creates throwaway `repo / "skills"` dirs testing SHIPPED_PATHS logic, not framework structure

## Risks
- Claude Code plugin loader may depend on `skills/` at root → mitigated by the fact that the plugin cache copies files anyway; the framework repo structure doesn't need to match the installed layout
- `hooks/hooks.json` hook path must be updated or drift notice silently fails → addressed in Step 4
- Test fixtures create mock framework trees → all mock trees need updating
