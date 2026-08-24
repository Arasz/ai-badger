"""Skills that cannot work alone travel together — now as one gateway skill (ADR-0021).

`migrate-documentation` ships no `references/` of its own. Its body names four files by relative
sibling path — three under `update-documentation/references/`, one under
`scaffold-documentation/references/` — and says, deliberately, "read them where they live."

They used to be three flat `optIn` skills held together by `SKILL_GROUPS["documentation"]`,
because a project that named only `migrate-documentation` received a skill whose every reference
path was dangling, and nothing said so (#266). Since 0.137.0 they are members of the
`documentation` gateway: one registered router whose `manifest.json` declares them under its own
`references/`, delivered as one tree, with `gateway_aliases` resolving their old names. The
testing group (`design-tests` + `review-tests`, SYNTHESIS.md ruling A) remains a configuration
group in `SKILL_GROUPS`.

The guards keep the declarations honest: no skill may cite a sibling outside what travels with
it, every group must name real catalog skills, and the sibling-citation scan reaches into the
gateway's member tree — directory existence alone proves nothing about file-level citations.
"""
from __future__ import annotations

import re

import pytest

from scaffold_helpers import _config

# The lookbehind matters: `../../outside/references/x.md` reaches past the skills directory and
# is not a sibling reference. Without it the guard would treat one as resolvable and never say so.
SIBLING_REF_RE = re.compile(r"(?<![./])\.\./([a-z][a-z0-9-]*)/(references/[a-z-]+\.md)")

# Level-1 registration plus the documentation gateway's member tree (ADR-0021): the members sit
# below the agents' reach, so the citation guard must descend deliberately.
SKILL_MD_GLOBS = (
    "features/*/skills/*/SKILL.md",
    "features/common/skills/documentation/references/*/SKILL.md",
)


def _catalog_skills(root):
    for pattern in SKILL_MD_GLOBS:
        for path in sorted(root.glob(pattern)):
            yield path.parent.name, path


DOCUMENTATION_MEMBERS = {"scaffold-documentation", "update-documentation",
                         "migrate-documentation"}


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


class TestTheDocumentationGatewayInstallsWhole:
    """One registered name delivers the members and everything they cite (ADR-0021)."""

    def test_naming_the_gateway_passes_through_as_itself(self, load_script):
        """`documentation` is a real registered skill now, so expansion adds nothing (R10)."""
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups(["documentation"]) == {"documentation"}

    @pytest.mark.parametrize("named", sorted(DOCUMENTATION_MEMBERS))
    def test_no_stale_member_name_survives_expansion(self, load_script, named):
        """A member's old name expands to itself only; the alias map does the resolving."""
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups([named]) == {named}

    def test_the_gateway_manifest_names_every_member(self, root, load_script):
        import json

        manifest = json.loads(
            (root / "features/common/skills/documentation/manifest.json").read_text(
                encoding="utf-8"))
        assert manifest["kind"] == "gateway"
        assert {m["name"] for m in manifest["members"]} == DOCUMENTATION_MEMBERS

    def test_the_alias_map_resolves_every_member_to_documentation(self, root, load_script):
        lib = load_script("engine/badger_lib.py")

        aliases = lib.gateway_aliases(root)

        assert {name: aliases[name] for name in DOCUMENTATION_MEMBERS} == \
            {name: "documentation" for name in DOCUMENTATION_MEMBERS}


TESTING_TWO = {"design-tests", "review-tests"}


class TestTheTestingGroupIsInstalledWhole:
    """`design-tests` and `review-tests` share one ruleset (SYNTHESIS.md ruling A) and are
    grouped for the same reason the documentation trio once were: neither works with the other
    absent from disk, so `SKILL_GROUPS["testing"]` makes naming either one install both.
    """

    @pytest.mark.parametrize("named", sorted(TESTING_TWO))
    def test_naming_either_member_installs_both(self, load_script, named):
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups([named]) == TESTING_TWO

    def test_naming_the_group_installs_both_members(self, load_script):
        lib = load_script("engine/badger_lib.py")

        assert lib.expand_skill_groups(["testing"]) == TESTING_TWO

    def test_the_group_name_itself_is_not_installed(self, load_script):
        lib = load_script("engine/badger_lib.py")

        assert "testing" not in lib.expand_skill_groups(["testing"])

    def test_both_members_declare_scope_default(self, load_script, root):
        """Ruling I: `scope: default` is how "required" is achieved — availability, not a
        third mechanism. Both skills must ship unasked, or the invariant call sites (task
        Phase 1/3, code-review-checklist §3.1) would be pointing at an opt-in skill.
        """
        lib = load_script("engine/badger_lib.py")
        skills_dir = root / "features" / "common" / "skills"

        assert TESTING_TWO <= set(lib.default_skills_in(skills_dir))


class TestEveryCitedSiblingTravelsWithItsCiter:
    """The guard that keeps the declarations honest as the catalog changes."""

    def test_no_skill_cites_a_sibling_it_does_not_sit_beside(self, root):
        offenders = []
        for name, path in _catalog_skills(root):
            home = path.parents[1]
            cited = {s for s, _ in SIBLING_REF_RE.findall(path.read_text(encoding="utf-8"))}
            for sibling in sorted(cited):
                if not (home / sibling).is_dir():
                    offenders.append(f"{name} cites ../{sibling}/ which does not sit beside it")

        assert not offenders, "; ".join(offenders)

    def test_every_grouped_skill_exists_in_the_catalog(self, load_script, root):
        """A group naming a skill nobody has would silently install nothing for that name."""
        lib = load_script("engine/badger_lib.py")
        known = {path.parent.name for path in root.glob("features/*/skills/*/SKILL.md")}

        for group, members in lib.SKILL_GROUPS.items():
            missing = [m for m in members if m not in known]
            assert not missing, f"group {group!r} names skills not in the catalog: {missing}"


class TestOptingIntoTheGatewayDeliversWhatItsMembersCite:
    """The end-to-end shape, updated for the gateway: one name, one tree, no dangling paths."""

    def _scaffold(self, make_scaffolder, names):
        config = _config(agents=["claude"])
        config["include"] = {"skills": list(names)}
        target = make_scaffolder.target
        make_scaffolder(config=config, skills=["task"]).run(
            generated_at="2026-08-01T00:00:00Z")
        return target

    def test_the_gateway_and_its_members_arrive(self, make_scaffolder):
        target = self._scaffold(make_scaffolder, ["documentation"])
        home = target / ".ai-badger" / "skills" / "documentation"

        assert (home / "SKILL.md").is_file()
        for member in sorted(DOCUMENTATION_MEMBERS):
            assert (home / "references" / member / "SKILL.md").is_file(), \
                f"{member} did not arrive inside the gateway"

    def test_every_relative_path_in_a_delivered_member_resolves(self, make_scaffolder):
        """Follow the paths as written, from where the member actually sits."""
        target = self._scaffold(make_scaffolder, ["documentation"])
        migrate = target / ".ai-badger" / "skills" / "documentation" / "references" / \
            "migrate-documentation"

        text = (migrate / "SKILL.md").read_text(encoding="utf-8")
        dangling = [
            f"../{sibling}/{relpath}"
            for sibling, relpath in SIBLING_REF_RE.findall(text)
            if not (migrate / ".." / sibling / relpath).resolve().is_file()
        ]

        assert not dangling, f"dangling after scaffold: {', '.join(dangling)}"

    def test_the_gateway_is_discoverable_too(self, make_scaffolder):
        """Delivered is not discoverable (#261) — the gateway must be linked, members need not."""
        target = self._scaffold(make_scaffolder, ["documentation"])

        link = target / ".claude" / "skills" / "documentation"
        assert link.exists() and (link / "SKILL.md").is_file()

    def test_nothing_arrives_for_a_project_that_asked_for_nothing(self, make_scaffolder):
        target = self._scaffold(make_scaffolder, [])

        assert not (target / ".ai-badger" / "skills" / "documentation").exists()


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


class TestGatewayNamesAreReportedAsValid:
    """Naming the gateway — or a name it absorbed — must never read as a mistake (#275 guard).

    A note that tells someone to delete config that works is worse than no note: it is acted on.
    """

    def test_naming_the_gateway_reports_an_ordinary_opt_in_include(self, load_script, root):
        lib = load_script("engine/badger_lib.py")
        skills_dir = root / "features" / "common" / "skills"
        addable = lib.opt_in_skills_in(skills_dir)

        notes = lib.inclusion_notes(["documentation"], [], addable,
                                    lib.default_skills_in(skills_dir))

        joined = "\n".join(notes)
        assert "included optIn skill 'documentation'" in joined, joined
        assert "safe to remove" not in joined, joined

    def test_a_stale_member_name_resolves_instead_of_being_called_a_mistake(
            self, load_script, root):
        """R4: the alias map turns an absorbed name into a resolution, never a warning."""
        lib = load_script("engine/badger_lib.py")
        skills_dir = root / "features" / "common" / "skills"
        addable = lib.opt_in_skills_in(skills_dir)
        aliases = lib.gateway_aliases(root)

        notes = lib.inclusion_notes(["update-documentation"], [], addable,
                                    lib.default_skills_in(skills_dir), aliases=aliases)

        joined = "\n".join(notes)
        assert "resolved to gateway 'documentation'" in joined, joined
        assert "safe to remove" not in joined, joined

    def test_a_genuine_typo_is_still_reported(self, load_script, root):
        """The note must keep working — a guard that never fires would hide real mistakes."""
        lib = load_script("engine/badger_lib.py")
        skills_dir = root / "features" / "common" / "skills"
        addable = lib.opt_in_skills_in(skills_dir)

        notes = lib.inclusion_notes(["documentatoin"], [], addable,
                                    lib.default_skills_in(skills_dir),
                                    aliases=lib.gateway_aliases(root))

        assert any("safe to remove" in n for n in notes), notes

    def test_excluding_a_stale_member_declines_the_whole_gateway(self, load_script):
        """R5: exclude is the mirror of include."""
        lib = load_script("engine/badger_lib.py")

        declined = lib.exclusions({"exclude": {"skills": ["scaffold-documentation"]}},
                                  aliases={"scaffold-documentation": "documentation"})

        assert declined["skills"] >= {"scaffold-documentation", "documentation"}
