"""The shared Scaffolder factory: defaults, overrides, and the shared-target contract."""
from __future__ import annotations
from conftest import _test_write


def test_factory_defaults_produce_a_runnable_scaffolder(make_scaffolder):
    scaf = make_scaffolder()
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (make_scaffolder.target / ".ai-badger" / "state.json").exists()
    assert result["notes"] is not None


def test_factory_defaults_match_the_suite_wide_construction(make_scaffolder):
    """Defaults match the construction the call sites spell out by hand."""
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
    """overwrite/reset_seed_files/execute reach the constructor untouched."""
    scaf = make_scaffolder(skills=["prompt-markers"], reset_seed_files=True,
                           execute=True, overwrite=True)

    assert scaf.reset_seed_files is True
    assert scaf.execute is True
    # overwrite is threaded into ScaffoldContext rather than stored directly.
    assert scaf.overwrite is True


def test_repeated_calls_share_one_target_without_recreating_it(make_scaffolder):
    """Two scaffolders over one target: the second must not recreate the directory."""
    first = make_scaffolder()
    sentinel = make_scaffolder.target / "sentinel"
    _test_write(sentinel, "untouched", encoding="utf-8")

    second = make_scaffolder()

    assert second.target == first.target
    assert sentinel.read_text(encoding="utf-8") == "untouched"


def test_factory_accepts_an_explicit_target(make_scaffolder, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()

    scaf = make_scaffolder(target=other)

    assert scaf.target == other


def test_loaded_module_is_reachable_for_tests_that_need_it(make_scaffolder):
    """Several tests touch module-level functions, not just the class."""
    assert callable(make_scaffolder.module.demote_headings)
