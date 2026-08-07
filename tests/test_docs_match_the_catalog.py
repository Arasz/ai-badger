"""Documentation that names a catalog fact must agree with the catalog.

`docs/skills.md` documented 23 of 37 skills while its own opening paragraph contradicted its own
table (14 + 8 = 22 != 21). Nothing checked it: `skills_lint` reads `SKILL.md` frontmatter and
`docs_guard` reads links, so a prose undercount is invisible to both. The same shape hit
`docs/scripts.md`, which lists the `tooling/` scripts by hand and lost two of them.

These checks derive every number from the source — `badger_lib.SKILL_SCOPES` for routing, the
catalog directories for stack-local skills, the filesystem for scripts — and never from the prose.
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

# How a declared scope reads in the `Ships` column.
SHIPS_BY_SCOPE = {"default": "default", "optIn": "opt-in"}

# Stack-local skills are declared by the stack that holds them, not by SKILL_SCOPES.
STACK_LOCAL_SKILL_DIRS = {"claude": "claude-only"}

SCRIPT_DIRS = ("engine", "tooling", "gates")


def _badger_lib(root: Path):
    """`SKILL_SCOPES` is the routing source of truth (ADR-0005)."""
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


def _catalog_skills(root: Path) -> dict:
    """`{skill name: expected Ships cell}` derived from the catalog, not from any document."""
    expected = {name: SHIPS_BY_SCOPE[scope]
                for name, scope in _badger_lib(root).SKILL_SCOPES.items()}
    for stack, ships in STACK_LOCAL_SKILL_DIRS.items():
        for skill in (root / "features" / stack / "skills").iterdir():
            if (skill / "SKILL.md").is_file():
                expected[skill.name] = ships
    return expected


def _one_count(pattern: re.Pattern, text: str, label: str) -> int:
    found = pattern.search(text)
    assert found, f"docs/skills.md no longer states the {label} in a checkable form"
    return int(found.group(1))


class TestSkillsDocCoversTheCatalog:
    """Every skill the catalog routes has a row, and every row names a skill that exists."""

    def test_no_catalog_skill_is_undocumented(self, root):
        undocumented = sorted(set(_catalog_skills(root)) - set(_documented_skills(_skills_doc(root))))

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
               len(_badger_lib(root).SKILL_SCOPES)

    @pytest.mark.parametrize("scope,pattern,label", [
        ("default", DEFAULT_TOTAL_RE, "default count"),
        ("optIn", OPT_IN_TOTAL_RE, "optIn count"),
    ])
    def test_each_scope_total_is_right(self, root, scope, pattern, label):
        scopes = _badger_lib(root).SKILL_SCOPES
        text = _skills_doc(root)

        assert _one_count(pattern, text, label) == sum(1 for s in scopes.values() if s == scope)


class TestScriptsDocCoversTheScripts:
    """`docs/scripts.md` is the only map of the runnable surface; an omitted script is invisible."""

    @pytest.mark.parametrize("directory", SCRIPT_DIRS)
    def test_every_script_is_named(self, root, directory):
        text = (root / "docs" / "scripts.md").read_text(encoding="utf-8")
        present = sorted(p.name for p in (root / directory).glob("*.py")
                         if not p.name.startswith("_"))

        missing = [name for name in present if f"`{name}`" not in text]

        assert not missing, f"docs/scripts.md omits {directory}/: {', '.join(missing)}"


class TestTheseChecksCouldFail:
    """Each assertion above must go red on a broken document; a green that cannot fail proves nothing."""

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

    def test_an_omitted_script_is_caught(self):
        text = "| `index_build.py` | Rebuild the index |"

        missing = [name for name in ("index_build.py", "validate.py") if f"`{name}`" not in text]

        assert missing == ["validate.py"]