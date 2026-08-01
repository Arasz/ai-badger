"""The plugin copy of a skill says it is the generic one (D1).

A project with the plugin installed *and* a scaffold registers every skill twice: once bare from
`.claude/skills/`, once as `ai-badger:<name>` from the plugin. Measured on 2026-08-01, the two
copies of `code-review-checklist` had **byte-identical frontmatter** (md5 `503cde95…`) and bodies
differing by 28 lines — the scaffolded one carries six merged extensions.

Name and description are all an agent sees before choosing. Identical name, identical
description, different body: a coin flip where one face silently lacks the project's own checks.

So the plugin's `SKILL.md` keeps its frontmatter and carries a pointer instead of the procedure,
and the procedure moves to `SKILL.full.md` beside it. The agent gets a reason to prefer the
scaffolded copy; a plugin-only user loses nothing, because the pointer names the file that has
the whole thing.

Three skills keep their body inline: `welcome-ai-badger` creates the scaffold, and `den-refresh`
and `feed-badger` must run the framework's own copy — ADR-0011 makes that load-bearing across a
breaking version boundary.
"""
from __future__ import annotations

import re

import pytest

SHIPPED = "skills"


def _sync(load_script):
    return load_script("tooling/sync_plugin_skills.py")


def _frontmatter(text: str) -> str:
    parts = text.split("---")
    return parts[1] if len(parts) > 2 else ""


def _body(text: str) -> str:
    parts = text.split("---", 2)
    return parts[2] if len(parts) > 2 else text


class TestTheBootstrapThreeKeepTheirBody:
    """A pointer here would be circular or broken: these run before or without a scaffold."""

    @pytest.mark.parametrize("name", ["welcome-ai-badger", "den-refresh", "feed-badger"])
    def test_the_body_is_inline(self, root, name):
        shipped = root / SHIPPED / name / "SKILL.md"
        source = root / "features" / "common" / "skills" / name / "SKILL.md"

        assert shipped.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
        assert not (root / SHIPPED / name / "SKILL.full.md").exists()


class TestEveryOtherPluginCopyPoints:
    """The scaffolded copy is the tailored one; the plugin copy has to say so."""

    def _pointing(self, root):
        for skill_dir in sorted((root / SHIPPED).iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name in {"welcome-ai-badger", "den-refresh", "feed-badger"}:
                continue
            yield skill_dir

    def test_the_frontmatter_is_untouched(self, root):
        """Description drives triggering. A pointer must not change what the skill matches on."""
        for skill_dir in self._pointing(root):
            source = _find_source(root, skill_dir.name)
            shipped_fm = _frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
            source_fm = _frontmatter(source.read_text(encoding="utf-8"))

            assert shipped_fm == source_fm, f"{skill_dir.name}: frontmatter changed"

    def test_the_body_is_a_pointer(self, root):
        for skill_dir in self._pointing(root):
            body = _body((skill_dir / "SKILL.md").read_text(encoding="utf-8"))

            assert ".ai-badger/skills/" in body, f"{skill_dir.name}: no scaffolded path named"
            assert "SKILL.full.md" in body, f"{skill_dir.name}: does not name the full procedure"

    def test_the_full_procedure_is_beside_it(self, root):
        """Nothing is lost: a plugin-only user still has the whole skill, one file away."""
        for skill_dir in self._pointing(root):
            full = skill_dir / "SKILL.full.md"
            source = _find_source(root, skill_dir.name)

            assert full.is_file(), f"{skill_dir.name}: SKILL.full.md missing"
            assert _body(source.read_text(encoding="utf-8")).strip() in \
                full.read_text(encoding="utf-8")

    def test_the_pointer_is_short(self, root):
        """It is read on every turn the skill is considered; it is not a second skill."""
        for skill_dir in self._pointing(root):
            body = _body((skill_dir / "SKILL.md").read_text(encoding="utf-8"))

            assert len(body.strip().splitlines()) <= 12, f"{skill_dir.name}: pointer too long"


def _find_source(root, name):
    for stack in ("common", "claude"):
        candidate = root / "features" / stack / "skills" / name / "SKILL.md"
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no catalog source for {name}")


class TestTheRendererIsTestableOnItsOwn:
    """The check below compares rendered output, so the renderer needs its own tests."""

    def test_a_pointer_keeps_the_frontmatter_verbatim(self, load_script):
        sync = _sync(load_script)
        source = "---\nname: probe\ndescription: does a thing\n---\n\n# Probe\n\nStep one.\n"

        rendered = sync.render_pointer("probe", source)

        assert _frontmatter(rendered) == _frontmatter(source)

    def test_a_pointer_names_the_scaffolded_path_and_the_full_file(self, load_script):
        sync = _sync(load_script)
        source = "---\nname: probe\n---\n\nbody\n"

        rendered = sync.render_pointer("probe", source)

        assert ".ai-badger/skills/probe/SKILL.md" in rendered
        assert "SKILL.full.md" in rendered

    def test_a_source_without_frontmatter_is_left_alone(self, load_script):
        """Refuse rather than emit a pointer with no name for the agent to match on."""
        sync = _sync(load_script)
        source = "# Probe\n\nNo frontmatter here.\n"

        assert sync.render_pointer("probe", source) == source


class TestCheckModeUnderstandsTheRendering:
    """--check compares the shipped copy against what the renderer would produce.

    Without this it would report every pointed skill as diverged forever, and the first person
    to see that would 'fix' it by reverting the rendering.
    """

    def test_the_real_repo_is_in_sync(self, load_script):
        assert _sync(load_script).main(["--check"]) == 0
