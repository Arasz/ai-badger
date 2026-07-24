# Known gaps & follow-ups

Honest list of what's not yet done, ordered by impact. None block the core loop
(welcome scaffolds; feed detects + PRs), which is dogfooded and green.

## Resolved

1. ~~**Plugin-level hooks not auto-wired.**~~ **Fixed in v0.8.0.** `scaffold.py` now has
   `wire_hooks()` that reads `hooks-manifest.json`, rewrites hook paths to the scaffolded
   `.ai-badger/skills/` directory, and merges registrations into `.claude/settings.json`.
   Idempotent — skips hooks already registered.

2. ~~**`schema.json` vs `$schema` key.~~ **Fixed in v0.8.0.** All 9 schemas now allow
   `$schema` as a property with `"type": "string"`.

3. ~~**Extensions not config-gated.**~~ **Fixed in v0.10.1.** Extensions moved from external
   `features/<stack>/skills/task-extensions/` to inline `features/common/skills/task/extensions/`
   with `extension.json` requires conditions. `scaffold.py` prunes inline extensions whose
   config requirements aren't met. `requirement_met()` handles both `==` and `=` syntax.

4. ~~**Drift detection compared source hash, not scaffolded output.**~~ **Fixed in v0.10.1.**
   Manifest directory entries now hash the TARGET dir (after extension embedding/pruning)
   so `detect_additions` sees the actual scaffolded state.

5. ~~**Stale `task-extensions/` references in docs.**~~ **Fixed in v0.10.1.** Updated
   `ai-badger-framework-design.md`, `framework-architecture.md`, `authoring-a-feature.md`,
   and `hermes-claude-compatibility.md` to reflect the inline extension layout. Historical
   specs and changelogs left as-is.

6. ~~**Essential agent files are full copies, not proxies.**~~ **Dropped.** `CLAUDE.md`,
   `.github/copilot-instructions.md`, and `.junie/AGENTS.md` are copied from `.ai-badger/` with a
   managed header. The thin-proxy alternative is a documented spike — see `proxy-files-spike.md`.
   Symlinks break on Windows and cross-agent incompatibility (Copilot doesn't follow
   symlinks reliably). Full copies with managed headers are the proven approach.

7. ~~**Migration of job-search-ai-assistant deferred.**~~ **Dropped.** That repo remains the
   ad-hoc source; it has not yet been rewired to consume skills from this marketplace (a
   deliberate, separate follow-up).

8. ~~**Non-standard existing agent files aren't merged.**~~ **Fixed in v0.10.1.** `scaffold.py`
   now detects known non-standard agent file equivalents (e.g. root `COPILOT_INSTRUCTIONS.md`)
   and warns the user to reconcile. Detection uses `_NONSTANDARD_AGENT_FILES` mapping —
   extensible for future agents.

9. ~~**`task` skill scripts not exercised end-to-end.**~~ **Fixed in v0.10.1.** Added
   `test_full_lifecycle_start_subagent_finish_grade` integration test exercising the complete
   start → subagent → finish → grade → status cycle.

10. ~~**Plugin install is advisory by default.**~~ **Resolved.** The `--execute` flag runs
    install commands automatically with 30s timeout and error handling. Advisory default is
    intentional — `--execute` is the opt-in for automation.

## Open

11. **Catalog is MVP-sized.** Several stacks have instructions/invariants but no dedicated persona
    (e.g. `ts`, `js`, `css`, `terraform`, `mcp`). Personas exist where clearly justified
    (`dotnet`, `azure`, `node`, `react`, `angular`) plus the three base roles. Grow the catalog via
    `feed-badger` over time rather than front-loading speculative content.
