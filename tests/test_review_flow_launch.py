"""Review-flow CLI launch: a missing pydantic is one stderr line and exit 3; uv launches it."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CLI_PATH = (Path(__file__).resolve().parents[1]
            / "features/common/skills/review-flow/scripts/review_flow_cli.py")
CREATE = json.dumps({"repo": "octo/widgets", "pr": 7,
                     "head_sha": "0123456789abcdef0123456789abcdef01234567"})


def _env(tmp_path, **extra):
    return {**os.environ, "HOME": str(tmp_path / "home"),
            "AI_BADGER_TRACKING_ROOT": str(tmp_path / "tracking"), **extra}


def test_pydantic_hidden_exits_3_with_one_stderr_line(tmp_path):
    shadow = tmp_path / "shadow" / "pydantic"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text('raise ImportError("pydantic hidden by the test")\n',
                                        encoding="utf-8")
    done = subprocess.run([sys.executable, str(CLI_PATH), "flow-create", "--json", CREATE],
                          capture_output=True, text=True, check=False, timeout=60, cwd=tmp_path,
                          env=_env(tmp_path, PYTHONPATH=str(shadow.parent)))
    assert done.returncode == 3, done.stderr
    assert done.stdout == ""
    lines = done.stderr.splitlines()
    assert len(lines) == 1 and "pydantic" in lines[0], done.stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_uv_run_script_launches_the_cli(tmp_path):
    done = subprocess.run(["uv", "run", "--script", str(CLI_PATH), "flow-create", "--json",
                           CREATE], capture_output=True, text=True, check=False, timeout=300,
                          cwd=tmp_path, env=_env(tmp_path))
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["phase"] == "context"
