"""Tests for the skill_manage branch of features/common/hooks/ai_badger_hooks.py.

Hook wiring only; the sync logic itself is covered by tests/test_learned_skills_sync.py.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import logging
import os
import sys
import types
from unittest.mock import patch

import pytest

SKILL_ARGS = {"action": "create", "name": "apple-notes", "category": "apple"}


@pytest.fixture
def hooks(load_script):
    """Load the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def fake_sync(hooks, monkeypatch):
    """Stub out learned_skills_sync and return the list of recorded calls."""
    calls = []
    module = types.ModuleType(hooks.SYNC_MODULE_NAME)

    def on_skill_manage(args, status, cwd, **kwargs):
        calls.append(dict(kwargs, args=args, status=status, cwd=cwd))
        return {"action": "created", "target": "x", "reason": ""}

    module.on_skill_manage = on_skill_manage
    monkeypatch.setitem(sys.modules, hooks.SYNC_MODULE_NAME, module)
    return calls


def test_register_registers_post_tool_call_once(hooks):
    registered = []

    class _Ctx:
        def register_hook(self, name, callback):
            registered.append((name, callback))

    hooks.register(_Ctx())

    post = [cb for name, cb in registered if name == "post_tool_call"]
    assert post == [hooks.post_tool_observer]


def test_post_tool_observer_delegates_skill_manage_to_sync(tmp_path, hooks, fake_sync):
    hooks.post_tool_observer(tool_name="skill_manage", args=SKILL_ARGS,
                             status="ok", cwd=str(tmp_path))

    assert len(fake_sync) == 1
    call = fake_sync[0]
    assert call["args"] == SKILL_ARGS
    assert call["status"] == "ok"
    assert call["cwd"] == str(tmp_path)
    assert call["tool_name"] == "skill_manage"
    assert call["skills_root"] == hooks.hermes_skills_root()
    assert call["now"].endswith("Z")


def test_post_tool_observer_falls_back_to_process_cwd(hooks, fake_sync):
    """Hermes does not pass cwd to post_tool_call; the process cwd is the only signal."""
    hooks.post_tool_observer(tool_name="skill_manage", args=SKILL_ARGS, status="ok")

    assert fake_sync[0]["cwd"] == os.getcwd()


def test_post_tool_observer_does_not_call_sync_for_other_tools(tmp_path, hooks, fake_sync):
    hooks.post_tool_observer(tool_name="terminal", args={"command": "ls"},
                             status="ok", cwd=str(tmp_path))

    assert fake_sync == []


def test_post_tool_observer_swallows_sync_exceptions(tmp_path, hooks, monkeypatch, caplog):
    module = types.ModuleType(hooks.SYNC_MODULE_NAME)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("sync exploded")

    module.on_skill_manage = _boom
    monkeypatch.setitem(sys.modules, hooks.SYNC_MODULE_NAME, module)

    with caplog.at_level(logging.DEBUG, logger="ai_badger_hooks"):
        assert hooks.post_tool_observer(tool_name="skill_manage", args=SKILL_ARGS,
                                        status="ok", cwd=str(tmp_path)) is None

    assert any("learned-skill sync" in rec.getMessage() for rec in caplog.records)


def test_post_tool_observer_is_inert_without_sync_module(tmp_path, hooks, monkeypatch):
    """An older scaffold has no learned_skills_sync.py; the plugin must still work."""
    monkeypatch.setattr(hooks, "_load_learned_skills_sync", lambda: None)

    assert hooks.post_tool_observer(tool_name="skill_manage", args=SKILL_ARGS,
                                    status="ok", cwd=str(tmp_path)) is None


def test_hermes_skills_root_prefers_hermes_home_env(tmp_path, hooks, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hh"))

    assert hooks.hermes_skills_root() == tmp_path / "hh" / "skills"


def test_hermes_skills_root_falls_back_to_home(tmp_path, hooks, monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)

    with patch("pathlib.Path.home", return_value=tmp_path):
        assert hooks.hermes_skills_root() == tmp_path / ".hermes" / "skills"
