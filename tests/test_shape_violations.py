"""The shipped plugin copy is checked against something other than the renderer (G5).

Two oracles, neither of which the renderer can move: `shape_violations` compares the
shipped tree's relative-path set at every depth against a fresh render, and
`extra_file_violations` reads `PLUGIN_EXTRA_FILES` directly. Content equality stays
`check_skill`'s job.
"""
from __future__ import annotations

import pytest

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


def _plugin_tree(tmp_path, name: str):
    """A source skill and the plugin directory its shipped copy lives in."""
    src = tmp_path / "src"
    plugin = tmp_path / "plugin"
    src.mkdir()
    plugin.mkdir()
    _skill(src, name)
    return src, plugin, plugin / name


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


class TestShapeReachesEveryDepth:
    """`iterdir` stopped at the top level, which is where the content hash is blind."""

    def test_a_nested_entry_the_content_hash_ignores_is_reported(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "scripts" / "tests").mkdir(parents=True)
        (dest / "scripts" / "tests" / "payload.py").write_text("x = 1\n", encoding="utf-8")

        assert mod.check_skill(src, dest, "shape-test") is None  # excluded from the hash
        assert "unexpected scripts/tests/payload.py" in mod.shape_violations(
            src, dest, "shape-test")

    def test_a_nested_file_missing_from_the_shipped_copy_is_reported(
            self, tmp_path, load_script
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "references" / "details.md").unlink()

        assert "missing references/details.md" in mod.shape_violations(
            src, dest, "shape-test")

    def test_a_destination_that_was_never_synced_is_check_skills_report_not_ours(
            self, tmp_path, load_script
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "never-synced"
        src.mkdir()
        _skill(src, "shape-test")

        assert not dest.exists()
        assert mod.shape_violations(src, dest, "shape-test") == []
        assert mod.check_skill(src, dest, "shape-test") == "missing"


class TestDeclaredExtraFiles:
    """`PLUGIN_EXTRA_FILES` is the oracle for the files shipped from outside the skill dir."""

    def test_render_into_refuses_a_declared_source_that_is_absent(
            self, tmp_path, load_script, monkeypatch
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "shape-test")
        monkeypatch.setitem(mod.PLUGIN_EXTRA_FILES, "shape-test",
                            [(tmp_path / "never_written.py", "scripts/never_written.py")])

        with pytest.raises(FileNotFoundError) as excinfo:
            mod.render_into("shape-test", src, dest)

        assert "never_written.py" in str(excinfo.value)

    def test_check_all_catches_a_renderer_that_stops_shipping_a_declared_file(
            self, tmp_path, load_script, monkeypatch
    ):
        """With the shipper neutered the render equals the shipped copy, so only the
        declaration can tell the file is gone."""
        mod = load_script("tooling/sync_plugin_skills.py")
        src, plugin, dest = _plugin_tree(tmp_path, "shape-test")
        extra = tmp_path / "session_source.py"
        extra.write_text("# the declared source\n", encoding="utf-8")
        monkeypatch.setitem(mod.PLUGIN_EXTRA_FILES, "shape-test",
                            [(extra, "scripts/session_source.py")])
        monkeypatch.setattr(mod, "_ship_extra_files", lambda *_: None)
        _render(mod, src, dest, "shape-test")
        monkeypatch.setattr(mod, "_shipped_skills", lambda: [("shape-test", src, dest)])
        monkeypatch.setattr(mod, "TARGET", plugin)

        assert not (dest / "scripts" / "session_source.py").exists()
        assert mod.check_skill(src, dest, "shape-test") is None
        assert mod.shape_violations(src, dest, "shape-test") == []
        assert mod.check_all() == 1

    def test_check_mode_fails_when_a_declared_source_is_renamed_away(
            self, tmp_path, load_script, monkeypatch, capsys
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, plugin, dest = _plugin_tree(tmp_path, "shape-test")
        extra = tmp_path / "session_source.py"
        extra.write_text("# the declared source\n", encoding="utf-8")
        monkeypatch.setitem(mod.PLUGIN_EXTRA_FILES, "shape-test",
                            [(extra, "scripts/session_source.py")])
        _render(mod, src, dest, "shape-test")
        monkeypatch.setattr(mod, "_shipped_skills", lambda: [("shape-test", src, dest)])
        monkeypatch.setattr(mod, "TARGET", plugin)
        assert mod.main(["--check"]) == 0  # control: the declared file is shipped

        extra.rename(tmp_path / "renamed_source.py")

        assert mod.main(["--check"]) == 1
        assert "session_source.py" in capsys.readouterr().out


class TestCheckAllWiring:
    def test_check_all_flags_junk_the_content_hash_cannot_see(
            self, tmp_path, load_script, monkeypatch
    ):
        """The fixture leaves `check_skill` green, so only the shape loop can fail it."""
        mod = load_script("tooling/sync_plugin_skills.py")
        src, plugin, dest = _plugin_tree(tmp_path, "shape-test")
        _render(mod, src, dest, "shape-test")
        monkeypatch.setattr(mod, "_shipped_skills", lambda: [("shape-test", src, dest)])
        monkeypatch.setattr(mod, "TARGET", plugin)
        assert mod.check_all() == 0  # control: a freshly rendered copy is in sync

        cache = dest / "references" / "__pycache__"
        cache.mkdir()
        (cache / "details.cpython-311.pyc").write_bytes(b"\x00")

        assert mod.check_skill(src, dest, "shape-test") is None
        assert mod.check_all() == 1