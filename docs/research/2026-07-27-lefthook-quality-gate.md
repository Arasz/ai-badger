# Setting up a local quality gate with lefthook

**Provenance:** supplied by the maintainer, written from a real migration (2026-07-27) that cut a
private repo's GitHub Actions bill by moving emulator-backed and browser-based suites to a
pre-push hook. Reproduced here verbatim as the reference for ai-badger's own adoption. It is a
record of another project's experience, not a description of this repo.

**Audience:** an agent or developer setting this up in another repository.
**Prerequisite reading:** none, but §1 explains *why* before §3 explains *how*. Skipping §2 will
cost you a broken repo.

---

## 1. Why do this at all

Two independent motivations. Be honest about which one applies — they lead to different designs.

**Cost.** On a private repo, Actions minutes are billed. A measured baseline before the migration:

| workflow | share of spend |
|---|---:|
| .NET build + emulator + e2e | 38% |
| frontend build/test + Playwright | 37% |
| dependency auto-submission | 13% |
| everything else | 12% |

The expensive minority is always the same shape: **jobs that need containers, emulators, or a
browser.** Those are exactly the jobs a developer machine runs faster and for free.

**Feedback latency.** A pre-push gate fails in seconds-to-minutes against a warm incremental build;
CI fails in minutes against a cold one, after you've context-switched away.

**What this does NOT buy you:** protection against a developer who bypasses the hook. Hooks are
advisory by design. Keep a real CI gate for the cheap checks, and keep a nightly for the heavy ones
(see §7).

---

## 2. Read this before running `lefthook install` — it can silently break your repo

### 2.1 An existing hook will be silently disabled

`lefthook install` **renames a conflicting hook to `<hook>.old`**, and the `.old` file never runs
again. If your repo has a `pre-commit` installed by another tool, it stops working with no error.

Check first:

```bash
ls -la .git/hooks/ | grep -v sample
```

If anything is there, you have two options:
- **Configure only hooks you don't already have** (e.g. `pre-push:` only) — safest.
- **Port the existing hook's body into a lefthook script** before installing (see §4.3).

### 2.2 `core.hooksPath` is the other way hooks die

When `core.hooksPath` is set, git reads hooks from that path **exclusively**, with no warning.
**husky sets it to `.husky/_`**, which silently kills anything in `.git/hooks`.

```bash
git config --get core.hooksPath   # empty is normal; a value means read it carefully
```

lefthook installs into `.git/hooks` and does **not** set `core.hooksPath`. That is one of the main
reasons to prefer it here.

### 2.3 Worktrees share hooks

Hooks live in the **common** git dir, not per-worktree. Installing from any linked worktree affects
every worktree, and so does `core.hooksPath` (it lives in shared config). Install once; expect it
everywhere.

### 2.4 Config must exist wherever the hook fires

The installed hook resolves `lefthook.yml` at runtime from the repo root. If you install from a
branch that has the config and then check out a branch that doesn't, pushes from that branch will
misbehave. Land the config on your default branch early.

---

## 3. Install

```bash
brew install lefthook          # or: go install github.com/evilmartians/lefthook@latest
lefthook version               # 2.1.10 at time of writing
lefthook install               # writes .git/hooks/<hook> for each configured hook
echo "lefthook-local.yml" >> .gitignore
```

`lefthook-local.yml` is an untracked per-developer override file. Add it to `.gitignore` now so
nobody commits their personal skips.

Verify what was written:

```bash
ls -la .git/hooks/ | grep -v sample
lefthook validate
```

---

## 4. The design that survives contact with reality

### 4.1 Put the logic in a script, not in `lefthook.yml`

**Do not encode your verification pipeline in the hook manager's config.** Write a single portable
script; have lefthook call it. This is the highest-value decision in the whole setup.

Why:
- The script stays runnable by hand, by CI, and by an agent — not only via `git push`.
- Swapping hook managers later becomes a config change, not a rewrite.
- Anything with real control flow (starting containers, probing ports, bounded retry, teardown)
  simply cannot be expressed in hook-manager YAML.

```
scripts/verify.sh <subcommand>

  <stack>-unit     fast tests for one stack
  <stack>-e2e      browser/emulator tests for one stack
  pre-push         orchestrator: detect changed paths, dispatch the right subset
  all              everything, no change detection
  doctor           environment + hook-integrity checks
```

Contract worth enforcing:
- `exit 0` = pass, non-zero = fail. No other exit code means anything.
- First line: `cd "$(git rev-parse --show-toplevel)"` — correct under any cwd and any worktree.
- Reads only argv and env vars. No config file of its own, no manager-specific variables.
- Every subcommand prints an entry banner and its elapsed time.

### 4.2 Minimal `lefthook.yml`

```yaml
min_version: 2.1.0
assert_lefthook_installed: true

pre-push:
  parallel: true
  jobs:
    - name: quality gate
      script: "verify.sh"
      args: pre-push
      runner: bash

pre-commit:
  jobs:
    # Anything already installed in .git/hooks must move here BEFORE `lefthook
    # install`, or it is silently renamed to .old and stops running.
    - name: existing tooling
      script: "existing-hook.sh"
      runner: bash

    - name: lint frontend
      root: "src/frontend/"          # MUST be the real path — see §5.1
      glob: "*.{js,ts,jsx,tsx}"
      run: bunx eslint --fix {staged_files}
      stage_fixed: true
```

`script:` entries resolve to `.lefthook/<hook-name>/<script>`, e.g.
`.lefthook/pre-push/verify.sh`. Make them executable (`chmod +x`).

### 4.3 Preserving a pre-existing hook

Move its body verbatim into `.lefthook/pre-commit/<name>.sh`, reference it as a `script:` job, and
verify it still fires:

```bash
lefthook run pre-commit --force --file <a real tracked file>
```

---

## 5. Bugs we actually shipped — check for these

Every one of these got committed and had to be fixed. They are cheap to avoid and expensive to
diagnose.

### 5.1 A wrong `root:` blocks every commit

`root: "frontend/"` when the real path is `src/frontend/` produces:

```
fork/exec /bin/sh: no such file or directory
```

lefthook cannot exec into a directory that doesn't exist, the job **exits 1**, and every commit
touching a matching file is blocked. It does not warn you that the path is wrong.

**Verify by running it, not by reading it:**

```bash
lefthook run pre-commit --force --file <real tracked file>; echo "EXIT=$?"
```

### 5.2 `{staged_files}` appended to a whole-project command

```yaml
run: bun run lint {staged_files}     # WRONG if the script is `eslint .`
```

If the package script is `eslint .`, this expands to `eslint . <files>` — it lints the **entire
tree** (~77s here) and the staged-file scoping does nothing. Call the tool directly:

```yaml
run: bunx eslint --fix {staged_files}   # ~2s
```

`--fix` is also what makes `stage_fixed: true` meaningful; without a fixer it is a no-op.

### 5.3 A `doctor` check that greps `.git/hooks` will cry wolf after install

If your script asserts hook integrity by grepping `.git/hooks/pre-commit` for a marker, installing
lefthook replaces that file with lefthook's dispatcher and the check reports a false failure.
Check whether a hook is **effective** — direct *or* delegated:

```bash
_hook_effective() {
  local hook_file=$1 needle=$2 delegate=$3
  [ -f "$hook_file" ] || return 1
  grep -q "$needle" "$hook_file" && return 0
  grep -q "lefthook" "$hook_file" && [ -f "$delegate" ] \
    && grep -q "$(basename "$delegate")" lefthook.yml
}
```

A doctor that cries wolf gets ignored, which costs more than the check is worth.

### 5.4 The gate must self-test

Your change-detection table almost certainly routes `.github/workflows/**` to "run everything." Add
the gate's own files for the same reason — a broken gate is invisible until something else silently
stops being verified:

```
.github/workflows/*|.lefthook/*|lefthook.yml) want_all=1 ;;
```

### 5.5 Hardcoded self-references break when the file moves

If the failure output says `reproduce: scripts/verify.sh <lane>` and the script later moves, that
line points at a path that no longer exists. Derive it:

```bash
_self_abs="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
cd "$(git rev-parse --show-toplevel)" || exit 1
readonly SELF="${_self_abs#"$PWD"/}"
```

### 5.6 macOS ships bash 3.2

If `#!/usr/bin/env bash` resolves to the system bash, then under `set -u`, `"${arr[@]}"` on an
**empty** indexed array is an unbound-variable error. No associative arrays, no `${var,,}`. Use
plain space-separated strings for list handling, or require bash 5 explicitly.

---

## 6. Change detection and escape hatches

### 6.1 Only run what the change touches

Read git's pre-push stdin protocol — four fields per line,
`<local ref> <local sha> <remote ref> <remote sha>`:

- All-zero local shas = **branch deletion** → exit 0 immediately, run nothing.
- Empty stdin = hand-invoked → fall back to
  `git diff --name-only $(git merge-base HEAD origin/main)...HEAD`.

Map changed paths to lanes; run **cheap lanes first and fail fast**, so a typo doesn't cost you
container startup.

### 6.2 Three escape hatches, all advertised in the failure output

| hatch | scope |
|---|---|
| `git push --no-verify` | git-native, skips the hook entirely |
| `SKIP_VERIFY=1 git push` | honoured *inside* the script, so it survives a manager swap |
| `VERIFY_SKIP=lane1,lane2 git push` | one bad lane (the daily "Docker isn't running" case) |

Print them in the failure block itself:

```
✗ verify:api-e2e failed (after 214s)

  reproduce:  .lefthook/pre-push/verify.sh api-e2e
  bypass:     VERIFY_SKIP=api-e2e git push        # skip this stage only
              git push --no-verify                # skip the whole gate
  logs:       /tmp/verify/api-e2e.log
```

Reproduce command, bypass command, log path. Nothing else. **A gate a developer cannot bypass in
five seconds under pressure gets uninstalled — and an uninstalled gate is silent coverage loss.**

### 6.3 Containers: probe before starting

If a lane needs an emulator or database:

1. **TCP-probe the expected ports first.** If something answers, reuse it — starting a second
   instance against a shared named volume can corrupt it.
2. Bound every readiness loop explicitly (e.g. 60 × 2s) and comment what stops it.
3. **Fail loudly when a required binary is missing** rather than letting the suite self-skip. A
   silent skip inside a gate is worse than no gate.
4. Tear down in a `trap`, and tear down **only what this run started**.

---

## 7. What to leave in CI

Moving everything local is the wrong end state. Keep:

- **A cheap, always-on gate per stack** (compile + unit tests). Fast, and it cannot be bypassed.
- **A nightly run of the heavy suites** as the automated backstop for `--no-verify` pushes.

If you gate heavy CI jobs behind a variable, put the `schedule` branch **outside** that condition:

```
github.event_name == 'schedule' || vars.HEAVY == 'true' && ...
```

Gating the safety net with the same lever that disables what it backs up is circular — it is a
single point of failure with a reassuring name.

### The required-status-check trap (GitHub)

- A job skipped by a **job-level `if:`** reports `skipped`, which **satisfies** a required check.
- A workflow skipped by **path filter** creates **no check run at all** → the required check sits at
  "Expected — waiting for status" forever → **the PR is permanently unmergeable.**

So gate *jobs*, never *triggers*. And document plainly that a gated-off required check is green
while verifying nothing — otherwise it is security theatre.

---

## 8. Verify it works — don't infer it from the config

```bash
lefthook validate                                            # config parses
lefthook run pre-commit --force --file <real file>; echo $?  # exit 0, and the job actually ran
SKIP_VERIFY=1 <script> pre-push </dev/null; echo $?          # exit 0 fast
<script> doctor                                              # environment + hook integrity
<script> bogus; echo $?                                      # non-zero, usable error
git push                                                     # the real thing, end to end
```

Two failure modes to watch for specifically:

- **A "passing" run that ran nothing.** If your probe file doesn't exist, or `{staged_files}` is
  empty, lefthook prints a green check having done zero work. Always confirm the file you passed
  actually exists and that the job reports non-trivial elapsed time.
- **A failing job that exits 0.** In bash, an `if ... fi` with no `else` returns 0 when the
  condition is false — which silently swallows a failing command's exit code. Smoke-test the
  *failure* path, not just the happy one.

Reference: a full six-lane run on the source repo took **345s** and covered 1,516 frontend unit
tests, 141 Playwright tests, 100 emulator-backed tests and 9 host-process e2e tests, with clean
teardown. That is the scale of verification this moves off the billed path.

---

## 9. Resources

**lefthook**
- Docs: https://lefthook.dev/
- Configuration reference: https://lefthook.dev/configuration/
- Repository: https://github.com/evilmartians/lefthook

**GitHub Actions cost & required checks**
- Status checks reference: https://docs.github.com/en/pull-requests/reference/status-checks
- Conditions controlling job execution:
  https://docs.github.com/en/actions/using-jobs/using-conditions-to-control-job-execution
- Contexts (where `vars.*` is and isn't available):
  https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
- Actions runner pricing (minutes round up **per job**):
  https://docs.github.com/en/billing/reference/actions-runner-pricing
- Automatic dependency submission (bills your minutes, no file in the repo):
  https://docs.github.com/en/code-security/reference/supply-chain-security/automatic-dependency-submission

**Alternatives evaluated and rejected (July 2026)**
- `act` — https://github.com/nektos/act — ignores `continue-on-error`, `timeout-minutes` and
  `concurrency`; Docker-in-Docker under Colima on Apple Silicon is an open bug (act#5967). Fine as a
  workflow-YAML debugger, not as a verification gate.
- Dagger — https://dagger.io — .NET SDK is self-declared experimental.
- Earthly — https://earthly.dev/blog/shutting-down-earthfiles-cloud/ — sunset April 2025, frozen
  since July 2025, no longer accepting PRs.
- husky — unmaintained since Nov 2024, sets `core.hooksPath` (see §2.2), no file filtering.
- pre-commit (Python) — parallelises *within* a hook but never runs distinct hooks concurrently.

---

## 10. Adoption checklist

- [ ] Audit `.git/hooks/` and `core.hooksPath` **before** installing (§2)
- [ ] `brew install lefthook`; `lefthook install`; gitignore `lefthook-local.yml`
- [ ] Write `verify.sh` with subcommands + `pre-push` + `doctor` (§4.1)
- [ ] Port any pre-existing hook into `.lefthook/` (§4.3)
- [ ] Confirm every `root:` is a real path (§5.1)
- [ ] Confirm `{staged_files}` isn't being appended to a whole-tree command (§5.2)
- [ ] Add the gate's own files to the run-everything branch of change detection (§5.4)
- [ ] Wire all three escape hatches and print them on failure (§6.2)
- [ ] Keep a cheap always-on CI gate + a nightly heavy run (§7)
- [ ] Run every check in §8, including a real `git push` and a deliberate failure

---

## Notes specific to ai-badger (added by the orchestrator, 2026-07-27)

Audited before dispatch, so the implementing agent does not have to rediscover it:

```
.git/hooks/pre-commit          633B  Python pre-commit framework dispatcher
.git/hooks/pre-commit.legacy   244B  code-review-graph (update + detect-changes)
core.hooksPath                 unset
lefthook                       2.1.10 at /opt/homebrew/bin/lefthook
```

**§2.1 applies here, doubled.** `.pre-commit-config.yaml` drives six gates through that
dispatcher, and the `.legacy` file is evidence the rename dance already happened once — the
pre-commit framework displaced code-review-graph and chains to it. lefthook renames to `.old` and
does **not** chain, so a naive install would silently kill both.

**On "run bumps before push":** a pre-push hook must not mutate the tree. By the time `pre-push`
runs, the commits and refs being pushed are fixed; bumping `VERSION` there yields a dirty working
tree plus a pushed commit lacking the bump. This repo already enforces the requirement without
mutating: `scripts/release_guard.py` fails when the shipped surface changed since the last release
tag without a `VERSION` bump. Enforcement, not auto-editing, is what makes the step unskippable.
