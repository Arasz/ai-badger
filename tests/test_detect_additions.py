"""Tests for skills/feed-badger/scripts/detect_additions.py: diffs a scaffolded target's
.ai-badger/ tree against its manifest.json to find local "feed" candidates (new/changed).
"""
from __future__ import annotations

import json


def _write_manifest(aib, entries, framework_version="0.1.0"):
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "manifest.json").write_text(json.dumps({
        "$schema": "../schemas/manifest.schema.json",
        "frameworkVersion": framework_version,
        "generatedAt": "2026-07-19T00:00:00Z",
        "agents": ["claude"],
        "skillScope": "default",
        "entries": entries,
    }), encoding="utf-8")


def _run(detect_additions, target, capsys):
    rc = detect_additions.main(["--target", str(target)])
    out = json.loads(capsys.readouterr().out)
    return rc, out


def test_missing_manifest_reports_error_and_nonzero_exit(tmp_path, load_script, capsys):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    target.mkdir()

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 1
    assert "error" in out


def test_new_candidate_when_managed_file_absent_from_manifest(tmp_path, load_script, capsys):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    _write_manifest(aib, entries=[])
    instr = aib / "instructions" / "bar.md"
    instr.parent.mkdir(parents=True)
    instr.write_text("# bar\n", encoding="utf-8")

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 1
    candidate = out["candidates"][0]
    assert candidate["status"] == "new"
    assert candidate["feature"] == "instructions"
    assert candidate["path"] == ".ai-badger/instructions/bar.md"
    assert candidate["name"] == "bar"
    assert "suggestedGeneralization" in candidate


def test_changed_candidate_when_on_disk_hash_differs_from_manifest(
    tmp_path, load_script, capsys
):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    bl = load_script("scripts/badger_lib.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    persona = aib / "agents" / "foo.md"
    persona.parent.mkdir(parents=True)
    persona.write_text("original content\n", encoding="utf-8")
    original_hash = bl.sha256_file(persona)
    _write_manifest(aib, entries=[{
        "feature": "personas", "stack": "dotnet", "name": "foo",
        "source": "features/dotnet/personas/foo.md",
        "target": ".ai-badger/agents/foo.md",
        "frameworkVersion": "0.1.0", "hash": original_hash,
    }])
    persona.write_text("locally edited content\n", encoding="utf-8")

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 1
    candidate = out["candidates"][0]
    assert candidate["status"] == "changed"
    assert candidate["feature"] == "personas"
    assert candidate["path"] == ".ai-badger/agents/foo.md"
    assert candidate["name"] == "foo"
    assert candidate["originStack"] == "dotnet"
    assert candidate["originSource"] == "features/dotnet/personas/foo.md"


def test_no_candidate_when_managed_file_matches_manifest_hash(tmp_path, load_script, capsys):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    bl = load_script("scripts/badger_lib.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    persona = aib / "agents" / "foo.md"
    persona.parent.mkdir(parents=True)
    persona.write_text("original content\n", encoding="utf-8")
    _write_manifest(aib, entries=[{
        "feature": "personas", "stack": "dotnet", "name": "foo",
        "source": "features/dotnet/personas/foo.md",
        "target": ".ai-badger/agents/foo.md",
        "frameworkVersion": "0.1.0", "hash": bl.sha256_file(persona),
    }])

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 0
    assert out["candidates"] == []


def test_plugins_directory_scanned_for_new_candidates(tmp_path, load_script, capsys):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    _write_manifest(aib, entries=[])
    plugins_json = aib / "plugins" / "dotnet" / "plugins.json"
    plugins_json.parent.mkdir(parents=True)
    plugins_json.write_text(json.dumps({"plugins": [{"name": "dotnet-tool"}]}), encoding="utf-8")

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 1
    candidate = out["candidates"][0]
    assert candidate["status"] == "new"
    assert candidate["feature"] == "plugins"
    assert candidate["path"] == ".ai-badger/plugins/dotnet/plugins.json"


def test_directory_level_skill_entry_reported_changed_once_when_drifted(
    tmp_path, load_script, capsys
):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    bl = load_script("scripts/badger_lib.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    skill_dir = aib / "skills" / "task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# task\n", encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    scaffolded_hash = bl.sha256_file(skill_dir)
    _write_manifest(aib, entries=[{
        "feature": "skills", "stack": "common", "name": "task",
        "source": "features/common/skills/task",
        "target": ".ai-badger/skills/task",
        "frameworkVersion": "0.1.0", "hash": scaffolded_hash,
    }])
    # local drift: edit a file inside the scaffolded skill dir
    (skill_dir / "SKILL.md").write_text("# task (locally tweaked)\n", encoding="utf-8")

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 1
    candidate = out["candidates"][0]
    assert candidate["status"] == "changed"
    assert candidate["feature"] == "skills"
    assert candidate["path"] == ".ai-badger/skills/task"
    assert candidate["name"] == "task"


def test_directory_level_skill_entry_unchanged_produces_zero_candidates(
    tmp_path, load_script, capsys
):
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    bl = load_script("scripts/badger_lib.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    skill_dir = aib / "skills" / "task"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# task\n", encoding="utf-8")
    scaffolded_hash = bl.sha256_file(skill_dir)
    _write_manifest(aib, entries=[{
        "feature": "skills", "stack": "common", "name": "task",
        "source": "features/common/skills/task",
        "target": ".ai-badger/skills/task",
        "frameworkVersion": "0.1.0", "hash": scaffolded_hash,
    }])

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 0
    assert out["candidates"] == []


def _minimal_config():
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "feed-probe", "summary": "s", "domain": "d"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def test_pristine_scaffold_produces_zero_candidates(tmp_path, load_script, root, capsys):
    """Strongest end-to-end check: a target scaffolded by the real scaffold.py, diffed
    immediately by detect_additions, must show nothing new/changed."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    detect_additions = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")

    target = tmp_path / "proj"
    target.mkdir()
    scaf = scaffold.Scaffolder(
        root=root, target=target, config=_minimal_config(),
        skills=["task"], install=False,
    )
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    rc, out = _run(detect_additions, target, capsys)

    assert rc == 0
    assert out["candidateCount"] == 0
    assert out["candidates"] == []
