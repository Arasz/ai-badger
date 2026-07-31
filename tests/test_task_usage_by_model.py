"""A task records which model did its work, not just how many tokens it took.

`cacheEfficiency` was the discriminating metric this tracker reported, and measurement across
1250 real sessions put it at 0.975-0.986 everywhere — it cannot tell a cheap task from an
expensive one. The model mix can: over the same sessions, opus and sonnet produced comparable
output volume at 3.1x the cost. So the delegation policy the /task skill already prescribes
becomes checkable rather than aspirational.

No prices live here. Prices change and inventing them would be a fabricated number; output
tokens per model is the durable signal, and a reader applies whatever the rates are today.
"""
from __future__ import annotations

import json


SCRIPT = "features/common/skills/task/scripts/tracker_lib.py"


def _write(path, records):
    """records: (model, is_sidechain, input, output, cache_read, cache_creation) tuples."""
    lines = []
    for model, is_side, inp, out, cr, cc in records:
        message = {"usage": {"input_tokens": inp, "output_tokens": out,
                             "cache_read_input_tokens": cr,
                             "cache_creation_input_tokens": cc}}
        if model is not None:
            message["model"] = model
        lines.append(json.dumps({"type": "assistant", "isSidechain": is_side,
                                 "message": message}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestUsageIsSplitByModel:
    def test_each_model_gets_its_own_totals(self, load_script, tmp_path):
        tl = load_script(SCRIPT)
        transcript = tmp_path / "t.jsonl"
        _write(transcript, [
            ("claude-opus-5", False, 10, 100, 1000, 50),
            ("claude-sonnet-5", False, 20, 300, 2000, 60),
            ("claude-opus-5", True, 5, 50, 500, 10),
        ])

        by_model = tl.parse_transcript_usage(str(transcript))["byModel"]

        assert by_model["claude-opus-5"]["outputTokens"] == 150
        assert by_model["claude-opus-5"]["assistantMessages"] == 2
        assert by_model["claude-sonnet-5"]["outputTokens"] == 300
        assert by_model["claude-opus-5"]["cacheReadTokens"] == 1500

    def test_sidechain_work_counts_toward_its_model(self, load_script, tmp_path):
        """A subagent's tokens are billed work, and it is the model choice under scrutiny."""
        tl = load_script(SCRIPT)
        transcript = tmp_path / "t.jsonl"
        _write(transcript, [("claude-haiku-4-5", True, 1, 90, 10, 0)])

        by_model = tl.parse_transcript_usage(str(transcript))["byModel"]

        assert by_model["claude-haiku-4-5"]["outputTokens"] == 90

    def test_a_message_with_no_model_field_is_still_counted(self, load_script, tmp_path):
        """Real transcripts carry `<synthetic>` and occasionally nothing; neither may vanish."""
        tl = load_script(SCRIPT)
        transcript = tmp_path / "t.jsonl"
        _write(transcript, [(None, False, 1, 7, 0, 0)])

        by_model = tl.parse_transcript_usage(str(transcript))["byModel"]

        assert by_model["unknown"]["outputTokens"] == 7

    def test_the_per_model_totals_reconcile_with_the_cumulative_total(self, load_script,
                                                                     tmp_path):
        """The split must be a partition, not a second opinion."""
        tl = load_script(SCRIPT)
        transcript = tmp_path / "t.jsonl"
        _write(transcript, [
            ("claude-opus-5", False, 10, 100, 1000, 50),
            ("claude-sonnet-5", True, 20, 300, 2000, 60),
            (None, False, 3, 7, 5, 1),
        ])

        usage = tl.parse_transcript_usage(str(transcript))

        for key in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheCreationTokens"):
            assert sum(m[key] for m in usage["byModel"].values()) == usage["cumulative"][key], key

    def test_a_missing_transcript_reports_an_empty_split(self, load_script, tmp_path):
        tl = load_script(SCRIPT)

        usage = tl.parse_transcript_usage(str(tmp_path / "absent.jsonl"))

        assert usage["byModel"] == {}
        assert usage["transcriptFound"] is False


class TestTheTaskDeltaCarriesTheMix:
    def test_compute_usage_reports_output_tokens_per_model_for_the_task_only(self, load_script,
                                                                            tmp_path):
        """Two checkpoints of one session: what this task spent, not what the session has."""
        tl = load_script(SCRIPT)
        start = {"cumulative": {"outputTokens": 100}, "contextTokens": 0,
                 "byModel": {"claude-opus-5": {"outputTokens": 100}}}
        finish = {"cumulative": {"outputTokens": 400}, "contextTokens": 0,
                  "byModel": {"claude-opus-5": {"outputTokens": 250},
                              "claude-sonnet-5": {"outputTokens": 150}}}

        usage = tl.compute_usage(start, finish, [])

        assert usage["outputByModel"] == {"claude-opus-5": 150, "claude-sonnet-5": 150}

    def test_the_mix_is_the_share_of_output_each_model_produced(self, load_script):
        """The actionable number: 'this task did 80% of its output on the expensive model'."""
        tl = load_script(SCRIPT)
        start = {"cumulative": {"outputTokens": 0}, "contextTokens": 0, "byModel": {}}
        finish = {"cumulative": {"outputTokens": 100}, "contextTokens": 0,
                  "byModel": {"claude-opus-5": {"outputTokens": 80},
                              "claude-haiku-4-5": {"outputTokens": 20}}}

        usage = tl.compute_usage(start, finish, [])

        assert usage["modelMix"] == {"claude-opus-5": 0.8, "claude-haiku-4-5": 0.2}

    def test_a_model_that_only_ran_before_this_task_is_not_reported(self, load_script):
        """A delta, so work the previous task did must not be attributed to this one."""
        tl = load_script(SCRIPT)
        start = {"cumulative": {"outputTokens": 500}, "contextTokens": 0,
                 "byModel": {"claude-fable-5": {"outputTokens": 500}}}
        finish = {"cumulative": {"outputTokens": 600}, "contextTokens": 0,
                  "byModel": {"claude-fable-5": {"outputTokens": 500},
                              "claude-sonnet-5": {"outputTokens": 100}}}

        usage = tl.compute_usage(start, finish, [])

        assert usage["outputByModel"] == {"claude-sonnet-5": 100}
        assert usage["modelMix"] == {"claude-sonnet-5": 1.0}

    def test_no_output_at_all_reports_an_empty_mix_rather_than_dividing_by_zero(self,
                                                                               load_script):
        tl = load_script(SCRIPT)
        cp = {"cumulative": {"outputTokens": 0}, "contextTokens": 0, "byModel": {}}

        usage = tl.compute_usage(cp, cp, [])

        assert usage["modelMix"] == {}
        assert usage["outputByModel"] == {}

    def test_an_old_checkpoint_without_the_split_still_computes(self, load_script):
        """token-usage.json predates this field; a task in flight must not break on finish."""
        tl = load_script(SCRIPT)
        start = {"cumulative": {"outputTokens": 10}, "contextTokens": 0}
        finish = {"cumulative": {"outputTokens": 40}, "contextTokens": 0}

        usage = tl.compute_usage(start, finish, [])

        assert usage["outputTokens"] == 30
        assert usage["outputByModel"] == {}


class TestTheCheckpointCarriesTheSplit:
    def test_make_checkpoint_records_the_per_model_totals(self, load_script, tmp_path):
        tl = load_script(SCRIPT)
        transcript = tmp_path / "t.jsonl"
        _write(transcript, [("claude-opus-5", False, 1, 42, 0, 0)])

        checkpoint = tl.make_checkpoint(str(transcript))

        assert checkpoint["byModel"]["claude-opus-5"]["outputTokens"] == 42
