# Changelog

All notable changes to the ai-badger framework are documented here.
Each version gets its own file: `{version}-{slug}.md`.

## Format

```
docs/changelog/
  0.8.0-tier2-drift-new-items.md      # Latest
  0.7.2-move-auto-wm-to-claude.md
  0.7.1-hermes-external-dirs.md
  0.7.0-skills-hooks-adjustments.md
  0.6.0-...                            # Older entries
```

See individual files for details. Versions follow [SemVer](https://semver.org/).

## Convention

Every release must:
1. Bump `VERSION` (semver patch for fixes, minor for features, major for breaking)
2. Add a `docs/changelog/{version}-{slug}.md` entry here
3. Run `python3 scripts/version_sync.py` to propagate version to metadata files

This is enforced by the `version-changelog-required` invariant.
