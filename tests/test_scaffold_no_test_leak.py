"""Flagship guard: framework tests must never be scaffolded into a target repo.

If a skill directory ever gains a ``test_*.py`` or ``tests/``, ``scaffold.py`` must not copy it
into the target's ``.ai-badger/skills/``. This exercises the real scaffold pipeline end-to-end.
"""
from __future__ import annotations

import json


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
        "pluginScope": "default",
        "docs": {},
    }


def test_scaffold_excludes_test_files_from_skills(tmp_path, load_script, root):
    scaffold = load_script("skills/welcome-ai-badger/scripts/scaffold.py")

    # plant a stray test file inside the real task skill source, mimicking future test drift
    skill_scripts = root / "skills" / "task" / "scripts"
    planted = skill_scripts / "test_should_not_scaffold.py"
    planted.write_text("def test_noop():\n    assert True\n", encoding="utf-8")
    try:
        target = tmp_path / "proj"
        (target / "src").mkdir(parents=True)
        (target / "src" / "A.cs").write_text("public class A {}\n", encoding="utf-8")
        config_path = target / "config.json"
        config_path.write_text(json.dumps(_minimal_config()), encoding="utf-8")

        scaf = scaffold.Scaffolder(
            root=root, target=target, config=json.loads(config_path.read_text()),
            skills=["task"], install=False,
        )
        scaf.run(generated_at="2026-07-19T00:00:00Z")

        scaffolded = list((target / ".ai-badger" / "skills" / "task").rglob("test_*.py"))
        assert scaffolded == [], f"test files leaked into scaffold: {scaffolded}"
    finally:
        planted.unlink(missing_ok=True)
