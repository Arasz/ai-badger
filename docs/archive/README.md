# Archive — dated point-in-time records

Documents here were **true when written and are not maintained**. They are kept because deleting
a record destroys the reasoning behind it, but nothing in this directory should be read as a
description of how ai-badger works today.

Every file carries a header naming the date and framework version it was written against, and
what has since superseded it. Filenames are prefixed with that date.

For the current state, read [`../index.md`](../index.md).

| Document | Written against | Superseded by |
|---|---|---|
| [2026-07-24-known-gaps.md](2026-07-24-known-gaps.md) | 0.10.1 · 2026-07-24 | [`../reviews/2026-07-26-full-project-review.md`](../reviews/2026-07-26-full-project-review.md) and [`../plans/2026-07-27-deferred-work-plan.md`](../plans/2026-07-27-deferred-work-plan.md), which track the gap surface now |
| [2026-07-26-codebase-analysis-report.md](2026-07-26-codebase-analysis-report.md) | 0.14.1 · commit `7d9c767` | Nothing directly — it is a graph snapshot. Regenerate rather than read the numbers. |
| [2026-07-24-feature-support-by-agent-update.md](2026-07-24-feature-support-by-agent-update.md) | 0.9.0 · 2026-07-24 | `features/common/support.json`, which is the machine-readable source of truth for per-agent support |

## What belongs here

- A snapshot whose *numbers* have moved on (graph metrics, file counts, line references).
- A gap list or status page that a later, better-maintained document now covers.
- An editorial note written for a specific external publication.

## What does not

- **ADRs** (`../adr/`) — never edited, never archived; a decision that changes gets a new ADR
  that supersedes the old one.
- **Changelog entries** (`../changelog/`) — historical by construction, and the release timeline
  needs them all in one place.
- **Reviews and incidents** (`../reviews/`, `../incidents/`) — already dated by filename, and
  still cited by live plans.
- **Design records and specs** (`../design/`, `../specs/`) — these describe work that shipped and
  remain the explanation of *why* the code looks the way it does. They carry a status header
  instead.
