"""A missing pyyaml must degrade ai_badger_hooks.py, not take it down (issue #136).

Mirrors test_mcp_index.py::test_missing_yaml_degrades_with_a_message, the guarded-import model.
"""
# pylint: disable=protected-access  # hook internals under direct test

from __future__ import annotations

import builtins


def _no_yaml_import(monkeypatch):
    """Make `import yaml` raise ImportError for the next module load."""
    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)


def test_module_imports_with_yaml_absent(load_script, monkeypatch):
    """The module must import even when pyyaml cannot be imported at all."""
    _no_yaml_import(monkeypatch)
    hooks = load_script("features/common/hooks/ai_badger_hooks.py")
    assert hooks.yaml is None


def test_register_still_registers_every_hook_with_yaml_absent(load_script, monkeypatch):
    """register() must still wire all three hooks when pyyaml is unavailable."""
    _no_yaml_import(monkeypatch)
    hooks = load_script("features/common/hooks/ai_badger_hooks.py")

    registered = {}

    class DummyCtx:  # pylint: disable=too-few-public-methods
        def register_hook(self, name, callback):
            registered[name] = callback

    hooks.register(DummyCtx())

    assert set(registered) == {"on_session_start", "pre_llm_call", "post_tool_call"}


def test_non_yaml_hooks_still_fire_with_yaml_absent(load_script, monkeypatch, tmp_path):
    """The drift notice, usage hints, and tool observer keep working without pyyaml."""
    _no_yaml_import(monkeypatch)
    hooks = load_script("features/common/hooks/ai_badger_hooks.py")
    hooks.reset_session_hints()

    project = str(tmp_path)

    # session start must not raise on an unscaffolded project
    hooks.on_session_start_drift_notice(cwd=project)

    # usage hints still inject even though the MCP-index path is unreachable
    result = hooks.pre_llm_inject_context(cwd=project, message="build the solution")
    assert result is not None
    assert "/usage" in result["context"]

    # tool observer must not raise
    hooks.post_tool_observer(tool_name="rider:build_solution", result="{}", duration_ms=1)


def test_mcp_index_is_unreachable_but_silent_with_yaml_absent(load_script, monkeypatch, tmp_path):
    """_load_mcp_index degrades to None rather than raising AttributeError on `yaml.safe_load`.

    A real mcp-tools.yaml on disk proves the guard fires before any yaml attribute access,
    not merely because the file was missing.
    """
    _no_yaml_import(monkeypatch)
    hooks = load_script("features/common/hooks/ai_badger_hooks.py")

    aib = tmp_path / ".ai-badger"
    aib.mkdir()
    (aib / "mcp-tools.yaml").write_text("sources: []\n", encoding="utf-8")

    assert hooks._load_mcp_index(str(tmp_path)) is None
