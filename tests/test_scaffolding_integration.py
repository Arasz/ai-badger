"""Tests for scaffold.py's scaffolding.json integration.

When a features/<agent>/scaffolding.json exists, scaffold.py should use it to
determine what files to write for that agent, falling back to hardcoded behavior
when no scaffolding.json is present.
"""
from __future__ import annotations

import json
import shutil


def _minimal_config(agents=None):
    return {
        "frameworkVersion": "0.2.0",
        "project": {"name": "test-proj"},
        "stacks": ["python"],
        "agents": agents or ["claude"],
        "commands": {"test": "pytest"},
    }


def test_scaffolder_reads_scaffolding_json_for_agent(tmp_path, root, load_script):
    """When features/<agent>/scaffolding.json exists, the scaffolder should use it
    to write the declared files."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    # Create a minimal framework tree with a test agent that has scaffolding.json
    features = tmp_path / "features"
    test_agent = features / "test-agent"
    (test_agent / "templates").mkdir(parents=True)
    (test_agent / "templates" / "hello.md").write_text("# Hello from test-agent\n", encoding="utf-8")
    (test_agent / "scaffolding.json").write_text(json.dumps({
        "agent": "test-agent",
        "files": [
            {"source": "templates/hello.md", "target": "HELLO.md", "managed": True}
        ],
    }), encoding="utf-8")
    (test_agent / "stack.json").write_text(json.dumps({
        "name": "test-agent",
        "description": "test",
    }), encoding="utf-8")

    # Copy schemas for validation
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    (tmp_path / "VERSION").write_text("0.2.0\n", encoding="utf-8")

    # Create a minimal index
    index = {
        "$schema": "./schemas/index.schema.json",
        "frameworkVersion": "0.2.0",
        "stacks": {
            "common": {
                "skills": [
                    {"name": "prompt-markers", "path": "features/common/skills/prompt-markers"}
                ]
            }
        },
    }
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")

    # Copy prompt-markers skill (needed by scaffold)
    pm_src = root / "features" / "common" / "skills" / "prompt-markers"
    pm_dst = tmp_path / "features" / "common" / "skills" / "prompt-markers"
    shutil.copytree(pm_src, pm_dst)

    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(
        root=tmp_path, target=target, config=config,
        skills=[], install=False,
    )
    result = scaf.run(generated_at=None)

    # The scaffolder should have written the file declared in scaffolding.json
    hello_file = target / "HELLO.md"
    assert hello_file.exists()
    content = hello_file.read_text(encoding="utf-8")
    assert "Hello from test-agent" in content
    # Should have the managed header
    assert "Managed by ai-badger" in content


def test_scaffolder_falls_back_when_no_scaffolding_json(tmp_path, root, load_script):
    """When no scaffolding.json exists for an agent, the scaffolder should use
    existing hardcoded behavior (no crash, no error)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    # Use the real framework root — claude has no scaffolding.json yet in this test
    # (it does in production, but we're testing the fallback path)
    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["junie"])  # junie has no scaffolding.json
    scaf = scaffold.Scaffolder(
        root=root, target=target, config=config,
        skills=[], install=False,
    )
    result = scaf.run(generated_at=None)

    # Should not crash — fallback to hardcoded behavior
    assert "manifest" in result
