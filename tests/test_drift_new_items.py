"""Tier 2 drift: catalog items and detectable stacks the project has not scaffolded yet."""
from __future__ import annotations


# --- new items detection (Tier 2, ADR-0001 decision 5) ---

def test_detect_new_items_finds_catalog_items_not_in_manifest(tmp_path, load_script):
    """An item in the framework catalog but not in the manifest should be reported as new."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")

    # Framework has two invariants
    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    (fw / "features" / "common" / "invariants" / "existing.md").write_text("existing\n")
    (fw / "features" / "common" / "invariants" / "new-item.md").write_text("new\n")
    (fw / "VERSION").write_text("0.3.0\n")
    # Create index.json
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "common": {
                "invariants": [
                    {"name": "existing", "path": "features/common/invariants/existing.md"},
                    {"name": "new-item", "path": "features/common/invariants/new-item.md"},
                ]
            }
        }
    }
    bl.dump_json(fw / "index.json", idx)

    # Manifest only has the existing one
    manifest = {
        "frameworkVersion": "0.2.0",
        "agents": ["claude"],
        "entries": [
            {"feature": "invariants", "stack": "common", "name": "existing",
             "source": "features/common/invariants/existing.md",
             "target": ".ai-badger/invariants/existing.md",
             "frameworkVersion": "0.2.0",
             "hash": bl.sha256_file(fw / "features" / "common" / "invariants" / "existing.md")},
        ],
    }

    new_items = drift.detect_new_items(fw, manifest, stacks=["common"])

    assert len(new_items) == 1
    assert new_items[0]["name"] == "new-item"
    assert new_items[0]["feature"] == "invariants"


def test_detect_new_items_empty_when_manifest_is_current(tmp_path, load_script):
    """When manifest covers everything, no new items should be reported."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")

    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    (fw / "features" / "common" / "invariants" / "x.md").write_text("x\n")
    (fw / "VERSION").write_text("0.3.0\n")
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {"common": {"invariants": [
            {"name": "x", "path": "features/common/invariants/x.md"}
        ]}}
    }
    bl.dump_json(fw / "index.json", idx)

    manifest = {
        "frameworkVersion": "0.3.0", "agents": ["claude"],
        "entries": [
            {"feature": "invariants", "stack": "common", "name": "x",
             "source": "features/common/invariants/x.md",
             "target": ".ai-badger/invariants/x.md",
             "frameworkVersion": "0.3.0",
             "hash": bl.sha256_file(fw / "features" / "common" / "invariants" / "x.md")},
        ],
    }

    new_items = drift.detect_new_items(fw, manifest, stacks=["common"])
    assert new_items == []


def test_detect_new_items_only_checks_configured_stacks(tmp_path, load_script):
    """New items in stacks not in the project's config should be ignored."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")

    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    (fw / "features" / "dotnet" / "invariants").mkdir(parents=True)
    (fw / "features" / "dotnet" / "invariants" / "dotnet-only.md").write_text("dotnet\n")
    (fw / "VERSION").write_text("0.3.0\n")
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "common": {"invariants": []},
            "dotnet": {"invariants": [
                {"name": "dotnet-only", "path": "features/dotnet/invariants/dotnet-only.md"}
            ]},
        }
    }
    bl.dump_json(fw / "index.json", idx)

    manifest = {"frameworkVersion": "0.3.0", "agents": ["claude"], "entries": []}

    # Project only uses "common" stack — dotnet items should be ignored
    new_items = drift.detect_new_items(fw, manifest, stacks=["common"])
    assert new_items == []

    # But if project uses dotnet, it should find it
    new_items = drift.detect_new_items(fw, manifest, stacks=["common", "dotnet"])
    assert len(new_items) == 1


def test_a_new_template_is_reported_as_a_new_item(tmp_path, load_script):
    """Templates are a catalog feature type, so an unscaffolded one counts as new."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")

    fw = tmp_path / "fw"
    (fw / "features" / "common" / "templates").mkdir(parents=True)
    (fw / "features" / "common" / "templates" / "new.md.tmpl").write_text("hi\n")
    (fw / "VERSION").write_text("0.3.0\n")
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {"common": {"templates": [
            {"name": "new.md.tmpl", "path": "features/common/templates/new.md.tmpl"}
        ]}}
    }
    bl.dump_json(fw / "index.json", idx)

    manifest = {"frameworkVersion": "0.3.0", "agents": ["claude"], "entries": []}

    new_items = drift.detect_new_items(fw, manifest, stacks=["common"])

    assert [(i["feature"], i["name"]) for i in new_items] == [("templates", "new.md.tmpl")]


def test_compare_includes_new_items(tmp_path, load_script):
    """compare() should include new items in its result when index and stacks are provided."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")
    bl = load_script("scripts/badger_lib.py")

    fw = tmp_path / "fw"
    (fw / "features" / "common" / "invariants").mkdir(parents=True)
    (fw / "features" / "common" / "invariants" / "new.md").write_text("new\n")
    (fw / "VERSION").write_text("0.3.0\n")
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {"common": {"invariants": [
            {"name": "new", "path": "features/common/invariants/new.md"}
        ]}}
    }
    bl.dump_json(fw / "index.json", idx)

    manifest = {"frameworkVersion": "0.3.0", "agents": ["claude"], "entries": []}

    result = drift.compare(fw, manifest, stacks=["common"])

    assert "new" in [i["name"] for i in result.get("newItems", [])]


# ── detect_new_stacks ────────────────────────────────────────────────────────

def test_detect_new_stacks_finds_stack_not_in_config(tmp_path, load_script):
    """A stack with detection signals present but missing from config should be reported."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    fw = tmp_path / "fw"
    # Index has python and hermes stacks
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "python": {
                "meta": {"detectionSignals": ["*.py", "pyproject.toml", "requirements.txt"]},
            },
            "hermes": {
                "meta": {"detectionSignals": [".hermes.md", "HERMES.md"]},
            },
        },
    }
    fw.mkdir(parents=True, exist_ok=True)
    bl = load_script("scripts/badger_lib.py")
    bl.dump_json(fw / "index.json", idx)

    # Target has hermes signals but config only knows about python
    target = tmp_path / "proj"
    target.mkdir(parents=True, exist_ok=True)
    (target / ".hermes.md").write_text("# Hermes\n")

    new_stacks = drift.detect_new_stacks(target, fw, config_stacks=["python"])

    assert new_stacks == ["hermes"]


def test_detect_new_stacks_empty_when_config_is_complete(tmp_path, load_script):
    """When all detectable stacks are already in config, return empty."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    fw = tmp_path / "fw"
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "python": {
                "meta": {"detectionSignals": ["*.py", "pyproject.toml"]},
            },
        },
    }
    fw.mkdir(parents=True, exist_ok=True)
    bl = load_script("scripts/badger_lib.py")
    bl.dump_json(fw / "index.json", idx)

    target = tmp_path / "proj"
    target.mkdir(parents=True, exist_ok=True)
    (target / "pyproject.toml").write_text("[project]\n")

    new_stacks = drift.detect_new_stacks(target, fw, config_stacks=["python"])

    assert new_stacks == []


def test_detect_new_stacks_ignores_stacks_not_in_index(tmp_path, load_script):
    """Stacks detected by dependency heuristics but not in the index are ignored."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    fw = tmp_path / "fw"
    # Index only knows about python
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "python": {
                "meta": {"detectionSignals": ["*.py", "pyproject.toml"]},
            },
        },
    }
    fw.mkdir(parents=True, exist_ok=True)
    bl = load_script("scripts/badger_lib.py")
    bl.dump_json(fw / "index.json", idx)

    # Target has hermes signals but hermes is not in the index
    target = tmp_path / "proj"
    target.mkdir(parents=True, exist_ok=True)
    (target / ".hermes.md").write_text("# Hermes\n")
    (target / "pyproject.toml").write_text("[project]\n")

    new_stacks = drift.detect_new_stacks(target, fw, config_stacks=[])

    # python is detectable and in index but not in config — should be reported
    # hermes is detectable but NOT in index — should be ignored
    assert new_stacks == ["python"]


def test_detect_new_stacks_includes_expanded_requires(tmp_path, load_script):
    """New stacks should include transitively required stacks."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    fw = tmp_path / "fw"
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "react": {
                "meta": {"detectionSignals": ["*.tsx"], "requires": ["ts"]},
            },
            "ts": {
                "meta": {"detectionSignals": ["tsconfig.json"]},
            },
        },
    }
    fw.mkdir(parents=True, exist_ok=True)
    bl = load_script("scripts/badger_lib.py")
    bl.dump_json(fw / "index.json", idx)

    # Target has tsx files → react detected → requires ts
    target = tmp_path / "proj"
    target.mkdir(parents=True, exist_ok=True)
    (target / "app.tsx").write_text("export default () => null\n")

    new_stacks = drift.detect_new_stacks(target, fw, config_stacks=[])

    assert "react" in new_stacks
    assert "ts" in new_stacks


def test_detect_new_stacks_respects_ignore_list(tmp_path, load_script):
    """Stacks in the ignore list should be excluded from newStacks."""
    drift = load_script("features/common/skills/welcome-ai-badger/scripts/drift.py")

    fw = tmp_path / "fw"
    idx = {
        "frameworkVersion": "0.3.0",
        "stacks": {
            "python": {
                "meta": {"detectionSignals": ["*.py", "pyproject.toml"]},
            },
            "hermes": {
                "meta": {"detectionSignals": [".hermes.md", "HERMES.md"]},
            },
        },
    }
    fw.mkdir(parents=True, exist_ok=True)
    bl = load_script("scripts/badger_lib.py")
    bl.dump_json(fw / "index.json", idx)

    target = tmp_path / "proj"
    target.mkdir(parents=True, exist_ok=True)
    (target / "main.py").write_text("print('hi')\n")
    (target / ".hermes.md").write_text("# Hermes\n")

    # python is in config, hermes is detectable but ignored
    new_stacks = drift.detect_new_stacks(
        target, fw, config_stacks=["python"], ignore=["hermes"]
    )
    assert new_stacks == []
