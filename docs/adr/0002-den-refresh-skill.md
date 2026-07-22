# ADR-0002 — den-refresh: the framework-update skill

**Status:** Proposed (2026-07-22)

## Context

ai-badger currently has two operational skills:

- **welcome-ai-badger** — initial scaffold of a target repo (detect → config → scaffold)
- **feed-badger** — harvest project improvements back into the framework (detect_additions → classify → PR)

There is no dedicated skill for the third direction: pulling framework updates *into* a project
that was already scaffolded. The welcome-ai-badger SKILL.md documents an "Upgrading a scaffolded
project" section that describes re-running `scaffold.py` with the existing `config.json`. This
works mechanically — `scaffold.py` is idempotent — but it conflates two concerns inside one skill:

1. Initial onboarding (discovery, agent-authored config, plugin scope choice)
2. Ongoing maintenance (drift detection, re-scaffold, diff review)

A user who wants to update their project should not need to read through the onboarding flow
to find the upgrade path, and an agent executing the update should not re-detect stacks or
re-prompt for config that already exists.

The drift detection infrastructure already exists (ADR-0001 decision 5): `drift.py` for Tier 2
per-entry hash comparison, and the SessionStart hook for Tier 1 version mismatch notices. What's
missing is the skill that wires drift detection + re-scaffold into a single agent-executable flow.

## Decision

### 1. Create `den-refresh` as a third installable operational skill

The name follows the ai-badger theme: the badger's "den" is the framework repo, and "refresh"
describes pulling updates from it into a project. It lives at the repo-root `skills/den-refresh/`
alongside `welcome-ai-badger`, `feed-badger`, `task`, etc.

### 2. den-refresh is responsible for the full update flow

```
1. Verify prerequisites (config.json, manifest.json exist; framework checkout accessible)
2. Run drift.py → report what changed upstream
3. Re-scaffold using existing config.json (no re-detection, no re-authoring)
4. Report: what was refreshed, what was preserved (seed-once files), what needs review
5. Present the diff; the agent helps the user review it
```

The mechanical script is a thin orchestrator that calls the existing `drift.py` and `scaffold.py`
with the project's existing `config.json`. It adds:
- Prerequisite verification (does the project have config.json? Is it valid?)
- A summary report that merges drift output + scaffold notes
- Exit codes that the agent can branch on (0 = up to date, 1 = changes applied, 2 = error)

The agent's creative role is minimal: present the diff, note any seed-once files that were
preserved, and ask whether the user wants to commit. There is no config authoring, no stack
detection, no plugin scope prompt — those belong to `welcome-ai-badger`.

### 3. Reduce welcome-ai-badger's scope

The "Upgrading a scaffolded project" section moves from welcome-ai-badger's SKILL.md to
den-refresh's SKILL.md. welcome-ai-badger's SKILL.md gains a pointer: "Already scaffolded? Use
den-refresh to pull framework updates."

This keeps welcome-ai-badger focused on initial onboarding and makes the update path
discoverable as its own skill.

### 4. den-refresh preserves the script-vs-agent split

**Script (mechanical):**
- `skills/den-refresh/scripts/refresh.py` — orchestrator that:
  1. Validates prerequisites (config.json exists, manifest.json exists, framework root reachable)
  2. Runs `drift.py` to report what changed upstream
  3. Runs `scaffold.py --config <existing> --target . --root <framework>` to re-scaffold
  4. Merges drift output + scaffold notes into a structured JSON report

**Agent (creative only):**
- Present the report to the user
- Help review the diff (what changed, what stayed the same)
- Offer to commit or discard

### 5. The script is intentionally thin

`refresh.py` does not duplicate `drift.py` or `scaffold.py`. It calls them as subprocesses
(or imports their functions) and composes their output. A thin orchestrator is the right
abstraction: the individual pieces (drift, scaffold) remain independently testable, and the
orchestrator's added value is prerequisite checking + structured reporting.

## Consequences

**Good.** The three skills now map cleanly to the three directions of the framework:

| Direction | Skill | What it does |
|-----------|-------|--------------|
| Framework → project (initial) | welcome-ai-badger | Detect, config, scaffold |
| Framework → project (update) | den-refresh | Drift, re-scaffold, diff review |
| Project → framework | feed-badger | Detect additions, classify, PR |

Users discover the right skill by intent rather than by scanning one large skill document.
Agents executing the update flow don't re-run detection or re-prompt for config.

**Costs.** Three skills to maintain instead of two. The cost is low because `refresh.py` is
thin and delegates to existing scripts.

**Deferred.** The agent role in den-refresh (diff review) could eventually be automated with
a structured change classification (breaking / additive / cosmetic), but for now the agent's
help in presenting the diff and asking the user is the right level of automation.

**Rejected.** Merging drift detection into `scaffold.py` itself (making scaffold always check
drift first). This would couple two concerns that are useful independently — `drift.py` is
run explicitly as a pre-flight check before re-scaffolding, and making scaffold always check
adds overhead to every initial scaffold that doesn't need it.
