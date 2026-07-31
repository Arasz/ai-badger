"""Usage accounting must see subagent work, which does not live in the main transcript.

`parse_transcript_usage` folded subagents in by branching on `isSidechain`. Measured against
171 real transcripts, **no record carries `isSidechain: true`** — subagent work is written to
`<transcript-dir>/<session-id>/subagents/agent-<id>.jsonl`, with a paired `.meta.json` naming
the dispatch. So the split shipped in 0.56.0 reported 2.3% cheap-model output where the truth
across main plus subagents was 14.7%, and `modelMix` could not see delegation at all.

The `.meta.json` also carries `model` and `agentType` per dispatch, which is the attribution
the skill documented as unavailable.
"""
from __future__ import annotations

import json


SCRIPT = "features/common/skills/task/scripts/tracker_lib.py"


def _assistant(model, out, inp=0, cr=0, cc=0):
    return json.dumps({"type": "assistant", "message": {
        "model": model,
        "usage": {"input_tokens": inp, "output_tokens": out,
                  "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc}}})


def _session(tmp_path, session_id, main_records, subagents=()):
    """Lay out a transcript the way Claude Code does: a file plus a sibling directory."""
    transcript = tmp_path / f"{session_id}.jsonl"
    transcript.write_text("\n".join(main_records) + "\n", encoding="utf-8")
    if subagents:
        sub_dir = tmp_path / session_id / "subagents"
        sub_dir.mkdir(parents=True)
        for name, records, meta in subagents:
            (sub_dir / f"{name}.jsonl").write_text("\n".join(records) + "\n", encoding="utf-8")
            if meta is not None:
                (sub_dir / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return transcript


class TestSubagentOutputIsCounted:
    def test_a_subagent_transcript_contributes_to_the_model_split(self, load_script, tmp_path):
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 100)],
            [("agent-a1", [_assistant("claude-sonnet-5", 900)], {"model": "sonnet"})])

        usage = tl.parse_transcript_usage(str(transcript))

        assert usage["byModel"]["claude-sonnet-5"]["outputTokens"] == 900
        assert usage["cumulative"]["outputTokens"] == 1000

    def test_the_mix_reflects_delegation_rather_than_the_main_thread_alone(self, load_script,
                                                                          tmp_path):
        """The defect in one assertion: 90% of this task's output was delegated."""
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 100)],
            [("agent-a1", [_assistant("claude-sonnet-5", 900)], {"model": "sonnet"})])
        start = {"cumulative": {"outputTokens": 0}, "contextTokens": 0, "byModel": {}}

        usage = tl.compute_usage(start, tl.make_checkpoint(str(transcript)), [])

        assert usage["modelMix"]["claude-sonnet-5"] == 0.9

    def test_several_subagents_all_count(self, load_script, tmp_path):
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 10)],
            [("agent-a1", [_assistant("claude-haiku-4-5", 5)], {"model": "haiku"}),
             ("agent-a2", [_assistant("claude-sonnet-5", 20)], {"model": "sonnet"})])

        usage = tl.parse_transcript_usage(str(transcript))

        assert usage["cumulative"]["outputTokens"] == 35
        assert usage["assistantMessages"] == 3

    def test_a_session_with_no_subagent_directory_is_unaffected(self, load_script, tmp_path):
        tl = load_script(SCRIPT)
        transcript = _session(tmp_path, "sess", [_assistant("claude-opus-5", 42)])

        usage = tl.parse_transcript_usage(str(transcript))

        assert usage["cumulative"]["outputTokens"] == 42
        assert usage["dispatches"]["count"] == 0

    def test_context_tokens_still_come_from_the_main_thread_only(self, load_script, tmp_path):
        """Context occupancy is a property of the main conversation, not of its subagents."""
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 1, inp=10, cr=20, cc=30)],
            [("agent-a1", [_assistant("claude-sonnet-5", 1, inp=999, cr=999, cc=999)], None)])

        usage = tl.parse_transcript_usage(str(transcript))

        assert usage["contextTokens"] == 60


class TestDispatchesAreAttributed:
    """`.meta.json` carries per-dispatch model and agent type — the skill said it did not."""

    def test_dispatches_are_counted_and_split_by_agent_type(self, load_script, tmp_path):
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 1)],
            [("agent-a1", [_assistant("claude-sonnet-5", 1)],
              {"model": "sonnet", "agentType": "test-engineer"}),
             ("agent-a2", [_assistant("claude-opus-5", 1)],
              {"model": "opus", "agentType": "general-purpose"})])

        dispatches = tl.parse_transcript_usage(str(transcript))["dispatches"]

        assert dispatches["count"] == 2
        assert dispatches["byAgentType"] == {"test-engineer": 1, "general-purpose": 1}

    def test_a_dispatch_that_declared_no_model_is_counted_separately(self, load_script,
                                                                     tmp_path):
        """49% of real dispatches named no model and silently inherited the session's."""
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 1)],
            [("agent-a1", [_assistant("claude-opus-5", 1)], {"agentType": "general-purpose"}),
             ("agent-a2", [_assistant("claude-sonnet-5", 1)],
              {"model": "sonnet", "agentType": "test-engineer"})])

        dispatches = tl.parse_transcript_usage(str(transcript))["dispatches"]

        assert dispatches["undeclaredModel"] == 1
        assert dispatches["count"] == 2

    def test_an_unreadable_meta_file_degrades_to_unknown_rather_than_to_zero(self, load_script,
                                                                            tmp_path):
        """meta.json is an undocumented CLI artefact; a format change must not read as none."""
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 1)],
            [("agent-a1", [_assistant("claude-sonnet-5", 5)], None)])

        usage = tl.parse_transcript_usage(str(transcript))

        assert usage["cumulative"]["outputTokens"] == 6, "tokens count even with no meta"
        assert usage["dispatches"]["count"] == 1
        assert usage["dispatches"]["byAgentType"] == {"unknown": 1}


class TestSelfReportedSubagentTokensAreNotDoubleCounted:
    def test_grand_total_does_not_add_reported_tokens_the_transcript_already_saw(
            self, load_script, tmp_path):
        """`task_tracker.py subagent` reports totals by hand; those are now in the transcript."""
        tl = load_script(SCRIPT)
        transcript = _session(
            tmp_path, "sess", [_assistant("claude-opus-5", 100)],
            [("agent-a1", [_assistant("claude-sonnet-5", 900)], {"model": "sonnet"})])
        start = {"cumulative": {"outputTokens": 0, "inputTokens": 0, "cacheReadTokens": 0,
                                "cacheCreationTokens": 0}, "contextTokens": 0, "byModel": {}}

        usage = tl.compute_usage(start, tl.make_checkpoint(str(transcript)),
                                 [{"totalTokens": 900}])

        assert usage["grandTotal"] == usage["mainSessionTotal"], (
            "the transcript already counted the subagent; adding the report doubles it")
        assert usage["subagentTokens"] == 900, "still reported, for comparison"
