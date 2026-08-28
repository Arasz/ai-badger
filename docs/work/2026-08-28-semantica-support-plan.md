# Semantica MCP support fixes — implementation plan

**Date:** 2026-08-28
**Task:** continue-semantica-support-fixes
**Evidence:** `docs/work/2026-08-28-semantica-support-research.md` (MEASURED / READ / HYPOTHESIS labelled)
**Target version:** 0.138.0 (minor — see rationale at the end)
> Shipped as **0.139.0**: PR #436 took 0.138.0 while this branch was in flight.
> The minor-versus-patch reasoning below is unaffected.

## Summary

Semantica 0.6.6 breaks `export_graph` in every format, and its RDF branch writes a
progress bar to stdout, corrupting the MCP transport. ai-badger cannot fix upstream,
so this change does the three things it can: stop shipping an install command that
reproduces a gensim build failure on Python 3.14; declare
`SEMANTICA_DISABLE_PROGRESS=1` on the semantica MCP entry so a broken export returns
a handleable error instead of killing the session; and stop every document, probe and
per-session nudge from claiming a capability that does not exist.

## Simpler-shape check

The smallest change closing the measured defects is three string edits plus one JSON
key (P1, P4, P8). Rejected as over-engineering: a stdout-pollution probe in `check.py`
(it would have to run the polluting branch to detect pollution, and the json probe was
measured clean); a second RDF probe; rewording `tools.json` (it is the BM25 retrieval
corpus, not a health report — editing it churns the retrieval eval for no gain);
gating the nudge on a live probe (a subprocess per prompt to decide one line).

Accepted beyond the literal five issues, each because leaving it makes one of the five
a fiction: P3 (`install.py` selects 3.14 itself, so pinning only the documented command
fixes the sentence and not the failure); P2 (a committed twin of the block P1 edits);
P7 (the task asked to confirm graceful degradation — it cannot be confirmed).

## Plan points

| # | Title | Files | Gate |
|---|---|---|---|
| P1 | Pin the interpreter in the semantica install commands | `features/common/mcp/semantica/meta.json`, `tests/test_mcp_semantica_catalog.py` | `pytest tests/test_mcp_semantica_catalog.py`; `tooling/validate.py --all` |
| P2 | Retire the prerequisite-conversion twin | delete `tooling/convert_mcp_prerequisites.py`; `tests/test_engine_tooling_layout.py`; `docs/scripts.md` | `pytest tests/test_engine_tooling_layout.py`; `gates/docs_guard.py` |
| P3 | `install.py` stops choosing an interpreter above the gensim wheel ceiling | `features/common/mcp/semantica/scripts/install.py`, `tests/test_semantica_mcp_scripts.py` | `pytest tests/test_semantica_mcp_scripts.py` |
| P4 | Declare `SEMANTICA_DISABLE_PROGRESS` on the semantica MCP entry | `features/common/stack-mcp.json`, `tests/test_mcp_semantica_catalog.py` | `pytest tests/test_mcp_semantica_catalog.py tests/test_stack_mcp_servers.py`; `gates/scaffold_freshness_guard.py` |
| P5 | Delete the wrapper; make `check.py` report 0.6.6 honestly | delete `features/common/mcp/semantica/scripts/semantica_mcp_wrapper.py`; `check.py`; `engine/requirements.txt`; `tests/test_semantica_mcp_scripts.py` | `pytest tests/test_semantica_mcp_scripts.py`; `gates/deps_guard.py` |
| P6 | The session nudge stops instructing a call that always fails | `features/common/retrieval/context_enrichment.py`; `features/common/skills/semantica-knowledge-graph/scripts/export_semantica_graph.py`; both nudge tests | `pytest tests/test_context_enrichment*.py`; `tooling/sync_plugin_skills.py --check`; scaffold guard |
| P7 | The autosave saves only something that looks like a graph | `.../export_semantica_graph.py`, `tests/test_semantica_export_hook.py` | `pytest tests/test_semantica_export_hook.py tests/test_semantica_export_autosave_hook.py` |
| P8 | Correct the docs that claim RDF works | `features/common/skills/semantica-knowledge-graph/SKILL.md`; `docs/skills.md`; `docs/changelog/0.137.1-*.md` | `gates/docs_guard.py`; `sync_plugin_skills.py --check` — **no gate distinguishes a true claim from a false one; the check is review** |
| P9 | Version bump, changelog, regenerate derived trees | `VERSION`, new changelog, `.claude-plugin/*`, `index.json`, `.github/mcp.json`, `skills/**`, `.ai-badger/**` | full `pytest -q`, pylint, `index_build --check`, all pre-push lanes |

### Failing-first tests (the red-before-green contract)

- **P1** `test_semantica_install_commands_pin_the_interpreter` — asserts `--python 3.13`
  in `global.install/uv/command` and `local.uv`. Red today: the file ships the bare command.
- **P3** `test_the_venv_is_built_with_the_interpreter_that_was_chosen` — patch
  `subprocess.run`, call `ensure_venv(tmp, "/fake/python3.13")`, assert it appears in an
  argv. Red today: `ensure_venv` prints `py_exe` then builds with `venv.EnvBuilder()`,
  i.e. the running interpreter. Plus
  `test_an_interpreter_above_the_wheel_ceiling_is_rejected` — red today because
  `find_suitable_python` returns `sys.executable` before consulting any candidate.
- **P4** `test_semantica_declares_the_progress_kill_switch` — red today: no `env` key.
  Do **not** re-test the plumbing; `tests/test_stack_mcp_servers.py:789` already proves
  `env` reaches every destination.
- **P5** `test_no_fallback_rescues_a_broken_native_probe` — patches **`subprocess.run`**,
  not the private helper being deleted, so the test survives the deletion. Red today
  because the wrapper fallback returns True. Also `test_the_wrapper_is_gone` and
  `test_only_two_runtime_dependencies_are_declared`.
- **P6** flip the two `NUDGE_LINE` assertions to `"export_graph" not in` — red today.
  Plus `test_both_nudge_copies_agree`, which **passes today**, so per
  *prove-the-check-fails* it must be watched red by perturbing one copy, then reverted.
- **P7** `test_a_content_envelope_error_writes_nothing` — red today: `extract_graph_json`
  falls through to `return result` for a bare `{"content":[{"type":"text",...}]}`
  payload and writes the error envelope to `.semantica/` as a graph.

### Rewritten test — name it in the PR

`test_wrapper_fallback_saves_export_when_native_broken`
(`tests/test_semantica_mcp_scripts.py:156`) is deleted and replaced by P5's first test.
It asserted exactly the behaviour being removed, so this is where a regression hides.

## Parallelism

- **Lane A** P1 → P2 → P4 (P2 must follow P1; P1 and P4 share `test_mcp_semantica_catalog.py`)
- **Lane B** P3 → P5 (share `test_semantica_mcp_scripts.py`)
- **Lane C** P6 → P7 (share `export_semantica_graph.py`)
- **Lane D** P8, after P4
- **P9 alone, last** — it regenerates what A/B/C wrote

The architect's own recommendation: the file overlap is heavy and the change set small,
so **sequential A→B→C→D→P9 on one branch beats four worktrees**. Lanes are recorded for
the case where the work is split anyway.

## Version and changelog

**0.138.0 — minor, not patch.** ADR-0001 decision 3 defines `0.MINOR` as anything
changing what scaffolding does to a consumer repo. Three things clear that bar: P4 adds
an `env` block to every scaffolded `.mcp.json` and `.github/mcp.json` (output shape);
P6 changes what the `UserPromptSubmit` hook injects (hook contract); P2 and P5 delete
shipped files under `tooling/` and `features/` (removed features, both in
`SHIPPED_PATHS`). File:
`docs/changelog/0.138.0-semantica-0-6-6-honesty-and-transport-fix.md`.

## Known limits, stated rather than papered over

- **P4's gate is structural only.** The test locks the declaration; it cannot prove the
  transport stays clean. That needs semantica installed plus a live stdio handshake,
  which CI does not have. The behavioural proof is the recorded measurement (research
  record A1), not something CI re-runs. The changelog must say so.
- **P3's ceiling is inference, not measurement.** F1 measured that gensim 4.4.0 has no
  cp314 wheel and that a source build fails; that `install.py`'s pip path hits the same
  wall was not run. Solid over one package, but this is the point to defer if trimming.
- **P7's envelope shape is inferred** from the MCP result contract, not measured against
  a live `PostToolUse` payload. The fall-through is read directly from source and is not
  in doubt; what is unverified is whether Claude Code delivers that shape. The
  positive-constraint fix (`return only if "nodes" in payload`) is correct either way,
  which is the reason to prefer it over guessing.
- **P8 has no real gate.** `docs_guard` checks links, `sync_plugin_skills` checks copy
  equality; neither can tell a true claim from a false one. A negative-string assertion
  would pass on any rewording including a wrong one, so none is invented.

## Risks

- **Regeneration forgotten, `.github/mcp.json` ships without `env`.** Most likely
  failure. Caught by `scaffold_freshness_guard`, which cannot be satisfied by the edit
  alone. Run its printed remediation verbatim including `AI_BADGER_MCP_AVAILABILITY=all`.
- **The two `NUDGE_LINE` copies drift.** This repo's recurring defect. Caught by the new
  comparison test plus the sync check.
- **Deleting the wrapper turns out wrong.** Reversal is cheap — one commit back; P5's
  keep-it alternative is written out in the architect's full report.
