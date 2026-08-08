"""Tests for tooling/validate.py: --kind/--schema single-file validation and --all."""
from __future__ import annotations

import json
import shutil


def _copy_real_schemas(tmp_path, root):
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    _write_hooks_manifest(tmp_path)
    return tmp_path


def _write_hooks_manifest(tmp_path):
    """A complete manifest: since 0.88.4 a tree with no hooks-manifest.json fails --all."""
    d = tmp_path / "features" / "common" / "hooks"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hooks-manifest.json").write_text(json.dumps({"hooks": [
        {"name": "demo-hook", "agents": {
            agent: {"type": "hooks-json", "entry": "hooks.json", "event": "SessionStart",
                    "script": "demo_hook.py"}
            for agent in ("claude", "hermes", "copilot")}},
    ]}), encoding="utf-8")
    return d


def test_kind_config_valid_instance_returns_zero(tmp_path, root, load_script, capsys):
    """Against the real root: since 0.92.0 --kind config also checks that every stack and
    agent named is one the catalog ships, which a stub tree of copied schemas cannot answer."""
    validate = load_script("tooling/validate.py")
    instance = tmp_path / "config.json"
    instance.write_text(json.dumps({
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }), encoding="utf-8")

    rc = validate.main(["--kind", "config", "--root", str(root), str(instance)])

    assert rc == 0
    assert "ok" in capsys.readouterr().out


def test_kind_config_invalid_instance_returns_one(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    instance = tmp_path / "config.json"
    instance.write_text(json.dumps({"not": "a valid config"}), encoding="utf-8")

    rc = validate.main(["--kind", "config", "--root", str(fake_root), str(instance)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "INVALID" in out


def test_explicit_schema_path_is_used_over_kind(tmp_path, load_script, capsys):
    validate = load_script("tooling/validate.py")
    schema_path = tmp_path / "s.schema.json"
    schema_path.write_text(json.dumps({"type": "object", "required": ["x"]}), encoding="utf-8")
    instance = tmp_path / "i.json"
    instance.write_text(json.dumps({"x": 1}), encoding="utf-8")

    rc = validate.main(["--schema", str(schema_path), str(instance)])

    assert rc == 0
    assert "ok" in capsys.readouterr().out


def test_missing_instance_and_missing_all_flag_is_a_usage_error(load_script):
    validate = load_script("tooling/validate.py")

    import pytest
    with pytest.raises(SystemExit) as exc_info:
        validate.main([])

    assert exc_info.value.code == 2


def test_instance_without_schema_or_kind_is_a_usage_error(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    instance = tmp_path / "i.json"
    instance.write_text("{}", encoding="utf-8")

    import pytest
    with pytest.raises(SystemExit) as exc_info:
        validate.main([str(instance)])

    assert exc_info.value.code == 2


def test_all_flag_validates_the_real_framework_tree_and_reports_ok(root, load_script, capsys):
    validate = load_script("tooling/validate.py")

    rc = validate.main(["--all", "--root", str(root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "schemas self-check" in out


def test_all_flag_reports_invalid_when_a_skills_source_fails_its_schema(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    skills_dir = fake_root / "features" / "dotnet" / "skills"
    skills_dir.mkdir(parents=True)
    ss = fake_root / "features" / "dotnet" / "skills-source.json"
    ss.write_text(json.dumps({"not": "matching the schema"}), encoding="utf-8")

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "INVALID" in out


def test_all_flag_skips_index_json_when_absent(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "index.json" not in out


def test_all_validates_stack_mcp_and_stack_json(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    (fake_root / "features" / "dotnet").mkdir(parents=True)
    (fake_root / "features" / "dotnet" / "stack-mcp.json").write_text(
        json.dumps({"servers": "not a list"}), encoding="utf-8")

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "stack-mcp.json" in out


def test_all_validates_the_agent_capability_matrix(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    (fake_root / "features" / "common").mkdir(parents=True, exist_ok=True)
    (fake_root / "features" / "common" / "support.json").write_text(
        json.dumps({"description": "d", "agents": {"claude": {"name": "c"}}}), encoding="utf-8")

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "support.json" in out


def test_all_validates_stack_descriptors(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    (fake_root / "features" / "python").mkdir(parents=True)
    (fake_root / "features" / "python" / "stack.json").write_text(
        json.dumps({"nope": True}), encoding="utf-8")

    rc = validate.main(["--all", "--root", str(fake_root)])

    assert rc == 1
    assert "stack.json" in capsys.readouterr().out


def test_all_reports_hook_coverage_and_schema_coverage_even_when_there_is_nothing_to_say(
        root, load_script, capsys):
    """Silence read as "clean" and as "the glob matched nothing" alike, so both now print a
    verdict every run (the review's A9)."""
    validate = load_script("tooling/validate.py")

    rc = validate.main(["--all", "--root", str(root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ok       hooks-manifest agent coverage" in out
    assert "ok       schema coverage" in out


def test_a_tree_with_no_hooks_manifest_is_a_violation_not_a_pass(tmp_path, root, load_script,
                                                                 capsys):
    """An empty glob checked nothing. Reporting `[]` for it is the shape this whole gate exists
    to reject: one answer, and it looks like success."""
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    (fake_root / "features" / "common" / "hooks" / "hooks-manifest.json").unlink()

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "matched no file" in out


def test_every_schema_instance_glob_matches_at_least_one_file(root, load_script):
    """A glob matching nothing validates nothing: model.schema.json pointed at
    features/*/agent-instructions/model.json, which has never existed (the review's A10)."""
    validate = load_script("tooling/validate.py")

    inert = sorted(f"{name} -> {pattern}"
                   for name, patterns in validate.SCHEMA_INSTANCES.items()
                   for pattern in patterns
                   if not list(root.glob(pattern)))

    assert not inert, f"these globs validate nothing: {inert}"


def test_every_schema_has_a_coverage_decision(root, load_script):
    validate = load_script("tooling/validate.py")
    shipped = {p.name for p in (root / "schemas").glob("*.schema.json")}

    decided = set(validate.SCHEMA_INSTANCES) | set(validate.SCHEMAS_WITHOUT_LOCAL_INSTANCES)

    assert shipped == decided


def test_mcp_tools_exemption_reason_is_honest_not_that_the_format_is_yaml(root, load_script):
    """mcp-tools.json is JSON now (issue #145) — the exemption is "consumer-owned", like
    config/manifest/learned-skills, not "the instance is YAML"."""
    validate = load_script("tooling/validate.py")
    reason = validate.SCHEMAS_WITHOUT_LOCAL_INSTANCES["mcp-tools.schema.json"]
    assert "yaml" not in reason.lower()
    assert "instances live in consumer projects" in reason


def test_a_relative_link_in_an_inlined_catalog_body_is_a_violation(tmp_path, root, load_script):
    """0.112.0's defect: invariant bodies are inlined into agent files at the consumer's repo
    root, where a path relative to `features/<stack>/invariants/` points outside the repo."""
    validate = load_script("tooling/validate.py")
    d = tmp_path / "features" / "demo" / "invariants"
    d.mkdir(parents=True)
    (d / "rule.md").write_text(
        "# A rule\n\nSee [the other one](../../common/invariants/other.md).\n", encoding="utf-8")

    gaps = validate.inlined_relative_links(tmp_path)

    assert any("rule.md" in g and "../../common/invariants/other.md" in g for g in gaps), gaps


def test_an_absolute_url_in_an_inlined_catalog_body_is_allowed(tmp_path, load_script):
    """The escape hatch: a URL resolves from every depth, so it survives inlining."""
    validate = load_script("tooling/validate.py")
    d = tmp_path / "features" / "demo" / "invariants"
    d.mkdir(parents=True)
    (d / "rule.md").write_text(
        "# A rule\n\nSee [the docs](https://example.com/x.md).\n", encoding="utf-8")

    assert validate.inlined_relative_links(tmp_path) == []


def test_the_shipped_catalog_has_no_relative_links_in_inlined_bodies(root, load_script):
    validate = load_script("tooling/validate.py")

    assert validate.inlined_relative_links(root) == []


def test_a_relative_link_in_an_mcp_body_is_a_violation_too(tmp_path, load_script):
    """MCP server bodies fill the MCP_INSTRUCTIONS slot, so they are inlined like invariants."""
    validate = load_script("tooling/validate.py")
    d = tmp_path / "features" / "common" / "mcp" / "demo"
    d.mkdir(parents=True)
    (d / "server.md").write_text("## Demo\n\nSee [setup](../../../docs/setup.md).\n",
                                 encoding="utf-8")

    gaps = validate.inlined_relative_links(tmp_path)

    assert any("server.md" in g for g in gaps), gaps
