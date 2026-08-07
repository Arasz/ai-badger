# ai-badger scripts — how to run them and their tests

All scripts are plain Python 3.8+ standalone files (no install step). The framework validates
JSON against `schemas/` with `jsonschema`, so install that once:

```bash
python3 -m pip install -r engine/requirements.txt   # jsonschema
```

`$AI_BADGER` below is this repo's root (the directory containing `index.json`, `schemas/`,
`features/`).

## The engine (`engine/`)

The library every bootstrap shim imports, and the anchor of the framework-root predicate
(`engine/badger_lib.py`, ADR-0011). Not run directly.

| Module | What it does |
|--------|--------------|
| `badger_lib.py` | Shared helpers: root discovery, atomic JSON write, sha256, index read. |
| `framework_copies.py` | Every tree on the machine claiming to be ai-badger, the notice naming them, and the one prune allowed: `~/.ai-badger/framework`, on explicit request. Stdlib only and free of `badger_lib` — a SessionStart hook imports it and `badger_lib` requires `jsonschema`. |
| `frontmatter.py` | The one YAML-frontmatter extractor: `split(text)` gives the head, the raw block, the body and one entry per top-level key. Line-oriented, so pyyaml stays optional (ADR-0005); a caller needing typed values parses `raw` itself. |
| `unsafe_literals.py` | Secret/unsafe-literal scanning, shared by feed-badger and the Hermes learned-skills sync. Moves with `badger_lib.py`: one `sys.path` entry serves both. |

## Catalog and release tooling (`tooling/`)

| Script | What it does | Run |
|--------|--------------|-----|
| `index_build.py` | Rebuild `index.json` from the `features/` catalog (source of truth). | `python3 tooling/index_build.py` — add `--check` to fail if stale (CI). |
| `validate.py` | Validate config / catalog JSON against `schemas/`. | `python3 tooling/validate.py --all` or `--kind config <file>`. |
| `version_sync.py` | Propagate `VERSION` into `plugin.json`, `marketplace.json`, `index.json`. | `python3 tooling/version_sync.py` — `--check` fails CI on mismatch. |
| `changelog_index.py` | Regenerate the release table in `docs/changelog/README.md` from the entry files (issue #160). | `python3 tooling/changelog_index.py` — `--check` fails when the table is stale. |
| `sync_plugin_skills.py` | Refresh the published `skills/` copy from `features/`. | `python3 tooling/sync_plugin_skills.py` — `--check` fails on divergence. |
| `install_plugins.py` | Resolve per-agent skill install commands from `plugins-instructions.json`. Print-only; `scaffold.py --execute` runs them. | `python3 tooling/install_plugins.py --config <config.json>` |
| `retrieval_eval.py` | Score the MCP BM25 matcher against a fixture file: recall@1/@3, false-fire rate, coverage margin (ADR-0012). Wired into no gate — run by hand. | `python3 tooling/retrieval_eval.py` — `--fixtures`, `--index`, `--threshold`, `--json-out` for a machine-diffable report. |
| `fixture_harvest.py` | Propose eval fixtures from the queries the retrieval hooks actually recorded, so the corpus is not only author-written. Never writes an `expect` field — a human adds that, and that review is the privacy gate. | `python3 tooling/fixture_harvest.py` — queries are hashed unless `--include-queries`. |
| `drift.py` (in `welcome-ai-badger`) | Compare a scaffold against the framework's current content. | See den-refresh. |

## Repo gates (`gates/`)

Run only by CI and the pre-push hook, never by a consumer of the plugin, so they live apart
from the engine and the catalog tooling. They are not shipped surface: a gate-only change does
not require a `VERSION` bump.

| Gate | What it does | Run |
|--------|--------------|-----|
| `release_guard.py` | Fail if the shipped surface changed since the last release tag without a `VERSION` bump. | `python3 gates/release_guard.py` (needs `fetch-depth: 0` in CI). |
| `docs_guard.py` | Fail if a relative link or a backticked repo path in the docs no longer resolves, or a changelog entry is missing from its index. | `python3 gates/docs_guard.py`; exempt a path in `.docs-guard-ignore`. |
| `deps_guard.py` | Fail if any `*.py` under `engine/`, `tooling/`, `features/` or `gates/` imports a third-party module that `engine/requirements.txt` does not declare. Imports inside functions and `try:` blocks count. | `python3 gates/deps_guard.py` |
| `shipped_paths_guard.py` | Fail if a machine-specific absolute path (`/Users/…`, `/home/…`, `C:\Users\…`) appears in a tracked file outside `docs/`, root `*.md` and `tests/`. | `python3 gates/shipped_paths_guard.py`; exempt a path in `.shipped-paths-guard-ignore`. |
| `scaffold_freshness_guard.py` | Fail if re-scaffolding this repo against itself, in a throwaway copy, would change anything but a version stamp — a `features/**` edit that never reached `.ai-badger/`. Each finding is read as `stale` (the source moved ahead) or `hand-edited` (the mirror was changed here). | `python3 gates/scaffold_freshness_guard.py` |
| `tdd_guard.py` | Fail if `.py`/`.mjs` under `engine/`, `tooling/`, `features/` or `gates/` changed since `--base` and nothing under `tests/` did. | `python3 gates/tdd_guard.py --base origin/main` |
| `skills_lint.py` | Fail if a catalog `SKILL.md` breaks one of the eleven conventions (name grammar, description shape and size, body budget, conditioned `references/` mentions, a gotchas section, required and non-duplicated frontmatter keys). `tooling/validate.py --all` calls it too, so CI reports it without running it directly. | `python3 gates/skills_lint.py` |
| `gate_report.py` | Not a gate: the `Problem(path, line, message)` finding shape and the failure report shared by `deps_guard`, `docs_guard` and `shipped_paths_guard`. The other three report something else and keep their own output. | Imported, never run. |

## welcome-ai-badger (`features/common/skills/welcome-ai-badger/scripts/`)

Bootstraps a target repo. See that skill's `SKILL.md` for the full flow.

```bash
# 1. propose a config for the target repo
python3 "$AI_BADGER/features/common/skills/welcome-ai-badger/scripts/detect.py" --target . --root "$AI_BADGER" > /tmp/config.json
# 2. (agent authors/refines config.json, then) validate it
python3 "$AI_BADGER/tooling/validate.py" --kind config /tmp/config.json
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

`call-behaviorist` (`features/common/skills/call-behaviorist/scripts/behaviorist.py`) switches
on ai-badger's own audit log — `on [DURATION] [--project]`, `off`, `status`, `tail`, `analyze`,
`clear`. **Off by default**: nothing is written and no directory is created until you enable it,
and every enablement expires (4h default, 24h cap). State and records live at
`~/.ai-badger/debug/{state.json,audit.jsonl}`, relocatable together via `AI_BADGER_DEBUG_DIR` —
which is what this repo's own `tests/conftest.py` sets, at import time, so a test run cannot
append to a real developer's log. `AI_BADGER_DEBUG=1` forces logging on regardless of stored
state. A record is one JSON object per line with single-letter keys (`t` timestamp, `c`
component, `e` event, `v` the version of the copy of the code that ran, `p` project, `n` project
name, `s` session): the keys are a budget, not cosmetics, because a record must stay under
`PIPE_BUF` for concurrent `O_APPEND` writes to be atomic. Hooks reach the logger through a
`debug_log.py` vendored beside each hook group — they import nothing from the framework — and a
logging failure never breaks the hook it observes.

## Running the test suite

Framework tests live **only** in the top-level `tests/` directory. They are never part of any
scaffolded feature (`scaffold.py` excludes `test_*.py`/`tests/` from every copy), so a target repo
onboarded with ai-badger never receives them.

```bash
python3 -m pip install pytest jsonschema
python3 -m pytest -q                 # runs tests/ (configured via pyproject testpaths)
python3 -m pytest tests/test_scaffold_no_test_leak.py -q   # a single test
```

Lint (CI runs this on Python 3.8/3.9/3.10, tests excluded — they keep their own conventions).
The file selection below is the *only* one: CI, the lefthook `pylint` lane and the `lint` command
in [`CLAUDE.md`](../CLAUDE.md) all share it, so a green local run means a green build. Naming
directories instead would silently skip the `.ai-badger/` and `skills/` mirror trees (issue #183).

```bash
python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')
python3 tooling/index_build.py --check && python3 tooling/validate.py --all
```
