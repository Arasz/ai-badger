"""Review-flow model: refused shapes, the severity map, the verdict and the generated schemas."""
from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
MODEL_RELPATH = "features/common/skills/review-flow/scripts/review_flow_model.py"
RENDER_RELPATH = "features/common/skills/review-flow/scripts/review_render.py"
GENERATOR_RELPATH = "tooling/review_flow_schema.py"
HEAD = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "a" * 64


@pytest.fixture(name="m")
def _model(load_script):
    return load_script(MODEL_RELPATH)


def _fp(kind, path, symbol):
    return hashlib.sha256(f"{kind}|{path}|{symbol}".encode("utf-8")).hexdigest()


def _finding(**over):
    data = {
        "lanes": ["qa", "quality"],
        "source": "lane",
        "kind": "null_deref",
        "severity": "major",
        "confidence": "high",
        "location": {"path": "src/pay/charge.py", "start": 40, "end": 52, "symbol": "charge"},
        "in_diff": True,
        "title": "Missing null check on customer lookup",
        "reason": "`find_customer` returns None for unknown ids.\nThe next line dereferences it.",
        "evidence": [{"grade": "READ", "ref": "src/pay/charge.py:41"}],
        "agent": {"repro": "pytest -k unknown", "context": "Called from checkout().",
                  "fix": "raise UnknownCustomer"},
        "ac_refs": [],
        "tags": [],
        "disposition": None,
    }
    data.update(over)
    loc = data["location"]
    data.setdefault("fingerprint", _fp(data["kind"], loc["path"], loc["symbol"]))
    return data


def _downgrade(**over):
    data = {"action": "downgrade", "to": "minor", "ground": "fact_contradicts",
            "reason": "Caller guarantees a customer.", "basis": [{"type": "fact", "id": "F-1"}],
            "by": "worker"}
    data.update(over)
    return data


def _drop(**over):
    data = {"action": "drop", "ground": "rule", "reason": "Legacy code is out of scope.",
            "basis": [{"type": "rule", "id": "R-1"}], "by": "script"}
    data.update(over)
    return data


def _lanes(**status):
    runs = {lane: {"status": "done", "error": None}
            for lane in ("business", "qa", "architecture", "quality")}
    for lane, value in status.items():
        runs[lane] = {"status": value, "error": "worker timed out" if value == "failed" else None}
    return runs


def _publication():
    return {"review_id": 11, "summary_comment_id": 12, "event": "COMMENT",
            "at": "2026-11-18T12:00:00Z"}


def _round(**over):
    data = {"n": 1, "head_sha": HEAD, "phase": "published", "rules_digest": DIGEST,
            "lanes": _lanes(), "findings": [_finding(disposition={"action": "keep"})],
            "replies": [], "published": _publication()}
    data.update(over)
    return data


# Independent of the model's TRANSITIONS on purpose: the chain each fixture round walks.
PHASE_ORDER = ("context", "change_model", "lanes", "integrate", "global_scope", "result",
               "published", "awaiting_author", "reply_analysis", "closed")


def _chain(round_n, phase):
    """History entries that open round `round_n` and walk it to `phase`."""
    steps = PHASE_ORDER[:PHASE_ORDER.index(phase) + 1]
    return [{"round": round_n, "source": source, "target": target,
             "at": "2026-11-18T11:00:00Z", "trigger": f"to {target}"}
            for source, target in zip((None, *steps[:-1]), steps)]


def _flow(**over):
    """A valid flow; unless `history` is given, it replays every round to its phase."""
    data = {"schema_version": 1, "flow_id": "rf-1", "repo": "octo/widgets", "pr": 7,
            "issue_refs": ["#3"], "ac_source": "pasted",
            "acs": [{"id": "AC1", "statement": "Refunds post a ledger entry."}],
            "rounds": [_round()]}
    data.update(over)
    if "history" not in over:
        data["history"] = [entry for r in data["rounds"] for entry in _chain(r["n"], r["phase"])]
    return data


def _origin(pr=1, thread="https://github.com/o/r/pull/1#discussion_r1", author="alice"):
    return {"pr": pr, "thread_url": thread, "author": author, "association": "MEMBER",
            "quote": "This is fine for legacy."}


def _rule(rule_id="R-1", **over):
    data = {"id": rule_id, "status": "proposed", "statement": "Legacy code is not reviewed.",
            "applies": {"kinds": ["dead_code"], "paths": ["legacy/*"], "symbols": []},
            "effect": {"action": "suppress", "to": None, "ground": "rule"},
            "origins": [_origin()], "activated_by": None, "citation": None}
    data.update(over)
    return data


def _rules_file(**over):
    data = {"schema_version": 1, "rules": [_rule()],
            "facts": [{"id": "F-1", "statement": "Checkout always loads the customer.",
                       "grade": "READ", "evidence_ref": "src/checkout.py:10",
                       "applies": None, "effect": None}]}
    data.update(over)
    return data


# ------------------------------------------------------------------ ac1: fields and labels


def test_unknown_field_refused(m):
    with pytest.raises(ValidationError, match="extra"):
        m.Finding.model_validate(_finding(severty="major"))
    with pytest.raises(ValidationError, match="extra"):
        m.RulesFile.model_validate(_rules_file(rule=[]))
    with pytest.raises(ValidationError, match="extra"):
        m.ReviewFlow.model_validate(_flow(round=[]))


def test_unknown_label_refused(m):
    with pytest.raises(ValueError, match="Severe"):
        m.normalise_severity("checklist", "Severe")
    with pytest.raises(ValueError, match="critical"):
        m.normalise_severity("checklist", "critical")
    with pytest.raises(ValueError, match="observability"):
        m.normalise_severity("observability", "MINOR")
    with pytest.raises(ValidationError):
        m.Finding.model_validate(_finding(severity="High"))


EXPECTED_VOCABULARIES = {
    "checklist": {"Critical": "blocker", "High": "major", "Medium": "minor", "Low": "nit"},
    "lane_brief": {"BLOCKER": "blocker", "HIGH": "major", "MEDIUM": "minor", "LOW": "nit",
                   "NIT": "nit"},
    "design_gate_audit": {"MUST-FIX": "blocker", "SHOULD-FIX": "major", "NIT": "nit"},
    "review_gate_diff_verification": {"MUST-FIX": "blocker", "SHOULD-FIX": "major",
                                      "NIT": "nit"},
    "review_tests": {"blocker": "blocker", "major": "major", "minor": "minor"},
}


def test_every_label_of_five_vocabularies_maps(m):
    assert {name: {label: sev.value for label, sev in table.items()}
            for name, table in m.VOCABULARIES.items()} == EXPECTED_VOCABULARIES
    for name, table in EXPECTED_VOCABULARIES.items():
        for label, severity in table.items():
            assert m.normalise_severity(name, label) is m.Severity(severity)


# ------------------------------------------------------------------ ac2: illegal states


def test_invalid_drop_without_basis(m):
    with pytest.raises(ValidationError, match="basis"):
        m.Finding.model_validate(_finding(disposition=_drop(basis=[])))
    m.Finding.model_validate(_finding(disposition=_drop()))


def test_invalid_downgrade_without_basis(m):
    with pytest.raises(ValidationError, match="basis"):
        m.Finding.model_validate(_finding(disposition=_downgrade(basis=[])))
    m.Finding.model_validate(_finding(disposition=_downgrade()))


def test_invalid_downgrade_not_lower(m):
    with pytest.raises(ValidationError, match="lower"):
        m.Finding.model_validate(_finding(disposition=_downgrade(to="major")))
    with pytest.raises(ValidationError, match="lower"):
        m.Finding.model_validate(_finding(disposition=_downgrade(to="blocker")))


def test_invalid_keep_without_severity(m):
    data = _finding(disposition={"action": "keep"})
    del data["severity"]
    with pytest.raises(ValidationError, match="severity"):
        m.Finding.model_validate(data)
    with pytest.raises(ValidationError, match="extra"):
        m.Finding.model_validate(_finding(disposition={"action": "keep", "to": "minor"}))


def test_invalid_unreachable_without_defensive(m):
    unreachable = _downgrade(ground="unreachable_in_production")
    with pytest.raises(ValidationError, match="DEFENSIVE"):
        m.Finding.model_validate(_finding(disposition=unreachable, tags=["PRE_EXISTING"]))
    with pytest.raises(ValidationError, match="downgrade"):
        m.Finding.model_validate(_finding(disposition=_drop(ground="unreachable_in_production"),
                                          tags=["DEFENSIVE"]))
    kept = m.Finding.model_validate(_finding(disposition=unreachable,
                                             tags=["DEFENSIVE", "PRE_EXISTING"]))
    assert kept.effective_severity is m.Severity.MINOR


def test_invalid_effect_unreachable_must_downgrade(m):
    with pytest.raises(ValidationError, match="downgrade"):
        m.Effect.model_validate({"action": "suppress", "to": None,
                                 "ground": "unreachable_in_production"})
    with pytest.raises(ValidationError, match="to"):
        m.Effect.model_validate({"action": "downgrade", "to": None, "ground": "rule"})
    with pytest.raises(ValidationError, match="to"):
        m.Effect.model_validate({"action": "require", "to": "minor", "ground": "rule"})


def test_invalid_applies_matches_other(m):
    with pytest.raises(ValidationError, match="other"):
        m.Applies.model_validate({"kinds": ["perf", "other"], "paths": ["*"], "symbols": []})


def test_invalid_ref_prefix_disagrees_with_type(m):
    with pytest.raises(ValidationError, match="R-"):
        m.Ref.model_validate({"type": "rule", "id": "F-1"})


def test_invalid_human_part_over_line_limit(m, load_script):
    limit = load_script(RENDER_RELPATH).HUMAN_LINE_LIMIT
    fits = "\n".join(f"line {i}" for i in range(limit - 2))
    m.Finding.model_validate(_finding(reason=fits + "\n\n"))
    with pytest.raises(ValidationError, match="human part"):
        m.Finding.model_validate(_finding(reason=fits + "\none more"))
    with pytest.raises(ValidationError, match="title"):
        m.Finding.model_validate(_finding(title="two\nlines"))


def test_invalid_location_end_before_start(m):
    loc = {"path": "a.py", "start": 9, "end": 8, "symbol": "f"}
    with pytest.raises(ValidationError, match="end"):
        m.Finding.model_validate(_finding(location=loc))
    loc = {"path": "a.py", "start": 1, "end": 2, "symbol": ""}
    with pytest.raises(ValidationError, match="symbol"):
        m.Finding.model_validate(_finding(location=loc))


def test_invalid_published_round_without_publication(m):
    with pytest.raises(ValidationError, match="published"):
        m.Round.model_validate(_round(published=None))
    with pytest.raises(ValidationError, match="published"):
        m.Round.model_validate(_round(phase="result"))
    assert m.Round.model_validate(_round(phase="result", published=None)).published is None


def test_invalid_pending_lane_after_lanes_phase(m):
    with pytest.raises(ValidationError, match="pending"):
        m.Round.model_validate(_round(phase="integrate", published=None,
                                      lanes=_lanes(architecture="pending")))
    m.Round.model_validate(_round(phase="lanes", published=None, rules_digest=None,
                                  lanes=_lanes(architecture="pending"),
                                  findings=[_finding()]))


def test_invalid_round_lanes_incomplete_or_failed_without_error(m):
    lanes = _lanes()
    del lanes["business"]
    with pytest.raises(ValidationError, match="business"):
        m.Round.model_validate(_round(lanes=lanes))
    lanes = _lanes()
    lanes["qa"] = {"status": "failed", "error": None}
    with pytest.raises(ValidationError, match="error"):
        m.Round.model_validate(_round(lanes=lanes))


def test_invalid_result_round_with_undisposed_finding_or_no_digest(m):
    with pytest.raises(ValidationError, match="disposition"):
        m.Round.model_validate(_round(phase="result", published=None, findings=[_finding()]))
    with pytest.raises(ValidationError, match="rules_digest"):
        m.Round.model_validate(_round(phase="result", published=None, rules_digest=None))
    m.Round.model_validate(_round(phase="global_scope", published=None, rules_digest=None,
                                  findings=[_finding()]))


def test_invalid_duplicate_fingerprints_in_round(m):
    kept = _finding(disposition={"action": "keep"})
    with pytest.raises(ValidationError, match="fingerprint"):
        m.Round.model_validate(_round(findings=[kept, copy.deepcopy(kept)]))


def test_invalid_active_rule_without_activated_by(m):
    with pytest.raises(ValidationError, match="activated_by"):
        m.LearnedRule.model_validate(_rule(status="active"))
    with pytest.raises(ValidationError, match="activated_by"):
        m.LearnedRule.model_validate(_rule(status="retired"))
    with pytest.raises(ValidationError, match="activated_by"):
        m.LearnedRule.model_validate(_rule(status="proposed", activated_by="maintainer"))
    with pytest.raises(ValidationError, match="citation"):
        m.LearnedRule.model_validate(_rule(status="active", activated_by="citation"))
    cited = {"path": "src/a.py", "start": 1, "end": 3}
    m.LearnedRule.model_validate(_rule(status="active", activated_by="citation", citation=cited))


def test_invalid_threads_activation_one_distinct_author(m):
    same_author = [_origin(pr=1, thread="t1", author="alice"),
                   _origin(pr=2, thread="t2", author="alice")]
    with pytest.raises(ValidationError, match="threads"):
        m.LearnedRule.model_validate(_rule(status="active", activated_by="threads",
                                           origins=same_author))
    same_thread = [_origin(thread="t1", author="alice"), _origin(thread="t1", author="bob")]
    with pytest.raises(ValidationError, match="threads"):
        m.LearnedRule.model_validate(_rule(status="active", activated_by="threads",
                                           origins=same_thread))
    independent = same_author + [_origin(pr=1, thread="t3", author="bob")]
    m.LearnedRule.model_validate(_rule(status="active", activated_by="threads",
                                       origins=independent))


def test_invalid_rule_statement_over_limit(m):
    m.LearnedRule.model_validate(_rule(statement="x" * 500))
    with pytest.raises(ValidationError, match="500"):
        m.LearnedRule.model_validate(_rule(statement="x" * 501))


def test_invalid_fact_with_applies_but_no_effect(m):
    fact = _rules_file()["facts"][0]
    fact["applies"] = {"kinds": ["perf"], "paths": ["*"], "symbols": []}
    with pytest.raises(ValidationError, match="both"):
        m.ProjectFact.model_validate(fact)


def test_invalid_rules_file_ids_reused_or_out_of_order(m):
    with pytest.raises(ValidationError, match="R-1"):
        m.RulesFile.model_validate(_rules_file(rules=[_rule("R-1"), _rule("R-1")]))
    with pytest.raises(ValidationError, match="order"):
        m.RulesFile.model_validate(_rules_file(rules=[_rule("R-2"), _rule("R-1")]))
    m.RulesFile.model_validate(_rules_file(rules=[_rule("R-1"), _rule("R-3")]))


def test_invalid_worker_supplied_wrong_fingerprint(m):
    wrong = _finding(fingerprint=_fp("null_deref", "src/pay/charge.py", "refund"))
    with pytest.raises(ValidationError, match="fingerprint"):
        m.Finding.model_validate(wrong)
    finding = m.Finding.model_validate(_finding())
    assert finding.fingerprint == _fp("null_deref", "src/pay/charge.py", "charge")
    assert m.fingerprint_of("null_deref", "src/pay/charge.py", "charge") == finding.fingerprint


def test_invalid_flow_ac_source_and_acs_disagree(m):
    with pytest.raises(ValidationError, match="absent"):
        m.ReviewFlow.model_validate(_flow(ac_source="absent"))
    with pytest.raises(ValidationError, match="absent"):
        m.ReviewFlow.model_validate(_flow(acs=[]))
    m.ReviewFlow.model_validate(_flow(ac_source="absent", acs=[]))


def test_invalid_flow_rounds(m):
    second = _round(n=2, head_sha="b" * 40, phase="lanes", published=None,
                    lanes=_lanes(qa="pending"), findings=[])
    first_done = _round(phase="reply_analysis")
    m.ReviewFlow.model_validate(_flow(rounds=[first_done, second]))
    with pytest.raises(ValidationError, match="only the last round"):
        m.ReviewFlow.model_validate(_flow(rounds=[_round(phase="published"), second]))
    with pytest.raises(ValidationError, match="head_sha"):
        m.ReviewFlow.model_validate(_flow(rounds=[first_done, dict(second, head_sha=HEAD)]))
    with pytest.raises(ValidationError, match="numbered"):
        m.ReviewFlow.model_validate(_flow(rounds=[first_done, dict(second, n=3)]))
    bad_history = [{"round": 2, "source": None, "target": "context",
                    "at": "2026-11-18T11:00:00Z", "trigger": "start"}]
    with pytest.raises(ValidationError, match="round 2"):
        m.ReviewFlow.model_validate(_flow(history=bad_history))
    with pytest.raises(ValidationError, match="UTC"):
        m.ReviewFlow.model_validate(_flow(history=[dict(bad_history[0], round=1,
                                                       at="2026-11-18T11:00:00+02:00")]))


# ------------------------------------------------------------------ verdict and severity


def _verdict(m, findings, **lanes):
    return m.verdict(m.Round.model_validate(
        _round(phase="result", published=None, findings=findings, lanes=_lanes(**lanes))))


def _kept(severity, symbol):
    return _finding(severity=severity, location={"path": "a.py", "start": 1, "end": 1,
                                                 "symbol": symbol},
                    disposition={"action": "keep"})


def test_verdict_from_effective_severities_and_lanes(m):
    assert _verdict(m, [_kept("nit", "a"), _kept("blocker", "b")]) is m.Verdict.BLOCK
    assert m.Verdict.BLOCK.value == "Block"
    assert _verdict(m, [_kept("major", "a"), _kept("minor", "b")]) is m.Verdict.FIX
    assert m.Verdict.FIX.value == "Fix before merge"
    assert _verdict(m, [_kept("minor", "a"), _kept("nit", "b")]) is m.Verdict.SAFE
    assert m.Verdict.SAFE.value == "Safe to merge"
    assert _verdict(m, []) is m.Verdict.SAFE


def test_verdict_failed_lane_forbids_safe(m):
    assert _verdict(m, [_kept("nit", "a")], qa="failed") is m.Verdict.FIX
    assert _verdict(m, [_kept("blocker", "a")], qa="failed") is m.Verdict.BLOCK


def test_verdict_reads_dispositions_not_raw_severity(m):
    dropped = _kept("blocker", "a")
    dropped["disposition"] = _drop()
    downgraded = _kept("blocker", "b")
    downgraded["disposition"] = _downgrade(to="nit")
    lowered = _kept("major", "c")
    lowered["disposition"] = _downgrade(to="minor")
    round_ = m.Round.model_validate(_round(findings=[dropped, downgraded, lowered]))
    assert m.verdict(round_) is m.Verdict.SAFE
    assert round_.verdict is m.Verdict.SAFE
    assert [f.effective_severity for f in round_.findings] == [None, m.Severity.NIT,
                                                               m.Severity.MINOR]
    assert "verdict" not in round_.model_dump(mode="json")


# ------------------------------------------------------------------ renderer contract


def test_model_built_finding_renders_inline(m, load_script):
    render = load_script(RENDER_RELPATH)
    assert m.HUMAN_LINE_LIMIT == render.HUMAN_LINE_LIMIT
    finding = m.Finding.model_validate(_finding(
        tags=["PRE_EXISTING", "DEFENSIVE"],
        disposition=_downgrade(ground="unreachable_in_production")))
    dumped = finding.model_dump(mode="json")
    assert dumped["tags"] == ["DEFENSIVE", "PRE_EXISTING"]
    body = render.render_inline(dumped)
    assert f"fp={finding.fingerprint}" in body
    assert body.splitlines()[1] == "**MINOR** · qa, quality · null_deref · DEFENSIVE"
    assert "1 evidence item" in body
    round_ = m.Round.model_validate(_round(findings=[dumped]))
    summary = render.render_summary(
        {**round_.model_dump(mode="json"), "verdict": m.verdict(round_).value},
        {"ac_source": "pasted"}, __import__("datetime").datetime(
            2026, 11, 18, tzinfo=__import__("datetime").timezone.utc))
    assert "Reviewed commit: `" + HEAD + "`" in summary
    assert "## Review verdict: Safe to merge\n" in summary


# ------------------------------------------------------------------ rules at load


def _active(rule_id, action, kinds, paths, to=None):
    return _rule(rule_id, status="active", activated_by="maintainer",
                 applies={"kinds": kinds, "paths": paths, "symbols": []},
                 effect={"action": action, "to": to, "ground": "rule"})


def test_conflicting_active_rules_are_both_excluded(m):
    rules = m.RulesFile.model_validate(_rules_file(rules=[
        _active("R-1", "require", ["perf", "docs"], ["src/*"]),
        _active("R-2", "suppress", ["perf"], ["src/hot.py"]),
        _active("R-3", "downgrade", ["docs"], ["docs/*"], to="nit"),
        _rule("R-4", effect={"action": "require", "to": None, "ground": "rule"},
              applies={"kinds": ["dead_code"], "paths": ["legacy/*"], "symbols": []}),
        _active("R-5", "suppress", ["style"], ["src/*"]),
    ]))
    assert m.rule_conflicts(rules.rules) == {"R-1", "R-2"}
    assert [rule.id for rule in m.lane_rules(rules)] == ["R-3", "R-5"]


# ------------------------------------------------------------------ ac3: schemas


def test_schemas_generated_and_registered(load_script):
    generator = load_script(GENERATOR_RELPATH)
    validate = load_script("tooling/validate.py")
    built = generator.build_schemas(generator.load_model(ROOT))
    assert set(built) == {"schemas/review-flow.schema.json", "schemas/review-rules.schema.json"}
    registered = set(validate.SCHEMA_INSTANCES) | set(validate.SCHEMAS_WITHOUT_LOCAL_INSTANCES)
    for relpath, schema in built.items():
        assert json.loads((ROOT / relpath).read_text(encoding="utf-8")) == schema
        assert Path(relpath).name in registered
    assert built["schemas/review-flow.schema.json"]["title"] == "ReviewFlow"
    assert built["schemas/review-rules.schema.json"]["title"] == "RulesFile"


# ------------------------------------------------------------------ review round 1 fixes


@pytest.mark.parametrize("left,right,witness", [
    ("src/*/payment.py", "src/pay/*.py", "src/pay/payment.py"),
    ("src/*", "src/pay/*.py", "src/pay/a.py"),
    ("src/?ay/x.py", "src/p*/x.py", "src/pay/x.py"),
    ("src/[ab].py", "src/[bc].py", "src/b.py"),
])
def test_rule_conflicts_finds_wildcard_globs_that_share_a_path(m, left, right, witness):
    assert fnmatch.fnmatchcase(witness, left) and fnmatch.fnmatchcase(witness, right)
    rules = m.RulesFile.model_validate(_rules_file(rules=[
        _active("R-1", "require", ["perf"], [left]),
        _active("R-2", "suppress", ["perf"], [right]),
        _active("R-3", "suppress", ["perf"], ["docs/*.md"]),
    ]))
    assert m.rule_conflicts(rules.rules) == {"R-1", "R-2"}
    assert [rule.id for rule in m.lane_rules(rules)] == ["R-3"]


@pytest.mark.parametrize("left,right", [
    ("src/*/payment.py", "lib/*.py"),
    ("src/*.py", "src/*.js"),
    ("src/[ab].py", "src/[cd].py"),
    ("src/pay/?.py", "src/pay/ab.py"),
])
def test_rule_conflicts_leaves_disjoint_wildcard_globs_alone(m, left, right):
    rules = m.RulesFile.model_validate(_rules_file(rules=[
        _active("R-1", "require", ["perf"], [left]),
        _active("R-2", "suppress", ["perf"], [right]),
    ]))
    assert m.rule_conflicts(rules.rules) == set()
    assert [rule.id for rule in m.lane_rules(rules)] == ["R-1", "R-2"]


def _anchored(m, start, anchor, **over):
    location = {"path": "src/pay/charge.py", "start": start, "end": start, "symbol": "charge",
                "anchor": anchor}
    fingerprint = m.fingerprint_of("null_deref", "src/pay/charge.py", "charge", anchor)
    return _finding(location=location, fingerprint=fingerprint, **over)


def test_two_anchors_in_one_function_keep_two_fingerprints(m):
    first = _anchored(m, 41, "customer.id", disposition={"action": "keep"})
    second = _anchored(m, 48, "order.total", disposition={"action": "keep"})
    round_ = m.Round.model_validate(_round(findings=[first, second]))
    assert len({f.fingerprint for f in round_.findings}) == 2
    assert first["fingerprint"] != _fp("null_deref", "src/pay/charge.py", "charge")
    assert [f.location.anchor for f in round_.findings] == ["customer.id", "order.total"]


def test_anchor_identity_survives_line_shift_and_whitespace(m):
    raw = "  customer =\n\tfind_customer(id)  "
    expected = m.fingerprint_of("null_deref", "src/pay/charge.py", "charge",
                                "customer = find_customer(id)")
    assert m.fingerprint_of("null_deref", "src/pay/charge.py", "charge", raw) == expected
    shifted = m.Finding.model_validate(_anchored(m, 90, raw, title="customer may be None"))
    assert shifted.fingerprint == expected
    assert shifted.location.anchor == "customer = find_customer(id)"
    capped = m.Finding.model_validate(_anchored(m, 1, "x" * 250))
    assert capped.location.anchor == "x" * 200
    assert capped.fingerprint == m.fingerprint_of("null_deref", "src/pay/charge.py", "charge",
                                                  "x" * 200)
    with pytest.raises(ValidationError, match="fingerprint"):
        m.Finding.model_validate(_finding(location={
            "path": "src/pay/charge.py", "start": 1, "end": 1, "symbol": "charge",
            "anchor": "customer.id"}))


def test_no_anchor_keeps_the_kind_path_symbol_fingerprint(m):
    assert m.fingerprint_of("null_deref", "src/a.py", "f") == _fp("null_deref", "src/a.py", "f")
    assert m.fingerprint_of("null_deref", "src/a.py", "f", None) == \
        _fp("null_deref", "src/a.py", "f")
    assert m.Finding.model_validate(_finding()).location.anchor is None
    with pytest.raises(ValidationError, match="anchor"):
        m.Finding.model_validate(_finding(location={
            "path": "src/pay/charge.py", "start": 1, "end": 1, "symbol": "charge",
            "anchor": " \n "}))


def test_review_flow_accepts_the_schema_editor_hint(m):
    hint = "../../schemas/review-flow.schema.json"
    flow = m.ReviewFlow.model_validate(_flow(**{"$schema": hint}))
    assert flow.schema_ == hint
    assert m.ReviewFlow.model_validate(flow.model_dump(mode="json")).schema_ == hint


def test_publication_review_id_is_absent_not_zero(m):
    assert m.Publication.model_validate(dict(_publication(), review_id=None)).review_id is None
    assert m.Publication.model_validate(
        {k: v for k, v in _publication().items() if k != "review_id"}).review_id is None
    with pytest.raises(ValidationError, match="review_id"):
        m.Publication.model_validate(dict(_publication(), review_id=0))


def test_history_must_replay_each_round_to_its_stored_phase(m):
    m.ReviewFlow.model_validate(_flow(history=_chain(1, "published")))
    with pytest.raises(ValidationError, match="history"):
        m.ReviewFlow.model_validate(_flow(history=_chain(1, "result")))
    skipped = [entry for entry in _chain(1, "published") if entry["target"] != "lanes"]
    with pytest.raises(ValidationError, match="history"):
        m.ReviewFlow.model_validate(_flow(history=skipped))
    with pytest.raises(ValidationError, match="history"):
        m.ReviewFlow.model_validate(_flow(history=_chain(1, "published")[1:]))
    jump = [*_chain(1, "context"), dict(_chain(1, "change_model")[1], target="published")]
    with pytest.raises(ValidationError, match="history"):
        m.ReviewFlow.model_validate(_flow(history=jump))
    second = _round(n=2, head_sha="b" * 40, phase="lanes", published=None,
                    lanes=_lanes(qa="pending"), findings=[])
    two = _flow(rounds=[_round(phase="reply_analysis"), second],
                history=_chain(1, "reply_analysis") + _chain(2, "lanes"))
    assert m.ReviewFlow.model_validate(two).rounds[-1].phase is m.Phase.LANES
    with pytest.raises(ValidationError, match="round 2"):
        m.ReviewFlow.model_validate(dict(two, history=_chain(1, "reply_analysis")))


def test_anchor_cap_space_is_stable_through_serialization(m):
    raw = "x" * (m.ANCHOR_LIMIT - 1) + " trailing"
    finding = m.Finding.model_validate(_anchored(m, 1, raw))
    assert finding.location.anchor == "x" * (m.ANCHOR_LIMIT - 1)
    restored = m.Finding.model_validate_json(finding.model_dump_json())
    assert restored.fingerprint == finding.fingerprint


def test_history_rejects_opening_next_round_before_reply_analysis(m):
    second = _round(n=2, head_sha="b" * 40, phase="context", published=None,
                    lanes=_lanes(qa="pending"), findings=[])
    first_chain = _chain(1, "reply_analysis")
    data = _flow(rounds=[_round(phase="reply_analysis"), second],
                 history=first_chain[:-1] + _chain(2, "context") + first_chain[-1:])
    with pytest.raises(ValidationError, match="history"):
        m.ReviewFlow.model_validate(data)
    data["history"] = first_chain + _chain(2, "context")
    assert len(m.ReviewFlow.model_validate(data).rounds) == 2


@pytest.mark.parametrize("left,right,conflicts", [
    ("src/[!ab].py", "src/[ab].py", False),
    ("src/[ab].py", "src/[!ab].py", False),
    ("src/[!a].py", "src/[ab].py", True),
])
def test_rule_filter_respects_negated_character_classes(m, left, right, conflicts):
    rules = m.RulesFile.model_validate(_rules_file(rules=[
        _active("R-1", "require", ["perf"], [left]),
        _active("R-2", "suppress", ["perf"], [right]),
    ]))
    assert [r.id for r in m.lane_rules(rules)] == ([] if conflicts else ["R-1", "R-2"])
