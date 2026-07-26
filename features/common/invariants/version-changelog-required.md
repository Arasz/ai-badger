# Always bump VERSION and add changelog entry

Every release — no matter how small — must:
1. Bump `VERSION` (semver patch for fixes, minor for features, major for breaking changes)
2. Run `python3 scripts/version_sync.py` to propagate the version into plugin.json, marketplace.json, and index.json
3. Run `python3 scripts/index_build.py` to rebuild index.json if any feature files changed
4. Add a `docs/changelog/{version}-{slug}.md` entry describing what changed
5. Update `docs/changelog/README.md` if adding a new changelog format convention

This ensures every change is traceable and users can see what changed between versions.
