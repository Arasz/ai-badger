"""support.json must describe the catalog it ships, not a file the scaffolder never writes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _declared_scaffolded_files():
    support = json.loads(
        (ROOT / "features" / "common" / "support.json").read_text(encoding="utf-8"))
    return [
        pytest.param(agent, capability["scaffoldedFile"], id=f"{agent}-{name}")
        for agent, spec in support["agents"].items()
        for name, capability in (spec.get("capabilities") or {}).items()
        if isinstance(capability, dict) and "scaffoldedFile" in capability
    ]


@pytest.mark.parametrize("agent,scaffolded_file", _declared_scaffolded_files())
def test_a_declared_scaffolded_file_is_one_the_agent_scaffolding_writes(agent, scaffolded_file):
    path = ROOT / "features" / agent / "scaffolding.json"
    assert path.is_file(), f"{agent} declares scaffoldedFile but ships no scaffolding.json"

    targets = [f.get("target") for f in json.loads(path.read_text(encoding="utf-8"))["files"]]

    assert scaffolded_file in targets, (
        f"support.json says ai-badger scaffolds {scaffolded_file!r} for {agent}, "
        f"but features/{agent}/scaffolding.json writes {targets}")
