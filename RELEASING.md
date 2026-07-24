# Releasing ai-badger

A `git push` is not a release. ai-badger is consumed via two paths:

1. **Claude Code** — installed as a plugin from `.claude-plugin/`. Consumers resolve by `version` in `plugin.json`.
2. **Hermes Agent** — skills discovered via `skills.external_dirs` in `~/.hermes/config.yaml`. Consumers get updates via `den-refresh`.

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
3. `python3 scripts/version_sync.py` — propagates version to `plugin.json`, `marketplace.json`, and `index.json`.
4. `python3 scripts/version_sync.py --check && python3 scripts/release_guard.py` — both must pass.
5. `python3 -m pytest tests/ -q` and `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`.
6. Open a PR; CI runs the same gates.
7. After merge, from `main`: `claude plugin tag --push` — creates `ai-badger--v{version}`.
8. **Verify content, not just metadata** (fixes #27):

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

## Several PRs, one release

`release_guard.py` compares against the last release *tag*, not the previous commit. Multiple PRs may land at one unreleased version; tag once when the set is complete.
