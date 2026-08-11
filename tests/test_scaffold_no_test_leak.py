"""Flagship guard: framework tests and eval suites must never be scaffolded into a target repo.

If a skill directory ever gains a ``test_*.py``, ``tests/``, or ``evals/``, ``scaffold.py`` must
not copy it into the target's ``.ai-badger/skills/``. This exercises the real scaffold pipeline
end-to-end.
"""
from __future__ import annotations

import json
from conftest import _test_write


def _minimal_config() -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "leak-probe", "summary": "s", "domain": "d"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def test_scaffold_excludes_test_files_from_skills(tmp_path, root, make_scaffolder):
    skill_scripts = root / "features" / "common" / "skills" / "task" / "scripts"
    planted = skill_scripts / "test_should_not_scaffold.py"
    planted.write_text("def test_noop():\n    assert True\n", encoding="utf-8")  # deliberate real-repo write
    try:
        target = tmp_path / "proj"
        (target / "src").mkdir(parents=True)
        _test_write(target / "src" / "A.cs", "public class A {}\n", encoding="utf-8")
        config_path = target / "config.json"
        _test_write(config_path, json.dumps(_minimal_config()), encoding="utf-8")

        scaf = make_scaffolder(target=target, config=json.loads(config_path.read_text()),
                               skills=["task"])
        scaf.run(generated_at="2026-07-19T00:00:00Z")

        scaffolded = list((target / ".ai-badger" / "skills" / "task").rglob("test_*.py"))
        assert scaffolded == [], f"test files leaked into scaffold: {scaffolded}"
    finally:
        planted.unlink(missing_ok=True)


def test_scaffold_excludes_evals_from_skills(tmp_path, make_scaffolder):
    """The task skill ships evals/evals.json — a framework-only quality-regression harness.

    It must never land in a target repo's .ai-badger/skills/task/, the same way test files don't.
    """

    target = tmp_path / "proj"
    (target / "src").mkdir(parents=True)
    _test_write(target / "src" / "A.cs", "public class A {}\n", encoding="utf-8")
    config_path = target / "config.json"
    _test_write(config_path, json.dumps(_minimal_config()), encoding="utf-8")

    scaf = make_scaffolder(target=target, config=json.loads(config_path.read_text()),
                               skills=["task"])
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert not (target / ".ai-badger" / "skills" / "task" / "evals").exists()
