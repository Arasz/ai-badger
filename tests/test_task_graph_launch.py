"""The task-graph launch every generated MCP file carries, run for real.

The launch walks up from the session's cwd to the project script and runs it through `uv`,
so it works from any subdirectory, on any OS, without `sh` or `git`.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = "task-graph"
SCRIPT_REL = ".ai-badger/skills/task-decomposition/scripts/task_graph_server.py"

def _stub(body: str) -> str:
    """A PEP 723 stub server script whose behaviour is `body`."""
    header = ("# /// script\n# requires-python = \">=3.10\"\n# dependencies = []\n# ///\n"
              "import json\nimport os\nimport sys\n\n")
    return header + body


ECHO_BODY = '''for line in sys.stdin:
    print(json.dumps({"cwd": os.getcwd(), "file": __file__, "echo": line.strip(),
                      "venv": sys.prefix != sys.base_prefix}), flush=True)
sys.exit(3)
'''
STUB = _stub(ECHO_BODY)
PID_STUB = _stub('print(os.getpid(), flush=True)\nsys.stdin.read()\n')
PYPROJECT = "[project]\nname = 'consumer'\nversion = '0'\nrequires-python = '>=3.10'\n"


def _require_uv() -> str:
    """The uv path; fails on CI and skips locally when uv is absent."""
    uv = shutil.which("uv")
    if uv is None:
        message = "uv is not on PATH; the task-graph launch cannot be exercised"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    return uv


def _project(root: Path, stub: str = STUB) -> Path:
    """A consumer project at `root` holding `stub` as the task-graph script."""
    script = root / SCRIPT_REL
    script.parent.mkdir(parents=True)
    script.write_text(stub, encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return script


def _assert_ran_stub(done, script: Path, start: Path) -> None:
    """The launch ran `script` in `start` through uv's script runner, echoing and exiting 3."""
    assert done.returncode == 3, f"rc={done.returncode}\nstderr:\n{done.stderr}"
    reply = json.loads(done.stdout.strip().splitlines()[0])
    assert os.path.samefile(reply["file"], script), f"ran {reply['file']}\nstderr:\n{done.stderr}"
    assert os.path.samefile(reply["cwd"], start), f"cwd {reply['cwd']}\nstderr:\n{done.stderr}"
    assert reply["echo"] == "ping"
    assert reply["venv"] is True, "the script did not run in a uv-managed environment"


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
    _require_uv()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    proj = tmp_path / "proj"
    script = _project(proj)
    start = proj / "a" / "b c"
    start.mkdir(parents=True)
    command, args = _launch(ROOT / ".github/mcp.json")

    done = subprocess.run([command, *args], cwd=start, input="ping\n", capture_output=True,
                          text=True, timeout=180, check=False)

    _assert_ran_stub(done, script, start)
    assert not (proj / ".venv").exists(), "the launch created a project venv"
    assert not (proj / "uv.lock").exists(), "the launch wrote a uv.lock"


def test_the_launch_ignores_a_python_version_pin_above_the_start_dir(tmp_path, monkeypatch):
    """A `.python-version` the launcher's own interpreter cannot satisfy must not stop the launch."""
    _require_uv()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setenv("UV_OFFLINE", "1")
    proj = tmp_path / "proj"
    script = _project(proj)
    (proj / ".python-version").write_text("3.0\n", encoding="utf-8")
    start = proj / "a"
    start.mkdir()
    command, args = _launch(ROOT / ".github/mcp.json")

    done = subprocess.run([command, *args], cwd=start, input="ping\n", capture_output=True,
                          text=True, timeout=180, check=False)

    _assert_ran_stub(done, script, start)


def test_the_nearest_project_above_the_start_dir_wins(tmp_path, monkeypatch):
    """With nested projects, the walk-up runs the inner project's script, not the outer one."""
    _require_uv()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    outer = tmp_path / "proj"
    inner = outer / "inner"
    _project(outer, _stub('print("outer", flush=True)\nsys.stdin.read()\n'))
    _project(inner, _stub('print("inner", flush=True)\nsys.stdin.read()\n'))
    start = inner / "a"
    start.mkdir()
    command, args = _launch(ROOT / ".github/mcp.json")

    done = subprocess.run([command, *args], cwd=start, input="", capture_output=True,
                          text=True, timeout=180, check=False)

    assert done.stdout.split() == ["inner"], f"stdout={done.stdout!r}\nstderr:\n{done.stderr}"


def test_the_launch_runs_when_uv_is_not_on_path(tmp_path, monkeypatch):
    """Given an absolute uv, the launch still finds uv for its inner call through $UV."""
    uv = _require_uv()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    names = ("uv", "uv.exe")
    kept = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if not any((Path(d) / name).exists() for name in names)]
    monkeypatch.setenv("PATH", os.pathsep.join(kept))
    assert shutil.which("uv") is None
    proj = tmp_path / "proj"
    script = _project(proj)
    start = proj / "a"
    start.mkdir()
    _, args = _launch(ROOT / ".github/mcp.json")

    done = subprocess.run([uv, *args], cwd=start, input="ping\n", capture_output=True,
                          text=True, timeout=180, check=False)

    _assert_ran_stub(done, script, start)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals; Windows teardown is probed in CI separately")
def test_sigterm_to_the_launch_stops_the_server_while_stdin_stays_open(tmp_path, monkeypatch):
    """Terminating the launch must take its server child down, not orphan it."""
    _require_uv()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    proj = tmp_path / "proj"
    _project(proj, PID_STUB)
    command, args = _launch(ROOT / ".github/mcp.json")
    top = subprocess.Popen([command, *args], cwd=proj, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = 0
    try:
        pid = int(top.stdout.readline())
        top.send_signal(signal.SIGTERM)
        top.wait(timeout=30)
        deadline = time.monotonic() + 10
        gone = False
        while time.monotonic() < deadline and not gone:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                gone = True
        assert gone, f"server pid {pid} outlived the launch"
    finally:
        top.stdin.close()
        top.kill()
        top.wait()
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_the_launch_names_the_missing_script_and_exits_1_outside_a_project(tmp_path):
    """With no project script at or above the cwd, the launch says which file and exits 1."""
    _, args = _launch(ROOT / ".github/mcp.json")
    assert args[:-1] == ["run", "--no-project", "--python", "3", "python", "-c"], args
    empty = tmp_path / "empty"
    empty.mkdir()

    done = subprocess.run([sys.executable, "-c", args[-1]], cwd=empty, capture_output=True,
                          text=True, timeout=60, check=False)

    assert done.returncode == 1, f"rc={done.returncode}\nstderr:\n{done.stderr}"
    assert done.stderr.startswith(f"task-graph: {SCRIPT_REL} not found at or above"), done.stderr
    assert os.path.realpath(empty) in done.stderr or str(empty) in done.stderr, done.stderr


def test_every_generated_file_carries_the_declared_launch():
    """The Claude/Copilot and pi files launch task-graph exactly as the catalog declares it."""
    declared = _declared_launch()
    assert _launch(ROOT / ".github/mcp.json") == declared
    assert _launch(ROOT / ".pi/mcp.json") == declared
