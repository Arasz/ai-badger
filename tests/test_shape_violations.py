"""The shipped plugin copy is checked against something other than the renderer (G5).

Two oracles, neither of which the renderer can move: `shape_violations` compares the
shipped tree's relative-path set at every depth against a fresh render, ignoring what
git ignores, and `extra_file_violations` reads `PLUGIN_EXTRA_FILES` directly. Content
equality stays `check_skill`'s job.
"""
from __future__ import annotations

import subprocess

import pytest
from conftest import _test_write

FRONTMATTER = """\
---
name: {name}
description: >-
  Use when testing shape.
---
"""


def _skill(src, name: str) -> None:
    _test_write(src / "SKILL.md", FRONTMATTER.format(name=name), encoding="utf-8")
    (src / "references").mkdir()
    _test_write(src / "references" / "details.md", "# details\n", encoding="utf-8")


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
        _test_write(dest / "stray.txt", "not shipped\n", encoding="utf-8")
        assert "unexpected stray.txt" in mod.shape_violations(src, dest, "shape-test")

    def test_bootstrap_shape_has_no_full_body(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _skill(src, "den-refresh")
        _render(mod, src, dest, "den-refresh")
        assert not (dest / "SKILL.full.md").exists()
        assert mod.shape_violations(src, dest, "den-refresh") == []
        _test_write(dest / "SKILL.full.md", "stale\n", encoding="utf-8")
        assert "unexpected SKILL.full.md" in mod.shape_violations(src, dest, "den-refresh")

    def test_a_source_without_frontmatter_is_not_a_shape_violation(
            self, tmp_path, load_script
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        _test_write(src / "SKILL.md", "no frontmatter here\n", encoding="utf-8")
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
        _test_write(dest / "scripts" / "tests" / "payload.py", "x = 1\n", encoding="utf-8")

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
        _test_write(extra, "# the declared source\n", encoding="utf-8")
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
        _test_write(extra, "# the declared source\n", encoding="utf-8")
        monkeypatch.setitem(mod.PLUGIN_EXTRA_FILES, "shape-test",
                            [(extra, "scripts/session_source.py")])
        _render(mod, src, dest, "shape-test")
        monkeypatch.setattr(mod, "_shipped_skills", lambda: [("shape-test", src, dest)])
        monkeypatch.setattr(mod, "TARGET", plugin)
        assert mod.main(["--check"]) == 0  # control: the declared file is shipped

        extra.rename(tmp_path / "renamed_source.py")

        assert mod.main(["--check"]) == 1
        assert "session_source.py" in capsys.readouterr().out


class TestGitIgnoredEntriesAreNotShippedContent:
    """A `tests/` directory committed into `skills/` shipped; a `__pycache__/` the test
    run left behind did not. `.gitignore` already draws that line."""

    @staticmethod
    def _tree(mod, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        _test_write(tmp_path / ".gitignore", "__pycache__/\n*.pyc\n", encoding="utf-8")
        src, _, dest = _plugin_tree(tmp_path, "shape-test")
        _render(mod, src, dest, "shape-test")
        (dest / "scripts" / "tests").mkdir(parents=True)
        _test_write(dest / "scripts" / "tests" / "payload.py", "x = 1\n", encoding="utf-8")
        cache = dest / "scripts" / "__pycache__"
        cache.mkdir()
        _test_write(cache / "helper.cpython-310.pyc", b"\x00")
        return src, dest

    def test_a_committed_tests_directory_is_still_reported(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = self._tree(mod, tmp_path)

        assert "unexpected scripts/tests/payload.py" in mod.shape_violations(
            src, dest, "shape-test")

    def test_a_git_ignored_pycache_is_not_reported(self, tmp_path, load_script):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = self._tree(mod, tmp_path)

        violations = mod.shape_violations(src, dest, "shape-test")

        assert violations == ["unexpected scripts", "unexpected scripts/tests",
                              "unexpected scripts/tests/payload.py"]

    def test_the_verdict_is_the_same_when_git_exports_a_repository_to_its_hooks(
            self, tmp_path, load_script, monkeypatch
    ):
        """`git commit` inside a worktree exports GIT_DIR to every hook it runs. An inherited
        GIT_DIR makes `git -C <subdir>` read <subdir> as the work-tree root, so no .gitignore
        above it is ever consulted and every ignored artefact reads as shipped content."""
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = self._tree(mod, tmp_path)
        monkeypatch.setenv("GIT_DIR", str(tmp_path / ".git"))
        monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / ".git" / "index"))

        violations = mod.shape_violations(src, dest, "shape-test")

        assert violations == ["unexpected scripts", "unexpected scripts/tests",
                              "unexpected scripts/tests/payload.py"]

    def test_git_failing_inside_a_work_tree_is_surfaced_not_read_as_not_ignored(
            self, tmp_path, load_script, monkeypatch
    ):
        mod = load_script("tooling/sync_plugin_skills.py")
        src, dest = self._tree(mod, tmp_path)
        real_run = mod.subprocess.run

        def fake_run(cmd, **kwargs):
            if "check-ignore" in cmd:
                return subprocess.CompletedProcess(cmd, 128, "", "fatal: broken index")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        with pytest.raises(RuntimeError, match="check-ignore"):
            mod.shape_violations(src, dest, "shape-test")


class TestCheckAllWiring:
    def test_check_all_flags_a_nested_entry_the_content_hash_cannot_see(
            self, tmp_path, load_script, monkeypatch
    ):
        """The fixture leaves `check_skill` green, so only the shape loop can fail it."""
        mod = load_script("tooling/sync_plugin_skills.py")
        src, plugin, dest = _plugin_tree(tmp_path, "shape-test")
        _render(mod, src, dest, "shape-test")
        monkeypatch.setattr(mod, "_shipped_skills", lambda: [("shape-test", src, dest)])
        monkeypatch.setattr(mod, "TARGET", plugin)
        assert mod.check_all() == 0  # control: a freshly rendered copy is in sync

        (dest / "references" / "tests").mkdir()
        _test_write(dest / "references" / "tests" / "helper.py", "x = 1\n", encoding="utf-8")

        assert mod.check_skill(src, dest, "shape-test") is None
        assert mod.check_all() == 1