"""Tests for tooling/sync_plugin_skills.py — plugin skill directory sync (F-01, F-17)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import _test_write


def _write_tree(base: Path, files: dict) -> None:
    """Create base/relpath -> content for every entry in files."""
    for relpath, content in files.items():
        path = base / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        _test_write(path, content)


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
        sps = load_script("tooling/sync_plugin_skills.py")
        src = tmp_path / "src" / "some-skill"
        dest = tmp_path / "dest" / "some-skill"
        _write_tree(src, {"SKILL.md": "new content that must not land"})
        _write_tree(dest, {"SKILL.md": "original content", "notes.txt": "keep me"})

        before = _snapshot(dest)
        sps.sync_skill(src, dest, dry_run=True)
        after = _snapshot(dest)

        assert after == before

    def test_dry_run_reports_would_sync_without_deleting(self, tmp_path, load_script):
        sps = load_script("tooling/sync_plugin_skills.py")
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
        sps = load_script("tooling/sync_plugin_skills.py")
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
        sps = load_script("tooling/sync_plugin_skills.py")
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
        """The exemplar is synthetic on purpose.

        This used to name whichever real skill happened to be externally managed, so the test
        broke each time one was rewritten into the catalog — twice now. What is under test is
        the mechanism, not the membership.
        """
        sps = load_script("tooling/sync_plugin_skills.py")
        common_skills = tmp_path / "features" / "common" / "skills"
        _write_tree(common_skills / "owned-elsewhere", {"SKILL.md": "framework version"})
        dest = tmp_path / "skills" / "owned-elsewhere"
        _write_tree(dest, {"SKILL.md": "externally managed version"})

        monkeypatch.setattr(sps, "ROOT", tmp_path)
        monkeypatch.setattr(sps, "TARGET", tmp_path / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["owned-elsewhere"])
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])
        monkeypatch.setattr(sps, "MANAGED_EXTERNALLY", {"owned-elsewhere"})

        before = _snapshot(dest)
        sps.main([])
        after = _snapshot(dest)

        assert after == before
        out = capsys.readouterr().out
        assert "owned-elsewhere" not in out


class TestSyncSkillRealCopy:
    """A real (non-dry) sync must copy content and honour SKIP_PATTERNS."""

    def test_real_sync_copies_and_skips_patterns(self, tmp_path, load_script):
        sps = load_script("tooling/sync_plugin_skills.py")
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
        sps = load_script("tooling/sync_plugin_skills.py")
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
    sps = load_script("tooling/sync_plugin_skills.py")
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
        _test_write(shipped, "task skill (hand-edited)")

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
        _test_write(tmp_path / "skills" / "task" / "scripts" / "helper.py", "drift")

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
        _test_write(target / "task" / "SKILL.md", "diverged")

        before = _snapshot(target)
        temp_framework.main(["--check"])
        after = _snapshot(target)

        assert after == before

    def test_check_mode_ignores_managed_externally(self, tmp_path, load_script, monkeypatch):
        sps = load_script("tooling/sync_plugin_skills.py")
        _write_tree(tmp_path / "features" / "common" / "skills" / "owned-elsewhere",
                    {"SKILL.md": "framework version"})
        _write_tree(tmp_path / "skills" / "owned-elsewhere",
                    {"SKILL.md": "externally managed version"})
        monkeypatch.setattr(sps, "ROOT", tmp_path)
        monkeypatch.setattr(sps, "TARGET", tmp_path / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["owned-elsewhere"])
        monkeypatch.setattr(sps, "MANAGED_EXTERNALLY", {"owned-elsewhere"})
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])

        assert sps.main(["--check"]) == 0

    def test_check_and_dry_run_are_mutually_exclusive(self, temp_framework):
        with pytest.raises(SystemExit):
            temp_framework.main(["--check", "--dry-run"])


class TestRealCatalogParity:
    """The shipped skills/ copy of this repo must match features/ at all times."""

    def test_repo_plugin_copy_is_in_sync(self, load_script):
        sps = load_script("tooling/sync_plugin_skills.py")

        assert sps.main(["--check"]) == 0, (
            "run `python3 tooling/sync_plugin_skills.py` to refresh skills/"
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
        """A common skill whose frontmatter declares no scope reaches nobody; skills_lint
        refuses it at authorship, and this pins the index the scaffolder actually reads."""
        bl = load_script("engine/badger_lib.py")

        index = json.loads((root / "index.json").read_text())
        common = index.get("stacks", {}).get("common", {}).get("skills", [])
        undeclared = sorted(e["name"] for e in common
                            if e.get("scope") not in bl.SKILL_SCOPE_VALUES)

        assert not undeclared, (
            f"common-stack skill(s) routed nowhere: {undeclared}. Add `scope: default` "
            "(ships everywhere) or `scope: optIn` to each SKILL.md's frontmatter, then "
            "rerun tooling/index_build.py."
        )

    def test_the_index_scope_matches_what_each_skill_declares(self, root, load_script):
        """index.json is a derived view; a stale row is what re-derivation exists to catch."""
        bl = load_script("engine/badger_lib.py")
        index = json.loads((root / "index.json").read_text())

        wrong = {e["name"]: e.get("scope")
                 for stack, data in index.get("stacks", {}).items()
                 for e in data.get("skills", [])
                 if not e.get("external")
                 and e.get("scope") != bl.skill_scope_in(root / e["path"])}

        assert not wrong, f"index.json disagrees with the catalog: {wrong}"

    def test_scope_declarations_name_only_real_skills(self, root, load_script):
        bl = load_script("engine/badger_lib.py")
        skills_dir = root / "features" / "common" / "skills"
        declared = set(bl.default_skills_in(skills_dir)) | set(bl.opt_in_skills_in(skills_dir))

        assert declared and not declared - _catalog_skill_names(root)

    def test_default_scope_skills_ship_in_the_plugin_copy(self, root, load_script):
        bl = load_script("engine/badger_lib.py")
        sps = load_script("tooling/sync_plugin_skills.py")
        shipped = set(sps.COMMON_SKILLS) | set(sps.CLAUDE_SKILLS)

        for name in bl.default_skills_in(root / "features" / "common" / "skills"):
            assert name in shipped, f"{name} is scope 'default' but the plugin ships no copy"

    def test_the_review_checklist_ships_with_every_project(self, root, load_script):
        bl = load_script("engine/badger_lib.py")
        sps = load_script("tooling/sync_plugin_skills.py")

        assert bl.skill_scope_in(
            root / "features/common/skills/code-review-checklist") == bl.SKILL_SCOPE_DEFAULT
        assert "code-review-checklist" in sps.COMMON_SKILLS

    def test_fed_back_workflow_skills_are_opt_in(self, root, load_script):
        """Learned-workflow skills contributed from a consumer project are optIn,
        not default — they must never silently ship to every scaffolded project."""
        bl = load_script("engine/badger_lib.py")

        for name in ("artifact-verification", "code-review-evidence", "design-gate-audit",
                     "documentation-drift-audit", "multi-lane-report-assembly",
                     "parallel-expert-review", "pre-push-gate-debugging",
                     "research-record-audit", "review-gate-diff-verification",
                     "scripts-tooling-refactor", "spec-driven-refactoring",
                     "sqlite-bank-space-diagnosis", "sqlite-schema-review",
                     "worktree-agent-isolation"):
            assert bl.skill_scope_in(
                root / "features" / "common" / "skills" / name) == bl.SKILL_SCOPE_OPT_IN, name

    def test_decision_collection_skills_ship_with_every_project(self, root, load_script):
        """The two common skills are universal and have shipped plugin copies."""
        bl = load_script("engine/badger_lib.py")
        sps = load_script("tooling/sync_plugin_skills.py")

        for name in ("owner-gate-review", "differential-feature-refactor"):
            assert bl.skill_scope_in(
                root / "features" / "common" / "skills" / name) == bl.SKILL_SCOPE_DEFAULT
            assert name in sps.COMMON_SKILLS


class TestOrphanedPluginCopies:
    """A skill removed from the shipped list must not linger in the plugin dir (F-17)."""

    def test_a_skill_no_longer_shipped_is_removed_from_the_plugin_dir(
        self, tmp_path, temp_framework
    ):
        temp_framework.main([])
        orphan = tmp_path / "skills" / "retired-skill"
        _write_tree(orphan, {"SKILL.md": "shipped by a previous version"})

        temp_framework.main([])

        assert not orphan.exists()

    def test_check_mode_fails_on_an_orphaned_plugin_copy(self, tmp_path, temp_framework):
        temp_framework.main([])
        _write_tree(tmp_path / "skills" / "retired-skill", {"SKILL.md": "stale"})

        assert temp_framework.main(["--check"]) == 1

    def test_check_mode_names_the_orphaned_skill(self, tmp_path, temp_framework, capsys):
        temp_framework.main([])
        _write_tree(tmp_path / "skills" / "retired-skill", {"SKILL.md": "stale"})
        capsys.readouterr()

        temp_framework.main(["--check"])

        assert "retired-skill" in capsys.readouterr().out

    def test_prune_never_touches_a_managed_externally_directory(
        self, tmp_path, load_script, monkeypatch
    ):
        """MANAGED_EXTERNALLY has to gate deletion, not only writing.

        Such a directory is never in the shipped list, so a prune that only subtracts that list
        would delete it on the next sync. The set is empty today — every skill it once held has
        been rewritten into the catalog — which is exactly why this test supplies its own
        member rather than borrowing a real name: an empty set must not silently retire the
        guard along with its last entry.
        """
        sps = load_script("tooling/sync_plugin_skills.py")
        _write_tree(tmp_path / "features" / "common" / "skills" / "task", {"SKILL.md": "task"})
        external = tmp_path / "skills" / "owned-elsewhere"
        _write_tree(external, {"SKILL.md": "owned by another tool"})
        monkeypatch.setattr(sps, "ROOT", tmp_path)
        monkeypatch.setattr(sps, "TARGET", tmp_path / "skills")
        monkeypatch.setattr(sps, "COMMON_SKILLS", ["task"])
        monkeypatch.setattr(sps, "CLAUDE_SKILLS", [])
        monkeypatch.setattr(sps, "MANAGED_EXTERNALLY", {"owned-elsewhere"})

        sps.main([])

        assert (external / "SKILL.md").read_text() == "owned by another tool"

    def test_dry_run_reports_an_orphan_without_deleting_it(self, tmp_path, temp_framework):
        temp_framework.main([])
        orphan = tmp_path / "skills" / "retired-skill"
        _write_tree(orphan, {"SKILL.md": "stale"})

        temp_framework.main(["--dry-run"])

        assert orphan.exists()
