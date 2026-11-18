"""Learned review rules: load from the base ref, lifecycle verbs, scope matching and the lane cap.

The typed model, conflict detection and activation proofs live in `review_flow_model`; this
module owns reading `.ai-badger/review/rules.json` from the PR base ref (never the head),
writing it back, and the verbs that move a rule from proposed to active to retired.
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from pydantic import ValidationError

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import review_flow_model as model  # pylint: disable=wrong-import-position

RULES_PATH = ".ai-badger/review/rules.json"
LANE_RULE_CAP = 30
TEACHING_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
_CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")
_MISSING_AT_REF = ("does not exist in", "exists on disk, but not in")

Runner = Callable[[List[str], Path], Tuple[int, str, str]]


class RulesFileInvalid(Exception):
    """The rules file at the base ref is unreadable; names the path and the reason."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class RuleRefused(Exception):
    """A lifecycle verb was refused; the rules file is unchanged."""


@dataclass(frozen=True)
class LaneRules:
    """Rules a lane receives, how many the cap dropped, and ids left out by conflict."""

    rules: List[model.LearnedRule]
    dropped: int = 0
    conflicting: List[str] = field(default_factory=list)


def _run_git(args: List[str], cwd: Path) -> Tuple[int, str, str]:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    return done.returncode, done.stdout, done.stderr


def _empty() -> "model.RulesFile":
    return model.RulesFile(schema_version=1, rules=[], facts=[])


def _parse(text: str) -> "model.RulesFile":
    if any(line.startswith(_CONFLICT_MARKERS) for line in text.splitlines()):
        raise RulesFileInvalid(RULES_PATH, "merge conflict markers in file")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RulesFileInvalid(RULES_PATH, f"invalid JSON: {exc}") from exc
    try:
        return model.RulesFile.model_validate(data)
    except ValidationError as exc:
        raise RulesFileInvalid(RULES_PATH, f"fails the rules model: {exc}") from exc


def load(repo_root: Path, base_ref: str, run: Optional[Runner] = None) -> "model.RulesFile":
    """Rules at `base_ref` via `git show`; a path missing at that ref is an empty file."""
    runner = run or _run_git
    code, out, err = runner(["git", "show", f"{base_ref}:{RULES_PATH}"], Path(repo_root))
    if code != 0:
        if any(phrase in err for phrase in _MISSING_AT_REF):
            return _empty()
        raise RulesFileInvalid(RULES_PATH, f"git show {base_ref} failed: {err.strip()}")
    return _parse(out)


def dump(rules_file: "model.RulesFile") -> str:
    """The deterministic file text: model field order, two-space indent, trailing newline."""
    data = rules_file.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def save(repo_root: Path, rules_file: "model.RulesFile") -> Path:
    """Write the working-tree rules file and return its path."""
    target = Path(repo_root) / RULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump(rules_file), encoding="utf-8")
    return target


def head_diff_touches_rules(changed_paths: Iterable[str]) -> bool:
    """True when the head diff edits the rules file, so a finding can say so."""
    return any(PurePosixPath(path).as_posix() == RULES_PATH for path in changed_paths)


# ------------------------------------------------------------------ scope

def _scope_matches(applies: "model.Applies", kind: str, path: str,
                   symbol: Optional[str] = None) -> bool:
    """The one scope test: kind listed, a path glob hits, and the symbol glob hits if any."""
    if kind not in {item.value for item in applies.kinds}:
        return False
    if not any(fnmatch.fnmatchcase(path, glob) for glob in applies.paths):
        return False
    if symbol is None or not applies.symbols:
        return True
    return any(fnmatch.fnmatchcase(symbol, glob) for glob in applies.symbols)


def matches(applies: "model.Applies", finding: "model.Finding") -> bool:
    """Whether a rule or fact scope covers the finding; kind `other` is never covered."""
    return _scope_matches(applies, finding.kind.value, finding.location.path,
                          finding.location.symbol)


def _id_number(item_id: str) -> int:
    return int(item_id.split("-", 1)[1])


def lane_rules(rules_file: "model.RulesFile", paths: Sequence[str],
               kinds: Sequence[str]) -> LaneRules:
    """Active, non-conflicting rules in scope of the paths and kinds, by id, capped."""
    excluded = model.rule_conflicts(rules_file.rules)
    wanted = {getattr(kind, "value", kind) for kind in kinds}
    in_scope = [rule for rule in model.lane_rules(rules_file)
                if any(_scope_matches(rule.applies, kind, path)
                       for kind in wanted for path in paths)]
    ordered = sorted(in_scope, key=lambda rule: _id_number(rule.id))
    return LaneRules(rules=ordered[:LANE_RULE_CAP], dropped=max(0, len(ordered) - LANE_RULE_CAP),
                     conflicting=sorted(excluded, key=_id_number))


# ------------------------------------------------------------------ lifecycle

def _rebuild(rules_file: "model.RulesFile", rules: List["model.LearnedRule"]) -> "model.RulesFile":
    """A new, re-validated file with `rules` swapped in."""
    data = rules_file.model_dump(mode="json", by_alias=True)
    data["rules"] = [rule.model_dump(mode="json") for rule in rules]
    try:
        return model.RulesFile.model_validate(data)
    except ValidationError as exc:
        raise RuleRefused(f"result fails the rules model: {exc}") from exc


def _find(rules_file: "model.RulesFile", rule_id: str) -> "model.LearnedRule":
    for rule in rules_file.rules:
        if rule.id == rule_id:
            return rule
    raise RuleRefused(f"no rule {rule_id}")


def _replace(rules_file: "model.RulesFile", rule_id: str, **changes: Any) -> "model.RulesFile":
    _find(rules_file, rule_id)
    rules = []
    for rule in rules_file.rules:
        if rule.id == rule_id:
            data = rule.model_dump(mode="json")
            data.update(changes)
            try:
                rule = model.LearnedRule.model_validate(data)
            except ValidationError as exc:
                raise RuleRefused(f"rule {rule_id} cannot take that change: {exc}") from exc
        rules.append(rule)
    return _rebuild(rules_file, rules)


def next_rule_id(rules_file: "model.RulesFile") -> str:
    """The next rule id; ids only grow because rules are retired, never deleted."""
    highest = max((_id_number(rule.id) for rule in rules_file.rules), default=0)
    return f"R-{highest + 1}"


def _origin_of(reply: Mapping[str, Any]) -> "model.Origin":
    association = reply.get("association")
    if association not in TEACHING_ASSOCIATIONS:
        raise RuleRefused(f"author association {association!r} cannot teach; "
                          f"need one of {list(TEACHING_ASSOCIATIONS)}")
    try:
        return model.Origin(pr=reply["pr"], thread_url=reply["thread_url"],
                            author=reply["author"], association=association,
                            quote=reply["quote"])
    except (KeyError, ValidationError) as exc:
        raise RuleRefused(f"reply is not a valid origin: {exc}") from exc


def propose(rules_file: "model.RulesFile",
            reply: Mapping[str, Any]) -> Tuple["model.RulesFile", "model.LearnedRule"]:
    """Add a `proposed` rule taught by an OWNER, MEMBER or COLLABORATOR reply."""
    origin = _origin_of(reply)
    try:
        rule = model.LearnedRule(
            id=next_rule_id(rules_file), status="proposed", statement=reply["statement"],
            applies=reply["applies"], effect=reply["effect"], origins=[origin])
    except (KeyError, ValidationError) as exc:
        raise RuleRefused(f"reply is not a valid rule: {exc}") from exc
    return _rebuild(rules_file, [*rules_file.rules, rule]), rule


def add_origin(rules_file: "model.RulesFile", rule_id: str,
               reply: Mapping[str, Any]) -> "model.RulesFile":
    """Record a further thread that taught a still-`proposed` rule."""
    rule = _find(rules_file, rule_id)
    if rule.status != "proposed":
        raise RuleRefused(f"rule {rule_id} is {rule.status}; only a proposed rule takes origins")
    origin = _origin_of(reply)
    return _replace(rules_file, rule_id,
                    origins=[*(item.model_dump(mode="json") for item in rule.origins),
                             origin.model_dump(mode="json")])


def _require_proposed(rules_file: "model.RulesFile", rule_id: str) -> "model.LearnedRule":
    rule = _find(rules_file, rule_id)
    if rule.status != "proposed":
        raise RuleRefused(f"rule {rule_id} is {rule.status}, not proposed")
    return rule


def confirm(rules_file: "model.RulesFile", rule_id: str, maintainer: str) -> "model.RulesFile":
    """Activate a proposed rule on a named maintainer's confirmation."""
    if not maintainer or not maintainer.strip():
        raise RuleRefused("confirm needs the maintainer's name")
    _require_proposed(rules_file, rule_id)
    return _replace(rules_file, rule_id, status="active", activated_by="maintainer")


def activate_by_threads(rules_file: "model.RulesFile", rule_id: str) -> "model.RulesFile":
    """Activate a proposed rule taught in two threads by two different authors."""
    _require_proposed(rules_file, rule_id)
    return _replace(rules_file, rule_id, status="active", activated_by="threads")


def retire(rules_file: "model.RulesFile", rule_id: str) -> "model.RulesFile":
    """Retire an active rule; it stays in the file and its id is never reused."""
    rule = _find(rules_file, rule_id)
    if rule.status != "active":
        raise RuleRefused(f"rule {rule_id} is {rule.status}; only an active rule retires")
    return _replace(rules_file, rule_id, status="retired")


# ------------------------------------------------------------------ citation

def _safe_file(repo_root: Path, rel_path: str) -> Path:
    """The repo file for `rel_path`, refusing absolute, `..` and any path that resolves outside."""
    pure = PurePosixPath(rel_path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise RuleRefused(f"citation path {rel_path!r} must be repo-relative without '..'")
    root = Path(repo_root).resolve()
    current = root / pure
    if not current.is_file():
        raise RuleRefused(f"citation file {rel_path!r} does not exist")
    if root not in current.resolve().parents:
        raise RuleRefused(f"citation path {rel_path!r} leaves the repo")
    return current


def verify_citation(repo_root: Path, rules_file: "model.RulesFile", rule_id: str,
                    path: str, start: int, end: int, quote: str) -> "model.RulesFile":
    """Activate a proposed rule once `quote` is found inside `path` lines `start..end`."""
    _require_proposed(rules_file, rule_id)
    if not quote.strip():
        raise RuleRefused("citation quote is blank")
    target = _safe_file(repo_root, path)
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    if start < 1 or end < start or end > len(lines):
        raise RuleRefused(f"{path} has {len(lines)} lines; {start}..{end} is outside them")
    if quote.strip() not in "\n".join(lines[start - 1:end]):
        raise RuleRefused(f"quote not found in {path}:{start}..{end}")
    return _replace(rules_file, rule_id, status="active", activated_by="citation",
                    citation={"path": path, "start": start, "end": end})
