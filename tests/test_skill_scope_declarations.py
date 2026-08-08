"""Every common-stack skill declares its own scope, and six of them are pinned to `optIn`.

ADR-0018 collapsed two mechanisms into one: the directory a skill lives in says which stack owns
it, and a `scope:` key in its own `SKILL.md` says whether it ships unasked. There is no second
list to fall out of step with — `badger_lib.SKILL_SCOPES` is gone, and its absence is asserted
here because a reinstated copy would route silently and pass every other test in the suite.

The six pinned skills are all `optIn` (the documentation trio because a project asks for that
workflow rather than having it forced into every skill listing, the navigation trio because its
files derive from templates the third-party `code-review-graph` package auto-installs).
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


def _common_skills(root):
    return sorted(p.parent for p in (root / "features" / "common" / "skills").glob("*/SKILL.md"))


class TestOneMechanism:
    """The declaration lives with the skill; nothing else may answer the same question."""

    def test_badger_lib_keeps_no_second_scope_list(self, bl):
        assert not hasattr(bl, "SKILL_SCOPES"), (
            "SKILL_SCOPES is back. ADR-0018 deleted it: a skill's scope is the `scope:` key in "
            "its own SKILL.md, and a second list drifts from the first silently.")

    def test_every_common_skill_declares_a_scope(self, root, bl):
        undeclared = sorted(d.name for d in _common_skills(root)
                            if bl.skill_scope_in(d) is None)

        assert not undeclared, (
            f"common-stack skill(s) declaring no valid scope: {undeclared}. Add "
            f"`scope: default` or `scope: optIn` to each SKILL.md's frontmatter.")

    def test_no_skill_name_appears_in_two_stack_directories(self, root):
        """The hazard `stack_local_skills`' exclusion clause used to hide (ADR-0018)."""
        owners = {}
        for skill_md in sorted(root.glob("features/*/skills/*/SKILL.md")):
            owners.setdefault(skill_md.parent.name, []).append(
                skill_md.parents[2].name)
        clashes = {name: stacks for name, stacks in owners.items() if len(stacks) > 1}

        assert not clashes, (
            f"a skill name is claimed by two stacks: {clashes}. The directory is the routing "
            f"answer, so two directories mean two answers.")

    def test_the_check_sees_the_whole_catalog(self, root):
        """A glob that stopped matching would pass every assertion above vacuously."""
        assert len(list(root.glob("features/*/skills/*/SKILL.md"))) >= 45
        assert len(_common_skills(root)) >= 30


class TestPinnedScopes:
    """Each of the six declares a scope, and it is the one recorded here."""

    @pytest.mark.parametrize("name", DOCUMENTATION_SKILLS)
    def test_the_documentation_workflow_is_opt_in(self, root, bl, name):
        assert bl.skill_scope_in(
            root / "features" / "common" / "skills" / name) == bl.SKILL_SCOPE_OPT_IN

    @pytest.mark.parametrize("name", NAVIGATION_SKILLS)
    def test_the_navigation_skills_are_opt_in(self, root, bl, name):
        """Another tool installs its own copy of these; ai-badger writes them only when asked."""
        assert bl.skill_scope_in(
            root / "features" / "common" / "skills" / name) == bl.SKILL_SCOPE_OPT_IN

    def test_every_one_of_the_six_lives_in_the_common_catalog(self, root):
        for name in DOCUMENTATION_SKILLS + NAVIGATION_SKILLS:
            assert (root / "features" / "common" / "skills" / name / "SKILL.md").is_file()


class TestScopeIsReadFromTheSkillItself:
    """`skill_scope_in` answers from the file, so a fake tree is enough to make it wrong."""

    def test_a_directory_with_no_skill_md_has_no_scope(self, tmp_path, bl):
        (tmp_path / "nothing").mkdir()

        assert bl.skill_scope_in(tmp_path / "nothing") is None

    def test_an_undeclared_scope_reads_as_none(self, tmp_path, bl):
        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: s\n---\nbody\n", encoding="utf-8")

        assert bl.skill_scope_in(d) is None

    def test_a_value_outside_the_two_scopes_reads_as_none(self, tmp_path, bl):
        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: s\nscope: maybe\n---\nbody\n", encoding="utf-8")

        assert bl.skill_scope_in(d) is None

    @pytest.mark.parametrize("written,expected", [
        ("default", "default"), ("optIn", "optIn"),
        ("'optIn'", "optIn"), ('"default"', "default"),
    ])
    def test_a_declared_scope_is_read_back(self, tmp_path, bl, written, expected):
        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: s\nscope: {written}\n---\nbody\n", encoding="utf-8")

        assert bl.skill_scope_in(d) == expected

    def test_the_scope_sets_split_the_catalog_with_nothing_left_over(self, root, bl):
        skills_dir = root / "features" / "common" / "skills"
        defaults = set(bl.default_skills_in(skills_dir))
        opt_in = set(bl.opt_in_skills_in(skills_dir))

        assert not defaults & opt_in
        assert defaults | opt_in == {d.name for d in _common_skills(root)}


class TestPluginCopyFollowsScope:
    """`sync_plugin_skills` ships default-scope skills only."""

    @pytest.mark.parametrize("name", DOCUMENTATION_SKILLS + NAVIGATION_SKILLS)
    def test_an_opt_in_skill_is_absent_from_the_shipped_list_and_the_plugin_dir(
            self, root, sps, name):
        assert name not in sps.COMMON_SKILLS
        assert not (root / "skills" / name).exists()
