"""Tests for tooling/index_build.py: build_index() scanning + --check clean/stale CLI behavior."""
from __future__ import annotations

import json
import shutil

import jsonschema
import pytest


def _make_fake_root(tmp_path, root):
    """A synthetic framework tree (real schemas/ copied in, hand-built features/)."""
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    features = tmp_path / "features"

    dotnet_skills = features / "dotnet" / "skills" / "greet"
    dotnet_skills.mkdir(parents=True)
    (dotnet_skills / "SKILL.md").write_text("# greet\n", encoding="utf-8")

    dotnet_personas = features / "dotnet" / "personas"
    dotnet_personas.mkdir(parents=True)
    (dotnet_personas / "reviewer.md").write_text("# reviewer\n", encoding="utf-8")
    (dotnet_personas / "README.md").write_text("# readme, must be excluded\n", encoding="utf-8")

    dotnet_invariants = features / "dotnet" / "invariants"
    dotnet_invariants.mkdir(parents=True)
    (dotnet_invariants / "no-secrets.md").write_text("# no secrets\n", encoding="utf-8")

    dotnet_instructions = features / "dotnet" / "instructions"
    dotnet_instructions.mkdir(parents=True)
    (dotnet_instructions / "style.md").write_text("# style\n", encoding="utf-8")

    dotnet_hooks = features / "dotnet" / "hooks"
    dotnet_hooks.mkdir(parents=True)
    (dotnet_hooks / "hooks-manifest.json").write_text(json.dumps({
        "hooks": [{"name": "test-hook", "agents": {"hermes": {"type": "plugin", "entry": "test.py"}}}]
    }), encoding="utf-8")

    dotnet_templates = features / "dotnet" / "templates"
    dotnet_templates.mkdir(parents=True)
    (dotnet_templates / "Program.cs").write_text("// template\n", encoding="utf-8")
    (dotnet_templates / "README.md").write_text("# readme, must be excluded\n", encoding="utf-8")

    (features / "dotnet" / "stack.json").write_text(json.dumps({
        "name": "dotnet",
        "description": ".NET stack",
        "detectionSignals": ["*.csproj"],
    }), encoding="utf-8")

    # a stack with only a stack.json (no feature dirs) must still surface via meta
    metaonly = features / "metaonly"
    metaonly.mkdir(parents=True)
    (metaonly / "stack.json").write_text(json.dumps({
        "name": "metaonly",
        "description": "meta-only stack",
    }), encoding="utf-8")

    # common skills under features/common/skills/ (no longer at repo root)
    common_skill = tmp_path / "features" / "common" / "skills" / "wave"
    common_skill.mkdir(parents=True)
    (common_skill / "SKILL.md").write_text("# wave\n", encoding="utf-8")

    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")

    return tmp_path


def test_build_index_assembles_expected_stacks_and_items(tmp_path, root, load_script):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)

    index = index_build.build_index(fake_root)

    assert index["frameworkVersion"] == "1.2.3"
    assert set(index["stacks"]) == {"dotnet", "metaonly", "common"}

    dotnet = index["stacks"]["dotnet"]
    assert dotnet["skills"] == [{"name": "greet", "path": "features/dotnet/skills/greet"}]
    assert dotnet["personas"] == [{"name": "reviewer",
                                    "path": "features/dotnet/personas/reviewer.md"}]
    assert dotnet["invariants"] == [{"name": "no-secrets",
                                      "path": "features/dotnet/invariants/no-secrets.md"}]
    assert dotnet["instructions"] == [{"name": "style",
                                        "path": "features/dotnet/instructions/style.md"}]
    assert dotnet["hooks"] == [{"name": "hooks-manifest", "path": "features/dotnet/hooks/hooks-manifest.json"}]
    assert dotnet["templates"] == [{"name": "Program.cs", "path": "features/dotnet/templates/Program.cs"}]
    assert dotnet["meta"]["description"] == ".NET stack"
    assert "name" not in dotnet["meta"]  # stripped by build_index

    assert index["stacks"]["metaonly"] == {"meta": {"description": "meta-only stack"}}
    assert index["stacks"]["common"]["skills"] == [{"name": "wave", "path": "features/common/skills/wave"}]


def test_build_index_defaults_framework_version_when_version_file_missing(tmp_path, root, load_script):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)
    (fake_root / "VERSION").unlink()

    index = index_build.build_index(fake_root)

    assert index["frameworkVersion"] == "0.0.0"


def test_build_index_readme_excluded_from_md_and_template_items(tmp_path, root, load_script):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)

    index = index_build.build_index(fake_root)

    names = [item["name"] for item in index["stacks"]["dotnet"]["personas"]]
    assert "README" not in names
    template_paths = [item["path"] for item in index["stacks"]["dotnet"]["templates"]]
    assert not any(p.endswith("README.md") for p in template_paths)


class TestLegacyExtensionDirs:
    """`<skill>-extensions/<ext>/` was removed; it must fail loudly, never silently do nothing."""

    def _legacy(self, fake_root, base="greet", ext="loud"):
        d = fake_root / "features" / "dotnet" / "skills" / f"{base}-extensions" / ext
        d.mkdir(parents=True)
        (d / "marker.txt").write_text("ext\n", encoding="utf-8")
        return d

    def test_the_generated_index_carries_no_extensions_field(self, tmp_path, root, load_script):
        index_build = load_script("tooling/index_build.py")
        fake_root = _make_fake_root(tmp_path, root)
        self._legacy(fake_root)

        index = index_build.build_index(fake_root)

        assert all("extensions" not in item
                   for stack in index["stacks"].values()
                   for items in stack.values() if isinstance(items, list)
                   for item in items)

    def test_a_legacy_dir_is_reported_with_its_replacement_named(self, tmp_path, root,
                                                                 load_script):
        index_build = load_script("tooling/index_build.py")
        fake_root = _make_fake_root(tmp_path, root)
        self._legacy(fake_root)

        found = index_build.legacy_extension_dirs(fake_root)

        assert found == ["features/dotnet/skills/greet-extensions"]

    def test_an_orphan_legacy_dir_is_reported_too(self, tmp_path, root, load_script):
        """Naming no real skill made it doubly invisible before — it is still a mistake."""
        index_build = load_script("tooling/index_build.py")
        fake_root = _make_fake_root(tmp_path, root)
        self._legacy(fake_root, base="ghost", ext="variant")

        assert index_build.legacy_extension_dirs(fake_root) == [
            "features/dotnet/skills/ghost-extensions"
        ]

    def test_a_clean_catalog_reports_nothing(self, tmp_path, root, load_script):
        index_build = load_script("tooling/index_build.py")

        assert index_build.legacy_extension_dirs(_make_fake_root(tmp_path, root)) == []

    def test_main_refuses_to_build_and_points_at_the_supported_layout(self, tmp_path, root,
                                                                     load_script, capsys):
        index_build = load_script("tooling/index_build.py")
        fake_root = _make_fake_root(tmp_path, root)
        self._legacy(fake_root)

        rc = index_build.main(["--root", str(fake_root)])

        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 1
        assert "greet-extensions" in out
        assert "greet/extensions/" in out, "must name the supported layout, not just refuse"

    def test_the_real_catalog_uses_no_legacy_dirs(self, root, load_script):
        index_build = load_script("tooling/index_build.py")

        assert index_build.legacy_extension_dirs(root) == []


def test_the_schema_no_longer_permits_the_removed_extensions_field(root):
    """A stale index.json must be rejected, not quietly accepted as still-supported."""
    schema = json.loads((root / "schemas" / "index.schema.json").read_text())
    stale = {
        "frameworkVersion": "1.2.3",
        "stacks": {"dotnet": {"skills": [{"name": "greet",
                                          "path": "features/dotnet/skills/greet",
                                          "extensions": ["loud"]}]}},
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(stale, schema)


def test_main_check_reports_stale_when_index_json_missing(tmp_path, root, load_script, capsys):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)

    rc = index_build.main(["--root", str(fake_root), "--check"])

    assert rc == 1
    assert "missing or stale" in capsys.readouterr().out


def test_main_writes_index_json_then_check_reports_clean(tmp_path, root, load_script, capsys):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)

    rc_build = index_build.main(["--root", str(fake_root)])
    assert rc_build == 0
    assert (fake_root / "index.json").exists()
    capsys.readouterr()

    rc_check = index_build.main(["--root", str(fake_root), "--check"])

    assert rc_check == 0
    assert "up to date" in capsys.readouterr().out


def test_main_check_reports_stale_after_tree_changes(tmp_path, root, load_script):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)
    index_build.main(["--root", str(fake_root)])

    new_skill = fake_root / "features" / "dotnet" / "skills" / "new-one"
    new_skill.mkdir(parents=True)
    (new_skill / "SKILL.md").write_text("# new\n", encoding="utf-8")

    rc = index_build.main(["--root", str(fake_root), "--check"])

    assert rc == 1


def test_main_writes_valid_pretty_printed_json_with_trailing_newline(tmp_path, root, load_script):
    index_build = load_script("tooling/index_build.py")
    fake_root = _make_fake_root(tmp_path, root)

    index_build.main(["--root", str(fake_root)])

    text = (fake_root / "index.json").read_text(encoding="utf-8")
    assert text.endswith("\n")
    data = json.loads(text)
    assert data["stacks"]["dotnet"]["skills"][0]["name"] == "greet"
