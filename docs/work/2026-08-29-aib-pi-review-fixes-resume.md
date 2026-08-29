# Resume record — aib-pi-review-fixes (2026-08-29)

State snapshot for continuing this task in a fresh session. Everything below was measured,
not recalled. Where a fact was carried from an earlier plan and later disproved, the
correction is marked **CORRECTED**.

---

## 1. How to start working on this task

```bash
# 1. The work lives here. Every command runs in this worktree, not the main checkout.
cd /Users/arasz/RiderProjects/ai-badger/.ai-badger/worktrees/aib-pi-v2

# 2. Confirm you are where you think you are.
git log --oneline -1        # expect a171a2e7 or later, on task/aib-pi-review-fixes-v2
cat VERSION                 # expect 0.144.0

# 3. The venv lives in the MAIN checkout. There is no .venv in any worktree.
V=/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3
$V -m pytest -q                                    # expect 4644 passed, 17 skipped
$V -m pylint $(git ls-files '*.py' | grep -v '^tests/')   # expect 10.00/10
$V tooling/index_build.py --check                  # expect "index.json up to date"

# 4. TS gates. bun 1.4.0 at /opt/homebrew/bin. Run tsc from the WORKTREE ROOT.
cd features/pi && bun install --frozen-lockfile && cd -
bun test features/pi                               # expect 63 pass (more once G5 lands)
bunx tsc --noEmit -p features/pi                   # expect exit 0

# 5. Read the plan; section 11 is the newest revision and wins on any disagreement.
#    docs/work/2026-08-28-pi-review-fixes-plan.md
```

Then read section 5 (what remains) below and pick up there.

**Read before touching anything:** section 6, gotchas. Several are traps that already cost
this task time, and two of them will silently corrupt the release if repeated.

---

## 2. Identity

| Thing | Value |
|---|---|
| Task id | `aib-pi-review-fixes` (tracker: IN_PROGRESS since 2026-08-28T17:50:39Z) |
| Branch | `task/aib-pi-review-fixes-v2` |
| Worktree | `.ai-badger/worktrees/aib-pi-v2` |
| PR | https://github.com/Arasz/ai-badger/pull/449 (open, non-draft, all 8 checks green at 31ef066a) |
| Base | `main` @ `94338ada` |
| Release | VERSION `0.144.0`, changelog `docs/changelog/0.144.0-pi-becomes-a-harness-that-runs.md` |
| Companion PR | https://github.com/Arasz/pi-mcp-tools/pull/1 — fork F11–F18, **done**, 73/73 green, tsc clean |
| Effort level | high |

**Owner's goal:** pi replaces hermes as the daily harness. Every feature the owner uses daily
gets at least a simple usable form in pi. Full parity with claude/hermes/copilot is explicitly
out of scope.

---

## 3. Why the branch is `-v2`

PR #446 was squash-merged into main on 2026-08-28T20:52:09Z carrying the plan, a scaffold regen
and a pre-existing-failure repair — but **none of the implementation**. That squash orphaned
`task/aib-pi-review-fixes` and every lane branch built on it.

The work was **rebuilt onto main by patch**, never merged. `features/pi/` on main was
byte-identical to the lane base `f0ddd82c`, so every patch applied cleanly. Do not try to merge
the old branches; this repo has already paid 187 conflicts over a 19-file diff for that mistake.

Orphaned branches, kept only as provenance — do not merge them:

| Branch | Head | Content |
|---|---|---|
| `task/aib-pi-review-fixes` | `f0ddd82c` | Wave 0 tests, pre-rebuild |
| `task/aib-pi-lane-python` | `dd084ba3` | WP1–WP5, G1, G2 (7 commits) |
| `task/aib-pi-lane-ts` | `22fb568e` | P1–P4 (6 commits) |
| `task/aib-pi-lane-g34` | `173c17b4` | G3, G4 (2 commits) |
| `task/aib-pi-lane-g5` | `151974a7` | G5 — **in flight, not yet folded in** |

---

## 4. What is done — commits on `task/aib-pi-review-fixes-v2`

| Commit | Content |
|---|---|
| `5a91709c` | Wave 0: born-RED tests T1–T9 + plan rev 3 |
| `01a1495b` | Python lane: WP1–WP5, G1, G2 |
| `c9fcaefb` | TS lane: P1 adapter, P2 away mode, P3 cron repair, P4 doc truths |
| `7c5c6f66` | A vendored `node_modules` is not catalog content |
| `31ef066a` | Release 0.144.0, pi added to `config.agents`, keep-region idempotency fix |
| `9c30bed1` | Real-home guard checks for a leak, not for absence |
| `a171a2e7` | G3 session-usage reader, G4 hook-arm coverage contract |

All 18 review findings F1–F18 are addressed: F11–F18 in the fork PR, the rest here.

---

## 5. What remains

1. **Fold in the G5 lane** when it reports (branch `task/aib-pi-lane-g5`, worktree
   `.ai-badger/worktrees/aib-pi-lane-g5`). G5 = `adjust_agents.py` writing personas to
   `<project>/.pi/agents/*.md`, **plus ai-badger's own minimal subagent extension** at
   `features/pi/subagent/index.ts` so those files are not inert. Owner widened the scope
   explicitly: *"make them not inert — implement the extension as a part of G5."*
   Fold it the same way as the others:
   ```bash
   git diff 7c5c6f66 <lane-head> > /tmp/g5.patch && git apply --3way /tmp/g5.patch
   ```
   G5 also owns making `support.json`'s `pi.personas` row honest — it is currently
   `aiBadgerSupport: true` while nothing ships, deliberately left for that lane.

2. **Re-scaffold from the MAIN CHECKOUT, not a worktree.** The installed pi settings currently
   carry `skills: ["/Users/arasz/RiderProjects/ai-badger/.ai-badger/worktrees/aib-pi-v2/.ai-badger/skills"]`
   — a path that disappears when the worktree is removed. The final installing scaffold must run
   from `/Users/arasz/RiderProjects/ai-badger` so the path is stable.

3. **Run the section 10 machine-cutover checklist** end to end (see section 7 below for what is
   already proven and what is not).

4. **Finish the task**: update `.ai-badger/state.json`, `task_tracker.py finish aib-pi-review-fixes`,
   reflect into memory, merge PR #449.

5. **Owner decision still open:** hermes was left in `config.agents` alongside pi. Retiring it is
   the owner's call, not a side effect of this task.

---

## 6. Gotchas — read these before working

- **The venv is in the main checkout only.** `.venv/bin/python3` does not exist in any worktree.
  Use `/Users/arasz/RiderProjects/ai-badger/.venv/bin/python3`.
- **The pre-commit pylint hook runs with `--rcfile=/dev/null` and a 9.5 floor**, so it ignores
  pyproject.toml's `redefined-outer-name` / `protected-access` disables. If it blocks a test file,
  use the module-level idiom at the top of `tests/test_pi_adjustments.py`.
- **Any shipped-surface change requires the release ritual.** The pre-push `release` lane rejects a
  push when the shipped surface changed but VERSION matches the last tag. Bump VERSION, add a
  changelog entry, run `tooling/version_sync.py`, `tooling/index_build.py`, then re-scaffold.
- **The re-scaffold invocation is exact** and the freshness guard prints it verbatim:
  ```bash
  AI_BADGER_MCP_AVAILABILITY=all python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py \
      --config .ai-badger/config.json --target . --root . --no-install --skills ''
  ```
  `--skills ''` means "the set already scaffolded", recovered from the manifest — it does **not**
  mean none.
- **Editing a `features/common/skills/**` source requires `tooling/sync_plugin_skills.py`** to
  refresh the `skills/` copy, or the sync gate fails.
- **`docs/work/` files need a row in `docs/work/README.md`.** Pre-push does not check it; CI does.
  A missing row reddens main after a green push.
- **Tests run real scripts against real user state.** Two guards in `tests/test_pi_adjustments.py`
  originally asserted `~/.pi/agent/extensions/<name>/` does *not exist*, which broke the moment the
  cutover installed it. Guards must snapshot-and-compare, never assert absence.
- **A `bun install` under `features/pi` used to break the Python suite** — fixed in `7c5c6f66`, but
  it is why `features/pi/node_modules` is gitignored and skipped by the catalog walkers.

---

## 7. Measured facts — do not re-derive, do not contradict

All measured this session against the installed pi and this machine.

**pi runtime**
- pi **0.84.4** (was 0.84.3 when the plan was written), bin is `#!/usr/bin/env node` — there is
  **no `Bun` global**, so the `Bun.cron` rung can never fire today. It exists as future-proofing.
- Logged in to **openrouter**, default model `moonshotai/kimi-k2.6`. Headless `pi -p` works.
- `--resume, -r` takes **no argument** (interactive selector). Resume by id is
  `pi -p --session <path|id>`, which accepts a partial UUID.
- Subdirectory extensions are discovered **only** as `~/.pi/agent/extensions/<name>/index.ts`.
  `package.json` does not register the entry for that layout.
- Skills discovery: `~/.pi/agent/skills/`, `~/.agents/skills/`, project `.pi/skills/` and
  `.agents/skills/` (trust-gated), package `skills/` dirs, the settings `skills` array,
  `--skill <path>`. **pi never reads `.claude/skills/`.**
- Project resources are trust-gated. `-p`, `--mode json` and `--mode rpc` **ignore project
  resources entirely** without a saved trust decision. This is why every ai-badger extension
  installs user-scope, and why G5's extension reads `.pi/agents/` itself through `fs`.
- `~/.pi/agent/trust.json` **does not exist**; `defaultProjectTrust` is `"ask"`.
- The `mcp` settings key has **zero occurrences** in pi's docs and dist — it is read solely by the
  pi-mcp-tools fork extension.
- Custom agent files are plain `*.md` (`entry.name.endsWith(".md")`), **not** `*.agent.md`.
  `.agent.md` is copilot's convention.

**Session JSONL — CORRECTED from the plan**
- Path: `~/.pi/agent/sessions/--<cwd-with-slashes-as-dashes>--/<ISO-timestamp>_<uuid>.jsonl`
- Usage is **nested under `message.usage`**, on entries of `type: "message"` — *not* top-level on
  assistant entries as the plan assumed.
- Field names are pi's own, not Anthropic's:
  `{"input":449,"output":23,"cacheRead":701,"cacheWrite":0,"reasoning":20,"totalTokens":1173,
    "cost":{"input":...,"output":...,"cacheRead":...,"cacheWrite":0,"total":...}}`

**Hook seam — CORRECTED from the plan**
- D1 named `python3 <cwd>/.ai-badger/hooks/ai_badger_hooks.py` as the adapter's shell-out target.
  That module is a **Hermes plugin**: no `__main__`, no `json.load(sys.stdin)`. It would import,
  print nothing, exit 0 — a gate that gates nothing.
- The real seam is the gate list in `<cwd>/.ai-badger/hooks/hooks.json`. The adapter reads that
  file rather than keeping a second copy that would drift from it.
- stdin the real gates parse:
  `{"hook_event_name":"PreToolUse","session_id":...,"cwd":...,"tool_name":...,"tool_input":{...}}`
- stdout: silence means allow; a decision is
  `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
    "permissionDecisionReason":"..."}}`. Every gate exits 0 unconditionally.
- Tool names must be translated to Claude casing (`bash→Bash`, `edit→MultiEdit`, `write→Write`,
  `grep→Grep`, `find→Glob`, `read→Read`, `ls→LS`) and pi's `path`→`file_path`,
  `edits[].oldText/newText`→`edits[].old_string/new_string`, because the shipped matchers are
  Claude-cased.
- `ctx.hasUI` is **false** under `-p` and `--mode json`, so an "ask" decision cannot be asked
  headless. The adapter allows and notices, rather than bricking headless runs — and that branch
  is tested separately from away mode, so an unasked ask is never counted as an away approval.
- `pi.exec()` cannot feed stdin; the adapter uses `node:child_process.spawn` for stdin, signal
  and timeout.

**MCP SDK 1.26.0 (fork Q1)**
- Reusing a `Client` after `close()` **succeeds** — verified live with a stdio echo server. The
  fork's original "unusable client" premise was stale. The fix (always recreate) is kept anyway,
  and the shipped comment states it as policy, not as an SDK claim.

---

## 8. Findings the plan did not have

| # | Finding |
|---|---|
| 1 | **pi was never in this repo's `config.agents`** (`['claude','copilot','hermes']`). Every pi arm opens with `if "pi" not in config.agents: return applied=False`, so all of it was inert here and no extension was ever installed. Fixed in `31ef066a`. |
| 2 | **`carry_keep_regions` duplicated a template's own keep region.** pi's `AGENTS.override.md.tmpl` is the only template shipping a keep block, so re-scaffolding appended another copy every run — measured 1, 2, 3 across three runs, unbounded, failing the freshness guard for anyone with pi enabled. Fixed; measured 1, 1, 1 after. |
| 3 | **A vendored `node_modules` under `features/` broke the catalog walkers.** Running the new bun/tsc gate turned the Python suite red — the two gates could not both be run in one tree. |
| 4 | **`adjust_cron` carried the identical silent-install defect as `adjust_hooks`.** The plan's fail-loud decision named only one twin. |
| 5 | **`support.json` carried three more false claims** than the finding list: the `.claude/skills/` "79/79" figure, an unearned `personas: true`, and copilot's `*.agent.md` convention. |
| 6 | **An unhandled EPIPE** when writing the payload to a gate that exits before reading stdin — found by running the adapter against this repo's real gates rather than mocks. |
| 7 | **G4's two sides speak different vocabularies** — adapter events `{tool_call}` vs manifest arms `{hermes, copilot}` — so the intended equality assertion would be permanently red or vacuously green. Reported rather than forced; five narrower assertions ship instead. |

---

## 9. Section 10 cutover checklist — current status

| # | Check | Status |
|---|---|---|
| 0 | Trust state recorded | **done** — no `trust.json`, `defaultProjectTrust: "ask"` |
| 1 | `~/.pi/agent/extensions/` holds `ai-badger/` and `pi-cron/`; pi loads them without error | **PASS** — both present with their `index.ts`; a headless `pi -p` session loaded cleanly |
| 2 | settings.json carries `skills` and `mcp`, unknown keys intact | **PASS** — both merged; all 12 pre-existing keys preserved, including ones the owner added by hand mid-task |
| 3 | pi-mcp-tools fork extension installed user-scope, `/mcp-status` lists merged servers | **not done** — fork PR open, extension not installed here |
| 4 | A pi session reads a skill from `.ai-badger/skills/` via the settings entry | **not done**; blocked on step 2 of section 5 (path points into a doomed worktree) |
| 5 | One tool call exercises the adapter in a real pi session; away mode auto-approves an ask | **partial** — proven under bun against this repo's real gates (`.git/config` edit blocked with reason, read allowed, missing-hooks fails open with a notice, all three error paths notify, away mode auto-approves and notifies). **Not yet witnessed inside a real pi session.** |
| 6 | One witnessed launchd cron fire | **not done** |
| 7 | `pi -p --session <id>` resumes; the tracker's resume command round-trips | **not done** |

Backup of pre-cutover pi state (settings.json, extensions/, auth.json):
`/private/tmp/claude-501/-Users-arasz-RiderProjects-ai-badger/d7677566-ce77-498c-8408-de443459ccf8/scratchpad/pi-backup-20260829-122122`
Note the scratchpad is session-scoped; copy it somewhere durable if it still matters.

---

## 10. Gate baselines

| Gate | Command | Expected |
|---|---|---|
| Suite | `$V -m pytest -q` | 4644 passed, 17 skipped, 0 failed |
| Lint | `$V -m pylint $(git ls-files '*.py' \| grep -v '^tests/')` | 10.00/10 |
| Index | `$V tooling/index_build.py --check` | up to date |
| TS tests | `bun test features/pi` | 63 pass (more once G5 lands) |
| TS types | `bunx tsc --noEmit -p features/pi` | exit 0 |
| Fork | `npx vitest run` + `npx tsc --noEmit` in `/Users/arasz/RiderProjects/pi-mcp-tools-fork` | 73/73, clean |
| CI | `gh pr checks 449` | 8 checks green |

`$V = /Users/arasz/RiderProjects/ai-badger/.venv/bin/python3`
