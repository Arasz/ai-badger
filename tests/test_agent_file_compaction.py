"""The agent files carry the binding rule, not the whole essay (0.113.0).

Invariant bodies were inlined in full and made up 52-54% of every generated agent file, times
four files. They are now one bullet each — title, the sentence that states the rule, and a link
to the copy under `.ai-badger/invariants/` that carries the rationale.

The path-specific list had the opposite problem: it rendered `x.instructions.md` -> a path ending
in `x.instructions.md`, spending a line per file to repeat a basename while dropping the `applyTo`
glob that says *when* to read it.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import sys
import types

import pytest

RENDERING = "features/common/skills/welcome-ai-badger/scripts/template_rendering.py"


@pytest.fixture
def rendering(load_script, root):
    """template_rendering imports its siblings by bare name, as the scaffold runs it."""
    scripts = str(root / "features" / "common" / "skills" / "welcome-ai-badger" / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return load_script(RENDERING)


def _ctx(root):
    """The slots this suite exercises read only these four fields."""
    return types.SimpleNamespace(
        config={"project": {}, "commands": {}, "personaRouting": [], "stacks": []},
        mcp_described=[], index={"frameworkVersion": "0.0.0"}, root=root)


def test_path_instructions_render_the_glob_that_says_when_to_read_the_file(
        rendering, tmp_path):
    path = tmp_path / "python.instructions.md"
    path.write_text("---\ndescription: 'Python.'\napplyTo: '**/*.py'\n---\n\n# Python\n",
                    encoding="utf-8")

    slots = rendering.TemplateRendering(_ctx(tmp_path)).compute_doc_slots([], [path])

    assert slots["PATH_INSTRUCTIONS"] == (
        "- `**/*.py` → `.ai-badger/instructions/python.instructions.md`")


def test_a_file_without_a_glob_still_names_itself(rendering, tmp_path):
    """No `applyTo` means no trigger to state; the row must not silently disappear."""
    path = tmp_path / "documentation.instructions.md"
    path.write_text("---\ndescription: 'Docs.'\n---\n\n# Docs\n", encoding="utf-8")

    slots = rendering.TemplateRendering(_ctx(tmp_path)).compute_doc_slots([], [path])

    assert slots["PATH_INSTRUCTIONS"] == (
        "- `documentation.instructions.md` → "
        "`.ai-badger/instructions/documentation.instructions.md`")


def test_an_invariant_becomes_a_bullet_with_its_rule_and_a_link(rendering):
    text = ("# TDD is mandatory\n\nWrite a failing, behavior-focused test before any production "
            "code change. No production code without a test that demanded it.\n")

    line = rendering.invariant_summary(text, "tdd-is-mandatory")

    assert line == (
        "- **TDD is mandatory** — Write a failing, behavior-focused test before any production "
        "code change.\n  → `.ai-badger/invariants/tdd-is-mandatory.md`")


def test_the_summary_keeps_the_sentence_that_states_the_rule(rendering):
    """Consumers pin assertions to invariant wording; the operative sentence has to survive."""
    text = ("# Route state transitions through a state machine\n\nWhere a domain object has "
            "explicit states, make the declared transitions the only way it moves between them, "
            "and record what triggered each move. A status field assigned in one place and read "
            "in five is a state machine nobody can see.\n")

    line = rendering.invariant_summary(text, "state-transitions-through-a-machine")

    assert "record what triggered each move" in line
    assert "nobody can see" not in line


def test_an_abbreviation_is_not_the_end_of_the_sentence(rendering):
    """`(e.g. \\`userId\\`` matched the boundary pattern, so the rule stopped at "e.g." """
    text = ("# Partition by the tenant/owner key\n\nEvery entity carries the tenant/owner key "
            "(e.g. `userId` in a single-tenant-per-partition design) as an explicit field, and "
            "it is also the partition key. Every query filters or partitions by it.\n")

    line = rendering.invariant_summary(text, "partition-by-userid")

    assert "it is also the partition key" in line
    assert "Every query filters" not in line, "the second sentence still belongs in the file"


def test_a_rule_that_lives_in_a_list_keeps_the_list(rendering):
    """"Every release must:" on its own says nothing — truncating at the colon loses the rule.

    Caught by test_release_convention_invariant, which noticed the concrete
    `docs/changelog/{version}-{slug}.md` path had stopped reaching the agent files.
    """
    text = ("# Always bump VERSION\n\nEvery release — no matter how small — must:\n"
            "1. Bump `VERSION`\n2. Add a `docs/changelog/{version}-{slug}.md` entry\n\n"
            "This ensures every change is traceable.\n")

    line = rendering.invariant_summary(text, "version-changelog-required")

    assert "docs/changelog/{version}-{slug}.md" in line
    assert "1. Bump `VERSION`" in line
    assert "traceable" not in line, "only the opening block belongs in the summary"


def test_the_compressed_section_is_under_half_the_lines_it_replaces(rendering, load_script, root):
    """The point of the change, measured on the real catalog and in the unit the budget counts.

    Rendered-against-rendered: the old section was `demote_headings(body)` joined by blank lines,
    so comparing against raw source chars would flatter the result.
    """
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    sources = [p for p in sorted((root / "features" / "common" / "invariants").glob("*.md"))
               if p.name != "README.md"]
    assert len(sources) > 10, "too few invariants for this measurement to mean anything"

    inlined = "\n\n".join(scaffold.demote_headings(p.read_text(encoding="utf-8").strip())
                          for p in sources)
    compressed = "\n".join(rendering.invariant_summary(p.read_text(encoding="utf-8"), p.stem)
                           for p in sources)

    before, after = len(inlined.splitlines()), len(compressed.splitlines())
    assert after < before / 2, f"{after} lines against {before} — not worth the loss of detail"
