# scaffold-documentation extension: ledger

This is a **config-gated extension** of the base `scaffold-documentation` skill, not a standalone
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

A documentation ledger tool is expected to expose these subcommands. Each one automates exactly one
obligation the base skill states; **exit 0 is the postcondition, not a suggestion**, and a non-zero
exit is never "the checker is wrong".

| Subcommand | Exit 0 means | Automates |
|---|---|---|
| `check` | the tree matches the canonical one, and every recorded file's content hash matches disk | the base skill's steps 1, 3 and 5 postconditions |
| `scaffold` | every canonical directory exists | base step 2 |
| `link-check` | every relative link in the tree resolves | base step 4's link half |
| `record` | one ledger entry appended and every projection regenerated | base step 5 |
| `where <old-path>` | a moved path resolved to its current one | nothing here; used by `migrate-documentation` |
| `freeze` | the derived do-not-touch list printed | the freeze list in `references/structure.md` |
| `trust`, `drain`, `migrate status\|next\|done` | see the `update-documentation` and `migrate-documentation` ledger extensions | — |

## Steps, with the tool bound

Replace the base skill's steps with these; the judgement in step 4 is unchanged and stays yours.

1. `<docs.tool> check`. **Postcondition:** you have the list of missing or extra paths. Exit 0 means
   the tree is already canonical — say so and stop; you are not the right skill.
2. `<docs.tool> scaffold`. **Postcondition:** every canonical directory exists. A non-zero exit
   means a path collided with an existing file — resolve that one path, do not re-run blind.
3. **Structure gate. Do not proceed until `<docs.tool> check` exits 0.** No content is written
   before it does.
4. Write the root README and each directory README as complete maps — judgement, unchanged.
   **Postcondition:** `<docs.tool> link-check` exits 0, **and** every file in each governed
   directory appears in its parent README. The second half is not automated; check it yourself.
5. `<docs.tool> record` for the seeded files. **Postcondition:** exit 0, and `<docs.tool> check`
   exits 0 including the content hash. An unrecorded seed makes the very next person's `check` fail.

## Notes

- A non-zero exit from `check` after `record` means the file changed after recording. Re-run
  `record`; do not edit the ledger.
- The tool lives in the project's scripts directory. Do not add one inside this skill.
