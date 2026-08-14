# complete-project-scope-code-review extension: claude

This is a **config-gated extension** of the base skill, not a standalone skill. The base names
lanes and roles; this binds them to Claude's dispatch mechanics.

**Activates when:** `.ai-badger/config.json` lists `claude` in `agents`.

## @stack: claude: which model runs which lane

The base skill's lanes split cleanly into two cost tiers, and the split is the largest lever in a
campaign this size.

- **High-reasoning lane (Opus).** Architecture, the domain-algorithm lane, the adversarial
  verification pass, the plan and both plan reviews, and arbitration when two lanes disagree about
  a fact. Anything whose value is in the reasoning rather than the reading. Dispatch with
  `model: "opus"` and prefix the call's `description` with `"Opus: "` so the lane is visible in
  the agent panel.
- **Survey lane (Sonnet).** Language-quality, data-access, QA and consumer-surface lanes; the
  implementation of an already-decided work package; test backfills against pre-derived
  expectations. Pass `model: "sonnet"` explicitly rather than relying on the session default.
- **Mechanical (Haiku).** Doc touch-ups, inventory greps, liveness checks.

Do not assume the orchestrating session is already the reasoning lane — the default model for new
sessions changes. Get it by dispatching with an explicit `model` override.

The seven-lane session this skill comes from ran three Opus lanes and four Sonnet lanes, plus an
Opus adversarial pass. The adversarial pass is the one to never economise on: it refuted or
corrected six claims that would otherwise have driven implementation.

## @stack: claude: isolation, and the hazards that travel with it

Every lane gets **its own worktree** and **its own workspace id** in any shared notes or memory
store. Use the Agent tool's own isolation rather than creating worktrees by hand — a manual step
before each dispatch is the one that gets skipped when the work feels urgent. Two things travel
with a new worktree and are easy to forget:

- **Arm any per-directory permission or auto-approval mode for the new path**, or the lane stalls
  waiting for an answer nobody is there to give. In a long autonomous campaign this looks exactly
  like a lane that found nothing.
- **The gate is re-run on the merged result.** Each lane's green measured a different tree.

**Push after every commit.** This is the concrete form of the base skill's stalled-lane hazard: a
lane's work exists only in its worktree until it is pushed, so the integrating side sees an absent
branch and concludes the lane produced nothing. It is also how work is lost when a draft PR is
squash-merged from outside the session.

**Two levels of dispatch, no deeper.** A lane may dispatch once; nothing below that. A tree that
widens without bound starves the work already running, and lane failures at depth three are
invisible.

## @stack: claude: reading a lane's real output

Subagent transcripts are written beside the session's, not inside it, at
`<transcript-dir>/<session-id>/subagents/agent-<id>.jsonl` with a paired `agent-<id>.meta.json`
naming `agentType`, `description`, `spawnDepth` and `model`. Read them when a lane's summary looks
truncated or when you need its actual model rather than the agent panel's — the panel's per-task
`model` field comes from an async live-status feed and can lag the transcript's `resolvedModel`.
The transcript is ground truth.

Judge a finished campaign by its **model mix** over the main transcript *and* its subagents
together, not by cache efficiency, which does not discriminate. A campaign whose dispatches are
mostly `general-purpose` is not routing to the project's personas whatever the config says.

**Keep always-loaded context byte-stable during the campaign.** Every lane's request prefix
includes `CLAUDE.md` and the project's state file; rewriting them mid-campaign turns every
subsequent lane's cache read into a fresh write. Update them between phases, not during one.

## @stack: claude: the review documents are the artefact

A campaign this long outlives its session. Write the integrated review, the plan and its revisions
into the project's docs tree as you go, and put the integration reasoning into merge commit
messages rather than into chat. The chat is not recoverable; the commits are. When the campaign
resumes in a new session — or in a `/compact`ed one — those files are what re-establishes context
in one read.
