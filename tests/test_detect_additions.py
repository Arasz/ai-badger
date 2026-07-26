"""Tests for features/common/skills/feed-badger/scripts/detect_additions.py.

Issue #65: extension content edits must be visible to detect_additions.
"""
import json


def test_extension_content_edit_detected_as_candidate(tmp_path, load_script, root, capsys):
    """Editing an extension file should produce a feed-badger candidate (#65)."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    detect = load_script("features/common/skills/feed-badger/scripts/detect_additions.py")

    target = tmp_path / "proj"
    target.mkdir()

    # Scaffold with github extension
    config = {
        "agents": ["claude"],
        "stacks": ["python"],
        "sourceControl": {"platform": "github", "repoUrl": "https://example.com/repo"},
    }
    scaf = scaffold.Scaffolder(
        root=root, target=target, config=config,
        skills=["task"], install=False,
    )
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
