"""Tests for scripts/sync_plugin_skills.py — plugin skill directory sync (F-01)."""
from __future__ import annotations

from pathlib import Path

import pytest


def _write_tree(base: Path, files: dict) -> None:
    """Create base/relpath -> content for every entry in files."""
    for relpath, content in files.items():
        path = base / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def _snapshot(tree: Path) -> dict:
    """Map every file under tree to its relative path and exact bytes."""
    if not tree.exists():
        return None
    return {
        str(p.relative_to(tree)): p.read_bytes()
        for p in sorted(tree.rglob("*"))
        if p.is_file()
    }


class TestSyncSkillDryRun:
    """sync_skill(..., dry_run=True) must never mutate dest."""

    def test_dry_run_leaves_dest_byte_identical(self, tmp_path, load_script):
        sps = load_script("scripts/sync_plugin_skills.py")
        src = tmp_path / "src" / "some-skill"
        dest = tmp_path / "dest" / "some-skill"
        _write_tree(src, {"SKILL.md": "new content that must not land"})
        _write_tree(dest, {"SKILL.md": "original content", "notes.txt": "keep me"})

        before = _snapshot(dest)
        sps.sync_skill(src, dest, dry_run=True)
        after = _snapshot(dest)

        assert after == before

    def test_dry_run_reports_would_sync_without_deleting(self, tmp_path, load_script):
        sps = load_script("scripts/sync_plugin_skills.py")
        src = tmp_path / "src" / "some-skill"
        dest = tmp_path / "dest" / "some-skill"
        _write_tree(src, {"SKILL.md": "new content"})
        _write_tree(dest, {"SKILL.md": "original content"})

        result = sps.sync_skill(src, dest, dry_run=True)

        assert result == 1
        assert dest.exists()


class TestMainPrintReflectsResult:
    """The per-skill print must be keyed on sync_skill's return value, not the flag."""

    def _setup_framework(self, tmp_path):
        common_skills = tmp_path / "features" / "common" / "skills"
        claude_skills = tmp_path / "features" / "claude" / "skills"
        _write_tree(common_skills / "task", {"SKILL.md": "task skill"})
        _write_tree(claude_skills / "auto-wm", {"SKILL.md": "auto-wm skill"})
        return tmp_path

    def test_missing_source_dir_prints_no_success_line(self, tmp_path, load_script, monkeypatch, capsys):
        sps = load_script("scripts/sync_plugin_skills.py")
        fw = self._setup_framework(tmp_path)
        monkeypatch.setattr(sps, "ROOT", fw)
        monkeypatch.setattr(sps, "TARGET", fw / ".claude" / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["task", "missing-skill"])
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])

        sps.main(["--dry-run"])

        out = capsys.readouterr().out
        assert "missing-skill" not in out
        assert "would sync: task" in out

    def test_missing_source_dir_prints_no_success_line_non_dry_run(
        self, tmp_path, load_script, monkeypatch, capsys
    ):
        sps = load_script("scripts/sync_plugin_skills.py")
        fw = self._setup_framework(tmp_path)
        monkeypatch.setattr(sps, "ROOT", fw)
        monkeypatch.setattr(sps, "TARGET", fw / ".claude" / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["task", "missing-skill"])
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])

        sps.main([])

        out = capsys.readouterr().out
        assert "missing-skill" not in out
        assert "synced: task" in out


class TestManagedExternallyNeverTouched:
    """Names in MANAGED_EXTERNALLY must be skipped entirely, dest untouched."""

    def test_managed_externally_skill_is_left_alone(self, tmp_path, load_script, monkeypatch, capsys):
        sps = load_script("scripts/sync_plugin_skills.py")
        common_skills = tmp_path / "features" / "common" / "skills"
        _write_tree(common_skills / "debug-issue", {"SKILL.md": "framework version"})
        dest = tmp_path / ".claude" / "skills" / "debug-issue"
        _write_tree(dest, {"SKILL.md": "externally managed version"})

        monkeypatch.setattr(sps, "ROOT", tmp_path)
        monkeypatch.setattr(sps, "TARGET", tmp_path / ".claude" / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["debug-issue"])
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])
        assert "debug-issue" in sps.MANAGED_EXTERNALLY

        before = _snapshot(dest)
        sps.main([])
        after = _snapshot(dest)

        assert after == before
        out = capsys.readouterr().out
        assert "debug-issue" not in out


class TestSyncSkillRealCopy:
    """A real (non-dry) sync must copy content and honour SKIP_PATTERNS."""

    def test_real_sync_copies_and_skips_patterns(self, tmp_path, load_script):
        sps = load_script("scripts/sync_plugin_skills.py")
        src = tmp_path / "src" / "some-skill"
        dest = tmp_path / "dest" / "some-skill"
        _write_tree(src, {
            "SKILL.md": "the skill",
            "scripts/helper.py": "print('hi')",
            "tests/test_helper.py": "def test_x(): pass",
            "test_root_level.py": "def test_y(): pass",
            "evals/eval_one.md": "eval content",
            "__pycache__/helper.cpython-311.pyc": "junk",
        })

        result = sps.sync_skill(src, dest, dry_run=False)

        assert result == 1
        assert (dest / "SKILL.md").read_text() == "the skill"
        assert (dest / "scripts" / "helper.py").read_text() == "print('hi')"
        assert not (dest / "tests").exists()
        assert not (dest / "test_root_level.py").exists()
        assert not (dest / "evals").exists()
        assert not (dest / "__pycache__").exists()

    def test_missing_source_returns_zero_and_leaves_dest(self, tmp_path, load_script):
        sps = load_script("scripts/sync_plugin_skills.py")
        src = tmp_path / "src" / "does-not-exist"
        dest = tmp_path / "dest" / "some-skill"
        _write_tree(dest, {"SKILL.md": "unchanged"})

        before = _snapshot(dest)
        result = sps.sync_skill(src, dest, dry_run=False)
        after = _snapshot(dest)

        assert result == 0
        assert after == before
