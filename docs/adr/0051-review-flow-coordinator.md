# ADR-0051 — A typed review flow: one coordinator, one-shot workers, scripts move the state

**Date:** 2026-11-18
**Status:** Proposed (2026-11-18)
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code
**Extends:** —
**Research:** `docs/work/2026-11-18-code-review-coordinator-flow-research.md`; task plan `aib-code-review-coordinator-flow-model` (task tracking, not committed). The owner settled storage, rule activation, publishing and scope on 2026-11-18. This record writes those decisions down; it does not re-open them.

## Context

The framework has many review skills (`code-review` router, `review-changes`,
`code-review-checklist`, `review-tests`, `code-review-evidence`,
`complete-project-scope-code-review`). All of them are prose. No script in the repository posts
an inline review comment, a review or a summary comment. The task skill's GitHub review loop is
also prose only (research §1.6).

The owner wants one PR review flow with these properties:

- One coordinator agent. Every unit of judgement is a one-shot worker.
- The flow state is strongly typed and stored in the ai-badger database, like task-graph.
- A script does all work that a script can check.
- Replies to review comments teach review rules, and the next round applies them.
- A global-scope pass re-judges each finding against facts about the whole system.
- The flow works in limited execution mode (no hooks).

Four existing severity vocabularies disagree (research §1.4), and no "learned rule",
`DEFENSIVE` tag or global-scope concept exists.

## Decision

1. **Skill.** A new common skill `review-flow` at `features/common/skills/review-flow/`, scope
   `default`. It reuses the existing review skills, personas and MCP tools through a `Tools`
   section that the coordinator fills on first use. It does not replace the `code-review`
   router.

2. **Phase machine.** Each round moves through these phases, in this order:
   `context -> change_model -> lanes -> integrate -> global_scope -> result -> published ->
   awaiting_author -> reply_analysis`, then a new round or `closed`. The `lanes` phase runs four
   lanes in parallel: `business`, `qa`, `architecture`, `quality`. Each lane has a `LaneRun`
   (`pending | done | failed`). A failed lane forbids the verdict "Safe to merge". The phase
   lives on `Round`. The verdict is derived from effective severities and failed lanes. It is
   never stored, except frozen in the round's `round-N.json` result file. The `submit` command
   is the only path that moves state. Every move goes through a declared transition table and
   is recorded in `ReviewFlow.history` with the round number.

3. **Script versus worker.** A script owns every step that has a checkable answer. A worker
   owns judgement and returns JSON that a script validates before `submit` accepts it.

   | Step | Script | Worker |
   |---|---|---|
   | Fetch PR, diff, files, threads, replies | yes | — |
   | Load and validate `rules.json` from the base ref; compute rule conflicts | yes | — |
   | Find ACs (tool, pasted, absent) | records the source | reads the tool output or the paste |
   | Change model (semantic summary of the change) | validates the shape | writes it |
   | Lane review (business, qa, architecture, quality) | validates findings, recomputes fingerprints | finds issues |
   | Integrate (merge duplicates across lanes) | dedups by fingerprint, merges `lanes` | judges near-duplicates |
   | Global scope (facts and rules applied to findings) | applies `require`/`suppress`/`downgrade` effects | proposes a `Disposition` with basis refs |
   | Verdict, rendering of inline and summary bodies | yes | — |
   | Publish, edit in place, resolve threads | yes | — |
   | Reply analysis (proposed rules from replies) | validates `LearnedRule`, checks author association | proposes the rule |
   | Rule activation by citation | verifies the cited code exists at the base ref | — |

4. **Storage split.** Flow state lives in `tracking.db` in a new `review_flows` table. The table
   is created with `CREATE TABLE IF NOT EXISTS` in `_DDL`. There is no `SCHEMA_VERSION` bump.
   Precedent: `engine/badger_store.py:331-334` adds `test_economy` the same way, because a bump
   makes every older copy refuse the database (`engine/badger_store.py:496-504` raises when the
   stored version is newer than the code). An extra table is invisible to older code.
   Learned rules and project facts live in a committed file, `.ai-badger/review/rules.json`,
   validated by the `RulesFile` model. The flow always loads it from the PR base ref,
   never from the PR head, so a PR cannot change the rules that review it. `Round.rules_digest` pins
   the sha of the file that the round used.

5. **Rule lifecycle.** A rule starts `proposed`. It becomes `active` by one of three paths:
   - a maintainer confirms it (`activated_by: maintainer`);
   - a script-verified code citation (`activated_by: citation`): the script checks that the
     cited code exists at the base ref;
   - 2 or more independent threads (`activated_by: threads`): independent means
     distinct thread ids by distinct authors.
   Only replies from authors whose association is `OWNER`, `MEMBER` or `COLLABORATOR` can teach a
   rule. Rule and fact ids are monotonic (`R-n`, `F-n`), never reused, and a rule is retired,
   never deleted. Two active rules conflict when their kinds intersect, their path globs
   overlap, and one is `require` while the other is `suppress` or `downgrade`. The conflict is
   computed at load and both rules are excluded from the lanes.

6. **Severity.** One closed enum, ordered: `blocker | major | minor | nit`. The five existing
   source vocabularies map to it:

   | Source | Vocabulary | Mapping |
   |---|---|---|
   | `code-review-checklist` (`SKILL.md:45`) | Critical / High / Medium / Low | blocker / major / minor / nit |
   | `complete-project-scope-code-review` lane brief (`references/lane-brief.md:60`) | BLOCKER / HIGH / MEDIUM / LOW / NIT | blocker / major / minor / nit / nit |
   | `design-gate-audit` (`SKILL.md:43`) | MUST-FIX / SHOULD-FIX / NIT | blocker / major / nit |
   | `review-gate-diff-verification` (`SKILL.md:57`) | MUST-FIX / SHOULD-FIX / NIT | blocker / major / nit |
   | `review-tests` | blocker / major / minor | blocker / major / minor |

7. **Rule and fact grammar.** `Applies{kinds, paths, symbols}` plus
   `Effect{action: require | suppress | downgrade, to, ground}` is the whole predicate grammar.
   It is a conjunction with fnmatch globs and no expressions. `Kind` is a closed enum; `other`
   is never matched by a rule or a fact. A finding's `Disposition` is a discriminated union
   `Keep | Downgrade | Drop`. `Downgrade` and `Drop` carry a closed `Ground`
   (`fact_contradicts | unreachable_in_production | rule | duplicate | out_of_scope`) and at
   least one basis ref to a fact or a rule. **DEFENSIVE rule:** ground
   `unreachable_in_production` requires the `DEFENSIVE` tag on the finding, and its effect must
   be `downgrade`. **Fingerprint:** `sha256(kind|path|symbol)`, or the sha256 of the JSON
   array `[kind, path, symbol, anchor]` when the finding sets `Location.anchor` (so a `|` inside
   a field cannot make two findings collide), recomputed by the validator; a worker cannot
   supply its own. `symbol` is required, with `<module>` as the
   fallback. `anchor` is optional: the offending code text, whitespace-normalised and cut to 200
   characters. It keeps two defects in one function apart, and because it is code text rather
   than a line number or a title, it survives a line shift and a reworded title.
   `Finding.lanes` is a list of every lane that raised the finding.

8. **Publishing.** Publish posts its inline findings as one review whose event is always
   `COMMENT`; a round with no inline findings updates only the summary comment. The flow never
   approves and never requests changes.
   - Inline comment: a human part of at most 4 lines (reason and severity), then a collapsed
     `<details>` agent block (reproduction path, wider context, proposed fix). The renderer
     refuses a longer human part; it never truncates.
   - Summary: one issue comment per PR, found by its marker and edited in place each round. It
     shows the verdict, the last update and the reviewed head sha. Details are collapsed.
   - Findings outside the diff go into the summary, not inline.
   - Three markers identify our objects: `finding` (inline comment), `summary` (the summary
     comment) and `resolved` (our reply on a thread we resolve, so a re-run after a failed
     resolve does not reply twice).

9. **Security.**
   - A marker counts only on a comment authored by the authenticated `gh api user` login.
   - Untrusted text (PR body, issue, reply, rule statement) enters a worker brief only inside a
     delimited, length-capped data block.
   - Publish always passes the flow's repo explicitly. It refuses when the cwd remote does not
     match that repo, or when the PR head moved since the round started.
   - A thread is resolved only when its anchored lines changed in the new head, or a worker
     submitted verified-fixed. Otherwise the thread is labelled "not re-reported".

10. **Limited environments.** v1 is CLI only, with no MCP server in v1. The CLI is a PEP 723
    script. Launch order: `uv run --script`; if `uv` is absent, `python3` when `pydantic`
    imports; else exit 3 with a message. Without `gh`, publish runs as a dry run and writes the
    rendered bodies to the result directory.

11. **Acceptance criteria source.** Jira is read only through a tool found in the `Tools`
    section. Without such a tool, the coordinator uses ACs the user pasted. Without either, the
    flow records `ac_source: absent` and the summary says "AC source absent".

## GitHub API surface

The publisher and fetcher use only these calls. Each line was checked against the cited page on
2026-11-18.

- `GET /repos/{owner}/{repo}/pulls/{pull_number}` — PR head sha, base ref; diff via media type `application/vnd.github.diff` — https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` — changed files and patches — https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files
- `GET /repos/{owner}/{repo}/pulls/{pull_number}/comments` — existing review comments, to find our markers — https://docs.github.com/en/rest/pulls/comments#list-review-comments-on-a-pull-request
- `PATCH /repos/{owner}/{repo}/pulls/comments/{comment_id}` — edit our own inline comment — https://docs.github.com/en/rest/pulls/comments#update-a-review-comment-for-a-pull-request
- `POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies` — reply in a thread — https://docs.github.com/en/rest/pulls/comments#create-a-reply-for-a-review-comment
- `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` with `commit_id`, `event` (`COMMENT` only; the API also accepts `APPROVE`, `REQUEST_CHANGES`), `body`, `comments[]` of `path`, `line`, `side`, `body` — https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request
- `GET /repos/{owner}/{repo}/issues/{issue_number}/comments` — find the summary by marker — https://docs.github.com/en/rest/issues/comments#list-issue-comments
- `POST /repos/{owner}/{repo}/issues/{issue_number}/comments` — first summary — https://docs.github.com/en/rest/issues/comments#create-an-issue-comment
- `PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}` — edit the summary in place — https://docs.github.com/en/rest/issues/comments#update-an-issue-comment
- `GET /user` — authenticated login (`login` is a required response field) for marker ownership — https://docs.github.com/en/rest/users/users#get-the-authenticated-user
- GraphQL `PullRequest.reviewThreads` → `PullRequestReviewThread{id, isResolved, comments}` → `PullRequestReviewComment{author, authorAssociation, fullDatabaseId, body, url, createdAt}` (`body` to find the marker, the thread root's `url` for a rule's thread origin, `createdAt` for the reply time) — https://docs.github.com/en/graphql/reference/pulls
- GraphQL `PullRequestReviewComment.fullDatabaseId` (`BigInt`, sent as a JSON string) replaces `databaseId`, which is deprecated because it does not support 64-bit ids — MEASURED 2026-11-18 by schema introspection (`__type(name: "PullRequestReviewComment")`, `includeDeprecated: true`) and a live query that returned the value as a string — https://docs.github.com/en/graphql/reference/objects#pullrequestreviewcomment
- GraphQL mutation `resolveReviewThread(input: {threadId})` returning `thread` — https://docs.github.com/en/graphql/reference/pulls

## Consequences

- Positive: review state is typed and replayable; a round's result file freezes what was
  published. Tests can drive the whole machine through the CLI without GitHub.
- Positive: rules that change review behaviour go through a committed file and normal PR review.
  A PR cannot weaken its own review.
- Positive: one severity enum ends the four-way vocabulary drift for this flow.
- Negative: a new model, transition table, store adapter, renderer and publisher to maintain.
  The CLI duplicates part of the task-graph pattern instead of sharing code with it.
- Negative: the thread-to-REST-comment join depends on GraphQL `fullDatabaseId` matching the
  REST comment id.
- Neutral: no MCP server in v1, so agents call the CLI. An MCP twin can come later without a
  model change.
- Neutral: cut from v1: Jira adapter code, committable suggestion blocks, auto-polling,
  non-GitHub publishing, cross-project rule sharing.

## Alternatives rejected

- **Reuse task-graph for the flow.** Rejected. A task plan is a DAG of steps with ACs and
  evidence. A review flow is a cyclic round machine with findings, dispositions and replies.
  Forcing it into a plan DAG would weaken both models.
- **Bump `SCHEMA_VERSION` for the new table.** Rejected. `engine/badger_store.py:496-504` makes
  an older copy refuse a database whose stored version is newer. The precedent at
  `engine/badger_store.py:331-334` adds a table with `CREATE TABLE IF NOT EXISTS` and no bump.
- **A separate `review.db`.** Rejected. A second database adds a second path resolver, a second
  lock and a second backup story for one table.
- **An MCP server in v1.** Rejected. The CLI works in limited environments where an MCP server
  may not run (research §2.4, UNVERIFIED there). A server can wrap the same `invoke_tool` later.
- **Rules from the PR head.** Rejected. The PR under review could then rewrite its own rules.
