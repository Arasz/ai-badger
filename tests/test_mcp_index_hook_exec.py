"""Guard tests: mcp_index_hook must never execute code found in a project tree.

The hook module is loaded at user scope, so any script it resolves from a cwd-derived
path is foreign content. See docs/reviews/2026-07-26-full-project-review.md F-03.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "features" / "common" / "hooks" / "mcp_index_hook.py"
)

# Both names are guarded on purpose: `mcp_index_build.py` is what the removed exec
# pointed at, `mcp_index.py` is the real script someone might "fix" the name to.
PLANTABLE_SCRIPT_NAMES = ("mcp_index_build.py", "mcp_index.py")


def _load_hook():
    """Import the hook module from features/ by path."""
    spec = importlib.util.spec_from_file_location("mcp_index_hook_under_test", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plant_project(tmp_path: Path, script_name: str) -> Path:
    """Build a project whose mcp-index script writes a sentinel when executed."""
    scripts_dir = tmp_path / ".ai-badger" / "skills" / "mcp-index" / "scripts"
    scripts_dir.mkdir(parents=True)
    sentinel = tmp_path / "sentinel.txt"
    (scripts_dir / script_name).write_text(
        f"from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    return sentinel


@pytest.mark.parametrize("script_name", PLANTABLE_SCRIPT_NAMES)
def test_session_start_never_executes_a_project_supplied_script(tmp_path, script_name):
    """on_session_start must not run anything found under the project's .ai-badger/."""
    sentinel = _plant_project(tmp_path, script_name)

    _load_hook().on_session_start(SimpleNamespace(cwd=str(tmp_path)))

    assert not sentinel.exists(), (
        f"on_session_start executed {script_name} from the project tree"
    )


@pytest.mark.parametrize("script_name", PLANTABLE_SCRIPT_NAMES)
def test_post_tool_call_never_executes_a_project_supplied_script(tmp_path, script_name):
    """post_tool_call must not run anything found under the project's .ai-badger/."""
    sentinel = _plant_project(tmp_path, script_name)

    _load_hook().post_tool_call(
        "mcp__some__tool", args={}, result=None, duration_ms=1,
        ctx=SimpleNamespace(cwd=str(tmp_path)),
    )

    assert not sentinel.exists(), (
        f"post_tool_call executed {script_name} from the project tree"
    )


def test_module_has_no_rebuild_entry_point():
    """The exec path is gone, not merely unreachable."""
    assert not hasattr(_load_hook(), "_rebuild_index")


def test_module_source_spawns_no_subprocess():
    """No subprocess machinery may be reintroduced into a user-scope hook."""
    source = HOOK_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "mcp_index_build" not in source
