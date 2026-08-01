"""The tag a merge creates must be the tag the release guard looks for.

Tagging was manual, and the ritual was skipped often enough to have its own failure mode: a
release that shipped untagged stays wrong on every later push, so the next unrelated PR's CI
fails on a gate nobody touched. 0.61.1, 0.64.2 and 0.68.0 each did this.

The workflow closes that gap, which moves the risk somewhere new: if its tag name ever drifts
from `release_guard.TAG_PATTERN`, tags would still be created and the guard would still report
none — the silently-permissive path the guard's own docstring warns about. This pins the two
together.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/release-tag.yml"

_spec = importlib.util.spec_from_file_location("release_guard", ROOT / "gates/release_guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

workflow = WORKFLOW_PATH.read_text(encoding="utf-8")


def rendered_tag(version: str) -> str:
    """Substitute the workflow's own tag expression rather than restating the format here.

    Restating it would let this test pass while the workflow said something else.
    """
    match = re.search(r'TAG_NAME\s*=\s*"?([A-Za-z0-9-]*)\$\{?VERSION\}?"?', workflow)
    assert match, "could not find the TAG_NAME assignment in the workflow"
    return f"{match.group(1)}{version}"


class TestTheWorkflowExists:
    def test_it_runs_on_pushes_to_main(self):
        assert "branches:" in workflow
        assert "main" in workflow

    def test_it_can_write_to_the_repository(self):
        """Pushing a tag needs more than the default read-only token."""
        assert "contents: write" in workflow

    def test_it_fetches_tags(self):
        """`fetch-depth: 0`; without it the existing-tag check sees an empty tag list."""
        assert "fetch-depth: 0" in workflow


class TestTheTagFormatMatchesTheGuard:
    """The one coupling that would fail silently rather than loudly."""

    def test_the_workflow_builds_a_tag_the_guard_recognises(self):
        rendered = rendered_tag("0.68.0")

        assert guard.TAG_PATTERN.match(rendered), (
            f"workflow would create {rendered!r}, which release_guard.TAG_PATTERN rejects"
        )

    @pytest.mark.parametrize("version", ["0.0.1", "1.2.3", "10.20.30"])
    def test_any_semver_renders_to_a_recognised_tag(self, version):
        assert guard.TAG_PATTERN.match(rendered_tag(version))


class TestOnlyTheRemoteCounts:
    """A local tag ref proves nothing once `git tag -a` has run (#273 review).

    The first version resolved `refs/tags/<name>` after tagging locally, so the "did a
    concurrent run push it?" branch answered yes unconditionally. A rejected push — tag
    protection, a token without `contents: write` — would have reported success and left the
    remote untagged, which is precisely what release_guard fails on afterwards.
    """

    def test_the_existence_checks_ask_the_remote(self):
        assert "git ls-remote --tags origin" in workflow

    def test_no_local_ref_resolution_decides_whether_a_tag_exists(self):
        """`git rev-parse` may still print HEAD for the log line; it must not gate anything."""
        gating = [line for line in workflow.splitlines()
                  if "rev-parse" in line and "refs/tags/" in line]

        assert not gating, f"local ref resolution still decides tag existence: {gating}"

    def test_a_failed_push_is_not_silently_tolerated(self):
        """The failure branch must still exit non-zero when the remote lacks the tag."""
        assert "exit 1" in workflow.split("git push origin")[-1]


def annotate_step() -> str:
    """The body of the annotation step, lifted from the workflow rather than restated.

    Same reason as `rendered_tag`: a test that restates the shell passes while the workflow
    says something else, and breaks on a harmless requote (#292).
    """
    match = re.search(
        r"- name: Annotate a stale release subject\n\s+run: \|\n(.*?)(?=\n\s*- name:)",
        workflow, re.DOTALL)
    assert match, "could not find the 'Annotate a stale release subject' step in the workflow"
    return textwrap.dedent(match.group(1))


def run_annotate(tmp_path, subject: str, version: str) -> str:
    """Run the real step over a real commit, and return what it wrote to stdout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run(git + ["init", "-q"], cwd=repo, check=True)
    (repo / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    subprocess.run(git + ["add", "VERSION"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "--no-verify", "-m", subject], cwd=repo, check=True)

    done = subprocess.run(["bash", "-c", annotate_step()], cwd=repo,
                          capture_output=True, text=True, check=True)
    return done.stdout


class TestReleaseSubjectAnnotation:
    """A stale squash title should be visible without blocking the already-merged release."""

    def test_the_workflow_reads_the_head_subject(self):
        assert 'SUBJECT="$(git log -1 --format=%s)"' in workflow

    @pytest.mark.parametrize("subject,version,warns", [
        # The repo's own convention: the release version is the last parenthesised group.
        ("fix: a task worktree lands where every agent has a directory (0.72.1) (#285)",
         "0.73.0", True),
        ("feat: review before you plan, and check every join (0.72.0) (#284)", "0.72.0", False),
        # A decoy earlier in the subject must not win over the trailing release version.
        ("feat: support python (3.9.1) runtime and bump to (0.73.0) (#291)", "0.73.0", False),
        ("feat: support python (3.9.1) runtime and bump to (0.73.0) (#291)", "0.73.1", True),
        # Nothing parenthesised to compare: silent by design, documented in RELEASING.md.
        ("docs(work): record the sixteen-rules plan while it is in flight (#280)", "0.73.0",
         False),
        ("chore: bump to 0.73.1 (#292)", "0.73.0", False),
    ])
    def test_a_parenthesised_version_mismatch_is_annotated(self, tmp_path, subject, version,
                                                           warns):
        out = run_annotate(tmp_path, subject, version)

        assert ("::warning title=Release subject/version mismatch::" in out) is warns, out

    def test_the_annotation_names_both_versions(self, tmp_path):
        """The warning is only actionable if it says which two numbers disagree."""
        out = run_annotate(tmp_path, "fix: something (0.72.1) (#285)", "0.73.0")

        assert "0.72.1" in out and "0.73.0" in out

    def test_the_step_never_fails_the_release(self, tmp_path):
        """Advisory by design: the merge has already happened by the time this runs."""
        script = annotate_step()
        repo = tmp_path / "repo"
        repo.mkdir()
        git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
        subprocess.run(git + ["init", "-q"], cwd=repo, check=True)
        (repo / "VERSION").write_text("0.73.0\n", encoding="utf-8")
        subprocess.run(git + ["add", "VERSION"], cwd=repo, check=True)
        subprocess.run(git + ["commit", "-q", "--no-verify", "-m", "fix: stale (0.1.2) (#1)"],
                       cwd=repo, check=True)

        done = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True,
                              check=False)

        assert done.returncode == 0, done.stderr


class TestTheGuardStillDrivesTheFormat:
    """A sanity anchor: the prefix is not free-form, it is what the guard already parses."""

    def test_the_guard_parses_the_prefix_the_workflow_uses(self):
        rendered = rendered_tag("9.9.9")

        assert guard._semver(rendered) == (9, 9, 9)
