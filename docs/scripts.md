# ai-badger scripts — how to run them and their tests

All scripts are plain Python 3.10+ standalone files (no install step). The framework validates
JSON against `schemas/` with `jsonschema`, and the task-plan model uses `pydantic`. `pyyaml` is
optional and degrades to a printed note. Codex project configuration uses `tomllib` on
Python 3.11+ and the conditional `tomli` dependency on Python 3.10. The task-graph server and
CLI are PEP 723 scripts started with `uv run --script` (see `features/common/stack-mcp.json`), so
consumers need `uv`, which fetches `pydantic` on first launch. Install the requirements:

```bash
python3 -m pip install -r engine/requirements.txt   # jsonschema, pyyaml, pydantic, tomli (+ optional semantica)
```

`$AI_BADGER` below is this repo's root (the directory containing `index.json`, `schemas/`,
`features/`).

## The engine (`engine/`)

The library every bootstrap shim imports, and the anchor of the framework-root predicate
(`engine/badger_lib.py`, ADR-0011). Not run directly.

| Module | What it does |
|--------|--------------|
| `badger_lib.py` | Shared helpers: root discovery, atomic JSON write, sha256, index read. |
| `badger_store.py` | The SQLite runtime store (ADR-0024): three databases behind one module (tracking, user and the audit sink), call-time env roots, open pragmas, lazy COMMIT-then-rename migration of the legacy JSON stores, per-key last-write-wins dual-read. Stdlib only, imports nothing from the engine, and is vendored verbatim into consumer skills. `vendored_copies_report()` finds every copy by globbing `features/**` and `skills/**` on disk and names any that differ; `tests/test_badger_store_vendored.py` runs it. |
| `framework_copies.py` | Every tree on the machine claiming to be ai-badger, the notice naming them, and the one prune allowed: `~/.ai-badger/framework`, on explicit request. Stdlib only and free of `badger_lib` — a SessionStart hook imports it and `badger_lib` requires `jsonschema`. |
| `frontmatter.py` | The one YAML-frontmatter extractor: `split(text)` gives the head, the raw block, the body and one entry per top-level key. Line-oriented, so pyyaml stays optional (ADR-0005); a caller needing typed values parses `raw` itself. |
| `unsafe_literals.py` | Secret/unsafe-literal scanning, shared by feed-badger and the Hermes learned-skills sync. Moves with `badger_lib.py`: one `sys.path` entry serves both. |

## Catalog and release tooling (`tooling/`)

| Script | What it does | Run |
|--------|--------------|-----|
| `index_build.py` | Rebuild `index.json` from the `features/` catalog (source of truth). | `python3 tooling/index_build.py` — add `--check` to fail if stale (CI). |
| `validate.py` | Validate config / catalog JSON against `schemas/`. | `python3 tooling/validate.py --all` or `--kind config <file>`. |
| `version_sync.py` | Propagate `VERSION` into `plugin.json`, `marketplace.json`, `index.json`, and every other shipped `*.json` with a top-level `frameworkVersion` (derived from `release_paths.py`, e.g. `features/common/data/model-groups.json`). | `python3 tooling/version_sync.py` — `--check` fails CI on mismatch. |
| `release_paths.py` | The shipped-surface root list (`skills`, `features`, `engine`, `tooling`, `schemas`, `index.json`, `hooks`, `.claude-plugin`, `BREAKING_VERSIONS`), shared by `release_guard.py` and `version_sync.py` so the two agree on what "shipped" means. | Imported, never run. |
| `test_pi_hook_fires.py` | Phase 0 pi trust-sentinel probe: user-scope extensions fire, project-local blocked (needs a `pi` binary; not CI-wired). | `python3 tooling/test_pi_hook_fires.py`. |
| `changelog_index.py` | Regenerate the release table in `docs/changelog/README.md` from the entry files (issue #160). | `python3 tooling/changelog_index.py` — `--check` fails when the table is stale. |
| `task_plan_schema.py` | Emit/verify `schemas/task-plan.schema.json` from the pydantic `TaskPlan` model (`features/common/skills/task-decomposition/scripts/task_plan_model.py`). The schema description records the boundary: DAG rules (key==id, unknown dependency, cycle) are pydantic-only. | `python3 tooling/task_plan_schema.py` (write) — `--check` fails on drift, printing the first differing JSON pointer; `--root` points at another tree. |
| `sync_plugin_skills.py` | Refresh the published `skills/` copy from `features/`. | `python3 tooling/sync_plugin_skills.py` — `--check` fails on divergence. |
| `generate_model_map.py` | Re-render the model map (`features/common/data/model-groups.json`) from the leaderboard CSV, pi's model store and the OpenRouter catalogue snapshot. The refresh rule lives in the script's docstring: a tier by input price, the newest model of each line, the primary anchor's model first, the rest in ascending price. Rows the leaderboard leaves unpriced are printed by name; rows with no OpenRouter listing are excluded with their reason. | `python3 tooling/generate_model_map.py` — `--check` fails on drift, `--refresh-catalogue` re-fetches the catalogue snapshot. |
| `vendor_archify.py` | Keep the vendored Archify packet honest: an offline `--check` compares the tree against `vendor.json` (MISSING/EXTRA/CHANGED), and `--revendor <archify.zip> --expect-sha256 <sha>` re-vendors a new upstream release with the expected sha supplied on the command line. The origin check is `--revendor`; `--check` proves internal consistency only. | `python3 tooling/vendor_archify.py --check` · maintainer re-vendor (see `features/common/skills/archify/VENDOR.md` for the canonical command): `gh release download v2.16.0 --repo tt-a1i/archify -p archify.zip` then `python3 tooling/vendor_archify.py --revendor archify.zip --expect-sha256 4c59fa6557a2385beaaef8c7219cc414573acc9f0c30a932d5053b0b20689a46 --tag v2.16.0 --commit c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de`. |
| `install_plugins.py` | Resolve per-agent skill install commands from `plugins-instructions.json`. Print-only; `scaffold.py --execute` runs them. | `python3 tooling/install_plugins.py --config <config.json>` |
| `retrieval_eval.py` | Score the MCP BM25 matcher against a fixture file: recall@1/@3, false-fire rate, coverage margin (ADR-0012). Wired into no gate — run by hand. | `python3 tooling/retrieval_eval.py` — `--fixtures`, `--index`, `--threshold`, `--json-out` for a machine-diffable report. |
| `fixture_harvest.py` | Propose eval fixtures from the queries the retrieval hooks actually recorded, so the corpus is not only author-written. Never writes an `expect` field — a human adds that, and that review is the privacy gate. | `python3 tooling/fixture_harvest.py` — queries are hashed unless `--include-queries`. |
| `drift.py` (in `welcome-ai-badger`) | Compare a scaffold against the framework's current content. | See den-refresh. |

## Repo gates (`gates/`)

Run only by CI and the pre-push hook, never by a consumer of the plugin, so they live apart
from the engine and the catalog tooling. They are not shipped surface: a gate-only change does
not require a `VERSION` bump.

Each gate fails with a non-zero exit. The CI step column names the workflow that runs it:
`pylint.yml` (workflow name "Lint and test") has a `gates` job that walks every lane in
`.lefthook/pre-push/verify.sh`, and the same lanes run in the pre-push hook (`lefthook.yml`).
`consumer_journey.py` is the exception: `consumer-journey.yml` runs it on its own, and a local
push skips it.

| Gate | What it does | CI step | Run |
|--------|--------------|---------|-----|
| `release_guard.py` | Fail if the shipped surface (`tooling/release_paths.py`) changed since the last release tag without a `VERSION` bump. | Lint and test, `gates` job: `verify.sh release` | `python3 gates/release_guard.py` (needs `fetch-depth: 0` in CI). |
| `docs_guard.py` | Fail if a relative link or a backticked repo path in the docs no longer resolves, or a changelog entry is missing from its index. | Lint and test, `gates` job: `verify.sh docs` | `python3 gates/docs_guard.py`; exempt a path in `.docs-guard-ignore`. |
| `deps_guard.py` | Fail if any `*.py` under `engine/`, `tooling/`, `features/` or `gates/` imports a third-party module that `engine/requirements.txt` does not declare. Imports inside functions and `try:` blocks count. | Lint and test, `gates` job: `verify.sh deps` | `python3 gates/deps_guard.py` |
| `shipped_paths_guard.py` | Fail if a machine-specific absolute path (`/Users/…`, `/home/…`, `C:\Users\…`) appears in a tracked file outside `docs/`, root `*.md` and `tests/`. The `docs/` exemption stops at generated pages: a `.html`/`.htm` file under `docs/` is scanned, because a generated page is not prose. | Lint and test, `gates` job: `verify.sh paths` | `python3 gates/shipped_paths_guard.py`; exempt a path in `.shipped-paths-guard-ignore`. |
| `scaffold_freshness_guard.py` | Fail if re-scaffolding this repo against itself, in a throwaway copy, would change anything but a version stamp, such as a `features/**` edit that never reached `.ai-badger/`. Each finding is read as `stale` (the source moved ahead) or `hand-edited` (the mirror was changed here). | Lint and test, `gates` job: `verify.sh scaffold` | `python3 gates/scaffold_freshness_guard.py` |
| `consumer_journey.py` | Install ai-badger the way a consumer does, from a plugin-cache-shaped copy with no `.git`, into a real `git init` project, under a scratch `$HOME`, then work in the result with an edit the guard must refuse, one it must allow, two re-scaffolds, a teardown, and a before/after `$HOME` diff that counts directories and symlinks, not just regular files. | Consumer journey workflow, on every push | `python3 gates/consumer_journey.py` (`--root` to install from another tree, `--keep` to inspect the scratch dir). |
| `tdd_guard.py` | Fail if `.py`/`.mjs` under `engine/`, `tooling/`, `features/` or `gates/` (plus shipped pi `.ts` under `features/pi/adjustments/`) changed since `git merge-base --base HEAD` and no test (`tests/**` or `features/pi/tests/*.test.ts`) changed with it. It uses `--diff-filter=AMR`, so a deleted test does not count. | Lint and test, `gates` job: `verify.sh tdd` (skipped on a push to main) | `python3 gates/tdd_guard.py --base origin/main` |
| `skills_lint.py` | Fail if a catalog `SKILL.md` breaks one of the thirteen conventions (name grammar, description shape and size, body budget, conditioned `references/` mentions, a gotchas section, required and non-duplicated frontmatter keys). `tooling/validate.py --all` calls it too, so CI reports it without running it directly. | Lint and test, `gates` job: `verify.sh validate`, through `validate.py --all` | `python3 gates/skills_lint.py` |
| `workflow_lint.py` | Fail if a `uses:` in `.github/workflows/` is not pinned to a 40-character commit SHA (a `./` local action is exempt), or if a workflow declares no `permissions:` block at the top and one of its jobs declares none either. Enforces `features/github/invariants/pin-actions-to-sha.md`, which shipped violated nine times over before anything checked it. | Lint and test, `gates` job: `verify.sh workflows` | `python3 gates/workflow_lint.py` |
| `gate_report.py` | Not a gate: the `Problem(path, line, message)` finding shape and the failure report shared by `deps_guard`, `docs_guard` and `shipped_paths_guard`. The other three report something else and keep their own output. | none (library) | Imported, never run. |

`consumer_journey.py` refuses nothing of its own accord: it installs the plugin the way a stranger
would, scaffolds a throwaway `git init` project, works in it, re-scaffolds, tears it down, and
diffs `$HOME` for anything left behind.

What the gates do not cover: they check the artefacts, not the reasoning. A confidently wrong
claim in a PR body passes every one of them and still needs a reviewer.

## CI helpers (`.github/scripts/`)

Called only by a workflow in `.github/workflows/`, never by a gate, the pre-push hook or a
consumer of the plugin. Not shipped surface.

| Script | What it does | Run |
|--------|--------------|-----|
| `conflicting_pr_report.py` | Report the open pull requests that conflict with their base — GitHub dispatches no `pull_request` workflow run for those, so a required check whose only trigger is `pull_request` never reports and the PR reads as slow rather than stuck. Filtering only; `stuck-pr-watch.yml` posts the notice. | `gh api graphql ... \| python3 .github/scripts/conflicting_pr_report.py`; `--print-comment` prints the notice body. |

The workflows that call them live in `.github/workflows/`: `codeql.yml` (CodeQL),
`consumer-journey.yml` (Consumer journey), `labeler.yml` (Labeler), `pylint.yml` (Lint and test),
`release-tag.yml` (Tag the release), `secret-scan.yml` (Secret scan), `stuck-pr-watch.yml`
(Stuck PR watch) and `task-graph-launch.yml` (task-graph launch).

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
- `shared_scope.py` (`welcome-ai-badger/scripts/`): `collect --target COLLECTION --repo CHILD`
  (repeat `--repo` for every member, optionally supply `--config PARENT_CONFIG`) renders the
  parent stack union and enrolls the selected children. `sync --target CHILD --source
  COLLECTION/.ai-badger` refreshes one child with its local stacks. `prune --target
  COLLECTION --repo CHILD` removes one enrolled member: it keeps its identity, keeps private
  copies of the files it shared, and rejoins the ordinary scaffold flow (the last member
  cannot be pruned). All three accept `--root`, and `--register` opts into registering a
  newly minted child id with ai-raccoon (nothing is registered without it).
  Edit child `.ai-badger/shared-scope.json` overrides for persistent local settings.
- `shared_scope.py` from the parent side: `discover --target COLLECTION` reports the direct
  child repositories that carry a `.git` entry, one `dir:stacks` line each, plus the union of
  their stacks; it writes nothing. `init --target COLLECTION` does the work: it discovers the
  same children, decides every identity and every member's own settings before it writes
  anything, scaffolds the parent with the union of the children's stacks, and enrolls every
  child — a fresh one is scaffolded, an already-scaffolded one is converted and keeps its own
  project id. `--dry-run` reports the members, the union and the identity decisions and writes
  nothing; `--config PARENT_CONFIG` authors the parent's own defaults. The `dir:stacks` index
  is kept in the parent's `.ai-badger/shared-scope.json` as `memberStacks`.

- `scaffold.py` — materializes `.ai-badger/`, records provenance in `manifest.json`, preserves
  existing hand-authored discovery files by default, and never copies test files into a target.
  Flags: `--skills` (comma list; empty means the set already scaffolded), `--overwrite-agent-files`,
  `--reset-seed-files` (reseed SEED-ONCE files, discarding project edits), `--no-install` and
  `--execute` (run skill install commands instead of printing them).
- `den-refresh` (`features/common/skills/den-refresh/scripts/refresh.py`): re-scaffolds a project
  from its own config when the framework moved. `--force` re-scaffolds without a drift signal,
  `--prune-cache` deletes `~/.ai-badger/framework`, `--prune-namespaces` deletes orphaned
  `~/.hermes/skills/<project>/` trees.

## feed-badger (`features/common/skills/feed-badger/scripts/`)

Harvests generalizable local improvements back into the framework as draft PRs.

```bash
python3 "$AI_BADGER/features/common/skills/feed-badger/scripts/detect_additions.py" --target . --root "$AI_BADGER"
python3 "$AI_BADGER/features/common/skills/feed-badger/scripts/open_pr.py" --dry-run   # drop --dry-run to push + open a draft PR
```

## task / prompt-markers skill scripts

These run inside a scaffolded project as hooks and CLIs (`task_tracker.py`, `resume_cron.py`,
`statusline_capture.py`, hook entry points). They are documented by
their owning skills.
(`auto-wm` scripts live at `features/claude/skills/auto-wm/` — Claude Code-specific.)

`statusline_capture.py` captures session state and then, **only if `CLAUDE_USER_STATUSLINE`
points at an executable**, runs it with the same stdin and prints its output — so your own
statusline keeps working. Unset (the default), that step is skipped. The `task` skill declares
`platforms: [linux, macos]`: `fcntl` and `crontab` make it POSIX-only.

The task-graph plan server runs through `uv run --script`; its CLI twin is
`features/common/skills/task-decomposition/scripts/task_graph_cli.py` (`<tool> --json`), used
where no `.mcp.json` is loaded, such as worktree sessions.

A tool in the catalog ships `scripts/install.py` and `scripts/check.py`; a tool that declares a
`guard` script also ships that guard, which the harness's marked hook runs in place of the
tool's own. The catalog itself ships no tool.

`call-behaviorist` (`features/common/skills/call-behaviorist/scripts/behaviorist.py`) switches
on ai-badger's own audit log — `on [DURATION] [--project]`, `off`, `status`, `tail`, `analyze`,
`clear`. **Off by default**: nothing is written and no directory is created until you enable it,
and every enablement expires (4h default, 24h cap). State and records live in the audit DB
`~/.ai-badger/debug/audit.db` (`hook_state` KV + `hook_audit` table), relocatable whole via
`AI_BADGER_DEBUG_DIR` — which is what this repo's own `tests/conftest.py` sets, at import time,
so a test run cannot append to a real developer's log. `AI_BADGER_DEBUG=1` forces logging on
regardless of stored state. A record's payload keeps the single-letter keys (`t` timestamp, `c`
component, `e` event, `v` the version of the copy of the code that ran, `p` project, `n` project
name, `s` session) — a budget, not cosmetics, inherited from the JSONL append that survives as
the fallback sink and import seam. Hooks reach the logger through a
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

Lint (CI runs this against the floor, Python 3.10, tests excluded — they keep their own conventions).
The file selection below is the *only* one: CI, the lefthook `pylint` lane and the `lint` command
in [`CLAUDE.md`](../CLAUDE.md) all share it, so a green local run means a green build. Naming
directories instead would silently skip the `.ai-badger/` and `skills/` mirror trees (issue #183).

```bash
python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')
python3 tooling/index_build.py --check && python3 tooling/validate.py --all
```
