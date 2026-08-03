"""Tests for features/claude/adjustments/adjust_task.py: claude session-source delivery.

The claude task-tracking source (transcript reading) is agent-specific, so it ships in
features/claude/adjustments/claude_session_source.py and the adjustment copies it into the
scaffolded task skill's scripts dir as claude_session_source.py — one of the
*_session_source.py siblings the common tracker_lib.py discovers. A project without the
claude agent must not receive the file.
"""
from __future__ import annotations

from pathlib import Path

ADJUSTER = "features/claude/adjustments/adjust_task.py"
SOURCE_MODULE = "features/claude/adjustments/claude_session_source.py"
DEST = ".ai-badger/skills/task/scripts/claude_session_source.py"


def _context(root: Path, target: Path, *, agents=("claude",)) -> dict:
    return {
        "framework_root": root,
        "config": {"agents": list(agents), "stacks": ["python", "claude"]},
        "feature_dir": root / "features" / "claude" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "skills": ["task"],
    }


def test_installs_claude_session_source_into_scaffolded_task_scripts(tmp_path, root,
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


def test_skips_installation_without_the_claude_agent(tmp_path, root, load_script):
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"

    result = adjust_task.adjust(_context(root, target, agents=("hermes",)))

    assert not result["applied"]
    assert not (target / DEST).exists()


def test_skips_installation_when_the_task_skill_is_not_delivered(tmp_path, root, load_script):
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"
    ctx = _context(root, target)
    ctx["skills"] = ["prompt-markers"]

    result = adjust_task.adjust(ctx)

    assert not result["applied"]
    assert not (target / DEST).exists()


def test_delivered_module_registers_a_claude_source_into_tracker_lib(
        tmp_path, root, load_script, monkeypatch):
    """The delivered claude_session_source.py registers the claude source: env var,
    transcript-capable checkpoint, claude resume."""
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"
    adjust_task.adjust(_context(root, target))
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    delivered = load_script(str(target / DEST))
    delivered.register(tl)

    assert "claude" in tl.SESSION_SOURCES
    source = tl.session_source("claude")
    assert source["env_var"] == "CLAUDE_CODE_SESSION_ID"
    assert source["resume"]("sid-1") == "claude --resume sid-1"
    assert callable(source["checkpoint"])
    assert source["transcript"] is True


def test_transcript_source_returns_the_claude_source_when_registered(
        tmp_path, root, load_script, monkeypatch):
    """transcript_source() resolves the source that reads transcripts — the one an explicit
    --session-id is attributed to. None when nothing transcript-capable is registered."""
    scripts_dir = str(root / "features" / "common" / "skills" / "task" / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    assert tl.transcript_source() is None

    claude = load_script("features/claude/adjustments/claude_session_source.py")
    claude.register(tl)

    assert tl.transcript_source() == "claude"
