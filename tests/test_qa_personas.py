"""Behavioural contracts for the qa / qa-backend / qa-frontend persona family (W3d).

Three contracts modelled on MoE-3-personas-upstream.md §3.6's proposal (`make_scaffolder`/
`_config`, the same fixtures `tests/test_invariant_catalog.py` and `tests/test_agent_doc_budget.py`
already use):

  1. Stack gating is real — the check that goes red if `qa-backend.md` is ever filed under
     `features/node/` instead of `features/dotnet/` (SYNTHESIS.md V5: a `react` config resolves
     `node`/`ts` into `config.stacks`, so a gate spelled `stacks=node` would ship to every React
     project).
  2. Delivery reaches Claude Code — `.claude/agents/qa.md` exists, frontmatter starts at line 1,
     carries only `adjust_agents.CLAUDE_KEYS`, and the managed header sits on the first body line.
  3. No duplicated block — `qa-backend.md`/`qa-frontend.md` reference `qa.md` rather than copying
     it (the `frontend-engineer` react/vue hand-copy is the drift pattern this replaces).

Two more this brief added on top, both scoped to what W3d owns (personas + this test file, not
`review-tests`' SKILL.md/extensions, which is W2a/W2b's territory):

  4. Every rule id a qa persona cites resolves in the shared ruleset (`rules.json`, the index
     `rules_index.py` generates from `review-tests/references/*.md`), and every L0 principle that
     ruleset defines is cited somewhere in the family — both directions of the same drift MoE-3
     names for SKILL.md citations, applied to what W3d actually owns.
  5. The journey/delivery check W3c's report asked for: with `index.json` rebuilt, the three qa
     personas AND the `tests-are-designed-and-reviewed` invariant all reach a scaffolded project's
     `.ai-badger/agents/`, `.claude/agents/` and rendered `CLAUDE.md` in one run.
"""
from __future__ import annotations

import json
import re

import pytest

from scaffold_helpers import _config

ADJUSTER = "features/claude/adjustments/adjust_agents.py"
RULES_JSON = "features/common/skills/review-tests/rules.json"
INVARIANT = "tests-are-designed-and-reviewed"

# Mirrors rules_index.py's own ID_RE (features/common/skills/review-tests/scripts/rules_index.py)
# rather than re-deriving it: T0-01 (no group) | T1-SCO-01/T2-WID-01/T3-NET-01 (layer-group-nn) |
# TX-EXC-01 (L4 project-local). Kept identical on purpose — the two must agree on what a citation
# looks like, or this test could pass a rule the generator itself would reject.
RULE_ID_RE = re.compile(r"\bT(?:0-\d{2}|[1-4]-[A-Z0-9]+-\d{2}|X-[A-Z0-9]+-\d{2})\b")

QA_PERSONA_FILES = (
    "features/common/personas/qa.md",
    "features/dotnet/personas/qa-backend.md",
    "features/react/personas/qa-frontend.md",
)


def _rule_ids_in(text: str) -> set:
    return set(RULE_ID_RE.findall(text))


# Matches a bare frontmatter fence, a `key: value` frontmatter line, or a bare Markdown heading —
# the shape of the two false-positive windows measured against the real files before this filter
# existed: `('model: opus', '---', '')` (every `model: opus` persona closes frontmatter the same
# way) and `('', '## Tags', '')` (every catalog persona ends with a `## Tags` section). Neither is
# evidence of a copied block; both are the catalog's shared shape.
_STRUCTURAL_LINE_RE = re.compile(r"^(?:---|#{1,6}\s+\S.*|[A-Za-z][\w-]*:\s*\S*)$")


def _is_structural_boilerplate(window: tuple) -> bool:
    non_blank = [line.strip() for line in window if line.strip()]
    return bool(non_blank) and all(_STRUCTURAL_LINE_RE.match(line) for line in non_blank)


# ── 1. stack gating is real ────────────────────────────────────────────────────

@pytest.mark.parametrize("stacks,present,absent", [
    (["dotnet"], ("qa.md", "qa-backend.md"), ("qa-frontend.md",)),
    # react's own stack.json declares `"requires": ["ts", "node"]`; detect.py writes that
    # expanded closure into config.stacks (SYNTHESIS.md V5), so a config this test's `_config`
    # helper does not itself expand must still spell it out here to match what a real,
    # detect.py-authored react config looks like (test_scaffold.py:44 does the same).
    (["react", "ts", "node"], ("qa.md", "qa-frontend.md"), ("qa-backend.md",)),
    (["terraform"], ("qa.md",), ("qa-backend.md", "qa-frontend.md")),
])
def test_stack_gating_selects_the_right_qa_personas(make_scaffolder, stacks, present, absent):
    """A `react` config resolves `node`/`ts` into `config.stacks` (SYNTHESIS.md V5) — this is
    the check that goes red the moment `qa-backend.md` is filed under `features/node/`, because
    `node` is present in every react project's resolved stack list."""
    target = make_scaffolder.target
    make_scaffolder(config=_config(stacks=stacks, agents=["claude"]), skills=[]).run(
        generated_at="2026-08-22T00:00:00Z")

    delivered = {p.name for p in (target / ".ai-badger" / "agents").glob("*.md")}
    for name in present:
        assert name in delivered, f"{stacks}: expected {name} in .ai-badger/agents/, got {delivered}"
    for name in absent:
        assert name not in delivered, f"{stacks}: {name} must not scaffold, got {delivered}"


# ── 2. delivery reaches Claude Code ────────────────────────────────────────────

def test_qa_reaches_claude_codes_agents_directory(make_scaffolder, load_script):
    adjust_agents = load_script(ADJUSTER)
    target = make_scaffolder.target
    make_scaffolder(config=_config(stacks=["dotnet"], agents=["claude"]), skills=[]).run(
        generated_at="2026-08-22T00:00:00Z")

    delivered = target / ".claude" / "agents" / "qa.md"
    assert delivered.is_file()
    text = delivered.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "frontmatter must start at line 1"

    import frontmatter as fm
    split = fm.split(text)
    assert split.present
    keys = {entry.key for entry in split.entries}
    assert keys <= set(adjust_agents.CLAUDE_KEYS), (
        f"delivered frontmatter carries {keys - set(adjust_agents.CLAUDE_KEYS)}, "
        f"outside adjust_agents.CLAUDE_KEYS"
    )

    header_line = split.body.lstrip("\n").splitlines()[0]
    assert header_line.startswith("<!-- Managed by ai-badger."), (
        "the managed header must sit on the first body line — frontmatter must start at line 1 "
        "and so cannot carry it")


def test_qa_source_frontmatter_declares_no_key_outside_the_claude_allowlist(root, load_script):
    """A key `qa.md` declares that `adjust_agents.CLAUDE_KEYS` does not know is not a harmless
    extra: `render()` only re-emits keys from that allowlist (`for key in CLAUDE_KEYS: if key
    in keep: ...`), so anything else is silently dropped at delivery and nothing says so. This
    is a static check on the source, deliberately independent of the scaffold above, because a
    key that never survives delivery would otherwise leave the delivered-file check unable to
    see it was ever there."""
    adjust_agents = load_script(ADJUSTER)
    import frontmatter as fm
    text = (root / "features/common/personas/qa.md").read_text(encoding="utf-8")
    split = fm.split(text)
    keys = {entry.key for entry in split.entries}
    assert keys <= set(adjust_agents.CLAUDE_KEYS), (
        f"qa.md declares {keys - set(adjust_agents.CLAUDE_KEYS)}, which adjust_agents.CLAUDE_KEYS "
        f"does not carry through to .claude/agents/qa.md"
    )


# ── 3. no duplicated block ─────────────────────────────────────────────────────

def test_the_stack_qa_personas_copy_nothing_from_the_common_one(root):
    """qa-backend/qa-frontend point at qa.md; they must not carry a copy of it.

    The catalog's other shared-block pattern (react/vue frontend-engineer) is a hand-copy that
    drifts. These three land in one `.ai-badger/agents/` directory, so the delta files reference
    instead of copying — and this is the check that notices if someone re-introduces the copy.

    MoE-3-personas-upstream.md §3.6's literal window set flags on this repo's real files without
    the `_is_structural_boilerplate` filter below: `('model: opus', '---', '')` and
    `('', '## Tags', '')` are shared by every persona in the catalog and are not evidence of a
    copied block. Excluding purely-structural windows (a frontmatter fence/key line, or a bare
    heading) keeps the check aimed at prose duplication — see the red-proof pasted in the PR,
    which pastes the eight-principles block into `qa-backend.md` and confirms this test still
    catches it.
    """
    base = (root / "features/common/personas/qa.md").read_text(encoding="utf-8").splitlines()
    windows = {tuple(base[i:i + 3]) for i in range(len(base) - 2)
               if any(line.strip() for line in base[i:i + 3])}
    windows = {w for w in windows if not _is_structural_boilerplate(w)}
    for rel in ("features/dotnet/personas/qa-backend.md",
                "features/react/personas/qa-frontend.md"):
        lines = (root / rel).read_text(encoding="utf-8").splitlines()
        shared = [tuple(lines[i:i + 3]) for i in range(len(lines) - 2)
                  if tuple(lines[i:i + 3]) in windows]
        assert not shared, f"{rel} duplicates qa.md: {shared[:2]}"


# ── 4. rule ids, both directions ───────────────────────────────────────────────

def test_every_rule_id_a_qa_persona_cites_resolves_in_the_shared_ruleset(root):
    """Unbacked citations are the failure mode that makes a persona sound authoritative about a
    rule that does not exist (MoE-3-personas-upstream.md §3.6). `rules.json` is the generated
    index `rules_index.py` builds from `review-tests/references/*.md`, so it is the id space to
    check against rather than re-deriving it."""
    rules = json.loads((root / RULES_JSON).read_text(encoding="utf-8"))
    known_ids = {rule["id"] for rule in rules}

    unbacked = {}
    for rel in QA_PERSONA_FILES:
        cited = _rule_ids_in((root / rel).read_text(encoding="utf-8"))
        missing = cited - known_ids
        if missing:
            unbacked[rel] = sorted(missing)
    assert not unbacked, f"cited ids not in rules.json: {unbacked}"


def test_every_l0_principle_is_cited_somewhere_in_the_qa_persona_family(root):
    """The reverse direction: an L0 principle `rules.json` defines but no qa persona ever cites
    is dead prose the family claims to be governed by and is not ('both directions matter',
    MoE-3-personas-upstream.md §3.6). Scoped to L0 (layer '0') because that is the id space the
    qa personas actually cite today — the L1-L3 reverse check (every heading cited by some
    `SKILL.md`/`extensions/*/extension.md`) is `design-tests`'/`review-tests`' own territory
    (W2a/W2b), not this persona family's, and this test does not touch either skill's files."""
    rules = json.loads((root / RULES_JSON).read_text(encoding="utf-8"))
    principle_ids = {rule["id"] for rule in rules if rule["layer"] == "0"}

    cited = set()
    for rel in QA_PERSONA_FILES:
        cited |= _rule_ids_in((root / rel).read_text(encoding="utf-8"))

    uncited = principle_ids - cited
    assert not uncited, f"L0 principles never cited by any qa persona: {sorted(uncited)}"


# ── 5. the journey: qa family + the test invariant reach a scaffolded project ──

def test_qa_family_and_the_test_invariant_reach_a_scaffolded_project(make_scaffolder):
    """W3c narrowed `test-engineer` and added `tests-are-designed-and-reviewed`; before
    `index.json` was rebuilt to list it, the invariant scaffolded as zero files, per W3c's own
    report. This is what proves delivery now: all three qa personas and the invariant reach
    `.ai-badger/agents/` / `.ai-badger/invariants/`, `.claude/agents/`, and the rendered
    `CLAUDE.md`'s `## Non-negotiable invariants` section, for one dotnet+react project."""
    target = make_scaffolder.target
    result = make_scaffolder(config=_config(stacks=["dotnet", "react"], agents=["claude"]),
                              skills=[]).run(generated_at="2026-08-22T00:00:00Z")

    for name in ("qa.md", "qa-backend.md", "qa-frontend.md"):
        assert (target / ".ai-badger" / "agents" / name).is_file(), (
            f"{name} missing from .ai-badger/agents/")
        assert (target / ".claude" / "agents" / name).is_file(), (
            f"{name} missing from .claude/agents/")

    invariant_path = target / ".ai-badger" / "invariants" / f"{INVARIANT}.md"
    assert invariant_path.is_file(), (
        f"{INVARIANT} did not reach .ai-badger/invariants/ — is it listed under "
        f"common.invariants in index.json?"
    )
    invariant_entries = [e["name"] for e in result["manifest"]["entries"]
                          if e["feature"] == "invariants"]
    assert INVARIANT in invariant_entries, f"{INVARIANT}: missing from the manifest's entries"

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Non-negotiable invariants" in claude_md
    section = claude_md[claude_md.index("## Non-negotiable invariants"):]
    assert f"→ `.ai-badger/invariants/{INVARIANT}.md`" in section, (
        f"{INVARIANT}: not linked under '## Non-negotiable invariants' in the generated CLAUDE.md"
    )
