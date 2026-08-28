"""The Hermes plugin warns when delegated subagents will share one working copy.

Hermes has real subagent worktree isolation — `delegation.worktree_isolation` in
`~/.hermes/config.yaml` (tools/delegate_tool.py:887, Hermes 0.20.6) — but it defaults to
**false**, and `delegate_task` exposes no per-dispatch alternative: its per-task fields are
exactly `goal`, `context` and `output_schema`. So under Hermes there is nothing a
`pre_tool_call` gate could check, and the only lever is that one config key. With it unset,
`delegate_tool.py:2727` seeds every child's cwd from the parent's and parallel children
contend for one checkout.

Measured on this machine 2026-08-28: the key was absent from a `delegation:` block that set
only `max_iterations`, so the default applied.

The notice is read-only by design. ai-badger does not own `~/.hermes/config.yaml`, and a
"read-only" gate that wrote to `$HOME` bricked the Hermes plugin once already (0.89.0).

Parsed without pyyaml: `ai_badger_hooks` deliberately keeps `import yaml` off the hook path,
so this is a targeted scan of the `delegation:` block. Each test names its failure mode —
several exist because a naive scan gets exactly these wrong.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import pytest
from conftest import _test_write

HOOKS = "features/common/hooks/ai_badger_hooks.py"
ISOLATION = "features/common/hooks/hermes_isolation.py"


@pytest.fixture
def hooks(load_script, tmp_path, monkeypatch):
    """The isolation module with HERMES_HOME redirected — never the real ~/.hermes."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    return load_script(ISOLATION)


@pytest.fixture
def plugin(load_script, tmp_path, monkeypatch):
    """The plugin itself, for the two tests about the notice reaching a session start."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    return load_script(HOOKS)


def _config(tmp_path, text):
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    _test_write(home / "config.yaml", text)
    return home


def test_an_unset_key_is_reported(hooks, tmp_path):
    """The measured real case: a delegation block that never mentions the key."""
    _config(tmp_path, "delegation:\n  max_iterations: 250\nskills:\n  external_dirs: []\n")

    assert hooks.subagents_share_one_tree() is True


def test_an_explicit_false_is_reported(hooks, tmp_path):
    _config(tmp_path, "delegation:\n  worktree_isolation: false\n")

    assert hooks.subagents_share_one_tree() is True


def test_an_explicit_true_is_silent(hooks, tmp_path):
    _config(tmp_path, "delegation:\n  max_iterations: 250\n  worktree_isolation: true\n")

    assert hooks.subagents_share_one_tree() is False


def test_a_missing_delegation_block_is_reported(hooks, tmp_path):
    """No block at all still means the default applies."""
    _config(tmp_path, "skills:\n  external_dirs: []\n")

    assert hooks.subagents_share_one_tree() is True


def test_a_commented_out_key_does_not_count_as_set(hooks, tmp_path):
    """Hermes' own docs ship the key commented out; a comment configures nothing."""
    _config(tmp_path, "delegation:\n  # worktree_isolation: true\n  max_iterations: 250\n")

    assert hooks.subagents_share_one_tree() is True


def test_the_key_under_another_block_does_not_count(hooks, tmp_path):
    """The discriminator a naive grep fails.

    Only `delegation.worktree_isolation` is read by Hermes. The same key under any other
    top-level mapping configures nothing, and treating it as set would silence the notice
    for someone who is in fact unprotected.
    """
    _config(tmp_path, "somethingelse:\n  worktree_isolation: true\ndelegation:\n"
                      "  max_iterations: 250\n")

    assert hooks.subagents_share_one_tree() is True


def test_a_later_top_level_key_ends_the_block(hooks, tmp_path):
    """The scan must stop at the next top-level key, not run to end of file."""
    _config(tmp_path, "delegation:\n  max_iterations: 250\nskills:\n"
                      "  worktree_isolation: true\n")

    assert hooks.subagents_share_one_tree() is True


def test_an_inline_comment_does_not_hide_an_enabled_key(hooks, tmp_path):
    """Found by mutation: the value parse took the comment as part of the value.

    `worktree_isolation: true  # keep them apart` read as the string "true  # keep them
    apart", which is not "true", so a correctly-configured user was warned anyway — the
    worst kind of false alarm, the one that teaches you to ignore the notice.
    """
    _config(tmp_path, "delegation:\n  worktree_isolation: true  # keep them apart\n")

    assert hooks.subagents_share_one_tree() is False


def test_an_inline_comment_does_not_hide_a_disabled_key(hooks, tmp_path):
    """The other direction: commenting after `false` must still read as false."""
    _config(tmp_path, "delegation:\n  worktree_isolation: false  # default\n")

    assert hooks.subagents_share_one_tree() is True


def test_a_missing_config_is_silent(hooks):
    """No Hermes config means Hermes is not in use here; nagging would be noise."""
    assert hooks.subagents_share_one_tree() is False


def test_an_unreadable_config_is_silent(hooks, tmp_path):
    """Fails open: a notice that cannot read its input must not guess."""
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").mkdir()

    assert hooks.subagents_share_one_tree() is False


def test_the_notice_names_the_key_and_the_file(plugin, tmp_path, caplog):
    """A warning that does not say what to change is a nag."""
    _config(tmp_path, "delegation:\n  max_iterations: 250\n")

    with caplog.at_level("INFO"):
        plugin.on_session_start_drift_notice(cwd=str(tmp_path))

    logged = caplog.text
    assert "worktree_isolation" in logged, logged
    assert "delegation" in logged, logged


def test_the_notice_never_writes_to_the_config(hooks, plugin, tmp_path):
    """ai-badger does not own ~/.hermes/config.yaml (see 0.89.0)."""
    home = _config(tmp_path, "delegation:\n  max_iterations: 250\n")
    before = (home / "config.yaml").read_bytes()

    hooks.subagents_share_one_tree()
    plugin.on_session_start_drift_notice(cwd=str(tmp_path))

    assert (home / "config.yaml").read_bytes() == before
