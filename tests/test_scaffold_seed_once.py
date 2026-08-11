"""Seed-once files: written on the first scaffold, owned by the project from then on."""
from __future__ import annotations

import json
from conftest import _test_write


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
    _test_write(state_path, json.dumps(mutated), encoding="utf-8")

    make_scaffolder().run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(state_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_prompt_markers_config_mutation_survives_second_scaffold(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")

    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    assert marker_path.exists()
    mutated = {"markers": {"h": "custom-hint-marker"}}
    _test_write(marker_path, json.dumps(mutated), encoding="utf-8")

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
    _test_write(marker_path, json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")
    skill_md_path = skill_dir / "SKILL.md"
    original_skill_md = skill_md_path.read_text(encoding="utf-8")
    _test_write(skill_md_path, "# locally tampered content, should be refreshed away\n", encoding="utf-8")

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
    _test_write(model_path, json.dumps(mutated), encoding="utf-8")

    make_scaffolder().run(generated_at="2026-07-19T00:05:00Z")

    assert json.loads(model_path.read_text(encoding="utf-8")) == mutated


def test_scaffold_reset_seed_files_flag_forces_reset(make_scaffolder, root):
    target = make_scaffolder.target
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")

    state_path = target / ".ai-badger" / "state.json"
    marker_path = (target / ".ai-badger" / "skills" / "prompt-markers"
                   / "markers-context.json")
    _test_write(state_path, json.dumps({"lastUpdated": "mutated", "next": None,
                                       "completedTasks": []}), encoding="utf-8")
    _test_write(marker_path, json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")

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
    _test_write(pl, "\n## Project-Specific Checks\n\n- [ ] Check X\n- [ ] Check Y\n")

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
    _test_write(pl, "## My Project\n\n- [ ] Custom check\n")

    # Re-scaffold 3 times — project-local.md must survive each
    for _ in range(3):
        make_scaffolder(skills=["task"]).run(generated_at="2026-07-24T00:00:00Z")

    assert pl.exists(), "project-local.md was lost during re-scaffold"
    assert "Custom check" in pl.read_text(), "project-local.md content was reset"
    skill_md = target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    assert "## My Project" in skill_md.read_text(), "project-local not appended after re-scaffold"


# ------------------------------------------------------- the manifest says which is which
# The edit-time guard (generated_file_guard.py) has no other way to tell a template the next
# scaffold rewrites from one it seeds and then leaves alone (#354 follow-up, wave 4 W1).
def test_the_manifest_flags_seed_once_targets_and_only_those(make_scaffolder):
    manifest_path = make_scaffolder.target / ".ai-badger" / "manifest.json"

    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
    assert {e["target"] for e in entries if e.get("seedOnce")} == {
        ".ai-badger/state.json", ".ai-badger/agent-instructions/model.json"}


def test_a_regenerated_template_is_not_flagged_seed_once(make_scaffolder):
    """CLAUDE.md is rewritten on every run; flagging it would exempt it from the edit guard."""
    manifest_path = make_scaffolder.target / ".ai-badger" / "manifest.json"

    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
    rewritten = [e for e in entries
                 if e["target"] in ("CLAUDE.md", ".ai-badger/agent-instructions/schema.json")]
    assert len(rewritten) == 2, f"expected both regenerated templates recorded, got {rewritten}"
    assert not any(e.get("seedOnce") for e in rewritten)


def test_a_scaffolding_json_seed_once_entry_reaches_the_manifest(make_scaffolder, monkeypatch):
    """`seedOnce` in features/<agent>/scaffolding.json is the third seed-once site.

    Injected rather than declared: no agent ships one today, and the guard must not start
    denying edits to a file the scaffolder has been told to leave alone.
    """
    import badger_lib as bl

    real_load = bl.load_json

    def _seed_once_claude(path):
        loaded = real_load(path)
        if str(path).endswith("claude/scaffolding.json"):
            for entry in loaded["files"]:
                entry["seedOnce"] = True
        return loaded

    monkeypatch.setattr(bl, "load_json", _seed_once_claude)
    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    manifest = json.loads(
        (make_scaffolder.target / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    claude_md = [e for e in manifest["entries"] if e["target"] == "CLAUDE.md"]
    assert len(claude_md) == 1, f"CLAUDE.md not recorded once: {claude_md}"
    assert claude_md[0].get("seedOnce") is True


# ------------------------------------- the manifest names the files inside a skill it preserves
# Same question one level down: a skill directory is one manifest entry, so the edit-time guard
# cannot tell the copied files from the ones the scaffold stashes and restores. `projectOwned`
# lists the second kind on the skill's own entry, from the list the preservation reads (#15).
def _skill_entry(target, name):
    manifest = json.loads((target / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    matches = [e for e in manifest["entries"]
               if e.get("target") == f".ai-badger/skills/{name}" and e.get("feature") == "skills"]
    assert len(matches) == 1, f"expected one skills entry for {name}, got {matches}"
    return matches[0]


def test_the_manifest_lists_the_project_owned_files_of_each_delivered_skill(make_scaffolder):
    make_scaffolder(skills=["prompt-markers", "task"]).run(generated_at="2026-07-19T00:00:00Z")

    target = make_scaffolder.target
    assert _skill_entry(target, "prompt-markers")["projectOwned"] == [
        "project-local.md", "markers-context.json"]
    assert _skill_entry(target, "task")["projectOwned"] == ["project-local.md"]


def test_a_newly_preserved_skill_file_is_allowed_without_touching_the_guard(
        make_scaffolder, load_script, monkeypatch):
    """The acceptance the two-list shape kept failing: adding a name in one place is enough."""
    import skill_delivery

    monkeypatch.setitem(skill_delivery.SEED_ONCE_SKILL_FILES, "task", ["local-notes.json"])
    make_scaffolder(skills=["task"]).run(generated_at="2026-07-19T00:00:00Z")

    target = make_scaffolder.target
    assert "local-notes.json" in _skill_entry(target, "task")["projectOwned"]
    guard = load_script(
        "features/common/skills/welcome-ai-badger/scripts/generated_file_guard.py")
    skill = target / ".ai-badger" / "skills" / "task"
    assert guard.refusal(skill / "local-notes.json") is None
    assert guard.refusal(skill / "SKILL.md") is not None, \
        "the same skill's generated files must still be refused"


def test_editing_a_project_owned_file_does_not_move_the_skills_recorded_hash(make_scaffolder):
    """A skill entry's `hash` is what `scaffold_freshness_guard` re-derives; if a preserved
    file moves it, the push gate rejects the edit the edit-time guard just allowed."""
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:00:00Z")
    target = make_scaffolder.target
    before = _skill_entry(target, "prompt-markers")

    marker = target / ".ai-badger" / "skills" / "prompt-markers" / "markers-context.json"
    _test_write(marker, json.dumps({"markers": {"h": "custom"}}), encoding="utf-8")
    make_scaffolder(skills=["prompt-markers"]).run(generated_at="2026-07-19T00:05:00Z")

    after = _skill_entry(target, "prompt-markers")
    assert after["hash"] == before["hash"]
    assert after["dirMeta"] == before["dirMeta"]


def test_the_recorded_hash_still_covers_the_generated_files_beside_it(make_scaffolder, root,
                                                                     tmp_path):
    """Over-correction check: excluding the preserved file must not blind the hash."""
    import shutil

    framework = tmp_path / "fw"
    shutil.copytree(root, framework, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".venv",
                                                  ".ai-badger"))
    make_scaffolder(root=framework, skills=["prompt-markers"]).run(
        generated_at="2026-07-19T00:00:00Z")
    before = _skill_entry(make_scaffolder.target, "prompt-markers")

    catalog = framework / "features" / "common" / "skills" / "prompt-markers" / "SKILL.md"
    _test_write(catalog, catalog.read_text(encoding="utf-8") + "\nmoved\n", encoding="utf-8")
    make_scaffolder(root=framework, skills=["prompt-markers"]).run(
        generated_at="2026-07-19T00:05:00Z")

    assert _skill_entry(make_scaffolder.target, "prompt-markers")["hash"] != before["hash"]
