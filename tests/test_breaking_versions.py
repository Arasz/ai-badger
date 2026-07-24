"""Tests for breaking version detection and den-refresh breaking change behavior."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# --- badger_lib breaking version helpers ---

class TestBreakingVersions:
    def test_is_breaking_transition_same_version(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        assert bl.is_breaking_transition("0.7.0", "0.7.0", root) is False

    def test_is_breaking_transition_crosses_breaking(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        # 0.6.0 -> 0.7.0 crosses the 0.7.0 breaking boundary
        assert bl.is_breaking_transition("0.6.0", "0.7.0", root) is True

    def test_is_breaking_transition_within_breaking(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        # 0.7.0 -> 0.7.1 doesn't cross a breaking boundary
        assert bl.is_breaking_transition("0.7.0", "0.7.1", root) is False

    def test_is_breaking_transition_before_breaking(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        # 0.5.0 -> 0.6.0 doesn't cross a breaking boundary
        assert bl.is_breaking_transition("0.5.0", "0.6.0", root) is False

    def test_is_breaking_transition_future_breaking(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        # 0.6.0 -> 0.8.0 crosses 0.7.0
        assert bl.is_breaking_transition("0.6.0", "0.8.0", root) is True

    def test_read_breaking_versions(self, root, load_script):
        bl = load_script("scripts/badger_lib.py")
        versions = bl.read_breaking_versions(root)
        assert isinstance(versions, list)
        assert "0.7.0" in versions

    def test_read_breaking_versions_missing_file(self, tmp_path, load_script):
        bl = load_script("scripts/badger_lib.py")
        versions = bl.read_breaking_versions(tmp_path)
        assert versions == []


# --- refresh.py breaking change behavior ---

class TestRefreshBreakingChange:
    def test_breaking_change_creates_backup(self, tmp_path, root, load_script):
        """When crossing a breaking version, backup .ai-badger/ to .ai-badger.bckp/."""
        refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

        (tmp_path / "VERSION").write_text("0.7.0\n")
        (tmp_path / "BREAKING_VERSIONS").write_text("0.7.0\n")

        # Set up a target with old version
        target = tmp_path / "target"
        aib = target / ".ai-badger"
        aib.mkdir(parents=True)
        (aib / "config.json").write_text(json.dumps({
            "frameworkVersion": "0.6.0",
            "project": {"name": "test"},
            "stacks": [],
            "agents": ["claude"],
        }))
        # Write a file that should be backed up
        (aib / "state.json").write_text("{}")

        result = refresh.check_breaking_and_backup(tmp_path, target)

        assert result["isBreaking"] is True
        assert result["backupPath"] is not None
        assert (target / ".ai-badger.bckp").is_dir()
        assert (target / ".ai-badger.bckp" / "config.json").exists()
        assert (target / ".ai-badger.bckp" / "state.json").exists()

    def test_non_breaking_change_no_backup(self, tmp_path, root, load_script):
        """Non-breaking transitions should not create backup."""
        refresh = load_script("features/common/skills/den-refresh/scripts/refresh.py")

        (tmp_path / "VERSION").write_text("0.7.1\n")
        (tmp_path / "BREAKING_VERSIONS").write_text("0.7.0\n")

        target = tmp_path / "target"
        aib = target / ".ai-badger"
        aib.mkdir(parents=True)
        (aib / "config.json").write_text(json.dumps({"frameworkVersion": "0.7.0"}))

        result = refresh.check_breaking_and_backup(tmp_path, target)

        assert result["isBreaking"] is False
        assert not (target / ".ai-badger.bckp").exists()
