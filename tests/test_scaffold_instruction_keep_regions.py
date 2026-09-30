"""An instruction file's keep region must survive a re-scaffold.

`copy_file` wrote every instruction, invariant and persona file with a plain `shutil.copyfile`,
so the next scaffold replaced the project's edited copy with the framework's fresh one and
dropped every preserved region in it. That is the survival path the framework promises projects
(`welcome-ai-badger`: "Preserved regions survive"), and it is the path a consumer needed when a
den-refresh dropped its Cosmos registry guard line. `copy_file` now carries regions the same way
the managed agent files do.
"""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import scaffold_helpers
from conftest import _test_write

REGION = (
    "<!-- ai-badger:keep-start -->\n"
    "## Project registry\n\n"
    "- keep me: a new store needs a registry row\n"
    "<!-- ai-badger:keep-end -->"
)

INSTRUCTION = ".ai-badger/instructions/python.instructions.md"


def _scaffold(make_scaffolder, **kwargs):
    return make_scaffolder(**kwargs).run(generated_at="2026-07-19T00:00:00Z")


def test_a_keep_region_edited_into_an_instruction_file_survives_a_re_scaffold(make_scaffolder):
    target = make_scaffolder.target
    config = scaffold_helpers._config(stacks=["python"])
    _scaffold(make_scaffolder, config=config)

    edited = (target / INSTRUCTION).read_text(encoding="utf-8") + "\n\n" + REGION + "\n"
    _test_write(target / INSTRUCTION, edited, encoding="utf-8")

    _scaffold(make_scaffolder, config=config)

    after = (target / INSTRUCTION).read_text(encoding="utf-8")
    assert "keep me" in after
    assert after.count("ai-badger:keep-start") == 1


def test_the_framework_body_is_refreshed_around_the_carried_region(make_scaffolder):
    """Carrying a region must not freeze the file: the body still comes from the framework."""
    target = make_scaffolder.target
    config = scaffold_helpers._config(stacks=["python"])
    _scaffold(make_scaffolder, config=config)

    original = (target / INSTRUCTION).read_text(encoding="utf-8")
    deleted_bullet = "\n".join(
        line for line in original.splitlines()
        if "Target a currently supported CPython" not in line)
    _test_write(target / INSTRUCTION, deleted_bullet + "\n\n" + REGION + "\n", encoding="utf-8")

    _scaffold(make_scaffolder, config=config)

    after = (target / INSTRUCTION).read_text(encoding="utf-8")
    assert "Target a currently supported CPython" in after  # framework body is back
    assert "keep me" in after  # project region survived


def test_malformed_keep_markers_leave_the_instruction_file_untouched(make_scaffolder):
    """A keep-marker typo must not cost the project the file (welcome-ai-badger's promise)."""
    target = make_scaffolder.target
    config = scaffold_helpers._config(stacks=["python"])
    _scaffold(make_scaffolder, config=config)

    broken = "# python\n\n<!-- ai-badger:keep-start -->\nunclosed\n"
    _test_write(target / INSTRUCTION, broken, encoding="utf-8")

    result = _scaffold(make_scaffolder, config=config)

    assert (target / INSTRUCTION).read_text(encoding="utf-8") == broken
    assert any("left untouched" in note for note in result["notes"]), result["notes"]


def test_a_carried_region_does_not_read_as_drift(make_scaffolder, root, load_script):
    """The recorded hash has to be the source's, or every later refresh reports the region as
    drift and re-scaffolds forever."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    target = make_scaffolder.target
    config = scaffold_helpers._config(stacks=["python"])
    _scaffold(make_scaffolder, config=config)

    edited = (target / INSTRUCTION).read_text(encoding="utf-8") + "\n\n" + REGION + "\n"
    _test_write(target / INSTRUCTION, edited, encoding="utf-8")

    result = _scaffold(make_scaffolder, config=config)
    assert "keep me" in (target / INSTRUCTION).read_text(encoding="utf-8")

    compared = drift.compare(root, result["manifest"])

    assert "features/python/instructions/python.instructions.md" not in compared["changed"]
