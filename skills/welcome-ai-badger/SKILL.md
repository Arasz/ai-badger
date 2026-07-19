---
name: welcome-ai-badger
description: >-
  Bootstrap a repository with the ai-badger framework. Use when a user wants to set up a new
  or existing project with ai-badger — "welcome-ai-badger", "set up ai-badger here", "scaffold
  this repo with the framework", "onboard this project". Detects the repo's stacks and coding
  agents, authors a validated project config, and materializes a tailored .ai-badger/ scaffold
  (CLAUDE.md, personas, instructions, invariants, skills) plus agent-discovery copies.
---

# welcome-ai-badger

Scaffolds a target repository with a project-tailored selection of ai-badger framework
features. **The scripts do all mechanical work; you (the agent) only author `config.json` — the
one creative artifact — and answer/ask a few questions.**

## Responsibility split (do not blur it)

- **Scripts (mechanical, deterministic):** `detect.py` proposes a config; `validate.py` checks
  it; `scaffold.py` builds `.ai-badger/`, assembles `CLAUDE.md`, copies agent files, records
  provenance in `manifest.json`.
- **You (creative only):** turn the proposed config into a good `config.json` — write
  `project.summary`/`domain`, choose/confirm stacks, define `personaRouting`, resolve any
  detection ambiguity by asking the user. Then hand it back to `validate.py`.

## Prerequisites

Framework scripts need `jsonschema`:
```bash
python3 -m pip install -r "$AI_BADGER/scripts/requirements.txt"
```
`$AI_BADGER` = this framework's root (the dir containing `index.json`, `schemas/`, `common/`).
If `index.json` is missing or stale, run `python3 "$AI_BADGER/scripts/index_build.py"` first.

## Flow

1. **Detect.** From the target repo root:
   ```bash
   python3 "$AI_BADGER/skills/welcome-ai-badger/scripts/detect.py" --target . --root "$AI_BADGER" > /tmp/proposed-config.json
   ```
   This proposes stacks (with `requires` expanded), detected coding agents
   (claude/copilot/junie — only those with traces in the repo or user scope), source control,
   and build/test/lint/run commands.

2. **Author `config.json`.** Read the proposal. Fill in `project.summary` and `project.domain`
   (the domain is the *business* purpose, never a stack). Confirm the stack list against
   `index.json` (`stacks` must be known stacks). Add `personaRouting` mapping kinds of work to
   the personas that will be scaffolded (base roles: `architect`, `test-engineer`,
   `code-reviewer`, plus each selected stack's engineer persona). **Ask the user only when a
   choice is genuinely ambiguous** (e.g. detection found both a frontend and a backend and you
   can't tell the project's focus).

3. **Ask plugin scope.** Ask the user: **default** (honor each plugin entry's declared scope) or
   **local-only** (force every plugin install to project scope). Set `pluginScope` accordingly.
   (There is deliberately no "user-only" option.)

4. **Validate.**
   ```bash
   python3 "$AI_BADGER/scripts/validate.py" --kind config /tmp/proposed-config.json
   ```
   Fix any reported error in the config and re-run until it passes.

5. **Scaffold.**
   ```bash
   python3 "$AI_BADGER/skills/welcome-ai-badger/scripts/scaffold.py" \
     --config /tmp/proposed-config.json --target . --root "$AI_BADGER" \
     --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
   ```
   Produces `.ai-badger/` (config.json, manifest.json, CLAUDE.md, agents/, instructions/,
   invariants/, skills/, agent-instructions/, state.json) and agent-discovery copies for each
   detected agent (`CLAUDE.md`, `.github/copilot-instructions.md`, `.junie/AGENTS.md`). Note the
   printed plugin-setup commands and run them per the chosen scope (or hand them to the user).
   **Existing hand-authored discovery files are preserved by default** — see the preserve note
   below; on a mature repo the scaffold will report which files it left untouched.

6. **Verify & report.** Confirm the scaffold matches the stacks (no leakage from unselected
   stacks). Summarize what was written, the plugin commands, and any notes the script emitted.

## Notes

- **Idempotent:** re-running `scaffold.py` refreshes managed files and the manifest. Safe to
  re-run after editing `config.json`.
- **Copy-vs-reference:** essential agent files (CLAUDE.md, copilot-instructions, junie AGENTS.md)
  are *copied* to their conventional locations with a header pointing at `.ai-badger/` as the
  source of truth, because agent CLIs discover them by convention. See
  `docs/proxy-files-spike.md` for the planned thin-proxy alternative.
- **Preserve-by-default (mature repos):** a discovery file that already exists and does *not* carry
  the ai-badger managed header is treated as hand-authored and left untouched — its `.ai-badger/`
  source copy is still written, and the scaffold emits a `preserved …` note. Framework-written
  copies (which carry the header) and brand-new files are written/refreshed normally, so
  idempotent re-scaffolding still works. Pass `--overwrite-agent-files` to force the old
  copy-over behavior on every discovery file.
- **Extensions:** config-gated skill extensions (e.g. the GitHub PR/issue extension of `task`)
  are embedded automatically iff `config.json` supplies their required data.

## Upgrading a scaffolded project

A project's `.ai-badger/` is a snapshot, not a live link. It only changes when re-scaffolded.

1. `claude plugin marketplace update ai-badger`
2. `claude plugin update ai-badger@ai-badger` — then restart, as the CLI instructs.
3. Check what would change:
   `python3 <plugin>/skills/welcome-ai-badger/scripts/drift.py --target <project>`
4. Re-scaffold, then **read the diff before committing**.

Re-scaffolding is safe for project-owned data: `state.json` and
`skills/prompt-markers/markers-context.json` are seed-once and preserved, and the scaffolder
prints a `preserved seed-once ...` line for each. Managed files are refreshed by design, so
the diff is where you confirm nothing you meant to keep was framework-owned. Skill directories
are reported as `skipped` rather than checked, since their recorded hash covers the scaffolded
copy, not the framework's source tree.

A manifest from before 0.2.0 lacks the provenance keys and fails validation with an explicit
hint. There is no migration by design — re-scaffolding is the upgrade.
