# Session checkpoint — 2026-07-27, second

Point-in-time record. Supersedes nothing; the first checkpoint
(`2026-07-27-session-checkpoint.md`) covers the waves up to 0.27.0.

**0.32.0 is released** — `main` @ `1b69a7c`, tagged `ai-badger--v0.32.0`, pushed. 1031 tests
passing, all ten gates green, re-scaffolded against itself.

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

## In flight

- **`feat/wire-statusline-capture`** — `statusline_capture.py` ships but nothing registers it.
  Verified inert: `statusline-state.json` does not exist, so `poll_limit.py`'s "use Claude
  Code's own rate-limit metadata" fast path never fires and every check spends a probe. Same
  shipped-but-inert class as the plugin hooks and the extension mechanism. **Maintainer decided:
  wire the capture only, no ai-badger renderer, opt-in.** The agent was told to verify rather
  than assume whether project-level `statusLine` is honoured and whether the settings `env`
  block reaches the statusLine command — and to report back rather than ship if chaining cannot
  be made reliable without leaning on undocumented behaviour.

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
