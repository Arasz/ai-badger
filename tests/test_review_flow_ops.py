"""Review-flow machine: transition table over all phase pairs, guards, history, merge, verdict."""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest

SCRIPT_RELPATH = "features/common/skills/review-flow/scripts/review_flow.py"
HEAD = "0123456789abcdef0123456789abcdef01234567"
HEAD2 = "fedcba9876543210fedcba9876543210fedcba98"
DIGEST = "a" * 64
NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
LANES = ("business", "qa", "architecture", "quality")

# Independent of review_flow.TRANSITIONS on purpose: an extra edge in the table must go red here.
EXPECTED_EDGES = {
    ("context", "change_model"),
    ("change_model", "lanes"),
    ("lanes", "integrate"),
    ("integrate", "global_scope"),
    ("global_scope", "result"),
    ("result", "published"),
    ("published", "awaiting_author"),
    ("awaiting_author", "reply_analysis"),
    ("reply_analysis", "closed"),
}
PHASES = ("context", "change_model", "lanes", "integrate", "global_scope", "result",
          "published", "awaiting_author", "reply_analysis", "closed")


@pytest.fixture(name="rf")
def _review_flow(load_script):
    return load_script(SCRIPT_RELPATH)


def finding(rf, kind="null_deref", path="src/pay/charge.py", symbol="charge", start=40,
            end=52, severity="major", lanes=("qa",), title="Missing null check",
            disposition=None, evidence=None):
    return rf.model.Finding.model_validate({
        "fingerprint": rf.model.fingerprint_of(kind, path, symbol),
        "lanes": list(lanes), "source": "lane", "kind": kind, "severity": severity,
        "confidence": "high",
        "location": {"path": path, "start": start, "end": end, "symbol": symbol},
        "in_diff": True, "title": title, "reason": "The lookup can return None.",
        "evidence": evidence or [{"grade": "READ", "ref": f"{path}:{start}"}],
        "agent": {"repro": "", "context": "", "fix": ""}, "ac_refs": [], "tags": [],
        "disposition": disposition,
    })


def two_findings(rf, disposed):
    disposition = {"action": "keep"} if disposed else None
    return [finding(rf, disposition=disposition),
            finding(rf, kind="style", path="src/pay/util.py", symbol="<module>", start=1, end=1,
                    severity="nit", lanes=("quality",), title="Mixed quotes",
                    disposition=disposition)]


def flow_at(rf, phase, findings=None, lane_status=None, rounds_before=0):
    """A valid flow whose last round sits at `phase`, with two findings and four lanes."""
    rank = rf.model.PHASE_RANK[rf.model.Phase(phase)]
    lanes_done = rank >= rf.model.PHASE_RANK[rf.model.Phase.LANES]
    runs = {lane: {"status": "done" if lanes_done else "pending", "error": None} for lane in LANES}
    for lane, status in (lane_status or {}).items():
        runs[lane] = {"status": status, "error": "worker timed out" if status == "failed" else None}
    disposed = rank >= rf.model.PHASE_RANK[rf.model.Phase.GLOBAL_SCOPE]
    if findings is None:
        findings = two_findings(rf, disposed)
    published = rank >= rf.model.PHASE_RANK[rf.model.Phase.PUBLISHED]
    earlier = [{"n": i + 1, "head_sha": f"{i + 1:07x}", "phase": "reply_analysis",
                "rules_digest": DIGEST, "lanes": {lane: {"status": "done"} for lane in LANES},
                "findings": [], "replies": [], "published": publication()}
               for i in range(rounds_before)]
    last = {"n": rounds_before + 1, "head_sha": HEAD, "phase": phase,
            "rules_digest": DIGEST if disposed else None, "lanes": runs,
            "findings": [f.model_dump(mode="json") for f in findings], "replies": [],
            "published": publication() if published else None}
    rounds = [*earlier, last]
    return rf.model.ReviewFlow.model_validate({
        "schema_version": 1, "flow_id": "rf-1", "repo": "octo/widgets", "pr": 7,
        "issue_refs": [], "ac_source": "absent", "acs": [], "rounds": rounds,
        "history": [entry for r in rounds for entry in chain(r["n"], r["phase"])]})


def chain(round_n, phase):
    """History entries that open round `round_n` and walk it to `phase`."""
    steps = PHASES[:PHASES.index(phase) + 1]
    return [{"round": round_n, "source": source, "target": target,
             "at": "2026-11-18T11:00:00Z", "trigger": f"to {target}"}
            for source, target in zip((None, *steps[:-1]), steps)]


def publication():
    return {"review_id": 11, "summary_comment_id": 12, "event": "COMMENT",
            "at": "2026-11-18T12:00:00Z"}


def rules_file(rf, facts=(), rules=()):
    return rf.model.RulesFile.model_validate(
        {"schema_version": 1, "facts": list(facts), "rules": list(rules)})


def fact(fact_id, grade, kinds=("null_deref",), paths=("src/pay/*",), action="suppress",
         to=None, ground="fact_contradicts"):
    return {"id": fact_id, "statement": f"{fact_id} statement", "grade": grade,
            "evidence_ref": "docs/x.md", "applies": {"kinds": list(kinds), "paths": list(paths)},
            "effect": {"action": action, "to": to, "ground": ground}}


def rule(rule_id, status, kinds=("null_deref",), paths=("src/pay/*",)):
    origin = {"pr": 1, "thread_url": "https://github.com/o/r/pull/1#r1", "author": "alice",
              "association": "MEMBER", "quote": "fine"}
    return {"id": rule_id, "status": status, "statement": f"{rule_id} statement",
            "applies": {"kinds": list(kinds), "paths": list(paths)},
            "effect": {"action": "suppress", "ground": "rule"}, "origins": [origin],
            "activated_by": None if status == "proposed" else "maintainer"}


def refused(rf, code, call, *args, **kwargs):
    with pytest.raises(rf.TransitionRefused) as caught:
        call(*args, **kwargs)
    assert caught.value.code == code, str(caught.value)
    return caught.value


# --- ac1: transitions over every phase pair -------------------------------------------------


@pytest.mark.parametrize("source,target", list(itertools.product(PHASES, PHASES)))
def test_every_undeclared_transition_refused(rf, source, target):
    flow = flow_at(rf, source)
    pub = rf.model.Publication.model_validate(publication()) if target == "published" else None
    if (source, target) in EXPECTED_EDGES:
        moved = rf.advance(flow, rf.model.Phase(target), "test", NOW, publication=pub)
        assert moved.rounds[-1].phase.value == target
    else:
        refused(rf, "undeclared_transition", rf.advance, flow, rf.model.Phase(target), "test",
                NOW, publication=pub)


def test_history_records_trigger_and_round(rf):
    flow = flow_at(rf, "context", rounds_before=1)
    flow = rf.advance(flow, rf.model.Phase.CHANGE_MODEL, "change model written", NOW)
    flow = rf.advance(flow, rf.model.Phase.LANES, "lanes dispatched", NOW)
    entries = [(t.round, t.source.value, t.target.value, t.trigger, t.at)
               for t in flow.history[-2:]]
    assert entries == [
        (2, "context", "change_model", "change model written", "2026-11-18T12:00:00+00:00"),
        (2, "change_model", "lanes", "lanes dispatched", "2026-11-18T12:00:00+00:00"),
    ]
    assert flow.rounds[0].phase.value == "reply_analysis"


def test_refusal_leaves_state_and_revision_unchanged(rf):
    flow = flow_at(rf, "lanes", lane_status={"qa": "pending"})
    flow = flow.model_copy(update={"history": [rf.model.Transition(
        round=1, source=rf.model.Phase.CHANGE_MODEL, target=rf.model.Phase.LANES,
        at="2026-11-18T11:00:00Z", trigger="lanes dispatched")]})
    before = flow.model_dump(mode="json")
    refused(rf, "lanes_pending", rf.advance, flow, rf.model.Phase.INTEGRATE, "integrate", NOW)
    refused(rf, "undeclared_transition", rf.advance, flow, rf.model.Phase.RESULT, "skip", NOW)
    assert flow.model_dump(mode="json") == before
    assert len(flow.history) == 1


def test_naive_now_and_blank_trigger_are_refused(rf):
    flow = flow_at(rf, "context")
    with pytest.raises(ValueError):
        rf.advance(flow, rf.model.Phase.CHANGE_MODEL, "go", datetime(2026, 11, 18, 12))
    with pytest.raises(ValueError):
        rf.advance(flow, rf.model.Phase.CHANGE_MODEL, "  ", NOW)


# --- guards -------------------------------------------------------------------------------


def test_guard_ids_are_unique_and_each_names_its_operation(rf):
    ids = [guard.id for guard in rf.GUARDS]
    assert len(ids) == len(set(ids))
    assert {guard.op for guard in rf.GUARDS} <= set(rf.OPERATIONS)


def test_lanes_pending_at_integrate(rf):
    flow = flow_at(rf, "lanes", lane_status={"architecture": "pending"})
    error = refused(rf, "lanes_pending", rf.advance, flow, rf.model.Phase.INTEGRATE, "go", NOW)
    assert "architecture" in str(error)
    failed = flow_at(rf, "lanes", lane_status={"architecture": "failed"})
    assert rf.advance(failed, rf.model.Phase.INTEGRATE, "go", NOW).rounds[-1].phase.value \
        == "integrate"


def test_submit_wrong_round_and_wrong_phase(rf):
    flow = flow_at(rf, "lanes", lane_status={"qa": "pending"}, findings=[], rounds_before=1)
    new = [finding(rf, lanes=("qa",))]
    refused(rf, "wrong_round", rf.submit_lane, flow, 1, rf.model.Lane.QA, new)
    at_integrate = flow_at(rf, "integrate", findings=[])
    refused(rf, "wrong_phase", rf.submit_lane, at_integrate, 1, rf.model.Lane.QA, new)
    done = rf.submit_lane(flow, 2, rf.model.Lane.QA, new)
    assert done.rounds[-1].lanes[rf.model.Lane.QA].status == "done"
    assert [f.fingerprint for f in done.rounds[-1].findings] == [new[0].fingerprint]


def test_failed_lane_submission_records_error_and_no_findings(rf):
    flow = flow_at(rf, "lanes", lane_status={"qa": "pending"}, findings=[])
    failed = rf.submit_lane(flow, 1, rf.model.Lane.QA, [], error="worker timed out")
    run = failed.rounds[-1].lanes[rf.model.Lane.QA]
    assert (run.status, run.error) == ("failed", "worker timed out")


def _at_scope(rf):
    return flow_at(rf, "global_scope", findings=two_findings(rf, disposed=False))


def _drop(basis_type, basis_id, by="worker"):
    return {"action": "drop", "ground": "fact_contradicts", "reason": "not reachable",
            "basis": [{"type": basis_type, "id": basis_id}], "by": by}


def test_unknown_ref_refused_for_finding_fact_rule_and_retired_rule(rf):
    flow = _at_scope(rf)
    target = flow.rounds[-1].findings[0].fingerprint
    rules = rules_file(rf, facts=[fact("F-1", "READ")],
                       rules=[rule("R-1", "active"), rule("R-2", "retired")])
    for fingerprint, basis in (("f" * 64, ("fact", "F-1")), (target, ("fact", "F-9")),
                               (target, ("rule", "R-9")), (target, ("rule", "R-2"))):
        error = refused(rf, "unknown_ref", rf.submit_dispositions, flow, 1,
                        {fingerprint: _drop(*basis)}, rules)
        assert (fingerprint[:12] if fingerprint != target else basis[1]) in str(error)
    accepted = rf.submit_dispositions(flow, 1, {target: _drop("rule", "R-1")}, rules)
    assert accepted.rounds[-1].findings[0].effective_severity is None


def test_weak_blocker_drop_refused_strong_basis_accepted(rf):
    blocker = finding(rf, severity="blocker")
    flow = flow_at(rf, "global_scope", findings=[blocker])
    rules = rules_file(rf, facts=[fact("F-1", "INFERRED"), fact("F-2", "UNVERIFIED"),
                                  fact("F-3", "READ")])
    weak = {"action": "drop", "ground": "fact_contradicts", "reason": "guess",
            "basis": [{"type": "fact", "id": "F-1"}, {"type": "fact", "id": "F-2"}],
            "by": "worker"}
    refused(rf, "weak_blocker_drop", rf.submit_dispositions, flow, 1,
            {blocker.fingerprint: weak}, rules)
    strong = dict(weak, basis=[*weak["basis"], {"type": "fact", "id": "F-3"}])
    done = rf.submit_dispositions(flow, 1, {blocker.fingerprint: strong}, rules)
    assert done.rounds[-1].findings[0].disposition.action == "drop"
    major = flow_at(rf, "global_scope", findings=[finding(rf, severity="major")])
    rf.submit_dispositions(major, 1, {blocker.fingerprint: weak}, rules)


def test_missing_disposition_at_result(rf):
    flow = flow_at(rf, "global_scope", findings=two_findings(rf, disposed=False))
    flow = rf.submit_dispositions(flow, 1, {flow.rounds[-1].findings[0].fingerprint:
                                            {"action": "keep"}}, rules_file(rf))
    error = refused(rf, "missing_disposition", rf.advance, flow, rf.model.Phase.RESULT, "go", NOW)
    assert flow.rounds[-1].findings[1].fingerprint in str(error)
    assert flow.rounds[-1].findings[0].fingerprint not in str(error)


def test_same_head_refused_for_next_round(rf):
    flow = flow_at(rf, "reply_analysis")
    refused(rf, "same_head", rf.next_round, flow, HEAD, "push", NOW)
    nxt = rf.next_round(flow, HEAD2, "new push", NOW)
    last = nxt.rounds[-1]
    assert (last.n, last.head_sha, last.phase.value) == (2, HEAD2, "context")
    assert {run.status for run in last.lanes.values()} == {"pending"}
    entry = nxt.history[-1]
    assert (entry.round, entry.source, entry.target.value, entry.trigger) == \
        (2, None, "context", "new push")


def test_round_not_finished_refused_for_next_round(rf):
    refused(rf, "round_not_finished", rf.next_round, flow_at(rf, "awaiting_author"), HEAD2,
            "push", NOW)
    refused(rf, "round_not_finished", rf.next_round, flow_at(rf, "closed"), HEAD2, "push", NOW)


def test_publish_before_result_refused(rf):
    for phase in ("lanes", "integrate", "global_scope"):
        refused(rf, "publish_before_result", rf.check_publish, flow_at(rf, phase))
    rf.check_publish(flow_at(rf, "result"))


# --- ac2: fingerprint and the fingerprint merge ---------------------------------------------


def test_fingerprint_stable_under_line_shift_and_reword(rf):
    first = finding(rf, start=40, end=52, title="Missing null check", lanes=("qa",),
                    severity="minor")
    shifted = finding(rf, start=47, end=60, title="customer may be None here",
                      lanes=("quality",), severity="major")
    assert first.fingerprint == shifted.fingerprint
    flow = flow_at(rf, "lanes", findings=[], lane_status={"qa": "pending", "quality": "pending"})
    flow = rf.submit_lane(flow, 1, rf.model.Lane.QA, [first])
    flow = rf.submit_lane(flow, 1, rf.model.Lane.QUALITY, [shifted])
    merged = flow.rounds[-1].findings
    assert len(merged) == 1
    assert [lane.value for lane in merged[0].lanes] == ["qa", "quality"]
    assert merged[0].severity.value == "major"
    assert merged[0].title == "customer may be None here"
    assert {e.ref for e in merged[0].evidence} == {"src/pay/charge.py:40",
                                                   "src/pay/charge.py:47"}


def test_fingerprint_changes_with_kind_path_symbol(rf):
    base = rf.model.fingerprint_of("null_deref", "src/a.py", "f")
    assert len({base, rf.model.fingerprint_of("resource_leak", "src/a.py", "f"),
                rf.model.fingerprint_of("null_deref", "src/b.py", "f"),
                rf.model.fingerprint_of("null_deref", "src/a.py", "g")}) == 4


def test_integrate_returns_overlap_clusters_only_across_distinct_fingerprints(rf):
    leak = finding(rf, kind="resource_leak", start=45, end=48, lanes=("architecture",))
    null = finding(rf, start=40, end=46)
    other_file = finding(rf, path="src/pay/util.py", start=40, end=52, symbol="charge")
    apart = finding(rf, kind="perf", start=90, end=95, symbol="refund")
    flow = flow_at(rf, "integrate", findings=[null, leak, other_file, apart])
    round_, clusters = rf.integrate(flow.rounds[-1])
    assert clusters == [(null.fingerprint, leak.fingerprint)]
    assert [f.fingerprint for f in round_.findings] == [
        null.fingerprint, leak.fingerprint, other_file.fingerprint, apart.fingerprint]


def test_integrate_chains_overlaps_into_one_cluster(rf):
    a = finding(rf, kind="perf", start=1, end=5, symbol="a")
    b = finding(rf, kind="perf", start=10, end=12, symbol="b")
    c = finding(rf, kind="perf", start=4, end=11, symbol="c")  # bridges a and b
    _, clusters = rf.integrate(flow_at(rf, "integrate", findings=[a, b, c]).rounds[-1])
    assert clusters == [(a.fingerprint, b.fingerprint, c.fingerprint)]


# --- ac4: verdict ---------------------------------------------------------------------------


@pytest.mark.parametrize("severities,lane_status,expected", [
    (("blocker", "nit"), {}, "Block"),
    (("major", "minor"), {}, "Fix before merge"),
    (("minor", "nit"), {}, "Safe to merge"),
    ((), {}, "Safe to merge"),
    (("blocker",), {"qa": "failed"}, "Block"),
    (("minor",), {"qa": "failed"}, "Fix before merge"),
])
def test_verdict_table_pinned(rf, severities, lane_status, expected):
    findings = [finding(rf, severity=s, symbol=f"s{i}", disposition={"action": "keep"})
                for i, s in enumerate(severities)]
    round_ = flow_at(rf, "result", findings=findings, lane_status=lane_status).rounds[-1]
    assert rf.model.verdict(round_).value == expected


def test_verdict_uses_effective_severity(rf):
    dropped = finding(rf, severity="blocker", disposition=_drop("fact", "F-1", by="script"))
    round_ = flow_at(rf, "result", findings=[dropped]).rounds[-1]
    assert rf.model.verdict(round_).value == "Safe to merge"


def test_failed_lane_never_safe_to_merge(rf):
    for lane in LANES:
        round_ = flow_at(rf, "result", findings=[], lane_status={lane: "failed"}).rounds[-1]
        assert rf.model.verdict(round_).value != "Safe to merge", lane


# --- review round 1: lane and disposition guards ---------------------------------------------


def test_lane_finding_with_a_disposition_refused(rf):
    flow = flow_at(rf, "lanes", findings=[], lane_status={"qa": "pending"})
    clean = finding(rf, lanes=("qa",))
    decided = finding(rf, kind="perf", symbol="refund", lanes=("qa",),
                      disposition=_drop("rule", "R-1"))
    refused(rf, "lane_disposition", rf.submit_lane, flow, 1, rf.model.Lane.QA, [clean, decided])
    assert flow.rounds[-1].lanes[rf.model.Lane.QA].status == "pending"
    accepted = rf.submit_lane(flow, 1, rf.model.Lane.QA, [clean])
    assert [f.disposition for f in accepted.rounds[-1].findings] == [None]


def test_done_lane_refuses_a_changed_resubmission_and_replays_an_identical_one(rf):
    flow = flow_at(rf, "lanes", findings=[], lane_status={"qa": "pending", "quality": "pending"})
    first = finding(rf, lanes=("qa",))
    done = rf.submit_lane(flow, 1, rf.model.Lane.QA, [first])
    assert rf.submit_lane(done, 1, rf.model.Lane.QA, [first]).model_dump(mode="json") == \
        done.model_dump(mode="json")
    refused(rf, "lane_done", rf.submit_lane, done, 1, rf.model.Lane.QA, [])
    refused(rf, "lane_done", rf.submit_lane, done, 1, rf.model.Lane.QA, [first],
            error="worker timed out")
    other = finding(rf, kind="perf", symbol="refund", lanes=("qa",))
    refused(rf, "lane_done", rf.submit_lane, done, 1, rf.model.Lane.QA, [first, other])
    assert [f.fingerprint for f in done.rounds[-1].findings] == [first.fingerprint]


def test_failed_lane_accepts_a_resubmission(rf):
    flow = flow_at(rf, "lanes", findings=[], lane_status={"qa": "pending", "quality": "pending"})
    failed = rf.submit_lane(flow, 1, rf.model.Lane.QA, [], error="worker timed out")
    again = rf.submit_lane(failed, 1, rf.model.Lane.QA, [], error="worker timed out")
    assert again.model_dump(mode="json") == failed.model_dump(mode="json")
    retried = rf.submit_lane(failed, 1, rf.model.Lane.QA, [finding(rf, lanes=("qa",))])
    run = retried.rounds[-1].lanes[rf.model.Lane.QA]
    assert (run.status, run.error) == ("done", None)
    assert [lane.value for f in retried.rounds[-1].findings for lane in f.lanes] == ["qa"]


def test_worker_cannot_redecide_a_script_disposition(rf):
    script_drop = _drop("fact", "F-1", by="script")
    decided = finding(rf, disposition=script_drop)
    open_ = finding(rf, kind="style", path="src/pay/util.py", symbol="<module>",
                    severity="nit", lanes=("quality",))
    flow = flow_at(rf, "global_scope", findings=[decided, open_])
    rules = rules_file(rf, facts=[fact("F-1", "READ")])
    error = refused(rf, "already_decided", rf.submit_dispositions, flow, 1,
                    {open_.fingerprint: {"action": "keep"},
                     decided.fingerprint: {"action": "keep"}}, rules)
    assert decided.fingerprint[:12] in str(error)
    replay = rf.submit_dispositions(flow, 1, {decided.fingerprint: dict(script_drop),
                                              open_.fingerprint: {"action": "keep"}}, rules)
    assert replay.rounds[-1].findings[0].disposition == decided.disposition
    assert replay.rounds[-1].findings[1].disposition.action == "keep"


def test_basis_must_cover_the_finding_it_disposes(rf):
    flow = _at_scope(rf)
    target = flow.rounds[-1].findings[0]
    elsewhere = fact("F-1", "READ", paths=("src/legacy/*",))
    other_kind = fact("F-2", "READ", kinds=("perf",))
    unscoped = {"id": "F-3", "statement": "Charge always has a customer.", "grade": "READ",
                "evidence_ref": "docs/x.md"}
    rules = rules_file(rf, facts=[elsewhere, other_kind, unscoped],
                       rules=[rule("R-1", "active", paths=("lib/*",)), rule("R-2", "active")])
    for basis in (("fact", "F-1"), ("fact", "F-2"), ("rule", "R-1")):
        error = refused(rf, "basis_out_of_scope", rf.submit_dispositions, flow, 1,
                        {target.fingerprint: _drop(*basis)}, rules)
        assert basis[1] in str(error) and target.fingerprint[:12] in str(error)
    for basis in (("fact", "F-3"), ("rule", "R-2")):
        done = rf.submit_dispositions(flow, 1, {target.fingerprint: _drop(*basis)}, rules)
        assert done.rounds[-1].findings[0].disposition.basis[0].id == basis[1]
