"""Review rules store: base-ref loading, lifecycle verbs, citation checks, scope and the lane cap."""
from __future__ import annotations

import json
import subprocess

import pytest

SCRIPT_RELPATH = "features/common/skills/review-flow/scripts/review_rules.py"
RULES_PATH = ".ai-badger/review/rules.json"


@pytest.fixture(name="rr")
def _rules_module(load_script):
    return load_script(SCRIPT_RELPATH)


@pytest.fixture(name="model")
def _model(rr):
    return rr.model


def _origin(n=1, author="alice", association="MEMBER", thread=None):
    return {"pr": n, "thread_url": thread or f"https://example.test/pr/{n}#t{author}",
            "author": author, "association": association, "quote": "do not flag this"}


def _rule(n, status="active", activated_by="maintainer", kinds=("null_deref",),
          paths=("src/*.py",), action="suppress", origins=None, **over):
    data = {
        "id": f"R-{n}", "status": status, "statement": f"rule {n}",
        "applies": {"kinds": list(kinds), "paths": list(paths), "symbols": []},
        "effect": {"action": action, "to": None, "ground": "rule"},
        "origins": origins or [_origin()],
        "activated_by": activated_by if status != "proposed" else None,
        "citation": None,
    }
    data.update(over)
    return data


def _file(rules=(), facts=()):
    return {"schema_version": 1, "rules": list(rules), "facts": list(facts)}


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture(name="repo")
def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.test")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    return root


def _commit(root, files, message="c"):
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _parse(rr, data):
    return rr.model.RulesFile.model_validate(data)


def _reply(**over):
    data = {"pr": 7, "thread_url": "https://example.test/pr/7#t1", "author": "alice",
            "association": "MEMBER", "quote": "we never flag this",
            "statement": "Do not flag null checks in src",
            "applies": {"kinds": ["null_deref"], "paths": ["src/*.py"], "symbols": []},
            "effect": {"action": "suppress", "to": None, "ground": "rule"}}
    data.update(over)
    return data


# ------------------------------------------------------------------ load

def test_base_ref_rules_win_over_head_edit(rr, repo):
    base = _commit(repo, {RULES_PATH: json.dumps(_file([_rule(1)]))})
    _commit(repo, {RULES_PATH: json.dumps(_file([_rule(1), _rule(2)]))}, "head edit")
    (repo / RULES_PATH).write_text(json.dumps(_file([_rule(1), _rule(2), _rule(3)])))
    loaded = rr.load(repo, base)
    assert [rule.id for rule in loaded.rules] == ["R-1"]


def test_missing_rules_file_at_base_is_empty(rr, repo):
    base = _commit(repo, {"README.md": "x"})
    _commit(repo, {RULES_PATH: json.dumps(_file([_rule(1)]))}, "head adds")
    loaded = rr.load(repo, base)
    assert loaded.rules == [] and loaded.facts == []


def test_invalid_rules_json_raises_rules_file_invalid(rr, repo):
    base = _commit(repo, {RULES_PATH: "{not json"})
    with pytest.raises(rr.RulesFileInvalid) as caught:
        rr.load(repo, base)
    assert caught.value.path == RULES_PATH and "json" in caught.value.reason.lower()


def test_invalid_model_raises_rules_file_invalid(rr, repo):
    base = _commit(repo, {RULES_PATH: json.dumps({"schema_version": 2, "rules": [], "facts": []})})
    with pytest.raises(rr.RulesFileInvalid):
        rr.load(repo, base)


def test_invalid_conflict_markers_raise(rr, repo):
    text = "<<<<<<< HEAD\n" + json.dumps(_file()) + "\n=======\n{}\n>>>>>>> x\n"
    base = _commit(repo, {RULES_PATH: text})
    with pytest.raises(rr.RulesFileInvalid) as caught:
        rr.load(repo, base)
    assert "conflict" in caught.value.reason


def test_unknown_base_ref_is_invalid_not_empty(rr, repo):
    _commit(repo, {"README.md": "x"})
    with pytest.raises(rr.RulesFileInvalid):
        rr.load(repo, "no-such-ref")


def test_load_uses_injected_runner(rr, tmp_path):
    seen = []

    def run(args, cwd):
        seen.append((args, cwd))
        return 0, json.dumps(_file([_rule(1)])), ""

    loaded = rr.load(tmp_path, "origin/main", run=run)
    assert [rule.id for rule in loaded.rules] == ["R-1"]
    assert seen == [(["git", "show", f"origin/main:{RULES_PATH}"], tmp_path)]


# ------------------------------------------------------------------ save

def test_save_round_trips_deterministically(rr, tmp_path):
    rules_file = _parse(rr, _file([_rule(1), _rule(2, kinds=("perf",))]))
    path = rr.save(tmp_path, rules_file)
    first = path.read_text(encoding="utf-8")
    rr.save(tmp_path, rules_file)
    assert path == tmp_path / RULES_PATH
    assert path.read_text(encoding="utf-8") == first and first.endswith("\n")
    assert _parse(rr, json.loads(first)) == rules_file
    assert '"to": null' not in first


# ------------------------------------------------------------------ propose and lifecycle

def test_propose_adds_proposed_rule_with_next_id(rr):
    start = _parse(rr, _file([_rule(1), _rule(4)]))
    updated, rule = rr.propose(start, _reply())
    assert rule.id == "R-5" and rule.status == "proposed" and rule.activated_by is None
    assert [r.id for r in updated.rules] == ["R-1", "R-4", "R-5"]
    assert len(start.rules) == 2


def test_proposed_rule_absent_from_lane_rules(rr):
    updated, _ = rr.propose(_parse(rr, _file()), _reply())
    assert rr.lane_rules(updated, ["src/a.py"], ["null_deref"]).rules == []


@pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR",
                                         "MANNEQUIN"])
def test_non_collaborator_reply_never_proposes(rr, association):
    start = _parse(rr, _file())
    with pytest.raises(rr.RuleRefused, match="cannot teach"):
        rr.propose(start, _reply(association=association))
    assert start.rules == []


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_collaborator_replies_propose(rr, association):
    _, rule = rr.propose(_parse(rr, _file()), _reply(association=association))
    assert rule.origins[0].association == association


def test_active_via_maintainer_confirm(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    confirmed = rr.confirm(updated, rule.id, "carol")
    only = confirmed.rules[0]
    assert only.status == "active" and only.activated_by == "maintainer"
    assert [r.id for r in rr.lane_rules(confirmed, ["src/a.py"], ["null_deref"]).rules] == ["R-1"]


def test_confirm_refuses_blank_maintainer_and_unknown_rule(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    with pytest.raises(rr.RuleRefused):
        rr.confirm(updated, rule.id, "  ")
    with pytest.raises(rr.RuleRefused):
        rr.confirm(updated, "R-9", "carol")


def test_confirm_refuses_already_active(rr):
    with pytest.raises(rr.RuleRefused):
        rr.confirm(_parse(rr, _file([_rule(1)])), "R-1", "carol")


def test_active_via_two_independent_threads(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    updated = rr.add_origin(updated, rule.id, _reply(
        pr=8, thread_url="https://example.test/pr/8#t2", author="bob"))
    activated = rr.activate_by_threads(updated, rule.id)
    only = activated.rules[0]
    assert only.status == "active" and only.activated_by == "threads" and len(only.origins) == 2


def test_same_author_two_threads_not_independent(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    updated = rr.add_origin(updated, rule.id, _reply(
        pr=8, thread_url="https://example.test/pr/8#t2", author="alice"))
    with pytest.raises(rr.RuleRefused):
        rr.activate_by_threads(updated, rule.id)
    assert updated.rules[0].status == "proposed"


def test_same_thread_two_authors_not_independent(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    updated = rr.add_origin(updated, rule.id, _reply(author="bob"))
    with pytest.raises(rr.RuleRefused):
        rr.activate_by_threads(updated, rule.id)


def test_single_origin_is_not_enough_for_threads(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    with pytest.raises(rr.RuleRefused):
        rr.activate_by_threads(updated, rule.id)


def test_add_origin_refuses_non_collaborator(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    with pytest.raises(rr.RuleRefused):
        rr.add_origin(updated, rule.id, _reply(association="NONE", author="bob",
                                               thread_url="https://example.test/x"))


def test_retire_keeps_rule_and_removes_it_from_lanes(rr):
    start = _parse(rr, _file([_rule(1), _rule(2, kinds=("perf",))]))
    retired = rr.retire(start, "R-1")
    assert [(r.id, r.status) for r in retired.rules] == [("R-1", "retired"), ("R-2", "active")]
    assert retired.rules[0].activated_by == "maintainer"
    assert rr.lane_rules(retired, ["src/a.py"], ["null_deref"]).rules == []


def test_retire_refuses_proposed_and_unknown(rr):
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    with pytest.raises(rr.RuleRefused, match="only an active"):
        rr.retire(updated, rule.id)
    with pytest.raises(rr.RuleRefused):
        rr.retire(updated, "R-9")


def test_ids_never_reused_after_retire(rr):
    start = rr.retire(_parse(rr, _file([_rule(1), _rule(5)])), "R-5")
    _, rule = rr.propose(start, _reply())
    assert rule.id == "R-6"


# ------------------------------------------------------------------ citation

def _cite_setup(rr, repo, body="alpha\nbeta needle gamma\ndelta\n"):
    _commit(repo, {"src/a.py": body})
    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    return updated, rule.id


def test_active_via_script_verified_citation(rr, repo):
    updated, rid = _cite_setup(rr, repo)
    activated = rr.verify_citation(repo, updated, rid, "src/a.py", 2, 3, "needle gamma", base_ref="HEAD")
    only = activated.rules[0]
    assert only.status == "active" and only.activated_by == "citation"
    assert (only.citation.path, only.citation.start, only.citation.end) == ("src/a.py", 2, 3)


def test_refuse_citation_wrong_quote(rr, repo):
    updated, rid = _cite_setup(rr, repo)
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "src/a.py", 2, 2, "absent text", base_ref="HEAD")
    assert updated.rules[0].status == "proposed"


def test_refuse_citation_quote_on_other_line(rr, repo):
    updated, rid = _cite_setup(rr, repo)
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "src/a.py", 1, 1, "needle", base_ref="HEAD")


def test_refuse_citation_range_past_end_of_file(rr, repo):
    updated, rid = _cite_setup(rr, repo)
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "src/a.py", 2, 9, "needle", base_ref="HEAD")


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", "/etc/hosts"])
def test_refuse_citation_outside_repo(rr, repo, path):
    (repo.parent / "outside.txt").write_text("needle\n", encoding="utf-8")
    updated, rid = _cite_setup(rr, repo)
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, path, 1, 1, "needle", base_ref="HEAD")


def test_refuse_citation_symlink_escaping_repo(rr, repo):
    (repo.parent / "secret.txt").write_text("needle\n", encoding="utf-8")
    updated, rid = _cite_setup(rr, repo)
    (repo / "src" / "link.txt").symlink_to(repo.parent / "secret.txt")
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "src/link.txt", 1, 1, "needle", base_ref="HEAD")


def test_refuse_citation_through_symlinked_directory(rr, repo):
    outside = repo.parent / "outdir"
    outside.mkdir()
    (outside / "f.txt").write_text("needle\n", encoding="utf-8")
    updated, rid = _cite_setup(rr, repo)
    (repo / "linkdir").symlink_to(outside, target_is_directory=True)
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "linkdir/f.txt", 1, 1, "needle", base_ref="HEAD")


def test_refuse_citation_missing_file_and_blank_quote(rr, repo):
    updated, rid = _cite_setup(rr, repo)
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "src/none.py", 1, 1, "needle", base_ref="HEAD")
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(repo, updated, rid, "src/a.py", 2, 2, "   ", base_ref="HEAD")


# ------------------------------------------------------------------ conflict, scope, cap

def test_conflicting_rules_excluded(rr):
    rules_file = _parse(rr, _file([
        _rule(1, action="require"), _rule(2, action="suppress"),
        _rule(3, kinds=("perf",), paths=("docs/*.md",)),
    ]))
    result = rr.lane_rules(rules_file, ["src/a.py", "docs/x.md"], ["null_deref", "perf"])
    assert [rule.id for rule in result.rules] == ["R-3"]
    assert result.conflicting == ["R-1", "R-2"] and result.dropped == 0


def test_matches_requires_kind_path_and_symbol(rr, model):
    applies = model.Applies(kinds=["null_deref"], paths=["src/*.py"], symbols=["charge*"])

    def finding(kind="null_deref", path="src/a.py", symbol="charge_card"):
        return model.Finding(
            fingerprint=model.fingerprint_of(kind, path, symbol), lanes=["qa"], source="lane",
            kind=kind, severity="major", confidence="high",
            location={"path": path, "start": 1, "end": 2, "symbol": symbol}, in_diff=True,
            title="t", reason="r", evidence=[],
            agent={"repro": "", "context": "", "fix": ""}, ac_refs=[], tags=[])

    assert rr.matches(applies, finding())
    assert not rr.matches(applies, finding(kind="perf"))
    assert not rr.matches(applies, finding(path="lib/a.py"))
    assert not rr.matches(applies, finding(symbol="refund"))
    assert not rr.matches(applies, finding(kind="other"))
    open_symbols = model.Applies(kinds=["null_deref"], paths=["src/*.py"])
    assert rr.matches(open_symbols, finding(symbol="anything"))


def test_lane_rules_filters_by_paths_and_kinds(rr):
    rules_file = _parse(rr, _file([
        _rule(1, kinds=("perf",), paths=("src/*.py",)),
        _rule(2, kinds=("null_deref",), paths=("docs/*.md",)),
        _rule(3, kinds=("null_deref", "perf"), paths=("src/*.py",)),
    ]))
    result = rr.lane_rules(rules_file, ["src/a.py"], ["null_deref"])
    assert [rule.id for rule in result.rules] == ["R-3"]


def test_cap_31_active_returns_30_and_dropped_1(rr):
    rules = [_rule(n, action="suppress") for n in range(1, 32)]
    result = rr.lane_rules(_parse(rr, _file(rules)), ["src/a.py"], ["null_deref"])
    assert len(result.rules) == 30 == rr.LANE_RULE_CAP
    assert result.dropped == 1
    assert [rule.id for rule in result.rules] == [f"R-{n}" for n in range(1, 31)]


def test_cap_counts_only_active_non_conflicting(rr):
    rules = [_rule(n) for n in range(1, 31)]
    rules.append(_rule(31, status="retired"))
    rules.append(_rule(32, status="proposed"))
    result = rr.lane_rules(_parse(rr, _file(rules)), ["src/a.py"], ["null_deref"])
    assert len(result.rules) == 30 and result.dropped == 0


def test_lane_rules_order_is_by_id_not_file_order(rr):
    rules_file = _parse(rr, _file([_rule(2), _rule(10), _rule(11)]))
    result = rr.lane_rules(rules_file, ["src/a.py"], ["null_deref"])
    assert [rule.id for rule in result.rules] == ["R-2", "R-10", "R-11"]


# ------------------------------------------------------------------ head diff

def test_head_diff_touches_rules(rr):
    assert rr.head_diff_touches_rules(["src/a.py", RULES_PATH])
    assert rr.head_diff_touches_rules(["./" + RULES_PATH])
    assert not rr.head_diff_touches_rules(["src/a.py", "docs/review/rules.json"])
    assert not rr.head_diff_touches_rules([])


# ------------------------------------------------------------------ git environment

def test_load_answers_for_repo_root_when_git_dir_is_exported(rr, repo, tmp_path, monkeypatch):
    """A hook exports GIT_DIR; the default runner must still read the repo it was given."""
    base = _commit(repo, {RULES_PATH: json.dumps(_file([_rule(1)]))})
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    loaded = rr.load(repo, base)
    assert [rule.id for rule in loaded.rules] == ["R-1"]


def test_citation_quote_only_in_the_checkout_is_refused(rr, repo):
    """The reviewed checkout is the PR head; a citation must hold at the base commit."""
    updated, rid = _cite_setup(rr, repo, body="alpha\nbeta\ndelta\n")
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, {"src/a.py": "alpha\nbeta needle gamma\ndelta\n"}, "head adds the quote")
    with pytest.raises(rr.RuleRefused, match="quote not found"):
        rr.verify_citation(repo, updated, rid, "src/a.py", 2, 2, "needle", base_ref=base)
    assert updated.rules[0].status == "proposed"


def test_citation_quote_at_base_passes_after_the_checkout_drops_it(rr, repo):
    updated, rid = _cite_setup(rr, repo)
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "src" / "a.py").write_text("rewritten\n", encoding="utf-8")
    activated = rr.verify_citation(repo, updated, rid, "src/a.py", 2, 3, "needle gamma",
                                   base_ref=base)
    assert activated.rules[0].status == "active"
    assert activated.rules[0].citation.path == "src/a.py"


def test_citation_reads_through_the_injected_runner_at_the_base_ref(rr, tmp_path):
    seen = []

    def run(args, cwd):
        seen.append((args, cwd))
        return 0, "one\ntwo needle\n", ""

    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    activated = rr.verify_citation(tmp_path, updated, rule.id, "src/a.py", 2, 2, "needle",
                                   base_ref="origin/main", run=run)
    assert activated.rules[0].status == "active"
    assert seen == [(["git", "show", "origin/main:src/a.py"], tmp_path)]


@pytest.mark.parametrize("ref", ["", "-p", "--output=/tmp/x"])
def test_citation_refuses_a_base_ref_git_would_read_as_an_option(rr, tmp_path, ref):
    def run(args, cwd):
        raise AssertionError(f"git ran with {args} in {cwd}")

    updated, rule = rr.propose(_parse(rr, _file()), _reply())
    with pytest.raises(rr.RuleRefused):
        rr.verify_citation(tmp_path, updated, rule.id, "src/a.py", 1, 1, "needle",
                           base_ref=ref, run=run)


def test_git_env_drops_every_location_variable_and_keeps_the_rest(rr):
    names = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
             "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX",
             "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")
    env = rr.git_env({**{name: "/elsewhere" for name in names}, "PATH": "/usr/bin",
                      "GIT_AUTHOR_NAME": "kept"})
    assert env == {"PATH": "/usr/bin", "GIT_AUTHOR_NAME": "kept"}
