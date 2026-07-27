# Contributing to ai-badger

Thanks for looking. This is a small project — one maintainer, no committee — so the process is
short, but the gates are real and CI enforces them. Read this once and you will not be surprised
by a red build.

If something here does not match what the repository actually does, that is a bug in this file.
Open an issue.

## First time here?

You do not need to understand the whole framework to make a useful change. Good first
contributions:

- A fix to a `features/…/*.md` catalog file (a persona, an invariant, an instruction).
- A missing test for behaviour that already works.
- A documentation correction — especially one that names a file path that no longer exists.

Two things to know before you start, because they shape everything below:

1. **Write the failing test first.** This is not aspirational; a CI gate checks that a code change
   touched tests.
2. **A `git push` is not a release.** Releases are a separate, deliberate step. See
   [`RELEASING.md`](RELEASING.md).

## Setup

Python **3.8+** (CI runs 3.8, 3.9 and 3.10) and Node (for the two `.mjs` gate scripts).

```bash
git clone https://github.com/Arasz/ai-badger
cd ai-badger
python3 -m venv .venv
.venv/bin/python3 -m pip install -r scripts/requirements.txt -r scripts/requirements-dev.txt
.venv/bin/python3 -m pip install pytest
```

`scripts/requirements.txt` carries the runtime dependencies and `scripts/requirements-dev.txt`
carries `pylint`; `pytest` is not pinned in either, so install it separately (CI installs
`pylint pytest jsonschema pyyaml` explicitly).

**Use `.venv/bin/python3` for everything below.** Depending on your machine the system `python3`
may be a version with no pytest installed; every command in this file assumes the venv
interpreter.

Runtime dependencies are deliberately minimal, and the two behave differently on purpose:

- **`jsonschema` is required.** `scripts/badger_lib.py` imports it unguarded. Validation that
  silently no-ops is worse than a missing dependency — an unvalidated config would sail straight
  into the scaffolder — so it fails loudly instead.
- **`pyyaml` is optional.** It is imported behind a guard and degrades to a printed note
  (`mcp_index.YAML_MISSING_HINT`), because the features needing it are not on the critical path.

Everything else is standard library. **Do not add a third runtime dependency without a very good
reason**; if you must, decide deliberately which of these two shapes it takes and say so here.
`scripts/deps_guard.py` enforces the declaration half of that rule: it parses every `*.py` under
`scripts/` and `features/` and fails on a third-party import — including one hidden inside a
function or a `try:` block — that `scripts/requirements.txt` does not declare.

Optionally install the pre-commit hooks, which run six of the gates locally:

```bash
.venv/bin/python3 -m pip install pre-commit
pre-commit install
```

They are `version-sync`, `index-build`, `plugin-skills-sync`, `docs-guard`, `deps-guard`, and
`pylint` — see
[`.pre-commit-config.yaml`](.pre-commit-config.yaml).

Separately, lefthook runs **every** gate on `git push`. That one is worth installing — it is what
stops an unbumped `VERSION` or a failing test from reaching CI. See
[Automating the gates](#automating-the-gates-lefthook).

## How the repository is laid out

```
features/{stack|common}/{feature}/   the catalog — skills, personas, invariants, instructions,
                                     hooks, adjustments, templates
scripts/                             mechanical Python: index_build, validate, version_sync,
                                     release_guard, tdd_guard, docs_guard, deps_guard,
                                     sync_plugin_skills, badger_lib
schemas/                             a JSON Schema per *.json model
index.json                           SCRIPT-GENERATED. Never hand-edit it.
tests/                               pytest; tests/js/ holds the node --test suites
docs/                                see docs/index.md
```

[`docs/framework-architecture.md`](docs/framework-architecture.md) explains the model,
[`docs/authoring-a-feature.md`](docs/authoring-a-feature.md) is the how-to for adding a catalog
entry, and [`docs/scripts.md`](docs/scripts.md) covers running the scripts.

## The workflow

### 1. Branch. Never push to `main`.

```bash
git checkout -b task/short-description
```

**One task, one PR.** Do not bundle unrelated work into a single change — it makes review and
rollback lose their scope.

The single exception: **the maintainer may ask for a change to be merged locally**, skipping the
PR. That is their call and nobody else's — if you are contributing, or you are an agent working
in this repo, assume the rule is absolute unless you were told otherwise for that specific
change. The exception drops the PR, never the gates: everything in
[step 6](#6-run-every-gate-before-you-ask-for-review) still has to pass before the push, because
the PR was the record, not the safety net.

### 2. Write the failing test first

TDD is a non-negotiable invariant in [`CLAUDE.md`](CLAUDE.md). No production code without a test
that demanded it.

```bash
.venv/bin/python3 -m pytest tests/test_the_thing.py -q   # red
# ...implement...
.venv/bin/python3 -m pytest -q                           # green
```

`scripts/tdd_guard.py` checks the one thing a machine can: that a change to `.py` or `.mjs` under
`scripts/` or `features/` came with a change to a test file. It is a signal, not a proof — it
cannot tell a real test from an empty one, so passing it is not the point; writing the test first
is.

There is an escape hatch — `[no-tests]` in a commit message in the range — and it is **printed in
CI output**, so an unjustified one is visible rather than silent. Use it only for changes that
genuinely cannot be tested, and say why in the PR body.

Catalog JSON is covered by `validate.py --all` and documentation by review, so neither counts as
code for this gate.

### 3. Commit small, push often, open a draft PR early

Open a **draft PR from your first commit** so the work is visible in flight rather than arriving
as one large diff at the end.

### 4. Re-scaffold if you touched the scaffolder

`skills/` and `.ai-badger/` hold copies of catalog content that go stale. After touching
`scripts/` or `features/common/skills/welcome-ai-badger/`, regenerate them or
`sync_plugin_skills --check` and pylint will fail:

```bash
.venv/bin/python3 scripts/sync_plugin_skills.py
.venv/bin/python3 features/common/skills/welcome-ai-badger/scripts/scaffold.py \
    --config .ai-badger/config.json --target . --root .
```

`index.json` is likewise generated — run `.venv/bin/python3 scripts/index_build.py` after adding
or removing a catalog entry, and commit the result. Never edit it by hand.

### 5. Decide whether this is a release

Run the release guard. It compares the shipped surface (`features/`, `scripts/`, `schemas/`,
`index.json`, `skills/`) against the **last release tag** — not the previous commit:

```bash
.venv/bin/python3 scripts/release_guard.py
```

- **It passes and reports no shipped-surface change** (docs-only, tests-only): do *not* bump
  `VERSION`, do *not* add a changelog entry.
- **It fails**: your change ships. Then, per the invariant in [`CLAUDE.md`](CLAUDE.md):
  1. Bump [`VERSION`](VERSION) — patch for fixes, minor for anything that changes what
     scaffolding *does* to a consumer repo. Pre-1.0, the minor slot is the breaking slot.
  2. Add `docs/changelog/{version}-{slug}.md` describing what changed. **One file per version —
     this repo does not keep a single root `CHANGELOG.md`.** See
     [`docs/changelog/README.md`](docs/changelog/README.md).
  3. Add the version to [`BREAKING_VERSIONS`](BREAKING_VERSIONS) if a re-scaffold is *required*,
     not merely recommended.
  4. `.venv/bin/python3 scripts/version_sync.py` — propagates the version into `plugin.json`,
     `marketplace.json` and `index.json`.

Full detail, including the semver-for-a-catalog rules, is in [`RELEASING.md`](RELEASING.md).

### 6. Run every gate before you ask for review

One command runs all of them:

```bash
.lefthook/pre-push/verify.sh all
```

That is the same script the pre-push hook runs — see
[Automating the gates](#automating-the-gates-lefthook) below. To run them by hand instead, or to
see what each one does, these are exactly what CI runs (`.github/workflows/pylint.yml`), so a
green local run means a green build:

```bash
.venv/bin/python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')   # 10.00 required
.venv/bin/python3 -m pytest -q
.venv/bin/python3 scripts/index_build.py --check
.venv/bin/python3 scripts/sync_plugin_skills.py --check
.venv/bin/python3 scripts/validate.py --all
.venv/bin/python3 scripts/version_sync.py --check
.venv/bin/python3 scripts/docs_guard.py
.venv/bin/python3 scripts/deps_guard.py
.venv/bin/python3 scripts/release_guard.py
.venv/bin/python3 scripts/tdd_guard.py --base origin/main
node --test "tests/js/*.test.mjs"
```

What each one is for:

| Gate | Fails when |
|---|---|
| `pylint` | Anything below 10.00 on non-test Python. Tests keep their own conventions and are excluded. |
| `pytest -q` | Any test fails. |
| `index_build.py --check` | `index.json` does not match the catalog on disk. |
| `sync_plugin_skills.py --check` | The shipped `skills/` copy has drifted from `features/`. |
| `validate.py --all` | Any catalog JSON violates its schema in `schemas/`. |
| `version_sync.py --check` | `plugin.json`, `marketplace.json` or `index.json` disagree with `VERSION`. |
| `docs_guard.py` | A relative link or a backticked repo path in the docs no longer resolves, or a changelog entry is missing from `docs/changelog/README.md`. |
| `deps_guard.py` | Code imports a third-party module that `scripts/requirements.txt` does not declare. |
| `release_guard.py` | The shipped surface changed since the last release tag without a `VERSION` bump. |
| `tdd_guard.py` | Code changed and no test changed with it. Runs on branches, not on `main`. |
| `node --test` | A `.mjs` gate script's tests fail. |

**CodeQL** also runs on every pull request and is a required check before merge.

### Automating the gates (lefthook)

[`lefthook.yml`](lefthook.yml) wires the gates to `pre-push`, so the checks above cannot be
skipped by forgetting them. Install it once:

```bash
brew install lefthook   # or: go install github.com/evilmartians/lefthook@latest
lefthook install
.lefthook/pre-push/verify.sh doctor
```

`doctor` reports the interpreter it resolved, whether `pytest`/`pylint`/`jsonschema` import, and
whether the hooks are intact. Run it first when the gate behaves oddly.

All the logic is in [`.lefthook/pre-push/verify.sh`](.lefthook/pre-push/verify.sh), not in the
YAML, so it stays runnable by hand, in CI and by an agent:

| Command | Does |
|---|---|
| `verify.sh all` | Every lane, no change detection. |
| `verify.sh pre-push` | Only the lanes the pushed commits can affect. |
| `verify.sh lanes` | Prints what `pre-push` would run, without running it. |
| `verify.sh <lane>` | One lane — `pytest`, `pylint`, `docs`, `release`, `tdd`, `js`, … |
| `verify.sh doctor` | Environment and hook integrity. |

Only `pre-push` is wired. `pre-commit` deliberately stays with the pre-commit framework: it
already runs six of these gates and chains to code-review-graph, and `lefthook install` renames
a hook it conflicts with to `.old` and never runs it again. Configuring both would silently kill
that chain.

**It verifies; it never edits.** A pre-push hook must not mutate the tree — by the time it runs,
the commits being pushed are already fixed, so bumping `VERSION` there would leave a dirty
working tree and push a commit without the bump. `release_guard.py` is what makes the bump
unskippable: it fails the push until you bump `VERSION` yourself. Do that in a commit, per
[step 5](#5-decide-whether-this-is-a-release).

When a lane fails it prints how to reproduce it, where the log is, and how to bypass it:

```
VERIFY_SKIP=pytest git push   # skip one lane
SKIP_VERIFY=1 git push        # skip every lane
git push --no-verify          # skip the hook entirely
```

Use them when a lane is broken for reasons unrelated to your change, and say so in the PR — CI
still runs every gate, so a bypassed push fails there instead. Per-developer overrides go in
`lefthook-local.yml`, which is gitignored.

### 7. Open the PR

State in the body:

- What was red before you implemented, and what is green now.
- **Any pre-existing test you rewrote to a new contract, by name.** A rewritten test is a changed
  promise; it must be visible in review rather than buried in the diff.
- Whether this is a release (and if so, which version and which changelog file).
- Anything you deliberately did not do, and why.

Then wait for CI. Do not merge with a red build.

### 8. After merge — tag, if you released

**This step is the release**, and it is easy to forget because a green PR looks finished without
it. From `main`:

```bash
claude plugin tag --push     # creates ai-badger--v{version}
```

Until that runs, the version denotes no commit and `release_guard.py` still compares against the
*previous* tag — which silently disables the guard. That is exactly how this project accumulated
a 32-release gap; the post-mortem is
[`docs/incidents/2026-07-27-untagged-releases.md`](docs/incidents/2026-07-27-untagged-releases.md).
Never skip a tag.

Then verify the release shipped by checking **content**, not the CLI's own output — see the
mandatory verification section in [`RELEASING.md`](RELEASING.md).

## Conventions worth knowing

The full list of non-negotiable invariants is in [`CLAUDE.md`](CLAUDE.md). The ones that most
often surprise a new contributor:

- **Screaming architecture.** Name folders and modules after the domain concept, not the
  technical bucket. No catch-all `Services/`, `Controllers/`, `Utils/`. A shared technical
  chassis (logging, DI wiring, cross-cutting middleware) is the one accepted exception.
- **Guard clauses over hand-rolled null checks.** Fail fast at the boundary with a dedicated
  guard helper, so the exception type and message stay consistent.
- **Minimal comments.** A doc comment is 1–3 lines stating the contract. Put the "why" in an ADR
  or a spec document and point at it. Test doc comments are one sentence or none — the test name
  and body carry the intent.
- **No hardcoded secrets**, anywhere, including examples and fixtures. Sample values must be
  obviously fake.
- **No hand-rolled crypto or security orchestration.** Delegate to an audited library.

Scoped instructions live in `.ai-badger/instructions/` — read
`python.instructions.md`, `javascript.instructions.md`, or `documentation.instructions.md`
before editing files of that kind.

## Architecture decisions

Decisions that would otherwise get re-litigated are recorded as ADRs in
[`docs/adr/`](docs/adr/README.md), numbered, MADR-shaped, and **never edited after acceptance** —
a decision that changes gets a *new* ADR that supersedes the old one.

If your change reverses or constrains a recorded decision, add the ADR in the same PR.

## What is in scope

**Wanted:** catalog content that is genuinely project-agnostic; new stack support; tests; bug
fixes with a failing test; documentation that names real file paths.

**Not wanted:** project-specific content dressed up as a framework feature (if it only makes
sense in your repo, keep it in your repo — that is what `.ai-badger/`'s seed-once files are
for); a third runtime dependency; hand-edited `index.json`; changes to `docs/adr/` entries that
have already been accepted.

**Ask first** (open an issue before writing code): anything that changes the scaffold output
shape, a schema, or a hook contract — those are minor-version, blast-radius changes.

## Security

Do not open a public issue for a security problem. See [`SECURITY.md`](SECURITY.md).

## Code of conduct

Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
