# ADR-0036: Reuse or register the project id with ai-raccoon

**Date:** 2026-10-04
**Status:** Accepted (2026-10-04, targeting 0.188.0; see `docs/changelog/0.188.0-project-id-registered-with-ai-raccoon.md`).
**Author:** Rafał Araszkiewicz (Arasz) with pi (task `aib-mint-project-id-from-raccoon`)
**Scope:** `features/common/skills/welcome-ai-badger/scripts/{project_id,scaffold}.py`,
`features/common/skills/den-refresh/scripts/refresh.py`,
`features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py`,
`gates/consumer_journey.py`, `tests/`.
**Amends:** ADR-0025, decision 1. ADR-0025's other decisions stand.

## Context

ADR-0025 made the project its own identity: `.ai-badger/project-id`, a uuid4 minted at
scaffold time, never regenerated, resolved by an upward walk. That removed ai-badger's
dependency on the bank — and left the id meaningless *to the bank*. The memory hook and the
memory-first gate pass the walked id to ai-raccoon, so a freshly scaffolded project's uuid
was refused as `project-not-registered` on every read and write until a human registered it
by hand, while the bank still knew the pre-ADR projects by repo basename.

ai-raccoon 1.57.0 closes that gap with two verbs (ADR-0107's error model; the contract was
given by session `ai-raccoon-f7` on 2026-10-04, PR #846):

- `project id get --name <n>` — exit 0 prints exactly one stored id line (legacy raw-text ids
  as stored), 18 when no project has that name, 19 when several do (candidates on stderr).
- `project id register <id> --name <n>` — exit 0 prints `registered <id>` or
  `already registered <canonical>` when the id or an alias of it is already registered,
  18 when the id is retired, 10 for a non-guid that neither is registered nor holds rows.

## Decision

1. **The file is still the identity and is never rewritten.** A present non-blank id keeps
   its value and its bytes. When `raccoon` is allowed and it parses as a uuid, the flow
   costs exactly one `register` — register folds aliases, so no `check` call is needed
   (owner ruling, 2026-10-04). A non-guid file id is skipped silently: `register` is never
   called with an id it cannot take.
2. **A missing or blank file reuses the bank's id by name, or mints and registers.** An
   installing scaffold or any den-refresh asks `get --name <project name>`. A hit is written
   verbatim (legacy non-guid ids included). A not-found mints a uuid4 and registers it. Every
   other outcome — ambiguous, malformed reply, unparseable verb, key band, server band,
   timeout, missing executable — mints a uuid4 without registering and keeps the warning
   (`missing` and the switch produce no warning at all).
3. **One shared flow drives both mint sites.** `project_id.ensure_project_id` is the only
   uuid4 mint in the scaffold/refresh code; `refresh.py`'s duplicate is deleted. The
   scaffolder calls it with `raccoon=self.install`, so `--no-install` never reaches the CLI;
   den-refresh calls it from step 1c on every run.
4. **The name is the main checkout's basename.** `git rev-parse --git-common-dir` collapses a
   linked worktree, so a refresh inside `.ai-badger/worktrees/<task>` never registers a
   project named after the worktree. Outside git the on-disk basename answers, recovered
   case-insensitively when only the spelling's case differs.
5. **The exit codes live in one constants block** in `project_id.py`: 0 ok, 10 usage, 11
   `Usage.Unparseable` (a binary older than 1.57.0, or a changed verb), 18 `ProjectUnknown`
   (get: no such name; register: retired), 19 `ProjectAmbiguous`, the Key band 20-29 and the
   Bank/Port/Server/Reach band 30-69, 95 `Internal.Timeout`. A specific code is matched
   before any band. Each call has a 40 s timeout (80 s worst case for a lookup followed by a
   register on a fresh mint, because the CLI may cold-start its own server).
6. **`AI_BADGER_RACCOON_REGISTER=0` disables every call**, checked once so both verbs honour
   it. The suite, the consumer journey and the fixture all set it; a repo that never uses
   ai-raccoon is not warned.
7. **The gate names the walked id.** `memory_first_gate.project_id` resolves through
   `badger_store.resolve_project_id` — the nearest `.ai-badger/project-id`, with
   `AI_BADGER_PROJECT_ID` first — and falls back to the legacy basename chain only when the
   store is absent or the walk finds nothing. `AI_RACCOON_PROJECT_ID` is retired: the gate
   and the memory hook share one override.

## Alternatives

- **Mint via the MCP tool `project_id_token_get`.** Rejected by the owner: it rewrites
  identity and cannot register an existing id.
- **`check` before `register`.** Dropped per the owner's 2026-10-04 ruling: `register` folds
  aliases itself, and the contract confirms an alias exits 0 with `already registered
  <canonical>` and creates nothing.
- **Import `memory_context.find_executable` for the binary lookup.** Rejected: the bootstrap
  scaffolder ships without a framework checkout and must not depend on a hook module, so a
  pinned twin is used (tests keep the two copies byte-equal in behaviour).
- **Provisional exit codes.** Rejected once the 1.57.0 contract landed: guessing outside the
  real bands was the plan review's MUST-1 (20-22 collide with the Key category, and a bank
  key failure would have been read as not-found).

## Consequences

- **Ids are registered per machine.** The first den-refresh on each machine registers the
  committed uuid with that machine's bank. While 1.56.1 is installed, every installing
  scaffold and den-refresh prints the upgrade note (exit 11); the id is still minted locally,
  so nothing breaks.
- **A uuid4 written while ai-raccoon was unreachable or ambiguous permanently forgoes
  legacy-id reuse**, because the file is never rewritten.
- **A committed uuid4 the bank already aliases to a legacy project** (this repo:
  `024ef989` -> `ai-badger`) gets `already registered <canonical>` from register and creates
  nothing. One that is unknown *and* whose basename already names a legacy project registers
  a second project under that name, which makes a later `get --name` ambiguous; the owner
  resolves that with ai-raccoon's repair alias map.
- **Under 1.57.0, a repo with no id file resolves the gate to the basename**, which the bank
  refuses on reads. Tolerated: the post hook records any `memory_search`
  (`memory_first_gate_post_hook.py`), and `MAX_DENIALS` fails open.
- **The id file stays machine-local convenience, not an authentication token** (ADR-0024/L8):
  registering it asserts an identity, it does not prove one.

## References

- Amended: [ADR-0025](0025-project-resolution-independence.md), decision 1.
- ai-raccoon contract: ADR-0107 (`src/AiRaccoon/ErrorCode.cs`), PR #846, session
  `ai-raccoon-f7`, 2026-10-04.
- Plan review: the four MUST fixes folded into the plan at revision 1 (exit-code collision,
  switch coverage, literal-check shape, `-k` deselection). The plan record lives in the
  task-graph store for `aib-mint-project-id-from-raccoon`, revision 1.