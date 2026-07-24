# Known gaps & follow-ups (v0.1.0)

Honest list of what the MVP does not yet do, ordered by how likely each is to bite. None block
the core loop (welcome scaffolds; feed detects + PRs), which is dogfooded and green.

1. **Plugin-level hooks are not auto-wired.** `prompt-markers` bundles hook scripts
   inside its skill dir, but the plugin has no root `hooks/hooks.json`, so installing the
   plugin does not by itself activate the `UserPromptSubmit`/gate hooks. Follow-up: either add a
   plugin-level `hooks/hooks.json`, or have `welcome-ai-badger` wire the hooks into the target
   project's `.claude/settings.json`. Until then, hooks must be wired manually per the skills' docs.
   (`auto-wm` was moved to `features/claude/skills/` — it uses Claude Code-specific hooks.)

2. **`agent-instructions/schema.json` vs `$schema` key.** The ported model schema sets
   `additionalProperties: false` without allowing a `$schema` property, yet `model.template.json`
   declares `$schema`. The `.mjs` validators use duck-typed checks (not `jsonschema`), so nothing
   breaks today; if strict JSON-Schema validation is added, loosen the schema to permit `$schema`.

3. **Essential agent files are full copies, not proxies.** `CLAUDE.md`,
   `.github/copilot-instructions.md`, and `.junie/AGENTS.md` are copied from `.ai-badger/` with a
   managed header. The thin-proxy alternative is a documented spike — see `proxy-files-spike.md`.

4. **Non-standard existing agent files aren't merged.** A repo may already ship a root
   `COPILOT_INSTRUCTIONS.md` (the arasz-home-page dogfood does). `welcome-ai-badger` writes the
   standard `.github/copilot-instructions.md` and leaves the old file in place; the two coexist.
   Follow-up: detect and reconcile pre-existing agent instruction files.

5. **`task` skill scripts ported but not exercised end-to-end in a scaffolded project.** The
   dogfood ran `welcome`/`feed`, not a full `/task` cycle inside the scaffolded repo. The
   tracking scripts compile and smoke-test, but a real task run in a scaffolded project is untested.

6. **Plugin install is advisory.** `scaffold.py` prints the `claude plugin marketplace add` /
   `plugin install` commands per chosen scope rather than shelling out. Automating this behind a
   flag is a follow-up.

7. **Catalog is MVP-sized.** Several stacks have instructions/invariants but no dedicated persona
   (e.g. `ts`, `js`, `css`, `terraform`, `mcp`). Personas exist where clearly justified
   (`dotnet`, `azure`, `node`, `react`, `angular`) plus the three base roles. Grow the catalog via
   `feed-badger` over time rather than front-loading speculative content.

8. **Migration of job-search-ai-assistant deferred.** That repo remains the ad-hoc source; it has
   not yet been rewired to consume skills from this marketplace (a deliberate, separate follow-up).
