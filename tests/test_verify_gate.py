"""Tests for .lefthook/pre-push/verify.sh: the local pre-push quality gate.

The gate's own failure modes are the ones nothing else can catch — a "passing" run that ran
nothing, and a failing lane that still exits 0. Both are asserted here against the real script
under /bin/bash, which on macOS is 3.2.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / ".lefthook" / "pre-push" / "verify.sh"
ZERO = "0" * 40

# The gate keys its log directory by the checkout it runs in, so these tests — which run it in
# the real repo — would write over the very log a failing push tells the user to read (#212).
_LOG_DIR = tempfile.mkdtemp(prefix="verify-gate-tests-")


def _run(*args, stdin="", env=None):
    """Invoke the gate under /bin/bash with a clean, non-skipping environment."""
    environ = dict(os.environ)
    environ.pop("VERIFY_SKIP", None)
    environ.pop("SKIP_VERIFY", None)
    environ["VERIFY_LOG_DIR"] = _LOG_DIR
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
    # Find the commit that last touched .lefthook/ and use its parent as base,
    # so the diff includes gate files and want_all triggers.
    last_gate = subprocess.run(["git", "log", "-1", "--format=%H", "--", ".lefthook/"],
                               capture_output=True, text=True, cwd=str(REPO),
                               check=False).stdout.strip()
    if not last_gate:
        pytest.skip("no .lefthook/ commit in history")
    base = f"{last_gate}~1"
    selected = _run("lanes", stdin=f"refs/heads/x {head} refs/heads/x {base}\n").stdout.split()
    # Gate file changes must select every lane, or a broken gate hides silently.
    for lane in ("pytest", "pylint", "js", "docs", "release", "paths", "scaffold", "validate"):
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
                                  "release", "paths", "scaffold", "validate", "tdd", "js",
                                  "pylint", "pytest"])
def test_every_advertised_lane_is_dispatchable(lane):
    """A lane named in usage but missing from the dispatch table would skip silently."""
    done = _run(lane, env={"VERIFY_SKIP": lane})
    assert done.returncode == 0
    assert lane in done.stdout


def test_lanes_do_not_inherit_the_hook_git_environment(tmp_path):
    """git points a hook's children at THIS repo, so a test building a temp repo would
    commit into the real one. The lane must see the environment a hand-run would."""
    probe = tmp_path / "probe.sh"
    probe.write_text('#!/bin/sh\nfor v in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; do\n'
                     '  eval "val=\\$$v"\n  [ -n "$val" ] && exit 9\ndone\nexit 0\n',
                     encoding="utf-8")
    probe.chmod(0o755)
    gitdir = _git("rev-parse", "--path-format=absolute", "--git-dir").strip()
    done = _run("docs", env={"AIB_PYTHON": str(probe), "GIT_DIR": gitdir,
                             "GIT_INDEX_FILE": f"{gitdir}/index"})
    assert done.returncode == 0, f"a lane still saw git's hook environment:\n{done.stdout}"


@pytest.mark.parametrize("lane", ["pylint", "js"])
def test_lane_with_nothing_to_check_fails_instead_of_passing(lane, tmp_path):
    """A file-list lane that finds nothing has a broken index, not a clean tree. Reporting
    a 0s pass there is the "passing run that ran nothing" failure the gate exists to stop."""
    empty = tmp_path / "repo"
    empty.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(empty), check=True)
    gate = empty / ".lefthook" / "pre-push"
    gate.mkdir(parents=True)
    (gate / "verify.sh").write_text(GATE.read_text(encoding="utf-8"), encoding="utf-8")
    (gate / "verify.sh").chmod(0o755)
    done = subprocess.run(["/bin/bash", str(gate / "verify.sh"), lane], cwd=str(empty),
                          capture_output=True, text=True, check=False)
    assert done.returncode != 0, f"{lane} reported a pass with nothing to check"
    assert "refusing to report a pass" in done.stdout


def test_log_dir_is_per_checkout(tmp_path):
    """Two checkouts must not share a log path, or a nested run overwrites the log the
    failure block just told the developer to open."""
    other = tmp_path / "repo"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(other), check=True)
    gate = other / ".lefthook" / "pre-push"
    gate.mkdir(parents=True)
    (gate / "verify.sh").write_text(GATE.read_text(encoding="utf-8"), encoding="utf-8")
    (gate / "verify.sh").chmod(0o755)
    here = _run("pylint", env={"VERIFY_SKIP": "pylint"}).stdout
    there = subprocess.run(["/bin/bash", str(gate / "verify.sh"), "pylint"], cwd=str(other),
                           capture_output=True, text=True, check=False).stdout
    assert "refusing to report a pass" not in here
    assert "refusing to report a pass" in there


def _cited_log_dir():
    """The LOG_DIR verify.sh derives with no override: cksum of the repo path, under TMPDIR."""
    key = subprocess.run(["cksum"], input=str(REPO), capture_output=True, text=True,
                         check=True).stdout.split()[0]
    return Path(os.environ.get("TMPDIR", "/tmp")) / "ai-badger-verify" / key


def test_a_gate_run_does_not_clobber_the_log_a_real_push_cites():
    """The pytest lane runs this suite, so its gate runs must not overwrite the cited log (#212)."""
    cited = _cited_log_dir() / "release.log"
    cited.parent.mkdir(parents=True, exist_ok=True)
    sentinel = "the failure the outer push actually hit\n"
    cited.write_text(sentinel, encoding="utf-8")
    _run("release", env={"AIB_PYTHON": "/bin/false"})
    assert cited.read_text(encoding="utf-8") == sentinel, \
        "a gate run from the test suite overwrote the log path a failing push reports"


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


def test_summary_log_is_appended_on_run():
    """Every gate invocation appends a structured line to logs/lefthook.log."""
    log_path = REPO / "logs" / "lefthook.log"
    before_lines = log_path.read_text().splitlines() if log_path.exists() else []
    _run("release", env={"VERIFY_SKIP": "release"})
    assert log_path.exists(), "logs/lefthook.log was not created"
    after_lines = log_path.read_text().splitlines()
    assert len(after_lines) > len(before_lines), "no new log line appended"
    line = after_lines[-1]
    # Format: 2026-07-27 21:30:00 | lane       | release | PASS | 0s
    assert "|" in line
    parts = [p.strip() for p in line.split("|")]
    assert len(parts) >= 5, f"expected at least 5 pipe-delimited fields, got {len(parts)}"
    assert parts[1] == "lane"
    assert parts[2] == "release"
    assert parts[3] in ("PASS", "FAIL")
    assert parts[4].endswith("s")


def test_summary_log_records_failed_lanes():
    """A failing run logs the failed lane names after a 'failed:' marker."""
    log_path = REPO / "logs" / "lefthook.log"
    before_lines = log_path.read_text().splitlines() if log_path.exists() else []
    _run("release", env={"AIB_PYTHON": "/bin/false"})
    after_lines = log_path.read_text().splitlines()
    assert len(after_lines) > len(before_lines), "no log line for failing run"
    line = after_lines[-1]
    assert "FAIL" in line
    assert "failed:" in line, f"expected 'failed:' marker in: {line}"
    assert "release" in line.split("failed:")[1]
