"""Seed-once files: written on the first scaffold, owned by the project from then on."""
from __future__ import annotations

import json


# ---------------------------------------------------------------------- seed-once vs managed
# GitHub issue Arasz/ai-badger#15: re-scaffolding a live project must never destroy project-owned
# data. state.json (a task index) and features/common/skills/prompt-markers/markers-context.json (a project's
# customized marker config) are SEED-ONCE: the framework writes them on first scaffold, then the
# project owns them. Managed files (SKILL.md, scripts) inside the very same skill directory must
# still refresh normally -- only the specific seed-once sub-file is protected.
def test_scaffold_state_json_mutation_survives_second_scaffold(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    state_path = target / ".ai-badger" / "state.json"
    assert state_path.exists()
    mutated = {"lastUpdated": "2026-07-19T00:00:00Z", "next": None,
               "completedTasks": [{"id": 1}, {"id": 2}, {"id": 3},
                                   {"id": 4}, {"id": 5}, {"id": 6}, {"id": 7}, {"id": 8}]}
    state_path.write_text(json.dumps(mutated), encoding="utf-8")

    make_scaffolder().run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(state_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_prompt_markers_config_mutation_survives_second_scaffold(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")

    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    assert marker_path.exists()
    mutated = {"markers": {"h": "custom-hint-marker"}}
    marker_path.write_text(json.dumps(mutated), encoding="utf-8")

    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(marker_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_prompt_markers_skill_md_still_refreshes_when_config_is_preserved(
    make_scaffolder
):
    """Guard against over-correction: only markers-context.json is seed-once. SKILL.md (a
    managed file living in the very same skill directory) must still be refreshed to the
    framework's current content on re-scaffold."""
    target = make_scaffolder.target
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")

    skill_dir = target / ".ai-badger" / "skills" / "prompt-markers"
    marker_path = skill_dir / "markers-context.json"
    marker_path.write_text(json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")
    skill_md_path = skill_dir / "SKILL.md"
    original_skill_md = skill_md_path.read_text(encoding="utf-8")
    skill_md_path.write_text("# locally tampered content, should be refreshed away\n",
                              encoding="utf-8")

    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:05:00Z")

    assert skill_md_path.read_text(encoding="utf-8") == original_skill_md
    assert json.loads(marker_path.read_text(encoding="utf-8")) == {"markers": {"h": "custom"}}


def test_scaffold_seeds_state_json_on_first_run(make_scaffolder, root):
    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    state_path = make_scaffolder.target / ".ai-badger" / "state.json"
    assert state_path.exists()
    template = (root / "features" / "common" / "templates" / "state.json")
    assert json.loads(state_path.read_text(encoding="utf-8")) == json.loads(
        template.read_text(encoding="utf-8"))


def test_scaffold_seeds_prompt_markers_config_on_first_run(make_scaffolder, root):
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")

    marker_path = (make_scaffolder.target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    assert marker_path.exists()
    template = root / "features" / "common" / "skills" / "prompt-markers" / "markers-context.json"
    assert json.loads(marker_path.read_text(encoding="utf-8")) == json.loads(
        template.read_text(encoding="utf-8"))


def test_scaffold_model_json_seed_once_regression_pin(make_scaffolder):
    """model.json's seed-once behavior is already correct but had zero test coverage before
    this pin -- nothing stopped a refactor from silently breaking it."""
    target = make_scaffolder.target
    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    model_path = target / ".ai-badger" / "agent-instructions" / "model.json"
    assert model_path.exists()
    mutated = {"version": 1, "files": {"custom.md": "custom-instructions"}}
    model_path.write_text(json.dumps(mutated), encoding="utf-8")

    make_scaffolder().run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(model_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_reset_seed_files_flag_forces_reset(make_scaffolder, root):
    target = make_scaffolder.target
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")

    state_path = target / ".ai-badger" / "state.json"
    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    state_path.write_text(json.dumps({"lastUpdated": "mutated", "next": None,
                                       "completedTasks": []}), encoding="utf-8")
    marker_path.write_text(json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")

    make_scaffolder(skills=["prompt-markers"], reset_seed_files=True).run(
        generated_at="2026-07-19T00:05:00Z")

    template_state = json.loads(
        (root / "features" / "common" / "templates" / "state.json").read_text(encoding="utf-8"))
    template_marker = json.loads(
        (root / "features" / "common" / "skills" / "prompt-markers" / "markers-context.json").read_text(encoding="utf-8"))
    assert json.loads(state_path.read_text(encoding="utf-8")) == template_state
    assert json.loads(marker_path.read_text(encoding="utf-8")) == template_marker


# --------------------------------------------------------- project-local.md append
def test_scaffold_appends_project_local_md_to_skill(make_scaffolder):
    """project-local.md content is appended to SKILL.md after scaffold."""
    target = make_scaffolder.target

    # First scaffold — creates the skill
    make_scaffolder(skills=["task"]).run(generated_at="2026-07-24T00:00:00Z")

    skill_md = target / ".ai-badger" / "skills" / "task" / "SKILL.md"

    # Write project-local additions
    pl = target / ".ai-badger" / "skills" / "task" / "project-local.md"
    pl.write_text("\n## Project-Specific Checks\n\n- [ ] Check X\n- [ ] Check Y\n")

    # Re-scaffold — project-local.md should be preserved and appended
    result = make_scaffolder(skills=["task"]).run(generated_at="2026-07-24T00:00:00Z")

    refreshed = skill_md.read_text()
    assert "## Project-Specific Checks" in refreshed, "project-local content not appended"
    assert "- [ ] Check X" in refreshed, "project-local item missing"
    assert refreshed.endswith("- [ ] Check Y\n"), "trailing newline missing"
    assert any("appended project-local.md" in n for n in result["notes"]), (
        f"Expected append note, got: {result['notes']}"
    )


def test_scaffold_preserves_project_local_md_across_rescaffold(make_scaffolder):
    """project-local.md is seed-once: survives re-scaffold without overwriting."""
    target = make_scaffolder.target
    make_scaffolder(skills=["task"]).run(generated_at="2026-07-24T00:00:00Z")

    pl = target / ".ai-badger" / "skills" / "task" / "project-local.md"
    pl.write_text("## My Project\n\n- [ ] Custom check\n")

    # Re-scaffold 3 times — project-local.md must survive each
    for _ in range(3):
        make_scaffolder(skills=["task"]).run(generated_at="2026-07-24T00:00:00Z")

    assert pl.exists(), "project-local.md was lost during re-scaffold"
    assert "Custom check" in pl.read_text(), "project-local.md content was reset"
    skill_md = target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    assert "## My Project" in skill_md.read_text(), "project-local not appended after re-scaffold"
