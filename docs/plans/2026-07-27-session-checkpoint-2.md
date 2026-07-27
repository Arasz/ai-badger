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
| Defect 1 — `manifest.schema.json` permits `dirMeta` | schema fix | **yes** |

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
| `fix/manifest-dirmeta-schema` — **merged** | `scaffold.py` emits `dirMeta`; `manifest.schema.json` sets `additionalProperties: false` and omits it | `validate_file` on `.ai-badger/manifest.json` → **9 of 57 entries rejected**; now 0 |
| `fix/portable-hook-paths` — **merged** | `wire_hooks` writes absolute paths; `merge_hooks` dedupes on the whole command string | this repo's `.claude/settings.json` holds `python3 "/Users/arasz/RiderProjects/ai-badger/.ai-badger/skills/task/scripts/session_start_hook.py"` |
| `feat/preserved-regions` — **merged** | managed agent files silently drop project-authored content on re-scaffold | reporter's own workaround was a hand-written "re-check this line after a refresh" reminder |

The report attributed `dirMeta` to `feed-badger`'s `detect_additions`. That is wrong, and the
agent checked rather than accepting it: `detect_additions.py` never reads the key — it
recomputes `bl.dir_content_hash` and compares only `content_hash`. The real consumer is
`drift.py:208`, which uses it as an O(1) structural pre-check before the content hash, driven
by `refresh.py`. Keeping the key and widening the schema was therefore right; removing the
emitter would have silently slowed every drift check to a full re-hash.

**Hook paths.** `${CLAUDE_PROJECT_DIR}` was verified three ways before being relied on — the
documented placeholder, this repo's own `drift_notice_hook.py:52` which already reads the env
var, and an empirical run. The dedupe keys on the text after the last of three explicit
markers (`/.ai-badger/skills/`, `/features/common/skills/`, `/features/claude/skills/`), so all
five spellings of one script collapse while distinct scripts stay distinct; anything with no
marker (the `code-review-graph` shell hooks) falls back to the literal command and is copied
through untouched. `merge_hooks` now *removes* superseded entries rather than only skipping the
append — which is what repairs an already-broken project rather than merely halting its growth.
I re-ran the reporter's exact eleven-entry shape against the merged code: **five entries
collapse to three**, both duplicated absolutes gone, the third-party hook byte-identical and
still first.

**Preserved regions — the report understated it.** The requested feature was
`<!-- ai-badger:keep-start -->` markers. The underlying defect was one line:
`agent_files.py:69` wrote the `.ai-badger/` source-of-truth copy with a bare
`write_text(body)`, bypassing `_copy_with_header` entirely. So the file the project is *told*
to edit received none of the four preservation mechanisms that already existed — no managed
header, no preserve check, no note. That is exactly the reported inversion (root `CLAUDE.md`
preserved, source of truth silently overwritten), and it was never a missing feature so much
as a write path that skipped the rules. The fix routes both write sites through one helper
rather than adding a fifth mechanism, per ADR-0006.

Malformed markers (unterminated, stray end, nested) leave the file **byte-identical** and emit
a note naming the line. A typo costs a refresh, never content.

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
   Deliberately not dispatched: Wave 12 was rewriting that file. `.mcp.json` is tracked, so a
   refresh run from a worktree rewrites `cwd` to that worktree and stages it — merging would
   point the project's MCP server at a directory that later gets deleted.
   **Decided (maintainer): preserve an existing valid `cwd`; write it only when absent.**
   Writing `${CLAUDE_PROJECT_DIR}` was rejected — Claude Code documents `${VAR}` expansion in
   `.mcp.json` for `command`/`args`/`env`/`url`/`headers`, and `cwd` is not on that list;
   depending on it would repeat the unverified-behaviour mistake `0.28.0-mcp-user-tool-paths.md`
   explicitly refused. Omitting `cwd` entirely was rejected for the same reason — the default
   launch directory is not documented either. Residual, accepted: a fresh scaffold still writes
   a machine-specific path that a second clone inherits.
2. **Wire the statusline capture.** `features/common/skills/task/scripts/statusline_capture.py`
   ships but nothing registers it — no scaffolding writes a `statusLine` key. Verified inert:
   `statusline-state.json` does not exist, so `poll_limit.py`'s "use Claude Code's own
   rate-limit metadata" fast path never fires and every check spends a probe. Same
   shipped-but-inert class as the plugin hooks and the extension mechanism. The wrapper already
   chains through `$CLAUDE_USER_STATUSLINE`, so a user's own statusline keeps rendering.
   **Decided (maintainer): wire the capture only — no ai-badger renderer.** Opt-in with
   consent, since `statusLine` is a personal setting.
3. Cut **0.32.0** centrally: bump `VERSION`, write the changelog, re-scaffold, tag. Wave 12
   earmarked `docs/changelog/0.29.0-one-mcp-writer.md`; that number is stale — fold it into the
   0.32.0 entry, and record that the two command splitters were preserved rather than unified.
   The re-scaffold also clears two known-stale artefacts: `.ai-badger/skills/welcome-ai-badger/
   scripts/hook_wiring.py` (one version behind `features/`) and this repo's own
   `.claude/settings.json`, whose absolute hook path should collapse to the portable form on
   its own — the cleanest proof the repair works.
4. Update the deferred-work plan's status table — Waves 11, 12, 15 and 18 still read `planned`.
5. `SECURITY.md:110` says there is no secret-scanning hook. Still literally true (it says
   *pre-commit hook*; Wave 18 is CI), but the "Automated checks" list above it now
   under-reports.
6. Follow-up from the preserved-regions work: `.ai-badger/instructions/*.md` are catalog copies
   written by `scaffold_instructions` via `shutil.copyfile` and do **not** carry regions, while
   their `.github/instructions/` copies now do. The asymmetry is in the safe direction (a
   marked region in the `.github/` copy survives), but it is an asymmetry.

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
