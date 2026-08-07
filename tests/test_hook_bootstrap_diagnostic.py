"""The Hermes plugin must say why it could not find the framework, not fail silently.

`ai_badger_hooks._bootstrap_lib()` raises a `RuntimeError` naming every place it looked and
what to do about it. The module discarded that message and set `FRAMEWORK_ROOT = None`, so the
plugin loaded, registered all four hooks, and did nothing at all with no output anywhere
(theme B, B2). Lesser problems in the same module already print to stderr.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

HOOKS = "features/common/hooks/ai_badger_hooks.py"


def _load_stranded(tmp_path, root, monkeypatch):
    """Import a copy of the plugin with no framework above it and an empty home."""
    home = tmp_path / "home"
    home.mkdir()
    stranded = tmp_path / "plugins" / "ai-badger" / "ai_badger_hooks.py"
    stranded.parent.mkdir(parents=True)
    shutil.copy2(root / HOOKS, stranded)
    monkeypatch.delenv("AI_BADGER", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(tmp_path)

    spec = importlib.util.spec_from_file_location("aib_stranded_hooks", stranded)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_stranded_plugin_prints_why_it_found_no_framework(tmp_path, root, monkeypatch,
                                                            capsys):
    module = _load_stranded(tmp_path, root, monkeypatch)

    assert module.FRAMEWORK_ROOT is None, "the fixture is not rootless; it proves nothing"
    err = capsys.readouterr().err
    assert "could not locate the ai-badger framework" in err
    assert err.startswith("ai-badger: ")


def test_the_diagnostic_is_printed_once(tmp_path, root, monkeypatch, capsys):
    """One line per load: a session-start hook must not shout on every callback."""
    _load_stranded(tmp_path, root, monkeypatch)

    err = capsys.readouterr().err
    assert err.count("could not locate the ai-badger framework") == 1
