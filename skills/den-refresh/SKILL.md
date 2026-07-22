---
name: den-refresh
description: >-
  Pull framework updates into an already-scaffolded ai-badger project. Use when
  the framework has new features or fixes and you want to update a project's
  .ai-badger/ content — "den-refresh", "refresh my project from the framework",
  "pull ai-badger updates", "update the scaffold". Checks what changed upstream,
  re-scaffolds with the existing config, and reports the result.
---

# den-refresh

Pulls framework updates from the ai-badger catalog into a project that was
already scaffolded. **The script does all mechanical work; you (the agent)
present the report and help the user review the diff.**

This is the update direction of the framework: framework → project (update).
For initial setup use `welcome-ai-badger`; to contribute back use `feed-badger`.

## Responsibility split

- **Script (mechanical):** `refresh.py` validates prerequisites (config.json,
  manifest.json), runs drift detection, re-scaffolds with the existing config,
  and emits a JSON report. Skills with extensions (e.g., `task` with
  `github`/`hermes` extensions) are re-scaffolded and their extensions
  re-embedded automatically.
- **You (creative only):** present the report, help the user review what
  changed, and offer to commit or discard. There is no config authoring, no
  stack detection, no plugin scope prompt — those belong to `welcome-ai-badger`.

## Prerequisites

- Project has `.ai-badger/config.json` and `.ai-badger/manifest.json` (it was
  scaffolded by `welcome-ai-badger`)
- An ai-badger framework checkout is accessible (`$AI_BADGER`)

## Flow

1. **Run refresh.** From the target repo root:
   ```bash
   python3 "$AI_BADGER/skills/den-refresh/scripts/refresh.py" --target . --root "$AI_BADGER"
   ```
   This:
   - Validates that config.json and manifest.json exist
   - Reads the manifest to extract scaffolded skill names
   - Runs drift detection against the framework's current content
   - If drift is found, re-scaffolds using the existing config.json
   - Outputs a JSON report with drift details and scaffold notes

   Exit codes: 0 = success (up to date or changes applied), 2 = error (missing
   config/manifest, invalid config).

2. **Review the report.** The JSON output includes:
   - `frameworkVersion` — what version the project was scaffolded with vs. current
   - `drift.changed` — framework files that differ from the scaffolded copies
   - `drift.removed` — scaffolded files whose framework source no longer exists
   - `drift.skipped` — directory-valued entries (skills) that can't be hash-compared
   - `reScaffolded` — whether a re-scaffold was performed
   - `scaffold` — if re-scaffolded: entry count, refreshed skill names, notes

3. **Review the diff.** After re-scaffold, `git diff` shows exactly what
   changed. Seed-once files (state.json, markers-context.json, model.json) are
   preserved and won't appear in the diff unless they were mutated by the
   project before the refresh.

4. **Commit or discard.** Managed files should be committed to pick up the
   framework updates. Seed-once files are project-owned and never overwritten.

## How it differs from `welcome-ai-badger`

| | welcome-ai-badger | den-refresh |
|---|---|---|
| When to use | First time setup | Subsequent updates |
| Detection | Runs detect.py | Reads existing config |
| Config | Agent authors new config.json | Uses existing config.json |
| Questions | Asks for summary, domain, persona routing, plugin scope | No questions |
| Plugin install | Runs plugin install commands | Skips plugin install |
| Skills | Scaffolds from the skill list | Extracts skill names from manifest |

## Rules

- **Never re-detect.** den-refresh uses the project's existing config.json as-is.
  If the config needs updating (new stacks, changed commands), edit it first,
  then run den-refresh.
- **Seed-once files survive.** `state.json`, `markers-context.json`, and
  `model.json` are seed-once and preserved across re-scaffolds.
- **Skills with extensions are refreshed.** The script extracts skill names
  from the manifest, so skills like `task` (with `github`/`hermes` extensions)
  are re-scaffolded and their extensions re-embedded.
- **Managed files are overwritten.** Everything else under `.ai-badger/` that
  the framework originally placed is refreshed to the framework's current
  content. Review the diff before committing.

## Notes

- If the project's config.json is invalid, den-refresh exits with an error.
  Fix the config first (re-run `welcome-ai-badger` steps 2-4 if needed), then
  run den-refresh.
- If `index.json` is missing or stale in the framework checkout, run
  `python3 "$AI_BADGER/scripts/index_build.py"` first.
- den-refresh delegates to the same `scaffold.py` that `welcome-ai-badger`
  uses — the re-scaffold is identical to an initial scaffold, just driven by
  an existing config.