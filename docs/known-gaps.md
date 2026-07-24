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

## Open

3. **Essential agent files are full copies, not proxies.** `CLAUDE.md`,
   `.github/copilot-instructions.md`, and `.junie/AGENTS.md` are copied from `.ai-badger/` with a
   managed header. The thin-proxy alternative is a documented spike — see `proxy-files-spike.md`.
   **Deferred** — symlinks break on Windows and cross-agent incompatibility (Copilot doesn't follow
   symlinks reliably). Full copies with managed headers are the proven approach.

4. **Non-standard existing agent files aren't merged.** A repo may already ship a root
   `COPILOT_INSTRUCTIONS.md` (the arasz-home-page dogfood does). `welcome-ai-badger` writes the
   standard `.github/copilot-instructions.md` and leaves the old file in place; the two coexist.
   **Deferred** — merge logic is complex edge case. Follow-up: detect and reconcile pre-existing
   agent instruction files.

5. **`task` skill scripts not exercised end-to-end in a scaffolded project.** The
   dogfood ran `welcome`/`feed`, not a full `/task` cycle inside the scaffolded repo. The
   tracking scripts compile and smoke-test, but a real task run in a scaffolded project is untested.
   Follow-up: write integration test exercising `start` → `finish` → `grade` lifecycle.

6. **Plugin install is advisory by default.** `scaffold.py` prints `claude plugin marketplace add` /
   `plugin install` commands per chosen scope. The new `--execute` flag runs them automatically
   with 30s timeout and error handling. Default behavior unchanged (advisory/prints only).

7. **Catalog is MVP-sized.** Several stacks have instructions/invariants but no dedicated persona
   (e.g. `ts`, `js`, `css`, `terraform`, `mcp`). Personas exist where clearly justified
   (`dotnet`, `azure`, `node`, `react`, `angular`) plus the three base roles. Grow the catalog via
   `feed-badger` over time rather than front-loading speculative content.

8. **Migration of job-search-ai-assistant deferred.** That repo remains the ad-hoc source; it has
   not yet been rewired to consume skills from this marketplace (a deliberate, separate follow-up).
