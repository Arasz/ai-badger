"""The task-graph launch every generated MCP file carries, run for real.

The launch walks up from the session's cwd to the project script and runs it through `uv`,
so it works from any subdirectory, on any OS, without `sh` or `git`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = "task-graph"
SCRIPT_REL = ".ai-badger/skills/task-decomposition/scripts/task_graph_server.py"

STUB = '''# /// script
# dependencies = []
# ///
import json
import os
import sys

for line in sys.stdin:
    print(json.dumps({"cwd": os.getcwd(), "file": __file__, "echo": line.strip()}), flush=True)
'''


def _launch(path: Path) -> tuple[str, list[str]]:
    """The task-graph command and args as declared in the JSON file at `path`."""
    entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"][SERVER]
    return entry["command"], list(entry.get("args", []))


def _declared_launch() -> tuple[str, list[str]]:
    """The task-graph command and args as declared in the catalog source."""
    servers = json.loads((ROOT / "features/common/stack-mcp.json").read_text(encoding="utf-8"))["servers"]
    item = next(s for s in servers if s["name"] == SERVER)
    return item["command"], list(item.get("args", []))


def test_the_launch_reaches_the_project_script_from_a_nested_subdirectory(tmp_path, monkeypatch):
    """Started deep inside a project, the declared launch runs the project's script in that cwd."""
    if shutil.which("uv") is None:
        message = "uv is not on PATH; the task-graph launch cannot be exercised"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    proj = tmp_path / "proj"
    script = proj / SCRIPT_REL
    script.parent.mkdir(parents=True)
    script.write_text(STUB, encoding="utf-8")
    (proj / "pyproject.toml").write_text(
        "[project]\nname = 'consumer'\nversion = '0'\nrequires-python = '>=3.10'\n", encoding="utf-8")
    start = proj / "a" / "b c"
    start.mkdir(parents=True)
    command, args = _launch(ROOT / ".github/mcp.json")

    done = subprocess.run([command, *args], cwd=start, input="ping\n", capture_output=True,
                          text=True, timeout=180, check=False)

    assert done.returncode == 0, f"rc={done.returncode}\nstderr:\n{done.stderr}"
    reply = json.loads(done.stdout.strip().splitlines()[0])
    assert os.path.samefile(reply["file"], script), f"ran {reply['file']}\nstderr:\n{done.stderr}"
    assert os.path.samefile(reply["cwd"], start), f"cwd {reply['cwd']}\nstderr:\n{done.stderr}"
    assert reply["echo"] == "ping"
    assert not (proj / ".venv").exists(), "the launch created a project venv"
    assert not (proj / "uv.lock").exists(), "the launch wrote a uv.lock"


def test_the_launch_names_the_missing_script_and_exits_1_outside_a_project(tmp_path):
    """With no project script at or above the cwd, the launch says which file and exits 1."""
    _, args = _launch(ROOT / ".github/mcp.json")
    assert args[:-1] == ["run", "--no-project", "python", "-c"], args
    empty = tmp_path / "empty"
    empty.mkdir()

    done = subprocess.run([sys.executable, "-c", args[-1]], cwd=empty, capture_output=True,
                          text=True, timeout=60, check=False)

    assert done.returncode == 1, f"rc={done.returncode}\nstderr:\n{done.stderr}"
    assert done.stderr.startswith(f"task-graph: {SCRIPT_REL} not found at or above"), done.stderr


def test_every_generated_file_carries_the_declared_launch():
    """The Claude/Copilot and pi files launch task-graph exactly as the catalog declares it."""
    declared = _declared_launch()
    assert _launch(ROOT / ".github/mcp.json") == declared
    assert _launch(ROOT / ".pi/mcp.json") == declared
