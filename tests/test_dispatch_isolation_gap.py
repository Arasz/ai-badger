"""Replication tests for the two dispatch-enforcement gaps diagnosed 2026-08-28.

Symptom the user reported: running under the Hermes harness with the `task` skill,
subagents "seem to not follow instructions", and **no worktree isolation happens unless
the prompt says so**.

Two independent causes, one test class each:

1. `TestWorktreeIsolationIsEnforced` — FIXED. Every other invariant the framework cares
   about on a tool call had a hook that could veto it (model lanes, memory-first, generated
   files, blast-radius kills); per-agent worktree isolation had none, and survived only as
   prose competing with the rest of the context window. `dispatch_gate_hook` now carries an
   isolation half. Scope note: the owner ruled it fires under parallelism only, so the
   assertion below is a *parallel* dispatch, not a lone one — a lone sequential lane shares
   the tree with nobody. `tests/test_dispatch_gate_isolation.py` owns the full behaviour.

2. `TestHermesHasNoDispatchEnforcement` — STILL OPEN, tracked as Task B. Under Hermes not
   even the model gate runs. The `dispatch-gate` exemption in tooling/validate.py justifies
   that with a premise (`customAgents supported=false`) that is equally true of Claude, where
   the same gate is wired and demonstrably resolves lane files. A reason that does not
   distinguish the two agents cannot be the reason one of them is exempt.

   These two stay `xfail` rather than being deleted: the gap is real and measured, and the
   fix waits only on observing a live `delegate_task` payload — which decides whether the
   answer is a Hermes gate or an honestly-rewritten exemption. Deleting them would lose the
   finding; asserting the opposite would be a lie.
"""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import io
import json

import pytest
from conftest import _test_write

HOOK_PATH = "features/common/skills/task/scripts/dispatch_gate_hook.py"
HOOKS_JSON = "features/common/hooks/hooks.json"
SUPPORT_JSON = "features/common/support.json"
HERMES_PLUGIN = "features/common/hooks/ai_badger_hooks.py"


@pytest.fixture
def hook(load_script, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return load_script(HOOK_PATH)


def _run(hook, monkeypatch, payload, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    hook.main()
    return capsys.readouterr().out


def _dispatch(cwd, tool_use_id="toolu_1", **tool_input):
    payload = {
        "session_id": "sess_1",
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_use_id": tool_use_id,
        "cwd": str(cwd),
        "tool_input": {"prompt": "implement the thing", "description": "a thing",
                       "subagent_type": "test-engineer", "model": "sonnet"},
    }
    payload["tool_input"].update(tool_input)
    return payload


class TestWorktreeIsolationIsEnforced:
    """The user's second symptom: nothing stopped an unisolated dispatch."""

    def test_a_parallel_dispatch_that_names_no_isolation_is_denied(self, hook, monkeypatch,
                                                                   tmp_path, capsys):
        """Two write lanes dispatched together must not share one tree.

        Before the fix `decide()` returned as soon as it saw a `model` and never looked at
        `isolation` — the whole of the user's "no worktree isolation is used if I didn't
        mention it". The first dispatch establishes the fan-out; the second is the one the
        gate must refuse. The lane file is what proves the persona writes — the gate needs
        positive proof, and a type with no lane file is left alone.
        """
        hook.dispatch_ledger.LEDGER_DIR = tmp_path / "dispatch-lanes"
        agents = tmp_path / ".claude" / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        _test_write(agents / "test-engineer.md",
                    "---\nname: test-engineer\ndescription: d\nmodel: sonnet\n---\n\nB.\n")
        _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_1"), capsys)

        out = _run(hook, monkeypatch, _dispatch(tmp_path, tool_use_id="toolu_2"), capsys)

        assert "deny" in out, (
            "dispatch_gate_hook allowed a parallel Agent dispatch carrying no isolation: "
            f"hook output was {out!r}")

    def test_some_agent_matching_hook_inspects_isolation(self, root):
        """Derive the claim from the shipped manifest rather than trusting the prose.

        Collects every PreToolUse hook whose matcher covers `Agent` and greps the script
        it runs. If no shipped gate so much as mentions isolation, the SKILL.md contract
        has no mechanical backing at all.
        """
        manifest = json.loads((root / HOOKS_JSON).read_text(encoding="utf-8"))
        entries = manifest["hooks"]["PreToolUse"]
        agent_scripts = [
            inner["command"].split("/")[-1].rstrip('"')
            for entry in entries if "Agent" in (entry.get("matcher") or "")
            for inner in entry["hooks"]
        ]
        assert agent_scripts, "no PreToolUse hook matches Agent at all"

        inspects = []
        for name in agent_scripts:
            for path in root.glob(f"features/common/skills/*/scripts/{name}"):
                body = path.read_text(encoding="utf-8")
                if "worktree" in body or "isolation" in body:
                    inspects.append(name)

        assert inspects, (
            "no hook gating Agent dispatches reads worktree/isolation; the scripts that run "
            f"are {agent_scripts}. Per-agent worktree isolation is prose in task/SKILL.md "
            "with no gate behind it.")


class TestHermesHasNoDispatchEnforcement:
    """The user's first symptom: under Hermes, dispatch instructions are unenforced."""

    def test_the_hermes_exemption_reason_distinguishes_hermes_from_claude(self, root,
                                                                         load_script):
        """`customAgents supported=false` cannot be why Hermes is exempt: Claude is too.

        tooling/validate.py exempts `dispatch-gate` for hermes because "Hermes has no
        custom-agent files (support.json customAgents supported=false)". support.json
        records exactly the same flag for claude — and the gate ships for claude anyway,
        resolving `.claude/agents/<type>.md` lanes that the framework itself scaffolds.
        A premise both agents satisfy explains neither.
        """
        support = json.loads((root / SUPPORT_JSON).read_text(encoding="utf-8"))
        claude_flag = support["agents"]["claude"]["capabilities"]["customAgents"]["supported"]
        hermes_flag = support["agents"]["hermes"]["capabilities"]["customAgents"]["supported"]

        validate = load_script("tooling/validate.py")
        reason = validate.HOOKS_MANIFEST_AGENT_EXEMPTIONS["dispatch-gate"]["hermes"]

        assert not (claude_flag == hermes_flag and "customAgents" in reason), (
            "the dispatch-gate hermes exemption rests on customAgents="
            f"{hermes_flag}, but claude records customAgents={claude_flag} and is gated "
            f"regardless. Reason text: {reason!r}")

    def test_the_hermes_plugin_surfaces_the_isolation_setting(self, root):
        """Hermes cannot be gated per dispatch, so the plugin warns about the config instead.

        This test used to demand a `pre_tool_call` dispatch gate. Hermes 0.20.6's
        DELEGATE_TASK_SCHEMA settles that there is nothing to gate: the per-task properties
        are exactly goal, context and output_schema. Isolation is real but session-wide —
        `delegation.worktree_isolation`, default false — so the only honest lever is telling
        the user it is off.
        """
        source = (root / HERMES_PLUGIN).read_text(encoding="utf-8")

        assert "worktree_isolation" in source, (
            "the hermes plugin says nothing about delegation.worktree_isolation, so a user "
            "whose subagents all share one checkout is never told")
        assert "def subagents_share_one_tree" in source
