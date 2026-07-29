"""The concrete release-changelog convention ships only behind evidence of a changelog stack;
every project gets the generic, path-free release-traceability principle instead (#130).
"""
from __future__ import annotations

from scaffold_helpers import _config

RENDERED_FILES = (
    "CLAUDE.md",
    ".ai-badger/CLAUDE.md",
    ".github/copilot-instructions.md",
    ".ai-badger/copilot-instructions.md",
    "HERMES.md",
    ".hermes.md",
    ".ai-badger/HERMES.md",
    ".junie/AGENTS.md",
    ".ai-badger/AGENTS.md",
)


def _scaffold(make_scaffolder, config):
    target = make_scaffolder.target
    make_scaffolder(config=config).run(generated_at="2026-07-28T00:00:00Z")
    return target


def test_a_project_without_the_changelog_stack_renders_no_changelog_paths(make_scaffolder):
    config = _config(stacks=["python"], agents=["claude", "copilot", "hermes", "junie"])

    target = _scaffold(make_scaffolder, config)

    for rel in RENDERED_FILES:
        path = target / rel
        assert path.is_file(), f"expected {rel} to be rendered"
        assert "docs/changelog/" not in path.read_text(encoding="utf-8"), rel
    assert not (target / ".ai-badger" / "invariants" / "version-changelog-required.md").exists()


def test_the_generic_release_invariant_ships_from_common(make_scaffolder):
    config = _config(stacks=["python"], agents=["claude"])

    target = _scaffold(make_scaffolder, config)

    assert "Releases are traceable" in (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert (target / ".ai-badger" / "invariants" / "traceable-releases.md").is_file()


def test_a_project_with_the_changelog_stack_gets_the_concrete_convention(make_scaffolder):
    config = _config(stacks=["python", "changelog"], agents=["claude"])

    target = _scaffold(make_scaffolder, config)

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "docs/changelog/{version}-{slug}.md" in claude_md
    assert (target / ".ai-badger" / "invariants" / "version-changelog-required.md").is_file()
