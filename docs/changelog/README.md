# Changelog

All notable changes to the ai-badger framework are documented here. **Each version gets its own
file, `{version}-{slug}.md`** — there is no single root `CHANGELOG.md`, and adding one is not a
refactor decision. See "Convention" below.

Because the entries are separate files, this README is the index that reconstructs the release
timeline. **The table below is generated** — run `python3 tooling/changelog_index.py` after
adding an entry and commit the result; do not hand-edit it. See
["The table is generated"](#the-table-is-generated).

## Releases, newest first

Versions follow [SemVer](https://semver.org/) as adapted for a catalog rather than an API — see
[`../../RELEASING.md`](../../RELEASING.md) and
[ADR-0001](../adr/0001-versioning-and-release-model.md). Pre-1.0, the **minor** slot is the
breaking slot. Versions listed in [`../../BREAKING_VERSIONS`](../../BREAKING_VERSIONS) require a
re-scaffold.

<!-- changelog-index:start -->
| Version | Entry |
|---|---|
| 0.61.4 | [The tracking-state guard names who wrote](0.61.4-the-guard-names-who-wrote.md) |
| 0.61.3 | [Naming the test that spawned a daemon, instead of guessing](0.61.3-naming-the-test-that-spawned-it.md) |
| 0.61.2 | [The usage-limit poller stops](0.61.2-a-poller-that-stops.md) |
| 0.61.1 | [The plugin sync can remove, so `--check` can see a surplus](0.61.1-the-plugin-sync-can-remove.md) |
| 0.61.0 | [a removed skill takes its directory with it](0.61.0-a-removed-skill-takes-its-directory.md) |
| 0.60.1 | [the docs catch up with the dispatch gate](0.60.1-the-docs-catch-up-with-the-dispatch-gate.md) |
| 0.60.0 | [delegation becomes a mechanism](0.60.0-delegation-becomes-a-mechanism.md) |
| 0.59.1 | [the banner yields line 1 to frontmatter](0.59.1-the-banner-yields-line-one-to-frontmatter.md) |
| 0.59.0 | [the aspire stack, and the MCP server the CLI already ships](0.59.0-the-aspire-stack-and-its-mcp-server.md) |
| 0.58.0 | [the review-form skill is named for what it is](0.58.0-owner-gate-review.md) |
| 0.57.0 | [usage accounting can see subagents](0.57.0-usage-accounting-can-see-subagents.md) |
| 0.56.1 | [`dir_count` is not compared when it cannot be answered](0.56.1-dir-count-is-not-compared-when-it-cannot-be-answered.md) |
| 0.56.0 | [a task records which model did the work](0.56.0-a-task-records-which-model-did-the-work.md) |
| 0.55.0 | [commit now, and say when work is at risk](0.55.0-commit-now-and-say-when-work-is-at-risk.md) |
| 0.54.4 | [the matcher answers conversational turns, and now we know how often](0.54.4-the-matcher-answers-conversational-turns.md) |
| 0.54.3 | [a test run leaves nothing behind](0.54.3-a-test-run-leaves-nothing-behind.md) |
| 0.54.2 | [a skill's exclusions stop at the skill's edge](0.54.2-exclusions-stop-at-the-skills-edge.md) |
| 0.54.1 | [review forms preserve feedback safely](0.54.1-review-form-safety.md) |
| 0.54.0 | [two skills for getting a decision out of a human](0.54.0-decision-collection-skills.md) |
| 0.53.2 | [a directory entry is hashed over the files it owns](0.53.2-dir-entry-hashes-what-it-owns.md) |
| 0.53.1 | [the query survives long enough to be a fixture](0.53.1-the-query-survives-long-enough-to-be-a-fixture.md) |
| 0.53.0 | [entry titles carry their casing and 0.51.0's build order](0.53.0-entry-titles-carry-their-meaning.md) · [fixtures people actually typed](0.53.0-fixtures-people-actually-typed.md) · [one declaration per server, per host](0.53.0-one-declaration-per-server-per-host.md) · [one frontmatter block, and the configured stacks' personas](0.53.0-one-frontmatter-block-and-the-configured-personas.md) · [personas reach Claude Code](0.53.0-personas-reach-claude-agents.md) · [the log a failing push cites tells the truth](0.53.0-the-cited-log-tells-the-truth.md) · [the index row stops being hand-written](0.53.0-the-index-row-stops-being-hand-written.md) · [the self-scaffold stops being taken on trust](0.53.0-the-self-scaffold-stops-being-taken-on-trust.md) · [the skills nobody here uses](0.53.0-the-skills-nobody-here-uses.md) |
| 0.52.1 | [curation reaches the name the host chose](0.52.1-curation-reaches-the-name-the-host-chose.md) |
| 0.52.0 | [discovery comes back, from the host that still answers](0.52.0-discovery-comes-back-from-the-host-that-answers.md) · [the manifest records what it does not own](0.52.0-the-manifest-records-what-it-does-not-own.md) |
| 0.51.2 | [one lint behaviour, not two](0.51.2-one-lint-behaviour.md) · [the skill that could not import on the floor](0.51.2-the-skill-that-could-not-import-on-the-floor.md) · [the skills tree gets its own collaborator](0.51.2-the-skills-tree-gets-its-own-collaborator.md) |
| 0.51.1 | [the observer emits when the index never heard of the server](0.51.1-the-observer-emits-on-an-unindexed-server.md) |
| 0.51.0 | [a build is not a dotnet](0.51.0-a-build-is-not-a-dotnet.md) · [MCP rebuild step 1 of 8: `mcp` becomes a catalog feature type](0.51.0-mcp-becomes-a-catalog-feature-type.md) · [`.mcp.json` stops shipping](0.51.0-mcp-json-stops-shipping.md) · [MCP rebuild step 3 of 8: one declaration set, three readers](0.51.0-one-declaration-set-three-readers.md) · [six tests that could not pass alone](0.51.0-six-tests-that-could-not-pass-alone.md) · [MCP rebuild step 6 of 8: the Claude adjuster approves, and the project can decline](0.51.0-the-claude-adjuster-approves-and-declines.md) · [MCP rebuild step 7 of 8: the file Copilot actually reads, and the two hosts that only get a proposal](0.51.0-the-file-copilot-actually-reads.md) · [MCP rebuild step 5 of 8: the index records curation, and admits when a server said nothing](0.51.0-the-index-records-curation-and-status.md) · [MCP rebuild step 8 of 8: the legacy MCP reader is gone](0.51.0-the-legacy-mcp-reader-is-gone.md) · [MCP rebuild step 4 of 8: the legacy MCP registries are deleted](0.51.0-the-legacy-mcp-registries-are-deleted.md) · [MCP rebuild step 2 of 8: the MCP catalog carries the instructions](0.51.0-the-mcp-catalog-carries-the-instructions.md) |
| 0.50.0 | [context-enrichment reaches Claude and Copilot, unconditionally](0.50.0-context-enrichment-reaches-claude-and-copilot.md) · [MCP support is configuration, not retrieval](0.50.0-mcp-support-is-configuration-not-retrieval.md) · [the stopword-count comment was wrong, and now it can't drift again](0.50.0-stopword-count-comment-was-wrong.md) · [the checkpoint hook users had to wire themselves](0.50.0-the-checkpoint-hook-users-had-to-wire-themselves.md) · [the coverage gate stops scaling with query length](0.50.0-the-coverage-gate-stops-scaling-with-query-length.md) · [the gap is answerability, not vocabulary](0.50.0-the-gap-is-answerability-not-vocabulary.md) · [what the MCP tool index is for](0.50.0-what-the-mcp-tool-index-is-for.md) |
| 0.49.0 | [a harder retrieval fixture set, and a runner to measure it](0.49.0-a-harder-retrieval-fixture-set-and-a-runner-to-measure-it.md) · [the easy fixtures were hiding the answer](0.49.0-the-easy-fixtures-were-hiding-the-answer.md) |
| 0.48.0 | [a Copilot hook event stops overwriting its neighbour](0.48.0-a-copilot-hook-event-stops-overwriting-its-neighbour.md) · [the BM25 coverage tie-break's direction is now tested](0.48.0-bm25-coverage-tie-break-direction-is-now-tested.md) · [how retrieval works, written down](0.48.0-how-retrieval-works-written-down.md) · [the MCP tool index becomes JSON, and the hook stops importing yaml](0.48.0-mcp-tools-json.md) · [the Claude hook wiring stops adopting a neighbour's script](0.48.0-the-claude-hook-wiring-stops-adopting-a-neighbours-script.md) |
| 0.47.0 | [a missing pyyaml no longer takes four hooks down with it](0.47.0-a-missing-package-stops-taking-four-hooks-with-it.md) · [Junie can finally see the skills ai-badger claimed to give it](0.47.0-junie-can-see-skills.md) · [retrieval tells you what it did, and a redact switch for the query](0.47.0-retrieval-tells-you-what-it-did.md) · [the MCP recommender ranks by BM25, and its accuracy can now fail a test](0.47.0-retrieval-that-can-fail.md) · [the scaffold detects itself](0.47.0-the-scaffold-detects-itself.md) |
| 0.46.0 | [a config edit is drift](0.46.0-a-config-edit-is-drift.md) · [an empty skill list is not an instruction](0.46.0-an-empty-skill-list-is-not-an-instruction.md) · [an invariant must be true](0.46.0-an-invariant-must-be-true.md) |
| 0.45.0 | [a project can raise the agent-doc size budget](0.45.0-agent-doc-budget-override.md) |
| 0.44.0 | [Shape D refuses to run stale plugin copies](0.44.0-shape-d-refuses-stale-copies.md) |
| 0.43.1 | [an agent is a catalog stack too](0.43.1-an-agent-is-a-catalog-stack-too.md) |
| 0.43.0 | [the delegations nothing called](0.43.0-the-delegations-nothing-called.md) |
| 0.42.0 | [drift sees a subtraction](0.42.0-drift-sees-a-subtraction.md) |
| 0.41.0 | [a record that names no project belongs to no project](0.41.0-a-record-that-names-no-project.md) |
| 0.40.0 | [drift compares the framework, and every check must prove it can fail](0.40.0-drift-compares-the-framework.md) |
| 0.39.1 | [the documentation describes the product, not the work that produced it](0.39.1-docs-describe-the-product-not-the-work.md) |
| 0.39.0 | [three trees claim to be ai-badger, and only one is ours to delete](0.39.0-three-trees-claim-to-be-ai-badger.md) |
| 0.38.0 | [an upgrade is not version skew](0.38.0-an-upgrade-is-not-version-skew.md) |
| 0.37.0 | [`scripts/` becomes `engine/` and `tooling/`](0.37.0-engine-and-tooling.md) · [`Scaffolder` stops being six mixins pretending to be one object](0.37.0-scaffolder-collaborators.md) |
| 0.36.2 | [the four repo gates move to `gates/`](0.36.2-the-gates-move-out-of-scripts.md) |
| 0.36.1 | [stack-local skill discovery](0.36.1-stack-local-skill-discovery.md) |
| 0.36.0 | [a project can decline a framework artifact](0.36.0-a-project-can-decline-an-artifact.md) · [an explicit debug sink, beneath the `$HOME` floor](0.36.0-an-explicit-debug-sink.md) |
| 0.35.6 | [the framework cache reports its own version skew](0.35.6-the-cache-reports-its-own-skew.md) |
| 0.35.5 | [the test suite cannot reach the real audit log](0.35.5-the-suite-cannot-reach-the-real-log.md) |
| 0.35.4 | [the behaviorist stops inventing failures](0.35.4-behaviorist-stops-inventing-failures.md) |
| 0.35.3 | [an untagged release fails the guard instead of mentioning it](0.35.3-an-untagged-release-fails-the-guard.md) |
| 0.35.2 | [test isolation fix for prompt-markers debug-log tests](0.35.2-test-isolation-fix.md) |
| 0.35.1 | [all hooks instrumented with debug_log](0.35.1-all-hooks-instrumented.md) |
| 0.35.0 | [lefthook summary logging](0.35.0-lefthook-summary-logging.md) |
| 0.34.1 | [a hook never breaks a session, and a gate that says so before you push](0.34.1-a-hook-never-breaks-a-session.md) |
| 0.34.0 | [skills that arrive, and one definition of "framework root"](0.34.0-skills-that-arrive-and-a-root-that-agrees.md) |
| 0.33.0 | [ai-badger no longer installs a plugin that intercepts every tool call](0.33.0-no-third-party-tool-call-interception.md) |
| 0.32.0 | [four defects a real refresh found, and the waves that landed with them](0.32.0-defects-found-by-a-real-refresh.md) |
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
| 0.18.0 | [Hermes learned-skills sync (hook wiring)](0.18.0-hermes-learned-skills-hook.md) · [Hermes learned-skills sync (core module)](0.18.0-hermes-learned-skills-sync.md) · [plugin hooks: resolve cwd, read Hermes' kwarg names](0.18.0-plugin-hook-cwd.md) · [reverse #58: restore Hermes skill discovery](0.18.0-reverse-58-hermes-skill-discovery.md) |
| 0.17.4 | [factual corrections to the Claude model lanes](0.17.4-claude-lanes-factual-corrections.md) |
| 0.17.3 | [an optional embeddings dependency is detected, never installed](0.17.3-optional-embeddings-dependency.md) |
| 0.17.2 | [project-scoped skills only](0.17.2-project-scoped-skills.md) |
| 0.17.1 | [pylint hook + drift hash fix](0.17.1-pylint-hook-drift-fix.md) |
| 0.17.0 | [Claude model lanes for the `task` skill](0.17.0-claude-model-lanes.md) |
| 0.16.1 | [drift stops false-flagging config-gated extensions, and a pylint cleanup](0.16.1-drift-hash-fix.md) |
| 0.16.0 | [plugin skill discovery restored, and a stack-ignore list](0.16.0-plugin-skill-discovery.md) |
| 0.15.1 | [error recovery and GH issue creation for scaffold skills](0.15.1-error-recovery-gh-issues.md) |
| 0.15.0 | [feature dependencies are checked and installed at scaffold time](0.15.0-dependency-check.md) |
| 0.14.1 | [scaffold.py domain module split](0.14.1-scaffold-domain-module-split.md) |
| 0.14.0 | [external tools are scaffolded from the catalog](0.14.0-external-tools-catalog.md) |
| 0.13.1 | [scaffold re-runs stop appending duplicate hooks](0.13.1-hook-dedup-fix.md) |
| 0.13.0 | [stack MCP server declarations](0.13.0-stack-mcp-declarations.md) |
| 0.12.0 | [new stack detection in den-refresh](0.12.0-new-stack-detection.md) |
| 0.11.1 | [MCP index text parsing + tool indexing](0.11.1-mcp-index-text-parsing.md) |
| 0.11.0 | [external MCP tool integration](0.11.0-external-mcp-tools.md) |
| 0.10.2 | [known-gaps cleanup](0.10.2-known-gaps-cleanup.md) |
| 0.10.1 | [config-gated inline extensions](0.10.1-config-gated-inline-extensions.md) |
| 0.10.0 | [directory-content hash drift detection](0.10.0-dir-hash-drift-detection.md) |
| 0.9.4 | [fix adjust_task.py absolute path in record()](0.9.4-fix-adjust-task-path.md) |
| 0.9.3 | [commit-based drift detection for skills](0.9.3-commit-drift-detection.md) |
| 0.9.2 | [den-refresh version sync without drift](0.9.2-refresh-version-sync-fix.md) |
| 0.9.1 | [GitHub fallback for framework root discovery](0.9.1-github-fallback-framework-root.md) |
| 0.9.0 | [adjustment execution, Copilot support via adjustments](0.9.0-hook-wiring-execute-copilot.md) |
| 0.8.0 | [tier 2 drift: new items detection](0.8.0-tier2-drift-new-items.md) |
| 0.7.2 | [move auto-wm to the Claude stack](0.7.2-move-auto-wm-to-claude.md) |
| 0.7.1 | [Hermes `external_dirs` registration + den-refresh config update](0.7.1-hermes-external-dirs.md) — *this mechanism was later reverted; see [ADR-0003](../adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md)* |
| 0.7.0 | [skills sources, hooks, and adjustments](0.7.0-skills-hooks-adjustments.md) · [work summary: skills sources, hooks, and adjustments](0.7.0-work-summary.md) |
<!-- changelog-index:end -->

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
2. Add a `docs/changelog/{version}-{slug}.md` entry whose first line is a `# ` title, then run
   `python3 tooling/changelog_index.py` to put it in the table above.
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

### The table is generated

The entry *files* deliver the conflict avoidance the convention is for; the index row did not.
Every PR riding one unreleased version edited the same table line, so N concurrent PRs cost N−1
hand-resolved conflicts on it — five in one session — and a careless resolution dropped an entry
without any gate noticing (issue #160). So the table is no longer written by hand:

- `python3 tooling/changelog_index.py` regenerates the region between the
  `<!-- changelog-index:start -->` / `<!-- changelog-index:end -->` markers. Everything outside
  them, including this prose, is yours.
- `python3 tooling/changelog_index.py --check` fails when the committed table does not match the
  files on disk. It runs in pre-commit, in the lefthook `docs` lane and in CI, so a missing row
  is now a red build rather than a silent omission.
- **Titles come from the entry's `# ` heading**, with a leading `{version} —` stripped (the
  Version column already carries it). Retitle the entry, regenerate, and the index follows.
- **Ordering:** versions semver-descending; several entries at one version join with ` · ` in
  filename order. Filename rather than commit date so a row is a function of the tree alone —
  two branches that both add an entry produce the same row whichever lands first.
- A row annotation goes in the entry, not the table: a single
  `<!-- index-note: … -->` line is rendered after that entry's link as ` — *…*`.
  0.7.1's revert notice is the one in use.

A concurrent-PR conflict on the table line is still possible, but it is no longer resolved by
hand: take either side, re-run the generator, and `--check` proves the result.

### Writing a good entry

Look at [0.25.0](0.25.0-hardening.md) or [0.24.0](0.24.0-outbound-scan.md) for the house style: a
title that states the change rather than naming the module, a link back to the plan or review that
motivated it, one section per fix explaining what was wrong *before*, and an explicit
"behaviour changes worth knowing" section for anything a consumer must act on.
