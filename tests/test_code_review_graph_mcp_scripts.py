"""Tests for code-review-graph MCP prerequisite scripts (check.py and install.py)."""
from __future__ import annotations

import sys
from unittest.mock import patch


def test_crg_check_script_returns_zero_when_importable(tmp_path, load_script):
    check = load_script("features/common/mcp/code-review-graph/scripts/check.py")
    with patch.object(check, "can_import_crg", return_value=True), \
         patch.object(check, "check_python_version", return_value=True):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 0


def test_crg_check_script_returns_one_when_python_too_old(tmp_path, load_script):
    check = load_script("features/common/mcp/code-review-graph/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=False):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 1


def test_crg_check_script_returns_one_when_uninstalled(tmp_path, load_script):
    check = load_script("features/common/mcp/code-review-graph/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=True), \
         patch.object(check, "find_crg_executable", return_value=None), \
         patch.object(check, "can_import_crg", return_value=False):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 1


def test_crg_check_reports_not_ready_when_version_works_but_serve_cannot_start(tmp_path, load_script):
    """`--version` exiting 0 is not proof the MCP server can start.

    A venv holding mcp>=2 keeps the CLI working while `serve` dies on
    `from fastmcp import FastMCP`, which is how a clobbered install passed the
    old check and then failed to connect.
    """
    check = load_script("features/common/mcp/code-review-graph/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=True), \
         patch.object(check, "find_crg_executable", return_value="/fake/code-review-graph"), \
         patch.object(check, "can_serve", return_value=False), \
         patch.object(check, "can_import_crg", return_value=False):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 1


def test_crg_check_reports_ready_when_serve_starts(tmp_path, load_script):
    check = load_script("features/common/mcp/code-review-graph/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=True), \
         patch.object(check, "find_crg_executable", return_value="/fake/code-review-graph"), \
         patch.object(check, "can_serve", return_value=True):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 0


def test_crg_can_serve_uses_the_real_serve_entrypoint(load_script):
    """The probe must run `serve`, not `--version`."""
    check = load_script("features/common/mcp/code-review-graph/scripts/check.py")
    seen = {}

    class Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Ok()

    with patch("subprocess.run", side_effect=fake_run):
        assert check.can_serve("/fake/code-review-graph") is True
    assert seen["cmd"][1] == "serve"


def test_crg_install_fails_when_installed_but_cannot_serve(tmp_path, load_script):
    """A clobbered environment must fail the install, not be reported SUCCESS."""
    install = load_script("features/common/mcp/code-review-graph/scripts/install.py")

    def fake_ensure_venv(target, py_exe):
        venv_py = target / ".venv" / "bin" / "python"
        venv_py.parent.mkdir(parents=True, exist_ok=True)
        venv_py.touch()
        (venv_py.parent / "code-review-graph").touch()
        return venv_py

    class Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    with patch.object(install, "find_suitable_python", return_value=sys.executable), \
         patch.object(install, "find_uv", return_value=None), \
         patch.object(install, "ensure_venv", side_effect=fake_ensure_venv), \
         patch.object(install, "verify_serves", return_value=False), \
         patch("subprocess.run", return_value=Ok()):
        ret = install.main(["--target", str(tmp_path)])
        assert ret == 1


def test_crg_install_uses_uv_when_available(tmp_path, load_script):
    """uv resolves and installs the full dependency set when it is on PATH."""
    install = load_script("features/common/mcp/code-review-graph/scripts/install.py")
    calls = []

    class Ok:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Ok()

    def fake_ensure_venv(target, py_exe):
        venv_py = target / ".venv" / "bin" / "python"
        venv_py.parent.mkdir(parents=True, exist_ok=True)
        venv_py.touch()
        (venv_py.parent / "code-review-graph").touch()
        return venv_py

    with patch.object(install, "find_suitable_python", return_value=sys.executable), \
         patch.object(install, "find_uv", return_value="/usr/local/bin/uv"), \
         patch.object(install, "ensure_venv", side_effect=fake_ensure_venv), \
         patch.object(install, "verify_serves", return_value=True), \
         patch("subprocess.run", side_effect=fake_run):
        ret = install.main(["--target", str(tmp_path)])
        assert ret == 0

    assert any("uv" in str(c[0]) and "pip" in c for c in calls), f"uv was not used: {calls}"


def test_crg_install_script_fails_when_no_python_found(tmp_path, load_script):
    install = load_script("features/common/mcp/code-review-graph/scripts/install.py")
    with patch.object(install, "find_suitable_python", return_value=None):
        ret = install.main(["--target", str(tmp_path)])
        assert ret == 1


def test_crg_install_script_creates_venv_and_installs(tmp_path, load_script):
    install = load_script("features/common/mcp/code-review-graph/scripts/install.py")
    mock_py = sys.executable

    def fake_ensure_venv(target, py_exe):
        venv_py = target / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        venv_py.parent.mkdir(parents=True, exist_ok=True)
        venv_py.touch()
        crg_bin = target / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / ("code-review-graph.exe" if sys.platform == "win32" else "code-review-graph")
        crg_bin.touch()
        return venv_py

    class FakeCompletedProcess:
        returncode = 0
        stdout = "code-review-graph 2.3.7"
        stderr = ""

    with patch.object(install, "find_suitable_python", return_value=mock_py), \
         patch.object(install, "ensure_venv", side_effect=fake_ensure_venv), \
         patch("subprocess.run", return_value=FakeCompletedProcess()):
        ret = install.main(["--target", str(tmp_path)])
        assert ret == 0
