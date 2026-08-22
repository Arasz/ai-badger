<!-- Managed by ai-badger. Source of truth: tooling/changelog_index.py. Regenerate with: python3 tooling/changelog_index.py -->

# Changelog

All notable changes to the ai-badger framework are documented here.

Format: one file per release under `docs/changelog/<version>-<slug>.md`, named after
the version it went out at. Each file carries:
- A `# <version> — <title>` heading
- A classification: **Major** (breaking), **Minor** (additive), or **Patch** (fixes)
- The date and headline changes
- Sections for new features, changes, fixes, and upgrade notes where relevant

When cutting a release:
1. Add `docs/changelog/<version>-<slug>.md`
2. Run `python3 tooling/changelog_index.py` to regenerate the index table below
3. Commit both files together with the `VERSION` bump

<!-- changelog-index:start -->
| Version | Entry |
|---|---|
| 0.132.0 | [QA personas, `design-tests` + `review-tests`, one layered test ruleset](0.132.0-qa-personas-and-test-skills.md) |
| 0.132.0 | [playwright-mcp and browser-usage skill](0.132.0-playwright-mcp-and-browser-usage-skill.md) |
| 0.131.1 | [ai-raccoon-memory relays the code-engine-not-configured warning](0.131.1-ai-raccoon-memory-relays-code-engine-warning.md) |
| 0.131.0 | [vue stack](0.131.0-vue-stack.md) |
| 0.130.1 | [Semantica: shim resolves the project dir; export probe runs in the resolved env](0.130.1-semantica-moe-followups.md) |
| 0.130.0 | [Semantica integration](0.130.0-semantica-integration.md) |
| 0.129.0 | [Hermes MCP client & memory tools integration](0.129.0-hermes-mcp-client-and-memory-tools.md) |
| 0.128.1 | [Fix: restore shipped invariant bytes across self-scaffold](0.128.1-restore-shipped-invariants.md) |
| 0.128.0 | [Cross-session coordination hooks](0.128.0-cross-session-coordination-hooks.md) |
| 0.127.0 | [UX design review lens](0.127.0-ux-design-review-lens.md) |
| 0.126.0 | [ArchUnit link & size fitness functions](0.126.0-archunit-link-and-size.md) |
| 0.125.0 | [Task extensions framework](0.125.0-task-extensions.md) |
| 0.124.0 | [Agent doc-budget override](0.124.0-agent-doc-budget-override.md) |
| 0.123.0 | [Pipeline runs the rest](0.123.0-pipeline-runs-the-rest.md) |
| 0.122.0 | [Plugin tool-reference discovery](0.122.0-plugin-tool-references.md) |
| 0.121.0 | [Catalog seed for mcp-index](0.121.0-mcp-index-catalog-seed.md) |
| 0.120.0 | [Isolate every agent](0.120.0-isolate-every-agent.md) |
| 0.119.0 | [ArchUnit Vacuous Rules Detection](0.119.0-archunit-vacuous-rules.md) |
| 0.118.0 | [Telemetry-driven skill creation nudging](0.118.0-telemetry-driven-skill-creation.md) |
| 0.117.0 | [Claude Code OTEL trace collection](0.117.0-claude-otel-tracing.md) |
| 0.116.0 | [Dynamic BM25 MCP tool retrieval](0.116.0-bm25-mcp-retrieval.md) |
| 0.115.0 | [Subagent token attribution in task tracker](0.115.0-subagent-token-attribution.md) |
| 0.114.0 | [Changelog index generation and release gate enforcement](0.114.0-changelog-index-generation.md) |
| 0.113.0 | [Single framework root resolution](0.113.0-single-framework-root.md) |
| 0.112.0 | [Automated release model and state-file tracking](0.112.0-automated-release-model.md) |
<!-- changelog-index:end -->
