"""Gateway skills: the manifest contract (lint rule 13) and the alias map it feeds.

A gateway is a registered level-1 skill directory carrying ``manifest.json``. Its members live
under ``references/<member>/`` — one nesting level deeper than registration reaches — so the
manifest is the only declaration that they exist, and rule 13 is what keeps that declaration
honest: every member present, none extra, every ``purpose`` copied verbatim from the member's
own frontmatter description (derive-or-delete).

The same manifests feed ``badger_lib.gateway_aliases``: a stale config name that used to be a
flat skill resolves to the gateway that absorbed it. Ambiguity — one member name claimed by two
gateways — is never resolved silently.
"""
from __future__ import annotations

import json

import pytest
from conftest import _test_write
from scaffold_helpers import _config

MEMBER_DESCRIPTION = (
    "Use when member a is needed: it covers the whole workflow and cannot work alone.")


def _frontmatter(name, description, scope="optIn"):
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: \"{description}\"\n"
        f"version: 1.0.0\n"
        f"author: ai-badger\n"
        f"license: MIT\n"
        f"platforms: [linux, macos, windows]\n"
        f"scope: {scope}\n"
        f"metadata:\n"
        f"  hermes:\n"
        f"    tags: [tests]\n"
        f"    related_skills: []\n"
        f"---\n"
    )


_ROUTER_BODY = (
    "# Doc gateway\n\n"
    "Read `manifest.json` when choosing which member to open.\n\n"
    "## Gotchas\n\n"
    "No environment-specific gotchas known.\n"
)


def _write_member(gateway_dir, name, description=MEMBER_DESCRIPTION):
    member = gateway_dir / "references" / name
    member.mkdir(parents=True)
    # Members sit below registration depth: minimal frontmatter, no scope needed.
    _test_write(member / "SKILL.md",
                f"---\nname: {name}\ndescription: \"{description}\"\n---\n\n# {name}\n",
                encoding="utf-8")
    return member


def _manifest(members=("member-a",), kind="gateway", **overrides):
    entry = {
        "kind": kind,
        "members": [
            {"name": name, "purpose": MEMBER_DESCRIPTION, "triggers": ["member", "a"],
             "paths": {"skill": f"references/{name}"}}
            for name in members
        ],
    }
    entry.update(overrides)
    return entry


def _write_gateway(tmp_path, manifest=None, name="doc-gateway", stack="common",
                   body=_ROUTER_BODY, frontmatter=None, members=("member-a",)):
    """A canonical gateway skill dir: lint-clean SKILL.md plus manifest.json and its members."""
    d = tmp_path / "features" / stack / "skills" / name
    d.mkdir(parents=True)
    _test_write(d / "SKILL.md", (frontmatter or _frontmatter(
        name, f"Use when {name} routes to a member.")) + body, encoding="utf-8")
    for member in members:
        _write_member(d, member)
    if manifest is not None:
        _test_write(d / "manifest.json",
                    manifest if isinstance(manifest, str) else json.dumps(manifest),
                    encoding="utf-8")
    return d


def _rule13(violations):
    return [v for v in violations if "rule 13" in v]


# ------------------------------------------------------------------ T1: the manifest is read
class TestAManifestMustBeValid:
    """A manifest that does not parse, or does not declare the gateway kind, is not a pass."""

    def test_a_manifest_without_the_gateway_kind_fails_lint(self, tmp_path, load_script):
        lint = load_script("gates/skills_lint.py")
        _write_gateway(tmp_path, manifest=_manifest(kind="something-else"))

        assert _rule13(lint.skills_lint(tmp_path)), "a kind-less manifest read as a pass"

    def test_an_unparseable_manifest_fails_lint(self, tmp_path, load_script):
        lint = load_script("gates/skills_lint.py")
        _write_gateway(tmp_path, manifest="{not json")

        assert _rule13(lint.skills_lint(tmp_path))

    def test_a_well_formed_manifest_passes_rule_13(self, tmp_path, load_script):
        lint = load_script("gates/skills_lint.py")
        _write_gateway(tmp_path, manifest=_manifest())

        assert not _rule13(lint.skills_lint(tmp_path)), lint.skills_lint(tmp_path)

    def test_empty_members_and_missing_triggers_fail(self, tmp_path, load_script):
        lint = load_script("gates/skills_lint.py")
        _write_gateway(tmp_path, manifest=_manifest())
        manifest_path = tmp_path / "features/common/skills/doc-gateway/manifest.json"
        broken = _manifest()
        broken["members"] = [{"name": "member-a", "purpose": MEMBER_DESCRIPTION,
                              "triggers": [], "paths": {"skill": "references/member-a"}}]
        _test_write(manifest_path, json.dumps(broken), encoding="utf-8")

        assert _rule13(lint.skills_lint(tmp_path))


# ------------------------------------------------------------------ T2: member paths exist
def test_manifest_member_path_must_exist(tmp_path, load_script):
    """A ghost member path is a silent routing dead end: renamed away, still advertised."""
    lint = load_script("gates/skills_lint.py")
    gateway = _write_gateway(tmp_path, manifest=_manifest())

    (gateway / "references" / "member-a").rename(gateway / "references" / "renamed-away")

    problems = _rule13(lint.skills_lint(tmp_path))
    assert problems and "member-a" in problems[0]


# ------------------------------------------------------------------ T3: orphans
def test_orphan_member_dir_under_references_fails_lint(tmp_path, load_script):
    """The silent-disappearance hazard: a skill moved in, the manifest forgotten."""
    lint = load_script("gates/skills_lint.py")
    gateway = _write_gateway(tmp_path, manifest=_manifest())

    stray = gateway / "references" / "stray-skill"
    stray.mkdir()
    _test_write(stray / "SKILL.md", "---\nname: stray-skill\n---\nbody\n", encoding="utf-8")

    problems = _rule13(lint.skills_lint(tmp_path))
    assert problems and "stray-skill" in problems[0]


# ------------------------------------------------------------------ T4: names line up
def test_member_name_must_match_directory_and_be_unique(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    manifest = _manifest(("member-a", "member-b"))
    manifest["members"][1]["name"] = "member-a"  # duplicate, and neither matches member-b's dir
    _write_gateway(tmp_path, manifest=manifest, members=("member-a", "member-b"))

    problems = "\n".join(_rule13(lint.skills_lint(tmp_path)))

    assert "unique" in problems or "duplicate" in problems, problems


# ------------------------------------------------------------------ R9: purpose is derived
def test_purpose_must_equal_the_member_description_byte_for_byte(tmp_path, load_script):
    """Derive-or-delete: the manifest may not paraphrase what the member already declares."""
    lint = load_script("gates/skills_lint.py")
    manifest = _manifest()
    manifest["members"][0]["purpose"] = "Use when member a is roughly needed."
    _write_gateway(tmp_path, manifest=manifest)

    problems = _rule13(lint.skills_lint(tmp_path))

    assert problems and "purpose" in problems[0]


# ------------------------------------------------------------------ T5: no lint exemption
def test_gateway_skill_md_is_fully_linted(tmp_path, load_script):
    """The gateway itself stays under every existing rule — there is no gateway exemption."""
    lint = load_script("gates/skills_lint.py")
    stripped = _frontmatter("doc-gateway", "Use when doc-gateway routes to a member.")
    stripped = stripped.replace("version: 1.0.0\n", "")
    _write_gateway(tmp_path, manifest=_manifest(), frontmatter=stripped)

    bad = lint.skills_lint(tmp_path)

    assert any("rule 10" in v and "version" in v for v in bad), bad


# ------------------------------------------------------------------ T12: the alias map
class TestGatewayAliases:
    """badger_lib.gateway_aliases derives member -> gateway from disk, never a literal."""

    def test_members_map_to_their_gateway(self, tmp_path, load_script):
        bl = load_script("engine/badger_lib.py")
        _write_gateway(tmp_path, manifest=_manifest(), name="gateway-one",
                       members=("member-a",))
        _write_gateway(tmp_path, manifest=_manifest(("member-x",)), name="gateway-two",
                       members=("member-x",))

        assert bl.gateway_aliases(tmp_path) == {"member-a": "gateway-one",
                                                "member-x": "gateway-two"}

    def test_an_ambiguous_member_name_is_never_silent(self, tmp_path, load_script):
        bl = load_script("engine/badger_lib.py")
        _write_gateway(tmp_path, manifest=_manifest(), name="gateway-one",
                       members=("member-a",))
        _write_gateway(tmp_path, manifest=_manifest(), name="gateway-two",
                       members=("member-a",))

        with pytest.raises(Exception, match="member-a"):
            bl.gateway_aliases(tmp_path)

    def test_directories_without_a_manifest_are_ignored(self, tmp_path, load_script):
        bl = load_script("engine/badger_lib.py")
        _write_gateway(tmp_path, manifest=None, name="plain-skill", members=("member-a",))
        import shutil
        shutil.rmtree(tmp_path / "features/common/skills/plain-skill/references")

        assert bl.gateway_aliases(tmp_path) == {}


# ------------------------------------------------------------------ R4: notes know the alias
class TestInclusionNotesAreAliasAware:
    """A stale member name resolves loudly, and is never called a mistake (#275 guard)."""

    ALIASES = {"update-documentation": "documentation"}

    def _notes(self, lib, root, included):
        skills_dir = root / "features" / "common" / "skills"
        return lib.inclusion_notes(included, [], lib.opt_in_skills_in(skills_dir),
                                   lib.default_skills_in(skills_dir),
                                   aliases=self.ALIASES)

    def test_a_stale_member_name_resolves_to_its_gateway(self, load_script, root):
        lib = load_script("engine/badger_lib.py")

        notes = self._notes(lib, root, ["update-documentation"])

        joined = "\n".join(notes)
        assert "resolved to gateway 'documentation'" in joined, joined
        assert "safe to remove" not in joined, joined

    def test_a_genuine_typo_is_still_reported(self, load_script, root):
        lib = load_script("engine/badger_lib.py")

        notes = self._notes(lib, root, ["documentatoin"])

        assert any("safe to remove" in n for n in notes), notes


# ------------------------------------------------------------------ R5: exclusions too
def test_excluding_a_stale_member_suppresses_the_gateway(load_script):
    """Excluding must stay the mirror of including: a stale name declines the whole gateway."""
    lib = load_script("engine/badger_lib.py")
    config = {"exclude": {"skills": ["update-documentation"]}}

    declined = lib.exclusions(config, aliases={"update-documentation": "documentation"})

    assert "documentation" in declined["skills"]


# ------------------------------------------------------------------ R3: extensions travel
class TestMemberExtensionsTravelWithTheGateway:
    """The trio's ledger fragments move inside their member dirs and stay live there (R3)."""

    def test_a_docs_tool_project_still_gets_the_ledger_fragment(self, make_scaffolder):
        config = _config()
        config["docs"] = {"tool": "ledgertool"}
        config["include"] = {"skills": ["documentation"]}
        scaf = make_scaffolder(config=config, skills=["task"])
        scaf.run(generated_at="2026-08-24T00:00:00Z")

        delivered = scaf.target / ".ai-badger" / "skills" / "documentation"
        ledger = (delivered / "references" / "scaffold-documentation" / "extensions" / "ledger")
        assert ledger.is_dir(), "the ledger fragment did not arrive inside its member dir"

    def test_an_unset_docs_tool_prunes_the_ledger_fragment(self, make_scaffolder):
        config = _config()
        config["include"] = {"skills": ["documentation"]}
        scaf = make_scaffolder(config=config, skills=["task"])
        result = scaf.run(generated_at="2026-08-24T00:00:00Z")

        delivered = scaf.target / ".ai-badger" / "skills" / "documentation"
        ledger = (delivered / "references" / "scaffold-documentation" / "extensions" / "ledger")
        assert not ledger.exists(), "an unmet requirement left the ledger fragment behind"
        assert any("skipped (config requirements not met)" in n for n in result["notes"])
