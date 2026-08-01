# Releasing ai-badger

A `git push` is not a release. ai-badger is consumed via two paths:

1. **Claude Code** — installed as a plugin from `.claude-plugin/`. Consumers resolve by `version` in `plugin.json`.
2. **Hermes Agent** — skills discovered through per-project symlinks under `~/.hermes/skills/<project>/` ([ADR-0003](docs/adr/0003-hermes-skill-discovery-via-namespaced-symlinks.md)). Consumers get updates via `den-refresh`. The `skills.external_dirs` mechanism this line used to describe shipped in v0.7.1 and was reverted.

Both paths require a version bump to signal a release. See [ADR-0001](docs/adr/0001-versioning-and-release-model.md).

## Semver for a catalog

This ships instructions and scaffolding, not an API.

- **0.MINOR** — anything that changes what scaffolding *does* to a consumer repo: removed or renamed features, changed target paths, changed hook contracts, changed detection behavior, new schemas, new feature types.
- **0.x.PATCH** — content fixes to existing files that do not alter scaffold output shape.
- **BREAKING** — add the version to `BREAKING_VERSIONS` if a re-scaffold is required (not just recommended). den-refresh will detect this and back up `.ai-badger/` before re-scaffolding.

Pre-1.0, the minor slot is the breaking slot. The number tracks blast radius, not intent.

## Cutting a release

1. Edit `VERSION`.
2. Add `docs/changelog/{version}-{slug}.md` describing what changed.
3. `python3 tooling/changelog_index.py` — regenerates the release table in `docs/changelog/README.md` from the entry files. Never hand-edit that table (issue #160).
4. `python3 tooling/version_sync.py` — propagates version to `plugin.json`, `marketplace.json`, and `index.json`.
5. `python3 tooling/version_sync.py --check && python3 tooling/changelog_index.py --check && python3 gates/release_guard.py` — all three must pass.
6. `python3 -m pytest tests/ -q` and `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`.
7. Open a PR; CI runs the same gates.
8. **Merge. The tag is automatic** — since 0.69.2 a workflow tags `ai-badger--v{version}` from
   `main` after the merge. Nobody runs `claude plugin tag --push` by hand any more.

   That step used to be step 8 and used to be *the* release, and it was skipped 32 times: a
   green PR looks identical whether or not anyone remembered. Automating it removed the failure
   mode; verify the tag reached the remote anyway
   (`git ls-remote --tags origin | grep "refs/tags/ai-badger--v{version}$"`)
   rather than assuming, because a workflow that did not run also looks like nothing.
9. **Verify content, not just metadata** (fixes #27):

### Verification (mandatory)

Do NOT trust `claude plugin update` output alone — it can reuse a stale cache directory.
Verify the release actually shipped by checking **content**:

```bash
# Option A: Hash-based verification (preferred)
CACHE_DIR="$HOME/.claude/plugins/cache/ai-badger--ai-badger/$(python3 -c "import json;print(json.load(open('$HOME/.claude/plugins/installed_plugins.json'))['plugins']['ai-badger@ai-badger']['version'])")"
python3 -c "
import hashlib, pathlib
h = hashlib.sha256()
for f in sorted(pathlib.Path('$CACHE_DIR').rglob('*')):
    if f.is_file():
        h.update(f.read_bytes())
print(h.hexdigest())
"
# Compare against: git archive $TAG | sha256sum
```

```bash
# Option B: File existence check (minimum)
# A file introduced by the release MUST exist in the cache
ls "$CACHE_DIR"/BREAKING_VERSIONS  # introduced in 0.7.0
```

If verification fails: move the cache dir aside and re-run `claude plugin update`.

### Hermes verification

Hermes users get updates via `den-refresh`. No cache trap — the framework files are read directly from the project's `.ai-badger/` directory. After tagging, Hermes users run:

```bash
# From their project root
den-refresh
```

This re-scaffolds with the latest framework. If the version is in `BREAKING_VERSIONS`, a backup is created automatically.

## Tags

Releases are tagged `ai-badger--v{version}` — the convention Claude Code resolves by. A version denotes exactly one commit, forever; never re-point or reuse one.

Tags are **not** cut in batches. `0.3.0`–`0.19.0` carry no tag and never will: retro-tagging them would claim they passed the verification below, which they did not. The baseline restarts at `ai-badger--v0.20.0`.

## Several PRs, one release

`release_guard.py` compares against the last release *tag*, not the previous commit. Multiple PRs may land at one unreleased version; tag once when the set is complete.

*One* unreleased version in flight is this model working. Two or more means a tag was skipped, and the guard prints `UNTAGGED RELEASES` naming them and **exits 1** — checked before the diff, because an untagged release is a fact about the repo rather than about what this push touched.

### Merge order is part of the release

Two PRs carrying different versions must merge in version order. On 2026-08-01 they did not: a
0.70.0 branch merged, then a 0.69.3 branch merged seventeen minutes later and wrote `VERSION`
**backwards**. Both changes landed; only the recorded version stopped describing the tree, and
`main` sat below its own highest tag with nowhere to go next.

`release_guard.py` now refuses a `VERSION` below the last released tag — it previously asked only
whether the two *differed*, and inequality is not ordering, so it reported `0.70.0 -> 0.69.3` as a
bump and passed. Re-check the base before merging the second PR of a pair; a version stated in a
PR description is a comment, not a control.

A tag whose commit contains a *later* release's shipped surface is deleted rather than moved: it
labels a superset of what it claims. Re-cut the content at a fresh version above the highest tag,
and remove the misleading tag only after the new one exists, so `main` is never untagged.

The check earns that severity: `release_guard.py` derives its baseline from the last tag, so between 2026-07-19 and 2026-07-27 it compared against an 18-minor-stale `ai-badger--v0.2.0`, found changes and a differing `VERSION` every run, and passed 32 times without ever being capable of failing. When a check's authority comes from the artefact it is checking, its silence carries no information.
