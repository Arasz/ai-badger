# Security policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report privately through GitHub's [private vulnerability reporting][pvr] — the
**Security → Report a vulnerability** tab on this repository. That channel is preferred because
it keeps the report, the fix, and the advisory in one place.

If private reporting is unavailable to you, email **araszkiewiczrafal@gmail.com** with
`ai-badger security` in the subject.

[pvr]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability

### What to include

- What an attacker can do, and what they need in order to do it (a hostile catalog entry? a
  hand-edited `.ai-badger/config.json`? a malicious target repo?).
- The affected file and, where possible, a failing test or a reproduction command.
- The version — `VERSION` at the repo root, or `frameworkVersion` in the target repo's
  `.ai-badger/manifest.json`.

### What to expect

This is a **one-maintainer project**. There is no on-call rotation and no guaranteed response
time. Realistically: acknowledgement within a week, and a fix released as a normal version bump
with a `docs/changelog/` entry describing it. If a report needs coordinated disclosure, say so
and the advisory stays private until a fixed version is tagged.

## Supported versions

Only the **latest tagged release** is supported. Releases are tagged `ai-badger--v{version}`;
the baseline restarts at `ai-badger--v0.20.0` (versions `0.3.0`–`0.19.0` carry no tag and never
will — see [`RELEASING.md`](RELEASING.md)).

Fixes ship forward. There are no backports to older minors.

## What this project actually is, security-wise

ai-badger is a **local code generator**. There is no server, no hosted service, and no account.
The scripts read a catalog from this repository and write files into a target repository and, for
some agents, into the user's home directory. So the honest threat model is:

| Surface | What it does | Who controls the input |
|---|---|---|
| `welcome-ai-badger` / `den-refresh` scaffolding | Writes `.ai-badger/`, agent-discovery files (`CLAUDE.md`, `.github/copilot-instructions.md`, `.junie/AGENTS.md`, `HERMES.md`), and merges into `.claude/settings.json` / `.mcp.json` | The framework catalog plus the user's own `.ai-badger/config.json` |
| Hermes skill discovery | Creates symlinks under `~/.hermes/skills/<project>/` and copies hook plugins into `~/.hermes/plugins/` | Same |
| Skill / dependency installation | Can run `pip`, `npm`, and plugin-install commands | Catalog templates; **opt-in only**, see below |
| `feed-badger` | Takes content *out* of a private repo and puts it in a public draft PR | The user's repo |
| Hooks | Run in the agent's process on session start, prompt submit, and tool calls | Catalog scripts, plus project files they read |

**The dangerous direction is outbound and side-effecting**, not inbound parsing. A vulnerability
report that lands hardest here is one where scaffolding writes outside the target repo, executes
something the user did not approve, or publishes something the user did not intend to publish.

### Hardening already in place

These are the measures that exist today, so a report can build on them rather than restate them.
Each links to the release that introduced it.

From [0.24.0 — outbound scan](docs/changelog/0.24.0-outbound-scan.md):

- `feed-badger`'s `open_pr.py` scans every declared path for credential-shaped literals **before**
  running any git command, and exits non-zero on a finding. The matched text is never logged —
  findings carry only `{file, pattern}` with `pattern` from a closed vocabulary.
- `git add -A` was removed. Contributions are staged from an explicit, required, repeatable
  `--path`, so unrelated dirty files in the checkout cannot be published by accident.
- The scanner is one module (`engine/unsafe_literals.py`) used by both the inbound
  learned-skills path and the outbound PR path.

From [0.25.0 — the hardening pass](docs/changelog/0.25.0-hardening.md):

- **No shell.** Install commands are argv lists, not strings passed to `shell=True`. The command
  *template* is tokenised before substitution, so a value containing a space or `;` stays one
  argument.
- **No silent installs.** `run_dependency_check` reports what *would* be installed and where;
  `--execute` opts in. This is why 0.25.0 is in `BREAKING_VERSIONS`.
- **ReDoS caps.** The two `.mjs` gate scripts refuse patterns over 500 characters and files over
  1 MB, and report the refusal through the normal error path.
- **User-scope state is owner-only.** `~/.claude/awm/state.json`, `decisions.jsonl`, and the
  prompt-marker state are `0600` (directory `0700`); the decision log is capped at 5,000 lines.
  The `call-behaviorist` audit log at `~/.ai-badger/debug/` gets the same treatment and the same
  cap — it records project paths, session ids and working directories, so it says where someone
  works and what ran, and it logs no tool input and no prompt text at all.
- **Path containment is asserted, not assumed.** `project.name` cannot escape
  `~/.hermes/skills/<name>`, and a manifest `target` cannot steer the drift hasher out of the
  project (an absolute right-hand side no longer wins the `pathlib` join).

Structural properties that predate those waves:

- **Root resolution never touches the network** by default —
  `badger_lib.ensure_root(allow_network=…)` is an explicit opt-in, asserted by
  `tests/test_find_root_never_touches_the_network`.
- **Writes are atomic** — `badger_lib.atomic_write_text` uses `os.replace`, and a failed scaffold
  leaves a detectable `manifest.json.partial` marker rather than a half-written manifest.
- **Destructive writes are guarded** — a scaffold refuses to clobber files it does not own:
  unparseable `.claude/settings.json` aborts rather than being overwritten, a foreign entry in
  the Hermes namespace is never removed, and skills containing symlinks are refused on sync.
- **No hand-rolled crypto and no hardcoded secrets** — both are non-negotiable invariants in
  [`CLAUDE.md`](CLAUDE.md), enforced by review rather than by a scanner.

### Automated checks

- **CodeQL** runs on every push to `main`, every pull request, and weekly
  (`.github/workflows/codeql.yml`).
- **Dependabot** watches `engine/requirements.txt` and the GitHub Actions used by the workflows,
  weekly (`.github/dependabot.yml`).
- **gitleaks** scans the commit range on every push to **any** branch and every pull request, and the
  whole history weekly (`.github/workflows/secret-scan.yml`). Findings are redacted: this
  repository is public, so an unredacted report would publish the credential it just caught.
- **`deps_guard.py`** fails the build on a third-party import that
  `engine/requirements.txt` does not declare — in pre-commit and on all three CI Python
  versions.
- The runtime dependency surface is deliberately tiny: **`jsonschema` and `pyyaml`**. Everything
  else is Python 3.8+ stdlib. Their imports differ on purpose — `jsonschema` is required and
  imported unguarded, because a guarded import would let validation silently pass when it is
  absent; `pyyaml` is optional and guarded, degrading to a printed note.

There is still no secret-scanning **pre-commit** hook. That is now a decision rather than an
omission, and both candidates were looked at:

- **gitleaks as a local hook.** `.pre-commit-config.yaml` is deliberately one `local` repo of
  `language: system` hooks with no third-party dependency. Adding gitleaks there puts a
  downloaded binary or a Go toolchain on every contributor's machine and in every commit — the
  trade CI can make and a commit hook cannot, which is why
  [`.github/workflows/secret-scan.yml`](.github/workflows/secret-scan.yml) uses the Action and
  stops there.
- **`engine/unsafe_literals.py` as a local hook.** It is offline and stdlib-only, but it is a
  five-pattern guard on content *leaving* a repository, not a history scanner — a different
  door on purpose. It also matches a tracked file on a deliberately fake fixture value
  ([`tests/test_learned_skills_sync.py`](tests/test_learned_skills_sync.py)), so it would ship
  with a permanent exception from its first run. A permanently-baselined scanner is
  theatre, and a five-pattern one advertised as secret scanning is worse than none: it buys
  false confidence.

So, stated plainly: **a credential can be committed locally, and is caught when the branch is
pushed to `main` or opened as a pull request** — not on the push of a topic branch that is
neither. Closing that last window is a matter of widening the CI trigger, not of adding a local
hook.

## Out of scope

- Vulnerabilities in the coding agents themselves (Claude Code, GitHub Copilot, JetBrains Junie,
  Hermes Agent) — report those to their vendors.
- Vulnerabilities in bundled **external** MCP tools such as
  [code-review-graph](https://github.com/tirth8205/code-review-graph) — report upstream. What *is*
  in scope here is how ai-badger declares, merges, or installs them.
- The fact that scaffolding writes files into your repository and home directory. That is the
  product. A report that it writes somewhere it should not is very much in scope.
- Anything requiring you to already have write access to this repository's catalog or to the
  user's machine.
