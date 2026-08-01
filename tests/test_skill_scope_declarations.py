"""The six skills of the documentation + code-navigation set are pinned to their scopes.

A later edit that silently flips one has to argue with these assertions. All six are `optIn`
(ADR-0005 for what each scope means): the documentation trio because a project asks for that
workflow rather than having it forced into every skill listing, the navigation trio because
its files derive from templates the third-party `code-review-graph` package auto-installs —
shipping them `default` would have ai-badger's plugin mirror and `.claude/skills/` symlinks
contend with another tool's files in every project that has it.
"""
from __future__ import annotations

import pytest

DOCUMENTATION_SKILLS = ("scaffold-documentation", "update-documentation",
                        "migrate-documentation")
NAVIGATION_SKILLS = ("review-changes", "debug-issue", "refactor-safely")


@pytest.fixture(name="bl")
def _bl(load_script):
    return load_script("engine/badger_lib.py")


@pytest.fixture(name="sps")
def _sps(load_script):
    return load_script("tooling/sync_plugin_skills.py")


class TestPinnedScopes:
    """Each of the six declares a scope, and it is the one recorded here."""

    @pytest.mark.parametrize("name", DOCUMENTATION_SKILLS)
    def test_the_documentation_workflow_is_opt_in(self, bl, name):
        assert bl.skill_scope(name) == bl.SKILL_SCOPE_OPT_IN

    @pytest.mark.parametrize("name", NAVIGATION_SKILLS)
    def test_the_navigation_skills_are_opt_in(self, bl, name):
        """Another tool installs its own copy of these; ai-badger writes them only when asked."""
        assert bl.skill_scope(name) == bl.SKILL_SCOPE_OPT_IN

    def test_every_one_of_the_six_lives_in_the_common_catalog(self, root):
        for name in DOCUMENTATION_SKILLS + NAVIGATION_SKILLS:
            assert (root / "features" / "common" / "skills" / name / "SKILL.md").is_file()


class TestPluginCopyFollowsScope:
    """`sync_plugin_skills` ships default-scope skills only."""

    @pytest.mark.parametrize("name", DOCUMENTATION_SKILLS + NAVIGATION_SKILLS)
    def test_an_opt_in_skill_is_absent_from_the_shipped_list_and_the_plugin_dir(
            self, root, sps, name):
        assert name not in sps.COMMON_SKILLS
        assert not (root / "skills" / name).exists()
