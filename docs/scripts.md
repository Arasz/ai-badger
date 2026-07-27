# ai-badger scripts — how to run them and their tests

All scripts are plain Python 3.8+ standalone files (no install step). The framework validates
JSON against `schemas/` with `jsonschema`, so install that once:

```bash
python3 -m pip install -r scripts/requirements.txt   # jsonschema
```

`$AI_BADGER` below is this repo's root (the directory containing `index.json`, `schemas/`,
`features/`).

## Core scripts (`scripts/`)

| Script | What it does | Run |
|--------|--------------|-----|
| `index_build.py` | Rebuild `index.json` from the `features/` catalog (source of truth). | `python3 scripts/index_build.py` — add `--check` to fail if stale (CI). |
| `validate.py` | Validate config / catalog JSON against `schemas/`. | `python3 scripts/validate.py --all` or `--kind config <file>`. |
| `badger_lib.py` | Shared helpers (root discovery, atomic JSON write, sha256, index read). Imported by the other scripts; not run directly. | — |
| `version_sync.py` | Propagate `VERSION` into `plugin.json`, `marketplace.json`, `index.json`. | `python3 scripts/version_sync.py` — `--check` fails CI on mismatch. |
| `release_guard.py` | Fail if the shipped surface changed since the last release tag without a `VERSION` bump. | `python3 scripts/release_guard.py` (needs `fetch-depth: 0` in CI). |
| `docs_guard.py` | Fail if a relative link or a backticked repo path in the docs no longer resolves, or a changelog entry is missing from its index. | `python3 scripts/docs_guard.py`; exempt a path in `.docs-guard-ignore`. |
| `sync_plugin_skills.py` | Refresh the published `.claude/skills/` copy from `features/`. | `python3 scripts/sync_plugin_skills.py` — `--check` fails on divergence. |
| `install_plugins.py` | Resolve per-agent skill install commands from `plugins-instructions.json`. Print-only; `scaffold.py --execute` runs them. | `python3 scripts/install_plugins.py --config <config.json>` |
| `drift.py` (in `welcome-ai-badger`) | Compare a scaffold against the framework's current content. | See den-refresh. |

## welcome-ai-badger (`features/common/skills/welcome-ai-badger/scripts/`)

Bootstraps a target repo. See that skill's `SKILL.md` for the full flow.

```bash
# 1. propose a config for the target repo
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/detect.py" --target . --root "$AI_BADGER" > /tmp/config.json
# 2. (agent authors/refines config.json, then) validate it
python3 "$AI_BADGER/scripts/validate.py" --kind config /tmp/config.json
# 3. scaffold .ai-badger/ into the target
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/scaffold.py" \
    --config /tmp/config.json --target . --root "$AI_BADGER" \
    --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
#    --overwrite-agent-files  # opt-in: replace hand-authored CLAUDE.md/instructions (default preserves them)
```

- `detect.py` — data-driven stack detection from each stack's `detectionSignals` (ignores vendored
  and agent-tooling dirs like `node_modules`, `.venv`, `.claude`).
- `scaffold.py` — materializes `.ai-badger/`, records provenance in `manifest.json`, preserves
  existing hand-authored discovery files by default, and never copies test files into a target.

## feed-badger (`features/common/skills/feed-badger/scripts/`)

Harvests generalizable local improvements back into the framework as draft PRs.

```bash
python3 "$AI_BADGER/features/common/skills/feed-badger/scripts/detect_additions.py" --target . --root "$AI_BADGER"
python3 "$AI_BADGER/features/common/skills/feed-badger/scripts/open_pr.py" --dry-run   # drop --dry-run to push + open a draft PR
```

## task / prompt-markers skill scripts

These run inside a scaffolded project as hooks and CLIs (`task_tracker.py`, `resume_cron.py`,
`poll_limit.py`, `statusline_capture.py`, hook entry points). They are documented by
their owning skills; `poll_limit.py --once` and `--interval-seconds` support manual/testing runs.
(`auto-wm` scripts live at `features/claude/skills/auto-wm/` — Claude Code-specific.)

`statusline_capture.py` captures session state and then, **only if `CLAUDE_USER_STATUSLINE`
points at an executable**, runs it with the same stdin and prints its output — so your own
statusline keeps working. Unset (the default), that step is skipped. The `task` skill declares
`platforms: [linux, macos]`: `fcntl` and `crontab` make it POSIX-only.

## Running the test suite

Framework tests live **only** in the top-level `tests/` directory. They are never part of any
scaffolded feature (`scaffold.py` excludes `test_*.py`/`tests/` from every copy), so a target repo
onboarded with ai-badger never receives them.

```bash
python3 -m pip install pytest jsonschema
python3 -m pytest -q                 # runs tests/ (configured via pyproject testpaths)
python3 -m pytest tests/test_scaffold_no_test_leak.py -q   # a single test
```

Lint (CI runs this on Python 3.8/3.9/3.10, tests excluded — they keep their own conventions):

```bash
python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')
python3 scripts/index_build.py --check && python3 scripts/validate.py --all
```
