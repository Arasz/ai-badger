"""Typed review-flow model: flow state, findings, learned rules, severity map and verdict.

`schemas/review-flow.schema.json` and `schemas/review-rules.schema.json` (emitted by
`tooling/review_flow_schema.py`) are projections of `ReviewFlow` and `RulesFile`. Cross-field
rules (fingerprint recomputation, phase ranks, rule activation proof) are pydantic-only.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import (AfterValidator, BaseModel, ConfigDict, Field, field_serializer,
                      model_validator)

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_render import HUMAN_LINE_LIMIT  # pylint: disable=wrong-import-position

__all__ = ["HUMAN_LINE_LIMIT"]

MODULE_SYMBOL = "<module>"
"""The `Location.symbol` for a finding that sits outside any named symbol."""

RULE_STATEMENT_LIMIT = 500
ANCHOR_LIMIT = 200
HEAD_SHA_PATTERN = r"^[0-9a-f]{7,40}$"
DIGEST_PATTERN = r"^[0-9a-f]{64}$"

_FORBID = ConfigDict(extra="forbid", populate_by_name=True)


class Kind(str, Enum):
    """Closed finding kind; rules and facts match on it, never on `other`."""

    NULL_DEREF = "null_deref"
    UNCHECKED_ERROR = "unchecked_error"
    RESOURCE_LEAK = "resource_leak"
    CONCURRENCY = "concurrency"
    INJECTION = "injection"
    AUTHZ = "authz"
    INPUT_VALIDATION = "input_validation"
    CONTRACT_BREAK = "contract_break"
    AC_UNMET = "ac_unmet"
    TEST_GAP = "test_gap"
    PERF = "perf"
    CONFIG = "config"
    DEAD_CODE = "dead_code"
    STYLE = "style"
    DOCS = "docs"
    OTHER = "other"


class Severity(str, Enum):
    """Ordered severity; `RANK` gives the order, higher is worse."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"


RANK = {Severity.NIT: 0, Severity.MINOR: 1, Severity.MAJOR: 2, Severity.BLOCKER: 3}


class Grade(str, Enum):
    """How a piece of evidence or a fact is known."""

    MEASURED = "MEASURED"
    READ = "READ"
    INFERRED = "INFERRED"
    UNVERIFIED = "UNVERIFIED"


class Ground(str, Enum):
    """Why a finding was downgraded or dropped."""

    FACT_CONTRADICTS = "fact_contradicts"
    UNREACHABLE_IN_PRODUCTION = "unreachable_in_production"
    RULE = "rule"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"


class Tag(str, Enum):
    """Stored finding tags; out-of-diff and learned-rule marks are derived, not stored."""

    DEFENSIVE = "DEFENSIVE"
    PRE_EXISTING = "PRE_EXISTING"


class Lane(str, Enum):
    """The four parallel review lanes."""

    BUSINESS = "business"
    QA = "qa"
    ARCHITECTURE = "architecture"
    QUALITY = "quality"


class Phase(str, Enum):
    """Round phases in order; `PHASE_RANK` gives the position."""

    CONTEXT = "context"
    CHANGE_MODEL = "change_model"
    LANES = "lanes"
    INTEGRATE = "integrate"
    GLOBAL_SCOPE = "global_scope"
    RESULT = "result"
    PUBLISHED = "published"
    AWAITING_AUTHOR = "awaiting_author"
    REPLY_ANALYSIS = "reply_analysis"
    CLOSED = "closed"


PHASE_RANK = {phase: index for index, phase in enumerate(Phase)}

TRANSITIONS: Dict[Phase, Tuple[Phase, ...]] = {
    Phase.CONTEXT: (Phase.CHANGE_MODEL,),
    Phase.CHANGE_MODEL: (Phase.LANES,),
    Phase.LANES: (Phase.INTEGRATE,),
    Phase.INTEGRATE: (Phase.GLOBAL_SCOPE,),
    Phase.GLOBAL_SCOPE: (Phase.RESULT,),
    Phase.RESULT: (Phase.PUBLISHED,),
    Phase.PUBLISHED: (Phase.AWAITING_AUTHOR,),
    Phase.AWAITING_AUTHOR: (Phase.REPLY_ANALYSIS,),
    Phase.REPLY_ANALYSIS: (Phase.CLOSED,),
    Phase.CLOSED: (),
}
"""In-round moves. A round opens at `context` with no source; the next round opens from
`reply_analysis` through `next_round`, not along this table."""


class Verdict(str, Enum):
    """Round verdict, derived by `verdict`; never stored on the model."""

    BLOCK = "Block"
    FIX = "Fix before merge"
    SAFE = "Safe to merge"


# ------------------------------------------------------------------ severity vocabularies

CHECKLIST = {"Critical": Severity.BLOCKER, "High": Severity.MAJOR,
             "Medium": Severity.MINOR, "Low": Severity.NIT}
"""`code-review-checklist` labels."""
LANE_BRIEF = {"BLOCKER": Severity.BLOCKER, "HIGH": Severity.MAJOR, "MEDIUM": Severity.MINOR,
              "LOW": Severity.NIT, "NIT": Severity.NIT}
"""`complete-project-scope-code-review` lane-brief labels."""
DESIGN_GATE_AUDIT = {"MUST-FIX": Severity.BLOCKER, "SHOULD-FIX": Severity.MAJOR,
                     "NIT": Severity.NIT}
"""`design-gate-audit` labels."""
REVIEW_GATE_DIFF_VERIFICATION = dict(DESIGN_GATE_AUDIT)
"""`review-gate-diff-verification` labels (same words as the design gate)."""
REVIEW_TESTS = {"blocker": Severity.BLOCKER, "major": Severity.MAJOR, "minor": Severity.MINOR}
"""`review-tests` labels."""

VOCABULARIES: Dict[str, Dict[str, Severity]] = {
    "checklist": CHECKLIST,
    "lane_brief": LANE_BRIEF,
    "design_gate_audit": DESIGN_GATE_AUDIT,
    "review_gate_diff_verification": REVIEW_GATE_DIFF_VERIFICATION,
    "review_tests": REVIEW_TESTS,
}


def normalise_severity(vocab: str, label: str) -> Severity:
    """Map a source vocabulary's label to `Severity`; unknown vocabularies and labels raise."""
    table = VOCABULARIES.get(vocab)
    if table is None:
        raise ValueError(f"unknown severity vocabulary {vocab!r}; known: {sorted(VOCABULARIES)}")
    if label not in table:
        raise ValueError(f"{label!r} is not a {vocab} severity; known: {list(table)}")
    return table[label]


def normalise_anchor(text: str) -> str:
    """Anchor text as stored: whitespace runs collapsed to one space, cut to `ANCHOR_LIMIT`."""
    anchor = " ".join(text.split())[:ANCHOR_LIMIT]
    if not anchor:
        raise ValueError("anchor is blank; omit it instead")
    return anchor


def fingerprint_of(kind: Union[Kind, str], path: str, symbol: str,
                   anchor: Optional[str] = None) -> str:
    """The finding fingerprint: sha256 hex of `kind|path|symbol`, or of the JSON array
    `[kind, path, symbol, anchor]` when anchored, so a `|` inside a field cannot collide."""
    kind_value = kind.value if isinstance(kind, Kind) else kind
    key = f"{kind_value}|{path}|{symbol}"
    if anchor is not None:
        key = json.dumps([kind_value, path, symbol, normalise_anchor(anchor)])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _validate_utc(value: str) -> str:
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{value!r} is not an ISO-8601 timestamp: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{value!r} is not UTC; use a +00:00 or Z offset")
    return value


UtcTimestamp = Annotated[str, AfterValidator(_validate_utc)]


# ------------------------------------------------------------------ rule grammar


class Applies(BaseModel):
    """Which findings a rule or fact covers: a conjunction of fnmatch globs."""

    model_config = _FORBID

    kinds: List[Kind] = Field(min_length=1)
    paths: List[str] = Field(min_length=1)
    symbols: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _never_other(self) -> "Applies":
        if Kind.OTHER in self.kinds:
            raise ValueError("kind 'other' is never matched by a rule or fact")
        return self


class Effect(BaseModel):
    """What a matching rule or fact does to a finding."""

    model_config = _FORBID

    action: Literal["require", "suppress", "downgrade"]
    to: Optional[Severity] = None
    ground: Ground

    @model_validator(mode="after")
    def _consistent(self) -> "Effect":
        if (self.action == "downgrade") != (self.to is not None):
            raise ValueError("'to' is required for downgrade and forbidden otherwise")
        if self.ground is Ground.UNREACHABLE_IN_PRODUCTION and self.action != "downgrade":
            raise ValueError("ground unreachable_in_production must use action downgrade")
        return self


class Ref(BaseModel):
    """A basis reference to a fact (`F-n`) or a rule (`R-n`)."""

    model_config = _FORBID

    type: Literal["fact", "rule"]
    id: str = Field(pattern=r"^[FR]-[1-9][0-9]*$")

    @model_validator(mode="after")
    def _prefix(self) -> "Ref":
        prefix = "F-" if self.type == "fact" else "R-"
        if not self.id.startswith(prefix):
            raise ValueError(f"a {self.type} ref id starts with {prefix!r}: {self.id!r}")
        return self


class Keep(BaseModel):
    """Disposition: the finding stands at its own severity."""

    model_config = _FORBID

    action: Literal["keep"]


class Downgrade(BaseModel):
    """Disposition: the finding stands at a lower severity, with its basis."""

    model_config = _FORBID

    action: Literal["downgrade"]
    to: Severity
    ground: Ground
    reason: str
    basis: List[Ref] = Field(min_length=1)
    by: Literal["script", "worker"]


class Drop(BaseModel):
    """Disposition: the finding is removed, with its basis."""

    model_config = _FORBID

    action: Literal["drop"]
    ground: Ground
    reason: str
    basis: List[Ref] = Field(min_length=1)
    by: Literal["script", "worker"]

    @model_validator(mode="after")
    def _not_unreachable(self) -> "Drop":
        if self.ground is Ground.UNREACHABLE_IN_PRODUCTION:
            raise ValueError("ground unreachable_in_production must downgrade, not drop")
        return self


Disposition = Annotated[Union[Keep, Downgrade, Drop], Field(discriminator="action")]


# ------------------------------------------------------------------ findings


class Location(BaseModel):
    """Where a finding sits; `symbol` is `MODULE_SYMBOL` outside any named symbol.

    `anchor` is the offending code text; it keeps two defects in one symbol apart.
    """

    model_config = _FORBID

    path: str = Field(min_length=1)
    start: int = Field(ge=1)
    end: int
    symbol: str = Field(min_length=1)
    anchor: Optional[Annotated[str, AfterValidator(normalise_anchor)]] = None

    @model_validator(mode="after")
    def _ordered(self) -> "Location":
        if self.end < self.start:
            raise ValueError(f"end {self.end} is before start {self.start}")
        return self


class Evidence(BaseModel):
    """One graded pointer that supports a finding."""

    model_config = _FORBID

    grade: Grade
    ref: str


class AgentPart(BaseModel):
    """The collapsed agent block of an inline comment; empty text renders as none."""

    model_config = _FORBID

    repro: str
    context: str
    fix: str


class Finding(BaseModel):
    """One review finding; its fingerprint must equal `fingerprint_of` its kind and location."""

    model_config = _FORBID

    fingerprint: str
    lanes: List[Lane]
    source: Literal["lane", "lint"]
    kind: Kind
    severity: Severity
    confidence: Literal["high", "medium", "low"]
    location: Location
    in_diff: bool
    title: str
    reason: str
    evidence: List[Evidence]
    agent: AgentPart
    ac_refs: List[str]
    tags: Set[Tag]
    disposition: Optional[Disposition] = None

    @field_serializer("tags")
    def _sorted_tags(self, tags: Set[Tag]) -> List[str]:
        return sorted(tag.value for tag in tags)

    @model_validator(mode="after")
    def _fingerprint(self) -> "Finding":
        location = self.location
        expected = fingerprint_of(self.kind, location.path, location.symbol, location.anchor)
        if self.fingerprint != expected:
            raise ValueError(f"fingerprint {self.fingerprint!r} is not the sha256 of "
                             f"kind|path|symbol, or of the JSON [kind, path, symbol, anchor] "
                             f"when anchored: {expected!r}")
        return self

    @model_validator(mode="after")
    def _lanes(self) -> "Finding":
        if len(set(self.lanes)) != len(self.lanes):
            raise ValueError(f"lanes repeat: {[lane.value for lane in self.lanes]}")
        if self.source == "lane" and not self.lanes:
            raise ValueError("a lane finding names at least one lane")
        return self

    @model_validator(mode="after")
    def _human_part(self) -> "Finding":
        if not self.title.strip() or "\n" in self.title:
            raise ValueError("title must be one non-empty line")
        lines = 2 + len([line for line in self.reason.splitlines() if line.strip()])
        if lines > HUMAN_LINE_LIMIT:
            raise ValueError(f"human part is {lines} lines, limit is {HUMAN_LINE_LIMIT}")
        return self

    @model_validator(mode="after")
    def _disposition(self) -> "Finding":
        disposition = self.disposition
        if isinstance(disposition, Downgrade) and RANK[disposition.to] >= RANK[self.severity]:
            raise ValueError(f"downgrade to {disposition.to.value} is not lower than "
                             f"{self.severity.value}")
        ground = getattr(disposition, "ground", None)
        if ground is Ground.UNREACHABLE_IN_PRODUCTION and Tag.DEFENSIVE not in self.tags:
            raise ValueError("ground unreachable_in_production requires the DEFENSIVE tag")
        return self

    @property
    def effective_severity(self) -> Optional[Severity]:
        """Severity after the disposition; None when dropped."""
        if isinstance(self.disposition, Drop):
            return None
        if isinstance(self.disposition, Downgrade):
            return self.disposition.to
        return self.severity


# ------------------------------------------------------------------ rounds and flow


class LaneRun(BaseModel):
    """One lane's run in a round; a failed run carries its error."""

    model_config = _FORBID

    status: Literal["pending", "done", "failed"]
    error: Optional[str] = None

    @model_validator(mode="after")
    def _error(self) -> "LaneRun":
        if (self.status == "failed") != bool(self.error):
            raise ValueError("error is required for a failed lane and forbidden otherwise")
        return self


class Publication(BaseModel):
    """The posted review; the event is always COMMENT; `review_id` is None when none was posted."""

    model_config = _FORBID

    review_id: Optional[int] = Field(default=None, ge=1)
    summary_comment_id: Optional[int] = None
    event: Literal["COMMENT"]
    at: UtcTimestamp


class AuthorReply(BaseModel):
    """One reply on a review thread, kept for reply analysis."""

    model_config = _FORBID

    thread_url: str
    comment_id: int
    author: str
    association: Literal["OWNER", "MEMBER", "COLLABORATOR", "CONTRIBUTOR",
                         "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN", "NONE"]
    body: str
    at: UtcTimestamp


def verdict(round_: "Round") -> Verdict:
    """Block on any blocker; Fix before merge on any major or any lane not done; else Safe."""
    severities = {finding.effective_severity for finding in round_.findings}
    if Severity.BLOCKER in severities:
        return Verdict.BLOCK
    if Severity.MAJOR in severities or any(run.status != "done" for run in round_.lanes.values()):
        return Verdict.FIX
    return Verdict.SAFE


class Round(BaseModel):
    """One review pass over one head sha; the phase lives here."""

    model_config = _FORBID

    n: int = Field(ge=1)
    head_sha: str = Field(pattern=HEAD_SHA_PATTERN)
    phase: Phase
    rules_digest: Optional[str] = Field(default=None, pattern=DIGEST_PATTERN)
    lanes: Dict[Lane, LaneRun]
    findings: List[Finding]
    replies: List[AuthorReply]
    published: Optional[Publication] = None

    @model_validator(mode="after")
    def _by_phase(self) -> "Round":
        missing = [lane.value for lane in Lane if lane not in self.lanes]
        if missing:
            raise ValueError(f"round {self.n} has no run for lanes {missing}")
        rank = PHASE_RANK[self.phase]
        if rank >= PHASE_RANK[Phase.INTEGRATE]:
            pending = [lane.value for lane, run in self.lanes.items() if run.status == "pending"]
            if pending:
                raise ValueError(f"round {self.n} is at {self.phase.value} with lanes "
                                 f"still pending: {pending}")
        if rank >= PHASE_RANK[Phase.RESULT]:
            undisposed = [f.fingerprint for f in self.findings if f.disposition is None]
            if undisposed:
                raise ValueError(f"round {self.n} is at {self.phase.value}; findings without "
                                 f"a disposition: {undisposed}")
            if self.rules_digest is None:
                raise ValueError(f"round {self.n} is at {self.phase.value}; rules_digest unset")
        if (rank >= PHASE_RANK[Phase.PUBLISHED]) != (self.published is not None):
            raise ValueError(f"round {self.n} at {self.phase.value}: a published round has a "
                             "Publication, and only a published round has one")
        seen: Set[str] = set()
        for finding in self.findings:
            if finding.fingerprint in seen:
                raise ValueError(f"round {self.n} repeats fingerprint {finding.fingerprint}")
            seen.add(finding.fingerprint)
        return self

    @property
    def verdict(self) -> Verdict:
        """Derived from effective severities and lane runs; never stored."""
        return verdict(self)


class AcceptanceItem(BaseModel):
    """One acceptance criterion the business lane checks the change against."""

    model_config = _FORBID

    id: str
    statement: str


class Transition(BaseModel):
    """One recorded phase move; `source` is None for the move that opens a round."""

    model_config = _FORBID

    round: int = Field(ge=1)
    source: Optional[Phase] = None
    target: Phase
    at: UtcTimestamp
    trigger: str


class ReviewFlow(BaseModel):
    """The persisted review of one pull request across its rounds."""

    model_config = _FORBID

    schema_: Optional[str] = Field(default=None, alias="$schema")
    schema_version: Literal[1]
    flow_id: str = Field(min_length=1)
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    pr: int = Field(ge=1)
    issue_refs: List[str]
    ac_source: Literal["tool", "pasted", "absent"]
    acs: List[AcceptanceItem]
    rounds: List[Round] = Field(min_length=1)
    history: List[Transition]

    @model_validator(mode="after")
    def _consistent(self) -> "ReviewFlow":
        if (self.ac_source == "absent") != (not self.acs):
            raise ValueError("ac_source is absent exactly when acs is empty")
        if [r.n for r in self.rounds] != list(range(1, len(self.rounds) + 1)):
            raise ValueError("rounds must be numbered 1..n in order")
        shas = [r.head_sha for r in self.rounds]
        if len(set(shas)) != len(shas):
            raise ValueError(f"head_sha repeats across rounds: {shas}")
        early = [r.n for r in self.rounds[:-1] if r.phase is not Phase.REPLY_ANALYSIS]
        if early:
            raise ValueError(f"only the last round may be open; rounds {early} did not reach "
                             "reply_analysis")
        unknown = sorted({t.round for t in self.history} - {r.n for r in self.rounds})
        if unknown:
            raise ValueError(f"history names round {unknown[0]}, which does not exist")
        for round_ in self.rounds:
            _replays(round_, [t for t in self.history if t.round == round_.n])
        return self


def _replays(round_: Round, moves: List[Transition]) -> None:
    """Refuse history that does not open `round_` at context and walk declared edges to its phase."""
    reached: Optional[Phase] = None
    for move in moves:
        opens = move.source is None and move.target is Phase.CONTEXT
        if (reached is None and not opens) or (reached is not None and (
                move.source is not reached or move.target not in TRANSITIONS[reached])):
            source = move.source.value if move.source else None
            raise ValueError(f"history of round {round_.n}: {source} -> {move.target.value} "
                             f"does not follow {reached.value if reached else 'the opening'}")
        reached = move.target
    if reached is not round_.phase:
        raise ValueError(f"history of round {round_.n} ends at "
                         f"{reached.value if reached else 'nothing'}, the round is at "
                         f"{round_.phase.value}")


# ------------------------------------------------------------------ rules file


class Origin(BaseModel):
    """The review thread a rule was taught in."""

    model_config = _FORBID

    pr: int = Field(ge=1)
    thread_url: str
    author: str
    association: Literal["OWNER", "MEMBER", "COLLABORATOR"]
    quote: str


class Citation(BaseModel):
    """Code the script verified at the base ref to activate a rule."""

    model_config = _FORBID

    path: str = Field(min_length=1)
    start: int = Field(ge=1)
    end: int

    @model_validator(mode="after")
    def _ordered(self) -> "Citation":
        if self.end < self.start:
            raise ValueError(f"end {self.end} is before start {self.start}")
        return self


def _independent(origins: List[Origin]) -> bool:
    return any(a.thread_url != b.thread_url and a.author != b.author
               for i, a in enumerate(origins) for b in origins[i + 1:])


class LearnedRule(BaseModel):
    """A rule taught by review replies; only an activated rule reaches the lanes."""

    model_config = _FORBID

    id: str = Field(pattern=r"^R-[1-9][0-9]*$")
    status: Literal["proposed", "active", "retired"]
    statement: str = Field(min_length=1, max_length=RULE_STATEMENT_LIMIT)
    applies: Applies
    effect: Effect
    origins: List[Origin] = Field(min_length=1)
    activated_by: Optional[Literal["maintainer", "citation", "threads"]] = None
    citation: Optional[Citation] = None

    @model_validator(mode="after")
    def _activation(self) -> "LearnedRule":
        if (self.status != "proposed") != (self.activated_by is not None):
            raise ValueError(f"rule {self.id}: activated_by is set exactly when the rule is "
                             "active or retired")
        if self.activated_by == "citation" and self.citation is None:
            raise ValueError(f"rule {self.id}: activation by citation needs a citation")
        if self.activated_by == "threads" and not _independent(self.origins):
            raise ValueError(f"rule {self.id}: activation by threads needs two origins in "
                             "distinct threads by distinct authors")
        return self


class ProjectFact(BaseModel):
    """A graded fact about the whole system; applies and effect come together or not at all."""

    model_config = _FORBID

    id: str = Field(pattern=r"^F-[1-9][0-9]*$")
    statement: str = Field(min_length=1)
    grade: Grade
    evidence_ref: str
    applies: Optional[Applies] = None
    effect: Optional[Effect] = None

    @model_validator(mode="after")
    def _paired(self) -> "ProjectFact":
        if (self.applies is None) != (self.effect is None):
            raise ValueError(f"fact {self.id}: set both applies and effect, or neither")
        return self


def _ids_ascending(ids: List[str]) -> None:
    numbers = [int(item.split("-", 1)[1]) for item in ids]
    for previous, current, item in zip(numbers, numbers[1:], ids[1:]):
        if current == previous:
            raise ValueError(f"id {item} is used twice")
        if current < previous:
            raise ValueError(f"id {item} is out of order; ids only grow")


class RulesFile(BaseModel):
    """`.ai-badger/review/rules.json`: learned rules and project facts, retired never deleted."""

    model_config = _FORBID

    schema_: Optional[str] = Field(default=None, alias="$schema")
    schema_version: Literal[1]
    rules: List[LearnedRule]
    facts: List[ProjectFact]

    @model_validator(mode="after")
    def _ids(self) -> "RulesFile":
        _ids_ascending([rule.id for rule in self.rules])
        _ids_ascending([fact.id for fact in self.facts])
        return self


def _glob_tokens(glob: str) -> List[Tuple[str, str]]:
    """fnmatch tokens as (kind, chars): `*`, `?`, `lit`, `set` or `notset` (a `[...]` class)."""
    tokens: List[Tuple[str, str]] = []
    i = 0
    while i < len(glob):
        char, i = glob[i], i + 1
        j = i + 1 if glob[i:i + 1] == "!" else i
        close = glob.find("]", j + 1 if glob[j:j + 1] == "]" else j)
        if char in "*?":
            tokens.append((char, ""))
        elif char != "[" or close < 0:
            tokens.append(("lit", char))
        else:
            members = re.sub(r"(.)-(.)", lambda m: "".join(
                chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)), glob[j:close],
                             flags=re.DOTALL)
            tokens.append(("notset" if j > i else "set", members))
            i = close + 1
    return tokens


def _chars_meet(a: Tuple[str, str], b: Tuple[str, str]) -> bool:
    """Whether two one-character tokens accept a common character; two negated sets do."""
    a, b = sorted((a, b))  # kinds sort as ? < lit < notset < set
    if a[0] == "?" or a[0] == b[0] == "notset":
        return True
    if a[0] == "notset" and b[0] == "set":
        return bool(set(b[1]) - set(a[1]))
    if a[0] == "lit":
        return a[1] == b[1] if b[0] == "lit" else (a[1] in b[1]) == (b[0] == "set")
    return bool(set(a[1]) & set(b[1]))


def _glob_pair_overlaps(left: str, right: str) -> bool:
    """Whether some path matches both fnmatch globs (`*` spans `/`, as in `fnmatchcase`)."""
    a, b = _glob_tokens(left), _glob_tokens(right)
    seen, todo = set(), [(0, 0)]
    while todo:
        i, j = todo.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(a) and j == len(b):
            return True
        star_a = i < len(a) and a[i][0] == "*"
        star_b = j < len(b) and b[j][0] == "*"
        if star_a:
            todo.append((i + 1, j))
        if star_b:
            todo.append((i, j + 1))
        if i == len(a) or j == len(b) or (star_a and star_b):
            continue
        if star_a or star_b or _chars_meet(a[i], b[j]):
            todo.append((i if star_a else i + 1, j if star_b else j + 1))
    return False


def _globs_overlap(left: List[str], right: List[str]) -> bool:
    return any(_glob_pair_overlaps(a, b) for a in left for b in right)


def rule_conflicts(rules: List[LearnedRule]) -> Set[str]:
    """Ids of active rules where one requires and an overlapping one suppresses or downgrades."""
    active = [rule for rule in rules if rule.status == "active"]
    found: Set[str] = set()
    for i, left in enumerate(active):
        for right in active[i + 1:]:
            actions = {left.effect.action, right.effect.action}
            if "require" not in actions or actions == {"require"}:
                continue
            if not set(left.applies.kinds) & set(right.applies.kinds):
                continue
            if _globs_overlap(left.applies.paths, right.applies.paths):
                found |= {left.id, right.id}
    return found


def lane_rules(rules_file: RulesFile) -> List[LearnedRule]:
    """Active rules the lanes receive: conflicting pairs are both left out."""
    excluded = rule_conflicts(rules_file.rules)
    return [rule for rule in rules_file.rules
            if rule.status == "active" and rule.id not in excluded]
