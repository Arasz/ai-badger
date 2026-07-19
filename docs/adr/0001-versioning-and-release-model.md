# ADR-0001 — Versioning and release model

**Status:** Accepted (2026-07-19)

## Context

ai-badger had four independent version literals — `VERSION`, `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, and the generated `index.json` — all reading `0.1.0`, with
nothing enforcing that they agree and no process bumping them. There was no `CHANGELOG`,
`CONTRIBUTING`, or `RELEASE` doc, and no workflow that tagged, published, or cross-checked a
version. `grep -rn "\.claude-plugin" scripts/ tests/ skills/ .github/` returned zero hits: the
two plugin manifests sat entirely outside the mechanical validation the rest of the catalog
gets from `index_build.py --check` and `validate.py --all`.

The consequence was not that pinning was unavailable. Consumers were already pinned, harder
than intended, and shipped fixes never reached them.

`0.1.0` came to denote at least four different code states:

| What | Commit | Contains |
|---|---|---|
| A real user's installed plugin | `da214fb` | the pre-#12 `PROJECT_ROOT = SCRIPT_DIR.parents[3]` bug |
| Tag `v0.1.0` | `2710dd4` | #12–#14 fixed |
| `main` | `7989081` | #17–#19 also fixed |
| Any scaffold taken between those | various | mixed |

Verified on a live machine: `~/.claude/plugins/cache/ai-badger/ai-badger/0.1.0/skills/task/scripts/tracker_lib.py:34`
still contained the misrooting bug fixed in #12, in a directory named for the same version
`main` carried with the fix. That install was 16 commits behind and could not move:
`autoUpdate` defaults to `false` for third-party marketplaces, and `claude plugin update`
re-resolves the version, sees `0.1.0 == 0.1.0`, and skips. **A `git push` is not a release.**

Installs were also irreproducible. Someone installing today received `main`'s content labelled
`0.1.0`; an existing install had `da214fb` labelled `0.1.0`. Same version string, different
code, depending on when the command ran.

ai-badger is a public, MIT-licensed framework intended for use by people other than its author.
Version history is therefore a contract, not a private note.

## Decision

### 1. `VERSION` is the single source of truth, and generation enforces it

`scripts/version_sync.py` reads `VERSION` and writes it into `plugin.json`,
`marketplace.json`, and `index.json`. `--check` re-derives and diffs against committed
content, failing CI on mismatch.

This deliberately mirrors `index_build.py --check`, an existing and proven pattern in this
repo already wired into CI. Generation makes disagreement structurally impossible rather than
merely detected.

Rejected: hand-editing all four with a CI gate to catch mistakes (catches rather than
prevents), and semantic-release from conventional commits (pulls a Node toolchain into a
deliberately pure-stdlib-Python repo, and would have classified the `detect.py` behavior change
below as a `fix`, i.e. a patch — the opposite of the call made here).

### 2. A version denotes exactly one commit, forever

Releases are immutable tags named `ai-badger--v{version}` — the convention Claude Code
resolves releases by. A version string is never reused for different content.

`main` between releases is explicitly not a version. It is unreleased work, and consumers do
not see it, because plugin resolution reads the released version.

CI carries a release guard: if anything under `skills/`, `features/`, `scripts/`, `schemas/`,
or `index.json` differs from the **last release tag**, `VERSION` must differ from that tag's
version. Comparing against the last release tag rather than the previous commit is load-bearing
— it lets several PRs land at one unreleased version without inflating the number, and it is
the check that would have caught the situation in Context.

### 3. Semver for a catalog

This ships instructions and scaffolding, not an API, so the usual definitions need restating:

- **0.MINOR** — anything that changes what scaffolding *does* to a consumer repo: removed or
  renamed features, changed target paths, changed hook contracts, changed detection behavior.
- **0.x.PATCH** — content fixes to existing files that do not alter scaffold output shape.

Pre-1.0, the minor slot is the breaking slot.

The next release is therefore **0.2.0**, not `0.1.1`. Since the last tag, `detect.py` emits a
stack it previously never could (`angular`), and `scaffold.py` stopped overwriting files it
used to destroy. Both change what a re-scaffold does to a consumer repo. Intent was "fix"; the
blast radius is not a patch, and the number tracks blast radius.

### 4. A manifest records its own provenance

`.ai-badger/manifest.json` gains three **required** keys:

```json
"frameworkVersion": "0.2.0",
"frameworkCommit": "7989081…" | null,
"frameworkDirty": false
```

Once decision 2 holds, a version resolves to a commit by construction, so the SHA is redundant
for released scaffolds. It earns its place for scaffolds taken from an unreleased working tree
— which is what dogfooding does, and is how the state in Context arose.

`frameworkCommit` is git `HEAD` when scaffolding from a clone and `null` from a plugin cache,
which is a plain copy with no `.git` at all. `frameworkDirty` marks a scaffold taken from a
tree with uncommitted changes: provenance that is not reproducible.

The keys are required, with nullable values. Key *presence* is what carries meaning — a
manifest lacking them is unambiguously pre-0.2.0.

**No migration is provided.** Existing manifests must re-scaffold. This is a breaking change,
which 0.2.0 permits, and it is taken now precisely because it is cheap now: two consumers,
both the author's, no external installs yet. After the framework is publicly promoted that
window closes permanently. `validate.py` must emit an actionable "re-scaffold to upgrade"
message rather than a raw schema error.

Rejected: an optional field written on next scaffold (leaves provenance coarse indefinitely),
and a migration script (it would have to guess which commit produced an old scaffold, and given
that `0.1.0` denotes four states that guess is unknowable — inventing provenance is worse than
admitting it is unknown).

### 5. Drift detection is two-tier

**Tier 1 — automatic, local-only, free.** A SessionStart check compares the manifest's
`frameworkVersion` against `$CLAUDE_PLUGIN_ROOT/VERSION`. Two string reads, no network, no path
guessing. It prints one line on mismatch and is silent otherwise; a noisy hook gets ignored,
which defeats the purpose.

**Tier 2 — explicit.** Walks manifest entries, recomputes hashes against the framework's
current content, and reports changed, new, and removed items. Network is acceptable here, so
this is also where the upstream "is a newer release available" check lives.

Known limitation, accepted rather than solved: Tier 1 detects *divergence* between scaffold and
plugin, not *lockstep staleness*. It would not have caught the situation in Context, where both
read `0.1.0`. Only Tier 2's upstream check finds that, so it should be run periodically —
consumer CI on a schedule is a better home than a session hook.

Second known limitation, documented rather than solved: an upstream rename reads as "removed"
in Tier 2, because `entry["source"]` is a path with no forwarding record. Solving it needs a
provenance/redirect mechanism not worth building at this catalog's size.

## Consequences

**Good.** A version identifies content, so a bug report can name one. Installs become
reproducible. Fixes actually ship, because releasing is one action rather than remembering four
files. The two plugin manifests come under mechanical validation for the first time. The
release guard makes the failure that produced this ADR impossible to repeat silently.

**Costs.** Every consumer must re-scaffold to reach 0.2.0. Releasing gains ceremony that a
one-maintainer project did not previously have. Two literals (`v0.1.0` and `ai-badger--v0.1.0`)
point at `2710dd4`; the legacy tag is kept because deleting a published tag breaks anyone who
referenced it, and that rule matters more than tidiness once strangers depend on the repo.

**Deferred.** Per-consumer divergent pinning is supported by Claude Code via
`{plugin-name}--v{version}` tags plus semver-range `dependencies` constraints, letting two
repos hold different versions from one shared `marketplace.json`. It requires each consumer to
wrap the dependency in a thin local plugin. With one maintainer and two consumers, decisions
1–3 solve the actual pain; this is recorded as a known option, not adopted.

**Rejected outright.** Marketplace-source `ref` must never be added. It is accepted, stored,
and silently ignored — verified empirically with an isolated `HOME` and a tag at an old commit;
the clone still landed on `main`'s tip. It looks like a pin and is not, which is worse than no
pin. Pinning the plugin's own `source` is also unavailable here: the entry is `source: "./"`,
self-referential to the marketplace root, so a `{github, sha}` source object would be circular.

## Notes on method

Every mechanical claim in this ADR was verified against the live CLI and on-disk state rather
than documentation, after marketplace-source `ref` proved documented-but-unimplemented.
Documentation was treated as a lead, not a source.

Related: issue #20 (requirements), #15/#16 (the bugs whose fixes could not ship).
