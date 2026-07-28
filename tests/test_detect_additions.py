"""Tests for features/common/skills/feed-badger/scripts/detect_additions.py.

Issue #65: extension content edits must be visible to detect_additions.
"""
import json


def test_extension_content_edit_detected_as_candidate(load_script, root, capsys, make_scaffolder):
    """Editing an extension file should produce a feed-badger candidate (#65)."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")

    target = make_scaffolder.target

    # Scaffold with github extension
    config = {
        "agents": ["claude"],
        "stacks": ["python"],
        "sourceControl": {"platform": "github", "repoUrl": "https://example.com/repo"},
    }
    scaf = make_scaffolder(config=config, skills=["task"])
    scaf.run(generated_at="2026-07-26T00:00:00Z")

    # Verify extension was scaffolded
    ext_file = target / ".ai-badger" / "skills" / "task" / "extensions" / "github" / "extension.md"
    assert ext_file.exists(), "extension.md should be scaffolded"

    # Edit the extension file (user correction)
    ext_file.write_text("# Custom extension edit by user\n")

    # Run detect_additions
    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    # The edit should produce at least one candidate
    assert out["candidateCount"] >= 1, (
        f"Expected at least 1 candidate for extension edit, got {out['candidateCount']}. "
        f"Candidates: {out['candidates']}"
    )
    # Verify the extension file appears in candidates
    paths = [c["path"] for c in out["candidates"]]
    assert any("extension.md" in p for p in paths), (
        f"extension.md edit not found in candidates. Paths: {paths}"
    )


def _write_minimal_manifest(target):
    """Write the smallest .ai-badger/manifest.json that satisfies main()'s gate."""
    aib = target / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "manifest.json").write_text(json.dumps({
        "frameworkVersion": "0.18.0", "entries": [],
    }))
    return aib


def _write_learned_skill(aib, category="apple", name="apple-notes"):
    """Seed a learned-skill directory with a SKILL.md and nested files (research C9)."""
    skill_dir = aib / "skills" / "learned" / category / name
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# apple notes\n")
    (skill_dir / "scripts" / "helper.py").write_text("print('hi')\n")
    (skill_dir / "references" / "api.md").write_text("# api\n")
    return skill_dir


def test_learned_skill_dir_yields_single_candidate(tmp_path, load_script, root, capsys):
    """A learned-skill dir with 3 files surfaces as exactly 1 candidate (C9)."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = _write_minimal_manifest(target)
    _write_learned_skill(aib)

    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    assert out["candidateCount"] == 1, out["candidates"]


def test_learned_skill_candidate_is_named_for_the_skill(tmp_path, load_script, root, capsys):
    """The candidate is named for the skill directory, not for SKILL.md's stem."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = _write_minimal_manifest(target)
    _write_learned_skill(aib)

    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    assert out["candidates"][0]["name"] == "apple-notes"


def test_learned_skill_candidate_carries_learned_provenance(tmp_path, load_script, root, capsys):
    """When learned.json has a matching record, its sourcePath is attached alongside origin."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = _write_minimal_manifest(target)
    _write_learned_skill(aib)

    learned_data_dir = aib / "skills-data" / "hermes"
    learned_data_dir.mkdir(parents=True)
    (learned_data_dir / "learned.json").write_text(json.dumps({
        "version": 1,
        "skills": [{
            "name": "apple-notes", "category": "apple",
            "target": ".ai-badger/skills/learned/apple/apple-notes",
            "sourcePath": "apple/apple-notes",
            "sourceHash": "deadbeef",
            "syncedAt": "2026-07-26T20:00:00Z",
            "status": "synced",
        }],
    }))

    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    candidate = out["candidates"][0]
    assert candidate["origin"] == "hermes-learned"
    assert candidate["sourcePath"] == "apple/apple-notes"


def test_malformed_learned_json_still_yields_the_candidate(tmp_path, load_script, root, capsys):
    """A broken learned.json costs provenance, not the whole detection run."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = _write_minimal_manifest(target)
    _write_learned_skill(aib)

    learned_data_dir = aib / "skills-data" / "hermes"
    learned_data_dir.mkdir(parents=True)
    (learned_data_dir / "learned.json").write_text("{ not json at all")

    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    assert out["candidateCount"] == 1
    candidate = out["candidates"][0]
    assert candidate["name"] == "apple-notes"
    assert candidate["origin"] == "hermes-learned"
    assert "sourcePath" not in candidate


def test_non_learned_new_files_still_yield_per_file_candidates(tmp_path, load_script, root, capsys):
    """Non-learned unmanaged files keep the pre-existing one-candidate-per-file behavior."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = _write_minimal_manifest(target)
    instructions_dir = aib / "instructions"
    instructions_dir.mkdir()
    (instructions_dir / "extra.instructions.md").write_text("# extra\n")

    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    assert out["candidateCount"] == 1
    candidate = out["candidates"][0]
    assert candidate["name"] == "extra.instructions"
    assert candidate["path"] == ".ai-badger/instructions/extra.instructions.md"
    assert "origin" not in candidate


def test_source_hashed_entries_are_never_project_change_candidates(
        tmp_path, load_script, root, capsys):
    """An adjustment's hash describes the framework script, so no project file can match it."""
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")
    target = tmp_path / "proj"
    aib = target / ".ai-badger"
    linked = aib / "skills" / "task"
    linked.mkdir(parents=True)
    (linked / "SKILL.md").write_text("# task\n", encoding="utf-8")
    mirror = target / ".github" / "skills"
    mirror.mkdir(parents=True)
    (mirror / "task").symlink_to(linked)
    (aib / "manifest.json").write_text(json.dumps({
        "frameworkVersion": "0.33.0",
        "entries": [{
            "feature": "adjustments", "stack": "copilot", "name": "adjustments/task",
            "source": "features/copilot/adjustments/adjust_skills.py",
            "target": ".github/skills/task",
            "frameworkVersion": "0.33.0", "hash": "0" * 64,
        }],
    }), encoding="utf-8")

    rc = detect.main(["--target", str(target), "--root", str(root)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    assert [c for c in out["candidates"] if c["feature"] == "adjustments"] == []
