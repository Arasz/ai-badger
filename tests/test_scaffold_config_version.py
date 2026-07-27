"""The config the scaffolder writes must say which framework version wrote it."""
from __future__ import annotations

import json


def _config() -> dict:
    """A config carrying a deliberately stale frameworkVersion."""
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaffold_into(tmp_path, load_script, root, config):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    scaffold.Scaffolder(root=root, target=target, config=config,
                        skills=[], install=False).run(generated_at="2026-07-27T00:00:00Z")
    return json.loads((target / ".ai-badger" / "config.json").read_text(encoding="utf-8"))


def _framework_version(root) -> str:
    return json.loads((root / "index.json").read_text(encoding="utf-8"))["frameworkVersion"]


class TestScaffoldStampsFrameworkVersion:
    """config.frameworkVersion means 'the version that generated this' — so it must be true."""

    def test_the_written_config_carries_the_current_framework_version(self, tmp_path,
                                                                      load_script, root):
        written = _scaffold_into(tmp_path, load_script, root, _config())

        assert written["frameworkVersion"] == _framework_version(root)

    def test_a_stale_incoming_version_is_replaced_not_preserved(self, tmp_path,
                                                                load_script, root):
        """Copying 0.1.0 through is what let a real project claim 0.18.1 for nine releases."""
        written = _scaffold_into(tmp_path, load_script, root, _config())

        assert written["frameworkVersion"] != "0.1.0"

    def test_the_callers_config_dict_is_not_mutated(self, tmp_path, load_script, root):
        """The scaffolder owns its output copy, not the dict it was handed."""
        config = _config()

        _scaffold_into(tmp_path, load_script, root, config)

        assert config["frameworkVersion"] == "0.1.0"

    def test_every_other_config_key_survives_the_stamp(self, tmp_path, load_script, root):
        config = _config()

        written = _scaffold_into(tmp_path, load_script, root, config)

        for key, value in config.items():
            if key != "frameworkVersion":
                assert written[key] == value, key
