"""tool_catalog: the scaffold's view of the opt-in CLI tools a project enables (ADR-0039).

The collaborator reads `config.tools`, joins each name to its catalog `meta.json`, names the
prerequisite with absolute framework paths, runs check/install only under --execute, and
resolves each opted-in agent's arm from config alone.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import shutil
import subprocess
import sys
import types

import pytest

from scaffold_helpers import _config

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"
RTK = "features/common/tools/rtk"


@pytest.fixture
def tool_catalog(load_script, root):
    for entry in (str(root / SCRIPTS), str(root / "engine")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/tool_catalog.py")


class Runner:
    """Stands in for subprocess.run: records which prerequisite script ran, in order."""

    def __init__(self, calls, check_codes=(0,), install_code=0):
        self.calls = calls
        self.check_codes = list(check_codes)
        self.install_code = install_code
        self.argv = []

    def __call__(self, argv, **_kwargs):
        self.argv.append(argv)
        script = argv[1]
        if script.endswith("check.py"):
            self.calls.append("check")
            code = self.check_codes.pop(0)
        else:
            self.calls.append("install")
            code = self.install_code
        return subprocess.CompletedProcess(argv, code, "", "")


def _ctx(root, tmp_path, tools=None, agents=("claude", "codex", "copilot", "pi", "hermes")):
    import badger_lib as bl
    from scaffold_context import ScaffoldContext

    config = _config(stacks=["python"], agents=list(agents))
    if tools is not None:
        config["tools"] = tools
    return ScaffoldContext(
        root=root, target=tmp_path, aib=tmp_path / ".ai-badger", config=config,
        index=bl.read_index(root), stacks=bl.resolve_stacks(config), skills=[], excluded={})


def _catalog(tool_catalog, ctx, execute=False, runner=None):
    return tool_catalog.ToolCatalog(ctx, execute=execute, run=runner or Runner([]))


ALL = {"rtk": {"hooks": ["claude", "codex", "copilot", "pi", "hermes"]}}


# -- s5-a1: notes and the empty case -------------------------------------------------------

def test_no_config_tools_gives_no_notes_and_no_tools(tool_catalog, root, tmp_path):
    ctx = _ctx(root, tmp_path)

    tools = _catalog(tool_catalog, ctx, execute=True).prepare()

    assert tools == {}
    assert ctx.notes == []


def test_enabled_tool_notes_its_prerequisite_with_absolute_framework_paths(
        tool_catalog, root, tmp_path):
    ctx = _ctx(root, tmp_path, tools={"rtk": {}})

    _catalog(tool_catalog, ctx).prepare()

    [note] = [n for n in ctx.notes if n.startswith("prerequisite — rtk")]
    assert f"python3 {root / RTK / 'scripts' / 'check.py'}" in note
    assert f"python3 {root / RTK / 'scripts' / 'install.py'} --run" in note
    assert " features/common" not in note


def test_empty_hooks_still_enables_the_tool_with_no_arms(tool_catalog, root, tmp_path):
    """Intersection: enabled, no hooks, no --execute — present, armless, check unknown."""
    ctx = _ctx(root, tmp_path, tools={"rtk": {}})

    tools = _catalog(tool_catalog, ctx).prepare()

    assert tools["rtk"]["agents"] == {}
    assert tools["rtk"]["check_ok"] is None
    assert tools["rtk"]["meta"]["name"] == "rtk"


# -- s5-a2: what runs, and when ------------------------------------------------------------

def test_order_without_execute_nothing_runs(tool_catalog, root, tmp_path):
    calls = []
    ctx = _ctx(root, tmp_path, tools=ALL)

    tools = _catalog(tool_catalog, ctx, runner=Runner(calls)).prepare()

    assert calls == []
    assert tools["rtk"]["check_ok"] is None


def test_order_execute_with_a_passing_check_skips_install(tool_catalog, root, tmp_path):
    calls = []
    ctx = _ctx(root, tmp_path, tools=ALL)

    tools = _catalog(tool_catalog, ctx, execute=True, runner=Runner(calls, [0])).prepare()

    assert calls == ["check"]
    assert tools["rtk"]["check_ok"] is True


def test_order_execute_with_a_failing_check_installs_with_run_then_rechecks(
        tool_catalog, root, tmp_path):
    calls = []
    runner = Runner(calls, check_codes=[1, 0])
    ctx = _ctx(root, tmp_path, tools=ALL)

    tools = _catalog(tool_catalog, ctx, execute=True, runner=runner).prepare()

    assert calls == ["check", "install", "check"]
    assert runner.argv[1] == [sys.executable, str(root / RTK / "scripts" / "install.py"), "--run"]
    assert tools["rtk"]["check_ok"] is True


def test_order_execute_with_a_failed_install_leaves_check_false(tool_catalog, root, tmp_path):
    calls = []
    runner = Runner(calls, check_codes=[1], install_code=1)
    ctx = _ctx(root, tmp_path, tools=ALL)

    tools = _catalog(tool_catalog, ctx, execute=True, runner=runner).prepare()

    assert calls == ["check", "install"]
    assert tools["rtk"]["check_ok"] is False
    assert any("rtk" in n and "install" in n and "failed" in n for n in ctx.notes)


def test_order_prepare_runs_once_however_often_it_is_asked(tool_catalog, root, tmp_path):
    calls = []
    catalog = _catalog(tool_catalog, _ctx(root, tmp_path, tools=ALL), execute=True,
                       runner=Runner(calls, [0, 0]))

    catalog.prepare()
    catalog.prepare()

    assert calls == ["check"]


def test_order_scaffold_runs_check_and_install_before_adjustments_with_tools_in_context(
        make_scaffolder, monkeypatch, tmp_path):
    """Scaffolder.run: check -> install -> every adjustment, each handed the tools map."""
    import importlib.util

    calls, seen = [], []
    capture = types.ModuleType("tool_catalog_capture")
    capture.SEEN = seen
    capture.CALLS = calls
    monkeypatch.setitem(sys.modules, "tool_catalog_capture", capture)
    fake = tmp_path / "fake_adjust.py"
    fake.write_text(
        "import tool_catalog_capture as c\n"
        "def adjust(context):\n"
        "    c.CALLS.append('adjust')\n"
        "    c.SEEN.append(context)\n"
        "    return {'applied': False, 'notes': 'captured'}\n", encoding="utf-8")
    real_spec = importlib.util.spec_from_file_location
    monkeypatch.setattr(importlib.util, "spec_from_file_location",
                        lambda name, _path: real_spec(name, fake))

    config = _config(stacks=["python"], agents=["claude"])
    config["tools"] = {"rtk": {"hooks": ["claude"]}}
    scaf = make_scaffolder(config=config, execute=True)
    scaf.tools.run = Runner(calls, check_codes=[1, 0])
    monkeypatch.setattr(scaf, "install_plugins", lambda: [])
    monkeypatch.setattr(scaf, "_check_dependencies",
                        lambda: {"installed": [], "errors": [], "hints": []})

    scaf.run(generated_at="2026-10-17T00:00:00Z")

    assert calls[:3] == ["check", "install", "check"]
    assert calls[3:] and set(calls[3:]) == {"adjust"}
    tools = seen[0]["tools"]
    assert set(tools) == {"rtk"}
    assert tools["rtk"]["check_ok"] is True
    assert set(tools["rtk"]["agents"]) == {"claude"}
    assert tools["rtk"]["meta"]["name"] == "rtk"


# -- s5-a3: what is skipped, and said ------------------------------------------------------

def test_a_hook_agent_missing_from_config_agents_is_warned_and_skipped(
        tool_catalog, root, tmp_path):
    ctx = _ctx(root, tmp_path, tools={"rtk": {"hooks": ["claude", "codex"]}},
               agents=("claude",))

    tools = _catalog(tool_catalog, ctx).prepare()

    assert set(tools["rtk"]["agents"]) == {"claude"}
    assert any("codex" in n and "config.agents" in n for n in ctx.notes)


def test_a_tool_missing_from_the_catalog_is_warned_and_skipped(tool_catalog, root, tmp_path):
    ctx = _ctx(root, tmp_path, tools={"nosuchtool": {"hooks": ["claude"]}, "rtk": {}})

    tools = _catalog(tool_catalog, ctx).prepare()

    assert set(tools) == {"rtk"}
    assert any("nosuchtool" in n and "catalog" in n for n in ctx.notes)
    assert not any(n.startswith("prerequisite — nosuchtool") for n in ctx.notes)


# -- s5-a4: native arms read config only ---------------------------------------------------

def _no_which(*_args, **_kwargs):
    raise AssertionError("shutil.which must not be called")


def test_no_which_native_arms_resolve_from_config_alone(
        tool_catalog, root, tmp_path, monkeypatch):
    tool_hooks = sys.modules.get("tool_hooks") or __import__("tool_hooks")
    monkeypatch.setattr(shutil, "which", _no_which)
    ctx = _ctx(root, tmp_path, tools=ALL)

    agents = _catalog(tool_catalog, ctx).prepare()["rtk"]["agents"]

    assert agents["copilot"] == {"mode": "native", "arg": "copilot",
                                 "command": tool_hooks.guarded_command("rtk", "copilot")}
    for agent in ("claude", "codex"):
        assert agents[agent] == {"mode": "propose", "arg": agent}
    assert agents["hermes"] == {"mode": "propose", "arg": "hermes"}


@pytest.mark.parametrize("check_codes, expected", [([0], True), ([1, 1], False)])
def test_no_which_init_arm_runs_only_when_the_check_passed(
        tool_catalog, root, tmp_path, monkeypatch, check_codes, expected):
    monkeypatch.setattr(shutil, "which", _no_which)
    ctx = _ctx(root, tmp_path, tools=ALL)

    agents = _catalog(tool_catalog, ctx, execute=True,
                      runner=Runner([], check_codes)).prepare()["rtk"]["agents"]

    assert agents["pi"] == {"mode": "init", "arg": "pi", "run": expected}


def test_no_which_init_arm_does_not_run_without_execute(tool_catalog, root, tmp_path):
    agents = _catalog(tool_catalog, _ctx(root, tmp_path, tools=ALL)).prepare()["rtk"]["agents"]

    assert agents["pi"]["run"] is False


# -- s5-a5: POSIX only ---------------------------------------------------------------------

def test_posix_only_windows_resolves_no_arms_and_says_so(
        tool_catalog, root, tmp_path, monkeypatch):
    ctx = _ctx(root, tmp_path, tools=ALL)
    catalog = _catalog(tool_catalog, ctx)

    # Scoped: pytest's own reporting builds paths, and os.name='nt' breaks pathlib there.
    with monkeypatch.context() as patch:
        patch.setattr(tool_catalog.os, "name", "nt")
        tools = catalog.prepare()

    assert tools["rtk"]["agents"] == {}
    assert any("rtk" in n and "POSIX-only" in n for n in ctx.notes)
