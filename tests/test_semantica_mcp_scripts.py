"""Tests for semantica MCP prerequisite scripts (check.py and install.py)."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch


def _fake_subprocess_ok(cmd, **kwargs):
    """A subprocess that always succeeds; returns --version or probe output."""
    if cmd[-1] == "--version":
        return types.SimpleNamespace(returncode=0, stdout="semantica 0.6.6\n", stderr="")
    return types.SimpleNamespace(returncode=0, stdout='{"format": "json", "data": "{}"}\n', stderr="")


fake_subprocess_ok = _fake_subprocess_ok


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


def test_probe_runs_in_the_resolved_interpreter_not_ambient_python(tmp_path, load_script):
    """The probe must execute inside the resolved semantica env.

    A uv-tool / pipx install's `semantica` executable lives in its own venv;
    the ambient python check.py runs under cannot import semantica at all, so
    an in-process probe silently reports success there. The probe must shell
    out to the interpreter beside the resolved executable (the architect
    finding: probe against the RESOLVED environment, with a timeout).
    """
    check = load_script("features/common/mcp/semantica/scripts/check.py")

    calls = {}

    def fake_resolve(exe):
        calls["resolved"] = exe
        return "/resolved/venv/bin/python"

    def fake_subprocess(cmd, **kwargs):
        calls["cmd"] = cmd
        if cmd[-1] == "--version":
            return types.SimpleNamespace(returncode=0, stdout="semantica 0.6.5\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="{\"error\": \"broken\"}\n", stderr="")

    with patch.object(check, "find_semantica_executable", return_value="/resolved/venv/bin/semantica"), \
         patch.object(check, "_interpreter_for_executable", fake_resolve), \
         patch.object(check.subprocess, "run", fake_subprocess):
        ret = check.main(["--target", str(tmp_path)])

    assert ret == 0
    assert calls["resolved"] == "/resolved/venv/bin/semantica"
    assert calls["cmd"][0] == "/resolved/venv/bin/python"
    assert "export_graph" in calls["cmd"][-1]  # probe snippet mentions the tool


def test_probe_without_resolved_interpreter_stays_silent(tmp_path, load_script, capsys):
    """No interpreter beside the exe: warn nothing rather than misattribute."""
    check = load_script("features/common/mcp/semantica/scripts/check.py")

    with patch.object(check, "find_semantica_executable", return_value="/some/bin/semantica"), \
         patch.object(check, "_interpreter_for_executable", return_value=None), \
         patch.object(check.subprocess, "run", _fake_subprocess_ok):
        ret = check.main(["--target", str(tmp_path)])

    assert ret == 0
    assert "WARNING" not in capsys.readouterr().err


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


def test_wrapper_fallback_saves_export_when_native_broken(tmp_path, load_script):
    """When the native probe returns an error, export_graph_works tries the wrapper."""
    check = load_script("features/common/mcp/semantica/scripts/check.py")

    broken = {"error": "JSONExporter.export() missing file_path"}
    fixed = {"format": "json", "data": '{"nodes": []}'}

    with patch.object(check, "_probe_export_graph", return_value=broken), \
         patch.object(check, "_wrapper_script_path", return_value=Path("/nonexistent")), \
         patch.object(check, "_probe_wrapper_in_interpreter", return_value=fixed):
        # Wrapper exists and works → export_graph_works should return True
        assert check.export_graph_works(exe="/fake/semantica") is True

    with patch.object(check, "_probe_export_graph", return_value=broken), \
         patch.object(check, "_wrapper_script_path", return_value=None):
        # No wrapper → export_graph_works should return False
        assert check.export_graph_works() is False
