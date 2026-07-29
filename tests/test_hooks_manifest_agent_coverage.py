"""Every hooks-manifest.json entry must name every agent capable of its event family, or
record an explicit, non-trivial reason it does not (issue #147).

Three hooks shipped, tested and scaffolded, then never registered for the agent that would
have run them: mcp_index_hook.py (registered nowhere), stop_hook.py (#141), and
context-enrichment itself (Hermes-only until this issue). All three were found by accident.
This is the test the issue asked for: a hook entry missing one of HOOK_CAPABLE_AGENTS is a
failure unless tooling/validate.py's HOOKS_MANIFEST_AGENT_EXEMPTIONS says why, and #145's review
of the schema-coverage precedent (test_mcp_tools_exemption_reason_is_honest_not_that_the_format_
is_yaml) means a reason key existing is not enough — its text is checked too.
"""
from __future__ import annotations

import json


def test_the_real_manifest_has_no_unexplained_gaps(root, load_script):
    validate = load_script("tooling/validate.py")

    gaps = validate.hooks_manifest_agent_gaps(root)

    assert gaps == []


def test_an_agent_missing_from_a_hook_with_no_exemption_is_a_gap(tmp_path, load_script,
                                                                   monkeypatch):
    """The forcing function itself: an entry naming only one agent, with nothing recorded
    for the others, must be reported — not silently accepted because a key merely exists
    for a different hook."""
    validate = load_script("tooling/validate.py")
    monkeypatch.setattr(validate, "HOOKS_MANIFEST_AGENT_EXEMPTIONS", {})

    manifest_dir = tmp_path / "features" / "common" / "hooks"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "hooks-manifest.json").write_text(json.dumps({
        "hooks": [
            {"name": "solo-hook", "agents": {
                "claude": {"type": "hooks-json", "entry": "hooks.json",
                           "event": "UserPromptSubmit", "script": "solo_hook.py"},
            }},
        ]
    }), encoding="utf-8")

    gaps = validate.hooks_manifest_agent_gaps(tmp_path)

    assert any("solo-hook" in g and "'hermes'" in g for g in gaps), gaps
    assert any("solo-hook" in g and "'copilot'" in g for g in gaps), gaps
    assert not any("'claude'" in g and "solo-hook" in g for g in gaps), gaps


def test_a_recorded_exemption_closes_the_gap(tmp_path, load_script, monkeypatch):
    validate = load_script("tooling/validate.py")
    monkeypatch.setattr(validate, "HOOKS_MANIFEST_AGENT_EXEMPTIONS", {
        "solo-hook": {"hermes": "a real reason", "copilot": "another real reason"},
    })

    manifest_dir = tmp_path / "features" / "common" / "hooks"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "hooks-manifest.json").write_text(json.dumps({
        "hooks": [
            {"name": "solo-hook", "agents": {
                "claude": {"type": "hooks-json", "entry": "hooks.json",
                           "event": "UserPromptSubmit", "script": "solo_hook.py"},
            }},
        ]
    }), encoding="utf-8")

    gaps = validate.hooks_manifest_agent_gaps(tmp_path)

    assert gaps == []


def test_all_flag_fails_when_a_hook_has_an_unexplained_gap(tmp_path, root, load_script, capsys):
    """The check is wired into --all, not just callable in isolation."""
    import shutil
    validate = load_script("tooling/validate.py")
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    manifest_dir = tmp_path / "features" / "common" / "hooks"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "hooks-manifest.json").write_text(json.dumps({
        "hooks": [
            {"name": "solo-hook", "agents": {
                "claude": {"type": "hooks-json", "entry": "hooks.json",
                           "event": "UserPromptSubmit", "script": "solo_hook.py"},
            }},
        ]
    }), encoding="utf-8")

    rc = validate.main(["--all", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "hooks-manifest agent coverage" in out
    assert "solo-hook" in out


class TestExemptionReasonsAreMeaningful:
    """A reason key existing is not a reason — its text must say something (#145 finding)."""

    def test_every_exemption_reason_is_a_real_sentence_not_a_placeholder(self, load_script):
        validate = load_script("tooling/validate.py")
        for hook_name, per_agent in validate.HOOKS_MANIFEST_AGENT_EXEMPTIONS.items():
            for agent, reason in per_agent.items():
                assert isinstance(reason, str) and len(reason) >= 20, (
                    f"{hook_name}/{agent}: exemption reason is too short to be a reason: "
                    f"{reason!r}"
                )
                assert reason.strip().lower() not in ("todo", "n/a", "unknown", "tbd"), (
                    f"{hook_name}/{agent}: placeholder reason: {reason!r}"
                )

    def test_junie_exemption_reason_says_it_is_permanent_and_platform_level(self, load_script):
        validate = load_script("tooling/validate.py")
        reason = validate.JUNIE_HOOK_EXEMPTION
        assert isinstance(reason, str) and len(reason) >= 20
        assert "junie" in reason.lower()
        assert "junie" not in validate.HOOK_CAPABLE_AGENTS

    def test_session_start_tracking_exemption_is_framed_as_claude_only_design(self, load_script):
        validate = load_script("tooling/validate.py")
        per_agent = validate.HOOKS_MANIFEST_AGENT_EXEMPTIONS["session-start-tracking"]
        for reason in per_agent.values():
            assert "claude" in reason.lower()

    def test_task_checkpoint_exemptions_name_the_claude_only_machinery_they_depend_on(
        self, load_script
    ):
        """Both checkpoint entries read and write the /task skill's tracked-task ledger, which
        only session-start-tracking (itself Claude-only) ever populates. The reason has to say
        so, not merely assert Claude-onlyness."""
        validate = load_script("tooling/validate.py")
        for hook in ("task-checkpoint", "task-checkpoint-session-end"):
            per_agent = validate.HOOKS_MANIFEST_AGENT_EXEMPTIONS[hook]
            assert set(per_agent) == {"hermes", "copilot"}, hook
            for agent, reason in per_agent.items():
                assert "session-start-tracking" in reason or "transcript" in reason, (
                    f"{hook}/{agent}: {reason!r}"
                )

    def test_prompt_markers_exemption_is_framed_as_an_acknowledged_gap_not_a_design_limit(
        self, load_script
    ):
        """Distinguishes it from session-start-tracking's permanent, by-design exemption:
        this one records a known TODO, honestly, rather than dressing it up as impossible."""
        validate = load_script("tooling/validate.py")
        reason = validate.HOOKS_MANIFEST_AGENT_EXEMPTIONS["prompt-markers"]["hermes"]
        assert "gap" in reason.lower() or "not yet" in reason.lower() or "not been done" in reason.lower()
