"""Tests for scripts/sync_plugin_skills.py — plugin skill directory sync (F-01, F-17)."""
from __future__ import annotations

import json
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
        monkeypatch.setattr(sps, "TARGET", fw / "skills")
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
        monkeypatch.setattr(sps, "TARGET", fw / "skills")
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
        dest = tmp_path / "skills" / "debug-issue"
        _write_tree(dest, {"SKILL.md": "externally managed version"})

        monkeypatch.setattr(sps, "ROOT", tmp_path)
        monkeypatch.setattr(sps, "TARGET", tmp_path / "skills")
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


@pytest.fixture
def temp_framework(tmp_path, load_script, monkeypatch):
    """A sync script bound to a throwaway framework tree with one common + one claude skill."""
    sps = load_script("scripts/sync_plugin_skills.py")
    _write_tree(tmp_path / "features" / "common" / "skills" / "task", {
        "SKILL.md": "task skill",
        "scripts/helper.py": "print('hi')",
    })
    _write_tree(tmp_path / "features" / "claude" / "skills" / "auto-wm", {
        "SKILL.md": "auto-wm skill",
    })
    monkeypatch.setattr(sps, "ROOT", tmp_path)
    monkeypatch.setattr(sps, "TARGET", tmp_path / "skills")
    monkeypatch.setattr(sps, "COMMON_SKILLS", ["task"])
    monkeypatch.setattr(sps, "CLAUDE_SKILLS", ["auto-wm"])
    return sps


class TestCheckMode:
    """--check must fail the build whenever the shipped copy diverges (F-17)."""

    def test_check_mode_fails_when_shipped_copy_diverges(self, tmp_path, temp_framework):
        temp_framework.main([])

        shipped = tmp_path / "skills" / "task" / "SKILL.md"
        shipped.write_text("task skill (hand-edited)")

        assert temp_framework.main(["--check"]) == 1

    def test_check_mode_passes_when_copies_are_in_sync(self, temp_framework):
        temp_framework.main([])

        assert temp_framework.main(["--check"]) == 0

    def test_check_mode_fails_when_a_skill_was_never_synced(self, tmp_path, temp_framework):
        temp_framework.main([])
        import shutil
        shutil.rmtree(tmp_path / "skills" / "auto-wm")

        assert temp_framework.main(["--check"]) == 1

    def test_check_mode_names_the_diverged_skill(self, tmp_path, temp_framework, capsys):
        temp_framework.main([])
        capsys.readouterr()
        (tmp_path / "skills" / "task" / "scripts" / "helper.py").write_text("drift")

        temp_framework.main(["--check"])

        out = capsys.readouterr().out
        assert "task" in out
        assert "auto-wm" not in out

    def test_check_mode_ignores_excluded_files(self, tmp_path, temp_framework):
        temp_framework.main([])
        _write_tree(tmp_path / "features" / "common" / "skills" / "task", {
            "tests/test_helper.py": "def test_x(): pass",
            "evals/one.md": "eval",
        })

        assert temp_framework.main(["--check"]) == 0

    def test_check_mode_never_writes(self, tmp_path, temp_framework):
        temp_framework.main([])
        target = tmp_path / "skills"
        (target / "task" / "SKILL.md").write_text("diverged")

        before = _snapshot(target)
        temp_framework.main(["--check"])
        after = _snapshot(target)

        assert after == before

    def test_check_mode_ignores_managed_externally(self, tmp_path, load_script, monkeypatch):
        sps = load_script("scripts/sync_plugin_skills.py")
        _write_tree(tmp_path / "features" / "common" / "skills" / "debug-issue",
                    {"SKILL.md": "framework version"})
        _write_tree(tmp_path / "skills" / "debug-issue",
                    {"SKILL.md": "externally managed version"})
        monkeypatch.setattr(sps, "ROOT", tmp_path)
        monkeypatch.setattr(sps, "TARGET", tmp_path / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["debug-issue"])
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])

        assert sps.main(["--check"]) == 0

    def test_check_and_dry_run_are_mutually_exclusive(self, temp_framework):
        with pytest.raises(SystemExit):
            temp_framework.main(["--check", "--dry-run"])


class TestRealCatalogParity:
    """The shipped skills/ copy of this repo must match features/ at all times."""

    def test_repo_plugin_copy_is_in_sync(self, load_script):
        sps = load_script("scripts/sync_plugin_skills.py")

        assert sps.main(["--check"]) == 0, (
            "run `python3 scripts/sync_plugin_skills.py` to refresh skills/"
        )


def _catalog_skill_names(root) -> set:
    """Every in-repo skill the built index advertises, across all stacks."""
    index = json.loads((root / "index.json").read_text())
    return {
        entry["name"]
        for stack in index["stacks"].values()
        for entry in stack.get("skills", [])
        if not entry.get("external")
    }


class TestCatalogRouting:
    """Every catalogued skill must reach users by a route somebody chose on purpose."""

    def test_every_catalog_skill_is_reachable_by_a_declared_route(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")

        undeclared = sorted(_catalog_skill_names(root) - set(bl.SKILL_SCOPES))

        assert not undeclared, (
            f"catalogued but routed nowhere: {undeclared}. Add each to "
            "badger_lib.SKILL_SCOPES as 'default' (ships everywhere) or 'optIn'."
        )

    def test_scope_declarations_name_only_real_skills(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")

        assert not sorted(set(bl.SKILL_SCOPES) - _catalog_skill_names(root))

    def test_default_scope_skills_ship_in_the_plugin_copy(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        sps = load_script("scripts/sync_plugin_skills.py")
        shipped = set(sps.COMMON_SKILLS) | set(sps.CLAUDE_SKILLS)

        for name in bl.default_skill_names():
            assert name in shipped, f"{name} is scope 'default' but the plugin ships no copy"

    def test_the_review_checklist_ships_with_every_project(self, load_script):
        bl = load_script("scripts/badger_lib.py")
        sps = load_script("scripts/sync_plugin_skills.py")

        assert bl.skill_scope("code-review-checklist") == bl.SKILL_SCOPE_DEFAULT
        assert "code-review-checklist" in sps.COMMON_SKILLS

    def test_an_undeclared_skill_is_refused_rather_than_guessed(self, load_script):
        bl = load_script("scripts/badger_lib.py")

        with pytest.raises(bl.UnknownSkillScope):
            bl.skill_scope("no-such-skill")
