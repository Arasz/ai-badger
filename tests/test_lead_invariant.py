"""The simplified-technical-english invariant leads the invariants section of every agent file.

It governs every response and report an agent writes, so it sits first, where an agent reads it
before any other rule (critical-instruction-placement), instead of in its alphabetical slot.
"""
from __future__ import annotations

from scaffold_helpers import _config

LEAD = "simplified-technical-english"


def _bullets(doc: str) -> list:
    """The invariant bullets between '## Non-negotiable invariants' and the next '## ' heading."""
    start = doc.index("## Non-negotiable invariants")
    rest = doc[start + len("## Non-negotiable invariants"):]
    end = rest.find("\n## ")
    section = rest if end == -1 else rest[:end]
    return [line for line in section.splitlines() if line.startswith("- **")]


def test_the_ste_invariant_is_the_first_bullet_in_every_agent_file(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder(config=_config(agents=["claude", "hermes", "pi", "codex"])).run(
        generated_at="2026-10-23T00:00:00Z")

    files = ["CLAUDE.md", "HERMES.md", "AGENTS.override.md", "AGENTS.md"]
    for name in files:
        bullets = _bullets((target / ".ai-badger" / name).read_text(encoding="utf-8"))
        assert bullets, name
        assert f"(`{LEAD}`)" in bullets[0], f"{name}: {bullets[0]}"
        assert sum(f"(`{LEAD}`)" in b for b in bullets) == 1, name


def test_the_other_common_invariants_keep_their_sorted_order(make_scaffolder, root):
    target = make_scaffolder.target
    make_scaffolder(config=_config(agents=["claude"])).run(generated_at="2026-10-23T00:00:00Z")

    names = [b.split("(`", 1)[1].split("`)", 1)[0]
             for b in _bullets((target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8"))]
    common = {p.stem for p in (root / "features" / "common" / "invariants").glob("*.md")}
    rest = [n for n in names[1:] if n in common]
    assert names[0] == LEAD
    assert rest == sorted(common - {LEAD})
