"""Project-local invariants: .ai-badger/invariants/local/*.md render into the agent files.

The convention (issue #313): a project-owned directory under the scaffolded project. Each
file renders as one summary bullet in the invariants section of CLAUDE.md/HERMES.md after all
framework invariants, linking back to `.ai-badger/invariants/local/` for the body (0.113.0 —
before that the whole body was inlined). Files are never copied into the framework catalog, recorded
in the manifest, pruned, or overwritten.
"""
from __future__ import annotations

from scaffold_helpers import _config

STATIC = "# Static classes only\n\nPrefer sealed records and pure functions over mutable classes.\n"


def _scaffold(make_scaffolder, config):
    target = make_scaffolder.target
    result = make_scaffolder(config=config).run(generated_at="2026-08-06T00:00:00Z")
    return target, result


def _local(target):
    return target / ".ai-badger" / "invariants" / "local"


def _invariants_section(doc: str) -> str:
    """The text between '## Non-negotiable invariants' and the next '## ' heading."""
    start = doc.index("## Non-negotiable invariants")
    rest = doc[start + len("## Non-negotiable invariants"):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


# ---------------------------------------------------------------------------- delivery
def test_a_local_invariant_renders_demoted_inside_the_section(make_scaffolder):
    target = make_scaffolder.target
    local = _local(target)
    local.mkdir(parents=True)
    (local / "static-classes.md").write_text(STATIC, encoding="utf-8")

    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]))
    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    section = _invariants_section(claude_md)

    assert "- **Static classes only**" in section
    assert "→ `.ai-badger/invariants/local/static-classes.md`" in section
    assert "Prefer sealed records and pure functions over mutable classes." in section
    assert not claude_md.rstrip().endswith("Static classes only")
    aib_copy = (target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "- **Static classes only**" in _invariants_section(aib_copy)
    assert (local / "static-classes.md").read_text(encoding="utf-8") == STATIC


def test_local_invariants_render_after_all_framework_invariants(make_scaffolder):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "static-classes.md").write_text(STATIC, encoding="utf-8")

    target, _ = _scaffold(make_scaffolder, _config(agents=["claude"]))
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))

    assert "- **TDD is mandatory**" in section
    assert section.index("- **Static classes only**") > section.index("- **TDD is mandatory**")
    assert "- **" not in section.split("- **Static classes only**", 1)[1]


def test_local_invariants_render_in_sorted_order(make_scaffolder):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "beta.md").write_text("# Beta rule\n\nSecond file.\n", encoding="utf-8")
    (local / "alpha.md").write_text("# Alpha rule\n\nFirst file.\n", encoding="utf-8")

    target, result = _scaffold(make_scaffolder, _config(agents=["claude"]))
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))

    assert section.index("- **Alpha rule**") < section.index("- **Beta rule**")
    assert any("rendered 2 project-local invariant(s)" in n for n in result["notes"])


def test_rescaffold_renders_edited_local_invariants_and_leaves_the_files_alone(make_scaffolder):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "static-classes.md").write_text(STATIC, encoding="utf-8")
    _scaffold(make_scaffolder, _config(agents=["claude"]))

    edited = "# Static classes only\n\nEdited: still no mutable state.\n"
    (local / "static-classes.md").write_text(edited, encoding="utf-8")
    target, result = _scaffold(make_scaffolder, _config(agents=["claude"]))

    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))
    assert "Edited: still no mutable state." in section
    assert (local / "static-classes.md").read_text(encoding="utf-8") == edited
    pruned_or_overwritten = [n for n in result["notes"]
                             if "invariants/local" in n and
                             ("removed" in n or "left in place" in n or "overwrit" in n)]
    assert not pruned_or_overwritten


def test_a_local_invariant_sharing_a_delivered_name_is_reported(make_scaffolder, root):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "tdd-mandatory.md").write_text(
        "# TDD is mandatory\n\nProject-local body line.\n", encoding="utf-8")

    target, result = _scaffold(make_scaffolder, _config(agents=["claude"]))

    framework_copy = target / ".ai-badger" / "invariants" / "tdd-mandatory.md"
    assert framework_copy.read_text(encoding="utf-8") == (
        root / "features" / "common" / "invariants" / "tdd-mandatory.md"
    ).read_text(encoding="utf-8")
    assert any("project-local invariant 'tdd-mandatory' shares a name" in n
               for n in result["notes"])
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))
    assert "Project-local body line." in section
    assert "Write a failing, behavior-focused test" in section


# ------------------------------------------------------------------------- empty slot
def _config_without_invariants(root):
    """A config that declines every catalog invariant, so only the slot fallback can fill."""
    config = _config(agents=["claude"])
    config["exclude"] = {
        "invariants": sorted(p.stem for p in root.glob("features/*/invariants/*.md"))
    }
    return config


def test_an_empty_local_dir_keeps_the_slot_sane(make_scaffolder, root):
    _local(make_scaffolder.target).mkdir(parents=True)

    target, _ = _scaffold(make_scaffolder, _config_without_invariants(root))
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))

    assert section.strip() == "_None yet._"


def test_a_whitespace_only_local_file_is_skipped_not_rendered(make_scaffolder, root):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "blank.md").write_text(" \n\t\n  \n", encoding="utf-8")

    target, _ = _scaffold(make_scaffolder, _config_without_invariants(root))
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))

    assert section.strip() == "_None yet._"
    assert "\n\n\n" not in section


def test_a_local_invariant_replaces_the_fallback_when_framework_invariants_are_excluded(
        make_scaffolder, root):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "static-classes.md").write_text(STATIC, encoding="utf-8")

    target, _ = _scaffold(make_scaffolder, _config_without_invariants(root))
    section = _invariants_section((target / "CLAUDE.md").read_text(encoding="utf-8"))

    assert "- **Static classes only**" in section
    assert section.strip() != "_None yet._"


# ------------------------------------------------------------------------ other hosts
def test_local_invariants_reach_hermes_md_too(make_scaffolder):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "static-classes.md").write_text(STATIC, encoding="utf-8")

    target, _ = _scaffold(make_scaffolder, _config(agents=["claude", "hermes"]))
    hermes_md = (target / "HERMES.md").read_text(encoding="utf-8")

    assert "- **Static classes only**" in _invariants_section(hermes_md)


# ----------------------------------------------------------------------- provenance
def test_local_invariants_never_enter_the_manifest_and_survive_rescaffold_byte_identical(
        make_scaffolder):
    local = _local(make_scaffolder.target)
    local.mkdir(parents=True)
    (local / "static-classes.md").write_text(STATIC, encoding="utf-8")

    target, result = _scaffold(make_scaffolder, _config(agents=["claude"]))
    entries = result["manifest"]["entries"]
    assert not [e for e in entries if "invariants/local" in e.get("target", "")]

    _scaffold(make_scaffolder, _config(agents=["claude"]))
    assert (local / "static-classes.md").read_text(encoding="utf-8") == STATIC
