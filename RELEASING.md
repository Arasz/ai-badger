# Releasing ai-badger

A `git push` is not a release. Consumers resolve the plugin by the `version` in
`plugin.json`; if that string does not change, `claude plugin update` sees no change and
skips, so pushed fixes never reach anyone. See
[ADR-0001](docs/adr/0001-versioning-and-release-model.md).

## Semver for a catalog

This ships instructions and scaffolding, not an API.

- **0.MINOR** — anything that changes what scaffolding *does* to a consumer repo: removed or
  renamed features, changed target paths, changed hook contracts, changed detection behavior.
- **0.x.PATCH** — content fixes to existing files that do not alter scaffold output shape.

Pre-1.0, the minor slot is the breaking slot. The number tracks blast radius, not intent: a
change made as a bug fix still takes the minor slot if a re-scaffold now behaves differently.

## Cutting a release

1. Edit `VERSION`.
2. `python3 scripts/version_sync.py` — propagates it to `plugin.json`, `marketplace.json`,
   and (via `index_build.py`) `index.json`.
3. `python3 scripts/version_sync.py --check && python3 scripts/release_guard.py` — both must pass.
4. `python3 -m pytest tests/ -q` and `python3 -m pylint $(git ls-files '*.py' | grep -v '^tests/')`.
5. Open a PR; CI runs the same gates.
6. After merge, from `main`: `claude plugin tag --push` — creates `ai-badger--v{version}`,
   validating that `plugin.json` and the marketplace entry agree.
7. Verify a consumer can actually move, rather than assuming:

```bash
claude plugin marketplace update ai-badger
claude plugin update ai-badger@ai-badger
python3 -c "import json;d=json.load(open('$HOME/.claude/plugins/installed_plugins.json'));print(d['plugins']['ai-badger@ai-badger'])"
```

The recorded `version` and `gitCommitSha` must have moved. If they have not, the release did
not ship, regardless of what CI said.

## Tags

Releases are tagged `ai-badger--v{version}` — the convention Claude Code resolves by. A version
denotes exactly one commit, forever; never re-point or reuse one.

A legacy `v0.1.0` tag exists at the same commit as `ai-badger--v0.1.0` (`2710dd4`). It is kept
because deleting a published tag breaks anyone who referenced it. New releases use only the
`ai-badger--v` form.

## Several PRs, one release

`release_guard.py` compares against the last release *tag*, not the previous commit. Multiple
PRs may land at one unreleased version; tag once when the set is complete.
