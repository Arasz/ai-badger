"""Review-flow state machine: declared transitions, named guards, lane merge, integrate, global scope.

Pure functions over `review_flow_model`; no I/O and no clock. Every operation returns a new,
re-validated `ReviewFlow` or `Round`, or raises `TransitionRefused` with a guard id as `code`.
The verdict is `review_flow_model.verdict`; this module never computes another.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import review_flow_model as model  # pylint: disable=wrong-import-position
import review_rules  # pylint: disable=wrong-import-position
from pydantic import TypeAdapter  # pylint: disable=wrong-import-position

Phase = model.Phase

TRANSITIONS = model.TRANSITIONS

STRONG_GRADES = (model.Grade.MEASURED, model.Grade.READ)
"""Fact grades the script applies on its own and that may back dropping a blocker."""

OPERATIONS = ("advance", "submit", "next_round", "publish", "global_scope")


class TransitionRefused(Exception):
    """A refused move or submission; `code` is the guard id or `undeclared_transition`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Request:
    """What an operation asks for; each guard reads the fields it needs."""

    op: str
    target: Optional[Phase] = None
    round_n: Optional[int] = None
    phase: Optional[Phase] = None
    head_sha: Optional[str] = None
    dispositions: Mapping[str, dict] = field(default_factory=dict)
    rules_file: Optional["model.RulesFile"] = None
    lane: Optional["model.Lane"] = None
    findings: Sequence["model.Finding"] = ()
    error: Optional[str] = None
    rules_digest: Optional[str] = None


@dataclass(frozen=True)
class Guard:
    """One named precondition: `check` returns a refusal message, or None to allow."""

    id: str
    op: str
    target: Optional[Phase]
    check: Callable[["model.ReviewFlow", Request], Optional[str]]


@dataclass(frozen=True)
class _OpenRound:
    """The view a round-level guard reads: the round as the last of `rounds`."""

    rounds: Tuple["model.Round", ...]


_DISPOSITION = TypeAdapter(model.Disposition)


# ------------------------------------------------------------------ guard checks


def _lanes_pending(flow: "model.ReviewFlow", _req: Request) -> Optional[str]:
    pending = [lane.value for lane, run in flow.rounds[-1].lanes.items() if run.status == "pending"]
    return f"lanes still pending: {pending}" if pending else None


def _missing_disposition(flow: "model.ReviewFlow", _req: Request) -> Optional[str]:
    missing = [f.fingerprint for f in flow.rounds[-1].findings if f.disposition is None]
    return f"findings without a disposition: {missing}" if missing else None


def _wrong_round(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    current = flow.rounds[-1].n
    return None if req.round_n == current else \
        f"submission is for round {req.round_n}; the open round is {current}"


def _wrong_phase(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    current = flow.rounds[-1].phase
    return None if req.phase is current else \
        f"submission is for {req.phase.value}; round is at {current.value}"


def _unknown_ref(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    fingerprints = {f.fingerprint for f in flow.rounds[-1].findings}
    rules_file = req.rules_file
    facts = {fact.id for fact in rules_file.facts} if rules_file else set()
    rules = {rule.id: rule.status for rule in rules_file.rules} if rules_file else {}
    for fingerprint, disposition in req.dispositions.items():
        if fingerprint not in fingerprints:
            return f"no finding {fingerprint[:12]} in round {flow.rounds[-1].n}"
        for ref in disposition.get("basis") or []:
            ref_id = ref.get("id")
            if ref.get("type") == "fact" and ref_id not in facts:
                return f"no fact {ref_id}"
            if ref.get("type") == "rule" and rules.get(ref_id) != "active":
                state = rules.get(ref_id, "unknown")
                return f"rule {ref_id} is {state}; only an active rule is a basis"
    return None


def _basis_out_of_scope(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    findings = {f.fingerprint: f for f in flow.rounds[-1].findings}
    rules_file = req.rules_file
    scopes = {("fact", fact.id): fact.applies for fact in rules_file.facts} if rules_file else {}
    scopes.update({("rule", rule.id): rule.applies for rule in rules_file.rules}
                  if rules_file else {})
    for fingerprint, disposition in req.dispositions.items():
        for ref in disposition.get("basis") or []:
            applies = scopes.get((ref.get("type"), ref.get("id")))
            if applies is not None and not review_rules.matches(applies, findings[fingerprint]):
                return (f"{ref.get('id')} does not cover finding {fingerprint[:12]}; a scoped "
                        "basis must match the finding it disposes")
    return None


def _already_decided(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    findings = {f.fingerprint: f for f in flow.rounds[-1].findings}
    for fingerprint, disposition in req.dispositions.items():
        current = findings[fingerprint].disposition
        if current is not None and current.model_dump(mode="json") != \
                _DISPOSITION.validate_python(disposition).model_dump(mode="json"):
            return (f"finding {fingerprint[:12]} already has a {current.action} disposition; "
                    "only an identical replay is accepted")
    return None


def _lane_disposition(_flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    decided = [f.fingerprint[:12] for f in req.findings if f.disposition is not None]
    return f"lane findings carry a disposition: {decided}" if decided else None


def _lane_done(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    if req.lane is None or flow.rounds[-1].lanes[req.lane].status != "done":
        return None
    saved = flow.rounds[-1].lanes[req.lane].submission_digest
    if saved is not None and saved == _submission_digest(req.findings, req.error):
        return None
    return f"lane {req.lane.value} is done; only an identical replay is accepted"


def _digest_changed(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    current = flow.rounds[-1]
    if current.scope_brief_digest not in (None, req.rules_digest):
        return "rules changed since the global_scope brief; generate a new brief"
    retained = any(getattr(f.disposition, "by", None) == "script" or
                   isinstance(f.disposition, model.Keep) for f in current.findings)
    if retained and current.rules_digest not in (None, req.rules_digest):
        return (f"round {current.n} was judged against rules {current.rules_digest[:12]}; "
                f"a new digest {req.rules_digest[:12]} would keep the old dispositions")
    return None


def _weak_blocker_drop(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    findings = {f.fingerprint: f for f in flow.rounds[-1].findings}
    grades = {fact.id: fact.grade for fact in req.rules_file.facts} if req.rules_file else {}
    for fingerprint, disposition in req.dispositions.items():
        finding = findings.get(fingerprint)
        if disposition.get("action") != "drop" or finding is None \
                or finding.severity is not model.Severity.BLOCKER:
            continue
        basis = disposition.get("basis") or []
        strong = [ref for ref in basis
                  if ref.get("type") == "rule" or grades.get(ref.get("id")) in STRONG_GRADES]
        if not strong:
            return (f"blocker {fingerprint[:12]} dropped on INFERRED or UNVERIFIED facts only: "
                    f"{[ref.get('id') for ref in basis]}")
    return None


def _same_head(flow: "model.ReviewFlow", req: Request) -> Optional[str]:
    seen = [r.n for r in flow.rounds if r.head_sha == req.head_sha]
    return f"head {req.head_sha} was already reviewed in round {seen[0]}" if seen else None


def _round_not_finished(flow: "model.ReviewFlow", _req: Request) -> Optional[str]:
    phase = flow.rounds[-1].phase
    return None if phase is Phase.REPLY_ANALYSIS else \
        f"round {flow.rounds[-1].n} is at {phase.value}; a new round opens from reply_analysis"


def _publish_before_result(flow: "model.ReviewFlow", _req: Request) -> Optional[str]:
    phase = flow.rounds[-1].phase
    if model.PHASE_RANK[phase] < model.PHASE_RANK[Phase.RESULT]:
        return f"round {flow.rounds[-1].n} is at {phase.value}; publish needs result"
    return None


GUARDS: Tuple[Guard, ...] = (
    Guard("lanes_pending", "advance", Phase.INTEGRATE, _lanes_pending),
    Guard("missing_disposition", "advance", Phase.RESULT, _missing_disposition),
    Guard("wrong_round", "submit", None, _wrong_round),
    Guard("wrong_phase", "submit", None, _wrong_phase),
    Guard("unknown_ref", "submit", None, _unknown_ref),
    Guard("basis_out_of_scope", "submit", None, _basis_out_of_scope),
    Guard("already_decided", "submit", None, _already_decided),
    Guard("weak_blocker_drop", "submit", None, _weak_blocker_drop),
    Guard("lane_disposition", "submit", None, _lane_disposition),
    Guard("lane_done", "submit", None, _lane_done),
    Guard("digest_changed", "global_scope", None, _digest_changed),
    Guard("round_not_finished", "next_round", None, _round_not_finished),
    Guard("same_head", "next_round", None, _same_head),
    Guard("publish_before_result", "publish", None, _publish_before_result),
)
"""Every precondition, in the order checked; the first refusal wins."""


def _enforce(flow: "model.ReviewFlow", req: Request) -> None:
    for guard in GUARDS:
        if guard.op != req.op or guard.target not in (None, req.target):
            continue
        message = guard.check(flow, req)
        if message is not None:
            raise TransitionRefused(guard.id, message)


# ------------------------------------------------------------------ helpers


def _stamp(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return now.astimezone(timezone.utc).isoformat(timespec="seconds")


def _trigger(trigger: str) -> str:
    if not isinstance(trigger, str) or not trigger.strip():
        raise ValueError("trigger must be a non-empty string")
    return trigger


def _with_last_round(flow: "model.ReviewFlow", round_data: dict,
                     transition: Optional[dict] = None) -> "model.ReviewFlow":
    data = flow.model_dump(mode="json")
    data["rounds"][-1] = round_data
    if transition is not None:
        data["history"].append(transition)
    return model.ReviewFlow.model_validate(data)


# ------------------------------------------------------------------ moves


def advance(flow: "model.ReviewFlow", target: Phase, trigger: str, now: datetime,
            publication: Optional["model.Publication"] = None) -> "model.ReviewFlow":
    """Move the open round to `target` along a declared edge; `publication` goes with `published`."""
    at, trigger = _stamp(now), _trigger(trigger)
    current = flow.rounds[-1]
    if target not in TRANSITIONS[current.phase]:
        raise TransitionRefused("undeclared_transition",
                                f"{current.phase.value} -> {target.value} is not declared")
    _enforce(flow, Request(op="advance", target=target))
    round_data = current.model_dump(mode="json")
    round_data["phase"] = target.value
    if publication is not None:
        round_data["published"] = publication.model_dump(mode="json")
    return _with_last_round(flow, round_data, {"round": current.n, "source": current.phase.value,
                                               "target": target.value, "at": at,
                                               "trigger": trigger})


def next_round(flow: "model.ReviewFlow", head_sha: str, trigger: str,
               now: datetime) -> "model.ReviewFlow":
    """Open round n+1 at `context` for a new head, with every lane pending."""
    at, trigger = _stamp(now), _trigger(trigger)
    _enforce(flow, Request(op="next_round", head_sha=head_sha))
    n = flow.rounds[-1].n + 1
    data = flow.model_dump(mode="json")
    data["rounds"].append({"n": n, "head_sha": head_sha, "phase": Phase.CONTEXT.value,
                           "lanes": {lane.value: {"status": "pending"} for lane in model.Lane},
                           "findings": [], "replies": []})
    data["history"].append({"round": n, "source": None, "target": Phase.CONTEXT.value,
                            "at": at, "trigger": trigger})
    return model.ReviewFlow.model_validate(data)


def check_publish(flow: "model.ReviewFlow") -> None:
    """Refuse publishing a round that has not reached `result`."""
    _enforce(flow, Request(op="publish"))


# ------------------------------------------------------------------ submissions


def _union(items: Sequence, key: Callable = lambda item: item) -> list:
    seen, out = set(), []
    for item in items:
        if key(item) not in seen:
            seen.add(key(item))
            out.append(item)
    return out


def merge_findings(findings: Sequence["model.Finding"]) -> List[dict]:
    """One finding per fingerprint: the most severe one's text, with lanes and evidence unioned."""
    groups: Dict[str, List["model.Finding"]] = {}
    for finding in findings:
        groups.setdefault(finding.fingerprint, []).append(finding)
    merged = []
    for group in groups.values():
        base = max(group, key=lambda f: model.RANK[f.severity])  # first wins a tie
        data = base.model_dump(mode="json")
        lanes = {lane for f in group for lane in f.lanes}
        data["lanes"] = [lane.value for lane in model.Lane if lane in lanes]
        data["evidence"] = _union([e.model_dump(mode="json") for f in group for e in f.evidence],
                                  key=lambda e: (e["grade"], e["ref"]))
        data["ac_refs"] = _union([ref for f in group for ref in f.ac_refs])
        data["tags"] = sorted({tag.value for f in group for tag in f.tags})
        merged.append(data)
    return merged


def _submission_digest(findings: Sequence["model.Finding"], error: Optional[str]) -> str:
    payload = {"findings": [f.model_dump(mode="json", by_alias=True) for f in findings],
               "error": error}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _lane_result(current: "model.Round", lane: "model.Lane", findings: Sequence["model.Finding"],
                 error: Optional[str]) -> dict:
    round_data = current.model_dump(mode="json")
    round_data["lanes"][lane.value] = {"status": "failed", "error": error} if error \
        else {"status": "done", "error": None,
              "submission_digest": _submission_digest(findings, error)}
    if not error:
        round_data["findings"] = merge_findings([*current.findings, *findings])
    return round_data


def submit_lane(flow: "model.ReviewFlow", round_n: int, lane: "model.Lane",
                findings: Sequence["model.Finding"],
                error: Optional[str] = None) -> "model.ReviewFlow":
    """Record one lane's result in the `lanes` phase; findings merge by fingerprint on arrival.

    A lane takes a submission while pending or failed; a done lane takes only an identical replay.
    """
    _enforce(flow, Request(op="submit", round_n=round_n, phase=Phase.LANES, lane=lane,
                           findings=tuple(findings), error=error))
    if flow.rounds[-1].lanes[lane].status == "done":
        return flow
    return _with_last_round(flow, _lane_result(flow.rounds[-1], lane, findings, error))


def submit_dispositions(flow: "model.ReviewFlow", round_n: int, dispositions: Mapping[str, dict],
                        rules_file: "model.RulesFile") -> "model.ReviewFlow":
    """Apply a worker's dispositions in `global_scope`, keyed by fingerprint."""
    _enforce(flow, Request(op="submit", round_n=round_n, phase=Phase.GLOBAL_SCOPE,
                           dispositions=dispositions, rules_file=rules_file))
    round_data = flow.rounds[-1].model_dump(mode="json")
    for item in round_data["findings"]:
        if item["fingerprint"] in dispositions:
            item["disposition"] = dict(dispositions[item["fingerprint"]])
    return _with_last_round(flow, round_data)


# ------------------------------------------------------------------ integrate and global scope


def _overlaps(left: "model.Finding", right: "model.Finding") -> bool:
    a, b = left.location, right.location
    return a.path == b.path and a.start <= b.end and b.start <= a.end


def integrate(round_: "model.Round") -> Tuple["model.Round", List[Tuple[str, ...]]]:
    """Clusters of distinct fingerprints whose ranges overlap in one file, for a worker merge.

    Same-fingerprint findings already merged when their lanes submitted (`merge_findings`), since
    a round never holds a fingerprint twice.
    """
    findings = round_.findings
    parent = list(range(len(findings)))

    def root(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for i, left in enumerate(findings):
        for j in range(i + 1, len(findings)):
            if _overlaps(left, findings[j]):
                parent[root(j)] = root(i)
    groups: Dict[int, List[str]] = {}
    for i, finding in enumerate(findings):
        groups.setdefault(root(i), []).append(finding.fingerprint)
    clusters = [tuple(group) for group in groups.values() if len(group) > 1]
    return round_, clusters


def _effects(finding: "model.Finding", rules_file: "model.RulesFile"):
    facts = [(model.Ref(type="fact", id=fact.id), fact.statement, fact.effect)
             for fact in rules_file.facts
             if fact.effect is not None and fact.grade in STRONG_GRADES
             and review_rules.matches(fact.applies, finding)]
    rules = [(model.Ref(type="rule", id=rule.id), rule.statement, rule.effect)
             for rule in model.lane_rules(rules_file) if review_rules.matches(rule.applies, finding)]
    return facts + rules


def _script_disposition(finding: "model.Finding",
                        rules_file: "model.RulesFile") -> Tuple[Optional[dict], bool]:
    """The script's disposition for one finding, and whether it adds the DEFENSIVE tag."""
    effects = _effects(finding, rules_file)
    if any(effect.action == "require" for _, _, effect in effects):
        return {"action": "keep"}, False
    for ref, statement, effect in effects:
        base = {"ground": effect.ground.value, "reason": f"{ref.id}: {statement}",
                "basis": [ref.model_dump(mode="json")], "by": "script"}
        if effect.action == "suppress":
            return {"action": "drop", **base}, False
        if model.RANK[effect.to] < model.RANK[finding.severity]:
            defensive = effect.ground is model.Ground.UNREACHABLE_IN_PRODUCTION
            return {"action": "downgrade", "to": effect.to.value, **base}, defensive
    return None, False


def global_scope(round_: "model.Round", rules_file: "model.RulesFile",
                 rules_digest: str) -> Tuple["model.Round", List["model.Finding"]]:
    """Apply strong facts and active rules by script; return the findings left for the worker.

    Scope is `review_rules.matches` only. A finding that already has a disposition is untouched;
    dropped findings stay in the round. A round the script already judged keeps its digest.
    """
    _enforce(_OpenRound((round_,)), Request(op="global_scope", rules_digest=rules_digest))
    round_data = round_.model_dump(mode="json")
    round_data["rules_digest"] = rules_digest
    for finding, item in zip(round_.findings, round_data["findings"]):
        if finding.disposition is not None:
            continue
        disposition, defensive = _script_disposition(finding, rules_file)
        item["disposition"] = disposition
        if defensive:
            item["tags"] = sorted({*item["tags"], model.Tag.DEFENSIVE.value})
    judged = model.Round.model_validate(round_data)
    return judged, [f for f in judged.findings if f.disposition is None]
