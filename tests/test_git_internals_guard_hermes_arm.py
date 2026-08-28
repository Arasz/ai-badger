"""The Hermes arm of the git-internals guard (pre_tool_call_git_internals_guard).

Hermes does not use Claude's tool names. Its writers are `write_file` (path/content),
`patch` (mode=replace: path/old_string/new_string; mode=patch: a V4A `patch` string naming
files), `terminal` (command) and `execute_code` (code) — read from the tool schemas in
~/.hermes/hermes-agent/tools/{file_tools,terminal_tool,code_execution_tool}.py. Every case
below is the Hermes-shaped equivalent of a Claude payload the guard already refuses.

Payloads carry the full kwarg set `_get_pre_tool_call_directive_details` sends
(hermes_cli/plugins.py): tool_name, args, task_id, session_id, tool_call_id, turn_id,
api_request_id, middleware_trace. A block is `{"action": "block", "message": ...}`; None
allows.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import sys

import pytest

GUARD = "features/common/skills/git-work/scripts/git_internals_guard.py"


@pytest.fixture
def hooks(load_script):
    """A fresh copy of the Hermes plugin module."""
    return load_script("features/common/hooks/ai_badger_hooks.py")


@pytest.fixture
def guard(hooks, load_script, monkeypatch):
    """The real guard module, injected under the sibling-module name the arm imports."""
    module = load_script(GUARD)
    monkeypatch.setitem(sys.modules, hooks.GIT_INTERNALS_GUARD_MODULE_NAME, module)
    return module


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo-shaped cwd: Hermes passes no cwd, so the arm resolves against the process one."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def call(hooks, tool_name, args):
    """Invoke the arm the way hermes_cli.plugins invokes a pre_tool_call callback."""
    return hooks.pre_tool_call_git_internals_guard(
        tool_name=tool_name, args=args, task_id="t1", session_id="s1",
        tool_call_id="call-1", turn_id="turn-1", api_request_id="req-1",
        middleware_trace=[])


def blocked(decision):
    """True when the decision is a block naming git's own writers as the route."""
    return (isinstance(decision, dict) and decision.get("action") == "block"
            and "git config" in decision.get("message", "")
            and "git remote" in decision.get("message", ""))


# ---------------------------------------------------------------------------
# H1 — an edit-shaped Hermes call into a git dir is refused
# ---------------------------------------------------------------------------

def test_write_file_onto_git_config_is_blocked(hooks, guard, repo):
    """write_file is Hermes' Write: its path argument is `path`, not `file_path`."""
    decision = call(hooks, "write_file",
                    {"path": str(repo / ".git" / "config"), "content": "[core]\n"})

    assert blocked(decision), decision
    assert ".git/config" in decision["message"]


def test_patch_replace_onto_git_config_is_blocked(hooks, guard, repo):
    """patch(mode=replace) edits in place; the same `path` key carries the target."""
    decision = call(hooks, "patch", {
        "mode": "replace", "path": str(repo / ".git" / "config"),
        "old_string": "[core]", "new_string": "[core]\n\tbare = true"})

    assert blocked(decision), decision


def test_patch_v4a_naming_a_git_dir_file_is_blocked(hooks, guard, repo):
    """mode=patch names its files inside the patch text — no path argument at all."""
    body = ("*** Begin Patch\n*** Update File: " + str(repo / ".git" / "config")
            + "\n@@\n-[core]\n+[core]\n*** End Patch\n")
    decision = call(hooks, "patch", {"mode": "patch", "patch": body})

    assert blocked(decision), decision


def test_write_file_onto_the_worktree_pointer_file_is_blocked(hooks, guard, tmp_path,
                                                              monkeypatch):
    """A linked worktree's `.git` is a FILE; rewriting it detaches the tree from its repo."""
    monkeypatch.chdir(tmp_path)
    decision = call(hooks, "write_file",
                    {"path": str(tmp_path / ".git"), "content": "gitdir: /elsewhere\n"})

    assert blocked(decision), decision


# ---------------------------------------------------------------------------
# H2 — a terminal call that mutates a git dir is refused
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "cat > .git/config <<EOF\n[core]\nEOF",
    "sed -i '' -e 's/x/y/' .git/config",
    "echo '[core]' | tee .git/config",
    "truncate -s 0 .git",
    "rm -f .git/config",
    "python3 -c \"open('.git/config','w').write('')\"",
], ids=["heredoc", "sed-i", "tee", "truncate", "rm", "python-c"])
def test_terminal_mutation_of_a_git_dir_is_blocked(hooks, guard, repo, command):
    """The guard's own shell rule, reached under Hermes' tool name and `command` key."""
    decision = call(hooks, "terminal", {"command": command, "timeout": 30})

    assert blocked(decision), (command, decision)


def test_terminal_workdir_moves_where_a_relative_write_lands(hooks, guard, tmp_path,
                                                             monkeypatch):
    """terminal carries an optional `workdir`; a relative target resolves against it."""
    monkeypatch.chdir(tmp_path)
    inner = tmp_path / "repo"
    (inner / ".git").mkdir(parents=True)
    decision = call(hooks, "terminal",
                    {"command": "echo x > .git/config", "workdir": str(inner)})

    assert blocked(decision), decision


def test_execute_code_writing_a_git_dir_is_blocked(hooks, guard, repo):
    """A Python snippet in `code` is the same accident as Claude's `python3 -c`."""
    decision = call(hooks, "execute_code", {
        "code": "with open('" + str(repo / ".git" / "config") + "', 'w') as fh:\n"
                "    fh.write('')\n"})

    assert blocked(decision), decision


# ---------------------------------------------------------------------------
# H3 — git's own writers, every read, and ordinary files pass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name,args", [
    ("terminal", {"command": "git config --unset remote.origin.fetch"}),
    ("terminal", {"command": "git remote set-url origin git@example.com:a/b.git"}),
    ("terminal", {"command": "cat .git/config"}),
    ("terminal", {"command": "grep -r fetch .git/config"}),
    ("read_file", {"path": ".git/config"}),
    ("search_files", {"pattern": "fetch", "path": ".git"}),
    ("write_file", {"path": "notes.md", "content": "hi"}),
    ("patch", {"mode": "replace", "path": "notes.md", "old_string": "a", "new_string": "b"}),
    ("execute_code", {"code": "print(open('notes.md').read())"}),
], ids=["git-config", "git-remote", "cat", "grep", "read_file", "search_files",
        "ordinary-write", "ordinary-patch", "ordinary-code"])
def test_allowed_calls_return_none(hooks, guard, repo, tool_name, args):
    """A guard that also refuses the repair route and ordinary work is worse than none."""
    assert call(hooks, tool_name, args) is None


# ---------------------------------------------------------------------------
# H4 — the fail-open contract: missing module, exception, human override
# ---------------------------------------------------------------------------

def test_a_missing_guard_module_allows_and_is_observable(hooks, repo, monkeypatch, caplog):
    """F2 — an older scaffold has no sibling to load: allow, never stall, but log ONCE.
    Silent-when-missing made a registered guard inert with no diagnostic anywhere."""
    import logging

    monkeypatch.delitem(sys.modules, hooks.GIT_INTERNALS_GUARD_MODULE_NAME, raising=False)

    with caplog.at_level(logging.WARNING, logger="ai_badger_hooks"):
        assert call(hooks, "write_file",
                    {"path": str(repo / ".git" / "config"), "content": ""}) is None

    missing_logs = [r for r in caplog.records
                    if "git_internals_guard" in r.getMessage()
                    and "missing" in r.getMessage().lower()]
    assert missing_logs, "a missing guard module went unlogged"

    # once per process, not once per call
    with caplog.at_level(logging.WARNING, logger="ai_badger_hooks"):
        assert call(hooks, "write_file",
                    {"path": str(repo / ".git" / "config"), "content": ""}) is None
    assert len([r for r in caplog.records
                if "git_internals_guard" in r.getMessage()
                and "missing" in r.getMessage().lower()]) == 1


def test_a_raising_guard_allows(hooks, guard, repo, monkeypatch):
    """A PreToolUse hook that dies must not take the tool it gates down with it."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("guard exploded")
    monkeypatch.setattr(guard, "is_protected", boom)
    monkeypatch.setattr(guard, "find_violation", boom)
    monkeypatch.setattr(guard, "code_target", boom)

    assert call(hooks, "write_file",
                {"path": str(repo / ".git" / "config"), "content": ""}) is None
    assert call(hooks, "terminal", {"command": "echo x > .git/config"}) is None


def test_the_human_override_env_allows(hooks, guard, repo, monkeypatch):
    """Exported in the session environment by a human, for a deliberate manual repair."""
    monkeypatch.setenv(guard.OVERRIDE_ENV, "1")

    assert call(hooks, "write_file",
                {"path": str(repo / ".git" / "config"), "content": ""}) is None


def test_a_non_dict_args_payload_allows(hooks, guard, repo):
    """Hermes normalises args to a dict, but a malformed payload must not raise here."""
    assert call(hooks, "write_file", None) is None
    assert call(hooks, "write_file", "not-a-dict") is None


def test_an_oversized_execute_code_payload_fails_open_like_a_shell_command(
    hooks, guard, repo,
):
    """F3b — find_violation caps its input at MAX_COMMAND (B19): the lexer is superlinear and
    Hermes fails CLOSED on a pre_tool_call timeout, so an oversized payload must fail open the
    same way, not be scanned anyway. The write instruction sits past the cap: a guard that
    scans it (the pre-fix behaviour) blocks; one that honours the bound allows."""
    code = ("x" * (guard.MAX_COMMAND + 1)) + " open('.git/config', 'w')"

    assert call(hooks, "execute_code", {"code": code}) is None


def test_an_execute_code_payload_just_under_the_cap_is_still_scanned(hooks, guard, repo):
    """The companion: the bound is a cap, not an amnesty — under it, a write to a git dir is
    still refused, so the cap cannot be grown to swallow real payloads."""
    code = "x" * (guard.MAX_COMMAND - 100) + " open('.git/config', 'w').write('')"

    decision = call(hooks, "execute_code", {"code": code})

    assert blocked(decision), decision


# ---------------------------------------------------------------------------
# The deployed shape — ~/.hermes/plugins/ai-badger/, where the sibling is a FILE
# ---------------------------------------------------------------------------

@pytest.fixture
def plugin_dir(tmp_path, root, monkeypatch):
    """The installed plugin shape: ai_badger_hooks.py with the guard staged beside it.

    Loaded from the copy, not in place, so `_load_sibling_module`'s
    `Path(__file__).parent` lookup resolves against the staged directory the way it does
    in ~/.hermes/plugins/ai-badger/ — the sys.modules injection the other tests use would
    hide a guard that never gets copied there at all.
    """
    import importlib.util
    import shutil

    staged = tmp_path / "plugin"
    staged.mkdir()
    shutil.copy2(root / "features/common/hooks/ai_badger_hooks.py",
                 staged / "ai_badger_hooks.py")

    def load():
        label = f"aib_probe_git_guard_{tmp_path.name}"
        spec = importlib.util.spec_from_file_location(label, staged / "ai_badger_hooks.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[label] = module
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, label, module)
        return module

    monkeypatch.delitem(sys.modules, "git_internals_guard", raising=False)
    try:
        yield staged, load
    finally:
        sys.modules.pop("git_internals_guard", None)
        sys.modules.pop(f"aib_probe_git_guard_{tmp_path.name}", None)


def test_the_arm_finds_the_guard_staged_beside_it(plugin_dir, root, repo):
    """adjust_hooks must copy git_internals_guard.py into the plugin dir; this is why."""
    import shutil

    staged, load = plugin_dir
    shutil.copy2(root / GUARD, staged / "git_internals_guard.py")
    module = load()

    decision = module.pre_tool_call_git_internals_guard(
        tool_name="write_file", args={"path": str(repo / ".git" / "config"), "content": ""})

    assert blocked(decision), decision


def test_the_arm_allows_when_the_guard_was_never_staged(plugin_dir, repo):
    """An older scaffold's plugin dir has no guard file: allow, never stall."""
    _, load = plugin_dir
    module = load()

    assert module.pre_tool_call_git_internals_guard(
        tool_name="write_file",
        args={"path": str(repo / ".git" / "config"), "content": ""}) is None


def test_the_installer_copies_the_guard_into_the_plugin_dir(load_script, root, tmp_path):
    """F9b — the arm is dead unless the sibling actually ships: run the installer against a
    tmp_path plugin dir and assert the file lands, not just that the mapping names it."""
    import shutil

    adjust_hooks = load_script("features/hermes/adjustments/adjust_hooks.py")
    assert ("git-work", "git_internals_guard.py") in adjust_hooks.SHARED_SKILL_MODULES

    staged = tmp_path / "plugin"
    staged.mkdir()
    shutil.copy2(root / "features/common/hooks/ai_badger_hooks.py",
                 staged / "ai_badger_hooks.py")
    project = tmp_path / "proj"
    (project / ".ai-badger").mkdir(parents=True)
    context = {
        "framework_root": root,
        "config": {"agents": ["hermes"]},
        "feature_dir": root / "features" / "hermes" / "adjustments",
        "target_dir": project / ".ai-badger",
        "target": project,
        "skills": [],
        "index": {},
        "install": False,  # keep the test hermetic: no writes to the real ~/.hermes
    }
    adjust_hooks.adjust(context)

    assert (project / ".ai-badger" / "hooks" / "git_internals_guard.py").is_file(), (
        "the installer did not copy the guard beside the hook it arms")


# ---------------------------------------------------------------------------
# Registration — a hook nothing registers is the defect this repo keeps re-shipping
# ---------------------------------------------------------------------------

def test_register_wires_the_arm_onto_pre_tool_call(hooks, guard):
    """Registered with an agent behind it: the callback Hermes will call is this one."""
    class Ctx:
        def __init__(self):
            self.hooks = []

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

    ctx = Ctx()
    hooks.register(ctx)

    pre_tool = [cb for name, cb in ctx.hooks if name == "pre_tool_call"]
    assert hooks.pre_tool_call_git_internals_guard in pre_tool
    assert hooks.pre_tool_call_memory_gate in pre_tool


def test_the_manifest_names_this_method_for_hermes(load_script):
    """Derive-or-delete: the manifest's `method` must be a real callable on the module."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "features/common/hooks/hooks-manifest.json").read_text(encoding="utf-8"))
    entry = next(h for h in manifest["hooks"] if h["name"] == "git-internals-guard")
    arm = entry["agents"]["hermes"]
    module = load_script("features/common/hooks/ai_badger_hooks.py")

    assert arm == {"type": "plugin", "entry": "ai_badger_hooks.py",
                   "method": "pre_tool_call_git_internals_guard"}
    assert callable(getattr(module, arm["method"]))
