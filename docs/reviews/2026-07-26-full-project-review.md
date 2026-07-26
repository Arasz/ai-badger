# Full-project code review — ai-badger 0.18.1

| | |
|---|---|
| **Date** | 2026-07-26 |
| **Version reviewed** | 0.18.1 (`VERSION`, `.claude-plugin/plugin.json`) |
| **Commit** | `86457cf` — *feat: add Claude extension for task skill* |
| **Branch** | `task/full-project-code-review` |
| **Baseline** | 691 tests passing · pylint 10.00/10 (non-test scope) · `index_build.py --check` OK · `validate.py --all` OK |
| **Scope** | Whole project — `scripts/`, `features/`, `schemas/`, `tests/`, `docs/`, generated `.ai-badger/` and `.claude/` |

## Method

Eight independent reviewers worked in parallel from a shared brief
(`review-brief.md`), each with one lens and no visibility into the others:

| Lens | Focus |
|---|---|
| architecture | module boundaries, coupling, dead paths, refactor candidates |
| security | threat model of a tool that writes into repos **and** home directories |
| python | language-level correctness, portability, stdlib/3.8 claims |
| ai-agent | quality of the *generated product* (instructions, hooks, routing, token budget) |
| skills | SKILL.md engineering, judged against `superpowers:writing-skills` |
| tests | coverage of destructive / `$HOME`-touching / symlink paths |
| silent-failures | swallowed errors, fail-soft-and-silent, non-atomic writes |
| docs | doc↔code truth, ADRs, changelog, release process |

Raw output: **23 Critical · 60 Important · 37 Suggestions**, with substantial overlap.

This document is the integration pass. Every Critical was re-verified against the
actual code by an integrating reviewer who did **not** take any claim on faith:
each cited `file:line` was opened, and where the claim was testable it was
executed (e.g. `install_skills()` was run against the real catalog; `release_guard.py`
was run; `git ls-remote --tags` was checked against the remote). Findings below
carry a verdict: **CONFIRMED**, **PARTIAL** (real but overstated — the overstatement
is named), or **REJECTED**.

Tools used: `Read`/`Grep`/`Bash` for verification; the reviewers additionally used
`code-review-graph` MCP tools and `python3 -m pylint` targeted runs.

## Limitations of this review

These are recorded because they cost the reviewers time and will cost the next
reviewer the same time if they are not written down.

1. **`code-review-graph` produced no usable layering signal on this repo.**
   `get_architecture_overview_tool` reports 13 communities with **0 cross-community
   edges**; `get_surprising_connections_tool` returns only test-internal helper calls;
   `get_impact_radius_tool` saturates at *"500 nodes / 66 files / risk: high"* for
   **every** input, because `tests/conftest.py::load_script` is a universal hub.
   The cause is architectural, not a tool defect: the dominant coupling mechanisms
   here are `importlib.util.spec_from_file_location`, `sys.path.insert`, and shared
   filesystem paths — none of which a static parser can see. `features/README-adjustments.md:12-18`
   already documents this for the adjustment dispatch. **All blast-radius estimates in
   this document are hand-derived from direct callers and test coverage.**

2. **`get_knowledge_gaps_tool` / `tests_for` produced ~20 name-collision false
   positives.** The graph resolves `tests_for` by *unqualified* name: every function
   named `main` in the repo resolved to `test_awm.py::test_main_*`; `Scaffolder.run`
   resolved to `resume_cron.py`'s unrelated `run`. Modules reported as "untested
   hotspots" — `hook_wiring.wire_hooks`, `validate.validate_all`,
   `agent_files._apply_scaffolding`, `mcp_index._auto_tags` — are in fact covered
   end-to-end. The test reviewer re-verified every gap by grep + reading test bodies;
   the coverage gaps in this document are the manually-confirmed residue.

3. **The `.mjs` scripts were reviewed by reading only.** There is no JS test runner
   in the repo, so no claim about them was executed.

4. **Windows behaviour was reasoned about, not executed.** The POSIX-only findings
   (F-15) are from static reading of `import fcntl` / `crontab` / `venv/bin/pip`.

5. **No finding was reproduced against a released artefact**, because — see F-11 —
   no release artefact past `v0.2.0` exists.

---

# Executive summary

Eight lenses, working blind, converged on the same underlying story from different
directions. The codebase is not sloppy; it is *carefully written and
under-verified in exactly one dimension*. The eight themes below are the systemic
account, not a list of defects.

### T1 — Tests validate synthetic fixtures; the shipped catalog is unverified. This is the root cause of most of the dead code.

Four shipped features are inert, and each one is invisible for the same reason.
`tests/test_install_plugins.py:44-51` builds a *fixture* catalog containing a
`"claude plugin install {name} --scope {scope}"` template; the **real**
`features/claude/plugins-instructions.json` has no `{name}` template at all, so
`install_skills()` silently emits four identical marketplace-add commands and
installs nothing (F-06, reproduced). `tests/test_scaffold.py:500-536` asserts
`"SessionStart" in hooks` — which the *wrong* hook already satisfies (F-07).
`mcp_index_hook.py` shells out to a script name that exists nowhere in the repo,
and no test ever calls `_rebuild_index` (F-03). `_ensure_framework_cache` is only
ever reached by tests that mock it away (F-09).

691 green tests, pylint 10.00/10, `index_build --check`, `validate.py --all` and
`release_guard.py` all pass over a tree in which four advertised features do
nothing. **The gates are green because they check the fixtures and the index, not
the product.** Every remediation in this document should therefore add at least
one assertion against the *real* `features/` tree, not only a synthetic one.

### T2 — "Unreadable" is treated as "absent", and then overwritten.

The same six lines appear ~10 times:

```python
existing = {}
if path.exists():
    try:
        existing = load(path)
    except (ValueError, OSError):
        pass          # ← a parse error is now indistinguishable from an empty file
...
path.write_text(render(existing))   # ← unconditional
```

Sites: `hook_wiring.py:134-138` (project `.claude/settings.json` — reachable on
**every** scaffold), `mcp_tools.py:153/197/241/335` (`~/.hermes/config.yaml`,
`~/.claude/settings.json`, `.github/copilot/mcp-config.json`, `.mcp.json`),
`learned_skills_sync.load_manifest:154-166`, `task_tracker._current_crontab:290-292`,
`release_guard._git:46-51`. In a tool whose stated job is *"writes files into
users' repos and home directories"*, this idiom converts every transient parse
error into silent, irreversible loss of the user's `permissions`, `hooks`, `env`,
`statusLine` — or their entire crontab (F-02, F-04). In `release_guard` the same
idiom turns a git failure into a green release gate (F-10).

### T3 — Destructive operations run before their guards, and the repo already knows better.

`sync_skill()` `rmtree`s the destination **above** the `if dry_run: return` (F-01).
`install_cron()` writes an authoritative replacement crontab computed from a read
that failed (F-04). `adjust_skills.py:52-54` `rmtree`s a `.github/skills/<name>`
it never checked ownership of (F-16). This is not a knowledge gap: the same repo
contains `scaffold._owns_link` (refuses to unlink anything in `~/.hermes/skills/`
that does not resolve back into the project), `learned_skills_sync`'s
`dest.resolve().relative_to(learned_root.resolve())` containment check before
`rmtree`, and `tracker_lib.save_json`'s correct atomic write. **The right patterns
exist and are not applied uniformly** — which makes this cheap to fix and
important to fix as a convention, not as five isolated patches.

### T4 — Two generated artefacts, one gate.

`index.json` is generated and gated: `index_build.py --check` is wired into
pre-commit *and* CI. `.claude/skills/` — the directory plugin users actually load —
is generated by hand-running `sync_plugin_skills.py`, with no `--check`, no
pre-commit hook, no CI job, and no test (F-17). The failure mode is a one-line fix
committed to `features/` with everything green and the bug still shipping in
`.claude/`. Today the copies happen to be byte-identical (verified by two
reviewers independently), which is exactly why nobody has noticed the missing gate.

### T5 — The release model is fully specified, invariant-backed, CI-wired — and not operated.

`VERSION` is `0.18.1`; `docs/changelog/` has 33 entries; the newest tag on the
remote is `ai-badger--v0.2.0` (verified against `git ls-remote`). Consequence:
`release_guard.py` compares the working tree against a 16-version-old baseline,
always finds changes, always finds `VERSION != 0.2.0`, and **always takes the PASS
branch** — verified by running it (F-10, F-11). The invariant with the best
mechanical backing in the whole repo is currently a no-op, and nothing reports
that.

### T6 — User-scope reach exceeds user-scope consent.

A repo-scaffolding tool writes to six locations outside the repo, none behind a
prompt: `~/.claude/settings.json`, `~/.hermes/config.yaml`, `~/.hermes/skills/`,
the user's **crontab**, the machine's **global npm prefix** (`npm install -g`), and
`~/.ai-badger/framework` — the last being an unpinned `git clone` of `main` whose
contents are then `exec_module`'d (F-09). Separately, `auto-wm` stores
auto-approval state machine-globally at `~/.claude/awm/state.json` with no tool
denylist (F-12). Individually each is defensible; collectively they are a
consent-model gap, and the fix is uniform (an explicit, printed, opt-in gate).

### T7 — The product is agent-facing text, and the agent-facing text has drifted from the behaviour.

This framework's *deliverable* is instructions. So doc drift here is a product
defect, not a chore. `.hermes.md:1` tells an agent its source of truth is
`.ai-badger/.hermes.md`, which does not exist; `.github/copilot-instructions.md`
points at `.ai-badger/CLAUDE.md`, a **different file's identity** (F-08, verified
on disk). `RELEASING.md:6` documents a Hermes discovery mechanism ADR-0003
explicitly rejected (F-18). `docs/framework-architecture.md:111,141` hands the
reader a `config.json` example that fails the repo's own schema (F-19).
`.ai-badger/instructions/python.instructions.md` orders agents to treat pyright
type errors as build failures in a project with no type checker. CLAUDE.md's
"Agent delegation" section renders as `_Default routing._` — a placeholder that
reads like a policy.

### T8 — Several features are advertised in machine-readable manifests and implemented nowhere.

`hooks-manifest.json` declares `mcp-index-init` and `mcp-index-update`; both point
at a script that does not exist (F-03). `session_start_hook.py` — session
recording, poll-limit launch, unfinished-task recovery, all load-bearing for
`task/SKILL.md`'s Recovery section — is scaffolded into every consumer project and
wired by nothing (F-07). `auto-wm/SKILL.md` describes a user-level install that
`scaffold.py` does not perform. `statusline_capture.py` ships a default pointing at
the maintainer's own home directory, so the feature is silently off for 100% of
other users (F-20). The pattern: **a promise in a manifest or a SKILL.md is not
checked by anything**, so it survives indefinitely.

### What this adds up to

The engineering judgement in this repo is good — the security reasoning in
`learned_skills_sync.py`, the seed-once ownership model, the tiered drift
detection, and the honesty of `docs/changelog/0.17.4-*` (a public self-correction)
are better than most projects of this size. The gap is verification *of the
shipped artefact*, and it produces defects in a consistent shape. Fix the shape,
and the individual defects mostly stop recurring.

---

# Verified findings

Severity is the **integrated** severity after verification, which in several cases
differs from what the originating reviewer assigned. `Reported as` records the
original claim so the delta is auditable.

## Theme A — Destructive writes to state ai-badger does not own

### F-01 · Critical · CONFIRMED · `sync_plugin_skills.py --dry-run` deletes every target skill directory and copies nothing

- **Corroborated by:** security C5, silent-failures C3, architecture C2, tests I3 (4 reviewers, independently) — plus confirmed by the review requester by direct reading.
- **Where:** `scripts/sync_plugin_skills.py:71-80`, print bug at `:98-115`

```python
def sync_skill(src: Path, dest: Path, dry_run: bool) -> int:
    if not src.is_dir():
        return 0
    if dest.exists():
        shutil.rmtree(dest)      # ← runs even when dry_run is True
    if dry_run:
        return 1                 # ← returns before copytree recreates dest
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*SKIP_PATTERNS))
    return 1
```

- **Failure scenario:** a maintainer runs the flag documented as *"Show what would
  be copied"*. It removes `.claude/skills/{task,welcome-ai-badger,feed-badger,den-refresh,maintain-agent-instructions,prompt-markers,mcp-index,auto-wm}`
  and prints `would sync: <name>` for each — a report claiming nothing was touched.
- **Second, independent bug in the same loop:** the per-skill print is keyed on
  `args.dry_run`, not on `sync_skill`'s return value. A typo in `COMMON_SKILLS`, or
  a skill renamed upstream, makes `sync_skill` return `0` while the script still
  prints `synced: <name>`.
- **Blast radius (honest):** bounded to this repo's own generated `.claude/skills/`,
  which is regenerable by re-running without `--dry-run`. That is why it survived.
  It is still "the dry-run flag destroys data".
- **Fix:** move `if dry_run: return 1` above the `rmtree`; make the print
  conditional on the returned count.
- **TDD:** yes, trivially. See WP1 in the plan.

### F-02 · Critical · CONFIRMED (project scope) / PARTIAL (user scope) · An unparseable settings file is treated as empty and then replaced

- **Corroborated by:** security C3, silent-failures C1 (2 reviewers).
- **Where:** `features/common/skills/welcome-ai-badger/scripts/hook_wiring.py:134-145`
  (project `.claude/settings.json`); `mcp_tools.py:153-180` (`~/.hermes/config.yaml`),
  `:197-224` (`~/.claude/settings.json`), `:241-248`, `:335-340`.

At `hook_wiring.py:134-138` a `JSONDecodeError` (a `ValueError`) sets `settings = {}`;
`:143-145` then writes `settings` back with only a `hooks` key. Everything else in
the file — `permissions.deny`, `env`, `statusLine`, `mcpServers` — is gone. This
repo's own `.claude/settings.json` currently carries all four.

- **Verdict split, stated precisely:**
  - **CONFIRMED and reachable today:** the `hook_wiring.py` path fires on *every*
    scaffold/refresh with `claude` in `config.agents`. No special catalog content needed.
  - **PARTIAL — latent, not reachable with the shipped catalog:** the `mcp_tools.py`
    user-scope paths require at least one MCP server declared with `scope: "user"`.
    Verified: `features/common/mcp-servers.json` is `{"servers": []}` and no
    `"scope"` key appears in any `mcp-servers.json` in the tree. `scope: "user"` is
    a documented, schema-supported field, so this is one catalog line from arming —
    but the security reviewer's `~/.claude/settings.json` PoC required constructing
    that catalog entry, and that should be stated.
- **Related, same functions, CONFIRMED:** `yaml.YAMLError` is neither `ValueError`
  nor `OSError`, so a malformed `~/.hermes/config.yaml` raises out of
  `Scaffolder.run()` mid-scaffold, leaving a half-written `.ai-badger/` with no
  manifest. `existing.setdefault(...)` additionally raises `AttributeError` if the
  YAML parses to a list.
- **Fix:** on parse failure **abort the specific write**, append a note, and never
  overwrite a file you could not read. Write via tempfile + `os.replace` (the
  pattern `tracker_lib.save_json:150-163` already gets right). Back up to
  `<name>.bak-<ts>` before the first modification of any user-scope file. Catch
  `yaml.YAMLError` explicitly and assert the parsed value is a `dict`.
- **TDD:** yes — see WP2.

### F-03 · Critical (security shape) / Important (functional) · CONFIRMED with a corrected framing · A user-scope Hermes hook executes a `cwd`-derived path that the framework never creates

- **Corroborated by:** python C1, ai-agent C2, security C2 (3 reviewers, from three
  different angles — dead code, broken feature, latent RCE).
- **Where:** `features/common/hooks/mcp_index_hook.py:32-48`, invoked unconditionally
  from `:51-62` and `:65-86`; installed to `~/.hermes/plugins/` by
  `features/hermes/adjustments/adjust_hooks.py`.

```python
subprocess.run(
    ["python3", str(project_root / ".ai-badger" / "skills" / "mcp-index" / "scripts" / "mcp_index_build.py"),
     "--target", str(project_root)], ...)
```

- **Verified:** `find . -name "mcp_index_build.py"` returns **nothing** anywhere in
  the repo (`features/`, `.ai-badger/`, `.claude/`). The real script is
  `mcp_index.py`, and its `main()` does `cmd = argv[0]` (`mcp_index.py:554`), so
  even with the filename corrected, `argv = ["--target", <path>]` yields
  `cmd == "--target"`, which matches no subcommand and falls through to `_usage()`.
  **Two independent errors**, so the hook has never worked.
- **`project_root` comes from `_find_project_root()` (`:18-24`)**, which walks up
  from `os.getcwd()` for any `.ai-badger/` directory. The plugin lives at *user*
  scope, so this is not scoped to the project that installed it. No allowlist, no
  consent, no hash check, no containment check.
- **Framing correction (this is the PARTIAL part):** the security reviewer called
  this RCE. It is a **latent** RCE, not a live one: because the framework never
  creates the file, *any* occurrence of that path is foreign content — but there is
  none today, so the call is currently a silent no-op that logs at WARNING with no
  handler configured. The correct statement is: *the design (exec a path derived
  from cwd, at user scope) is the defect; the dead filename is what has kept it
  harmless.* Fixing the filename without fixing the design would **arm** it.
- **Also confirmed:** `post_tool_call` calls `_rebuild_index` unconditionally on
  every MCP tool call (`:86`) despite the docstring's staleness-check claim.
- **Fix (recommended):** delete `_rebuild_index` and both call sites, and remove the
  `mcp-index-init` / `mcp-index-update` entries from `hooks-manifest.json`. If the
  feature is wanted, re-introduce it behind (i) a resolved path required to be
  inside a project whose `.ai-badger/manifest.json` this installation wrote,
  (ii) a hash check against the manifest, and (iii) explicit opt-in in `~/.hermes`.
- **TDD:** yes — a test placing a sentinel-writing `mcp_index_build.py` in a temp
  project must show `on_session_start()` does not create the sentinel.

### F-04 · Critical · CONFIRMED · `install-cron` can replace the user's entire crontab, and it runs by default on `task start`

- **Corroborated by:** security C4, silent-failures I4 (2 reviewers).
- **Where:** `features/common/skills/task/scripts/task_tracker.py:290-292`,
  `:301-338`, `:341-351`; triggered from `cmd_start` at `:128-129`.

```python
def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""
```

- **Failure scenario, stated with its precondition:** `crontab -l` exits non-zero
  both for *"no crontab for user"* and for real failures — spool unreadable, cron
  not installed, sandboxed/denied (on macOS, a terminal without Full Disk Access).
  When it fails **while a crontab exists**, `_current_crontab()` returns `""`,
  `install_cron` computes `new_lines = [] + [desired_line]` and pipes that to
  `crontab -` as an authoritative replacement. The user's unrelated cron jobs are
  gone, with no backup. `uninstall_cron` has the identical conflation.
- **Not opt-in:** `cmd_start` calls `install_cron(quiet=True)` on **every**
  `task_tracker.py start` unless `--no-cron` is passed (verified at `:128-129`).
  The installed job runs `resume_cron.py`, which launches
  `claude --resume <id> -p <prompt> --permission-mode acceptEdits` unattended every
  30 minutes. Installing an unattended edit-accepting agent loop should be an
  explicit decision.
- **Also CONFIRMED (silent-failures I4):** no `FileNotFoundError` handling around
  the `crontab` calls, so on a machine without cron, `cmd_start` prints its success
  JSON at `:113-122` and *then* crashes with a raw traceback at `:129`.
- **Also CONFIRMED (minor):** `_desired_cron_line` (`:295-298`) interpolates paths
  unquoted — a repo path with a space breaks the line; one containing `%` silently
  truncates the command (cron treats `%` as a stdin separator).
- **Fix:** distinguish "no crontab" from failure and **abort** on failure; back up
  the previous crontab before any write; invert the flag to opt-in `--cron`; catch
  `FileNotFoundError`/`OSError`; quote interpolated paths.
- **TDD:** yes — see WP4.

### F-05 · Critical · CONFIRMED · The learned-skill secret scanner skips symlinks; the copy dereferences them

- **Corroborated by:** security C1 (single reviewer, but with an executed PoC in a
  sandboxed `$HOME`; independently re-verified here by reading the three cited sites).
- **Where:** `features/common/hooks/learned_skills_sync.py:261-262` (scan skips
  symlinks) vs `:234` (`copytree(..., symlinks=False)` dereferences them); gate at
  `:113-134` (`is_syncable`).

```python
for path in sorted(source_dir.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue                                    # ← scanner never looks
...
shutil.copytree(source_dir, dest, dirs_exist_ok=True, symlinks=False)   # ← copy dereferences
```

`is_syncable()` walks only the **path components of `source_dir`** looking for
symlinks (`current = skills_root; for part in parts: ... if current.is_symlink()`).
It never inspects files *inside* the skill. A Hermes skill containing
`creds.txt -> ../../../../.aws/credentials` passes all five gates.

- **Failure scenario:** the sync fires from `post_tool_call` on every successful
  `skill_manage` (`ai_badger_hooks.py:379-383`); the destination is
  `.ai-badger/skills/learned/…` inside the user's repo; `.ai-badger/skills/` is not
  gitignored. The target's *content* lands as a regular file and is one `git add .`
  from being pushed. The symlink can point anywhere on disk, making this an
  arbitrary-file-read → repo-write primitive.
- **Fix (recommended, minimal decision surface):** refuse outright — extend gate 4
  to walk every file under `source_dir` and return `(False, "symlink")` on any
  symlink found. Optionally *additionally* resolve-and-scan. Do not silently redact;
  the module's fixed-vocabulary refusal design is correct and should be preserved.
- **TDD:** yes — see WP5.

### F-16 · Important · CONFIRMED, with the abort claim REJECTED · `adjust_skills.py` `rmtree`s a foreign `.github/skills/<name>` and crashes on a plain-file destination; zero tests

- **Corroborated by:** tests C2, security I10 (2 reviewers).
- **Where:** `features/copilot/adjustments/adjust_skills.py:48-56` (whole 66-line
  file has no test — `grep -rln adjust_skills tests/` → nothing).

```python
if dst.is_symlink():
    dst.unlink()
elif dst.is_dir():
    shutil.rmtree(dst)
dst.symlink_to(os.path.relpath(src, dst.parent))
```

- **CONFIRMED:** a hand-authored `.github/skills/task/` (a plausible collision —
  that is Copilot's own convention) is deleted with no backup, no note, and no
  manifest ownership check. Contrast `scaffold._owns_link:106-114`, which does
  exactly the right thing for `~/.hermes/skills/`.
- **CONFIRMED:** a plain **file** at `dst` matches neither branch, so `symlink_to`
  raises `FileExistsError`.
- **REJECTED sub-claim:** the tests reviewer wrote that the `FileExistsError` *"can
  abort the whole scaffold for unrelated agents"*. It cannot. `run_adjustments`
  (`scaffold.py:537-539`) wraps each adjustment in
  `except Exception as exc: self.notes.append(f"adjustment '{script_name}' … failed: {exc}")`.
  The failure degrades to a user-visible note; the scaffold continues. Severity is
  Important, not Critical.
- **Fix:** manifest-ownership check before `rmtree`; handle the plain-file branch;
  add `tests/test_adjust_skills.py` mirroring `tests/test_scaffold.py:338-499`
  (which already covers exactly these cases for the hermes path).

## Theme B — Shipped features that do nothing

### F-06 · Critical · CONFIRMED, reproduced · The declarative skill-install layer emits no install command for any skill

- **Corroborated by:** architecture C1 (single reviewer; reproduced empirically here).
- **Where:** `scripts/install_plugins.py:156-164` (template selection), `:102`
  (stack list); data at `features/claude/plugins-instructions.json:4-12`.

`install_skills()` picks the first template containing `{name}`; when none exists
and there is only one template, it falls back to `cmd_templates[0]` — the
*add-source* template. The shipped `plugins-instructions.json` declares exactly one
template per source type, neither containing `{name}`.

**Reproduced against the real catalog and this repo's own `config.json`:**

```
$ python -c "install_skills(Path('.'), config, dry_run=True)"
{"commands": [
   "claude plugin marketplace add https://github.com/anthropics/claude-plugins-official",
   "claude plugin marketplace add https://github.com/anthropics/claude-plugins-official",
   "claude plugin marketplace add https://github.com/anthropics/claude-plugins-official",
   "claude plugin marketplace add https://github.com/anthropics/claude-plugins-official"],
 "warnings": [], "dryRun": true}
```

`pyright-lsp`, `semgrep`, `pydantic-ai`, `superpowers`, `pr-review-toolkit` are never
installed. `warnings` is **empty** — nothing surfaces the failure. With `--execute`
(`scaffold.py:405-422`) the same marketplace-add runs four times at a 30 s timeout each.

- **Compounding, CONFIRMED:** `install_plugins.py:102` reads `config.get("stacks")`
  without prepending `"common"`, while `scaffold.py:220` uses `["common"] + config["stacks"]`
  and `schemas/config.schema.json` *forbids* `common` in `config.stacks`. So
  `features/common/skills.json` (superpowers, pr-review-toolkit) is dead catalog
  data on top of the template bug.
- **Why it was invisible:** `tests/test_install_plugins.py:44-51` builds a fixture
  marketplace entry with **two** templates including `"claude plugin install {name} --scope {scope}"`.
  The tests assert against the fixture. This is theme T1 in its purest form.
- **Fix:** (a) add the `{name}` install template to each agent's
  `plugins-instructions.json`; (b) replace the silent `cmd_templates[0]` fallback
  with an appended warning; (c) use `["common"] + config["stacks"]`; (d) add a test
  that runs `install_skills` against the **real** `features/` tree and asserts each
  declared skill name appears in some command.
- **Behaviour-changing:** yes, deliberately. Needs a changelog note.

### F-07 · Critical · CONFIRMED · `session_start_hook.py` is scaffolded into every project and wired by nothing; the one hook that *is* wired is a guaranteed no-op in consumers

- **Corroborated by:** skills C1 (single reviewer; independently re-verified here
  against the manifest, `hooks.json`, and this repo's live `.claude/settings.json`).
- **Where:** `features/common/hooks/hooks-manifest.json` (verified: the only
  `claude`/`SessionStart` entry is `drift-notice`); `features/common/hooks/hooks.json`
  (verified: its `SessionStart` command is `drift_notice_hook.py`);
  `hook_wiring.py:60-121`; `features/common/skills/task/scripts/drift_notice_hook.py:1-19`, `:35-48`.

Two defects, one wiring path:

1. **`session_start_hook.py` is never registered by anything.** Exhaustive grep
   confirms the only references are its own module, sibling docstrings, and
   `tests/test_session_start_hook.py` (which tests internals and never asserts it is
   wired). So session recording (`current-session.json`), the background
   `poll_limit.py` launch, and the unfinished-tracked-task recovery nudge — all
   load-bearing for `task/SKILL.md`'s Recovery section — do not happen.
2. **The hook that *is* wired cannot work in a consumer.** `hook_wiring.py` rewrites
   `${CLAUDE_PLUGIN_ROOT}/features/common/skills/` → `<target>/.ai-badger/skills/`
   and merges that into the consumer's `.claude/settings.json`. But
   `drift_notice_hook.find_plugin_root()` walks ancestors for a `VERSION` file **and**
   a `features/common/skills/` directory — which a consumer repo has neither of, so
   it returns `None` and `main()` exits silently. The script's own docstring says so
   in as many words: *"A hook registered by a consumer's own `.claude/settings.json`
   … never has it set."* `hook_wiring.py`'s generic manifest-driven rewrite does
   precisely the thing ADR-0001 (#24) diagnosed and fixed once.
   *(Verified: this repo's own `.claude/settings.json` wires
   `python3 ".../.ai-badger/skills/task/scripts/drift_notice_hook.py"`. It only
   resolves **here** because the ancestor walk reaches the framework repo root,
   which does have `VERSION` + `features/common/skills/`. In any real consumer it
   does not.)*
- **Why it was invisible:** `tests/test_scaffold.py:500-536` asserts only
  `"SessionStart" in hooks` and that the command contains `.ai-badger/skills/` —
  both satisfied by the wrong hook.
- **Fix:** add a `session-start-tracking` entry to `hooks-manifest.json` +
  `hooks.json` pointing at `session_start_hook.py`; stop wiring `drift_notice_hook.py`
  through the consumer's `.claude/settings.json` (it must run from the plugin's own
  `hooks.json`); assert the *specific* wired command path in the scaffold test.
- **⚠ Ordering constraint:** this fix **arms** the `poll_limit` → `run_auto_wm`
  chain described in F-12. F-12's gate must land first. See the plan's dependency graph.

### F-08 · Important (reported as Critical) · CONFIRMED verbatim on disk · Managed-file headers point at paths that do not exist, and in one case at a different file's identity

- **Corroborated by:** ai-agent C1 (single reviewer; re-verified here by reading the
  live generated files).
- **Where:** `_shared.py:19-21` (`MANAGED_HEADER` `{name}` slot);
  `agent_files.py:79` and `:91` (both pass `file_entry["target"]`, never `aibCopy`);
  `features/copilot/templates/copilot-instructions.md.tmpl:7` (hardcoded).

Verified on disk in this repo:

| File | Header claims | Reality |
|---|---|---|
| `.hermes.md:1` | `Source of truth: .ai-badger/.hermes.md` | no such file — it is `.ai-badger/HERMES.md` |
| `.github/copilot-instructions.md:1` | `Source of truth: .ai-badger/.github/copilot-instructions.md` | no such path — it is `.ai-badger/copilot-instructions.md` |
| `.github/copilot-instructions.md:7` | `Source of truth for this file: .ai-badger/CLAUDE.md` | a **different file's** content and identity |
| `CLAUDE.md:1` | `.ai-badger/CLAUDE.md` | correct, by coincidence (`target == aibCopy`) |

- **Failure scenario:** this is the first line of always-loaded, agent-facing
  content, whose entire purpose is telling an agent where durable edits go. An agent
  asked to "fix the copilot instructions" follows the banner to `.ai-badger/CLAUDE.md`
  and edits the wrong document; an agent asked to fix HERMES.md creates
  `.ai-badger/.hermes.md`, which the scaffolder never reads, and the next
  `den-refresh` silently discards the work.
- **Severity downgraded from Critical to Important:** no automated process destroys
  data here. The loss requires an agent (or human) to act on the wrong banner. It is
  still high-confidence, cheap to fix, and directly in the product's core value
  proposition (T7), so it belongs early.
- **Fix:** pass `aib_copy or file_entry["target"]` as the `name` argument at both
  `_copy_with_header` call sites; correct
  `features/copilot/templates/copilot-instructions.md.tmpl:7`; add a test asserting
  every managed header's referenced path exists post-scaffold.

## Theme C — Consent and blast radius outside the repo

### F-09 · Important (reported as Critical/Important) · CONFIRMED clone / REJECTED "pulls on every call" · `find_root()` clones the framework from unpinned `main` and the result is executed

- **Corroborated by:** architecture I7, security I3, tests C1 (3 reviewers).
- **Where:** `scripts/badger_lib.py:73-106` (`_ensure_framework_cache`), `:109-134` (`find_root`).

- **CONFIRMED:** when no local framework is found, `find_root()` clones
  `https://github.com/Arasz/ai-badger` (`--depth=1`, **no tag, no pin, no signature
  check**) into `~/.ai-badger/framework` and returns it. `scaffold.py:25-45`,
  `refresh.py:44-66`, `drift.py:52-70` then `exec_module` from the resolved root, so
  whatever is on `main` at the moment of the clone is what runs.
- **CONFIRMED:** `badger_lib.py:3` documents the module as *"Deterministic and
  offline"*, and `validate.py`, `index_build.py`, `install_plugins.py`, `detect.py`,
  `drift.py` all call `find_root()` when `--root` is omitted. Running
  `validate.py --all` from a non-checkout directory clones ~10 MB from GitHub into
  `$HOME` — from a function named "find".
- **REJECTED sub-claim (security I3):** *"on every later call it runs `git pull
  --ff-only` there."* It does not. `find_root()` step 2 returns the cache directly
  whenever it contains `schemas/` **and** `features/`, so `_ensure_framework_cache`
  — and therefore the `git pull` branch — is only reached when the cache exists with
  a `.git` dir but is missing `schemas/`/`features/`. In practice the pull is
  near-unreachable. The unpinned *first* clone is the real finding; the
  "self-updating channel" framing is not supported by the code.
- **CONFIRMED (tests C1):** zero tests execute this function's body.
  `tests/test_badger_lib.py:34-35` mocks `_ensure_framework_cache` away. A regression
  in the clone args, the `exist_ok=True`, or the `RuntimeError` path would ship
  silently — and a future test that forgets to patch `FRAMEWORK_CACHE` would clone
  into a real developer's `$HOME` over the network.
- **Fix:** split responsibilities — `find_root()` stays a pure lookup that raises
  with an actionable message; a new explicit `ensure_root()` does the clone, pinned
  to the tag matching the installed `VERSION`, behind an `--allow-network`/prompt.
  Correct the `badger_lib` docstring either way. Add
  `TestEnsureFrameworkCache` with `FRAMEWORK_CACHE` → `tmp_path` and `subprocess.run`
  patched (never real git).

### F-12 · Important (reported as Critical) · PARTIAL — three sub-claims CONFIRMED, one REJECTED · `auto-wm` auto-approves without a denylist, machine-globally, with no expiry

- **Corroborated by:** security C6 (single reviewer).
- **Where:** `features/claude/skills/auto-wm/hooks/awm_gate.py:99-112`,
  `features/claude/skills/auto-wm/scripts/awm.py:80-99`,
  `features/common/skills/task/scripts/poll_limit.py:241-258`, `:295`, `:302`.

| Sub-claim | Verdict |
|---|---|
| No tool denylist — `Bash(rm -rf …)`, `WebFetch`, out-of-repo `Write` auto-approve identically to `Read` | **CONFIRMED.** In partner mode the *only* exclusion is `AskUserQuestion` (`awm_gate.py:106-107`). |
| Machine-global — state at `~/.claude/awm/state.json`, so enabling it in one project auto-approves in every session on the machine | **CONFIRMED.** No project scoping in state, no `cwd` check in the gate. |
| Partner mode never expires | **CONFIRMED.** `awm.py:86-91` writes `"expires_at": None`; only `away` mode has a wall clock. |
| *"It can be enabled without a human"* — `poll_limit.run_auto_wm()` shells out to `claude -p "/auto-wm away 4h"`, and `poll_limit.py` is spawned on every SessionStart | **REJECTED as a live path.** `poll_once` does call `auto_wm_runner()` unconditionally on the limited→unlimited transition (`poll_limit.py:295`, `:302`), and `session_start_hook.start_poll_limit_background()` does spawn it detached (`session_start_hook.py:30-46`, `:56`). **But `session_start_hook.py` is wired by nothing** (F-07), and it is the *only* caller of `start_poll_limit_background`. So `poll_limit` never runs in a scaffolded project, and the self-enable chain is unreachable today. |

- **This is the most important cross-finding in the review.** The self-enable path is
  dead only because a *different* feature is dead. Fixing F-07 — which is a correct
  and desirable fix — **arms** it. The plan therefore orders F-12's denylist and
  opt-in gate strictly before F-07's wiring.
- **Severity:** downgraded to Important as an isolated finding (auto-approval is the
  skill's declared, user-invoked purpose; the missing denylist and global scope are
  hardening gaps). It is treated as a **Wave-2 blocker** because of the F-07
  interaction, not because of its standalone severity.
- **Fix:** (a) hard denylist of tools that can never be auto-approved; (b) record a
  project path in `state.json` and refuse when `payload["cwd"]` is outside it;
  (c) give partner mode a maximum lifetime; (d) remove `run_auto_wm()` from
  `poll_once`, or gate it on an explicit opt-in flag in state.

## Theme D — Gates that cannot fail

### F-10 · Important (reported as Critical) · CONFIRMED as code · `release_guard.py` cannot distinguish "git failed" from "nothing changed"

- **Corroborated by:** silent-failures C4 (single reviewer).
- **Where:** `scripts/release_guard.py:46-51` (`_git` returns `""` on any non-zero
  exit), `:78-81` (`changed_shipped_paths` → `[]`), `:96-98` (prints
  `"no shipped-surface changes since {tag} — PASS"`).
- **CONFIRMED:** the code path exists exactly as described. A tag that is fetched
  but whose commit object is missing under a shallow/partial clone, or any transient
  git error, produces an empty diff indistinguishable from "no changes". The script
  already prints a grep-able `NO RELEASE TAG FOUND` sentinel for the *sibling*
  failure mode one function earlier — the asymmetry is the tell.
- **Severity downgraded to Important, with a sharper reason than the reviewer gave:**
  the guard is *already* inert for a different reason (F-11), so this path has never
  been the thing keeping releases honest. Verified by running it:
  ```
  $ python scripts/release_guard.py
  shipped surface changed since ai-badger--v0.2.0 and VERSION was bumped (0.2.0 -> 0.18.1) — PASS
  ```
  It compares against a 16-version-old tag, always finds changes, always finds a
  bumped VERSION, and always PASSes. Hardening `_git` without fixing F-11 buys nothing.
- **Fix:** make `_git` return `Optional[str]` (or raise) and have
  `changed_shipped_paths` propagate a hard failure with its own sentinel. Fix
  together with F-11.

### F-11 · Important (reported as Critical) · CONFIRMED factually / PARTIAL on impact · No release tag exists past `ai-badger--v0.2.0`

- **Corroborated by:** docs C3 (single reviewer; re-verified here against the remote).
- **Verified:** `git ls-remote --tags origin` returns only `ai-badger--v0.1.0`,
  `ai-badger--v0.2.0` (plus a stray `v0.1.0`). `VERSION` is `0.18.1`;
  `docs/changelog/` has 33 entries; `.claude-plugin/plugin.json` says `0.18.1`.
- **PARTIAL — the reviewer's impact claim is overstated.** They wrote that every
  change since `v0.2.0` *"has never shipped to any Claude Code plugin consumer"*.
  `RELEASING.md:5` itself says Claude Code consumers *"resolve by `version` in
  `plugin.json`"* — which is `0.18.1` — and Hermes consumers get updates via
  `den-refresh` against the checkout/cache, not a tag. So content does reach
  consumers; what does not exist is an **immutable, resolvable release point**.
- **The confirmed impacts are:**
  1. ADR-0001's "releases are immutable tags / a version string is never reused"
     model is documented but not operated, so a bug report against "0.18.1" cannot
     be pinned to a commit.
  2. `release_guard.py`'s baseline is 16 versions stale, making the release gate a
     no-op (F-10).
  3. `.github/workflows/pylint.yml` correctly sets `fetch-depth: 0` with an explicit
     comment about this exact trap — so the CI setup is right and the tag data is
     what is missing.
- **Fix:** either cut the missing tags (or tag current `main` as the next release
  and go forward), or state explicitly in `RELEASING.md`/ADR-0001 that tags are
  batched, rather than presenting a tag-per-version model the history does not follow.

### F-17 · Important · CONFIRMED · `.claude/` is a published, hand-synced copy with no `--check`, no CI job, no pre-commit hook, and no test

- **Corroborated by:** architecture C2, tests I3 (2 reviewers).
- **Verified:** `.pre-commit-config.yaml` wires `version-sync`, `index-build`,
  `pylint` only. `.github/workflows/pylint.yml` runs pylint, pytest,
  `index_build --check`, `validate --all`, `version_sync --check`, `release_guard` —
  no sync check. `tests/` contains no `test_sync_plugin_skills.py`.
- **Failure scenario:** a one-line fix in `features/` with everything green, and
  `.claude/skills/` — what plugin users load — still contains the bug, with no signal.
  Two reviewers independently diffed the copies and found them currently identical,
  which is precisely why the missing gate is invisible.
- **Fix:** add `sync_plugin_skills.py --check` (exit 1 on any diff, mirroring
  `index_build.py:162-167`), wire it as a third `always_run` pre-commit hook and a CI
  step, and add a parity test using `badger_lib.dir_content_hash` with
  `SKILL_EXCLUDE_PATTERNS`. Note `MANAGED_EXTERNALLY` must be honoured by the check.

### F-24 · Important · CONFIRMED · `validate.py --all` covers 6 of 17 schemas, and the consumers of the uncovered ones swallow parse errors

- **Corroborated by:** architecture I9 (single reviewer; re-verified here by reading
  `validate_all` and counting `schemas/`).
- **Verified:** `validate_all` (`scripts/validate.py:66-100`) checks the schema
  self-check, `index.json`, `skills-source.json`, `skills.json`,
  `hooks-manifest.json`, `adjustment.json`, `plugins-instructions.json`. `schemas/`
  contains 17 files. Not validated: `mcp-servers.json`, `external-tools.json`,
  `stack.json`, `dependencies.json`, `scaffolding.json`, `mcp-tools.yaml`,
  `model.json` — despite matching schemas existing for the first five.
- **Compounding:** `mcp_tools.py:30-33` and `:50-53` both `except (ValueError, OSError): continue`.
  A typo in `features/<stack>/mcp-servers.json` produces a scaffold missing servers,
  with no note, no warning, and a zero exit anywhere. (`scaffolding.json` is the
  exception and the model: `agent_files.py:32-39` validates inline and appends a note.)
- **Fix:** drive `validate_all` from the schemas directory via the existing
  `KIND_TO_SCHEMA` mapping; replace the two silent `continue`s with `self.notes.append(...)`.

## Theme E — Correctness and hygiene (spot-checked, all CONFIRMED)

### F-13 · Important · CONFIRMED · Hooks fail soft **and** totally silently — no breadcrumb anywhere

`awm_gate.py:116-120`, `awm_context.py:69-73`,
`prompt-markers/scripts/user_prompt_hook.py:121-127`, `task/scripts/user_prompt_hook.py:99-105`
all end in `except Exception: pass` with no log line. `ai_badger_hooks.py:322-341`
and `:367-383` log genuine failures at DEBUG only. The fail-soft contract is
correct and should be preserved; the observability gap is the defect. This repo has
already shipped a hook that failed silently for weeks (#76, `0.18.0-plugin-hook-cwd.md`).
**Fix:** keep `sys.exit(0)`; add one stderr/rotating-file line before swallowing;
raise genuine exceptions from DEBUG to WARNING (as `mcp_index_hook.py` already does).
*(Corroborated by silent-failures C2, I2, I3 + security suggestion 7.)*

### F-14 · Important · CONFIRMED · Unguarded third-party `import yaml` in directly shell-invoked skill scripts

`features/common/skills/mcp-index/scripts/mcp_index.py:25` and
`features/copilot/adjustments/adjust_agents.py:85` import `yaml` at module scope
with no guard, while `mcp_tools.py:144-148` wraps the identical import in
`try/except ImportError` and degrades with a note. `mcp-index/SKILL.md` tells the
agent to run the script directly on whatever bare `python3` is on PATH and has **no
Prerequisites section**. Downgraded from Critical: the failure is a loud
`ModuleNotFoundError`, pyyaml *is* in `scripts/requirements.txt`, and CI installs it.
**Fix:** apply the `mcp_tools.py` guard pattern and add a Prerequisites section
mirroring `welcome-ai-badger/SKILL.md:26-33`.
*(Corroborated by python C2, skills I3, tests I5.)*

### F-15 · Important · CONFIRMED · The `task` skill is POSIX-only, undeclared

`tracker_lib.py:27` and `resume_cron.py:31` `import fcntl` at module scope, and
`tracker_lib` is imported by every task entry point, so the whole skill fails to
import on Windows. `task_tracker.py:291,344` shell out to `crontab`.
`dependency_check.py:76,118,144-154` hardcode `venv/bin/pip` and `venv/bin/python3`.
`features/common/skills/task/SKILL.md` carries **no `platforms:` front-matter key**,
unlike `mcp-index/SKILL.md:7` and `code-review-checklist/SKILL.md`, which declare
`platforms: [linux, macos, windows]`. Downgraded from Critical: nothing claims
Windows support for `task`; the defect is the missing declaration.
**Fix:** declare `platforms: [linux, macos]`, or shim `fcntl`/`crontab`.
*(python C3.)*

### F-20 · Important · CONFIRMED · Maintainer's personal absolute path shipped as a default

`features/common/skills/task/scripts/statusline_capture.py:23`:
`_DEFAULT_USER_STATUSLINE = "/Users/arasz/.claude/statusline.sh"`. It leaks the
author's username into every scaffolded project, and because
`render_user_statusline` gates on `USER_STATUSLINE.exists()`, the feature is
silently off for 100% of users other than the author, with no note and only an
undocumented `CLAUDE_USER_STATUSLINE` override.
**Fix:** default to `None`; skip rendering when unset; document the env var in the
skill.
*(Corroborated by python I4, silent-failures I8, security suggestion 5.)*

### F-21 · Important · CONFIRMED · Prompt markers false-positive on Windows drive-letter paths

`user_prompt_hook.py:48-55` matches with
`prompt.strip().lower().startswith(prefix.lower())` against bare prefixes `h:`,
`f:`, `e:` (`markers-context.json`, verified). Any prompt beginning
`"H:\Projects\foo.py, can you check this?"` lowercases to `h:\projects…` and
silently injects *"HINT: … You MUST perform a quick, cheap research pass…"*. The
injection is silent `additionalContext` by design, so the user gets a behaviourally
distorted response with no signal. (The start-anchoring itself is correct and
already defeats the classic mid-message false positive — see Strengths.)
**Fix:** require whitespace or end-of-string after the bare single-letter prefixes.
*(ai-agent I3.)*

### F-22 · Important · CONFIRMED · A `for … break` loop silently makes `.mcp.json` inherit the first agent's overrides

`features/common/skills/welcome-ai-badger/scripts/mcp_tools.py:293-298`:

```python
resolved = srv
for agent in agents:
    resolved = self._resolve_server_for_agent(srv, agent)
    break
```

For `agents: ["copilot", "claude"]`, the **copilot** override wins in a file Claude
Code reads. It is a silent misconfiguration driven by list order, dressed as a loop.
**Fix:** replace with an explicit decision — resolve per output file's owning agent,
or document `.mcp.json` as agent-neutral and drop the override.
*(architecture I3.)*

### F-23 · Important · CONFIRMED · Non-atomic writes to shared state, inconsistent with the codebase's own correct pattern

`tracker_lib.save_json:150-163` does it right (tempfile in the destination dir +
`os.replace`, cleanup on failure, re-raise). These do not:
`badger_lib.dump_json:143-147` (used for `manifest.json`, `config.json`,
`plugin.json`, `marketplace.json`, `index.json` — verified: plain `open(…, "w")` +
`json.dump`), `learned_skills_sync.save_manifest:169-176`,
`mcp_index._write_index:198-205` (holds hand-curated tags), the four `mcp_tools.py`
sites, `hook_wiring.py:144-145`. `learned_skills_sync.load_manifest:154-166`
compounds it by returning an *empty* manifest on parse error, so the next sync
after a crash silently discards every prior learned-skill record.
**Fix:** hoist the `tracker_lib.save_json` implementation into `badger_lib` and route
every one of these through it.
*(silent-failures I5.)*

### F-25 · Important · CONFIRMED · `Scaffolder.run()` has no rollback and writes its manifest last

`scaffold.py:542-597` writes personas, instructions, skills, agent files, hooks,
`~/.claude`, `~/.hermes`, `.mcp.json`, and only then `manifest.json`. Only
`run_adjustments` is guarded. Any raise partway (the uncaught `yaml.YAMLError` from
F-02 is a proven one) leaves framework files on disk with **no manifest**, which
`den-refresh` reports as "never fully scaffolded" (`refresh.py:101-102`) and
`feed-badger` rejects outright — and `.claude/settings.json` may already have been
rewritten. Compounding: `refresh.check_breaking_and_backup:73-93` only backs up
`.ai-badger/` for *breaking* transitions, so a routine refresh has no recovery path.
**Fix:** write `manifest.json.partial` first and record progress, or stage to a temp
dir and `os.replace` per file; back up unconditionally before re-scaffold; wrap
user-scope writes so they degrade to a note.
*(security I11, silent-failures I1.)*

### F-26 · Important · CONFIRMED · `install_plugins.py`'s standalone `--dry-run` can never be turned off

`scripts/install_plugins.py:183`: `ap.add_argument("--dry-run", action="store_true", default=True, …)`
— `dry_run` is `True` whether or not the flag is passed. Harmless today (the only
real caller is `scaffold.py`'s library import), but the documented CLI does not do
what it says.
**Fix:** add a real `--execute`, or state plainly that the CLI is print-only.
*(docs I7.)*

## Theme F — Documentation truth (all CONFIRMED; grouped, low individual risk)

| ID | Finding | Verified |
|---|---|---|
| **F-18** | `RELEASING.md:6` documents Hermes discovery via `skills.external_dirs` — ADR-0003 `:111` explicitly records this as *"Shipped in v0.7.1 and reverted"*; the real mechanism is per-project symlinks under `~/.hermes/skills/<project>/` (`scaffold.py:431-440`) | ✔ read both |
| **F-19** | `docs/framework-architecture.md:111,141` show `"pluginScope": "default"` in a `config.json` example. `schemas/config.schema.json` has `additionalProperties: false` and its property list is `[$schema, frameworkVersion, project, stacks, agents, sourceControl, commands, personaRouting, skillScope, docs, externalTools, mcpToolIndex]` — `pluginScope` is not a legal key. The same doc's prose two paragraphs later says "skill scope" correctly | ✔ loaded the schema |
| **F-27** | `docs/ai-badger-framework-design.md` describes root-`skills/` and a `plugins.json`/`marketplaces.json` feature removed in v0.7.0; `docs/index.md:48` links it with no "historical" qualifier | ✔ (reviewer) |
| **F-28** | Three planning docs still say "Ready for implementation"/"Proposed" for work shipped in v0.7.0, v0.13.0, v0.18.0 (`specs/001-…`, `design/mcp-stack-declarations.md`, `design/hermes-learned-skills-sync-impl-plan.md`) | ✔ (reviewer) |
| **F-29** | `docs/scripts.md:13-19` lists 3 of the 7 scripts in `scripts/`; `install_plugins.py`, `release_guard.py`, `sync_plugin_skills.py`, `version_sync.py` are absent | ✔ (reviewer) |
| **F-30** | `docs/index.md` omits ADR-0003 — the authoritative record for the *current* Hermes mechanism, cross-referenced by other docs but invisible from the index — plus `audit-symlink-hermes-skills.md`, `design/*`, `research/*` | ✔ (reviewer) |
| **F-31** | `scaffold.py:8-9`'s Usage synopsis omits `--overwrite-agent-files`, `--reset-seed-files`, and `--execute` (the last is behaviourally significant) | ✔ (reviewer) |
| **F-32** | `CLAUDE.md`'s "Pure-stdlib Python 3.8+" is wrong on both halves: `badger_lib.py` imports `jsonschema`, `ai_badger_hooks.py`/`mcp_index.py` import `yaml`, CI installs both — and `badger_lib.py:3` itself says "Python 3.9+" while `pyproject.toml` declares no `requires-python` | ✔ read CI + `requirements.txt` |
| **F-33** | `docs/dictionary.md` documents skill extensions as `skills/{base}-extensions/`; the real, universally-implemented convention is `<skill>/extensions/<name>/` — vocabulary drift in the anti-drift document | ✔ (reviewer) |
| **F-34** | `schemas/manifest.schema.json:24`'s *"During transition, scaffold writes both"* has outlived 11 minor versions; `scaffold.py:587-588` still writes both unconditionally | ✔ (reviewer) |
| **F-35** | Two ADRs share number 0002 (`0002-den-refresh-skill.md`, `ADR-0002-mcp-tool-index.md`), and code references ADRs by number | ✔ (reviewer) |

## Theme G — Agent-product quality (CONFIRMED; carried forward, not Wave 1)

| ID | Finding | Where |
|---|---|---|
| **F-36** | The 110-line CLAUDE.md budget is enforced only reactively at task-finish, only for `CLAUDE.md`, and only for `/task` users. `HERMES.md`/`.hermes.md` are **already 24-26 lines over** the equivalent budget with zero mechanism checking them | `tracker_lib.py:83,104`; `stop_hook.py:56-73` |
| **F-37** | Hermes' `pre_llm_call` appends a static usage-hint line **every turn**, unconditionally — the project's own `0.18.0-plugin-hook-cwd.md:29-31` already identifies this as why a bug went unnoticed | `ai_badger_hooks.py:263-266` |
| **F-38** | `personaRouting` is `[]` while `task/SKILL.md:106` Phase 2 dispatches by it, and the empty case renders as `_Default routing._` — a placeholder that reads like a policy | `.ai-badger/config.json:29`; `template_rendering.py:31-38` |
| **F-39** | `python.instructions.md` prescribes pyright + ruff to a project that deliberately uses pylint only, with a documented rationale in `pyproject.toml` | `.ai-badger/instructions/python.instructions.md:9-10` |
| **F-40** | No `copilot` extension for the `task` skill (claude 67 lines, github 93, hermes 188, copilot 0) despite copilot being a first-class agent | `features/common/skills/task/extensions/` |
| **F-41** | "TDD is mandatory" is the only non-negotiable invariant with no mechanical enforcement, while its siblings have `release_guard.py`, `version_sync.py --check`, `index_build.py --check` | `.ai-badger/invariants/tdd-mandatory.md` |
| **F-42** | `auto-wm`'s "Installing from ai-badger" section describes a user-level-only install `scaffold.py` does not perform — and the skill's own "Common mistakes" warns against exactly what its scaffolding does to itself | `auto-wm/SKILL.md`; `scaffold.py:57-65` |
| **F-43** | `maintain-agent-instructions/SKILL.md:34,40` tells the agent to run `bun` against `#!/usr/bin/env node` scripts that use only `node:fs`/`node:path` | — |
| **F-44** | `mcp-index/SKILL.md` uses unanchored `skills/mcp-index/scripts/…` paths that resolve nowhere, and carries Hermes-only frontmatter (`author: Hermes Agent`, `metadata.hermes.*`) | — |
| **F-45** | All 8 SKILL.md `description` fields summarise the workflow, the exact anti-pattern `superpowers:writing-skills` warns against; `mcp-index`'s embeds an operational *instruction* | — |
| **F-46** | ~190 duplicated lines of "offer to create a GitHub issue" boilerplate across `welcome-ai-badger`, `den-refresh`, `feed-badger` SKILL.md | — |
| **F-47** | Both `.mjs` scripts have zero tests and no JS test runner exists — a TDD-invariant violation for the only JS in the repo. Both are CI gates with regex logic that fails *open* | `maintain-agent-instructions/scripts/*.mjs` |
| **F-48** | `tests/test_mcp_index_hooks.py:233-240` asserts nothing matching its name (`assert result is not None` + two comments describing the check that was never written) | — |

---

# Rejected and downgraded claims

Recorded in full, because a rejected finding is a result. Where a reviewer's *code*
observation was right but their *impact* claim was not, the delta is named.

| Original | Verdict | Reasoning |
|---|---|---|
| security I3: *"on every later call `find_root()` runs `git pull --ff-only`"* — a self-updating code-execution channel | **REJECTED** | `find_root()` step 2 returns the cache directly whenever it has `schemas/` + `features/`, so `_ensure_framework_cache`'s pull branch is only reachable for a cache that has `.git` but lacks both. The unpinned *first clone* is real (F-09); the "updates on every run" framing is not. |
| security C6 §4: *"the machine can transition itself into auto-approve-everything with no user action"* | **REJECTED as a live path** | The chain requires `session_start_hook.py` → `poll_limit.py` → `run_auto_wm()`. `session_start_hook.py` is the only caller of `start_poll_limit_background`, and it is wired by nothing (F-07, verified against `hooks-manifest.json`, `hooks.json`, and this repo's `.claude/settings.json`). Unreachable today — **and armed the moment F-07 is fixed.** Retained as a Wave-2 ordering constraint. |
| tests C2: the `FileExistsError` in `adjust_skills.py` *"can abort the whole scaffold for unrelated agents"* | **REJECTED** | `run_adjustments` (`scaffold.py:537-539`) catches broad `Exception` per adjustment and records a note. The scaffold continues. The underlying bug is real (F-16); the escalation is not. |
| docs C3: *"every change since v0.2.0 has never shipped to any plugin consumer"* | **DOWNGRADED** | `RELEASING.md:5` states Claude Code consumers resolve by `plugin.json.version` (`0.18.1`), and Hermes consumers use `den-refresh`. Content does reach consumers. What is missing is an immutable release point and a working `release_guard` baseline (F-11). |
| security C2 framed as live RCE | **DOWNGRADED to latent** | `mcp_index_build.py` exists nowhere, so nothing executes today. The design is the defect; the broken filename is what has kept it inert. Naming this precisely matters: "fix the filename" is the *wrong* first move. |
| silent-failures C4 (`release_guard._git`) rated Critical | **DOWNGRADED to Important** | Real code path, but the guard is already unconditionally passing for an unrelated reason (F-11), verified by running it. Hardening `_git` alone changes nothing observable. |
| python C1 (`mcp_index_hook`) rated Critical purely as a broken feature | **RE-CLASSIFIED** | The functional half is Important (a feature that has never worked, so nothing regressed). The Critical part is the security shape the security reviewer found independently. Merged into F-03 with both halves stated. |
| python C2 (unguarded `import yaml`) rated Critical | **DOWNGRADED to Important** | Loud `ModuleNotFoundError`, not a silent failure; `pyyaml` is declared in `scripts/requirements.txt` and installed by CI. The real gap is the missing Prerequisites section. |
| python C3 (POSIX-only `task` skill) rated Critical | **DOWNGRADED to Important** | Nothing in the repo claims Windows support for `task`. The defect is the missing `platforms:` declaration, not a broken supported configuration. |
| ai-agent C1 (managed headers) rated Critical | **DOWNGRADED to Important** | Factually exact and verified verbatim on disk, but no automated process destroys data — the loss requires an actor to follow the wrong banner. High confidence, cheap fix, early wave; not Critical. |
| docs C2 (`pluginScope` example) rated Critical | **DOWNGRADED to Important** | Produces a **loud** `additionalProperties` schema failure, not a silent one. A copy-paste victim gets a clear error immediately. |
| python review: *"No Python 3.9+/3.10+ syntax hazards found"* | **INDEPENDENTLY RE-VERIFIED — holds** | Re-checked the three riskiest files (`mcp_index.py`'s module-level `dict[str, Any]` annotation, `poll_limit.py`'s `int \| None`, `user_prompt_hook.py`'s PEP-604 unions). All three carry `from __future__ import annotations`, so the CI matrix's Python 3.8 leg is safe. Recorded because it was worth doubting. |
| architecture's blast-radius rankings sourced from `get_impact_radius_tool` | **N/A — the reviewer already disclaimed this** | Correctly flagged as unusable (uniform "500 nodes / high"). Their hand-derived estimates are used instead, and this document's plan does the same. |

---

# Strengths worth preserving

Merged and deduplicated across all eight reviewers. **This section is load-bearing
for the remediation plan: do not refactor these.**

1. **`learned_skills_sync.py`'s security design is the best-reasoned code in the
   repo.** Five explicit gates; a containment check before `rmtree` (`:203-206`); a
   framework-owned refusal (`:137-151`); and above all the **fixed-vocabulary finding
   format** — findings carry only `{file, pattern}` with `pattern ∈ UNSAFE_LITERAL_LABELS`
   and `bool(pattern.search(text))` pinning the match to a boolean, so no scanned
   byte can escape into a log. That is the correct defence against
   `py/clear-text-logging`, and the comments explaining *why* are load-bearing.
   F-05 is a gap in one input path, **not** a failure of the design — the fix must
   preserve this shape. *(security, python, silent-failures — 3 reviewers.)*

2. **`tracker_lib.save_json:150-163` is a correct atomic write** (mkstemp in the
   destination dir + `os.replace`, cleanup on failure, re-raise), and `locked_store`
   uses `flock` for read-modify-write. This is the pattern F-23 should propagate,
   not replace. *(silent-failures, security.)*

3. **`scaffold._owns_link:106-114`** refuses to touch anything in `~/.hermes/skills/`
   that is not a symlink resolving back into the project's own skills dir — the right
   instinct for a shared user directory, with the ADR-0003 rationale recorded. This
   is the guard F-16 is missing. *(security, architecture.)*

4. **Seed-once ownership is a real architectural idea, applied consistently.**
   `_seed_once_copy` / `_stash_seed_once_skill_files` / `_restore_seed_once_skill_files`
   (`scaffold.py:261-301`) plus `_copy_with_header`'s managed-header check give a
   coherent answer to "who owns this file — framework, project, or first writer",
   which most scaffolding tools never answer at all. `_copy_with_header` preserving
   hand-authored files unless `--overwrite-agent-files` is passed is the correct
   default for a tool that writes into other people's repos.
   *(architecture, security, skills.)*

5. **`scaffolding.json` is genuinely data-driven**, and `agent_files.py:120-129`'s
   *"No hardcoded fallback — all agents are data-driven"* is an accurate docstring.
   The file-entry vocabulary (`managed`, `seedOnce`, `template`, `alsoTarget`,
   `aibCopy`, `instructionsScoped`) is a well-chosen small language. Likewise
   `detect_stacks` (`detect.py:112-126`) reads `detectionSignals` from the index with
   transitive `requires` expansion — a new file-detected stack needs zero code.
   **This is the model the other agent seams should converge on.** *(architecture.)*

6. **Provenance + tiered drift detection is well designed.** `record()`
   (`scaffold.py:226-249`) captures source, target, hash, and a cheap structural
   pre-check (`dirMeta`); `drift.py:191-201` uses the two-phase comparison correctly;
   and `drift.py:6-18` names its *accepted* limitations (renames read as removals,
   directory entries skipped) — exactly the right way to document a boundary.
   *(architecture.)*

7. **`index_build.py --check` as a pre-commit + CI gate is the right pattern for a
   generated artefact.** F-17 is not a criticism of this; it is the observation that
   the pattern was applied to one generated artefact and not the second.
   *(architecture.)*

8. **Test hygiene around `$HOME` and destructive paths is strong.** `conftest.py` is
   minimal and correct; `load_script` re-execs a fresh module so there is no
   cross-test state leakage; every production path that touches `Path.home()` **and
   is exercised** is verified monkeypatched to `tmp_path`; **no test was found that
   touches a real `$HOME`**. `tests/test_open_pr.py` and `tests/test_awm_gate.py` are
   model examples — explicit safety-invariant docstrings, plus a sanity test that
   verifies the mocking strategy itself is sufficient. Symlink edge cases for the
   hermes/scaffold path (`test_scaffold.py:338-499`) are exhaustive — and are the
   template F-16 should copy. Negative-path coverage for malformed manifests/config
   is solid. *(tests.)*

9. **Subprocess hygiene is mostly good:** argv lists, explicit `timeout=`,
   `check=False` with handled return codes, `git -C <root>` instead of `cd`. Exactly
   one `shell=True` site in the whole repo. **No hardcoded secrets anywhere**,
   including fixtures (`sk-FAKE-not-a-real-key-000`, chosen deliberately and
   documented). **No hand-rolled crypto or validation** — JSON Schema goes through
   the audited `jsonschema` library with a written rationale; hashing is stdlib
   SHA-256. *(security.)*

10. **`poll_limit.py` is exemplary daemon error handling** — every subprocess failure
    and the top-level `run_forever` catch-all go through `log()`, which both prints
    and durably appends to a file. A daemon that must never crash also never fails
    *silently*. This is the counter-example to F-13 and the pattern it should adopt.
    *(silent-failures.)*

11. **`validate.py` / `index_build.py` / `version_sync.py` have a clean
    accumulate-errors-then-exit-nonzero design** with no "print error and exit 0"
    gates. `run_adjustments` (`scaffold.py:470-539`) catches broad exceptions
    per-adjustment but *always* surfaces the failure into `self.notes` — fail soft,
    never silently. *(silent-failures.)*

12. **The `pyproject.toml` `R0801` disable carries a written rationale** explaining
    why `_bootstrap_lib()` is repeated verbatim across nine scripts (each must stay
    self-contained wherever it is copied). A deliberate trade-off with the reasoning
    recorded is not debt, and a reviewer should not flag it. *(python.)*

13. **The framework publicly corrects its own claims.**
    `docs/changelog/0.17.4-claude-lanes-factual-corrections.md` walks back specific
    economic claims from `0.17.0`, and `0.17.0`'s entry is left in place with a
    `> Superseded` note rather than silently rewritten. Likewise
    `docs/audit-symlink-hermes-skills.md` was updated in place with a dated
    `## Reconciliation` section explaining how its own prior conclusion was
    overridden. For a framework whose product is agent-facing instructions, this
    models the exact posture its `code-reviewer` persona demands of others.
    *(ai-agent, docs.)*

14. **The plugin-hook `cwd`/kwarg fix (#76) is complete and tested at the real
    integration contract.** `tests/test_hook_cwd_resolution.py` invokes each Hermes
    hook with the exact kwargs Hermes sends (no `cwd`, `user_message` not `message`),
    **including a negative control** proving the fix did not turn a dead feature into
    a noisy one. Docs and code are in lockstep with `0.18.0-plugin-hook-cwd.md`.
    *(ai-agent, docs.)*

15. **The three shipped personas are genuinely differentiated**, not flavour text —
    distinct read-only `tools:` allowlists and distinct procedural gates. The
    config-gated skill-extension mechanism (`task/extensions/{claude,github,hermes}/`)
    states its activation condition in its own first lines and resolves placeholders
    through `scaffold.py` rather than hardcoding. `prompt-markers`' start-anchored
    matching correctly defeats the classic mid-message false positive.
    `task/evals/evals.json` carries two genuine end-to-end eval scenarios.
    *(ai-agent, skills.)*

16. **Zero content drift between `features/` and both generated copies today**, and
    **zero orphaned TODO/FIXME/HACK/XXX comments** anywhere in the repo. ADR
    references live in the code that implements them (`scaffold.py:82,149,436`,
    `drift.py:4`, `ai_badger_hooks.py:44`), which is what makes the "minimal comments"
    invariant survivable. *(skills, docs, architecture.)*

---

## Final count

| | Raw | After merge | Confirmed | Partial | Rejected |
|---|---|---|---|---|---|
| Critical | 23 | 19 distinct | **7** | 4 | 0 outright (4 sub-claims rejected) |
| Important | 60 | ~34 distinct | 22 spot-checked, all held | 1 | 1 sub-claim |
| Suggestion | 37 | ~28 distinct | not individually verified | — | — |

Criticals that survive verification **as Critical**: F-01, F-02, F-03, F-04, F-05,
F-06, F-07. Criticals downgraded to Important with reasons recorded: F-08, F-09,
F-10, F-11, F-12, F-14, F-15, F-16, F-19, and the docs cluster.

Remediation: `docs/plans/2026-07-26-remediation-plan.md`.
