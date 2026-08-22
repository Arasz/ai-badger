"""`design-tests`' two scripts: the resource scanner and the red-proof runner (W2a).

Both scripts ship inside `features/common/skills/design-tests/scripts/` to every scaffolded
project, so they are Python-3-stdlib-only (ADR-0005) and import nothing from `engine/` — that
dependency exists in this repo, not in a consumer's. Tests load them by path via `load_script`,
the same mechanism `tests/test_test_ruleset_index.py` uses for `rules_index.py`.
"""
# pylint: disable=redefined-outer-name  # pytest fixtures are injected by name
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
SCAN_SCRIPT = str(_ROOT / "features/common/skills/design-tests/scripts/scan_uncontrolled_resources.py")
RED_PROOF_SCRIPT = str(_ROOT / "features/common/skills/design-tests/scripts/red_proof.py")


# --------------------------------------------------------------------------- scan_uncontrolled_resources.py


@pytest.fixture
def scan(load_script):
    return load_script(SCAN_SCRIPT)


class TestScanFindsTheCatalogedPatterns:
    """MoE-4-benchmark.md §5.5(a)'s pattern lists, transcribed verbatim as the category table."""

    def test_csharp_wall_clock_now_is_flagged(self, scan):
        hits = scan.scan_text("var t = DateTime.UtcNow;\n", "Foo.cs")
        assert any(h.category == "wall-clock-now" for h in hits)

    def test_csharp_stopwatch_is_flagged(self, scan):
        hits = scan.scan_text("var sw = Stopwatch.StartNew();\n", "Foo.cs")
        assert any(h.category == "stopwatch" for h in hits)

    def test_csharp_thread_sleep_is_flagged(self, scan):
        hits = scan.scan_text("Thread.Sleep(50);\n", "Foo.cs")
        assert any(h.category == "sleep-or-delay" for h in hits)

    def test_csharp_unseeded_random_is_flagged(self, scan):
        hits = scan.scan_text("var r = new Random();\n", "Foo.cs")
        assert any(h.category == "unseeded-random" for h in hits)

    def test_csharp_environment_read_is_flagged(self, scan):
        hits = scan.scan_text("Environment.GetEnvironmentVariable(\"X\");\n", "Foo.cs")
        assert any(h.category == "environment" for h in hits)

    def test_csharp_filesystem_write_is_flagged(self, scan):
        hits = scan.scan_text("File.WriteAllText(p, s);\n", "Foo.cs")
        assert any(h.category == "filesystem" for h in hits)

    def test_csharp_new_httpclient_is_flagged(self, scan):
        hits = scan.scan_text("var c = new HttpClient();\n", "Foo.cs")
        assert any(h.category == "network" for h in hits)

    def test_csharp_mutable_static_is_flagged(self, scan):
        hits = scan.scan_text("static int counter = 0;\n", "Foo.cs")
        assert any(h.category == "mutable-static" for h in hits)

    def test_ts_date_now_is_flagged(self, scan):
        hits = scan.scan_text("const t = Date.now();\n", "foo.test.ts")
        assert any(h.category == "wall-clock-now" for h in hits)

    def test_ts_math_random_is_flagged(self, scan):
        hits = scan.scan_text("const x = Math.random();\n", "foo.test.ts")
        assert any(h.category == "unseeded-random" for h in hits)

    def test_ts_fetch_is_flagged(self, scan):
        hits = scan.scan_text("await fetch('/api/x');\n", "foo.test.tsx")
        assert any(h.category == "network" for h in hits)

    def test_ts_local_storage_is_flagged(self, scan):
        hits = scan.scan_text("localStorage.setItem('k', 'v');\n", "foo.test.js")
        assert any(h.category == "storage" for h in hits)

    def test_a_line_with_no_pattern_is_not_flagged(self, scan):
        hits = scan.scan_text("const sum = a + b;\n", "foo.test.ts")
        assert hits == []


class TestWallClockAssertionsAreNeverMitigable:
    """The two blocker rows (T1-ISO-01): a hit is always `blocker`, mitigation status never applies."""

    def test_csharp_elapsed_assertion_is_blocker(self, scan):
        text = "FakeTimeProvider provider = new();\nresult.Elapsed.Should().BeLessThan(TimeSpan.FromMilliseconds(50));\n"
        hits = scan.scan_text(text, "Foo.cs")
        assertion_hits = [h for h in hits if h.category == "wall-clock-assertion"]
        assert assertion_hits, "expected a wall-clock-assertion hit"
        assert all(h.severity == "blocker" for h in assertion_hits)
        assert all(not h.mitigated for h in assertion_hits)

    def test_ts_duration_assertion_is_blocker_even_with_fake_timers_in_scope(self, scan):
        text = "vi.useFakeTimers();\nexpect(elapsed).toBeLessThan(50); // ms\n"
        hits = scan.scan_text(text, "foo.test.ts")
        assertion_hits = [h for h in hits if h.category == "wall-clock-assertion"]
        assert assertion_hits
        assert all(h.severity == "blocker" and not h.mitigated for h in assertion_hits)


class TestMitigationDowngrade:
    """§5.5(a)'s calibration rule: a fake-timer/MSW/FakeTimeProvider marker in scope downgrades
    the *other* categories in that file to `mitigated`, reported separately from unmitigated."""

    def test_time_hit_is_mitigated_when_faketimeprovider_is_in_the_file(self, scan):
        text = "private readonly FakeTimeProvider _clock = new();\nvar t = DateTime.UtcNow;\n"
        hits = scan.scan_text(text, "Foo.cs")
        time_hits = [h for h in hits if h.category == "wall-clock-now"]
        assert time_hits and all(h.mitigated for h in time_hits)

    def test_time_hit_is_mitigated_when_use_fake_timers_is_in_the_file(self, scan):
        text = "vi.useFakeTimers();\nconst t = Date.now();\n"
        hits = scan.scan_text(text, "foo.test.ts")
        time_hits = [h for h in hits if h.category == "wall-clock-now"]
        assert time_hits and all(h.mitigated for h in time_hits)

    def test_network_hit_is_mitigated_when_msw_server_use_is_in_the_file(self, scan):
        text = "server.use(rest.get('/x', handler));\nawait fetch('/x');\n"
        hits = scan.scan_text(text, "foo.test.ts")
        net_hits = [h for h in hits if h.category == "network"]
        assert net_hits and all(h.mitigated for h in net_hits)

    def test_a_time_hit_is_unmitigated_with_no_marker_in_the_file(self, scan):
        hits = scan.scan_text("var t = DateTime.UtcNow;\n", "Foo.cs")
        time_hits = [h for h in hits if h.category == "wall-clock-now"]
        assert time_hits and all(not h.mitigated for h in time_hits)


class TestCommentsAreExcluded:
    """MoE-4 §5.5(a): "regex over the test tree, comments and strings excluded"."""

    def test_a_line_comment_is_not_scanned(self, scan):
        hits = scan.scan_text("// var t = DateTime.UtcNow;\n", "Foo.cs")
        assert hits == []

    def test_a_block_comment_is_not_scanned(self, scan):
        text = "/*\nvar t = DateTime.UtcNow;\n*/\n"
        hits = scan.scan_text(text, "Foo.cs")
        assert hits == []

    def test_code_after_a_line_comment_marker_on_the_same_line_is_still_scanned(self, scan):
        hits = scan.scan_text("Thread.Sleep(1); // deliberate\n", "Foo.cs")
        assert any(h.category == "sleep-or-delay" for h in hits)


class TestCliBehaviour:
    """Exit 0 always (findings are data, not a gate); --json for the benchmark consumer."""

    def _write(self, tmp_path, name, text):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_exit_code_is_zero_even_with_findings(self, tmp_path):
        f = self._write(tmp_path, "Foo.cs", "var t = DateTime.UtcNow;\n")
        proc = subprocess.run(
            [sys.executable, SCAN_SCRIPT, str(f)],
            cwd=tmp_path.parent, capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr

    def test_text_output_has_five_colon_separated_fields(self, tmp_path):
        f = self._write(tmp_path, "Foo.cs", "var t = DateTime.UtcNow;\n")
        proc = subprocess.run(
            [sys.executable, SCAN_SCRIPT, str(f)],
            capture_output=True, text=True, check=False,
        )
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        assert lines
        assert lines[0].count(":") >= 4

    def test_json_output_over_a_two_file_fixture_reports_wallclock_as_blocker_never_mitigated(
        self, tmp_path
    ):
        self._write(
            tmp_path, "Foo.cs",
            "FakeTimeProvider provider = new();\n"
            "result.Elapsed.Should().BeLessThan(TimeSpan.FromMilliseconds(50));\n",
        )
        self._write(
            tmp_path, "foo.test.ts",
            "vi.useFakeTimers();\nexpect(elapsed).toBeLessThan(50);\n",
        )
        proc = subprocess.run(
            [sys.executable, SCAN_SCRIPT, "--json", str(tmp_path)],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        findings = json.loads(proc.stdout)
        wallclock = [f for f in findings if f["category"] == "wall-clock-assertion"]
        assert wallclock, "expected at least one wall-clock-assertion finding"
        assert all(f["severity"] == "blocker" for f in wallclock)
        assert all(f["mitigated"] is False for f in wallclock)

    def test_scanning_a_directory_recurses_and_skips_node_modules(self, tmp_path):
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        self._write(tmp_path / "node_modules" / "pkg", "bad.ts", "Date.now();\n")
        sub = tmp_path / "src"
        sub.mkdir()
        self._write(sub, "real.ts", "Date.now();\n")

        proc = subprocess.run(
            [sys.executable, SCAN_SCRIPT, "--json", str(tmp_path)],
            capture_output=True, text=True, check=False,
        )
        findings = json.loads(proc.stdout)
        files = {f["file"] for f in findings}
        assert any("real.ts" in f for f in files)
        assert not any("node_modules" in f for f in files)


# --------------------------------------------------------------------------- red_proof.py


@pytest.fixture
def rp(load_script):
    return load_script(RED_PROOF_SCRIPT)


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.co", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _commit_file(repo, relpath, text):
    p = repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", relpath], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.co", "-c", "user.name=t",
                     "commit", "-q", "-m", "add"], cwd=repo, check=True)
    return p


class TestApplyMutation:
    def test_replaces_the_target_substring_on_the_named_line_and_returns_the_original(self, rp, tmp_path):
        f = tmp_path / "Foo.cs"
        f.write_text("line one\nGetUtcNow()\nline three\n", encoding="utf-8")

        original = rp.apply_mutation(f, 2, "GetUtcNow()", "GetLocalNow()")

        assert original == "line one\nGetUtcNow()\nline three\n"
        assert f.read_text(encoding="utf-8") == "line one\nGetLocalNow()\nline three\n"

    def test_raises_when_the_replace_string_is_not_on_that_line(self, rp, tmp_path):
        f = tmp_path / "Foo.cs"
        f.write_text("line one\nline two\n", encoding="utf-8")

        with pytest.raises(ValueError, match="not found"):
            rp.apply_mutation(f, 1, "nonexistent", "x")

    def test_raises_when_the_line_number_is_out_of_range(self, rp, tmp_path):
        f = tmp_path / "Foo.cs"
        f.write_text("only one line\n", encoding="utf-8")

        with pytest.raises(ValueError, match="out of range"):
            rp.apply_mutation(f, 99, "x", "y")


class TestJournalRoundTrip:
    def test_write_then_read_then_restore(self, rp, tmp_path):
        target = tmp_path / "Foo.cs"
        target.write_text("mutated content", encoding="utf-8")

        rp.write_journal(tmp_path, target, "original content")
        journal = rp.read_journal(tmp_path)

        assert journal is not None
        assert journal["path"] == str(target.resolve())
        assert journal["original_content"] == "original content"

        rp.restore_from_journal(journal)
        assert target.read_text(encoding="utf-8") == "original content"

    def test_no_journal_reads_as_none(self, rp, tmp_path):
        assert rp.read_journal(tmp_path) is None

    def test_delete_journal_removes_the_file(self, rp, tmp_path):
        target = tmp_path / "Foo.cs"
        target.write_text("x", encoding="utf-8")
        rp.write_journal(tmp_path, target, "x")

        rp.delete_journal(tmp_path)

        assert rp.read_journal(tmp_path) is None


class TestValidateTarget:
    def test_a_file_inside_the_repo_is_accepted(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        f = _commit_file(repo, "Foo.cs", "x\n")

        assert rp.validate_target(repo, f) is None

    def test_a_path_outside_the_repo_root_is_refused(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        outside = tmp_path / "elsewhere.cs"
        outside.write_text("x\n", encoding="utf-8")

        assert "outside" in rp.validate_target(repo, outside)

    def test_a_path_under_dot_git_is_refused(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        under_git = repo / ".git" / "config"

        assert ".git" in rp.validate_target(repo, under_git)


class TestBuildBreakHeuristic:
    def test_a_csharp_compiler_error_looks_like_a_build_break(self, rp):
        result = subprocess.CompletedProcess(args=[], returncode=1,
                                              stdout="Foo.cs(12,5): error CS1002: ; expected",
                                              stderr="")
        assert rp.looks_like_build_break(result)

    def test_a_plain_assertion_failure_does_not_look_like_a_build_break(self, rp):
        result = subprocess.CompletedProcess(args=[], returncode=1,
                                              stdout="Assert.Equal() Failure\nExpected: 1\nActual: 2",
                                              stderr="")
        assert not rp.looks_like_build_break(result)


class TestMainEndToEnd:
    """The three exit codes named in the contract, and the file is restored in all three."""

    def _run_cmd(self):
        return (
            f'{sys.executable} -c "import sys; '
            "c = open('target.txt').read(); "
            "sys.exit(1 if 'MUTATED' in c else 0)\""
        )

    def test_a_reddening_mutation_that_reverts_clean_exits_zero_and_restores(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        target = _commit_file(repo, "target.txt", "ORIGINAL\n")

        rc = rp.main([
            "--file", str(target), "--line", "1", "--replace", "ORIGINAL", "--with", "MUTATED",
            "--run", self._run_cmd(), "--root", str(repo),
        ])

        assert rc == 0
        assert target.read_text(encoding="utf-8") == "ORIGINAL\n"
        assert not (repo / ".design-tests" / "red-proof.journal.json").exists()

    def test_a_mutation_that_does_not_redden_exits_one_and_restores(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        target = _commit_file(repo, "target.txt", "ORIGINAL\n")

        rc = rp.main([
            "--file", str(target), "--line", "1", "--replace", "ORIGINAL", "--with", "HARMLESS",
            "--run", self._run_cmd(), "--root", str(repo),
        ])

        assert rc == 1
        assert target.read_text(encoding="utf-8") == "ORIGINAL\n"

    def test_a_build_break_exits_two_and_restores(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        target = _commit_file(repo, "target.txt", "ORIGINAL\n")
        build_break_cmd = (
            f'{sys.executable} -c "import sys; '
            'print(\\"Foo.cs(1,1): error CS1002: ; expected\\"); sys.exit(1)"'
        )

        rc = rp.main([
            "--file", str(target), "--line", "1", "--replace", "ORIGINAL", "--with", "MUTATED",
            "--run", build_break_cmd, "--root", str(repo),
        ])

        assert rc == 2
        assert target.read_text(encoding="utf-8") == "ORIGINAL\n"

    def test_a_dirty_target_is_refused_before_any_mutation(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        target = _commit_file(repo, "target.txt", "ORIGINAL\n")
        target.write_text("ORIGINAL\nuncommitted change\n", encoding="utf-8")

        rc = rp.main([
            "--file", str(target), "--line", "1", "--replace", "ORIGINAL", "--with", "MUTATED",
            "--run", self._run_cmd(), "--root", str(repo),
        ])

        assert rc != 0
        assert target.read_text(encoding="utf-8") == "ORIGINAL\nuncommitted change\n"

    def test_a_stale_journal_is_restored_on_start_and_the_run_refuses_to_proceed(self, rp, tmp_path):
        repo = _git_repo(tmp_path)
        target = _commit_file(repo, "target.txt", "ORIGINAL\n")
        # Simulate a crash mid-proof: the file is mutated and a journal exists, but nothing reverted.
        target.write_text("MUTATED\n", encoding="utf-8")
        rp.write_journal(repo, target, "ORIGINAL\n")

        rc = rp.main([
            "--file", str(target), "--line", "1", "--replace", "ORIGINAL", "--with", "MUTATED",
            "--run", self._run_cmd(), "--root", str(repo),
        ])

        assert rc != 0
        assert target.read_text(encoding="utf-8") == "ORIGINAL\n"
        # The journal itself is left in place; the caller must clear it before the tool proceeds.
        assert rp.read_journal(repo) is not None

        rp.delete_journal(repo)
        rc2 = rp.main([
            "--file", str(target), "--line", "1", "--replace", "ORIGINAL", "--with", "HARMLESS",
            "--run", self._run_cmd(), "--root", str(repo),
        ])
        assert rc2 == 1  # this mutation does not redden, but it *did* run — the refusal is over
