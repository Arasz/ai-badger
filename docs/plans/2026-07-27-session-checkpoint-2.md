# Session checkpoint — 2026-07-27, second

Point-in-time record. Supersedes nothing; the first checkpoint
(`2026-07-27-session-checkpoint.md`) covers the waves up to 0.27.0.

State at write time: `main` @ `502a6b5`, VERSION `0.31.1`, last tag `ai-badger--v0.31.1`,
**1011 tests passing**, all ten gates green. Everything below `501b936` is pushed; the two
merges after it are local only.

## Merged since 0.31.1 — unreleased

No `VERSION` bump yet. Parallel agents were forbidden from touching `VERSION` because every
merge conflict earlier in the session came from concurrent bumps; the release is cut centrally
once the in-flight work lands.

| Change | Shape | Shipped surface? |
|---|---|---|
| Wave 18 — gitleaks history scan (`.github/workflows/secret-scan.yml`) | CI only | no |
| Wave 11 — ADR-0007, no Python distribution | docs only | no |
| Wave 15 — `test_scaffold.py` and `test_drift.py` split into 12 modules | tests only | no |
| deps-guard — `scripts/deps_guard.py` + pre-commit + CI | gate | **yes** |
| Wave 12 — one MCP entry renderer behind a destination table | refactor | **yes** |

Two of these touch the shipped surface, so the central release must be at least a minor:
**0.32.0**.

### Wave 11's decision, because three other waves wait on it

ADR-0007: `badger_lib` and the scaffold engine are **not** published as a Python distribution.
Packaging fixes the two deployment shapes that already work and does nothing for the two that
are broken — a `.ai-badger/` scaffold and `~/.hermes/plugins/` are not failing to *import a
library*, they are failing to *find the catalog they were copied away from*. `features/` and
`schemas/` are data, not importable code.

Three plan claims were corrected by verification, and I re-checked each one:

- **Seven** canonical `_bootstrap_lib()` copies, not nine (19 files counting generated mirrors).
- **Four** disagreeing root predicates, not three — `drift_notice_hook.find_plugin_root` is the
  fourth, an independent implementation.
- `~/.hermes/plugins/` is a **fourth deployment shape** the plan's three-shape framing omitted.

Consequences: **Wave 7 proceeds** (WP33 must *resolve* rather than search, over four ordered
inputs, and record the root in `manifest.json` at scaffold time — a manifest addition, so
minor-version under ADR-0001 §3). **Wave 16 is unblocked** — the rename is just a rename.
**Wave 17's facade is mandatory, not tidiness**: `badger_lib` must survive as an import name
indefinitely (17 import sites, the shim's own predicate, and two user-visible error messages).

## In flight — three defect fixes, dispatched, not yet returned

From a user report against 0.31.1 during a 0.18.1 → 0.31.1 `den-refresh` of
`job-search-ai-assistant`. **All three reproduce on this repo's own dogfooded output** — I
verified each before dispatching, rather than taking the report at face value.

| Branch | Defect | Verified how |
|---|---|---|
| `fix/manifest-dirmeta-schema` | `scaffold.py` emits `dirMeta`; `manifest.schema.json` sets `additionalProperties: false` and omits it | `validate_file` on `.ai-badger/manifest.json` → **9 of 57 entries rejected** |
| `fix/portable-hook-paths` | `wire_hooks` writes absolute paths; `merge_hooks` dedupes on the whole command string | this repo's `.claude/settings.json` holds `python3 "/Users/arasz/RiderProjects/ai-badger/.ai-badger/skills/task/scripts/session_start_hook.py"` |
| `feat/preserved-regions` | managed agent files silently drop project-authored content on re-scaffold | reporter's own workaround was a hand-written "re-check this line after a refresh" reminder |

The hook-path defect is the worst of the three. Absolute paths mean every additional checkout
— worktree, second clone, or the `~/.ai-badger/framework` cache — appends a permanent duplicate
rather than matching an existing entry. In the reporter's project **five real hooks had become
eleven entries**, and two `drift_notice_hook.py` copies printed two contradictory version
warnings in one session, which reads as a versioning bug and sends you hunting in the wrong
place. The aggravating detail: running `den-refresh` from a git worktree — the documented-safe
way to make repo changes — is exactly what mints a new path, so the recommended workflow feeds
the bug.

Each fix agent was told to write the failing test first, to push a branch and **not** open a
PR, and not to touch `VERSION`.

## Still mine to do

1. **Defect 3 — `.mcp.json` `cwd`** (`mcp_tools.py`, `pin_cwd` in the new destination table).
   Deliberately not dispatched: Wave 12 was rewriting that file, and it has only just merged.
   `.mcp.json` is tracked, so a refresh run from a worktree rewrites `cwd` to that worktree and
   stages it — merging would point the project's MCP server at a directory that later gets
   deleted. Wave 12's `pin_cwd` column is now the single place to fix it.
2. Cut **0.32.0** centrally: bump `VERSION`, write the changelog, re-scaffold, tag. Wave 12
   earmarked `docs/changelog/0.29.0-one-mcp-writer.md`; that number is stale — fold it into the
   0.32.0 entry, and record that the two command splitters were preserved rather than unified.
3. Update the deferred-work plan's status table — Waves 11, 12, 15 and 18 still read `planned`.
4. `SECURITY.md:110` says there is no secret-scanning hook. Still literally true (it says
   *pre-commit hook*; Wave 18 is CI), but the "Automated checks" list above it now
   under-reports.

## Deferred, with reasons

- **Wave 6** — collides with both Wave 12 (`mcp_tools` is one of the mixins) and Wave 15
  (`test_scaffold.py`). Now unblocked, since both have merged.
- **Wave 7** — proceed per ADR-0007. WP32 must use a fake home: against the real home it passes
  for the wrong reason, because `~/.ai-badger/framework` exists here at VERSION **0.13.0**
  against a 0.31.1 catalog and satisfies `_is_root`.
- **Wave 16** — unblocked, but lands after Wave 7 so the root literal lives in one predicate
  instead of 19 files.
- **Wave 17** — needs 7 and 8 first.
- Instrument the remaining hooks (`prompt-markers`, `task`, `mcp_index`) — best after Wave 7.

## Two verified defects still unfixed

- `schemas/model.schema.json` and the agent-instructions template schema set
  `additionalProperties: false` without permitting `$schema`.
- `features/common/support.json` says Junie writes `.junie/guidelines.md`; `features/junie/
  scaffolding.json` writes `.junie/AGENTS.md`.
