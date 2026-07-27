"""Tests for .lefthook/pre-push/verify.sh: the local pre-push quality gate.

The gate's own failure modes are the ones nothing else can catch — a "passing" run that ran
nothing, and a failing lane that still exits 0. Both are asserted here against the real script
under /bin/bash, which on macOS is 3.2.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / ".lefthook" / "pre-push" / "verify.sh"
ZERO = "0" * 40


def _run(*args, stdin="", env=None):
    """Invoke the gate under /bin/bash with a clean, non-skipping environment."""
    environ = dict(os.environ)
    environ.pop("VERIFY_SKIP", None)
    environ.pop("SKIP_VERIFY", None)
    environ.update(env or {})
    return subprocess.run(
        ["/bin/bash", str(GATE), *args],
        input=stdin, capture_output=True, text=True, cwd=str(REPO), env=environ, check=False)


def test_gate_is_executable():
    assert GATE.is_file()
    assert os.access(GATE, os.X_OK)


def test_parses_under_bash_3_2():
    done = subprocess.run(["/bin/bash", "-n", str(GATE)], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr


def test_unknown_subcommand_is_non_zero():
    done = _run("bogus")
    assert done.returncode != 0
    assert "unknown subcommand" in done.stdout + done.stderr


def test_help_exits_zero():
    assert _run("--help").returncode == 0


def test_skip_verify_short_circuits_pre_push():
    done = _run("pre-push", env={"SKIP_VERIFY": "1"})
    assert done.returncode == 0
    assert "skipped" in done.stdout


def test_verify_skip_skips_named_lane():
    done = _run("release", env={"VERIFY_SKIP": "release"})
    assert done.returncode == 0
    assert "skipped" in done.stdout


def test_branch_deletion_runs_nothing():
    """An all-zero local sha publishes no content, so the gate must not fall back to a diff."""
    done = _run("lanes", stdin=f"refs/heads/gone {ZERO} refs/heads/gone {ZERO}\n")
    assert done.returncode == 0
    assert done.stdout.strip() == "DELETION"


def test_gate_own_files_route_to_every_lane():
    """A change to the gate itself must run everything, or a broken gate hides silently."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                          cwd=str(REPO), check=True).stdout.strip()
    selected = _run("lanes", stdin=f"refs/heads/x {head} refs/heads/x {ZERO}\n").stdout.split()
    # HEAD's branch carries .lefthook/ and lefthook.yml, so selection must be the full set.
    for lane in ("pytest", "pylint", "js", "docs", "release", "validate"):
        assert lane in selected


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(REPO),
                          check=True).stdout


def _docs_only_commit():
    """The most recent commit whose diff is confined to docs/*.md, if history has one."""
    for sha in _git("log", "-40", "--format=%H").split():
        changed = _git("diff", "--name-only", f"{sha}~1", sha).split()
        if changed and all(p.startswith("docs/") and p.endswith(".md") for p in changed):
            return sha
    return None


def test_docs_only_change_skips_the_expensive_lanes():
    """Change detection must actually narrow, or the gate is `all` wearing a disguise."""
    sha = _docs_only_commit()
    if sha is None:
        pytest.skip("no docs-only commit in recent history")
    selected = _run("lanes", stdin=f"refs/heads/x {sha} refs/heads/x {sha}~1\n").stdout.split()
    assert "docs" in selected
    for expensive in ("pytest", "pylint", "js"):
        assert expensive not in selected


@pytest.mark.parametrize("lane", ["version-sync", "index", "plugin-skills", "deps", "docs",
                                  "release", "validate", "tdd", "js", "pylint", "pytest"])
def test_every_advertised_lane_is_dispatchable(lane):
    """A lane named in usage but missing from the dispatch table would skip silently."""
    done = _run(lane, env={"VERIFY_SKIP": lane})
    assert done.returncode == 0
    assert lane in done.stdout


def test_failing_lane_propagates_non_zero():
    """The bash trap the guide names: an `if` with no `else` returns 0 and eats the failure."""
    done = _run("release", env={"AIB_PYTHON": "/bin/false"})
    assert done.returncode != 0
    assert "failed" in done.stdout


def test_failure_block_prints_all_three_escape_hatches():
    """A gate nobody can bypass under pressure gets uninstalled, which is silent coverage loss."""
    out = _run("release", env={"AIB_PYTHON": "/bin/false"}).stdout
    assert "VERIFY_SKIP=release" in out
    assert "SKIP_VERIFY=1" in out
    assert "--no-verify" in out
    assert "reproduce:" in out
