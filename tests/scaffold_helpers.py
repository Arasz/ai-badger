"""Shared config body and Scaffolder factory for the scaffold test modules."""
from __future__ import annotations

SCAFFOLD_SCRIPT = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _config(stacks=None, source_control=None, commands=None, agents=None) -> dict:
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": stacks if stacks is not None else ["dotnet"],
        "agents": agents if agents is not None else ["claude"],
        "sourceControl": source_control if source_control is not None else
            {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": commands if commands is not None else {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def build_scaffolder(module, *, root, target, config=None, skills=None,
                     install=False, **kwargs):
    """Construct a Scaffolder with the suite's default keywords; kwargs reach the constructor."""
    return module.Scaffolder(
        root=root,
        target=target,
        config=_config() if config is None else config,
        skills=[] if skills is None else skills,
        install=install,
        **kwargs)
