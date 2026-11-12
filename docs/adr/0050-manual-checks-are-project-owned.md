# ADR-0050 — Manual checks belong to the project; the checklist skill is generic

**Date:** 2026-11-12
**Status:** Proposed
**Author:** Rafał Araszkiewicz (Arasz) with Claude Code
**Extends:** —
**Research:** task plan `aib-generic-manual-checklist-project-checks` (task tracking, not committed) and its owner gate, whose answers are recorded under Decision

## Context

The only manual checklist in the framework is `features/ai-raccoon/skills/ai-raccoon-manual-checklist`.
Its rules for honest manual checks fit any project: record the evidence, derive facts and never pin
them, write checks that can fail, never inherit an earlier verdict. Its 44 items, its fact
script and its embedding stub fit only AiRaccoon.

The project's checks live in the template inside the skill directory. On every refresh the scaffolder
deletes and re-copies that directory (`skill_delivery.py` `scaffold_skills`). So a project that
changes its own checks loses the change at the next den-refresh. This has already happened:
AiRaccoon lost 18 items and had to restore them from git. Each change to a project check also
needs a framework release. And no other project can use the skill.

The checks that agents perform by hand are also partly mechanical. Agents count facts, make sure
every item has a command and evidence, and add up statuses. Agents do this badly, and a script
does it reliably.

## Decision

1. The framework ships one generic skill, `run-manual-checklist`, in `features/common/skills/`
   with `scope: optIn`. It holds only the general rules and the procedure.
2. Each project owns its checks file in its own tree, outside `.ai-badger/`. The default is
   `docs/checklist/checks.json`. The skill requires the path as input and refuses to run
   without it. The one exception is `init`: the agent reads the project, writes the first
   checks file and runs `check` on it until it passes. `init` is an agent procedure, not a
   script command.
3. A checks file declares:
   - `results-dir`: where filled runs go.
   - `rules`: the project's "never" rules, as prose for the agent.
   - `facts`: commands whose output a run compares against.
   - `items`: each with an `anchor` to the document that defines the behaviour.
4. `scripts/checklist.py` (stdlib only) does the mechanical work:
   - `check` validates a checks file.
   - `new-run` writes a dated run file. It fills the git metadata, runs every fact command and
     fails loudly when a command errors or prints nothing or zero.
   - `report` validates a filled run and prints the counts, every fail and the pending
     acceptances.

   Judgement stays with the agent: which items to write, what counts as evidence, and how to
   make an item able to fail.
5. The AiRaccoon items and scripts move to the ai-raccoon repository. The `ai-raccoon` stack
   then has no content, so it is deleted.

## Alternatives

- **Keep a skill per project in the framework.** Rejected. Every change to a check needs a
  framework release, and a refresh overwrites local edits.
- **Seed the checks file once inside the skill directory (`SEED_ONCE_SKILL_FILES`).** Rejected.
  The file survives a refresh, but it stays hidden under `.ai-badger/`. It becomes a second
  framework-managed exception, and the decisions a project's checks depend on live in the
  project's docs, not there.
- **A script that generates `init`.** Rejected. A skeleton invites placeholder items that pass
  against nothing. Writing items that can fail is the agent's job.

## Consequences

- Positive: a project changes its checks in its own PR. A refresh never touches them. Any
  project can opt in.
- Positive: run completeness and fact derivation are checked by code with tests. They are no
  longer judged by eye.
- Negative: this is a breaking scaffold change (a minor bump before 1.0). The old skill is
  pruned from consumers by the catalog-missing path in `superseded_prune.py`. A consumer that
  depended on it must add a checks file and opt in to `run-manual-checklist`.
- Negative: a project now owns its own fact scripts. AiRaccoon keeps its C# tool counter as a
  project script.
