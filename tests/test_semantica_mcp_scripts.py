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


def test_semantica_check_warns_when_export_graph_broken(tmp_path, load_script, capsys):
    """0.6.5/0.6.6 export_graph is broken upstream; the check must WARN, not fail.

    The graph tools (record_decision, query_decisions, ...) still work, so a
    fail-closed check would hide semantica entirely for everyone — the exact
    failure the version floor was supposed to avoid. Exit 0 with a warning.
    """
    check = load_script("features/common/mcp/semantica/scripts/check.py")
    with patch.object(check, "check_python_version", return_value=True), \
         patch.object(check, "find_semantica_executable", return_value=None), \
         patch.object(check, "can_import_semantica", return_value=True), \
         patch.object(check, "export_graph_works", return_value=False):
        ret = check.main(["--target", str(tmp_path)])

        assert ret == 0
        captured = capsys.readouterr()
        assert "export_graph" in captured.err.lower() or "export graph" in captured.err.lower()


def test_semantica_check_export_probe_detects_broken_json_branch(tmp_path, load_script):
    """The probe itself must distinguish broken from working, deterministically."""
    check = load_script("features/common/mcp/semantica/scripts/check.py")

    def fake_export(broken):
        def _probe():
            if broken:
                return {"error": "JSONExporter.export() missing 1 required positional argument: 'file_path'"}
            return {"format": "json", "data": "{\"nodes\": []}"}
        return _probe

    with patch.object(check, "_probe_export_graph", fake_export(True)):
        assert check.export_graph_works() is False
    with patch.object(check, "_probe_export_graph", fake_export(False)):
        assert check.export_graph_works() is True


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
