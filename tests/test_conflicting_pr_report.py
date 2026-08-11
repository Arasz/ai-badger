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
from conftest import _test_write

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/conflicting_pr_report.py"

_spec = importlib.util.spec_from_file_location("conflicting_pr_report", SCRIPT)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def pull_request(number, mergeable, comments=(), is_draft=False, comment_total=None):
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/o/r/pull/{number}",
        "isDraft": is_draft,
        "mergeable": mergeable,
        "comments": {
            "totalCount": len(comments) if comment_total is None else comment_total,
            "nodes": [{"body": body} for body in comments],
        },
    }


def payload(*nodes, total=None):
    pull_requests = {"nodes": list(nodes)}
    pull_requests["totalCount"] = len(nodes) if total is None else total
    return {"data": {"repository": {"pullRequests": pull_requests}}}


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


class TestItRefusesToReportOnPullRequestsItDidNotSee:
    """The query asks for the first 100. Open PR 101 would otherwise be silently clean."""

    def test_a_truncated_page_fails_rather_than_under_reporting(self):
        with pytest.raises(ValueError):
            report.stuck_pull_requests(payload(pull_request(1, "MERGEABLE"), total=101))

    def test_a_complete_page_is_fine(self):
        result = report.stuck_pull_requests(payload(pull_request(1, "MERGEABLE"), total=1))

        assert result.checked == 1

    def test_a_payload_without_a_total_is_not_treated_as_truncated(self):
        """Older captures and hand-written fixtures have no totalCount; absence is not proof."""
        result = report.stuck_pull_requests(
            {"data": {"repository": {"pullRequests": {"nodes": [pull_request(1, "CONFLICTING")]}}}})

        assert result.stuck == [1]


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


class TestItWillNotGuessFromAnUnreadCommentHistory:
    """A blocked PR attracts discussion. Once the notice scrolls out of the fetched window,
    "no marker here" stops meaning "not commented yet" — and re-posting every six hours is
    the same guess-instead-of-know this whole detector argues against."""

    def test_a_stuck_pr_whose_history_is_truncated_is_not_commented_again(self):
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=("chatter",), comment_total=500)))

        assert result.stuck == [341]
        assert result.needs_comment == []

    def test_and_it_says_so_rather_than_going_quiet(self):
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=("chatter",), comment_total=500)))

        assert result.history_truncated == [341]

    def test_a_truncated_history_that_still_shows_the_marker_is_settled(self):
        """Seeing the notice is proof; only its absence is inconclusive."""
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=(report.comment_body(),),
                                 comment_total=500)))

        assert result.needs_comment == []
        assert result.history_truncated == []

    def test_a_complete_history_is_not_reported_as_truncated(self):
        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=("chatter",))))

        assert result.needs_comment == [341]
        assert result.history_truncated == []

    def test_a_payload_without_a_comment_total_is_trusted(self):
        """Hand-written fixtures and older captures omit it; absence is not evidence."""
        node = pull_request(341, "CONFLICTING")
        del node["comments"]["totalCount"]

        result = report.stuck_pull_requests(payload(node))

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
        _test_write(source, json.dumps(payload(pull_request(341, "CONFLICTING"))), encoding="utf-8")

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
    """A green gate here is a weak signal, so each of these mutates something real."""

    def test_the_filter_discriminates_rather_than_always_firing(self):
        """One PR number, two mergeable states, opposite verdicts."""
        conflicting = report.stuck_pull_requests(payload(pull_request(341, "CONFLICTING")))
        mergeable = report.stuck_pull_requests(payload(pull_request(341, "MERGEABLE")))

        assert conflicting.stuck == [341]
        assert mergeable.stuck == []

    def test_dedup_breaks_when_the_marker_drifts(self, monkeypatch):
        """Mutate MARKER; a PR carrying the real notice must stop being recognised.

        This is the drift the two-spellings bug would cause, exercised rather than asserted.
        """
        carried = report.comment_body()
        monkeypatch.setattr(report, "MARKER", "<!-- some other marker -->")

        result = report.stuck_pull_requests(
            payload(pull_request(341, "CONFLICTING", comments=(carried,))))

        assert result.needs_comment == [341]
