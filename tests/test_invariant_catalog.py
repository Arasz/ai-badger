"""Five new common-stack invariants: proof-of-done, plain-names, check-sources-not-yourself,
measure-when-it-pays, ask-if-simpler.

Two behavioural contracts on top of the generic invariant machinery already covered by
test_invariant_rendering.py: each one must reach a scaffolded project on disk and in the
manifest, and each one's own heading must reach the generated CLAUDE.md under
"## Non-negotiable invariants". A third check is mechanical and needs no scaffold run at
all: every features/common/invariants/*.md stays short and single-headed.
"""
from __future__ import annotations

import pytest

from scaffold_helpers import _config

INVARIANTS_DIR = "features/common/invariants"

NEW_INVARIANTS = (
    "proof-of-done",
    "plain-names",
    "check-sources-not-yourself",
    "measure-when-it-pays",
    "ask-if-simpler",
)

# pr-per-task.md carries a deliberate multi-paragraph exception clause about who may waive
# the PR rule (7 lines); exempt from the length check only — the one-heading check still
# applies to it.
LONG_FORM = {"pr-per-task.md"}


def _scaffold(make_scaffolder, config):
    target = make_scaffolder.target
    result = make_scaffolder(config=config).run(generated_at="2026-08-01T00:00:00Z")
    return target, result


def _invariants_section(claude_md: str) -> str:
    """The text between '## Non-negotiable invariants' and the next '## ' heading."""
    start = claude_md.index("## Non-negotiable invariants")
    rest = claude_md[start + len("## Non-negotiable invariants"):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _invariant_files(root):
    return sorted(p for p in (root / INVARIANTS_DIR).glob("*.md") if p.name != "README.md")


# ------------------------------------------------------------------------------- delivery
@pytest.mark.parametrize("name", NEW_INVARIANTS)
def test_invariant_is_delivered_to_the_scaffolded_project(make_scaffolder, name):
    target, result = _scaffold(make_scaffolder, _config(agents=["claude"]))

    assert (target / ".ai-badger" / "invariants" / f"{name}.md").is_file(), (
        f"{name}: not copied to .ai-badger/invariants/ — is it in {INVARIANTS_DIR}/ "
        f"and listed under common.invariants in index.json?"
    )
    entries = [e["name"] for e in result["manifest"]["entries"] if e["feature"] == "invariants"]
    assert name in entries, f"{name}: missing from the manifest's invariants entries"


# ------------------------------------------------------------------------------ rendering
@pytest.mark.parametrize("name", NEW_INVARIANTS)
def test_invariant_heading_reaches_claude_md(make_scaffolder, root, name):
    """Since 0.113.0 the body is summarised, so the assertion is the title and the link."""
    source = root / INVARIANTS_DIR / f"{name}.md"
    assert source.is_file(), f"{name}: source file missing at {source}"

    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]))
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    section = _invariants_section(claude_md)

    title = source.read_text(encoding="utf-8").strip().splitlines()[0].lstrip("#").strip()

    assert f"- **{title}**" in section, (
        f"{name}: title {title!r} not found under "
        f"'## Non-negotiable invariants' in the generated CLAUDE.md"
    )
    assert f"→ `.ai-badger/invariants/{name}.md`" in section, (
        f"{name}: the summary must link to the copy carrying the rationale"
    )


# --------------------------------------------------------------------------- house style
def test_every_common_invariant_is_at_most_six_lines(root):
    """These render into every scaffolded project's CLAUDE.md, read on every turn by every
    agent and subagent — the line cap is a token-budget guard, not a style preference."""
    offenders = {}
    for path in _invariant_files(root):
        if path.name in LONG_FORM:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > 6:
            offenders[path.name] = line_count
    assert not offenders, (
        f"invariant sources embed in every scaffolded CLAUDE.md and cost every project's "
        f"token budget on every turn — over 6 lines: {offenders}"
    )


def test_every_common_invariant_has_exactly_one_heading_on_its_first_line(root):
    offenders = {}
    for path in _invariant_files(root):
        lines = path.read_text(encoding="utf-8").splitlines()
        heading_lines = [i for i, line in enumerate(lines) if line.lstrip().startswith("#")]
        if heading_lines != [0]:
            offenders[path.name] = heading_lines
    assert not offenders, f"each invariant needs exactly one heading, as its first line: {offenders}"
