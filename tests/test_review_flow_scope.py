"""Review-flow global scope: facts and active rules re-judge findings by script, nothing else."""
from __future__ import annotations

import pytest

from test_review_flow_ops import (DIGEST, fact, finding, flow_at, refused, rule,
                                  rules_file)

SCRIPT_RELPATH = "features/common/skills/review-flow/scripts/review_flow.py"
NEW_DIGEST = "b" * 64


@pytest.fixture(name="rf")
def _review_flow(load_script):
    return load_script(SCRIPT_RELPATH)


def scope_round(rf, findings):
    return flow_at(rf, "global_scope", findings=findings).rounds[-1].model_copy(
        update={"rules_digest": None})


def nullable_fact():
    return fact("F-1", "READ", kinds=("null_deref",), paths=("src/legacy/*",))


def by_fp(round_):
    return {f.fingerprint: f for f in round_.findings}


def test_nullable_fact_suppresses_null_deref_in_scope(rf):
    in_scope = finding(rf, path="src/legacy/orders.py", symbol="load")
    round_, remaining = rf.global_scope(scope_round(rf, [in_scope]),
                                        rules_file(rf, facts=[nullable_fact()]), NEW_DIGEST)
    got = by_fp(round_)[in_scope.fingerprint].disposition
    assert (got.action, got.ground.value, got.by) == ("drop", "fact_contradicts", "script")
    assert [(ref.type, ref.id) for ref in got.basis] == [("fact", "F-1")]
    assert "F-1" in got.reason
    assert round_.rules_digest == NEW_DIGEST
    assert remaining == []


def test_nullable_fact_keeps_null_deref_outside_scope(rf):
    outside = finding(rf, path="src/core/orders.py", symbol="load")
    other_kind = finding(rf, kind="resource_leak", path="src/legacy/orders.py", symbol="load")
    in_scope = finding(rf, path="src/legacy/orders.py", symbol="load")
    round_, remaining = rf.global_scope(
        scope_round(rf, [outside, other_kind, in_scope]),
        rules_file(rf, facts=[nullable_fact()]), NEW_DIGEST)
    dispositions = {fp: f.disposition for fp, f in by_fp(round_).items()}
    assert dispositions[outside.fingerprint] is None
    assert dispositions[other_kind.fingerprint] is None
    assert dispositions[in_scope.fingerprint].action == "drop"
    assert [f.fingerprint for f in remaining] == [outside.fingerprint, other_kind.fingerprint]


def test_config_reload_fact_downgrades_to_nit_defensive(rf):
    reload_fact = fact("F-2", "MEASURED", kinds=("config",), paths=("config/*",),
                       action="downgrade", to="nit", ground="unreachable_in_production")
    target = finding(rf, kind="config", path="config/app.yaml", symbol="<module>",
                     severity="major")
    round_, remaining = rf.global_scope(scope_round(rf, [target]),
                                        rules_file(rf, facts=[reload_fact]), NEW_DIGEST)
    got = by_fp(round_)[target.fingerprint]
    assert got.disposition.action == "downgrade"
    assert (got.disposition.to.value, got.disposition.by) == ("nit", "script")
    assert got.severity.value == "major"
    assert got.effective_severity.value == "nit"
    assert [tag.value for tag in got.tags] == ["DEFENSIVE"]
    assert remaining == []


def test_inferred_fact_or_proposed_rule_does_not_drop(rf):
    blocker = finding(rf, severity="blocker", path="src/legacy/orders.py", symbol="load")
    by_rule = finding(rf, path="src/pay/a.py", symbol="pay")
    retired = finding(rf, path="src/old/a.py", symbol="pay")
    active = finding(rf, path="src/ok/a.py", symbol="pay")
    rules = rules_file(rf, facts=[fact("F-1", "INFERRED", paths=("src/legacy/*",))],
                       rules=[rule("R-1", "proposed", paths=("src/pay/*",)),
                              rule("R-2", "retired", paths=("src/old/*",)),
                              rule("R-3", "active", paths=("src/ok/*",))])
    round_, remaining = rf.global_scope(scope_round(rf, [blocker, by_rule, retired, active]),
                                        rules, NEW_DIGEST)
    got = by_fp(round_)
    assert got[blocker.fingerprint].disposition is None
    assert got[by_rule.fingerprint].disposition is None
    assert got[retired.fingerprint].disposition is None
    assert [ref.id for ref in got[active.fingerprint].disposition.basis] == ["R-3"]
    assert [f.fingerprint for f in remaining] == [blocker.fingerprint, by_rule.fingerprint,
                                                  retired.fingerprint]
    flow = flow_at(rf, "global_scope", findings=[blocker])
    refused(rf, "weak_blocker_drop", rf.submit_dispositions, flow, 1, {blocker.fingerprint: {
        "action": "drop", "ground": "fact_contradicts", "reason": "guess",
        "basis": [{"type": "fact", "id": "F-1"}], "by": "worker"}}, rules)
    refused(rf, "unknown_ref", rf.submit_dispositions, flow, 1, {blocker.fingerprint: {
        "action": "drop", "ground": "rule", "reason": "taught once",
        "basis": [{"type": "rule", "id": "R-1"}], "by": "worker"}}, rules)


def test_conflicting_active_rules_do_nothing(rf):
    target = finding(rf, path="src/pay/a.py", symbol="pay")
    require = rule("R-2", "active")
    require["effect"] = {"action": "require", "ground": "rule"}
    rules = rules_file(rf, rules=[rule("R-1", "active"), require])
    round_, remaining = rf.global_scope(scope_round(rf, [target]), rules, NEW_DIGEST)
    assert by_fp(round_)[target.fingerprint].disposition is None
    assert [f.fingerprint for f in remaining] == [target.fingerprint]


def test_existing_disposition_is_not_rejudged(rf):
    kept = finding(rf, path="src/legacy/orders.py", symbol="load", disposition={"action": "keep"})
    round_, remaining = rf.global_scope(scope_round(rf, [kept]),
                                        rules_file(rf, facts=[nullable_fact()]), NEW_DIGEST)
    assert by_fp(round_)[kept.fingerprint].disposition.action == "keep"
    assert remaining == []


def test_dropped_findings_stay_in_model(rf):
    blocker = finding(rf, severity="blocker", path="src/legacy/orders.py", symbol="load")
    nit = finding(rf, kind="style", path="src/a.py", symbol="<module>", severity="nit",
                  disposition={"action": "keep"})
    round_, _ = rf.global_scope(scope_round(rf, [blocker, nit]),
                                rules_file(rf, facts=[nullable_fact()]), NEW_DIGEST)
    assert [f.fingerprint for f in round_.findings] == [blocker.fingerprint, nit.fingerprint]
    assert round_.findings[0].severity.value == "blocker"
    assert round_.findings[0].effective_severity is None
    assert rf.model.verdict(round_).value == "Safe to merge"
    assert DIGEST != round_.rules_digest


def test_new_rules_digest_refused_once_the_script_disposed(rf):
    blocker = finding(rf, severity="blocker", path="src/legacy/orders.py", symbol="load")
    open_ = finding(rf, kind="perf", path="src/a.py", symbol="run", severity="minor")
    rules = rules_file(rf, facts=[nullable_fact()])
    judged, _ = rf.global_scope(scope_round(rf, [blocker, open_]), rules, DIGEST)
    assert judged.findings[0].disposition.by == "script"
    refused(rf, "digest_changed", rf.global_scope, judged, rules, NEW_DIGEST)
    replay, remaining = rf.global_scope(judged, rules, DIGEST)
    assert replay.model_dump(mode="json") == judged.model_dump(mode="json")
    assert [f.fingerprint for f in remaining] == [open_.fingerprint]
    untouched, _ = rf.global_scope(scope_round(rf, [open_]), rules, DIGEST)
    moved, _ = rf.global_scope(untouched, rules, NEW_DIGEST)
    assert moved.rules_digest == NEW_DIGEST


def test_retained_keep_prevents_digest_change(rf):
    target = finding(rf)
    require = rule("R-1", "active")
    require["effect"] = {"action": "require", "ground": "rule"}
    rules = rules_file(rf, rules=[require])
    judged, _ = rf.global_scope(scope_round(rf, [target]), rules, DIGEST)
    assert judged.findings[0].disposition.action == "keep"
    replay, _ = rf.global_scope(judged, rules, DIGEST)
    assert replay == judged
    refused(rf, "digest_changed", rf.global_scope, judged, rules_file(rf), NEW_DIGEST)


def test_global_scope_rejects_rules_changed_since_brief(rf):
    target = finding(rf, severity="blocker")
    pinned = scope_round(rf, [target]).model_copy(update={"scope_brief_digest": DIGEST})
    refused(rf, "digest_changed", rf.global_scope, pinned, rules_file(rf), NEW_DIGEST)
