"""Tests for features/hermes/adjustments/adjust_task.py: hermes session-source delivery.

The hermes task-tracking code (state.db parsing) is agent-specific, so it ships in
features/hermes/adjustments/hermes_session_source.py and the adjustment copies it into the
scaffolded task skill's scripts dir as session_sources.py — the generic contract name the
common tracker_lib.py imports. A claude-only scaffold must not receive the file.
"""
from __future__ import annotations

from pathlib import Path

ADJUSTER = "features/hermes/adjustments/adjust_task.py"
SOURCE_MODULE = "features/hermes/adjustments/session_sources.py"
DEST = ".ai-badger/skills/task/scripts/session_sources.py"


def _context(root: Path, target: Path, *, agents=("hermes",)) -> dict:
    return {
        "framework_root": root,
        "config": {"agents": list(agents), "stacks": ["python", "hermes"]},
        "feature_dir": root / "features" / "hermes" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["task"],
    }


def test_installs_hermes_session_source_into_scaffolded_task_scripts(tmp_path, root,
                                                                     load_script):
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"

    result = adjust_task.adjust(_context(root, target))

    assert result["applied"]
    installed = target / DEST
    assert installed.is_file()
    assert installed.read_text(encoding="utf-8") == \
        (root / SOURCE_MODULE).read_text(encoding="utf-8")
    assert DEST in result["files"]


def test_records_the_destination_in_files_for_the_manifest(tmp_path, root, load_script):
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"

    result = adjust_task.adjust(_context(root, target))

    assert result["files"] == [DEST]


def test_skips_installation_without_the_hermes_agent(tmp_path, root, load_script):
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"

    result = adjust_task.adjust(_context(root, target, agents=("claude",)))

    assert not result["applied"]
    assert not (target / DEST).exists()


def test_delivered_module_registers_a_hermes_source_into_tracker_lib(
        tmp_path, root, load_script, monkeypatch):
    """The delivered session_sources.py must expose register(tracker_lib) wiring the
    hermes source: env var, checkpoint maker, resume command, delegation lookup."""
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"
    adjust_task.adjust(_context(root, target))
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    delivered = load_script(str(target / DEST))
    delivered.register(tl)

    assert "hermes" in tl.SESSION_SOURCES
    source = tl.session_source("hermes")
    assert source["env_var"] == "HERMES_SESSION_ID"
    assert source["resume"]("sid-1") == "hermes --resume sid-1"
    assert callable(source["checkpoint"])
    assert callable(source["delegation_usage"])


def test_unregistered_lib_defaults_to_the_claude_source(root, load_script):
    """session_source() without any registration returns the built-in claude source."""
    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    source = tl.session_source("nope")

    assert source["env_var"] == tl.CLAUDE_SESSION_ENV
    assert source["resume"]("sid-1") == f"claude --resume sid-1"
