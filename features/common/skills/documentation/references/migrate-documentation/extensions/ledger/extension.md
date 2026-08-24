# migrate-documentation extension: ledger

This is a **config-gated extension** of the base `migrate-documentation` skill, not a standalone
skill. The scaffolder embeds this fragment only when the project's `.ai-badger/config.json`
satisfies the activation condition below — otherwise the base skill's manual gates are what a
project gets, and it loses automation and nothing else.

**Activates when:** `.ai-badger/config.json` sets `docs.tool`.

## Read the invocation, never hardcode it

`docs` is a free-form string map. Read these keys at the start of the run, the same way the base
`task` skill reads `commands.build`:

| Key | Meaning | Default |
|---|---|---|
| `docs.tool` | the invocation prefix a subcommand is appended to | — (required) |
| `docs.root` | the documentation tree root | `docs/` |
| `docs.stateFile` | the migration state file | tool's default under `<docs.root>/meta/` |
| `docs.legacyRoot` | the legacy staging area | `<docs.root>/legacy/` |

Every command below is written `<docs.tool> <subcommand>`. **Never write a literal invocation into
a document, a commit message, or a PR body** — quote the resolved one.

## The capability contract

Each subcommand automates exactly one obligation the base skill states. **Exit 0 is the
postcondition, not a suggestion**, and a non-zero exit is never "the checker is wrong".

| Subcommand | Exit 0 means | Automates |
|---|---|---|
| `migrate status` | the phase, the `n/total` count and the single in-progress item are printed | base step 1 — the resume contract |
| `migrate next` | exactly one item handed out; it refuses while another is in progress | base step 7's one-at-a-time rule |
| `migrate done <id>` | the cursor advanced by exactly one section | base step 7's postcondition |
| `link-check` | every relative link resolves; `--fix` rewrites the failing ones | base steps 3 and 9 |
| `freeze` | the do-not-touch list derived from the build and live work | base step 3 |
| `check` | the tree is canonical, hashes match, and no vacated path is unexplained or resurrected | base steps 5, 6 and 9 |
| `record --path <new> --from <old>` | the move recorded as an old→new edge | base step 5 |
| `where <old-path>` / `where --all` | a vacated path resolved to its current one | base step 5's no-stub rule |
| `trust` | every `evidence=<path>:<line>` resolves | base step 7 — the evidence gate |
| `drain <path>` | `residual == 0` **and** every `processedto` target exists and contains the span id | base step 8 — the drain gate |
| `scaffold` | every canonical directory exists | base step 6, via `scaffold-documentation` |

## Steps, with the tool bound

The judgement in every step is unchanged. These bind the checks.

- **Step 1, every session:** `<docs.tool> migrate status` before anything else. If an item is in
  progress, finish it — `migrate next` refuses to hand out a second one, and **that refusal is the
  design, not a bug to work around**.
- **Step 3:** `<docs.tool> link-check` and `<docs.tool> freeze` before any file moves. **Do not
  proceed until `link-check` exits 0.**
- **Step 4:** write the classification and the boundary commit into `docs.stateFile`.
  **Postcondition:** every tracked path has exactly one row and the boundary SHA resolves.
- **Step 5:** the move and its record are one step.
  ```bash
  git mv <docs.root>/<old> <docs.root>/<new>
  <docs.tool> record --path <new> --from <old> --summary S --reason R
  ```
  **Postcondition:** `git show --stat` shows renames only; `link-check` and `check` both exit 0 —
  `check` fails if a vacated path is gone with no edge explaining it, if it is still on disk, or if
  a stub reappears at one.
- **Step 6:** invoke `scaffold-documentation`, then write the baseline. **Structure gate: do not
  proceed to extraction until `<docs.tool> check` exits 0**, with zero dead links and zero
  undischarged reference obligations.
- **Step 7:** `<docs.tool> migrate next` hands out one item; `<docs.tool> migrate done <id>` closes
  it. **Evidence gate: do not proceed to the next item until `<docs.tool> trust` exits 0.**
  `migrate next` failing on the third attempt at the same item is a signal to escalate, not to retry.
- **Step 8:** **do not delete a legacy file until `<docs.tool> drain <path>` exits 0 for it** — and
  paste that report into the deletion PR. This is the one irreversible step in the migration.
- **Step 9:** `link-check --fix` rewrites failing referrers. **Read its diff before committing**,
  and run the `record` invocation it prints, or `check` goes red on content drift.
  **Postcondition:** `link-check` and `check` exit 0, and `where --all` resolves every recorded move
  to a file that exists.

## Notes

- Update the cursor in `docs.stateFile` **in the same commit as the content it describes**. A tool
  that writes it separately reintroduces exactly the split this gate exists to prevent.
- Wire `check`, `trust` and `link-check` into the project's pre-push or CI lane.
- The tool lives in the project's scripts directory. Do not add one inside this skill.
