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


def test_the_venv_is_built_with_the_interpreter_that_was_chosen(tmp_path, load_script):
    """ensure_venv must build with py_exe, not with whatever is running.

    It printed py_exe and then called venv.EnvBuilder(), which uses the running
    interpreter — so any interpreter selection upstream was decorative. On a machine
    whose default python is 3.14 that silently produces a venv where semantica's
    gensim dependency has no wheel and its source build fails.
    """
    install = load_script("features/common/mcp/semantica/scripts/install.py")
    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        (tmp_path / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(install.subprocess, "run", side_effect=fake_run):
        install.ensure_venv(tmp_path, "/fake/python3.13")

    flat = [part for cmd in recorded for part in cmd]
    assert "/fake/python3.13" in flat, (
        f"ensure_venv never invoked the chosen interpreter; recorded: {recorded}"
    )


def test_a_gensim_build_failure_names_its_cause(tmp_path, load_script, capsys):
    """A pip failure carrying the gensim source-build signature explains itself.

    Deliberately a diagnostic, not a version gate: hardcoding an upper bound would
    have to agree with gensim's wheel matrix and nothing compares them, so it would
    block a working interpreter the day a cp314 wheel ships.
    """
    install = load_script("features/common/mcp/semantica/scripts/install.py")
    stderr = (
        "gensim/models/word2vec_inner.c:1686:65: error: no member named "
        "'ma_version_tag' in 'struct PyDictObject'\n"
    )
    assert "gensim" in install.explain_install_failure(stderr).lower()
    assert "wheel" in install.explain_install_failure(stderr).lower()
    assert install.explain_install_failure("some unrelated pip error") == ""


# ── check.py: no fallback may rescue a broken native probe ──────────────────

def test_no_fallback_rescues_a_broken_native_probe(tmp_path, load_script):
    """A working wrapper must not make check.py report a broken export as healthy.

    The wrapper patches export_graph in-process, but nothing launches it: the MCP
    entry runs the `semantica-mcp` console script. So a fallback that consults the
    wrapper reports a capability the running server does not have, and the warning
    that should reach the user is suppressed.

    Red-state note: this test builds a real bin layout so
    _interpreter_for_executable resolves (otherwise export_graph_works short-circuits
    to True and proves nothing), and discriminates on the wrapper snippet so the
    native probe fails while the wrapper probe succeeds.
    """
    check = load_script("features/common/mcp/semantica/scripts/check.py")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "semantica"
    exe.write_text("", encoding="utf-8")
    (bindir / "python").write_text("", encoding="utf-8")

    broken = '{"error": "JSONExporter.export() missing 1 required positional argument"}'
    healthy = '{"format": "json", "data": "{}"}'

    def fake_run(cmd, **kwargs):
        snippet = cmd[-1] if len(cmd) > 2 else ""
        payload = healthy if "semantica_mcp_wrapper" in snippet else broken
        return types.SimpleNamespace(returncode=0, stdout=payload + "\n", stderr="")

    with patch.object(check.subprocess, "run", side_effect=fake_run):
        assert check.export_graph_works(exe=str(exe)) is False, (
            "a wrapper the launch path never uses must not rescue the probe"
        )
