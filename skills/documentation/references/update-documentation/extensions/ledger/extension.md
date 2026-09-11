# update-documentation extension: ledger

This is a **config-gated extension** of the base `update-documentation` skill, not a standalone
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
| `docs.stateFile` | migration state file, if the project pins one | tool's default |
| `docs.legacyRoot` | legacy staging area, if the project pins one | `<docs.root>/legacy/` |

Every command below is written `<docs.tool> <subcommand>`. **Never write a literal invocation into
a document, a commit message, or a PR body** — quote the resolved one.

## The capability contract

Each subcommand automates exactly one obligation the base skill states. **Exit 0 is the
postcondition, not a suggestion**, and a non-zero exit is never "the checker is wrong".

| Subcommand | Exit 0 means | Automates |
|---|---|---|
| `check` | the tree is canonical and every recorded file's content hash matches disk | base step 9 |
| `trust` | every `evidence=<path>:<line>` resolves to a line that exists, and every marker is well-formed | base step 6 — the evidence gate |
| `record` | one ledger entry appended, and the changelog, index and frontmatter `version:`/`updated:` regenerated from it | base step 8 |
| `link-check` | every relative link in the tree resolves | base step 9's link half |
| `scaffold`, `where`, `freeze`, `drain`, `migrate …` | see the `scaffold-documentation` and `migrate-documentation` ledger extensions | — |

## Steps, with the tool bound

Replace the base skill's gate steps with these. Steps 1–5 and 7 are judgement and are unchanged.

6. **Evidence gate. Do not proceed until `<docs.tool> trust` exits 0.** It resolves every
   `evidence=` path and line and fails on any that does not exist. This is the gate an agent will
   self-certify — "I checked it" is not a check, and a plausible line number is not a line number.
   **A failure here means the evidence is wrong, never that the checker is wrong.**
8. **Record gate. Run `<docs.tool> record` and do not proceed until it exits 0.** It appends the
   ledger entry and regenerates the projections. A lock-held exit means another process holds the
   ledger — wait and retry, do not "fix" your input. **Reporting this task complete without a
   successful `record` is a failed run**: the projections are stale and the next person's `check`
   fails.
9. **Run `<docs.tool> check` and `<docs.tool> link-check`. Postcondition:** both exit 0. A
   content-hash failure means the file changed after `record` — re-run step 8. A `version:` failure
   means someone hand-edited it; that failure is correct.

## Notes

- `check` owns the ledger and the tree; `trust` owns the marker layer. Run both — neither implies
  the other.
- Wire both into whatever pre-push or CI lane the project runs, so the gates cannot be skipped by
  forgetting them.
- The tool lives in the project's scripts directory. Do not add one inside this skill.
