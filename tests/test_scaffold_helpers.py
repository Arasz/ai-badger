"""The shared Scaffolder factory: defaults, overrides, and the shared-target contract."""
from __future__ import annotations

import json


def test_factory_defaults_produce_a_runnable_scaffolder(make_scaffolder):
    scaf = make_scaffolder()
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (make_scaffolder.target / ".ai-badger" / "state.json").exists()
    assert result["notes"] is not None


def test_factory_defaults_match_the_suite_wide_construction(make_scaffolder):
    """The defaults are the shape 48 of the call sites spelled out by hand."""
    scaf = make_scaffolder()

    assert scaf.skills == []
    assert scaf.install is False
    assert scaf.config["stacks"] == ["dotnet"]


def test_factory_passes_through_skills_and_config(make_scaffolder):
    from scaffold_helpers import _config

    scaf = make_scaffolder(skills=["prompt-markers"], config=_config(stacks=["python"]))

    assert scaf.skills == ["prompt-markers"]
    assert scaf.config["stacks"] == ["python"]


def test_factory_forwards_unknown_keywords_to_the_constructor(make_scaffolder):
    """reset_seed_files/execute/overwrite appear at a handful of sites and must survive."""
    scaf = make_scaffolder(skills=["prompt-markers"], reset_seed_files=True)

    assert scaf.reset_seed_files is True


def test_repeated_calls_share_one_target_without_recreating_it(make_scaffolder):
    """The seed-once pattern: two scaffolders over one target, second must not reset it."""
    first = make_scaffolder()
    first.run(generated_at="2026-07-19T00:00:00Z")

    state_path = make_scaffolder.target / ".ai-badger" / "state.json"
    mutated = {"lastUpdated": "x", "next": None, "completedTasks": []}
    state_path.write_text(json.dumps(mutated), encoding="utf-8")

    second = make_scaffolder()
    second.run(generated_at="2026-07-19T00:05:00Z")

    assert second.target == first.target
    assert json.loads(state_path.read_text(encoding="utf-8")) == mutated


def test_factory_accepts_an_explicit_target(make_scaffolder, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()

    scaf = make_scaffolder(target=other)

    assert scaf.target == other


def test_loaded_module_is_reachable_for_tests_that_need_it(make_scaffolder):
    """Several tests touch module-level functions, not just the class."""
    assert callable(make_scaffolder.module.demote_headings)
