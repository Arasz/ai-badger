"""Tests for the stuck-PR detector: a required check that never runs must not look slow.

PR #341 is the worked example. Between 17:37 and 18:14 UTC its branch was conflicting with
main. `Lint and test` triggers on `push`, so `build (3.10)` reported three times over that
window; `Secret scan` and `CodeQL` trigger on `pull_request`, and GitHub dispatched neither —
zero runs, not a queued run. The `gitleaks` required check therefore reported nothing at all,
and the mergebox renders "nothing" and "still running" identically.

The detector's whole value is firing on that state, so these tests care about two things: that
a CONFLICTING pull request is reported, and that the marker the detector searches for is the
marker it posts. A drift between those two would make the detector re-comment forever, or —
worse, and the shape this repo keeps rediscovering — never comment while reporting success.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/conflicting_pr_report.py"

_spec = importlib.util.spec_from_file_location("conflicting_pr_report", SCRIPT)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def pull_request(number, mergeable, comments=(), is_draft=False):
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/o/r/pull/{number}",
        "isDraft": is_draft,
        "mergeable": mergeable,
        "comments": {"nodes": [{"body": body} for body in comments]},
    }


def payload(*nodes):
    return {"data": {"repository": {"pullRequests": {"nodes": list(nodes)}}}}


class TestItFiresOnAConflictingPullRequest:
    """The state that produced the finding. If this passes vacuously the detector is useless."""

    def test_a_conflicting_pull_request_is_reported_as_stuck(self):
        result = report.stuck_pull_requests(payload(pull_request(341, "CONFLICTING")))

        assert result.stuck == [341]

    def test_a_conflicting_pull_request_with_no_marker_comment_needs_one(self):
        result = report.stuck_pull_requests(payload(pull_request(341, "CONFLICTING")))

        assert result.needs_comment == [341]

    def test_a_conflicting_draft_is_still_stuck(self):
        """A draft PR's required checks are just as absent; it is stuck, only not yet ready."""
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", is_draft=True)))

        assert result.stuck == [341]

    def test_every_conflicting_pull_request_is_reported_not_just_the_first(self):
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING"),
                    pull_request(342, "MERGEABLE"),
                    pull_request(343, "CONFLICTING")))

        assert result.stuck == [341, 343]


class TestItStaysQuietWhenNothingIsStuck:
    """The other half of "prove it fires": a detector that always fires reports nothing."""

    def test_a_mergeable_pull_request_is_not_stuck(self):
        result = report.stuck_pull_requests(payload(pull_request(342, "MERGEABLE")))

        assert result.stuck == []
        assert result.needs_comment == []

    def test_no_open_pull_requests_is_not_an_error(self):
        result = report.stuck_pull_requests(payload())

        assert result.stuck == []
        assert result.checked == 0


class TestUnknownIsReportedAsUnknown:
    """GitHub computes mergeability lazily. Counting UNKNOWN as clean is the silent-pass path."""

    def test_an_unmeasured_pull_request_is_neither_stuck_nor_ignored(self):
        result = report.stuck_pull_requests(payload(pull_request(342, "UNKNOWN")))

        assert result.stuck == []
        assert result.unknown == [342]

    def test_a_missing_mergeable_field_counts_as_unknown(self):
        node = pull_request(342, "MERGEABLE")
        del node["mergeable"]

        result = report.stuck_pull_requests(payload(node))

        assert result.unknown == [342]


class TestTheMarkerItSearchesForIsTheMarkerItPosts:
    """The coupling that would fail silently: dedup reads one string, the comment writes another."""

    def test_the_comment_body_contains_the_marker(self):
        assert report.MARKER in report.comment_body()

    def test_a_pull_request_already_carrying_that_comment_is_not_commented_again(self):
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=(report.comment_body(),))))

        assert result.stuck == [341]
        assert result.needs_comment == []

    def test_an_unrelated_comment_does_not_suppress_the_notice(self):
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=("looks good to me",))))

        assert result.needs_comment == [341]


class TestTheCommentSaysWhatIsActuallyWrong:
    """"Merge main" is the fix; the notice is worthless if it reads as a generic conflict nag."""

    def test_it_names_the_trigger_that_never_fires(self):
        body = report.comment_body()

        assert "pull_request" in body

    def test_it_names_the_required_check_that_will_never_report(self):
        assert "gitleaks" in report.comment_body()

    def test_it_explains_why_the_other_check_still_reports(self):
        """The asymmetry is the whole reason this looks like slowness rather than absence."""
        body = report.comment_body()

        assert "push" in body
        assert "build (3.10)" in body


class TestTheCommandLine:
    """The workflow calls this as a subprocess; a traceback there is a silently skipped step."""

    def _run(self, args, stdin=""):
        return subprocess.run([sys.executable, str(SCRIPT)] + args, input=stdin,
                              capture_output=True, text=True, check=False)

    def test_it_reads_a_payload_from_stdin_and_prints_json(self):
        proc = self._run([], json.dumps(payload(pull_request(341, "CONFLICTING"))))

        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["needs_comment"] == [341]

    def test_it_reads_a_payload_from_a_file(self, tmp_path):
        source = tmp_path / "prs.json"
        source.write_text(json.dumps(payload(pull_request(341, "CONFLICTING"))), encoding="utf-8")

        proc = self._run(["--from", str(source)])

        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["stuck"] == [341]

    def test_print_comment_emits_the_body_the_dedup_looks_for(self):
        proc = self._run(["--print-comment"])

        assert proc.returncode == 0, proc.stderr
        assert report.MARKER in proc.stdout

    def test_malformed_input_fails_loudly_rather_than_reporting_nothing_stuck(self):
        """A detector that answers "all clear" to garbage is the failure mode it exists to catch."""
        proc = self._run([], "not json at all")

        assert proc.returncode != 0
        assert "stuck" not in proc.stdout

    def test_a_payload_with_no_repository_fails_loudly(self):
        proc = self._run([], json.dumps({"data": {"repository": None}}))

        assert proc.returncode != 0

    def test_help_runs(self):
        proc = self._run(["--help"])

        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr


class TestTheseChecksCouldFail:
    """A green gate here is a weak signal; each assertion above must have a way to go red."""

    def test_reporting_only_mergeable_pull_requests_would_be_caught(self):
        """Mutation: invert the filter. The conflicting-PR tests must then fail."""
        with pytest.raises(AssertionError):
            result = report.stuck_pull_requests(payload(pull_request(341, "MERGEABLE")))
            assert result.stuck == [341]

    def test_a_comment_body_without_the_marker_would_be_caught(self):
        with pytest.raises(AssertionError):
            assert report.MARKER in "a body that forgot its marker"
