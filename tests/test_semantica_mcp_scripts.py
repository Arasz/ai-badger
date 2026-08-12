"""Tests for semantica MCP prerequisite scripts (check.py and install.py)."""
from __future__ import annotations

import sys
from unittest.mock import patch


def test_semantica_check_script_returns_zero_when_importable(tmp_path, load_script):
    check = load_script("features/common/mcp/semantica/scripts/check.py")
    with patch.object(check, "can_import_semantica", return_value=True), \
         patch.object(check, "check_python_version", return_value=True):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 0


def test_semantica_check_script_returns_one_when_python_too_old(tmp_path, load_script):
    check = load_script("features/common/mcp/semantica/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=False):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 1


def test_semantica_check_script_returns_one_when_uninstalled(tmp_path, load_script):
    check = load_script("features/common/mcp/semantica/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=True), \
         patch.object(check, "find_semantica_executable", return_value=None), \
         patch.object(check, "can_import_semantica", return_value=False):
        ret = check.main(["--target", str(tmp_path)])
        assert ret == 1


def test_semantica_install_script_fails_when_no_python_found(tmp_path, load_script):
    install = load_script("features/common/mcp/semantica/scripts/install.py")
    with patch.object(install, "find_suitable_python", return_value=None):
        ret = install.main(["--target", str(tmp_path)])
        assert ret == 1


def test_semantica_install_script_creates_venv_and_installs(tmp_path, load_script):
    install = load_script("features/common/mcp/semantica/scripts/install.py")
    mock_py = sys.executable

    def fake_ensure_venv(target, py_exe):
        venv_py = target / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        venv_py.parent.mkdir(parents=True, exist_ok=True)
        venv_py.touch()
        return venv_py

    class FakeCompletedProcess:
        returncode = 0
        stdout = "semantica module installed"
        stderr = ""

    with patch.object(install, "find_suitable_python", return_value=mock_py), \
         patch.object(install, "ensure_venv", side_effect=fake_ensure_venv), \
         patch("subprocess.run", return_value=FakeCompletedProcess()):
        ret = install.main(["--target", str(tmp_path)])
        assert ret == 0
