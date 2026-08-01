"""Skills that cannot work alone are installed as a group (#266).

`migrate-documentation` ships no `references/` of its own. Its body names four files by relative
sibling path — three under `update-documentation/references/`, one under
`scaffold-documentation/references/` — and says, deliberately, "read them where they live; do not
copy them into a shared directory, which cannot ship."

All three are `optIn`. A project that named only `migrate-documentation` therefore received a
skill whose every reference path was dangling, and nothing said so: the scaffold reported it
included, because it was.

The hazard is invisible in this repository, which opted into all three at once — which is exactly
why it needed a test rather than a reading.

`SKILL_GROUPS` declares the dependency rather than inferring it from prose, and two guards keep
that declaration honest: no skill may cite a sibling it is not grouped with, and no group may
name a skill the catalog does not have. A declaration only knows what it was told; the guards are
what notice when the catalog moves underneath it.

They group in configuration only. A skills directory registers exactly one nesting level, so a
nested `documentation/` directory would be invisible to every agent — delivery stays flat.
"""
from __future__ import annotations

import re

import pytest

from scaffold_helpers import _config

# The lookbehind matters: `../../outside/references/x.md` reaches past the skills directory and
# is not a sibling reference. Without it the guard would treat one as resolvable and never say so.
SIBLING_REF_RE = re.compile(r"(?<![./])\.\./([a-z][a-z0-9-]*)/(references/[a-z-]+\.md)")


def _catalog_skills(root):
    for path in sorted(root.glob("features/*/skills/*/SKILL.md")):
        yield path.parent.name, path


class TestEverySiblingReferenceResolvesInTheCatalog:
    """A citation to a file the catalog does not have is dead on arrival, closure or not."""

    def test_each_referenced_sibling_exists(self, root):
        missing = []
        for name, path in _catalog_skills(root):
            for sibling, relpath in SIBLING_REF_RE.findall(path.read_text(encoding="utf-8")):
                target = path.parent.parent / sibling / relpath
                if not target.is_file():
                    missing.append(f"{name} -> ../{sibling}/{relpath}")

        assert not missing, "sibling references naming a file the catalog does not have: " + \
            ", ".join(missing)

    def test_the_scan_actually_finds_the_known_references(self, root):
        """An empty finding must mean 'all resolve', not 'the pattern never matched'."""
        found = [
            (name, sibling)
            for name, path in _catalog_skills(root)
            for sibling, _ in SIBLING_REF_RE.findall(path.read_text(encoding="utf-8"))
        ]

        assert ("migrate-documentation", "update-documentation") in found
        assert ("migrate-documentation", "scaffold-documentation") in found


DOCUMENTATION_THREE = {"scaffold-documentation", "update-documentation", "migrate-documentation"}


class TestAGroupIsInstalledWhole:
    """They cannot do their job alone, so the grouping is declared rather than inferred."""

    @pytest.mark.parametrize("named", sorted(DOCUMENTATION_THREE))
    def test_naming_any_member_installs_all_of_them(self, load_script, named):
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups([named]) == DOCUMENTATION_THREE

    def test_naming_the_group_installs_its_members(self, load_script):
        """A project can ask for the capability without knowing the three skill names."""
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups(["documentation"]) == DOCUMENTATION_THREE

    def test_the_group_name_itself_is_not_installed(self, load_script):
        """`documentation` is a group, not a skill; delivering it would look for a directory."""
        lib = load_script("engine/badger_lib.py")

        assert "documentation" not in lib.expand_skill_groups(["documentation"])

    def test_an_ungrouped_skill_is_unchanged(self, load_script):
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups(["debug-issue"]) == {"debug-issue"}

    def test_an_unknown_name_passes_through_untouched(self, load_script):
        """Reporting an unknown include name is `inclusion_notes`' job, not this one's."""
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups(["no-such-skill"]) == {"no-such-skill"}

    def test_naming_two_members_is_the_same_as_naming_one(self, load_script):
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups(
            ["migrate-documentation", "update-documentation"]) == DOCUMENTATION_THREE

    def test_an_empty_request_stays_empty(self, load_script):
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups([]) == set()


class TestEveryCitedSiblingIsInTheSameGroup:
    """The guard that keeps the declaration honest as the catalog changes.

    A group is a claim that these skills travel together. A skill citing a sibling *outside* its
    group is the same bug in a new place — and the declaration cannot catch it, because a
    declaration only knows what it was told.
    """

    def test_no_skill_cites_a_sibling_it_does_not_travel_with(self, load_script, root):
        lib = load_script("engine/badger_lib.py")
        offenders = []
        for name, path in _catalog_skills(root):
            cited = {s for s, _ in SIBLING_REF_RE.findall(path.read_text(encoding="utf-8"))}
            travels_with = lib.expand_skill_groups([name])
            for sibling in cited - travels_with:
                offenders.append(f"{name} cites ../{sibling}/ but is not grouped with it")

        assert not offenders, "; ".join(offenders)

    def test_every_grouped_skill_exists_in_the_catalog(self, load_script, root):
        """A group naming a skill nobody has would silently install nothing for that name."""
        lib = load_script("engine/badger_lib.py")
        known = {name for name, _ in _catalog_skills(root)}

        for group, members in lib.SKILL_GROUPS.items():
            missing = [m for m in members if m not in known]
            assert not missing, f"group {group!r} names skills not in the catalog: {missing}"


class TestOptingIntoOneDeliversWhatItCites:
    """The end-to-end shape of #266: the reported bug, reproduced through the scaffolder."""

    def _scaffold(self, make_scaffolder, names):
        config = _config(agents=["claude"])
        config["include"] = {"skills": list(names)}
        target = make_scaffolder.target
        make_scaffolder(config=config, skills=["task"]).run(
            generated_at="2026-08-01T00:00:00Z")
        return target

    def test_the_cited_references_are_present_on_disk(self, make_scaffolder):
        target = self._scaffold(make_scaffolder, ["migrate-documentation"])
        skills = target / ".ai-badger" / "skills"

        assert (skills / "migrate-documentation" / "SKILL.md").is_file()
        for sibling, relpath in (
            ("update-documentation", "references/placement.md"),
            ("update-documentation", "references/trust.md"),
            ("update-documentation", "references/amendments.md"),
            ("scaffold-documentation", "references/structure.md"),
        ):
            assert (skills / sibling / relpath).is_file(), \
                f"migrate-documentation cites ../{sibling}/{relpath} and it did not arrive"

    def test_every_relative_path_in_the_delivered_skill_resolves(self, make_scaffolder):
        """Follow the paths as written, from where the skill actually sits."""
        target = self._scaffold(make_scaffolder, ["migrate-documentation"])
        home = target / ".ai-badger" / "skills" / "migrate-documentation"

        text = (home / "SKILL.md").read_text(encoding="utf-8")
        dangling = [
            f"../{sibling}/{relpath}"
            for sibling, relpath in SIBLING_REF_RE.findall(text)
            if not (home / ".." / sibling / relpath).resolve().is_file()
        ]

        assert not dangling, f"dangling after scaffold: {', '.join(dangling)}"

    def test_a_pulled_in_sibling_is_discoverable_too(self, make_scaffolder):
        """Delivered is not discoverable (#261) — the closure must not reintroduce that gap."""
        target = self._scaffold(make_scaffolder, ["migrate-documentation"])

        link = target / ".claude" / "skills" / "update-documentation"
        assert link.exists() and (link / "SKILL.md").is_file()

    def test_nothing_arrives_for_a_project_that_asked_for_nothing(self, make_scaffolder):
        """The closure must not turn an empty include into three installed skills."""
        target = self._scaffold(make_scaffolder, [])

        for name in ("migrate-documentation", "update-documentation", "scaffold-documentation"):
            assert not (target / ".ai-badger" / "skills" / name).exists()


class TestTheGuardCouldFail:
    """The regex is the whole guard; a dead pattern would pass every catalog forever."""

    def test_a_sibling_reference_is_matched(self):
        assert SIBLING_REF_RE.findall("see `../update-documentation/references/trust.md` for") == [
            ("update-documentation", "references/trust.md")]

    def test_an_own_reference_is_not_matched(self):
        assert not SIBLING_REF_RE.findall("see `references/structure.md` beside this file")

    @pytest.mark.parametrize("text", [
        "../../outside/references/x.md",
        "`../sibling/scripts/thing.py`",
    ])
    def test_unrelated_paths_are_not_matched_as_sibling_references(self, text):
        assert not SIBLING_REF_RE.findall(text)


class TestAGroupNameIsReportedAsValid:
    """Naming a group must not be reported as a mistake (#275 review).

    `expand_skill_groups` made "documentation" a legal value, but the reporting path still saw
    the raw config names — so a working config was reported as
    "matches no optIn catalog skill — safe to remove from config.json".

    A note that tells someone to delete config that works is worse than no note: it is acted on.
    """

    def test_the_group_name_is_not_called_a_mistake(self, load_script, root):
        lib = load_script("engine/badger_lib.py")
        addable = lib.opt_in_skills_in(root / "features" / "common" / "skills")

        notes = lib.inclusion_notes(["documentation"], [], addable)

        assert not any("safe to remove" in n for n in notes), notes

    def test_the_group_name_says_what_it_delivered(self, load_script, root):
        lib = load_script("engine/badger_lib.py")
        addable = lib.opt_in_skills_in(root / "features" / "common" / "skills")

        notes = lib.inclusion_notes(["documentation"], [], addable)

        joined = " ".join(notes)
        for member in DOCUMENTATION_THREE:
            assert member in joined, f"the note does not say {member} was delivered"

    def test_a_genuine_typo_is_still_reported(self, load_script, root):
        """The note must keep working — a guard that never fires would hide real mistakes."""
        lib = load_script("engine/badger_lib.py")
        addable = lib.opt_in_skills_in(root / "features" / "common" / "skills")

        notes = lib.inclusion_notes(["documentatoin"], [], addable)

        assert any("safe to remove" in n for n in notes), notes
