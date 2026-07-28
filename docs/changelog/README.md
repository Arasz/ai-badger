# Changelog

All notable changes to the ai-badger framework are documented here. **Each version gets its own
file, `{version}-{slug}.md`** — there is no single root `CHANGELOG.md`, and adding one is not a
refactor decision. See "Convention" below.

Because the entries are separate files, this README is the index that reconstructs the release
timeline. Keep it current when you add an entry.

## Releases, newest first

Versions follow [SemVer](https://semver.org/) as adapted for a catalog rather than an API — see
[`../../RELEASING.md`](../../RELEASING.md) and
[ADR-0001](../adr/0001-versioning-and-release-model.md). Pre-1.0, the **minor** slot is the
breaking slot. Versions listed in [`../../BREAKING_VERSIONS`](../../BREAKING_VERSIONS) require a
re-scaffold.

| Version | Entry |
|---|---|
| 0.38.0 | [an upgrade is not version skew](0.38.0-an-upgrade-is-not-version-skew.md) |
| 0.37.0 | [`scripts/` becomes `engine/` and `tooling/`](0.37.0-engine-and-tooling.md) · [Scaffolder's mixins become collaborators](0.37.0-scaffolder-collaborators.md) |
| 0.36.2 | [the four repo gates move to `gates/`](0.36.2-the-gates-move-out-of-scripts.md) |
| 0.36.1 | [stack-local skill discovery](0.36.1-stack-local-skill-discovery.md) |
| 0.36.0 | [a project can decline a framework artifact](0.36.0-a-project-can-decline-an-artifact.md) · [an explicit debug sink](0.36.0-an-explicit-debug-sink.md) |
| 0.35.6 | [the framework cache reports its own version skew](0.35.6-the-cache-reports-its-own-skew.md) |
| 0.35.5 | [the test suite cannot reach the real audit log](0.35.5-the-suite-cannot-reach-the-real-log.md) |
| 0.35.4 | [the behaviorist stops inventing failures](0.35.4-behaviorist-stops-inventing-failures.md) |
| 0.35.3 | [an untagged release fails the guard](0.35.3-an-untagged-release-fails-the-guard.md) |
| 0.35.2 | [test isolation fix for prompt-markers debug-log tests](0.35.2-test-isolation-fix.md) |
| 0.35.1 | [all hooks instrumented with debug_log](0.35.1-all-hooks-instrumented.md) |
| 0.35.0 | [lefthook summary logging](0.35.0-lefthook-summary-logging.md) |
| 0.34.1 | [a hook never breaks a session](0.34.1-a-hook-never-breaks-a-session.md) |
| 0.34.0 | [skills that arrive, and a root that agrees](0.34.0-skills-that-arrive-and-a-root-that-agrees.md) |
| 0.33.0 | [no third-party tool-call interception by default](0.33.0-no-third-party-tool-call-interception.md) |
| 0.32.0 | [four defects a real refresh found](0.32.0-defects-found-by-a-real-refresh.md) |
| 0.31.1 | [orchestration files load their instructions](0.31.1-orchestration-files-load-their-instructions.md) |
| 0.31.0 | [a health report built from evidence](0.31.0-a-health-report-from-evidence.md) |
| 0.30.0 | [see what the framework actually did](0.30.0-see-what-the-framework-did.md) |
| 0.29.1 | [the PR rule has a named exception](0.29.1-pr-rule-has-a-named-exception.md) |
| 0.29.0 | [documentation that still points at the tree](0.29.0-docs-that-stay-true.md) |
| 0.28.3 | [the onboarding commands actually run](0.28.3-onboarding-commands-that-run.md) |
| 0.28.2 | [config.json says which version wrote it](0.28.2-config-says-which-version-wrote-it.md) |
| 0.28.1 | [plugin hooks load again](0.28.1-plugin-hooks-load-again.md) |
| 0.28.0 | [MCP servers that never started](0.28.0-mcp-user-tool-paths.md) |
| 0.27.1 | [task tracking actually runs](0.27.1-task-tracking-actually-runs.md) |
| 0.27.0 | [one way to extend a skill](0.27.0-one-extension-mechanism.md) |
| 0.26.0 | [the default skill set has one home](0.26.0-default-skill-set.md) |
| 0.25.0 | [the hardening pass](0.25.0-hardening.md) |
| 0.24.0 | [the path that publishes now checks what it publishes](0.24.0-outbound-scan.md) |
| 0.23.0 | [skill engineering, and the JavaScript that had no tests](0.23.0-skill-engineering-and-the-js-gap.md) |
| 0.22.0 | [portability, and documentation that matches the code](0.22.0-portability-and-truth.md) |
| 0.21.0 | [a gate that cannot fail is not a gate](0.21.0-gates-and-atomicity.md) |
| 0.20.0 | [shipped features are actually shipped](0.20.0-inert-features-activated.md) |
| 0.19.0 | [no command destroys state it did not create](0.19.0-destructive-write-guards.md) |
| 0.18.1 | [smaller agent files, one document outline](0.18.1-agent-file-size-and-outline.md) |
| 0.18.0 | [Hermes learned-skills sync — core module](0.18.0-hermes-learned-skills-sync.md) · [hook wiring](0.18.0-hermes-learned-skills-hook.md) · [reverse #58: restore Hermes skill discovery](0.18.0-reverse-58-hermes-skill-discovery.md) · [plugin hooks: resolve cwd](0.18.0-plugin-hook-cwd.md) |
| 0.17.4 | [factual corrections to the Claude model lanes](0.17.4-claude-lanes-factual-corrections.md) |
| 0.17.3 | [optional embeddings dependency](0.17.3-optional-embeddings-dependency.md) |
| 0.17.2 | [project-scoped skills only](0.17.2-project-scoped-skills.md) |
| 0.17.1 | [pylint hook + drift hash fix](0.17.1-pylint-hook-drift-fix.md) |
| 0.17.0 | [Claude model lanes for the `task` skill](0.17.0-claude-model-lanes.md) |
| 0.16.1 | [drift-hash fix + pylint cleanup](0.16.1-drift-hash-fix.md) |
| 0.16.0 | [plugin-skill discovery + stack-ignore](0.16.0-plugin-skill-discovery.md) |
| 0.15.1 | [error recovery and GH issue creation for scaffold skills](0.15.1-error-recovery-gh-issues.md) |
| 0.15.0 | [dependency check](0.15.0-dependency-check.md) |
| 0.14.1 | [`scaffold.py` domain module split](0.14.1-scaffold-domain-module-split.md) |
| 0.14.0 | [external-tools catalog](0.14.0-external-tools-catalog.md) |
| 0.13.1 | [hook dedup fix](0.13.1-hook-dedup-fix.md) |
| 0.13.0 | [stack MCP server declarations](0.13.0-stack-mcp-declarations.md) |
| 0.12.0 | [new stack detection in den-refresh](0.12.0-new-stack-detection.md) |
| 0.11.1 | [MCP index text parsing + tool indexing](0.11.1-mcp-index-text-parsing.md) |
| 0.11.0 | [external MCP tool integration](0.11.0-external-mcp-tools.md) |
| 0.10.2 | [known-gaps cleanup](0.10.2-known-gaps-cleanup.md) |
| 0.10.1 | [config-gated inline extensions](0.10.1-config-gated-inline-extensions.md) |
| 0.10.0 | [directory-content hash drift detection](0.10.0-dir-hash-drift-detection.md) |
| 0.9.4 | [fix `adjust_task.py` absolute path in `record()`](0.9.4-fix-adjust-task-path.md) |
| 0.9.3 | [commit-based drift detection for skills](0.9.3-commit-drift-detection.md) |
| 0.9.2 | [den-refresh version sync without drift](0.9.2-refresh-version-sync-fix.md) |
| 0.9.1 | [GitHub fallback for framework-root discovery](0.9.1-github-fallback-framework-root.md) |
| 0.9.0 | [adjustment execution, Copilot support via adjustments](0.9.0-hook-wiring-execute-copilot.md) |
| 0.8.0 | [tier 2 drift: new-items detection](0.8.0-tier2-drift-new-items.md) |
| 0.7.2 | [move auto-wm to the Claude stack](0.7.2-move-auto-wm-to-claude.md) |
| 0.7.1 | [Hermes `external_dirs` registration + den-refresh config update](0.7.1-hermes-external-dirs.md) — *this mechanism was later reverted; see [ADR-0003](../adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md)* |
| 0.7.0 | [skills sources, hooks, and adjustments](0.7.0-skills-hooks-adjustments.md) · [work summary](0.7.0-work-summary.md) |

Releases before 0.7.0 predate this directory.

**A version may have more than one entry.** `release_guard.py` compares against the last release
*tag*, not the previous commit, so several PRs can land at one unreleased version — 0.18.0 has
four. Tag once when the set is complete.

**Not every version here is tagged.** `0.3.0`–`0.19.0` carry no tag and never will; the baseline
restarts at `ai-badger--v0.20.0`. The post-mortem is
[`../incidents/2026-07-27-untagged-releases.md`](../incidents/2026-07-27-untagged-releases.md).

## Convention

Every release must:

1. Bump [`VERSION`](../../VERSION) — patch for fixes, minor for anything that changes what
   scaffolding *does* to a consumer repo.
2. Add a `docs/changelog/{version}-{slug}.md` entry, and a row to the table above.
3. Add the version to [`BREAKING_VERSIONS`](../../BREAKING_VERSIONS) if a re-scaffold is
   *required*, not merely recommended.
4. Run `python3 tooling/version_sync.py` to propagate the version into `plugin.json`,
   `marketplace.json` and `index.json`.

Whether a change *is* a release is decided by `gates/release_guard.py`, not by judgement: if it
reports no shipped-surface change since the last release tag, do not bump and do not add an entry.

### Why one file per version

This is a minority convention — the dominant one is a single
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) file at the repo root, and per-file
changelogs exist mainly to avoid merge conflicts on one growing file, a pressure that a
one-maintainer project does not feel. It is nevertheless a **non-negotiable invariant** in
[`CLAUDE.md`](../../CLAUDE.md), and changing it is a maintainer decision rather than a
housekeeping one. The tradeoff — a per-version file buys room for real prose about *why*, and
costs you this index — is recorded here so nobody has to rediscover it.

### Writing a good entry

Look at [0.25.0](0.25.0-hardening.md) or [0.24.0](0.24.0-outbound-scan.md) for the house style: a
title that states the change rather than naming the module, a link back to the plan or review that
motivated it, one section per fix explaining what was wrong *before*, and an explicit
"behaviour changes worth knowing" section for anything a consumer must act on.
