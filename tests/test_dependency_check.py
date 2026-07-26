"""Tests for dependency_check.py — verifies feature dependency detection and installation."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPT = "features/common/skills/welcome-ai-badger/scripts/dependency_check.py"


@pytest.fixture
def dep_root(tmp_path):
    """Fake framework root with dependencies.json."""
    deps = {
        "dependencies": [
            {
                "feature": "code-review-graph",
                "path": "features/common/skills/code-review-graph",
                "dependencies": [
                    {
                        "name": "code-review-graph",
                        "ecosystem": "python",
                        "package": "code-review-graph",
                        "venv": True,
                    }
                ],
            },
            {
                "feature": "some-node-tool",
                "path": "features/common/skills/some-node-tool",
                "dependencies": [
                    {
                        "name": "some-node-tool",
                        "ecosystem": "node",
                        "package": "some-node-tool",
                    }
                ],
            },
        ]
    }
    (tmp_path / "features" / "common").mkdir(parents=True)
    (tmp_path / "features" / "common" / "dependencies.json").write_text(
        json.dumps(deps), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def dep_target(tmp_path):
    """Fake project target dir."""
    return tmp_path / "project"


def test_missing_file(load_script, tmp_path):
    dc = load_script(SCRIPT)
    result = dc.run_dependency_check(tmp_path, tmp_path)
    assert result == {"installed": [], "already_present": [], "errors": []}


def test_venv_created_for_python_dep(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    result = dc.run_dependency_check(dep_root, dep_target, features=["code-review-graph"])
    venv_path = dep_target / ".venv"
    assert venv_path.exists()
    assert (venv_path / "bin" / "python3").exists() or (venv_path / "Scripts").exists()


def test_venv_not_created_when_already_exists(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    venv = dep_target / ".venv"
    venv.mkdir()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dc.run_dependency_check(dep_root, dep_target, features=["code-review-graph"])
        create_calls = [c for c in mock_run.call_args_list if "venv" in str(c)]
        assert len(create_calls) == 0


def test_pip_install_in_venv(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dc.run_dependency_check(dep_root, dep_target, features=["code-review-graph"])
        # With uv available, uses "uv pip install"; without uv, uses .venv/bin/pip
        install_calls = [
            c for c in mock_run.call_args_list
            if "install" in str(c.args[0])
        ]
        assert len(install_calls) >= 1
        cmd = install_calls[-1].args[0]
        assert "code-review-graph" in cmd


def test_uv_used_when_available(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    call_count = [0]
    def fake_run(cmd, **kw):
        call_count[0] += 1
        if cmd[0] == "uv" and cmd[1] == "--version":
            return MagicMock(returncode=0, stdout="uv 0.4.0", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", side_effect=fake_run):
        dc.run_dependency_check(dep_root, dep_target, features=["code-review-graph"])
        assert call_count[0] >= 2


def test_uv_unavailable_falls_back_to_pip(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    def fake_run(cmd, **kw):
        if cmd[0] == "uv":
            raise FileNotFoundError("uv not found")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", side_effect=fake_run):
        result = dc.run_dependency_check(dep_root, dep_target, features=["code-review-graph"])
        assert "code-review-graph" in result["installed"]


def test_install_error_recorded(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    def fake_run(cmd, **kw):
        if cmd[0] == "uv" and cmd[1] == "--version":
            raise FileNotFoundError()
        if "install" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="no such package")
        return MagicMock(returncode=0, stdout="", stderr="")
    with patch("subprocess.run", side_effect=fake_run):
        result = dc.run_dependency_check(dep_root, dep_target, features=["code-review-graph"])
        assert len(result["errors"]) == 1
        assert "code-review-graph" in result["errors"][0]


def test_node_ecosystem_uses_npx(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dc.run_dependency_check(dep_root, dep_target, features=["some-node-tool"])
        install_calls = [
            c for c in mock_run.call_args_list
            if any("install" in str(a) for a in c.args[0] if isinstance(a, str))
        ]
        assert len(install_calls) >= 1
        cmd = install_calls[0].args[0]
        assert cmd[0] == "npm"
        assert "install" in cmd


def test_multiple_ecosystems(load_script, dep_root, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = dc.run_dependency_check(
            dep_root, dep_target, features=["code-review-graph", "some-node-tool"]
        )
        assert len(result["installed"]) == 2


def test_get_venv_python_no_venv(load_script, dep_target):
    dc = load_script(SCRIPT)
    assert dc.get_venv_python(dep_target) is None


def test_get_venv_python_with_venv(load_script, dep_target):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    venv = dep_target / ".venv"
    venv.mkdir()
    result = dc.get_venv_python(dep_target)
    assert result is not None
    assert ".venv" in result


def test_detect_new_deps(load_script, dep_root):
    dc = load_script(SCRIPT)
    new = dc.detect_new_deps(dep_root, ["code-review-graph", "some-node-tool"])
    assert new == []


def test_detect_new_deps_finds_unscaffolded(load_script, dep_root):
    dc = load_script(SCRIPT)
    new = dc.detect_new_deps(dep_root, [])
    assert len(new) == 2
    features = [d["feature"] for d in new]
    assert "code-review-graph" in features


def test_cli_main(load_script, dep_root, dep_target, capsys):
    dc = load_script(SCRIPT)
    dep_target.mkdir(parents=True)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        code = dc.main(["--root", str(dep_root), "--target", str(dep_target)])
    assert code == 0
    out_text = capsys.readouterr().out
    # The JSON is on the last lines — find it
    json_start = out_text.index("{")
    out = json.loads(out_text[json_start:])
    assert "installed" in out
