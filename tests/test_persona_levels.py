"""L1 lane-vocabulary tests for PKG-3 (tiers/pkg3-lanes).

Dual-key contract (ratified pre-dispatch, recorded in docs/adr/0027-*):
personas carry `level:` (routing intent, low|medium|high) + Claude-legible
`model:` (bare lane, e.g. opus/sonnet). Grandfather clause: legacy bare pins
keep today's best-effort fallback; new personas are banned from bare (a
`model:` without a `level:` fails A4).

Precedence (3 clauses) is OWNED by PKG-2 (parallel lane). This file QUOTES it
in G1's assertion context and never restates it (M2).

  "An explicit model wins verbatim; else the persona's level resolves to its
  group's preferred pin; else the session model is inherited."

S7: the persona catalog glob is `features/*/personas/*.md` — not just
`features/common/personas/` (5 files). `api-engineer` lives in
`features/node/personas/`, `hermes-agent-author` in
`features/hermes/personas/`, plus dotnet/react/angular/azure/vue homes;
`tests/test_qa_personas.py` (qa in common, qa-backend in dotnet,
qa-frontend in react) decides the distribution. Every A-test below sweeps
the glob (discovery rule, M12-tracked); A4 pairs it with a provocation that
proves the sweep can fail (G4-tracked).

B3 note: the fail-loud variant (invalid registry raises) was CUT. The
warn-convention reasons: `model_groups.resolve` warns (UserWarning) on a
stale non-deciding level instead of failing (T-A7); hooks fail open; M5
requires invalid-registry → loud marker line + note, NOT hard abort. B3
asserts the marker/note content instead.
"""
from __future__ import annotations

import pytest

from scaffold_helpers import _config

# The canonical 3-clause precedence sentence, OWNED by PKG-2. Quoted here for
# G1 context only; this lane must never restate it (M2).
PRECEDENCE_QUOTE = (
    "An explicit model wins verbatim; else the persona's level resolves to its "
    "group's preferred pin; else the session model is inherited."
)

VALID_LEVELS = ("low", "medium", "high")
PERSONA_GLOB = "features/*/personas/*.md"
GATE_HOOK = "features/common/skills/task/scripts/dispatch_gate_hook.py"


def _personas(root):
    found = sorted(root.glob(PERSONA_GLOB))
    assert found, f"{PERSONA_GLOB} matched nothing — the discovery rule ran on no input"
    return found


def _frontmatter(root, load_script):
    import frontmatter as fm
    return fm


# ------------------------------------------------------------------ L1-A1: every persona declares a level
def test_L1_A1_every_catalog_persona_declares_a_level(root, load_script):
    """Discovery rule (M12): sweep the catalog glob, not a hardcoded list."""
    fm = _frontmatter(root, load_script)
    missing = []
    for path in _personas(root):
        fields = fm.fields(path.read_text(encoding="utf-8"))
        if not isinstance(fields.get("level"), str) or not fields["level"].strip():
            missing.append(path.relative_to(root).as_posix())
    assert not missing, f"personas without a level:: {missing}"


# ------------------------------------------------------------------ L1-A2: levels are closed, case-sensitive
def test_L1_A2_every_level_is_low_medium_or_high(root, load_script):
    fm = _frontmatter(root, load_script)
    bad = []
    for path in _personas(root):
        level = fm.fields(path.read_text(encoding="utf-8")).get("level")
        if isinstance(level, str):
            level = level.strip()
        if level not in VALID_LEVELS:
            bad.append(f"{path.relative_to(root).as_posix()} has level {level!r}")
    assert not bad, f"levels outside low|medium|high: {bad}"


# ------------------------------------------------------------------ L1-A3: dual-key keeps the Claude lane
def test_L1_A3_every_catalog_persona_keeps_a_bare_model_lane(root, load_script):
    """Grandfather clause: `model:` (opus/sonnet) stays; `level:` is added beside it."""
    fm = _frontmatter(root, load_script)
    missing = []
    for path in _personas(root):
        fields = fm.fields(path.read_text(encoding="utf-8"))
        if not isinstance(fields.get("model"), str) or not fields["model"].strip():
            missing.append(path.relative_to(root).as_posix())
    assert not missing, f"personas without a model: lane: {missing}"


# ------------------------------------------------------------------ L1-A4: new personas banned from bare + provocation
def test_L1_A4_no_persona_declares_a_model_without_a_level(root, load_script):
    """A `model:` without a `level:` is a new bare pin — banned (grandfather is for
    legacy pins that predate levels, and every legacy pin has now gained one)."""
    fm = _frontmatter(root, load_script)
    bare = []
    for path in _personas(root):
        fields = fm.fields(path.read_text(encoding="utf-8"))
        has_model = isinstance(fields.get("model"), str) and fields["model"].strip()
        has_level = isinstance(fields.get("level"), str) and fields["level"].strip()
        if has_model and not has_level:
            bare.append(path.relative_to(root).as_posix())
    assert not bare, f"bare model:-without-level: pins: {bare}"


def test_L1_A4_provocation_a_bare_fixture_fails_the_sweep(tmp_path, load_script):
    """Provocation pair (G4): the A4 check is real — a bare fixture is caught.

    Writes a bare `model:`-without-`level:` persona into a scratch dir and runs
    the same predicate A4 runs over the catalog, proving the sweep can go red.
    """
    import frontmatter as fm
    from conftest import _test_write
    bare = _test_write(
        tmp_path / "bare-probe.md",
        "---\nname: bare-probe\ndescription: probe\nmodel: opus\n---\n\nBody.\n",
        encoding="utf-8",
    )
    fields = fm.fields(bare.read_text(encoding="utf-8"))
    has_model = isinstance(fields.get("model"), str) and fields["model"].strip()
    has_level = isinstance(fields.get("level"), str) and fields["level"].strip()
    assert has_model and not has_level, "the probe must be bare to prove anything"
    # The A4 predicate, applied to the probe: it must flag it.
    flagged = bool(has_model and not has_level)
    assert flagged, "A4's predicate let a bare pin through — the sweep is decorative"


# ------------------------------------------------------------------ L1-B1: the map renders the level
def test_L1_B1_the_delegation_map_renders_each_personas_level(make_scaffolder):
    """The generator names the routing intent beside the lane it already named."""
    doc = make_scaffolder(config=_config(stacks=["dotnet"], agents=["claude"])).run(
        generated_at="2026-09-05T00:00:00Z")
    text = (make_scaffolder.target / ".ai-badger" / "delegation.md").read_text(
        encoding="utf-8")
    assert "Level:" in text, f"no Level: in delegation.md:\n{text[:1500]}"
    assert "Lane:" in text


def test_L1_B1_level_values_come_from_frontmatter(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder(config=_config(stacks=["dotnet"], agents=["claude"])).run(
        generated_at="2026-09-05T00:00:00Z")
    text = (target / ".ai-badger" / "delegation.md").read_text(encoding="utf-8")
    for bad in ("Level: opus", "Level: sonnet", "Level: haiku"):
        assert bad not in text, f"a bare lane leaked into a Level: slot: {bad}"


# ------------------------------------------------------------------ L1-B2: invalid level degrades loud, never aborts
def test_L1_B2_an_unknown_level_is_a_loud_marker_not_an_abort(
        make_scaffolder, load_script):
    """M5: an invalid level renders a marker line + a scaffold note, NOT an exception."""
    from conftest import _test_write
    agents = make_scaffolder.target / ".ai-badger" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    _test_write(
        agents / "level-probe.md",
        "---\nname: level-probe\ndescription: probe\nmodel: opus\nlevel: ultra\n---\n\nBody.\n",
        encoding="utf-8",
    )
    # Seed the ctx the generator reads: scaffold first so agents/ exists, then add probe.
    scaffolder = make_scaffolder(config=_config(stacks=["dotnet"], agents=["claude"]))
    result = scaffolder.run(generated_at="2026-09-05T00:00:00Z")
    assert result is not None, "scaffold aborted on an unknown level — M5 forbids a hard abort"


def test_L1_B3_marker_names_the_bad_level_and_the_valid_set(make_scaffolder):
    """B3 (cut from fail-loud to marker-content per the warn-convention): the loud
    line names the offending level and the closed set, so the fix is in the message."""
    from conftest import _test_write
    agents = make_scaffolder.target / ".ai-badger" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    _test_write(
        agents / "level-probe.md",
        "---\nname: level-probe\ndescription: probe\nmodel: opus\nlevel: ultra\n---\n\nBody.\n",
        encoding="utf-8",
    )
    make_scaffolder(config=_config(stacks=["dotnet"], agents=["claude"])).run(
        generated_at="2026-09-05T00:00:00Z")
    text = (make_scaffolder.target / ".ai-badger" / "delegation.md").read_text(
        encoding="utf-8")
    probe_lines = [ln for ln in text.splitlines() if "level-probe" in ln]
    assert probe_lines, f"level-probe missing from delegation.md:\n{text[:2000]}"
    joined = "\n".join(probe_lines)
    assert "ultra" in joined, f"marker names nothing: {joined}"
    assert "low" in text and "medium" in text and "high" in text


# ------------------------------------------------------------------ L1-G1: gate deny text (text only, zero logic change)
def test_L1_G1_deny_reason_names_levels_and_points_at_the_map(root, load_script):
    hook = load_script(GATE_HOOK)
    reason = hook.DENY_REASON
    for level in ("low", "medium", "high"):
        assert level in reason, f"DENY_REASON names no {level}: {reason!r}"
    assert ".ai-badger/delegation.md" in reason


def test_L1_G1_deny_reason_quotes_the_precedence_sentence(root, load_script):
    """M2: PKG-2 owns the precedence sentence; the gate QUOTES it, never restates it."""
    hook = load_script(GATE_HOOK)
    assert PRECEDENCE_QUOTE in hook.DENY_REASON, (
        "DENY_REASON must quote PKG-2's canonical 3-clause precedence sentence verbatim; "
        f"got: {hook.DENY_REASON!r}")


def test_L1_G1_level_is_documented_as_gate_only(root, load_script):
    """`declares_level` is gate/generator vocabulary, not Claude runtime routing:
    gate-declared ≠ runtime-routed (level: is stripped at .claude/agents/ delivery)."""
    hook = load_script(GATE_HOOK)
    doc = hook.__doc__ or ""
    assert "gate-only" in doc, "gate docstring must document level: as gate-only"
