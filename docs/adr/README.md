# Architecture Decision Records

A decision that would otherwise get re-litigated lives here: one file per decision, numbered
sequentially, in the MADR shape (context → decision → consequences).

**ADRs are never edited after acceptance.** If a decision changes, write a *new* ADR that
supersedes the old one and say so in both. Correcting a typo is fine; rewriting the reasoning is
not — the value of the record is that it says what was believed at the time.

The one exception already present: ADR-0003 carries a numbering note because `docs/adr/` briefly
held two files numbered 0002. That collision was resolved in 0.22.0. One number, one ADR.

| # | Decision | Status | Covers |
|---|---|---|---|
| [0001](0001-versioning-and-release-model.md) | Versioning and release model | Accepted (2026-07-19) | Why four version literals are kept in sync mechanically, immutable release tags, semver for a catalog rather than an API, provenance in `manifest.json`, two-tier drift detection |
| [0002](0002-den-refresh-skill.md) | `den-refresh`: the framework-update skill | Proposed (2026-07-22) | Why pulling framework updates *into* a project is a third skill rather than a mode of `welcome-ai-badger` |
| [0003](0003-hermes-skill-discovery-via-namespaced-symlinks.md) | Hermes skill discovery via namespaced symlinks | Accepted (2026-07-26) | The authoritative record of how Hermes finds skills: per-project symlinks under `~/.hermes/skills/<project>/`. Reverses the `skills.external_dirs` approach that shipped in 0.7.1 |
| [0004](0004-mcp-tool-index.md) | MCP Tool Index with tag + intent semantic matching | Accepted (2026-07-22) | Cutting prompt bloat and improving tool selection by indexing MCP tools instead of injecting every definition every turn |
| [0005](0005-default-skill-set.md) | One declaration of which skills ship | Accepted (2026-07-27) | Collapsing two hand-maintained skill lists into one source of truth; `code-review-checklist` becomes default |
| [0006](0006-one-skill-extension-mechanism.md) | One skill extension mechanism | Accepted (2026-07-27) | Two rival ways to extend a skill reduced to one; the legacy layout is now refused at build time rather than silently ignored |
| [0007](0007-no-python-distribution.md) | ai-badger ships as files, not as a Python distribution | Accepted (2026-07-27) | Why packaging `badger_lib` is declined against all four deployment shapes; what Waves 7, 16 and 17 should therefore do |
| [0008](0008-plugin-skills-live-at-the-plugin-skill-path.md) | Plugin skills live at the plugin skill path, and only there | Accepted (2026-07-27) | Why the plugin's skills moved from `.claude/skills/` to `skills/`, what the loader actually scans, and what two same-named skills do |
| [0009](0009-one-framework-root-resolution.md) | One framework root, resolved rather than searched | Accepted (2026-07-27) | The single root predicate, why a declared root refuses while a discovered one falls through, `--root` read from `sys.argv` before argparse, and `frameworkRoot` as a validated manifest hint |

## Writing a new one

Take the next free number. Keep the filename kebab-case and imperative-ish
(`0007-short-title.md`). State the status and date at the top. If it supersedes an earlier ADR,
name it — and add a line to the superseded ADR pointing forward, since that is the one edit an
accepted ADR is allowed.

Add the ADR in the same pull request as the change it justifies, not afterwards.
