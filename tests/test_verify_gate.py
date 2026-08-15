"""Tests for .lefthook/pre-push/verify.sh: the local pre-push quality gate.

The gate's own failure modes are the ones nothing else can catch — a "passing" run that ran
nothing, and a failing lane that still exits 0. Both are asserted here against the real script
under /bin/bash, which on macOS is 3.2.
"""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List

import pytest

import badger_lib as bl
from conftest import _test_write

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / ".lefthook" / "pre-push" / "verify.sh"
ZERO = "0" * 40

# The gate keys its log directory by the checkout it runs in, so these tests — which run it in
# the real repo — would write over the very log a failing push tells the user to read (#212).
_LOG_DIR = tempfile.mkdtemp(prefix="verify-gate-tests-")
# Same reason as _LOG_DIR: without this the suite appends rows to the repo's own summary that
# no push produced, and a reader cannot tell them from real ones.
_LOG_SUMMARY = str(Path(_LOG_DIR) / "lefthook.log")


def _gate_env(env=None):
    """A clean, non-skipping, redirected environment for the gate.

    One source, so a caller that builds its own cannot quietly stop redirecting the logs.
    """
    environ = dict(os.environ)
    environ.pop("VERIFY_SKIP", None)
    environ.pop("SKIP_VERIFY", None)
    # Same reason as the two above: an outer gate run exports its own deadline, and a nested
    # run inheriting a nearly-spent one would time out for a reason no test asked for.
    environ.pop("VERIFY_DEADLINE", None)
    environ["VERIFY_LOG_DIR"] = _LOG_DIR
    environ["VERIFY_LOG_SUMMARY"] = _LOG_SUMMARY
    environ.update(env or {})
    return environ


def _run(*args, stdin="", env=None):
    """Invoke the gate under /bin/bash with a clean, non-skipping environment."""
    return subprocess.run(
        ["/bin/bash", str(GATE), *args], input=stdin, capture_output=True, text=True,
        cwd=str(REPO), env=_gate_env(env), check=False)


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


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(REPO),
                          check=True).stdout


@pytest.mark.parametrize("lane", ["version-sync", "index", "plugin-skills", "deps", "docs",
                                  "release", "paths", "workflows", "scaffold", "validate", "tdd",
                                  "js", "pylint", "pytest"])
def test_every_advertised_lane_is_dispatchable(lane):
    """A lane named in usage but missing from the dispatch table would skip silently."""
    done = _run(lane, env={"VERIFY_SKIP": lane})
    assert done.returncode == 0
    assert lane in done.stdout


# ── the hook's `unset` and badger_lib's list are one enumeration in two languages ──
#
# verify.sh drops git's hook environment in shell; `badger_lib.git_env` drops it in Python.
# Nothing compared the two, and verify.sh was missing five of the nine names in
# GIT_LOCATION_ENV. A superset, not equality: verify.sh legitimately also drops
# GIT_QUARANTINE_PATH, GIT_REFLOG_ACTION, GIT_AUTHOR_DATE, GIT_COMMITTER_DATE and GIT_EDITOR,
# which pin git's behaviour rather than its location.


def _unset_names(text: str) -> List[str]:
    """Every name a top-level `unset` drops, following backslash line continuations."""
    lines = text.splitlines()
    names: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("unset "):
            while line.rstrip().endswith("\\") and index + 1 < len(lines):
                index += 1
                line = line.rstrip()[:-1] + lines[index]
            names += line.split()[1:]
        index += 1
    return names


def test_the_hook_unsets_every_variable_badger_lib_calls_a_location_variable():
    """A name in only one of the two lists is a hole in the other."""
    dropped = set(_unset_names(GATE.read_text(encoding="utf-8")))

    assert bl.GIT_LOCATION_ENV, "the tuple is empty, so this proves nothing"
    assert "GIT_DIR" in dropped, "the unset line did not parse, so the check below proves nothing"
    missing = sorted(set(bl.GIT_LOCATION_ENV) - dropped)
    assert not missing, (
        "verify.sh does not unset every variable badger_lib.git_env strips, so a lane sees a "
        f"git environment the Python helpers refuse to trust: {missing}")


def test_the_unset_reader_follows_a_line_continuation():
    """The real `unset` spans two lines; a reader stopping at the first would pass blind."""
    assert _unset_names("unset A B \\\n      C D\nunset E\n") == ["A", "B", "C", "D", "E"]


def test_the_unset_reader_ignores_a_mention_that_unsets_nothing():
    """A name in a comment, or in a function's own local unset, is not the environment scrub."""
    assert _unset_names("# unset GIT_DIR\nfoo() { unset GIT_WORK_TREE; }\n") == []


def test_lanes_do_not_inherit_the_hook_git_environment(tmp_path):
    """git points a hook's children at THIS repo, so a test building a temp repo would
    commit into the real one. The lane must see the environment a hand-run would."""
    probe = tmp_path / "probe.sh"
    _test_write(probe, '#!/bin/sh\nfor v in GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; do\n'
                     '  eval "val=\\$$v"\n  [ -n "$val" ] && exit 9\ndone\nexit 0\n', encoding="utf-8")
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
    _test_write(gate / "verify.sh", GATE.read_text(encoding="utf-8"), encoding="utf-8")
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
    _test_write(gate / "verify.sh", GATE.read_text(encoding="utf-8"), encoding="utf-8")
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


@contextmanager
def _preserved(path: Path):
    """Restore a real on-disk file after a test writes over it, including restoring its absence."""
    had = path.exists()
    before = path.read_bytes() if had else None
    try:
        yield
    finally:
        if had:
            path.write_bytes(before)  # deliberate real-path write — gate bypass for restore
        elif path.exists():
            path.unlink()


def test_preserved_restores_prior_content(tmp_path):
    target = tmp_path / "cited.log"
    _test_write(target, "the real failure\n", encoding="utf-8")
    with _preserved(target):
        _test_write(target, "a test fixture\n", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "the real failure\n"


def test_preserved_restores_absence(tmp_path):
    target = tmp_path / "never-existed.log"
    with _preserved(target):
        _test_write(target, "a test fixture\n", encoding="utf-8")
    assert not target.exists()


def test_a_gate_run_does_not_clobber_the_log_a_real_push_cites():
    """The pytest lane runs this suite, so its gate runs must not overwrite the cited log (#212)."""
    cited = _cited_log_dir() / "release.log"
    cited.parent.mkdir(parents=True, exist_ok=True)
    sentinel = "the failure the outer push actually hit\n"
    with _preserved(cited):
        _test_write(cited, sentinel, encoding="utf-8")
        _run("release", env={"AIB_PYTHON": "/bin/false"})
        assert cited.read_text(encoding="utf-8") == sentinel, \
            "a gate run from the test suite overwrote the log path a failing push reports"


def test_log_summary_honours_an_override(tmp_path):
    """Without this the suite appends real-looking lane rows to the repo's own logs/lefthook.log."""
    redirected = tmp_path / "lefthook.log"
    repo_summary = REPO / "logs" / "lefthook.log"
    with _preserved(repo_summary):
        _run("release", env={"AIB_PYTHON": "/bin/false",
                             "VERIFY_LOG_SUMMARY": str(redirected)})
        assert redirected.exists(), "VERIFY_LOG_SUMMARY was ignored"
        assert "release" in redirected.read_text(encoding="utf-8")


def test_a_redirected_run_leaves_the_repo_summary_alone(tmp_path):
    redirected = tmp_path / "lefthook.log"
    repo_summary = REPO / "logs" / "lefthook.log"
    before = repo_summary.read_bytes() if repo_summary.exists() else None
    with _preserved(repo_summary):
        _run("release", env={"AIB_PYTHON": "/bin/false",
                             "VERIFY_LOG_SUMMARY": str(redirected)})
        after = repo_summary.read_bytes() if repo_summary.exists() else None
    assert after == before, "a redirected gate run still wrote the repo's lefthook.log"


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
    """Every gate invocation appends a structured line to the summary log."""
    log_path = Path(_LOG_SUMMARY)
    before_lines = log_path.read_text().splitlines() if log_path.exists() else []
    _run("release", env={"VERIFY_SKIP": "release"})
    assert log_path.exists(), "the summary log was not created"
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
    log_path = Path(_LOG_SUMMARY)
    before_lines = log_path.read_text().splitlines() if log_path.exists() else []
    _run("release", env={"AIB_PYTHON": "/bin/false"})
    after_lines = log_path.read_text().splitlines()
    assert len(after_lines) > len(before_lines), "no log line for failing run"
    line = after_lines[-1]
    assert "FAIL" in line
    assert "failed:" in line, f"expected 'failed:' marker in: {line}"
    assert "release" in line.split("failed:")[1]


# ── the validate lane covers the agent-instruction validators ───────────────────
#
# Both .mjs validators ran in no gate at all until 0.91.0 (review finding A7): only their unit
# tests did, so real drift between the model and CLAUDE.md/AGENTS.md reached main unnoticed.

AGENT_INSTRUCTION_VALIDATORS = (
    "features/common/skills/maintain-agent-instructions/scripts/validate-agent-instructions.mjs",
    "features/common/skills/maintain-agent-instructions/scripts/check-agent-drift.mjs",
)


def _shim(path, body):
    """Write an executable /bin/sh shim and return its path as a string."""
    _test_write(path, f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


@contextmanager
def _recording_node(tmp_path, exit_code=0):
    """Put a `node` on PATH that records its argv and exits with `exit_code`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    record = tmp_path / "node-argv.txt"
    _shim(bindir / "node", f'printf "%s\\n" "$*" >> {record}\nexit {exit_code}')
    yield record, {"PATH": f"{bindir}:{os.environ['PATH']}",
                   "AIB_PYTHON": _shim(tmp_path / "py-pass", "exit 0")}


def test_the_validate_lane_runs_both_agent_instruction_validators(tmp_path):
    with _recording_node(tmp_path) as (record, env):
        done = _run("validate", env=env)

    assert done.returncode == 0, done.stdout
    invoked = record.read_text(encoding="utf-8") if record.exists() else ""
    for script in AGENT_INSTRUCTION_VALIDATORS:
        assert script in invoked, f"the validate lane never ran {script}:\n{invoked}"


def test_the_validate_lane_fails_when_an_agent_instruction_validator_fails(tmp_path):
    """A validator that reports drift must take the lane down with it."""
    with _recording_node(tmp_path, exit_code=1) as (_record, env):
        done = _run("validate", env=env)

    assert done.returncode != 0, f"a failing validator was swallowed:\n{done.stdout}"


# ── the local lane set ──────────────────────────────────────────────────────────
#
# pytest was selected in 209 of the 225 pre-push rows in logs/lefthook.log; those runs are p50
# 89s against p50 4s for the 16 without it. Both lanes already run in CI on every push to every
# branch (.github/workflows/pylint.yml runs `verify.sh pytest` and `verify.sh pylint`), on the
# 3.10 this project floors at rather than whatever the developer's machine has — so the local
# copy is slower than the push and proves less than the run it duplicates.

CI_OWNED = ("pytest", "pylint")


def _advertised_lanes():
    """Every lane the gate advertises, read off its own usage line rather than restated here."""
    for line in _run("--help").stdout.splitlines():
        if "one of:" in line:
            return line.split("one of:", 1)[1].split()
    raise AssertionError("usage no longer advertises the lane list, so nothing here is derived")


def _selected_for_a_push(env=None):
    """The lanes a push would run, over a ref pair whose diff is empty by construction.

    HEAD against HEAD publishes content (so it is not the deletion case) and diffs to nothing,
    so no assertion below depends on what happens to be committed on the branch it runs from.
    """
    head = _git("rev-parse", "HEAD").strip()
    return _run("lanes", stdin=f"refs/heads/x {head} refs/heads/x {head}\n",
                env=env).stdout.split()


def test_a_push_leaves_pytest_and_pylint_to_ci():
    """The whole point: a push must not spend 89s re-proving what CI proves better."""
    selected = _selected_for_a_push()

    assert selected, "the gate selected no lane at all, so the assertions below prove nothing"
    for lane in CI_OWNED:
        assert lane not in selected, f"a push still runs {lane} locally: {selected}"


def test_a_push_runs_every_other_lane():
    """No routing left: the local set is the advertised lanes minus the two CI owns.

    Derived from the usage line, so a lane added to `$LANES` and forgotten here cannot pass.
    """
    selected = _selected_for_a_push()
    expected = [lane for lane in _advertised_lanes() if lane not in CI_OWNED]

    assert expected, "no lanes were derived from usage, so this compares nothing"
    assert selected == expected, f"{selected} != {expected}"


@pytest.mark.parametrize("lane", CI_OWNED)
def test_a_ci_owned_lane_is_still_invocable_by_hand(lane):
    """`pylint.yml` invokes each by name; dropping it from `$LANES` makes that step exit 2."""
    done = _run(lane, env={"VERIFY_SKIP": lane})

    assert done.returncode == 0, done.stdout + done.stderr
    assert lane in done.stdout


def test_all_still_runs_the_ci_owned_lanes():
    """`all` means every lane. Only the push selection narrows, and CI reads `$LANES` from
    this script to build the lane list its `gates` job walks."""
    out = _run("all", env={"VERIFY_SKIP": ",".join(_advertised_lanes())}).stdout
    named = {line.split()[1] for line in out.splitlines() if "skipped (VERIFY_SKIP)" in line}

    for lane in CI_OWNED:
        assert lane in named, f"`verify.sh all` no longer runs {lane}: {sorted(named)}"


# ── --risk actually changes which lanes run ─────────────────────────────────────
#
# `--risk` was parsed, persisted and printed by task_tracker.py and consumed by nothing
# (review finding A8). The gate now asks the tracker, so the flag buys what it claims.

def _risk_stub(tmp_path, task_id=""):
    """A stand-in for `$PY` that answers the risk query with `task_id` (empty = risk off)."""
    body = f'printf "%s" "{task_id}"' if task_id else "exit 0"
    return {"AIB_PYTHON": _shim(tmp_path / "py-stub", body)}


def test_a_risk_task_drops_the_lane_it_names(tmp_path):
    """Same push, risk off then on, so only the flag can explain the difference."""
    env = {"VERIFY_RISK_DROPPED": "journey"}
    offered = _selected_for_a_push({**_risk_stub(tmp_path), **env})
    selected = _selected_for_a_push({**_risk_stub(tmp_path, "TASK-1"), **env})

    assert "journey" in offered, (
        f"journey was not offered even without --risk, so its absence proves nothing "
        f"about the flag: {offered}")
    assert "journey" not in selected, f"--risk left journey in: {selected}"


def test_a_risk_task_keeps_every_other_lane(tmp_path):
    """`--risk` trades away what it names and nothing else."""
    env = {"VERIFY_RISK_DROPPED": "journey"}
    offered = _selected_for_a_push({**_risk_stub(tmp_path), **env})
    selected = _selected_for_a_push({**_risk_stub(tmp_path, "TASK-1"), **env})

    assert selected == [lane for lane in offered if lane != "journey"], \
        f"--risk changed more than the lane it names: {offered} -> {selected}"


def test_a_risk_run_that_drops_nothing_announces_nothing(tmp_path):
    """`pytest` is the only lane `--risk` trades away and no push runs it, so there is no
    trade to announce. Machinery claiming a safety trade it is not making is worse than absent.
    """
    out = _run("pre-push", env=_risk_stub(tmp_path, "TASK-1")).stdout

    assert "limited gates" not in out, f"--risk claimed a trade it did not make:\n{out}"


def test_a_risk_run_that_drops_a_local_lane_says_so_and_names_it(tmp_path):
    """The other half: the notice above is silent because the dropped set is empty, not
    because the notice is gone. A reduced gate that looks like a full one is the real failure.
    """
    out = _run("pre-push", env={**_risk_stub(tmp_path, "TASK-1"),
                                "VERIFY_RISK_DROPPED": "journey"}).stdout
    notice = [line for line in out.splitlines() if "limited gates" in line]

    assert len(notice) == 1, f"expected exactly one notice, got {notice}:\n{out}"
    assert "TASK-1" in notice[0], notice[0]
    # The notice must name what this run actually dropped. Asserting it anywhere in `out`
    # passes against the old unconditional notice, because the lane list prints below it.
    assert "journey" in notice[0], notice[0]
    assert "pytest" not in notice[0], f"the notice still restates a lane no push runs: {notice[0]}"


# ── the wall-clock deadline ─────────────────────────────────────────────────────
#
# 2026-08-15: a pre-push run reached the pytest lane and was still sitting there 23 minutes
# later with no output. Its process had PPID 1 — git push, lefthook and verify.sh had all
# exited and the lane outlived every one of them. logs/lefthook.log held 225 pre-push rows and
# not one of them was that run: `_log_summary` is only reached after `run_lanes` returns, so a
# hung or killed run is invisible by construction and every surviving row is a survivor.


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _reap(pid: int) -> None:
    """Leave no `sleep 600` behind when the assertion that follows it fails."""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _hanging_python(tmp_path):
    """An AIB_PYTHON that never returns, so only the deadline can end the lane.

    600s against a 1s deadline: no threshold here is close enough to flake under load.
    """
    return _shim(tmp_path / "py-hang", "sleep 600")


def test_a_lane_past_the_deadline_is_killed(tmp_path):
    """The gate must bound its own wall clock; nothing outside it was found to."""
    started = time.monotonic()
    done = _run("release", env={"AIB_PYTHON": _hanging_python(tmp_path),
                                "VERIFY_DEADLINE": "1"})
    elapsed = time.monotonic() - started

    assert elapsed < 15, f"a 1s deadline let the gate run {elapsed:.0f}s"
    assert done.returncode == 124, (
        f"a deadline kill must be distinguishable from a lane's own failure — expected 124, "
        f"got {done.returncode}:\n{done.stdout}\n{done.stderr}")
    assert "TIMEOUT" in done.stdout, done.stdout
    assert "release" in done.stdout, f"the timeout never named the lane in flight:\n{done.stdout}"


def test_a_timed_out_run_still_writes_a_summary_row(tmp_path):
    """The survivorship fix: the row is written before the kill, so a killed shell keeps it."""
    summary = tmp_path / "lefthook.log"
    _run("release", env={"AIB_PYTHON": _hanging_python(tmp_path), "VERIFY_DEADLINE": "1",
                         "VERIFY_LOG_SUMMARY": str(summary)})

    assert summary.exists(), "a run the deadline killed left no trace in the summary log"
    rows = [row for row in summary.read_text(encoding="utf-8").splitlines() if row.strip()]
    assert len(rows) == 1, "expected exactly one row, got:\n" + "\n".join(rows)
    fields = [field.strip() for field in rows[0].split("|")]
    assert fields[3] == "TIMEOUT", rows[0]
    assert "release" in fields[-1], f"the row does not name the lane in flight: {rows[0]}"


def test_the_deadline_kills_the_whole_process_group(tmp_path):
    """The observed orphan: killing the direct child reparents its children onto PID 1."""
    pidfile = tmp_path / "grandchild.pid"
    shim = _shim(tmp_path / "py-spawn", f'sleep 600 &\nprintf "%s" "$!" >{pidfile}\nwait')
    started = time.monotonic()
    _run("release", env={"AIB_PYTHON": shim, "VERIFY_DEADLINE": "1"})
    elapsed = time.monotonic() - started

    assert pidfile.exists(), "the shim started no grandchild, so this proves nothing"
    # Without this the grandchild is dead because it slept out its 600s, not because anything
    # killed it, and the assertion below would pass against a gate with no deadline at all.
    assert elapsed < 15, f"the deadline never fired ({elapsed:.0f}s), so nothing was killed"
    pid = int(pidfile.read_text(encoding="utf-8"))
    try:
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        assert not _alive(pid), (
            f"the lane's grandchild (pid {pid}) outlived the deadline kill — this is the "
            "orphan on PID 1 the deadline exists to prevent")
    finally:
        _reap(pid)


def test_an_operator_interrupt_still_writes_a_summary_row(tmp_path):
    """The other way a run ends with no row. The deadline is set far away, so only the signal
    can end this one."""
    summary = tmp_path / "lefthook.log"
    log_dir = tmp_path / "gate-logs"
    env = _gate_env({"AIB_PYTHON": _hanging_python(tmp_path), "VERIFY_DEADLINE": "300",
                     "VERIFY_LOG_DIR": str(log_dir), "VERIFY_LOG_SUMMARY": str(summary)})
    gate = subprocess.Popen(  # pylint: disable=consider-using-with
        ["/bin/bash", str(GATE), "release"], cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        # Non-empty, not merely present: the file is created by the redirect a moment before the
        # pgid lands in it, and signalling inside that window tests a different thing — a trap
        # with nothing to kill — rather than the one this case is about.
        started = time.monotonic()
        while not _nonempty(log_dir / "current-pgid") and time.monotonic() - started < 60:
            time.sleep(0.05)
        assert _nonempty(log_dir / "current-pgid"), \
            "the lane never reached the point of having a process group, so this proves nothing"
        gate.send_signal(signal.SIGTERM)
        out, _err = gate.communicate(timeout=60)
    finally:
        if gate.poll() is None:
            gate.kill()

    assert gate.returncode == 130, out
    assert "interrupted" in out, out
    rows = [row for row in summary.read_text(encoding="utf-8").splitlines() if row.strip()]
    assert len(rows) == 1, "expected exactly one row, got:\n" + "\n".join(rows)
    fields = [field.strip() for field in rows[0].split("|")]
    assert fields[3] == "ABORT", rows[0]
    assert "release" in fields[-1], f"the row does not name the lane in flight: {rows[0]}"
