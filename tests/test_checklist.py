"""Behaviour of run-manual-checklist's checklist.py: check, new-run and report."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "features/common/skills/run-manual-checklist/scripts/checklist.py"
FIXTURES = Path(__file__).parent / "fixtures" / "checklist"


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, check=False)


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def checks_data(**over):
    data = {
        "schema": 1,
        "results-dir": "results",
        "rules": ["never pin facts"],
        "facts": {"count": {"command": "printf 3"}},
        "items": [
            {"item": "first-item", "expected-result": "works", "anchor": "docs/a.md#top",
             "negative-control": "break it"},
            {"item": "second-item", "expected-result": "also works"},
        ],
    }
    data.update(over)
    return data


@pytest.fixture(name="repo")
def repo_fixture(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"],
                ["config", "user.name", "t"], ["checkout", "-q", "-b", "feature/x"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, capture_output=True)
    (root / "docs").mkdir()
    (root / "docs/a.md").write_text("# top\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True,
                   capture_output=True)
    return root


def make_checks(repo, **over):
    return write_json(repo / "docs/checklist/checks.json", checks_data(**over))


# ---------------------------------------------------------------- check

def test_check_valid_file(repo):
    result = run_cli("check", make_checks(repo))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok: 2 items, 1 facts"


def test_check_duplicate_item_id_rejected(repo):
    items = checks_data()["items"]
    items[1]["item"] = "first-item"
    result = run_cli("check", make_checks(repo, items=items))
    assert result.returncode == 1
    assert "duplicate" in result.stderr


def test_check_missing_anchor_file_rejected(repo):
    items = checks_data()["items"]
    items[0]["anchor"] = "docs/missing.md#x"
    result = run_cli("check", make_checks(repo, items=items))
    assert result.returncode == 1
    assert "anchor" in result.stderr


def test_check_anchor_without_fragment_and_absent_anchor_ok(repo):
    items = checks_data()["items"]
    items[0]["anchor"] = "docs/a.md"
    assert run_cli("check", make_checks(repo, items=items)).returncode == 0


def test_check_empty_items_rejected(repo):
    result = run_cli("check", make_checks(repo, items=[]))
    assert result.returncode == 1
    assert "items" in result.stderr


def test_check_empty_fact_command_rejected(repo):
    result = run_cli("check", make_checks(repo, facts={"count": {"command": "  "}}))
    assert result.returncode == 1
    assert "command" in result.stderr


def test_check_reports_every_problem_with_path(repo):
    data = checks_data()
    data["items"][0]["item"] = "Bad Id"
    data["items"][1]["expected-result"] = ""
    checks = make_checks(repo, extra=1, items=data["items"])
    result = run_cli("check", checks)
    assert result.returncode == 1
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 3
    assert all(line.startswith(f"{checks}:") for line in lines)
    assert any("$.items[0].item" in line for line in lines)
    assert any("$.extra" in line for line in lines)


def test_check_usage_and_bad_json_exit_two(repo, tmp_path):
    assert run_cli("check").returncode == 2
    assert run_cli("check", tmp_path / "nope.json").returncode == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert run_cli("check", bad).returncode == 2


# --------------------------------------------------------------- new-run

def new_run(repo, *extra, checks=None, slug="smoke"):
    return run_cli("new-run", checks or make_checks(repo), "--slug", slug,
                   "--date", "2026-11-12", *extra)


def test_new_run_writes_skeleton(repo):
    result = new_run(repo)
    assert result.returncode == 0, result.stderr
    path = repo / "results/2026-11-12-smoke.json"
    lines = result.stdout.splitlines()
    assert lines[0] == str(path)
    assert "rule: never pin facts" in lines
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n") and text.startswith('{\n "run"')
    data = json.loads(text)
    assert data["run"]["date"] == "2026-11-12"
    assert data["run"]["branch"] == "feature/x"
    assert len(data["run"]["commit"]) == 40
    assert data["run"]["note"] == ""
    assert data["derived"] == {"count": "3"}
    assert data["findings-against-prior-runs"] == []
    first, second = data["items"]
    assert first == {"item": "first-item", "anchor": "docs/a.md#top",
                     "expected-result": "works", "command": "", "evidence": "",
                     "observed-result": "", "status": "", "accepted": None,
                     "acceptance-reason": ""}
    assert "anchor" not in second


def test_new_run_refuses_invalid_checks(repo):
    result = new_run(repo, checks=make_checks(repo, items=[]))
    assert result.returncode == 1
    assert not (repo / "results").exists()


def test_new_run_does_not_overwrite_without_force(repo):
    assert new_run(repo).returncode == 0
    path = repo / "results/2026-11-12-smoke.json"
    path.write_text("SENTINEL", encoding="utf-8")
    result = new_run(repo)
    assert result.returncode == 2
    assert path.read_text(encoding="utf-8") == "SENTINEL"
    assert new_run(repo, "--force").returncode == 0
    assert path.read_text(encoding="utf-8") != "SENTINEL"


def test_new_run_fact_printing_nothing_fails(repo):
    checks = make_checks(repo, facts={"empty": {"command": "printf ''"}})
    result = new_run(repo, checks=checks)
    assert result.returncode == 1
    assert "empty" in result.stderr
    assert not (repo / "results").exists()


def test_new_run_fact_zero_fails_only_with_nonzero_flag(repo):
    flagged = make_checks(repo, facts={"n": {"command": "printf 0", "nonzero": True}})
    result = new_run(repo, checks=flagged)
    assert result.returncode == 1
    assert "fact 'n': printed 0 but is marked nonzero" in result.stderr
    plain = make_checks(repo, facts={"n": {"command": "printf 0"}})
    ok = new_run(repo, checks=plain)
    assert ok.returncode == 0, ok.stderr
    assert json.loads((repo / "results/2026-11-12-smoke.json").read_text())["derived"] == {"n": "0"}


def test_new_run_fact_nonzero_exit_fails_with_stderr_tail(repo):
    cmd = "python3 -c \"import sys; print('7'); sys.stderr.write('boom-tail'); sys.exit(3)\""
    result = new_run(repo, checks=make_checks(repo, facts={"bad": {"command": cmd}}))
    assert result.returncode == 1
    assert "bad" in result.stderr and "boom-tail" in result.stderr
    assert not (repo / "results").exists()


def test_new_run_fact_runs_in_repo_root(repo):
    checks = make_checks(repo, facts={"where": {"command": "basename \"$PWD\""}})
    assert new_run(repo, checks=checks).returncode == 0
    data = json.loads((repo / "results/2026-11-12-smoke.json").read_text())
    assert data["derived"] == {"where": "repo"}


# ---------------------------------------------------------------- report

def good_item(name="first-item", **over):
    item = {"item": name, "anchor": "docs/a.md", "expected-result": "works", "command": "echo",
            "evidence": "out", "observed-result": "ok", "status": "pass", "accepted": True,
            "acceptance-reason": "fine"}
    item.update(over)
    return item


def run_data(items=None, **run_over):
    run = {"date": "2026-11-12", "branch": "b", "commit": "c", "note": ""}
    run.update(run_over)
    return {"run": run, "derived": {"count": "3"}, "findings-against-prior-runs": [],
            "items": items if items is not None else [good_item()]}


def auto_checks(tmp_path, data):
    """A checks file naming exactly the item ids the run file carries."""
    items = data.get("items", []) if isinstance(data, dict) else []
    ids = [i["item"] for i in items if isinstance(i, dict) and isinstance(i.get("item"), str)]
    entries = [{"item": ident, "expected-result": next(
        i["expected-result"] for i in items if i.get("item") == ident)}
        for ident in dict.fromkeys(ids)]
    return write_json(tmp_path / "auto-checks.json", checks_data(items=entries or [
        {"item": "placeholder", "expected-result": "x"}],
        facts={key: {"command": "printf 1"} for key in data.get("derived", {})}
        if isinstance(data, dict) else {}))


def report(tmp_path, data, *extra):
    if "--checks" not in extra:
        extra = (*extra, "--checks", auto_checks(tmp_path, data))
    return run_cli("report", write_json(tmp_path / "run.json", data), *extra)


def test_report_complete_exits_zero_with_counts(tmp_path):
    items = [good_item("a"), good_item("b")]
    result = report(tmp_path, run_data(items))
    assert result.returncode == 0, result.stderr
    assert "- pass: 2" in result.stdout.splitlines()


def test_report_counts_each_status_exactly(tmp_path):
    items = [good_item("a"), good_item("b", status="fail"), good_item("c", status="fail"),
             good_item("d", status="skipped"), good_item("e", status="substituted")]
    lines = report(tmp_path, run_data(items)).stdout.splitlines()
    for expected in ("- pass: 1", "- fail: 2", "- skipped: 1", "- substituted: 1"):
        assert expected in lines


def test_report_item_without_evidence_is_incomplete(tmp_path):
    result = report(tmp_path, run_data([good_item(evidence="")]))
    assert result.returncode == 1
    assert "evidence" in result.stderr


def test_report_evidence_may_be_a_list_of_lines(tmp_path):
    result = report(tmp_path, run_data([good_item(status="fail", evidence=["line one", "line two"])]))
    assert result.returncode != 1, result.stderr
    assert "line one" in result.stdout


@pytest.mark.parametrize("evidence", [[], ["", "  "], [1]])
def test_report_list_evidence_without_text_is_incomplete(tmp_path, evidence):
    result = report(tmp_path, run_data([good_item(evidence=evidence)]))
    assert result.returncode == 1
    assert "evidence" in result.stderr


def test_report_item_without_command_is_incomplete(tmp_path):
    result = report(tmp_path, run_data([good_item(command="")]))
    assert result.returncode == 1
    assert "command" in result.stderr


def test_report_item_without_id_is_incomplete(tmp_path):
    item = good_item()
    del item["item"]
    assert report(tmp_path, run_data([item])).returncode == 1


@pytest.mark.parametrize("status", ["skipped", "substituted"])
def test_report_skip_without_reason_is_incomplete(tmp_path, status):
    result = report(tmp_path, run_data([good_item(status=status, **{"acceptance-reason": ""})]))
    assert result.returncode == 1
    assert "reason" in result.stderr


@pytest.mark.parametrize("field", ["acceptance-reason", "acceptation-reason", "skip-reason"])
def test_report_skip_reason_from_any_accepted_field(tmp_path, field):
    item = good_item(status="skipped", **{"acceptance-reason": ""})
    item[field] = "no GPU on this host"
    result = report(tmp_path, run_data([item]))
    assert result.returncode == 0, result.stderr
    assert "no GPU on this host" in result.stdout


def test_report_status_outside_enum_is_incomplete(tmp_path):
    for status in ("pending", "partial", ""):
        assert report(tmp_path, run_data([good_item(status=status)])).returncode == 1


def test_report_accepted_must_be_null_or_bool(tmp_path):
    assert report(tmp_path, run_data([good_item(accepted="yes")])).returncode == 1


def test_report_shape_errors(tmp_path):
    assert report(tmp_path, []).returncode == 1
    assert report(tmp_path, {"run": "string", "items": []}).returncode == 1


def test_report_lists_every_fail_with_evidence(tmp_path):
    items = [good_item("a"), good_item("b", status="fail", evidence="distinctive-evidence-text"),
             good_item("c", status="fail", evidence="second-evidence")]
    result = report(tmp_path, run_data(items))
    assert result.returncode == 0, result.stderr
    assert "distinctive-evidence-text" in result.stdout
    assert "second-evidence" in result.stdout


def test_report_pending_acceptance_exits_three(tmp_path):
    result = report(tmp_path, run_data([good_item("a"), good_item("b-item", accepted=None)]))
    assert result.returncode == 3
    assert "b-item" in result.stdout


def test_report_prints_findings(tmp_path):
    data = run_data()
    data["findings-against-prior-runs"] = ["prior run missed the thing"]
    assert "prior run missed the thing" in report(tmp_path, data).stdout


def test_report_usage_and_unreadable_exit_two(tmp_path):
    assert run_cli("report").returncode == 2
    checks = auto_checks(tmp_path, run_data())
    assert run_cli("report", tmp_path / "none.json", "--checks", checks).returncode == 2
    run = write_json(tmp_path / "run.json", run_data())
    assert run_cli("report", run).returncode == 2  # --checks is required
    assert run_cli("report", run, "--checks", tmp_path / "none.json").returncode == 2


def test_report_cross_check_missing_scoped_item(tmp_path, repo):
    checks = make_checks(repo)
    result = report(tmp_path, run_data([good_item("first-item")]), "--checks", checks)
    assert result.returncode == 1
    assert "second-item" in result.stderr


def test_report_cross_check_unscoped_item_may_be_absent(tmp_path, repo):
    checks = make_checks(repo)
    data = run_data([good_item("first-item")], scope=["first-item"])
    assert report(tmp_path, data, "--checks", checks).returncode == 0


def test_report_cross_check_unknown_item(tmp_path, repo):
    checks = make_checks(repo)
    items = [good_item("first-item"), good_item("second-item"), good_item("stranger")]
    result = report(tmp_path, run_data(items), "--checks", checks)
    assert result.returncode == 1
    assert "stranger" in result.stderr


def test_report_full_cycle_from_new_run(tmp_path, repo):
    checks = make_checks(repo)
    assert new_run(repo, checks=checks).returncode == 0
    path = repo / "results/2026-11-12-smoke.json"
    data = json.loads(path.read_text())
    assert run_cli("report", path, "--checks", checks).returncode == 1  # unfilled skeleton
    for item in data["items"]:
        item.update({"command": "echo", "evidence": "e", "observed-result": "o",
                     "status": "pass", "accepted": True})
    path.write_text(json.dumps(data), encoding="utf-8")
    assert run_cli("report", path, "--checks", checks).returncode == 0
    data["items"][0]["accepted"] = None
    path.write_text(json.dumps(copy.deepcopy(data)), encoding="utf-8")
    assert run_cli("report", path, "--checks", checks).returncode == 3


# -------------------------------------------------------- historic runs

@pytest.mark.parametrize(("name", "code"), [
    # `full-mcp-surface` is substituted and carries no reason in any accepted field.
    ("2026-11-11-2.6.0-decision-recording.json", 1),
    # top-level list, the pre-schema shape.
    ("2026-08-13-state-1-10-1.json", 1),
    # well-formed, every item answered.
    ("2026-10-22-2.0.0-post-rename.json", 0),
])
def test_historic_runs(name, code, tmp_path):
    run = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    result = run_cli("report", FIXTURES / name, "--checks", auto_checks(tmp_path, run))
    assert result.returncode == code, result.stderr


# ------------------------------------------------------- never a traceback

def assert_clean_refusal(result):
    assert result.returncode == 1, result.stdout
    assert "Traceback" not in result.stderr
    assert result.stderr.strip()


@pytest.mark.parametrize("scope", [5, "first-item", ["first-item", 1], {"a": 1}])
def test_report_scope_must_be_a_list_of_strings(tmp_path, repo, scope):
    data = run_data([good_item("first-item")], scope=scope)
    assert_clean_refusal(report(tmp_path, data, "--checks", make_checks(repo)))


@pytest.mark.parametrize("status", [[1], {"a": 1}, 5, None])
def test_report_non_string_status_is_incomplete(tmp_path, status):
    assert_clean_refusal(report(tmp_path, run_data([good_item(status=status)])))


@pytest.mark.parametrize("bad", [{"items": 5}, {"items": ["a"]}, {"items": [{"item": ["a"]}]}])
def test_report_malformed_checks_file_is_refused(tmp_path, repo, bad):
    checks = make_checks(repo, **bad)
    assert_clean_refusal(report(tmp_path, run_data(), "--checks", checks))


# ------------------------------------------------------------- rejected

def test_report_rejected_item_is_listed_and_exits_four(tmp_path):
    items = [good_item("a"), good_item("b-item", status="fail", accepted=False,
                                       **{"acceptance-reason": "tracked nowhere yet"})]
    result = report(tmp_path, run_data(items))
    assert result.returncode == 4, result.stderr
    out = result.stdout.splitlines()
    assert "## Rejected" in out
    assert "- b-item: tracked nowhere yet" in out


def test_report_pending_wins_over_rejected(tmp_path):
    items = [good_item("a", accepted=None), good_item("b-item", accepted=False)]
    assert report(tmp_path, run_data(items)).returncode == 3


def test_report_without_rejections_lists_none(tmp_path):
    out = report(tmp_path, run_data()).stdout.splitlines()
    assert out[out.index("## Rejected") + 2] == "none"


# ------------------------------------------------- duplicates and scope

def test_report_duplicate_run_item_ids_are_incomplete(tmp_path, repo):
    items = [good_item("first-item"), good_item("first-item"), good_item("second-item")]
    result = report(tmp_path, run_data(items), "--checks", make_checks(repo))
    assert result.returncode == 1
    assert "duplicate" in result.stderr


def test_report_scope_naming_an_id_not_in_checks_is_refused(tmp_path, repo):
    data = run_data([good_item("first-item")], scope=["first-item", "ghost-item"])
    result = report(tmp_path, data, "--checks", make_checks(repo))
    assert result.returncode == 1
    assert "ghost-item" in result.stderr


def test_report_run_item_outside_scope_is_refused(tmp_path, repo):
    data = run_data([good_item("first-item"), good_item("second-item")], scope=["first-item"])
    result = report(tmp_path, data, "--checks", make_checks(repo))
    assert result.returncode == 1
    assert "second-item" in result.stderr and "scope" in result.stderr


def test_report_exact_scope_passes(tmp_path, repo):
    data = run_data([good_item("second-item", **{"expected-result": "also works"})], scope=["second-item"])
    assert report(tmp_path, data, "--checks", make_checks(repo)).returncode == 0


# ---------------------------------------------------------- path escape

@pytest.mark.parametrize("slug", ["../../pwn", "a/b", "Bad Slug", ""])
def test_new_run_slug_must_be_a_kebab_id(repo, slug):
    result = new_run(repo, slug=slug)
    assert result.returncode == 2
    assert "slug" in result.stderr
    assert not (repo / "results").exists()
    assert not list(repo.parent.glob("**/pwn*"))


@pytest.mark.parametrize("date", ["../x", "2026-13-01", "20261112", "2026-11-12/.."])
def test_new_run_date_must_be_iso(repo, date):
    result = run_cli("new-run", make_checks(repo), "--slug", "smoke", "--date", date)
    assert result.returncode == 2
    assert "date" in result.stderr
    assert not (repo / "results").exists()


@pytest.mark.parametrize("results_dir", ["../x", "results/../../x", "a/../../x"])
def test_results_dir_escaping_the_repo_is_rejected(repo, results_dir):
    checks = make_checks(repo, **{"results-dir": results_dir})
    check = run_cli("check", checks)
    assert check.returncode == 1
    assert "results-dir" in check.stderr
    assert new_run(repo, checks=checks).returncode == 1
    assert not (repo.parent / "x").exists()


# ----------------------------------------------------- the shipped example

def test_shipped_example_checks_file_is_valid():
    example = ROOT / "features/common/skills/run-manual-checklist/examples/checks.json"
    result = run_cli("check", example, "--repo", ROOT)
    assert result.returncode == 0, result.stderr


def test_schema_must_be_the_integer_one(repo):
    for bad in (1.0, True, "1"):
        assert run_cli("check", make_checks(repo, schema=bad)).returncode == 1

@pytest.mark.parametrize("anchor", ["../outside.md", "docs", "docs/link.md"])
def test_anchor_must_resolve_to_file_inside_repo(repo, anchor):
    outside = repo.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (repo / "docs/link.md").symlink_to(outside)
    items = checks_data()["items"]
    items[0]["anchor"] = anchor
    result = run_cli("check", make_checks(repo, items=items))
    assert_clean_refusal(result)
    assert "anchor file not found" in result.stderr


@pytest.mark.parametrize("scope", [[], None, [""], ["Bad Id"]])
def test_present_scope_must_name_items(tmp_path, scope):
    result = report(tmp_path, run_data(scope=scope))
    assert_clean_refusal(result)
    assert "scope" in result.stderr


@pytest.mark.parametrize("observed", ["", "  ", None])
def test_report_requires_observed_result(tmp_path, observed):
    result = report(tmp_path, run_data([good_item(**{"observed-result": observed})]))
    assert_clean_refusal(result)
    assert "observed-result" in result.stderr


def test_accepted_failure_requires_reason(tmp_path):
    result = report(tmp_path, run_data([
        good_item(status="fail", **{"acceptance-reason": "  "})]))
    assert_clean_refusal(result)
    assert "reason" in result.stderr


@pytest.mark.parametrize("field", ["acceptance-reason", "acceptation-reason", "skip-reason"])
def test_accepted_failure_allows_reason_aliases(tmp_path, field):
    item = good_item(status="fail", **{"acceptance-reason": "", field: "tracked defect"})
    assert report(tmp_path, run_data([item])).returncode == 0


@pytest.mark.parametrize("change", ["expectation", "fact-added", "fact-removed"])
def test_report_detects_changed_checks(tmp_path, repo, change):
    checks = make_checks(repo)
    assert new_run(repo, checks=checks).returncode == 0
    data = json.loads((repo / "results/2026-11-12-smoke.json").read_text())
    for item in data["items"]:
        item.update(command="echo", evidence="output", status="pass", accepted=True,
                    **{"observed-result": "ok"})
    updated = json.loads(checks.read_text())
    if change == "expectation":
        updated["items"][0]["expected-result"] = "new expectation"
    elif change == "fact-added":
        updated["facts"]["new-fact"] = {"command": "printf 1"}
    else:
        updated["facts"] = {}
    write_json(checks, updated)
    result = report(tmp_path, data, "--checks", checks)
    assert_clean_refusal(result)
    assert ("expected-result" if change == "expectation" else "derived") in result.stderr


def test_empty_scope_cannot_complete_an_empty_run(tmp_path, repo):
    result = report(tmp_path, run_data([], scope=[]), "--checks", make_checks(repo))
    assert_clean_refusal(result)
    assert "scope" in result.stderr


def test_standalone_checklist_ignores_git_repository_overrides(repo, tmp_path, monkeypatch):
    script = tmp_path / "installed/checklist.py"
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "missing.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))
    result = subprocess.run(
        [sys.executable, str(script), "new-run", str(make_checks(repo)), "--slug", "standalone",
         "--date", "2026-11-12"], capture_output=True, text=True, check=False, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    run = json.loads((repo / "results/2026-11-12-standalone.json").read_text())
    assert run["run"]["branch"] == "feature/x"
    assert len(run["run"]["commit"]) == 40
    assert run["derived"] == {"count": "3"}
