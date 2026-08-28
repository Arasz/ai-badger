"""The isolation half of the PreToolUse dispatch gate: deny an unisolated write lane
only when another lane is live.

Owner ruling 2026-08-28: gate on parallelism, not on every write. A lone sequential
subagent editing the current tree passes untouched — the contract's harm (shared build
output, one agent compiling against another's half-applied edit) only exists under
concurrency, and concurrency means this session's own fan-out. A machine-wide live-session
count was tried and cut: /tmp/cc-socks carries no cwd and read 6 on an idle machine, so the
gate would have denied every unisolated write dispatch forever.

Each test names the failure mode it targets:

- `test_a_lone_write_dispatch_is_allowed` — the quiet path. If this breaks, the gate fires
  on ordinary single-agent work, which is what gets a gate switched off for good.
- `test_a_write_dispatch_beside_a_sibling_is_denied` — the whole point.
- `test_isolation_worktree_is_allowed_beside_a_sibling` — the offered fix must actually work,
  or the deny message is a dead end.
- `test_a_read_only_lane_is_allowed_beside_a_sibling` — architect/code-reviewer never write,
  so isolating them is pure overhead.
- `test_the_read_only_exemption_is_derived_not_listed` — a hardcoded persona list here is the
  derive-or-delete-the-list trap; this pins the behaviour to frontmatter, not to names.
- `test_a_missing_model_still_denies_for_model` — the isolation check is additive; it must not
  swallow the older gate.
- `test_a_broken_ledger_does_not_block` — fails open.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import io
import json

import pytest
from conftest import _test_write

HOOK_PATH = "features/common/skills/task/scripts/dispatch_gate_hook.py"

WRITE_LANE = "---\nname: {name}\ndescription: a persona\nmodel: sonnet\n---\n\nBody.\n"
READ_LANE = ("---\nname: {name}\ndescription: a persona\nmodel: opus\n"
             "disallowedTools: Write, Edit, MultiEdit, NotebookEdit\n---\n\nBody.\n")
PARTIAL_LANE = ("---\nname: {name}\ndescription: a persona\nmodel: opus\n"
                "disallowedTools: WebFetch\n---\n\nBody.\n")


@pytest.fixture
def hook(load_script, monkeypatch, tmp_path):
    """The hook with the project dir cleared and the ledger redirected into tmp_path."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    module = load_script(HOOK_PATH)
    module.dispatch_ledger.LEDGER_DIR = tmp_path / "dispatch-lanes"
    return module


def _run(hook, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        hook.main()
    return buf.getvalue()


def _dispatch(cwd, subagent_type="test-engineer", tool_use_id="toolu_1", **tool_input):
    payload = {
        "session_id": "sess_1",
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_use_id": tool_use_id,
        "cwd": str(cwd),
        "tool_input": {"prompt": "implement it", "description": "work",
                       "subagent_type": subagent_type, "model": "sonnet"},
    }
    payload["tool_input"].update(tool_input)
    return payload


def _lane(project, name, template=WRITE_LANE):
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    _test_write(agents / f"{name}.md", template.format(name=name))
    return project


def test_a_lone_write_dispatch_is_allowed(hook, monkeypatch, tmp_path):
    _lane(tmp_path, "test-engineer")

    assert _run(hook, monkeypatch, _dispatch(tmp_path)) == ""


def test_a_write_dispatch_beside_a_sibling_is_denied(hook, monkeypatch, tmp_path):
    _lane(tmp_path, "test-engineer")
    _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"))

    out = _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_2"))

    assert "deny" in out and "isolation" in out, out


def test_isolation_worktree_is_allowed_beside_a_sibling(hook, monkeypatch, tmp_path):
    _lane(tmp_path, "test-engineer")
    _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"))

    out = _run(hook, monkeypatch,
               _dispatch(tmp_path, tool_use_id="toolu_2", isolation="worktree"))

    assert out == "", out


def test_a_read_only_lane_is_allowed_beside_a_sibling(hook, monkeypatch, tmp_path):
    _lane(tmp_path, "code-reviewer", template=READ_LANE)
    _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"))

    out = _run(hook, monkeypatch,
               _dispatch(tmp_path, subagent_type="code-reviewer", tool_use_id="toolu_2"))

    assert out == "", out


def test_the_read_only_exemption_is_derived_not_listed(hook, monkeypatch, tmp_path):
    """Same persona name, two frontmatters: only the one that disallows writing is exempt.

    A gate keyed on the name 'code-reviewer' would pass both and this test would not move.
    """
    _lane(tmp_path, "ambiguous", template=READ_LANE)
    _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"))
    exempt = _run(hook, monkeypatch,
                  _dispatch(tmp_path, subagent_type="ambiguous", tool_use_id="toolu_2"))

    _lane(tmp_path, "ambiguous", template=WRITE_LANE)
    gated = _run(hook, monkeypatch,
                 _dispatch(tmp_path, subagent_type="ambiguous", tool_use_id="toolu_3"))

    assert exempt == "", f"read-only frontmatter should be exempt, got {exempt!r}"
    assert "deny" in gated, f"write-capable frontmatter should be gated, got {gated!r}"


def test_a_missing_model_still_denies_for_model(hook, monkeypatch, tmp_path):
    """The isolation check is additive — it must not swallow the model gate."""
    _test_write(tmp_path / "noop.txt", "")

    out = _run(hook, monkeypatch,
               _dispatch(tmp_path, subagent_type="unknown-persona", model=""))

    assert "deny" in out and "model" in out, out


def test_a_broken_ledger_does_not_block(hook, monkeypatch, tmp_path):
    """An unreadable ledger reports no siblings, so the dispatch proceeds."""
    _lane(tmp_path, "test-engineer")
    hook.dispatch_ledger.LEDGER_DIR = tmp_path / "missing" / "deeper"

    assert _run(hook, monkeypatch, _dispatch(tmp_path)) == ""


def test_a_lane_disallowing_only_non_write_tools_is_still_gated(hook, monkeypatch, tmp_path):
    """A `disallowedTools` list that bans nothing write-related does not make a lane safe.

    Found by mutation: returning True for any non-empty list passed every other test, which
    would have exempted every lane that merely restricts, say, WebFetch.
    """
    _lane(tmp_path, "restricted", template=PARTIAL_LANE)
    _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"))

    out = _run(hook, monkeypatch,
               _dispatch(tmp_path, subagent_type="restricted", tool_use_id="toolu_2"))

    assert "deny" in out, out


def test_a_lane_keeping_write_is_gated_even_when_it_bans_editing(hook, monkeypatch, tmp_path):
    """`architect`'s real shape: Edit/MultiEdit/NotebookEdit banned, Write kept.

    It can still add a file to a shared tree, so it is a writer for isolation purposes.
    """
    _lane(tmp_path, "planner", template=(
        "---\nname: planner\ndescription: a persona\nmodel: opus\n"
        "disallowedTools: Edit, MultiEdit, NotebookEdit\n---\n\nBody.\n"))
    _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"))

    out = _run(hook, monkeypatch,
               _dispatch(tmp_path, subagent_type="planner", tool_use_id="toolu_2"))

    assert "deny" in out, out


def test_isolated_siblings_do_not_make_a_plain_dispatch_parallel(hook, monkeypatch, tmp_path):
    """Lanes that took their own worktree are not in the shared tree, so they are not siblings.

    Found in review: recording every dispatch regardless would count four isolated lanes as
    four occupants of a tree none of them is in, and deny the one dispatch actually alone.
    """
    _lane(tmp_path, "test-engineer")
    for n in (1, 2, 3):
        _run(hook, monkeypatch,
             _dispatch(tmp_path, tool_use_id=f"toolu_{n}", isolation="worktree"))

    out = _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_4"))

    assert out == "", f"a lone lane beside three isolated ones must pass, got {out!r}"


def test_read_only_siblings_still_count_as_occupants(hook, monkeypatch, tmp_path):
    """A read-only lane is exempt from needing isolation, but it is still in the shared tree.

    Found in review: exempting before recording meant a writer arriving beside two reviewers
    saw an empty ledger. It cannot disturb *them* by being read-only — but they can be
    disturbed by it, which is the direction that matters.
    """
    _lane(tmp_path, "code-reviewer", template=READ_LANE)
    _lane(tmp_path, "test-engineer")
    for n in (1, 2):
        _run(hook, monkeypatch,
             _dispatch(tmp_path, subagent_type="code-reviewer", tool_use_id=f"toolu_{n}"))

    out = _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_3"))

    assert "deny" in out, f"a writer joining two reviewers in one tree must be denied, got {out!r}"
