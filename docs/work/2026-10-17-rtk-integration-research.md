# rtk integration research record (task aib-ship-rtk-token-proxy-tool)

Date: 2026-10-17. Goal: ship rtk (https://github.com/rtk-ai/rtk, CLI output-compression proxy) as an ai-badger catalog tool — a new `tools` feature type at `features/common/tools/rtk/` with check/install and opt-in per-harness hook wiring.

User decisions so far: high-effort loop; new `tools` category (not under `mcp/`); install = detect + opt-in per-harness hook wiring (`rtk init`), opt-in via `config.json`.

Three sources, each graded per finding:
- Part A: how the `mcp` feature type flows through ai-badger (lane d-47, read-only code research).
- Part B: rtk install and integration surface, measured against rtk 1.0.1 in HOME-overridden /tmp sandboxes (lanes d-48/d-50).
- Part C: what the user's own machine already has (Claude session 61f1aa82, report from its history).

## Synthesis — load-bearing facts for the plan

1. [MEASURED] A local `rtk init` for Claude writes NO hook and no `.claude/settings.json`; only a `CLAUDE.md` marker block + `.rtk/filters.toml` (B F5). A project-level Claude hook therefore has to be written by ai-badger itself (PreToolUse `Bash` → `rtk hook claude`), or installed user-level with `-g`.
2. [MEASURED] Local `rtk init` for Codex and Copilot edits files ai-badger generates (`AGENTS.md` gets `@RTK.md`, `.github/copilot-instructions.md` gets a marker block) plus `.codex/hooks.json` / `.github/hooks/rtk-rewrite.json` (B F7, F8). Re-scaffolding would overwrite the instruction-file edits and the scaffold freshness guard would flag them (A F25).
3. [MEASURED] pi local writes only `.pi/extensions/rtk.ts`; `--auto-patch` overwrites a user's non-stock `rtk.ts` with no backup (B F9). Hermes has no project scope; it always writes `~/.hermes` (B F10).
4. [MEASURED] init is idempotent (B F11); uninstall leaves residue in 5 of 6 cases and Claude local uninstall is refused (B F12).
5. [MEASURED] Non-interactive recipe: `rtk init [-g] <flags> --auto-patch </dev/null` with `RTK_TELEMETRY_DISABLED=1`; exit 0 ok / 1 refusal / 2 bad args (B F13, F14).
6. [MEASURED/READ] Telemetry is opt-in, off by default; the Homebrew 1.0.1 build has no endpoint compiled in (B F15). Local tracking DB (`history.db`, 90 days) stays on disk.
7. [READ] Licence: CLI Apache-2.0, but the default build links BUSL-1.1 `rtk-engine`; an Apache-only `rtk-oss` edition exists without pipeline/PostToolUse features (B F2).
8. [READ] Floors: `--copilot` 0.34, Codex 0.36, hermes 0.40, pi 0.42; only 1.0.1 measured → pin `>=1.0.1` (B F4). Check: `rtk --version`; hook verification is per harness (`rtk init --show` covers Claude only; B F17).
9. [READ] No non-MCP CLI tool type exists in ai-badger; archify/uv are skill `dependencies.json` entries (A F27). Hook wiring today handles ai-badger's own scripts only; per-agent `adjust_*.py` adjustments are the seam for per-harness tool wiring (A F28). A minimal change set is in A, "Minimal change set".
10. [UNVERIFIED] How rtk's `updatedInput` PreToolUse rewrite composes with ai-badger's own Bash PreToolUse hooks in one Claude session.

# Part A — mcp feature type flow (lane d-47)

This is for adding a sibling `tools` feature type, starting with `features/common/tools/rtk/`. I made no edits and no commits. Paths are relative to the worktree root. `S=` stands for `features/common/skills/welcome-ai-badger/scripts`. The top-level `skills/` tree is the plugin mirror of `features/common/skills/`.

## 1. FeatureType registry and its consumers

### F1 — `mcp` is one row in a 4-field registry; adding a row is the only engine-side declaration [READ]
Evidence: `engine/badger_lib.py:39-57` (`FeatureType(name, index_rule, drift_reports_new, hashes_source=False)`, with `md_carrying` derived from `index_rule == "md"`), `:60-78` (the `FEATURE_TYPES` tuple; `mcp` is at `:77`), `:73-76` (the comment explains why `mcp` has no manifest entry and is not drift-reported).

### F2 — Every list derives from the registry, so a new row flows through automatically [READ]
The derived lists are `FEATURES` (`badger_lib.py:80`), `DRIFT_NEW_FEATURES` (`:82-84`), `_BY_NAME` / `feature_type()` (`:86`, `:99-101`) and `EXCLUDABLE_FEATURES = DRIFT_NEW_FEATURES` (`:91`). `INCLUDABLE_FEATURES` is a literal `("skills",)` (`:96`). `exclusions()` iterates `EXCLUDABLE_FEATURES` (`:119`). If `tools` gets `drift_reports_new=False`, it stays out of both drift's "new items" report and `config.exclude`.

### F3 — `iter_feature_dirs` picks up any `features/<stack>/<name>/` directory as soon as the name is registered [READ]
Evidence: `badger_lib.py:1146-1162` loops over `FEATURES`. Callers are `tooling/index_build.py:156`, `tooling/validate.py:652` (stack names) and `tooling/validate.py:760` (`_artifact_owners`, filtered to `REFERENCEABLE_FEATURES` at `:156`, so `tools` is ignored there). No stack currently has a `tools/` directory: `find features -maxdepth 3 -type d -name tools` returned nothing.

### F4 — Other consumers only read `hashes_source` [READ]
Evidence: `S/record_provenance.py:72-74`, `S/superseded_prune.py:98`, `features/common/skills/feed-badger/scripts/detect_additions.py:212`. These run on manifest entries, and `mcp` writes none (F1), so a `tools` row with `hashes_source=False` is inert there.

## 2. index_build

### F5 — Discovery is a rule-name → builder map; `_mcp_items` lists each subdirectory that contains `meta.json` [READ]
Evidence: `tooling/index_build.py:89-93` (`_mcp_items`), `:101-109` (`_RULES`, keyed by `FeatureType.index_rule`), `:158` (dispatch). A new `index_rule` value needs a `_RULES` entry or `build_index` raises `KeyError`. Reusing `index_rule="mcp"` would work as-is, but the name would read wrong.

### F6 — The module docstring documents each rule, and a test pins it [READ]
Evidence: `index_build.py:6-14`; `tests/test_mcp_feature_type.py:133-137` asserts `"mcp" in index_build.__doc__`.

### F7 — The index is validated against `index.schema.json`, whose per-stack properties are a hand-maintained list [READ]
Evidence: `index_build.py:193` validates. `schemas/index.schema.json:30-37` lists the eight feature keys. The containing object is closed (`additionalProperties: false`, around line 18; I inferred this from the `meta` block shape). So a `tools` bucket fails validation until `"tools": {"$ref": "#/$defs/featureList"}` is added.

### F8 — `--check` compares the in-memory index with `index.json`, and `index.json` ships [READ]
Evidence: `index_build.py:200-206`; `tooling/release_paths.py:14-24` lists `index.json` and `features` in `SHIPPED_PATHS`, so the change needs a VERSION bump.

## 3. scaffold, detect, validate, drift

### F9 — No `config.json` key selects mcp items; stacks plus `stack-mcp.json` do [READ]
`McpTools.collect_catalog_mcp_servers` reads `features/<stack>/stack-mcp.json` for every stack in `ctx.stacks`, with common first and the last writer winning. Evidence: `S/mcp_tools.py:184-206`, `features/common/stack-mcp.json:1-59`.

The config keys involved are:
- `mcp.approve` and `mcp.decline` (`schemas/config.schema.json:223-242`).
- `mcpToolIndex` (`:243-259`).

The config's top level is closed. Its current keys are `frameworkVersion, project, commonStacks, stacks, agents, sourceControl, commands, personaRouting, personaModelPins, skillScope, docs, include, exclude, mcp, mcpToolIndex, agentDocs, statusLineCapture, dataPolicy`, with `additionalProperties: false`. I checked this with python. There is no `tools` key yet.

### F10 — Nothing per-item is copied into `.ai-badger/`; mcp items reach a project only through document slots and generated config [READ]
Evidence: `badger_lib.py:73-76`. `scaffold.py` touches mcp only at:
- `:274` (constructs `McpTools`)
- `:572` and `:635-637` (adjustment context)
- `:713-715` (`fill_mcp_described` and the delegation map)
- `:727-733` (writes generated config)

### F11 — Per-harness config writes [READ]
- **Claude:** `.mcp.json`, through `generate_mcp_json` (`S/mcp_tools.py:872`, destination `MCP_JSON` at `:142-145`). Approval and deny rules go to `.claude/settings.json` via `features/claude/adjustments/adjust_mcp.py:1-6`. User-scoped servers are proposed for `~/.claude/settings.json` via `propose_claude_mcp_user` (`:771`, `CLAUDE_USER_SETTINGS` at `:152-156`).
- **Copilot CLI:** `.github/mcp.json` (`generate_copilot_mcp_json` at `:790`, destination at `:146-151`). The coding agent only gets a proposal (`features/copilot/adjustments/adjust_mcp.py:1-6`).
- **pi:** `.pi/mcp.json`, written as a union merge with `exposure="direct"` (`:895`, `PI_MCP_JSON` at `:159-163`). `features/pi/adjustments/adjust_mcp.py` only migrates legacy settings.json entries.
- **Codex:** an owned TOML block appended to `.codex/config.toml` (`features/codex/adjustments/adjust_mcp.py:1`; registered at `features/codex/adjustments/adjustment.json`, `"feature": "mcp"`).
- **Hermes:** a proposal only, for `~/.hermes/config.yaml` (`features/hermes/adjustments/adjust_mcp.py:1-6`).

Adjustments receive `mcp_servers`, `mcp_declarations` and `mcp_declined` in their context (`scaffold.py:621-638`).

### F12 — An availability gate drops servers whose binary is missing; the freshness guard forces it open [READ]
Evidence: `S/mcp_tools.py:240-266` (`availability.command`, with the `AI_BADGER_MCP_AVAILABILITY` override); `gates/scaffold_freshness_guard.py:81,224`. A `tools` gate (for example, wire rtk hooks only when `rtk` is on PATH) needs the same override, or the freshness guard stops being deterministic across machines.

### F13 — `detect.py` touches mcp only to recognise MCP-tool-only venvs [READ]
Evidence: `S/detect.py:225-264`. It globs `features/*/mcp/*/meta.json` for `package` names (`:246`). It does not select stacks.

### F14 — `validate.py` has hand-listed schema → instance globs, and a completeness test enforces them [READ]
Evidence: `tooling/validate.py:42-62` (`mcp-server.schema.json` → `features/*/mcp/*/meta.json` at `:50`); the comment at `:40-41` names `test_every_schema_has_a_coverage_decision`; the check is at `:373` and `:826`. `INLINED_BODY_GLOBS` includes `*/mcp/*/*.md` (`:161`). A `tools/*/*.md` body inlined into agent files needs a matching glob.

### F15 — drift never reports mcp items, and has no mcp-specific comparison [READ / INFERRED]
- [READ] `drift.py:199` iterates `DRIFT_NEW_FEATURES` only, which excludes `mcp`. The only mcp code in drift is the legacy `mcp-tools.yaml` note (`drift.py:437-452`).
- [INFERRED] A catalog change reaches a project through the `frameworkVersion` bump and a re-scaffold, plus the `generatedConfig` records in the manifest (`scaffold.py:752-754`).

## 4. Schemas

### F16 — `mcp-server.schema.json` defines `meta.json`: `name` (required), `package`, `description`, `homepage`, `prerequisite{summary (required), check, install, local{…}, global{…}}` [READ]
Evidence: `schemas/mcp-server.schema.json:1-74`. The sub-objects `local` and `global` each allow `summary, check, install, uv, command` (`:47-70`).

The description at `:30` says ai-badger never installs a server's prerequisite. The `code-review-graph` and `semantica` catalog entries ship `scripts/install.py` anyway, but only as text the operator runs (F19).

### F17 — `manifest.schema.json` has a hardcoded feature enum that includes `mcp`, and a test pins it [READ]
Evidence: `schemas/manifest.schema.json:64`; `tests/test_mcp_feature_type.py:142-146`. `tools` needs adding here even if it never writes an entry, for symmetry and the matching test.

### F18 — The tools sibling of `stack-mcp.json` is `stack-mcp.schema.json`, validated over `features/*/stack-mcp.json` [READ]
Evidence: `validate.py:49`. Tests are in `tests/test_mcp_feature_type.py:150-240` (`TestStackMcpSchema`).

## 5. Prerequisite check and install

### F19 — `meta.json`'s `prerequisite` is only reported as a scaffold note; `scripts/check.py` and `install.py` are never executed by ai-badger [READ]
`note_declared_prerequisites` formats `summary/check/install/local.install/global.install` into `ctx.notes` once per run, for declared and non-declined servers (`S/mcp_tools.py:269-301`, called from `declared_servers` at `:366`). The note ends with "ai-badger declares the server, it does not install it" (`:299-300`).

A search for `check.py` and `install.py` finds the scripts only in their own `meta.json` (`features/common/mcp/code-review-graph/meta.json:8-15`) and in tests (`tests/test_mcp_prerequisites.py:139-150`, `test_code_review_graph_mcp_scripts.py`, `test_semantica_mcp_scripts.py`).

### F20 — The `meta.json` check paths are framework-relative, so they don't resolve in a consumer repo [INFERRED]
`"check": "python3 features/common/mcp/code-review-graph/scripts/check.py"` (`meta.json:8`) is a path relative to the framework root. Per F10, mcp items are not copied into `.ai-badger/`, so the path does not exist in a consumer project. A `tools/rtk/scripts/check.py` would have the same problem unless `tools` items are materialised, or the note renders an absolute framework path.

### F21 — The precedent that actually executes installs is `dependencies.json` plus `dependency_check.py`, gated by `--execute` [READ]
`run_dependency_check(root, target, features=self.skills, allow_install=self.execute)` (`scaffold.py:531-553`). It installs `system`-ecosystem dependencies only when `--execute` is given and `command` is set, and otherwise emits a hint (`S/dependency_check.py:275-287`, `_install_system` at `:114-140`, `_pending_hint` at `:316-334`).

It is keyed by `feature` matched against delivered skill names, so the current filter would never select a `tools` item named `rtk`. The schema's ecosystem enum is `python|node|system` (`schemas/dependencies.schema.json:38-41`). There are no pip/npm installs without consent (`dependency_check.py:221-228`).

### F22 — welcome-ai-badger and den-refresh both reach this through `Scaffolder.run` [READ]
den-refresh loads and runs `scaffold.py`'s `Scaffolder` (`features/common/skills/den-refresh/scripts/refresh.py:242-260`). Its own `check_prerequisites` (`:202`, `:358-359`) checks ai-badger's own prerequisites (config.json and so on), not catalog items. The flags `--execute` and `--no-install` are defined at `scaffold.py:11-16` and `:279-280`.

## 6. How `server.md` reaches the agent files

### F23 — `server.md` is inlined verbatim through the `{{MCP_INSTRUCTIONS}}` slot; the `## MCP Tools: <name>` heading is part of each `server.md` [READ]
Steps:
1. `fill_mcp_described` collects available servers plus the `server.md` text found via the index (`S/mcp_tools.py:208-220`, `:303-326`).
2. `compute_doc_slots` sets `"MCP_INSTRUCTIONS"` with `_render_instruction_blocks` (`S/template_rendering.py:144-150`, `:177`).
3. The slot appears in `features/common/templates/CLAUDE.md.tmpl:40`, `HERMES.md.tmpl:61`, `features/pi/templates/AGENTS.override.md.tmpl:40` and `features/codex/templates/AGENTS.md.tmpl:40`.

The heading comes from the file itself, e.g. `features/common/mcp/playwright/server.md:1-2` (`<!-- Playwright MCP tools -->` / `## MCP Tools: playwright`).

The delegation map's `{{MCP_SERVERS}}` takes a one-line blurb from the same prose (`template_rendering.py:243-266`). A `tools` type needs a parallel `{{TOOLS_INSTRUCTIONS}}` slot in all four templates, or must reuse the mcp slot, which would mislabel rtk as an MCP tool.

## 7. Tests and regenerated files

### F24 — Tests that pin the registry or the mcp type [READ]
- `tests/test_badger_lib.py:655-684`: `FEATURES` is derived from the registry; `md_carrying == [personas, invariants, instructions]`; `DRIFT_NEW_FEATURES == (skills, personas, invariants, instructions)`. All of these stay true with `tools(drift_reports_new=False)`.
- `tests/test_config_exclude.py:60-64`
- `tests/test_mcp_feature_type.py:30-146` (registry, `_mcp_items` rules, index bucket, schema, docstring, manifest enum). This is the template to clone as `tests/test_tools_feature_type.py`.
- `tests/test_index_build.py:69-236`
- `tests/test_mcp_prerequisites.py:47-188`
- `tests/test_mcp_catalog_instructions.py`
- `tests/test_stack_mcp_servers.py`
- `tests/test_validate.py` (schema coverage decision)
- `tests/test_scaffold_delegation_map.py`
- `tests/test_mcp_declared_servers.py`

### F25 — Files to regenerate [READ / INFERRED]
- [READ] `index.json`, via `tooling/index_build.py`.
- [READ] `VERSION` plus `docs/changelog/<ver>-<slug>.md`, per the invariant and `release_paths.py`.
- [INFERRED] This repo's own self-scaffold (`AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md`, `HERMES.md`, `.hermes.md`, `.ai-badger/manifest.json`), which `gates/scaffold_freshness_guard.py` re-scaffolds and compares, if any tools prose lands in the agent files.
- `skills/` is the mirror maintained by `tooling/sync_plugin_skills.py`, and only matters if a skill changes.

## 8. Docs that list the feature types

### F26 — Docs listing feature types [READ]
- `docs/framework-architecture.md:24-38` (the discovery-rule table plus the stack-level files paragraph)
- `README.md:207-235` (the feature bullet list; `mcp` is at `:225-228`), `:299-305` (the server table) and `:343-370` (the tree and mermaid diagrams)
- `docs/dictionary.md:105` (the Adjustment row)
- `docs/adr/0014-mcp-support-is-configuration-not-retrieval.md` (the governing ADR). A `tools` type needs its own ADR.

## Precedents

### F27 — Existing non-MCP external CLI tools are handled as skill dependencies, not as a feature type [READ]
- archify needs Node 18+ and uv is needed by the task-graph CLI. Both are `system` entries in `features/common/dependencies.json` (`feature: archify`, `feature: task-decomposition`), installed only with `--execute` (F21).
- archify is vendored by `tooling/vendor_archify.py`.
- task-graph is the one hybrid: an MCP server launched through `uv` (`stack-mcp.json:44-57`), with a CLI twin under `task-decomposition`.

None of these is a top-level catalog type. rtk would be the first.

### F28 — Hook wiring is reusable for ai-badger-owned Python scripts only, not for wiring an external `rtk init` [READ / INFERRED]
- [READ] `HookWiring.wire` (`S/hook_wiring.py:213-330`) reads `features/common/hooks/hooks-manifest.json` and `hooks.json`, and writes only Claude `.claude/settings.json` registrations that point at `.ai-badger/skills/.../*.py`, guarded with `${CLAUDE_PROJECT_DIR}`.
- [READ] Copilot, Codex, Hermes and pi each have their own `adjust_hooks.py` (`features/{copilot,codex,hermes,pi}/adjustments/`). Codex publishes an allowlist of `SCRIPTS` (`features/codex/adjustments/adjust_hooks.py:14-18`). Per README `:219-222`, pi needs no per-hook arm (ADR-0022).
- [INFERRED] The closest reusable seam for an opt-in `rtk init` is the per-agent adjustment pipeline. A `features/<agent>/adjustments/adjust_tools.py` would receive the context at `scaffold.py:621-638`, extended with the declared tools, and can run or propose per-host commands, honouring `install` / `--no-install` the way Hermes does. The `scaffold.run` order (hooks wired at `:719`, adjustments at `:721`, the dependency check at `:723`) means an `--execute`-gated install would currently run after the adjustments that wire it.

## Minimal change set to add a `tools` feature type

1. `engine/badger_lib.py`: add `FeatureType("tools", "tools", False)` with a comment in the style of `:73-76`.
2. `tooling/index_build.py`: add `_tools_items` (subdirectories with `meta.json`), a `_RULES["tools"]` entry and a docstring line.
3. `schemas/index.schema.json`: add a `"tools"` featureList property.
4. `schemas/manifest.schema.json:64`: add `"tools"` to the enum.
5. New `schemas/tool.schema.json` for `features/*/tools/*/meta.json`, modelled on `mcp-server.schema.json`: `name`, `package`, `description`, `homepage`, `prerequisite{summary, check, install, local, global}`, and possibly `hooks` / `init` per harness.
6. `schemas/config.schema.json`: a new top-level `tools` object (for example `{enable:[...], hooks:{<agent>:bool}}` for the opt-in wiring). The decline/approve semantics are still open.
7. `tooling/validate.py`: a `SCHEMA_INSTANCES` entry for the new schema; an optional `INLINED_BODY_GLOBS` entry `*/tools/*/*.md`.
8. Scaffold side: a new collaborator `S/tool_catalog.py`, modelled on `mcp_tools.py`, covering collect / available / prerequisite note / described. Wire it in `S/scaffold.py` (constructor, `run()`, adjustment context) and `S/scaffold_context.py` (`tools_described`, noted flags).
9. `S/template_rendering.py`: a `{{TOOLS_INSTRUCTIONS}}` slot, added to `features/common/templates/CLAUDE.md.tmpl`, `HERMES.md.tmpl`, `features/pi/templates/AGENTS.override.md.tmpl` and `features/codex/templates/AGENTS.md.tmpl`.
10. Per-harness hook wiring (opt-in): `features/{claude,copilot,codex,pi,hermes}/adjustments/adjust_tools.py` plus the matching `adjustment.json` entries.
11. Catalog: `features/common/tools/rtk/{meta.json, tool.md, scripts/check.py, scripts/install.py}`, plus a stack-level declaration if declaring stays separate from describing (a `stack-tools.json` equivalent to `stack-mcp.json`, with its own schema and validate entry).
12. Tests: `tests/test_tools_feature_type.py` (clone of `test_mcp_feature_type.py`), check/install script tests (clone of `test_code_review_graph_mcp_scripts.py`), prerequisite-note tests (clone of `test_mcp_prerequisites.py`), and slot-injection tests (clone of `test_mcp_catalog_instructions.py`). The `test_validate.py` coverage decision updates automatically.
13. Regenerate `index.json`; bump `VERSION` and add the changelog entry; add an ADR next to ADR-0014; update `docs/framework-architecture.md:24-38` and `README.md:207-235` / `:343-370`; and re-scaffold this repo's own agent files if the slot renders text.

## Still open
- **Declaring vs. describing:** should `tools` copy mcp's split between a stack-level declaration and the catalog entry, or should having `meta.json` be enough? That decides whether a stack-tools schema and file are needed.
- **Running check.py:** does ai-badger execute `scripts/check.py` / `install.py` under `--execute`, which mcp never does (F19), or only report them in the scaffold notes? If it runs them, how are framework-relative paths resolved in consumer repos (F20)? Running them would extend `dependency_check`'s keying beyond skill names (F21).
- **[UNVERIFIED] What `rtk init` writes per harness:** the exact files, whether it is idempotent, and whether it overlaps ai-badger's managed `.claude/settings.json` hooks merge. I did not check this against rtk's docs. It is needed before deciding whether the Claude arm runs `rtk init` or writes the hook through `HookWiring` / `merge_hooks` itself.
- **Hermes and Copilot coding agent:** they have no project route for MCP (proposal only). Is rtk hook support for them proposal-only too?
- **Availability gating:** whether `tools` should honour `AI_BADGER_MCP_AVAILABILITY` (or a new `AI_BADGER_TOOLS_AVAILABILITY`) to keep `scaffold_freshness_guard` deterministic (F12).
- **Naming:** `features/mcp/` is a stack, not just the feature type. No `tools` stack exists, but a future stack named `tools` would collide in the same way.

# Part B — rtk install and integration surface (lanes d-48/d-50)

Date: 2026-10-17. Tested against local Homebrew `rtk 1.0.1`. Upstream source is at `/tmp/rtk-src`, at HEAD `4ef8730`, tag `v1.0.1`/`latest`. Experiment outputs are in `/tmp/rtkres/*`, made by `run.sh`. That script overrides `HOME`, `XDG_*` and `CODEX_HOME` to `/tmp/rtkhome-<name>` and runs in a temp repo `/tmp/rtkrepo-<name>`, with stdin from `/dev/null`. I reused the earlier lane's artifacts and only re-ran what was missing: `--show`, `--dry-run`, exit codes, verification commands, and the case where a project already has its own pi extension (`/tmp/rtkhome-pip`, `/tmp/rtkrepo-pip`).

Note on this session: the bash tool here already sends output through rtk. Plain `grep`, `cat` and `find` came back compressed or rewritten, so I read evidence with `/usr/bin/*` and `/bin/cat`.

## 1. Install, license, versions

### F1 — Supported install methods: Homebrew, the curl script, winget, cargo from git, and release assets [READ]
- macOS and Linux: `brew install rtk` (the formula is `rtk: stable 1.0.1 (bottled)`).
- Any Unix: `curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh`. It installs to `${RTK_INSTALL_DIR:-$HOME/.local/bin}`.
- Windows: `winget install rtk-ai.rtk`.
- From source: `cargo install --git https://github.com/rtk-ai/rtk rtk`. Upstream warns that `cargo install rtk` from crates.io is a different crate ("Rust Type Kit").
- Release assets are `rtk-<target>`, `rtk-oss-<target>`, `.deb` and `.rpm`.

Evidence: `INSTALL.md:47,58,65,71,80-89`; `install.sh:9-18`; `brew info rtk`.

### F2 — The default build is not Apache-2.0 only [READ]
- The CLI itself is Apache-2.0.
- The default build links `rtk-engine`, which is BUSL-1.1 (source-available). Its use grant covers running it as part of `rtk`.
- The `rtk-proxy` daemon is also BUSL-1.1.
- An Apache-2.0-only edition exists: `RTK_EDITION=oss` for the curl script, `brew install rtk-ai/tap/rtk-oss`, or `cargo … --no-default-features`. It has no `rtk pipeline`, no PostToolUse compression and no delegation tasks.
- Both editions install a binary named `rtk`, so they cannot be installed side by side.

Evidence: `README.md:14,96,134-135,345-357`; `INSTALL.md:73-89`; `Cargo.toml:30`.

### F3 — Latest release is v1.0.1 (2026-10-14); check with `rtk --version` [READ/MEASURED]
- `rtk --version` prints `rtk 1.0.1`.
- Upstream says to confirm you have the right binary with `rtk gain`, which shows the dashboard rather than "command not found".

Evidence: `git log -1` in `/tmp/rtk-src` shows `tag: v1.0.1, tag: latest, origin/master`; `Cargo.toml:25`; `INSTALL.md:52`.

### F4 — Earliest version per flag: `--copilot` 0.34.0, Codex 0.36.0, `--agent hermes` 0.40.0, `--agent pi` 0.42.0. A safer floor is 0.50.0, and pinning 1.0.x is better [READ]
- `--copilot`: added in 0.34.0 (`feat(init): add --copilot flag`). Since 0.41.0 it keeps user content in `copilot-instructions.md`.
- Codex: the earliest entries are in 0.36.0 (it honours `CODEX_HOME`). In 0.50.0, `rtk init --codex` stopped touching the user's own files and stays inside the project.
- `--agent hermes`: added in 0.40.0.
- `--agent pi`: added in 0.42.0 (`hook: add pi support`). A barrel-import fix came in 0.47.0.

All the file-level behaviour below was only measured on 1.0.1, so the feature should pin `>=1.0.1`.

Evidence: `/tmp/rtk-CHANGELOG-master.md` lines 782, 439, and the hermes/codex/copilot entries (via an awk version map).

## 2. What `rtk init` writes, per harness

### F5 — A local Claude init does not write `.claude/settings.json` and registers no hook [MEASURED/READ]
- `rtk init --auto-patch` without `-g` writes only two files: `./CLAUDE.md`, containing a `<!-- rtk-instructions v2 -->…<!-- /rtk-instructions -->` block (509 B when the file is new), and `./.rtk/filters.toml`, a commented template.
- This is deliberate in the source: "Project scope writes the awareness block and a filters template, and stops. Registering a hook… stays with `-g`".
- So a local init cannot collide with the `.claude/settings.json` ai-badger merges into. The hook only exists after `-g`, which writes the user-level `~/.claude/settings.json`.

Evidence: `claude-l.r1`; `claude-l.repocopy/CLAUDE.md`; `src/hooks/init/mod.rs:947-951`.

### F6 — `rtk init -g` for Claude writes four things, merges into existing hooks, and reformats the file [MEASURED]
It writes:
- `~/.claude/RTK.md`
- `~/.claude/CLAUDE.md`, adding a line `@RTK.md`
- `~/.claude/settings.json`, adding `PreToolUse:[{matcher:"Bash",hooks:[{type:"command",command:"rtk hook claude"}]}]`
- `~/Library/Application Support/rtk/filters.toml`

On the preserved setup, which already had `model`, a `python3 mine.py` Bash hook and a `SessionStart` hook:
- rtk appended its entry and kept the other keys.
- It wrote a `.bak` of the original, which was minified JSON, and re-emitted the file pretty-printed.

What this means for ai-badger:
- Any byte-level drift check on a settings file rtk has touched will fire once.
- When both hooks are active, Claude runs both PreToolUse Bash hooks. rtk's hook returns `updatedInput` (for example `git status` becomes `rtk git status`), and how that interacts with ai-badger's own Bash PreToolUse hooks is untested (see Still open).

Evidence: `claude-g.homecopy/.claude/settings.json`; `pres.home.inst/.claude/settings.json(.bak)`; `rtk hook claude` with stdin JSON produced `{"hookSpecificOutput":{…"updatedInput":{"command":"rtk git status"}}}`.

### F7 — Codex local writes three project files; Codex global writes three files under `CODEX_HOME` [MEASURED]
- `rtk init --codex` writes:
  - `./RTK.md`
  - `./AGENTS.md` with `@RTK.md`
  - `./.codex/hooks.json`, with a `PreToolUse` Bash entry running `rtk hook codex`

  When `.codex/hooks.json` already exists, it is merged (existing `SessionStart` kept) and backed up to `.bak`.
- `-g --codex` writes `$CODEX_HOME/{RTK.md,AGENTS.md,hooks.json}`.
- Both print advice about a sandbox `writable_roots` setting but do not change `config.toml`.
- `--codex` together with `--no-patch` is refused with exit 1.

Evidence: `codex-l.log`, `codex-g.log`, `pres.repo.inst/.codex/*`, `codex-lnp.log`.

### F8 — Copilot local writes into `.github/`; global writes into `~/.copilot/` [MEASURED]
- Local: `.github/hooks/rtk-rewrite.json`, containing `{"version":1,"hooks":{"PreToolUse":[{"type":"command","command":"rtk hook copilot","cwd":".","timeout":5}]}}`, plus an instructions block in `.github/copilot-instructions.md`. Existing content in that file is kept.
- Global: `~/.copilot/hooks/rtk-rewrite.json` and `~/.copilot/copilot-instructions.md`.

Evidence: `copilot-l.log`, `copilot-g.log`, `pres.repo.inst/.github/*`.

### F9 — Pi local writes `.pi/extensions/rtk.ts`; global writes `~/.pi/agent/extensions/rtk.ts`. Nothing else is touched [MEASURED]
- No instruction files and no settings are changed.
- If a different `rtk.ts` already exists:
  - with no flag or `--no-patch`, rtk refuses with exit 1 and leaves the file alone;
  - with `--auto-patch`, rtk overwrites the file and keeps no backup. The user's file is lost.

Evidence: `pi-l.log`, `pi-g.log`; `/tmp/rtkrepo-pip` runs (outputs quoted in this lane: "Overwrite the non-stock Pi extension…? (non-interactive mode, defaulting to N)", EXIT=1; then with `--auto-patch` EXIT=0 and the file header is now `// RTK Pi extension`).

### F10 — Hermes has no project-scope install: with or without `-g`, init writes `~/.hermes` [MEASURED]
- Files: `~/.hermes/plugins/rtk-rewrite/{plugin.yaml,__init__.py}`, plus `rtk-rewrite` added to `plugins.enabled` in `~/.hermes/config.yaml`.
- Other keys and other plugins in `config.yaml` are kept.
- The `-l` and `-g` runs produce identical hashes.

Evidence: `hermes-l.h1` equals `hermes-g.h1`; `pres.home.inst/.hermes/config.yaml`.

## 3. Idempotency and uninstall

### F11 — Running init twice changes nothing except rtk's own `history.db` [MEASURED]
- In every harness, the second run left every file hash unchanged apart from `~/Library/Application Support/rtk/history.db`. Claude and Codex runs record the init call there.
- Second-run messages say "already present" or "already up to date".

Evidence: the `### idempotency diff` section of each `*.log`.

### F12 — Uninstall removes rtk's own content, but leaves something behind in five cases [MEASURED]
- Claude local: `--uninstall` is refused with exit 1 ("Uninstall only works with --global flag…"). The `CLAUDE.md` block and `.rtk/filters.toml` stay; ai-badger would have to remove the marker block itself.
- Claude `-g`: removes `RTK.md`, `CLAUDE.md` (when rtk created it) and its hook. It leaves `settings.json` as `{}`, a `settings.json.bak`, and the global `filters.toml`.
- Codex: leaves `hooks.json` with `"PreToolUse": []`, a `hooks.json.bak`, and a 0-byte `AGENTS.md` when rtk created it.
- Copilot: leaves `copilot-instructions.md` containing just `"\n"`.
- Hermes: leaves `plugins: enabled: []`.
- Pi: removed cleanly.

On the preserved pre-existing setup, the user's content survived uninstall each time: Claude's `model` and other hooks, the Codex `SessionStart` hook, the text in `AGENTS.md` and `CLAUDE.md`, the Copilot text, and Hermes `other-plugin`. Two side effects remain: the JSON stays pretty-printed (formatting is not restored), and the trailing newline of the global `CLAUDE.md` was dropped.

Evidence: `*.hu`/`*.ru` (the hash `da39a3ee5e6b` is the empty file, `adc83b19e793` is `"\n"`); `rtkhome-pres/*` and `rtkrepo-pres/*` compared with `pres.*.inst`.

## 4. Running non-interactively, and exit codes

### F13 — Non-interactive recipe: `rtk init [-g] <harness flags> --auto-patch </dev/null` with `RTK_TELEMETRY_DISABLED=1` (and `RTK_ONRAMP_DISABLED=1` for safety) [MEASURED/READ]
The prompts init can raise are:
- telemetry consent
- permission to patch `settings.json`
- the proxy on-ramp (only in the default ask mode)
- overwriting a non-stock pi extension
- trusting custom filters (`--trust-filters` or `--no-trust-filters`)

When stdin is not a TTY, each prompt defaults to "No". The source warns that a pseudo-TTY, as in devcontainers or some CI, can hang the telemetry prompt; `RTK_TELEMETRY_DISABLED=1` short-circuits it.

`--dry-run` writes nothing and lists each planned write (measured: zero files created).

Evidence: `src/hooks/init/mod.rs:986-999,1298-1320`; the dry-run output in this lane.

### F14 — Exit codes: 0 success, 1 refusal, 2 bad arguments [MEASURED]
- 0: success, including the "already present" cases.
- 0: uninstalling when nothing is installed (`codex-lnp`).
- 1: refusals — Claude local uninstall, `--codex` with `--no-patch`, a non-stock pi extension without `--auto-patch`.
- 2: clap argument errors — an invalid `--agent`, or `--auto-patch` with `--no-patch`.

Evidence: the logs plus this lane's runs.

## 5. Telemetry and network

### F15 — Telemetry is opt-in and off by default, and the Homebrew 1.0.1 build cannot send any [MEASURED/READ]
- Nothing is sent unless `telemetry.consent_given = true` and `telemetry.enabled` is set. `maybe_ping` also returns early if `RTK_TELEMETRY_DISABLED=1` (exactly the string "1") or if no endpoint was compiled in.
- When enabled, it sends one HTTPS POST per day from a background thread, with a 2 s timeout.
- `rtk telemetry status` on this build reports: `consent: never asked`, `enabled: no`, `device hash: (not applicable; this build has no telemetry endpoint)`.
- Other commands: `rtk telemetry disable` and `rtk telemetry forget`. Config key: `[telemetry] enabled = false`.

Evidence: `src/core/telemetry.rs:16-17,33-58`; `telemetry_cmd.rs:5-6,97-98`; `docs/TELEMETRY.md:24-27,123-135`.

### F16 — Other network paths exist, but init does not use them non-interactively [READ/MEASURED]
- The LLM proxy daemon listens on `127.0.0.1:8080`. It is only offered in ask mode; `--auto-patch` and `--no-patch` never adopt it.
- Remote pipelines are installed through the user's own `gh`.
- Several commands probe proxy reachability. `rtk gain` printed "LLM proxy: running on 127.0.0.1:8080" — that is a daemon on this machine, not something init started.
- Local data stays on disk: `[tracking] enabled=true`, `history_days=90`, and the `[retriever]` SQLite store. To lock this down, set `tracking.enabled=false` or use the `RTK_DB_PATH` / `RTK_RECALL=0` overrides.

Evidence: `mod.rs:986-1001`; `pipeline_remote.rs:1-5`; `rtk config` output.

## 6. Checking that the hook is active

### F17 — Use `rtk init --show` for Claude, `rtk verify` for integrity, and `rtk gain` for real usage; `rtk pipeline validate` does not check hooks [MEASURED]
- `--show` exits 0 and reports `[ok] Hook: rtk hook claude`, `[ok] settings.json: RTK hooks configured`, and so on. It only covers Claude, OpenCode and Cursor, not pi, hermes, codex or copilot. It also exits 0 when nothing is installed, so read the `[ok]`/`[--]` lines rather than the exit code.
- `rtk verify` exits 0 even when the hook is missing (`SKIP RTK hook not installed`). Look for `PASS  native binary hook registered`.
- `rtk gain` shows savings once commands have gone through rtk ("No tracking data yet" before that), and is upstream's own recommended check.
- `rtk pipeline validate` prints `pipeline: ok (rtk:default)` and only validates the compression pipeline configuration.
- The local init's footer status line `hooks: registered globally` is also unreliable: it reports `Ok` whenever `~/.claude` does not exist.

For the other harnesses, ai-badger should check for the written files itself (F7–F10).

Evidence: this lane's runs; `src/hooks/hook_check.rs:26-34`.

## 7. Config and data directories

### F18 — On macOS, config and data both live in `~/Library/Application Support/rtk`; `XDG_CONFIG_HOME` is ignored, and `RTK_CONFIG_DIR` only moves pipeline config [MEASURED/READ]
- rtk uses the Rust `dirs` crate. With `XDG_*` set, `config.toml`, `filters.toml` and `history.db` still landed under `$HOME/Library/Application Support/rtk`.
- `RTK_CONFIG_DIR` only moves the pipeline config root (`pipeline_config.rs:79-88`). `config.toml` always resolves through `user_dirs::config()` (`config.rs:510-512`).
- The tracking database can be moved with `RTK_DB_PATH`.
- The docs give the path as `~/.local/share/rtk/tracking.db`. That is the Linux location, and the file is actually named `history.db` in 1.0.1.

Evidence: `*.h1` hashes; `src/core/user_dirs.rs:50-66`; `rtk config` printing `Config: …/Library/Application Support/rtk/config.toml`.

## Per-harness summary

| Harness | Init command (non-interactive) | Files written | Idempotent | Uninstall clean |
|---|---|---|---|---|
| Claude (local) | `rtk init --auto-patch` | `./CLAUDE.md` (marker block), `./.rtk/filters.toml`. **No hook, no `.claude/settings.json`** | yes | **no**: refused, exit 1; block and template stay |
| Claude (global) | `rtk init -g --auto-patch` | `~/.claude/{RTK.md,CLAUDE.md(@RTK.md),settings.json(PreToolUse Bash → rtk hook claude)}`, global `filters.toml` | yes | partly: user content kept; leaves `{}`/pretty-printed JSON, `.bak`, `filters.toml` |
| Codex (local) | `rtk init --codex` | `./RTK.md`, `./AGENTS.md(@RTK.md)`, `./.codex/hooks.json` (+`.bak` if it existed) | yes | partly: `PreToolUse: []`, `.bak`, empty `AGENTS.md` left |
| Codex (global) | `rtk init -g --codex` | `$CODEX_HOME/{RTK.md,AGENTS.md,hooks.json}` | yes | partly: same leftovers |
| Copilot (local) | `rtk init --copilot --auto-patch` | `.github/hooks/rtk-rewrite.json`, block in `.github/copilot-instructions.md` | yes | almost: `"\n"` file left when rtk created it |
| Copilot (global) | `rtk init -g --copilot --auto-patch` | `~/.copilot/hooks/rtk-rewrite.json`, `~/.copilot/copilot-instructions.md` | yes | almost: same |
| Pi (local) | `rtk init --agent pi --auto-patch` | `.pi/extensions/rtk.ts` (with `--auto-patch`, overwrites a user's file with no backup) | yes | yes |
| Pi (global) | `rtk init -g --agent pi --auto-patch` | `~/.pi/agent/extensions/rtk.ts` | yes | yes |
| Hermes (local = global) | `rtk init [-g] --agent hermes --auto-patch` | `~/.hermes/plugins/rtk-rewrite/*`, `plugins.enabled` entry in `~/.hermes/config.yaml` | yes | almost: `enabled: []` left |

## Still open
- Combined Claude hooks: what happens when ai-badger's own PreToolUse Bash hooks and `rtk hook claude`'s `updatedInput` run together in one session. That decides order and wins-last behaviour and needs a live Claude test. Not measured.
- Exactly when the Codex hooks.json integration started (somewhere between 0.36.0 and 0.50.0). I would pin `>=1.0.1` anyway, since that is the only version measured.
- Windows and Linux directory layout, and how the Windows `winget` build behaves. Not tested.
- What exit code 3 from `rtk rewrite "git status"` means. Observed, not looked up; it may matter if ai-badger scripts call `rtk rewrite`.
- Whether release binaries other than Homebrew have a telemetry endpoint compiled in. On those builds the consent and env gates would be what stops pings. Not checked.

# Part C — existing local setup (Claude session 61f1aa82)

- rtk 1.0.1 brew, pre-existing. Ran `rtk init -g --auto-patch` (Claude only). Pre-existing: PreToolUse `rtk hook claude`, ~/.claude/RTK.md (slim), @RTK.md in ~/.claude/CLAUDE.md. init added PostToolUse `rtk hook claude` matcher `Bash|Read|Grep|Glob|WebFetch|WebSearch|mcp__.*`.
- ~/.config/rtk/pipeline.toml rewritten: extends rtk:posthook + rtk:proxy; [upstream.haiku] anthropic claude-haiku-5-5, api_key_command reads 1Password ~/.env FIFO; [task.compact] digest; after-tool rules keep-verbatim(git diff/show, recall), compact shell/web >5000 tok, mcp >6000. ~/Library/Application Support/rtk/pipeline.toml -> symlink to it.
- ~/.config/zsh/dotenv.zsh + ~/.zshenv source line: loads 1Password FIFO ~/.env (ANTHROPIC_API_KEY) — personal, out of scope.
- ANTHROPIC_BASE_URL=http://127.0.0.1:8080 in ~/.claude/settings.json env = rtk llm-proxy (INFERRED from rtk gain + ~/Library/Application Support/rtk/llm-proxy/rtk-proxy.log); start mechanism unknown.
Gotchas: macOS config dir is ~/Library/Application Support/rtk (ignores XDG; RTK_CONFIG_DIR works); `rtk init -g` prompts unless --auto-patch; new after-tool rules need `rtk init -g` (validate says "hook needed"); restart harness after init; haiku-5-5 rejects temperature (silent fallback); `--dry-run -v` rejected; telemetry enabled+consent in config.toml by default.
Unverified: init idempotency, --uninstall, PostToolUse route in live session.
Unresolved: global ANTHROPIC_API_KEY export may override Claude Max login.
