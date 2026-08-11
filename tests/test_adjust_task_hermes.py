"""Tests for features/hermes/adjustments/adjust_task.py: hermes session-source delivery.

The hermes task-tracking code (state.db parsing) is agent-specific, so it ships in
features/hermes/adjustments/hermes_session_source.py and the adjustment copies it into the
scaffolded task skill's scripts dir as hermes_session_source.py — the `<agent>_session_source.py` contract name the
common tracker_lib.py imports. A claude-only scaffold must not receive the file.
"""
from __future__ import annotations

import sys
from pathlib import Path
from conftest import _test_write

ADJUSTER = "features/hermes/adjustments/adjust_task.py"
SOURCE_MODULE = "features/hermes/adjustments/hermes_session_source.py"
DEST = ".ai-badger/skills/task/scripts/hermes_session_source.py"


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


def test_skips_installation_when_the_task_skill_is_not_delivered(tmp_path, root, load_script):
    adjust_task = load_script(ADJUSTER)
    target = tmp_path / "proj"
    ctx = _context(root, target)
    ctx["skills"] = ["prompt-markers"]

    result = adjust_task.adjust(ctx)

    assert not result["applied"]
    assert not (target / DEST).exists()


def test_delivered_module_registers_a_hermes_source_into_tracker_lib(
        tmp_path, root, load_script, monkeypatch):
    """The delivered hermes_session_source.py must expose register(tracker_lib) wiring the
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


def test_guarded_import_registers_a_present_sibling_source(load_script, root, monkeypatch,
                                                           tmp_path):
    """tracker_lib's guarded import wires a sibling *_session_source.py when one is present.

    This is the scaffolded shape: agent adjustments copy their modules beside
    tracker_lib.py, and a fresh tracker_lib import must pick them up without any explicit
    register() call. The absent branch is what every other test sees (scripts dir has no
    session source modules); this pins the present branch by importing a copied tracker_lib
    whose SCRIPT_DIR really contains the sibling.
    """
    import importlib.util
    import shutil

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy2(root / "features/common/skills/task/scripts/tracker_lib.py",
                 scripts_dir / "tracker_lib.py")
    _test_write(scripts_dir / "probe_session_source.py", "def register(tracker_lib):\n"
        "    tracker_lib.register_session_source(\n"
        "        'probe', env_var='PROBE_SESSION_ID',\n"
        "        resolve=lambda: {'sessionId': 'p-1', 'transcriptPath': None}\n"
        "        if __import__('os').environ.get('PROBE_SESSION_ID') else {},\n"
        "        checkpoint=lambda session: {},\n"
        "        resume=lambda session_id: f'probe --resume {session_id}',\n"
        "        delegation_usage=None)\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(scripts_dir))
    monkeypatch.setenv("PROBE_SESSION_ID", "p-1")

    # Import the copy under a unique name so the discovery import (which scans the copy's
    # SCRIPT_DIR) actually runs and finds the sibling probe module.
    spec = importlib.util.spec_from_file_location("tracker_lib_probe_copy",
                                                  scripts_dir / "tracker_lib.py")
    assert spec is not None and spec.loader is not None
    tl = importlib.util.module_from_spec(spec)
    sys.modules["tracker_lib_probe_copy"] = tl
    spec.loader.exec_module(tl)

    assert "probe" in tl.SESSION_SOURCES
    assert tl.session_source("probe")["resume"]("s-1") == "probe --resume s-1"
    assert tl.resolve_own_session()["source"] == "probe"


def test_unregistered_lib_has_no_session_source(root, load_script):
    """session_source() without any registration returns None — no agent is special."""
    tl = load_script("features/common/skills/task/scripts/tracker_lib.py")

    assert tl.session_source("claude") is None
    assert tl.session_source("hermes") is None