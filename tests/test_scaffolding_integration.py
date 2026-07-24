"""Tests for scaffold.py's scaffolding.json integration.

When a features/<agent>/scaffolding.json exists, scaffold.py should use it to
determine what files to write for that agent. When no scaffolding.json is present,
the scaffolder logs a note and skips the agent.
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


def _make_test_framework(tmp_path, root, scaffolding_json=None):
    """Create a minimal framework tree with a test agent."""
    features = tmp_path / "features"
    test_agent = features / "test-agent"
    (test_agent / "templates").mkdir(parents=True)
    (test_agent / "templates" / "hello.md").write_text("# Hello from test-agent\n", encoding="utf-8")
    (test_agent / "templates" / "hello.tmpl").write_text(
        "# {{PROJECT_NAME}} — hello\n", encoding="utf-8")
    if scaffolding_json:
        (test_agent / "scaffolding.json").write_text(
            json.dumps(scaffolding_json), encoding="utf-8")
    (test_agent / "stack.json").write_text(json.dumps({
        "name": "test-agent", "description": "test",
    }), encoding="utf-8")

    shutil.copytree(root / "schemas", tmp_path / "schemas")
    (tmp_path / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    index = {
        "$schema": "./schemas/index.schema.json",
        "frameworkVersion": "0.2.0",
        "stacks": {"common": {"skills": [
            {"name": "prompt-markers", "path": "features/common/skills/prompt-markers"}
        ]}},
    }
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    pm_src = root / "features" / "common" / "skills" / "prompt-markers"
    pm_dst = tmp_path / "features" / "common" / "skills" / "prompt-markers"
    shutil.copytree(pm_src, pm_dst)
    return tmp_path


# --- Schema validation tests ---

def test_scaffolding_schema_validates_minimal_file(tmp_path, root, load_script):
    """A minimal scaffolding.json with one file entry must pass schema validation."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {
        "agent": "claude",
        "files": [
            {"source": "templates/CLAUDE.md", "target": "CLAUDE.md", "managed": True}
        ],
    }
    errors = badger_lib.validate(instance, schema)
    assert errors == []


def test_scaffolding_schema_rejects_missing_agent(tmp_path, root, load_script):
    """Missing 'agent' field must fail validation."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {"files": [{"source": "x", "target": "y", "managed": True}]}
    errors = badger_lib.validate(instance, schema)
    assert len(errors) > 0


def test_scaffolding_schema_rejects_missing_files(tmp_path, root, load_script):
    """Missing 'files' field must fail validation."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {"agent": "claude"}
    errors = badger_lib.validate(instance, schema)
    assert len(errors) > 0


def test_scaffolding_schema_rejects_missing_required_file_fields(tmp_path, root, load_script):
    """Each file entry must have source, target, and managed."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {"agent": "claude", "files": [{"source": "templates/CLAUDE.md"}]}
    errors = badger_lib.validate(instance, schema)
    assert len(errors) > 0


def test_scaffolding_schema_accepts_optional_seed_once(tmp_path, root, load_script):
    """The seedOnce boolean must be accepted as an optional field."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    instance = {
        "agent": "prompt-markers",
        "files": [{
            "source": "markers-context.json", "target": "markers-context.json",
            "managed": True, "seedOnce": True,
        }],
    }
    errors = badger_lib.validate(instance, schema)
    assert errors == []


def test_scaffolding_schema_validates_example_instance(root, load_script):
    """A realistic scaffolding.json must pass validation against its schema."""
    badger_lib = load_script("scripts/badger_lib.py")
    schema = badger_lib.load_json(root / "schemas" / "scaffolding.schema.json")
    scaffolding = {
        "agent": "claude",
        "description": "Claude Code agent discovery files",
        "files": [{
            "source": "templates/CLAUDE.md", "target": "CLAUDE.md", "managed": True,
        }],
    }
    errors = badger_lib.validate(scaffolding, schema)
    assert errors == []


# --- Integration tests ---

def test_scaffolder_reads_scaffolding_json_for_agent(tmp_path, root, load_script):
    """When features/<agent>/scaffolding.json exists, the scaffolder should use it
    to write the declared files."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    fw = _make_test_framework(tmp_path, root, scaffolding_json={
        "agent": "test-agent",
        "files": [
            {"source": "templates/hello.md", "target": "HELLO.md", "managed": True}
        ],
    })
    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(root=fw, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    hello_file = target / "HELLO.md"
    assert hello_file.exists()
    content = hello_file.read_text(encoding="utf-8")
    assert "Hello from test-agent" in content
    assert "Managed by ai-badger" in content


def test_scaffolder_skips_agent_without_scaffolding_json(tmp_path, root, load_script):
    """When an agent has no scaffolding.json, the scaffolder logs a note and skips it
    without crashing."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    target = tmp_path / "proj"
    target.mkdir()

    # "unknown-agent" has no features/unknown-agent/scaffolding.json in the real repo
    config = _minimal_config(agents=["unknown-agent"])
    scaf = scaffold.Scaffolder(root=root, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    # Should not crash — just skip the agent with a note
    assert "manifest" in result
    assert any("no scaffolding.json" in n for n in result["notes"])


def test_scaffolder_template_flag_renders_source(tmp_path, root, load_script):
    """When template=True, the scaffolder should render the .tmpl source with
    standard slots (PROJECT_NAME, etc.) instead of copying it verbatim."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    fw = _make_test_framework(tmp_path, root, scaffolding_json={
        "agent": "test-agent",
        "files": [{
            "source": "templates/hello.tmpl", "target": "HELLO.md",
            "managed": True, "template": True,
        }],
    })
    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(root=fw, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    hello_file = target / "HELLO.md"
    assert hello_file.exists()
    content = hello_file.read_text(encoding="utf-8")
    # Template should have been rendered with PROJECT_NAME
    assert "test-proj" in content
    assert "{{PROJECT_NAME}}" not in content


def test_scaffolder_template_with_managed_false_writes_rendered_content(tmp_path, root, load_script):
    """When template=True and managed=False, the scaffolder should write the
    RENDERED content, not the raw .tmpl source file. This is the latent bug fix."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    fw = _make_test_framework(tmp_path, root, scaffolding_json={
        "agent": "test-agent",
        "files": [{
            "source": "templates/hello.tmpl", "target": "HELLO.md",
            "managed": False, "template": True,
        }],
    })
    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(root=fw, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    hello_file = target / "HELLO.md"
    assert hello_file.exists()
    content = hello_file.read_text(encoding="utf-8")
    # Should be rendered, not raw template
    assert "test-proj" in content
    assert "{{PROJECT_NAME}}" not in content
    # Should NOT have managed header (managed=False)
    assert "Managed by ai-badger" not in content


def test_scaffolder_also_target_writes_second_copy(tmp_path, root, load_script):
    """When alsoTarget is set, the scaffolder should write the same content to
    both the primary target and the also-target."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    fw = _make_test_framework(tmp_path, root, scaffolding_json={
        "agent": "test-agent",
        "files": [{
            "source": "templates/hello.md", "target": "HELLO.md",
            "managed": True, "alsoTarget": ".hello.md",
        }],
    })
    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(root=fw, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    # Primary target
    assert target / "HELLO.md"
    assert "Hello from test-agent" in (target / "HELLO.md").read_text(encoding="utf-8")
    # Also-target
    assert (target / ".hello.md").exists()
    assert "Hello from test-agent" in (target / ".hello.md").read_text(encoding="utf-8")


def test_scaffolder_aib_copy_writes_source_of_truth(tmp_path, root, load_script):
    """When aibCopy is set, the scaffolder should write a source-of-truth copy
    under .ai-badger/."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    fw = _make_test_framework(tmp_path, root, scaffolding_json={
        "agent": "test-agent",
        "files": [{
            "source": "templates/hello.tmpl", "target": "HELLO.md",
            "managed": True, "template": True, "aibCopy": "HELLO.md",
        }],
    })
    target = tmp_path / "proj"
    target.mkdir()

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(root=fw, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    # Source of truth under .ai-badger/
    aib_copy = target / ".ai-badger" / "HELLO.md"
    assert aib_copy.exists()
    content = aib_copy.read_text(encoding="utf-8")
    # Should be rendered template (not raw)
    assert "test-proj" in content


def test_scaffolder_seed_once_preserves_existing_file(tmp_path, root, load_script):
    """When seedOnce=True and target already exists, the scaffolder should
    preserve the existing file."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    fw = _make_test_framework(tmp_path, root, scaffolding_json={
        "agent": "test-agent",
        "files": [{
            "source": "templates/hello.md", "target": "HELLO.md",
            "managed": True, "seedOnce": True,
        }],
    })
    target = tmp_path / "proj"
    target.mkdir()
    # Pre-existing file
    (target / "HELLO.md").write_text("my custom content\n", encoding="utf-8")

    config = _minimal_config(agents=["test-agent"])
    scaf = scaffold.Scaffolder(root=fw, target=target, config=config,
                                skills=[], install=False)
    result = scaf.run(generated_at=None)

    # Should preserve existing content
    assert (target / "HELLO.md").read_text(encoding="utf-8") == "my custom content\n"
    assert any("preserved seed-once" in n for n in result["notes"])
