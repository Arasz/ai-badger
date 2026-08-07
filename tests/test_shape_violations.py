"""The shipped plugin copy's top-level shape is the rendered shape (G5).

The render produced by `render_into` is the contract: a shape the renderer itself
would create (e.g. no `SKILL.full.md` for a source without frontmatter, or the
inline body of a bootstrap skill) is not a violation. The check compares entry
names only — content equality is `check_skill`'s job.
"""
from __future__ import annotations

import textwrap

FRONTMATTER = """\
---
name: {name}
description: >-
  Use when testing shape.
---
"""


def _skill(src, name: str) -> None:
    (src / "SKILL.md").write_text(FRONTMATTER.format(name=name), encoding="utf-8")
    (src / "references").mkdir()
    (src / "references" / "details.md").write_text("# details\n", encoding="utf-8")


def _render(module, src, dest, name: str) -> None:
    module.render_into(name, src, dest)


class TestShapeViolations:
    def test_a_rendered_copy_has_no_violations(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src = tmp_path / "src"
        dest = tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        assert mod.shape_violations(src, dest, "shape-test") == []

    def test_missing_full_body_is_reported(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "SKILL.full.md").unlink()
        assert "missing SKILL.full.md" in mod.shape_violations(src, dest, "shape-test")

    def test_missing_skillmd_is_reported(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "SKILL.md").unlink()
        assert "missing SKILL.md" in mod.shape_violations(src, dest, "shape-test")

    def test_an_extra_top_level_entry_is_reported(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "stray.txt").write_text("not shipped\n", encoding="utf-8")
        assert "unexpected stray.txt" in mod.shape_violations(src, dest, "shape-test")

    def test_bootstrap_shape_has_no_full_body(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "den-refresh")
        _render(mod, src, dest, "den-refresh")
        assert not (dest / "SKILL.full.md").exists()
        assert mod.shape_violations(src, dest, "den-refresh") == []
        (dest / "SKILL.full.md").write_text("stale\n", encoding="utf-8")
        assert "unexpected SKILL.full.md" in mod.shape_violations(src, dest, "den-refresh")

    def test_a_source_without_frontmatter_is_not_a_shape_violation(
        self, tmp_path, load_script
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        (src / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")
        _render(mod, src, dest, "shape-test")
        assert not (dest / "SKILL.full.md").exists()  # renderer left it alone
        assert mod.shape_violations(src, dest, "shape-test") == []

    def test_check_all_flags_a_shape_violation(self, tmp_path, load_script, monkeypatch):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "SKILL.full.md").unlink()
        monkeypatch.setattr(mod, "_shipped_skills", lambda: [("shape-test", src, dest)])
        monkeypatch.setattr(mod, "TARGET", tmp_path)
        assert mod.check_all() == 1
