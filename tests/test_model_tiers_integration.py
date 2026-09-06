"""Join tests for the model-tier wave (tiers/int): cross-package assertions no lane owns.

Each lane tested its own surface (PKG-1 registry leaf, PKG-2 prose, PKG-3 lanes,
PKG-4 pi delivery). These tests pin the JOINS — the wordings, versions, and
resolutions that must agree across lanes:

  (i)  M2 wording parity: the gate-voice family (DENY_REASON inner quote,
       PRECEDENCE_QUOTE value, ADR-0027 blockquote) is canonically identical
       (direction C, F1: formatting-blind exact equality, not raw substring).
       Skill prose carries the same contract in skill voice (backticked SUB_*
       cores, lane-tested) and is deliberately out of scope here.
  (iii) frameworkVersion == VERSION inside the shipped registry.
  (7a) registry<->docs consistency, derived not listed: the advisory $/task
       table in the changelog is parsed (not copied) and every short pin it
       names must resolve to exactly one registry id in its tier — preferred
       first, dearest *deciding* (non-demoted) last. delegation.md Level values
       and persona frontmatter levels must sit inside the registry's group keys.
  (7b) Claude-side delegation matrix over the REAL shipped registry (no
       fixtures): low|medium|high resolve to the preferred pins, an explicit
       model wins verbatim over every level, absent-everything inherits (None),
       and a deciding unknown level raises UnknownLevel.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

LEAF = "features/common/skills/task/scripts/model_groups.py"
GATE_SOURCES = (
    "features/common/skills/task/scripts/dispatch_gate_hook.py",
    ".ai-badger/skills/task/scripts/dispatch_gate_hook.py",
    "skills/task/scripts/dispatch_gate_hook.py",
)
ADR = "docs/adr/0027-dual-key-persona-levels.md"
LANE_QUOTE_CARRIER = "tests/test_persona_levels.py"
SHIPPED_REGISTRY = ".ai-badger/model-groups.json"
CANONICAL_SEED = "features/common/data/model-groups.json"
VERSION_FILE = "VERSION"
CHANGELOG = "docs/changelog/0.165.0-model-groups-registry.md"
DELEGATION_MD = ".ai-badger/delegation.md"
PERSONA_GLOB = "features/*/personas/*.md"

# The canonical 3-clause precedence sentence (M2; owned by PKG-2, quoted by PKG-3).
# Kept as three clauses so a rewording of any single clause fails its own assertion.
CLAUSE_EXPLICIT_WINS = "An explicit model wins verbatim"
CLAUSE_LEVEL_RESOLVES = "the persona's level resolves to its group's preferred pin"
CLAUSE_INHERIT = "the session model is inherited"
CLAUSES = (CLAUSE_EXPLICIT_WINS, CLAUSE_LEVEL_RESOLVES, CLAUSE_INHERIT)


def _clauses_present(text: str) -> list[str]:
    """Clauses of the canonical sentence missing from text (empty == full quote).

    Whitespace-normalized: shipped sources line-wrap the quote, so raw
    substrings would false-red on a line break. Normalization collapses
    whitespace runs only — a rewording still fails loudly."""
    flat = " ".join(text.split())
    return [clause for clause in CLAUSES if clause not in flat]


def _canon(s: str) -> str:
    """Canonical form of a precedence quote (direction C, F1).

    Strip surrounding double quotes, strip leading `> ` blockquote markers
    per line, collapse whitespace runs. Lets word-identical quotes compare
    equal across Python-literal wraps, file line-wraps, and ADR blockquotes."""
    lines = [line.lstrip()[2:] if line.lstrip().startswith("> ") else line
             for line in s.strip().splitlines()]
    text = " ".join(lines).strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return " ".join(text.split())


def _loose(s: str) -> str:
    """Whitespace-collapsed form for anchor checks (not equality)."""
    return " ".join(s.split())


def _deny_inner_sentence(deny_reason: str) -> str:
    """The quoted precedence sentence inside the runtime DENY_REASON value."""
    match = re.search(r'"([^"]*explicit model wins[^"]*)"', deny_reason)
    assert match, "DENY_REASON carries no quoted precedence sentence"
    return match.group(1)


def _lane_quote_value(root: Path) -> str:
    """PRECEDENCE_QUOTE's runtime value without importing test code.

    The carrier file deliberately avoids importable helpers (see its header
    contract note at tests/test_persona_levels.py:1-14), so parse the assigned string with
    ast instead of importing the module."""
    tree = ast.parse((root / LANE_QUOTE_CARRIER).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "PRECEDENCE_QUOTE"):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{LANE_QUOTE_CARRIER}: PRECEDENCE_QUOTE not found")


def _adr_blockquote_sentence(root: Path) -> str:
    """The ratified blockquote's sentence (ADR-0027).

    Markers are stripped per line BEFORE joining: joining first would leave
    a later line's `>` stranded mid-string (regression this helper owns).
    Takes the FIRST contiguous `>` block CONTAINING the anchor sentence, so
    an unrelated blockquote elsewhere in the ADR can neither concatenate
    into nor shadow the sentence."""
    stripped = []
    for line in (root / ADR).read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(">"):
            stripped.append(line.lstrip()[1:])
        elif stripped:
            break
    assert stripped, f"{ADR}: no blockquote found"
    joined = " ".join(stripped)
    if "explicit model wins" not in _loose(joined):
        raise AssertionError(f"{ADR}: anchor block missing — ratified sentence moved?")
    return joined


# ------------------------------------------------------- (i) M2 quote parity
def test_m2_deny_reason_quotes_all_three_clauses(root: Path, load_script) -> None:
    """PKG-3 quotes, never restates: each clause is a substring of the RUNTIME
    DENY_REASON value (source-text checks would trip on Python string-literal
    quotes at the wrap points — the lane test pins the value for the same reason)."""
    hook = load_script(GATE_SOURCES[0])
    missing = _clauses_present(hook.DENY_REASON)
    assert not missing, f"DENY_REASON restates instead of quoting; missing {missing}"


def test_m2_shipped_gate_copies_are_byte_identical(root: Path) -> None:
    """Every delivered copy of the gate ships the same quote (scaffold syncs them)."""
    bodies = [(root / rel).read_text(encoding="utf-8") for rel in GATE_SOURCES]
    for rel, body in zip(GATE_SOURCES[1:], bodies[1:]):
        assert body == bodies[0], f"{rel}: shipped gate copy drifted from {GATE_SOURCES[0]}"


def test_m2_adr_blockquote_carries_the_same_three_clauses(root: Path) -> None:
    """The ratified record (ADR-0027) and the gate quote the same sentence."""
    text = (root / ADR).read_text(encoding="utf-8")
    unquoted = text.replace(">", " ")  # blockquote markers are markdown, not wording
    missing = _clauses_present(unquoted)
    assert not missing, f"{ADR}: ratified sentence drifted from the gate quote; missing {missing}"


def test_m2_lane_quote_carrier_agrees_clause_by_clause(root: Path) -> None:
    """Cross-anchor without importing test code: PRECEDENCE_QUOTE's carrier file
    contains every clause, so the join constant and the lane constant cannot fork."""
    text = (root / LANE_QUOTE_CARRIER).read_text(encoding="utf-8")
    missing = _clauses_present(text)
    assert not missing, f"{LANE_QUOTE_CARRIER}: lane quote forked; missing {missing}"


def test_m2_clause_check_can_fail() -> None:
    """The predicate is not vacuous: a restated clause is caught."""
    assert _clauses_present("An explicit model wins verbatim; else something else") == [
        CLAUSE_LEVEL_RESOLVES, CLAUSE_INHERIT]
    assert _clauses_present(
        CLAUSE_EXPLICIT_WINS + "; else " + CLAUSE_LEVEL_RESOLVES + "; else " + CLAUSE_INHERIT) == []


def test_m2_gate_family_is_canonically_identical(root: Path, load_script) -> None:
    """Direction C (F1): the gate-voice family is byte-identical once
    formatting is canonicalized — DENY_REASON's inner quote, the lane
    carrier value, and the ADR blockquote must be the same sentence.
    Skill voice is deliberately out of scope (different readers)."""
    hook = load_script(GATE_SOURCES[0])
    deny = _canon(_deny_inner_sentence(hook.DENY_REASON))
    lane = _canon(_lane_quote_value(root))
    adr = _canon(_adr_blockquote_sentence(root))
    assert deny == lane == adr, (
        f"gate family forked:\nDENY={deny!r}\nLANE={lane!r}\nADR={adr!r}")


def test_m2_canonical_equality_can_fail() -> None:
    """The canonical predicate is not vacuous: a one-word rewording fails it,
    while wrapping/formatting differences do not."""
    base = ('"An explicit model wins verbatim; else the persona\'s level resolves '
            'to its group\'s preferred pin; else the session model is inherited."')
    reworded = base.replace("preferred pin", "preferred entry")
    assert _canon(base) == _canon(_lane_quote_sibling(base))
    assert _canon(reworded) != _canon(base)


def _lane_quote_sibling(sentence: str) -> str:
    """Same sentence as an ADR blockquote would wrap it (formatting differs).

    Derived from the input (not hardcoded) so a legitimate canonical change
    cannot desync the pair."""
    import textwrap

    core = sentence.strip().strip('"')
    return "> " + "\n> ".join(textwrap.wrap(core, width=60))


# ------------------------------------------------------- (iii) version parity
def test_shipped_registry_framework_version_equals_version(root: Path) -> None:
    """The delivered registry rides the release lineage (0.165.0 kept, never downgraded)."""
    version = (root / VERSION_FILE).read_text(encoding="utf-8").strip()
    doc = json.loads((root / SHIPPED_REGISTRY).read_text(encoding="utf-8"))
    assert doc["frameworkVersion"] == version, (
        f"{SHIPPED_REGISTRY} frameworkVersion {doc['frameworkVersion']!r} != VERSION {version!r}")


def test_shipped_registry_matches_the_canonical_seed(root: Path) -> None:
    """Delivered copy == canonical source (parsed): scaffold ships verbatim."""
    shipped = json.loads((root / SHIPPED_REGISTRY).read_text(encoding="utf-8"))
    seed = json.loads((root / CANONICAL_SEED).read_text(encoding="utf-8"))
    assert shipped["groups"] == seed["groups"]


# ------------------------------------------------------- (7a) registry<->docs
def _registry_groups(root: Path) -> dict:
    return json.loads((root / SHIPPED_REGISTRY).read_text(encoding="utf-8"))["groups"]


def _advisory_rows(root: Path) -> list[tuple[str, str, str]]:
    """Parse (tier, preferred-short, dearest-short) from the changelog table — derived,
    so a new table row is covered without touching this file."""
    rows = []
    for line in (root / CHANGELOG).read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*(low|medium|high)\s*\|\s*(\S+)\s*→\s*(\S+)\s*\|", line)
        if match:
            rows.append((match.group(1), match.group(2), match.group(3)))
    assert rows, f"{CHANGELOG}: advisory table unparsable — rows changed shape"
    return rows


def test_advisory_table_shorts_resolve_into_the_registry(root: Path) -> None:
    """Every short pin the advisory table names is exactly one registry id in its
    tier (dash-token match on the final segment); first short is the preferred pin,
    second short is the dearest *deciding* (non-demoted) pin."""
    groups = _registry_groups(root)
    for tier, preferred_short, dearest_short in _advisory_rows(root):
        members = groups[tier]
        deciding = [m for m in members if m.get("status") != "demoted"]
        for short, expected in ((preferred_short, deciding[0]), (dearest_short, deciding[-1])):
            # The table names human truncations (spark-contributor), not id fragments:
            # every dash-token of the short must sit in the final id segment, unique
            # per tier. Any future pin that breaks uniqueness reds this test (fail-loud).
            tokens = short.split("-")
            hits = [m["id"] for m in members
                    if all(tok in m["id"].split("/")[-1] for tok in tokens)]
            assert len(hits) == 1, f"{tier}: {short!r} matches {hits} — table/registry forked"
            assert hits[0] == expected["id"], (
                f"{tier}: {short!r} resolves to {hits[0]!r}, table position says {expected['id']!r}")


def test_delegation_map_levels_are_registry_keys(root: Path) -> None:
    """delegation.md Level: values sit inside the registry's closed group set."""
    groups = _registry_groups(root)
    text = (root / DELEGATION_MD).read_text(encoding="utf-8")
    rendered = set(re.findall(r"Level:\s*(\w+)", text))
    assert rendered, f"{DELEGATION_MD}: no Level: lines rendered"
    assert rendered <= set(groups), f"map names levels outside the registry: {rendered - set(groups)}"


def test_persona_frontmatter_levels_are_registry_keys(root: Path, load_script) -> None:
    """Every catalog persona's level: resolves against the shipped registry."""
    import frontmatter as fm

    groups = _registry_groups(root)
    bad = []
    for path in sorted(root.glob(PERSONA_GLOB)):
        level = fm.fields(path.read_text(encoding="utf-8")).get("level")
        if isinstance(level, str):
            level = level.strip()
        if level not in groups:
            bad.append(f"{path.relative_to(root)} has level {level!r}")
    assert not bad, f"persona levels outside the registry: {bad}"


# ------------------------------------------------------- (7b) Claude-side matrix
@pytest.fixture()
def shipped_groups(root: Path, load_script):
    """The REAL delivered registry — no fixtures; a rotated pin reds this file."""
    mg = load_script(LEAF)
    return mg, mg.load_groups(str(root / SHIPPED_REGISTRY))


@pytest.mark.parametrize("level", ("low", "medium", "high"))
def test_matrix_level_resolves_to_the_preferred_pin(shipped_groups, level: str) -> None:
    mg, groups = shipped_groups
    assert mg.resolve(level, None, groups) == mg.preferred(level, groups)


@pytest.mark.parametrize("level", ("low", "medium", "high"))
def test_matrix_explicit_model_wins_verbatim_over_every_level(shipped_groups, level: str) -> None:
    mg, groups = shipped_groups
    pin = "openrouter/join/probe-explicit"
    assert mg.resolve(level, pin, groups) == pin


def test_matrix_absent_everything_inherits(shipped_groups) -> None:
    mg, groups = shipped_groups
    assert mg.resolve(None, None, groups) is None


def test_matrix_deciding_unknown_level_raises(shipped_groups) -> None:
    mg, groups = shipped_groups
    with pytest.raises(mg.UnknownLevel):
        mg.resolve("ultra", None, groups)
