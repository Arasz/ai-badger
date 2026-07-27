# Session checkpoint — 2026-07-27, second

Point-in-time record. Supersedes nothing; the first checkpoint
(`2026-07-27-session-checkpoint.md`) covers the waves up to 0.27.0.

**0.33.0 is released** — tagged `ai-badger--v0.33.0`, pushed. 1053 tests passing, all ten gates
green. 0.32.0 (four defects from a real refresh) and 0.33.0 (stop installing a tool-call
interceptor) both shipped; statusline wiring is merged and unreleased.

## What shipped in 0.32.0

Four defects from a real `0.18.1 → 0.31.1` `den-refresh` of `job-search-ai-assistant`, plus
four waves that were in flight when the report arrived.

| Change | Shipped surface? |
|---|---|
| Hook commands are `${CLAUDE_PROJECT_DIR}`-relative; duplicates collapse | **yes** |
| `.mcp.json` keeps a recorded `cwd` that still names a scaffolded project | **yes** |
| `manifest.schema.json` permits `dirMeta`, which the scaffolder always emitted | **yes** |
| Preserved regions, and the `.ai-badger/` source of truth obeys the same write rules | **yes** |
| Wave 12 — one MCP entry renderer behind a destination table | **yes** |
| deps-guard — `scripts/deps_guard.py` + pre-commit + CI | **yes** |
| Wave 11 — ADR-0007, no Python distribution | docs only |
| Wave 15 — `test_scaffold.py` / `test_drift.py` split into 12 modules | tests only |
| Wave 18 — gitleaks history scan | CI only |

**All four defects reproduced on this repo's own dogfooded output.** That is why they survived:
the framework was producing the same broken artefacts it ships, and every gate was green.

### The proof the hook repair is retroactive

Before the release re-scaffold, this repo's `.claude/settings.json` held
`python3 "/Users/arasz/RiderProjects/ai-badger/.ai-badger/skills/task/scripts/session_start_hook.py"`.
After it: `python3 "${CLAUDE_PROJECT_DIR}/.ai-badger/skills/task/scripts/session_start_hook.py"`
— **collapsed in place**, no duplicate appended, both third-party `code-review-graph` entries
byte-identical. I separately replayed the reporter's exact eleven-entry shape against the
merged code: five entries collapse to three.

### Corrections the agents made to their own briefs

- **`dirMeta`'s consumer.** The report (and my dispatch prompt, which repeated it) attributed it
  to `feed-badger`'s `detect_additions`. Wrong — that script never reads the key; it recomputes
  `bl.dir_content_hash` and compares only `content_hash`. The real consumer is `drift.py:208`,
  an O(1) structural pre-check before the content hash. Removing the emitter would have silently
  slowed every drift check to a full re-hash.
- **Preserved regions were a symptom.** The requested feature was `ai-badger:keep-*` markers.
  The cause was one line: `agent_files.py` wrote the `.ai-badger/` copy with a bare
  `write_text(body)`, bypassing `_copy_with_header` — so the file projects are *told* to edit
  received none of the four preservation mechanisms that already existed. Fixed by routing both
  write sites through one helper, not by adding a fifth (ADR-0006).
- **ADR-0007 corrected three plan claims**: seven canonical `_bootstrap_lib()` copies, not nine;
  **four** disagreeing root predicates, not three (`drift_notice_hook.find_plugin_root` is an
  independent fourth); and `~/.hermes/plugins/` is a fourth deployment shape the three-shape
  framing omitted. I re-verified all three.

### Decisions worth not re-litigating

- `${CLAUDE_PROJECT_DIR}` **is** used for hook commands — verified three ways (documented
  placeholder, this repo's own `drift_notice_hook.py:52` which already reads the env var, and an
  empirical run).
- `${CLAUDE_PROJECT_DIR}` is **not** used for `.mcp.json`'s `cwd`. Claude Code documents `${VAR}`
  expansion there for `command`/`args`/`env`/`url`/`headers`; `cwd` is not on that list, and the
  default launch directory is not documented either, so omitting `cwd` was equally unfounded.
  Same rule as `0.28.0-mcp-user-tool-paths.md`. Residual, accepted: a fresh scaffold still
  writes a machine-specific path a second clone inherits.
- Wave 12's two command splitters were **preserved, not unified** — unifying silently changes
  generated `.mcp.json` content.
- Wave 18 ships with **no baseline and no `.gitleaksignore`**: a scan of all 307 commits found
  nothing, so the gate blocks from its first run.

## ADR-0007's consequences for the waves that waited

- **Wave 7 — proceed, nothing discarded.** WP33 must *resolve* rather than search, over four
  ordered inputs (`--root` → `$AI_BADGER` → ancestor walk → a root recorded in `manifest.json` →
  cache), because the ancestor walk structurally cannot succeed in two of the four shapes.
  Recording the root at scaffold time is a manifest addition, so minor under ADR-0001 §3.
  **WP32 must use a fake home**: against the real home it passes for the wrong reason, because
  `~/.ai-badger/framework` exists here at VERSION 0.13.0 against a current catalog and satisfies
  `_is_root`.
- **Wave 16 — unblocked.** The rename is just a rename. Lands after Wave 7 so the root literal
  lives in one predicate instead of 19 files.
- **Wave 17 — the facade is mandatory, not tidiness.** `badger_lib` must survive as an import
  name indefinitely: 17 import sites, the shim's own predicate, and two user-visible error
  messages. Split modules must be flat siblings, not a package with `__init__.py`.
- **Wave 6** — was blocked by Waves 12 and 15; both have now shipped.

## 0.33.0 — the plugin that intercepted every tool call

`semgrep` was `scope: default` for the python stack, so `welcome-ai-badger --execute` installed
**Semgrep Guardian** on every python project: a ~16 MB prebuilt Go binary hooking
`PreToolUse`/`PostToolUse` on `Write|Edit|Bash`, plus a `guardian` MCP server, which opens a
browser to Semgrep OAuth when it finds no session. The symptom that surfaced it was a login page
appearing on **`git commit`** — a commit is a Bash call.

Removed from the catalog rather than made configurable: installing a tool-call interceptor
silently, as a side effect of scaffolding, is not the framework's decision to make. The guard is
`TestThirdPartyPluginsAreNotAddedSilently`, which pins the complete external-plugin set so
adding one fails the suite until the allow-list is updated. `pydantic-ai` and `pyright-lsp` were
re-checked rather than assumed: no hooks, no MCP server, no binaries.

## Merged, unreleased — statusline capture

`statusline_capture.py` shipped but nothing registered it. Verified inert:
`statusline-state.json` did not exist, so `poll_limit.py`'s "use Claude Code's own rate-limit
metadata" fast path never fired and every check spent a probe — the same shipped-but-inert class
as the plugin hooks and the extension mechanism.

Opt-in via `statusLineCapture.enabled` (default **false**), because a project-level `statusLine`
**overrides the user's own** — demonstrated live, not assumed. Three verifications worth keeping:

- **Project-level `statusLine` clobbers user-level.** Confirmed in the Claude Code binary's
  trust scanner and then live in a pty: a probe entry rendered instead of the configured
  `~/.claude/statusline.sh`.
- **Settings `env` does reach the statusLine command — but that is undocumented**, so it was not
  built on. The displaced renderer is recorded in
  `.ai-badger/task-tracking/statusline-delegate.json` (gitignored, machine-local) instead;
  `CLAUDE_USER_STATUSLINE` still wins when set.
- **`${CLAUDE_PROJECT_DIR}` is documented only for hooks**, so it was verified directly:
  statusLine and hooks share one executor that sets it in the child environment. Safe here,
  confirmed two ways.

A hazard found mid-task and fixed: with capture enabled but the `task` skill not scaffolded, the
wiring pointed `statusLine` at a nonexistent script — silently blanking the status bar. It now
refuses with a note.

**Known gap:** flipping `enabled` back to `false` leaves the wired `statusLine` in place. An
unwire path that restores the delegate is a coherent follow-up.

## Issue triage (2026-07-27 16:40)

- **#76** (Hermes plugin hooks receive no `cwd`) — **closed.** Fixed in 0.18.0; `_project_cwd()`
  at `ai_badger_hooks.py:84` is the single resolver, with the requested tests in
  `tests/test_hook_cwd_resolution.py`. Left open by oversight, not left unfixed.
- **#67** (sync Hermes learned skills) — **closed.** Delivered in 0.18.0, past its acceptance
  criteria: it asked for a proof-of-concept and got shipped code plus two test files. Its
  question-5 assumption was corrected on close — the scaffold does *not* copy
  `.ai-badger/skills/` into `.claude/skills/`; that path does not exist. Pointed at #103.
- **#103** (ai-badger skills invisible to Claude Code) — **open, both causes reproduced on
  0.33.0.** Cause 1: no `skills/` at the plugin root, so the plugin contributes zero skills
  despite its description promising them. The convention was verified against the `superpowers`
  plugin, which has a top-level `skills/` and declares no skills key in `plugin.json`. Cause 2:
  `features/claude/` has **no `adjustments/` directory at all**, where copilot has three.
  **Cause 2 is fixed and merged** (`features/claude/adjustments/adjust_skills.py`, 12 tests);
  cause 1 is still in flight on `fix/plugin-exposes-its-skills`.

The migration hazard was the delicate part: a hand-committed `.claude/skills/<name>` that appears
in no manifest, which `den-refresh` cannot see and never updates, is worse than an absent skill.
The implemented rule is refuse-and-report — a destination is replaced only when ai-badger
demonstrably placed it (our own symlink resolving inside `.ai-badger/skills/`, or a path recorded
in `manifest.json`). Everything else is left byte-for-byte and named in a note that says what to
do about it, not merely what happened. Skills outside the adjustment's own list are never
iterated, so third-party ones cannot be touched at all.

I re-verified this independently of the agent's own tests, running the adjustment against a
project seeded with both hazards: `den-refresh` linked and resolved to the managed copy, the
hand-committed `task` kept its 0.18.1 content, and a third-party `my-own-skill` survived. The
agent also mutation-tested its own guards — short-circuiting `_ours` to clobber-anything made
exactly the four guard tests fail, which is the evidence that they are load-bearing rather than
decorative.

Deliberately not done: factoring the ~90% shared logic out of the copilot and claude adjustments.
Per-agent duplication is the established pattern (`adjust_hooks.py` exists separately under both
`copilot/` and `hermes/`), adjustments load standalone via `importlib` with no shared package,
and a shared module would mean editing `features/copilot/`. Worth revisiting if a third agent
needs the same behaviour.

## Backlog dispatch plan (2026-07-27 17:00)

Split by real file surface, not by theme. **Part 1 is running now; Part 2 waits on Wave 7.**

### Part 1 — dispatched, in flight

| Branch | Work |
|---|---|
| `fix/plugin-exposes-its-skills` | #103 cause 1 — plugin contributes zero skills |
| `task/wave-7-one-framework-root` | **The keystone.** WP32/33/34 per ADR-0007 |
| `task/wave-8-feature-registry` | One feature-type registry; a new template becomes visible to drift |
| `fix/small-batch-a` | Junie path contradiction · `$schema` rejected by every strict schema · statusline unwire path · secret-scanning pre-commit (or a justified decision not to) |

**Waves 7 and 8 share two files by design.** `scripts/badger_lib.py`: Wave 7 owns root
resolution (~L84+), Wave 8 owns `FEATURES` (~L23). `drift.py`: Wave 7 owns only the
`_bootstrap_lib()` preamble, Wave 8 owns the feature tuple (~L100). Each agent was told which
region it owns. This is a regional overlap, not a collision.

Every Part 1 agent was told **not** to hand-edit `.claude/skills/` — regenerate via
`sync_plugin_skills.py` — because #103 cause 1 may be *relocating* that mirror. A post-merge
re-sync is expected.

### Part 2 — queued, dispatch after Wave 7 merges

| Work | Why it waits |
|---|---|
| **Wave 6** — five mixins → composed collaborators | Genuine collision: restructures `scaffold.py` and the welcome-ai-badger mixins, which Wave 7's shim work also edits |
| **Wave 16** — rename top-level `scripts/` | After 7, so the root literal lives in one predicate instead of 19 files |
| **Wave 17** — split `badger_lib.py` | Needs 7 **and** 8. ADR-0007: the `badger_lib` facade is mandatory, not tidiness — flat sibling modules, never a package with `__init__.py` |
| **Small batch B** — preserved-region asymmetry in `.ai-badger/instructions/*.md`; instrument `prompt-markers` / `task` / `mcp_index` hooks | Both touch `scaffold.py` / hook preambles that Wave 7 edits |

## Open, not started

1. Instrument the remaining hooks (`prompt-markers`, `task`, `mcp_index`) — best after Wave 7.
2. `schemas/model.schema.json` and the agent-instructions template schema set
   `additionalProperties: false` without permitting `$schema`.
3. `features/common/support.json` says Junie writes `.junie/guidelines.md`;
   `features/junie/scaffolding.json` writes `.junie/AGENTS.md`.
4. `.ai-badger/instructions/*.md` are catalog copies written via `shutil.copyfile` and do **not**
   carry preserved regions, while their `.github/instructions/` copies now do. The asymmetry is
   in the safe direction, but it is an asymmetry.
5. No secret-scanning **pre-commit** hook — Wave 18 is CI-side only, so a credential can be
   committed locally and is caught on push. `SECURITY.md` now says exactly this.
