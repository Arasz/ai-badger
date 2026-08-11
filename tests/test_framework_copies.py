"""Competing framework trees: what is found, what is said about them, what may be deleted (#109).

The governing invariant is 0.19.0's: no command destroys state it did not create. `~/.ai-badger/
framework` is ours — `badger_lib._clone_pinned` writes it — so it is the only tree these tests
allow a deletion of, and only under an explicit opt-in.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import _test_write


def _make_root(path: Path, version: str = None) -> Path:
    """A directory satisfying the one framework-root predicate, optionally versioned."""
    (path / "schemas").mkdir(parents=True, exist_ok=True)
    (path / "features").mkdir(parents=True, exist_ok=True)
    (path / "engine").mkdir(parents=True, exist_ok=True)
    _test_write(path / "engine" / "badger_lib.py", "", encoding="utf-8")
    if version:
        _test_write(path / "VERSION", version + "\n", encoding="utf-8")
    return path


def _home_cache(home: Path, version: str = "0.13.0") -> Path:
    return _make_root(home / ".ai-badger" / "framework", version)


def _plugin_cache(home: Path, version: str) -> Path:
    return _make_root(
        home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger" / version, version)


@pytest.fixture
def fc(load_script):
    return load_script("engine/framework_copies.py")


class TestDiscovery:
    """Every tree on the machine that claims to be ai-badger, and who owns each."""

    def test_the_home_cache_is_ours(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home)

        copies = fc.discover(home=home)

        assert [c.path for c in copies] == [cache]
        assert copies[0].owner == fc.AI_BADGER
        assert copies[0].version == "0.13.0"
        assert copies[0].prunable

    def test_a_plugin_cache_version_belongs_to_claude_code_and_is_never_prunable(self, fc,
                                                                                 tmp_path):
        home = tmp_path / "home"
        cached = _plugin_cache(home, "0.36.2")

        copies = fc.discover(home=home)

        assert [c.path for c in copies] == [cached]
        assert copies[0].owner == fc.CLAUDE_CODE
        assert not copies[0].prunable

    def test_the_running_root_is_named_and_is_never_prunable(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home)
        running = _make_root(tmp_path / "checkout", "0.37.0")

        copies = fc.discover(running_root=running, home=home)

        by_path = {c.path: c for c in copies}
        assert by_path[running].running and not by_path[running].prunable
        assert by_path[cache].prunable

    def test_the_running_root_is_listed_once_even_when_it_is_the_cache(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home)

        copies = fc.discover(running_root=cache, home=home)

        assert [c.path for c in copies] == [cache]
        assert copies[0].running and not copies[0].prunable

    def test_a_directory_that_is_not_a_framework_root_is_not_a_copy(self, fc, tmp_path):
        home = tmp_path / "home"
        (home / ".ai-badger" / "framework").mkdir(parents=True)
        _test_write(home / ".ai-badger" / "framework" / "README.md", "hi", encoding="utf-8")

        assert fc.discover(home=home) == []

    def test_a_cache_without_a_version_file_still_reports_as_a_copy(self, fc, tmp_path):
        home = tmp_path / "home"
        _make_root(home / ".ai-badger" / "framework")

        copies = fc.discover(home=home)

        assert copies[0].version is None

    def test_discovery_survives_an_unreadable_plugin_cache(self, fc, tmp_path):
        home = tmp_path / "home"
        _home_cache(home)
        (home / ".claude" / "plugins" / "cache" / "ai-badger").mkdir(parents=True)
        _test_write(home / ".claude" / "plugins" / "cache" / "ai-badger" / "ai-badger", "not a directory", encoding="utf-8")

        assert len(fc.discover(home=home)) == 1

    def test_the_default_home_is_the_environment_home(self, fc):
        assert fc.home_cache() == Path.home() / ".ai-badger" / "framework"

    def test_the_copy_predicate_agrees_with_badger_lib(self, fc, load_script, tmp_path, root):
        """Restated, not imported (badger_lib needs jsonschema) — so pin the two together."""
        lib = load_script("engine/badger_lib.py")
        cases = [root, tmp_path, _make_root(tmp_path / "yes"), tmp_path / "absent"]

        assert ([fc.is_framework_root(p) for p in cases]
                == [lib.is_framework_root(p) for p in cases])


class TestTheNotice:
    """Two contradictory notices read as a framework bug; naming the trees is the fix (#109)."""

    def test_silent_when_only_one_tree_claims_to_be_ai_badger(self, fc, tmp_path):
        home = tmp_path / "home"
        _home_cache(home)

        assert fc.competing_copies_notice(fc.discover(home=home)) is None

    def test_every_competing_tree_is_named_with_its_path_and_version(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home, "0.13.0")
        plugin = _plugin_cache(home, "0.36.2")
        running = _make_root(tmp_path / "checkout", "0.37.0")

        notice = fc.competing_copies_notice(fc.discover(running_root=running, home=home))

        for path, version in ((cache, "0.13.0"), (plugin, "0.36.2"), (running, "0.37.0")):
            assert str(path) in notice, path
            assert version in notice, version

    def test_the_notice_says_the_copies_disagree_not_the_framework(self, fc, tmp_path):
        home = tmp_path / "home"
        _home_cache(home)
        _plugin_cache(home, "0.36.2")

        notice = fc.competing_copies_notice(fc.discover(home=home))

        assert "claim to be ai-badger" in notice

    def test_only_our_own_cache_carries_a_removal_command(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home)
        plugin = _plugin_cache(home, "0.36.2")

        notice = fc.competing_copies_notice(fc.discover(home=home))

        cache_line = next(l for l in notice.splitlines() if str(cache) in l)
        plugin_line = next(l for l in notice.splitlines() if str(plugin) in l)
        assert fc.PRUNE_COMMAND in cache_line
        assert fc.PRUNE_COMMAND not in plugin_line
        assert "Claude Code" in plugin_line

    def test_the_running_tree_is_never_offered_for_removal(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home)
        _plugin_cache(home, "0.36.2")

        notice = fc.competing_copies_notice(fc.discover(running_root=cache, home=home))

        cache_line = next(l for l in notice.splitlines() if str(cache) in l)
        assert fc.PRUNE_COMMAND not in cache_line

    def test_an_idle_cache_disagreeing_with_the_running_tree_is_reported_as_such(self, fc,
                                                                                tmp_path):
        home = tmp_path / "home"
        _home_cache(home, "0.13.0")
        running = _make_root(tmp_path / "checkout", "0.37.0")

        copies = fc.discover(running_root=running, home=home)

        assert fc.idle_home_cache(copies).version == "0.13.0"
        assert fc.idle_cache_disagrees(copies)

    def test_a_cache_agreeing_with_the_running_tree_is_not_a_disagreement(self, fc, tmp_path):
        home = tmp_path / "home"
        _home_cache(home, "0.37.0")
        running = _make_root(tmp_path / "checkout", "0.37.0")

        assert not fc.idle_cache_disagrees(fc.discover(running_root=running, home=home))

    def test_the_plugin_cache_alone_is_not_a_disagreement_worth_nagging_about(self, fc, tmp_path):
        """Claude Code keeps every version it installed; that is its business, not a defect."""
        home = tmp_path / "home"
        _plugin_cache(home, "0.36.0")
        _plugin_cache(home, "0.36.2")
        running = _make_root(tmp_path / "checkout", "0.37.0")

        assert not fc.idle_cache_disagrees(fc.discover(running_root=running, home=home))


class TestPruning:
    """A directory in a user's home is deleted on an explicit opt-in, or not at all."""

    def test_absent_when_there_is_no_cache(self, fc, tmp_path):
        home = tmp_path / "home"
        home.mkdir()

        assert fc.prune_home_cache(home=home, execute=True).status == fc.ABSENT

    def test_the_default_reports_the_path_the_version_and_the_command(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home, "0.13.0")

        result = fc.prune_home_cache(home=home)

        assert result.status == fc.REPORTED
        assert result.path == cache and result.version == "0.13.0"
        assert fc.PRUNE_COMMAND in result.detail
        assert cache.is_dir(), "the default must not delete anything"

    def test_the_opt_in_removes_the_cache(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home, "0.13.0")

        result = fc.prune_home_cache(home=home, execute=True)

        assert result.status == fc.REMOVED
        assert result.version == "0.13.0"
        assert not cache.exists()

    def test_it_refuses_a_directory_that_is_not_a_framework_root(self, fc, tmp_path):
        home = tmp_path / "home"
        stranger = home / ".ai-badger" / "framework"
        stranger.mkdir(parents=True)
        _test_write(stranger / "notes.txt", "someone else's", encoding="utf-8")

        result = fc.prune_home_cache(home=home, execute=True)

        assert result.status == fc.REFUSED
        assert "framework root" in result.detail
        assert (stranger / "notes.txt").is_file()

    def test_it_refuses_a_cache_that_is_a_symlink(self, fc, tmp_path):
        home = tmp_path / "home"
        elsewhere = _make_root(tmp_path / "elsewhere", "0.13.0")
        (home / ".ai-badger").mkdir(parents=True)
        os.symlink(elsewhere, home / ".ai-badger" / "framework")

        result = fc.prune_home_cache(home=home, execute=True)

        assert result.status == fc.REFUSED
        assert "symlink" in result.detail
        assert (elsewhere / "VERSION").is_file(), "never delete through a link"

    def test_it_refuses_a_cache_holding_a_symlink_that_leaves_it(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home, "0.13.0")
        outside = tmp_path / "outside"
        outside.mkdir()
        _test_write(outside / "keep.txt", "keep", encoding="utf-8")
        os.symlink(outside, cache / "features" / "linked")

        result = fc.prune_home_cache(home=home, execute=True)

        assert result.status == fc.REFUSED
        assert "symlink" in result.detail
        assert (outside / "keep.txt").is_file()
        assert cache.is_dir()

    def test_it_refuses_to_delete_the_root_it_is_running_from(self, fc, tmp_path):
        home = tmp_path / "home"
        cache = _home_cache(home, "0.13.0")

        result = fc.prune_home_cache(home=home, running_root=cache, execute=True)

        assert result.status == fc.REFUSED
        assert "running" in result.detail
        assert cache.is_dir()

    def test_it_never_touches_the_claude_code_plugin_cache(self, fc, tmp_path):
        """Claude Code populates that path; ai-badger only ever reads it (0.19.0)."""
        home = tmp_path / "home"
        _home_cache(home, "0.13.0")
        plugin = _plugin_cache(home, "0.36.2")

        fc.prune_home_cache(home=home, execute=True)

        assert (plugin / "VERSION").is_file()
        assert plugin.parent.is_dir()

    def test_a_failed_removal_is_reported_not_raised(self, fc, tmp_path, monkeypatch):
        home = tmp_path / "home"
        _home_cache(home, "0.13.0")

        def boom(*_args, **_kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(fc.shutil, "rmtree", boom)
        result = fc.prune_home_cache(home=home, execute=True)

        assert result.status == fc.FAILED
        assert "permission denied" in result.detail
