"""Documentation that names a catalog fact must agree with the catalog.

`docs/skills.md` documented 23 of 37 skills while its own opening paragraph contradicted its own
table (14 + 8 = 22 != 21). Nothing checked it: `skills_lint` reads `SKILL.md` frontmatter and
`docs_guard` reads links, so a prose undercount is invisible to both. The same shape hit
`docs/scripts.md`, which lists the `tooling/` scripts by hand and lost two of them.

These checks derive every number from the source — each skill's own `scope:` frontmatter for
routing, the catalog directories for stack-local skills, the filesystem for scripts — and never
from the prose.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# `| [name](#anchor) | purpose | ships | invoked how |` — the "At a glance" row shape.
SKILL_ROW_RE = re.compile(r"^\|\s*\[([a-z0-9-]+)\]\(#[a-z0-9-]+\)\s*\|[^|]*\|\s*([^|]+?)\s*\|")

# Prose counts, each written as a numeral so it can be checked rather than admired.
CATALOG_TOTAL_RE = re.compile(r"catalogs (\d+) skills")
COMMON_TOTAL_RE = re.compile(r"(\d+) live under `features/common/skills/`")
DEFAULT_TOTAL_RE = re.compile(r"\*\*(\d+) are `default`\*\*")
OPT_IN_TOTAL_RE = re.compile(r"\*\*(\d+) are `optIn`\*\*")
# The tree sentence: "**These 48 are not the whole tree.**
# `features/*/skills/*/SKILL.md` matches **54** files:" — both regexes are anchored to that
# literal so they cannot match a different sentence that happens to share a fragment.
TREE_TOTAL_RE = re.compile(r"`features/\*/skills/\*/SKILL\.md` matches \*\*(\d+)\*\* files")
THESE_TOTAL_RE = re.compile(r"\*\*These (\d+) are not the whole tree\.\*\*")

SKILLS_GLOB = "features/*/skills/*/SKILL.md"

# How a declared scope reads in the `Ships` column.
SHIPS_BY_SCOPE = {"default": "default", "optIn": "opt-in"}

# Stack-local skills are declared by the stack directory that holds them, not by a `scope:`.
STACK_LOCAL_SKILL_DIRS = {"claude": "claude-only"}

SCRIPT_DIRS = ("engine", "tooling", "gates")

# L10-4: `docs/framework-architecture.md` and `README.md` each carried a hand-written skill
# inventory (a total, a `default`/`optIn` split, and a member list) that drifted from the
# catalog after c8da0f0 and f9c6f28 (ADR-0028/0029) — "Thirty-six skills ... The fourteen with
# `scope: default` ... The other twenty-two are `optIn`" and its README/mermaid echoes. Unlike
# `docs/skills.md`, these two pages get no derived-count check: they must instead carry no
# hand-written count at all, digit or spelled out, so there is nothing left to drift.
HAND_WRITTEN_SKILL_COUNT_RE = re.compile(r"\b\d+ (skills|default|optIn)\b")

_NUMBER_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty)(?:-(?:one|two|three|"
    r"four|five|six|seven|eight|nine))?"
)
SPELLED_OUT_SKILL_COUNT_RE = re.compile(rf"\b{_NUMBER_WORD}\b\s+skills\b", re.IGNORECASE)

NO_HAND_COUNT_DOCS = ("docs/framework-architecture.md", "README.md")


def _unescape_mermaid_breaks(text: str) -> str:
    """A mermaid node label spells its line break as a literal ``\\n``, not a real newline
    (`SKILLSDIR["...skills/\\n14 default: ..."]`). Left alone, the digit run out of it
    (`skills/\\n14`) sits right after the escape's `n`, which is a word character too, so
    `\\b\\d+` never gets a boundary to match at. Unescaping to a space first restores it."""
    return text.replace("\\n", " ")


def _badger_lib(root: Path):
    """`skill_scope_in` reads the routing source of truth: the skill itself (ADR-0018)."""
    engine = str(root / "engine")
    if engine not in sys.path:
        sys.path.insert(0, engine)
    import badger_lib  # pylint: disable=import-outside-toplevel

    return badger_lib


def _skills_doc(root: Path) -> str:
    return (root / "docs" / "skills.md").read_text(encoding="utf-8")


def _documented_skills(text: str) -> dict:
    """`{skill name: Ships cell}` for every row of the at-a-glance table."""
    rows = {}
    for line in text.splitlines():
        match = SKILL_ROW_RE.match(line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def _common_scopes(root: Path) -> dict:
    """`{skill name: declared scope}` for the common catalog, read from each SKILL.md."""
    bl = _badger_lib(root)
    return {d.name: bl.skill_scope_in(d)
            for d in sorted((root / "features" / "common" / "skills").iterdir())
            if (d / "SKILL.md").is_file()}


def _catalog_skills(root: Path) -> dict:
    """`{skill name: expected Ships cell}` derived from the catalog, not from any document."""
    expected = {name: SHIPS_BY_SCOPE[scope]
                for name, scope in _common_scopes(root).items()}
    for stack, ships in STACK_LOCAL_SKILL_DIRS.items():
        for skill in (root / "features" / stack / "skills").iterdir():
            if (skill / "SKILL.md").is_file():
                expected[skill.name] = ships
    return expected


def _one_count(pattern: re.Pattern, text: str, label: str) -> int:
    found = pattern.findall(text)
    assert len(found) == 1, (
        f"docs/skills.md states the {label} {len(found)} times, expected exactly once")
    return int(found[0])


class TestSkillsDocCoversTheCatalog:
    """Every skill the catalog routes has a row, and every row names a skill that exists."""

    def test_no_catalog_skill_is_undocumented(self, root):
        documented = _documented_skills(_skills_doc(root))
        undocumented = sorted(set(_catalog_skills(root)) - set(documented))

        assert not undocumented, (
                "docs/skills.md has no at-a-glance row for: " + ", ".join(undocumented)
        )

    def test_no_row_names_a_skill_the_catalog_does_not_have(self, root):
        stale = sorted(set(_documented_skills(_skills_doc(root))) - set(_catalog_skills(root)))

        assert not stale, (
                "docs/skills.md documents skills that are not in the catalog: " + ", ".join(stale)
        )

    def test_each_row_reports_the_declared_scope(self, root):
        documented = _documented_skills(_skills_doc(root))
        expected = _catalog_skills(root)

        wrong = sorted(f"{name}: doc says {documented[name]!r}, catalog says {ships!r}"
                       for name, ships in expected.items()
                       if name in documented and documented[name] != ships)

        assert not wrong, "docs/skills.md misreports how a skill ships:\n  " + "\n  ".join(wrong)

    def test_the_check_sees_the_whole_table(self, root):
        """A regex that stops matching would pass both directions vacuously."""
        assert len(_documented_skills(_skills_doc(root))) >= 20


class TestSkillsDocCountsAreDerived:
    """The opening paragraph's numerals are claims about the catalog, so they are checked."""

    def test_the_catalog_total_is_right(self, root):
        text = _skills_doc(root)

        assert _one_count(CATALOG_TOTAL_RE, text, "catalog total") == len(_catalog_skills(root))

    def test_the_common_total_is_right(self, root):
        text = _skills_doc(root)

        assert _one_count(COMMON_TOTAL_RE, text, "features/common total") == \
               len(_common_scopes(root))

    @pytest.mark.parametrize("scope,pattern,label", [
        ("default", DEFAULT_TOTAL_RE, "default count"),
        ("optIn", OPT_IN_TOTAL_RE, "optIn count"),
    ])
    def test_each_scope_total_is_right(self, root, scope, pattern, label):
        scopes = _common_scopes(root)
        text = _skills_doc(root)

        assert _one_count(pattern, text, label) == sum(1 for s in scopes.values() if s == scope)

    def test_the_tree_total_is_right(self, root):
        """The glob numeral is a claim too, and nothing derived it before."""
        text = _skills_doc(root)
        globbed = list((root / "features").glob("*/skills/*/SKILL.md"))

        assert _one_count(TREE_TOTAL_RE, text, "tree total") == len(globbed)

    def test_the_these_sentence_matches_the_page_total(self, root):
        """"These N are not the whole tree" counts the skills this page documents."""
        text = _skills_doc(root)

        assert _one_count(THESE_TOTAL_RE, text, "'These N' total") == \
               len(_catalog_skills(root))


class TestScriptsDocCoversTheScripts:
    """`docs/scripts.md` is the only map of the runnable surface; an omitted script is invisible."""

    @pytest.mark.parametrize("directory", SCRIPT_DIRS)
    def test_every_script_is_named(self, root, directory):
        text = (root / "docs" / "scripts.md").read_text(encoding="utf-8")
        present = sorted(p.name for p in (root / directory).glob("*.py")
                         if not p.name.startswith("_"))

        missing = [name for name in present if f"`{name}`" not in text]

        assert not missing, f"docs/scripts.md omits {directory}/: {', '.join(missing)}"


class TestNoHandWrittenSkillCounts:
    """`docs/framework-architecture.md` and `README.md` (including its mermaid diagram) name no
    skill count of their own, digit or spelled out: `docs/skills.md` is the one page that counts,
    and it derives its numbers (see `TestSkillsDocCountsAreDerived` above)."""

    @pytest.mark.parametrize("relpath", NO_HAND_COUNT_DOCS)
    def test_no_digit_skill_count(self, root, relpath):
        text = _unescape_mermaid_breaks((root / relpath).read_text(encoding="utf-8"))
        found = HAND_WRITTEN_SKILL_COUNT_RE.findall(text)

        assert not found, f"{relpath} states a hand-written skill count: {found}"

    @pytest.mark.parametrize("relpath", NO_HAND_COUNT_DOCS)
    def test_no_spelled_out_skill_count(self, root, relpath):
        text = _unescape_mermaid_breaks((root / relpath).read_text(encoding="utf-8"))
        found = SPELLED_OUT_SKILL_COUNT_RE.findall(text)

        assert not found, f"{relpath} states a spelled-out skill count: {found}"


class TestTheseChecksCouldFail:
    """Each assertion above must go red on a broken document, or it proves nothing."""

    def test_the_digit_pattern_catches_the_regression(self):
        mermaid_node = _unescape_mermaid_breaks(
            r'SKILLSDIR["features/common/skills/\n14 default: welcome'
            r'\n22 optIn (scope: optIn in each SKILL.md)"]'
        )

        assert HAND_WRITTEN_SKILL_COUNT_RE.search("36 skills live under `features/common/skills/`.")
        assert HAND_WRITTEN_SKILL_COUNT_RE.findall(mermaid_node) == ["default", "optIn"]

    def test_the_spelled_out_pattern_catches_the_regression(self):
        assert SPELLED_OUT_SKILL_COUNT_RE.search(
            "Thirty-six skills live under `features/common/skills/`.")

    def test_a_deleted_row_is_caught(self):
        catalog = {"task", "den-refresh"}
        documented = _documented_skills("| [task](#task) | Run one task | default | by name |")

        assert sorted(catalog - set(documented)) == ["den-refresh"]

    def test_an_orphaned_row_is_caught(self):
        catalog = {"task"}
        documented = _documented_skills(
            "| [task](#task) | Run one task | default | by name |\n"
            "| [retired](#retired) | Gone from the catalog | opt-in | by name |\n"
        )

        assert sorted(set(documented) - catalog) == ["retired"]

    def test_a_wrong_ships_column_is_caught(self):
        documented = _documented_skills("| [task](#task) | Run one task | opt-in | by name |")

        assert documented["task"] != SHIPS_BY_SCOPE["default"]

    def test_a_stale_count_is_caught(self):
        assert _one_count(CATALOG_TOTAL_RE, "ai-badger catalogs 22 skills.", "total") == 22

    def test_a_stale_tree_total_is_caught(self):
        assert _one_count(TREE_TOTAL_RE,
                          "`features/*/skills/*/SKILL.md` matches **99** files",
                          "tree total") == 99
        assert _one_count(THESE_TOTAL_RE, "**These 3 are not the whole tree.**", "these") == 3

    def test_a_doubled_tree_sentence_is_caught(self):
        doubled = ("`features/*/skills/*/SKILL.md` matches **54** files; "
                   "`features/*/skills/*/SKILL.md` matches **54** files")
        with pytest.raises(AssertionError):
            _one_count(TREE_TOTAL_RE, doubled, "tree total")

    def test_an_omitted_script_is_caught(self):
        text = "| `index_build.py` | Rebuild the index |"

        missing = [name for name in ("index_build.py", "validate.py") if f"`{name}`" not in text]

        assert missing == ["validate.py"]