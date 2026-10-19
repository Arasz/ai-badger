"""Real shared child discovery and runtime consumers."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from conftest import _test_write
from test_shared_scopes import _collected_pair, _snapshot, _success


def test_v1_child_shares_immutable_resources_and_runs_its_own_tracker(tmp_path, root):
    """The parent union reaches a usable child without sharing identity or runtime writes."""
    source, child, sibling = _collected_pair(tmp_path, root)
    aib = child / ".ai-badger"
    instruction = aib / "instructions" / "csharp.instructions.md"
    assert instruction.is_symlink(), "identical immutable instructions must share parent files"
    assert instruction.resolve() == source / "instructions" / "csharp.instructions.md"
    assert not os.path.isabs(os.readlink(instruction))
    assert aib.is_dir() and not aib.is_symlink()
    assert not (aib / "instructions").is_symlink()
    assert not (aib / "skills" / "task").is_symlink()
    assert (child / ".claude" / "skills" / "task" / "SKILL.md").is_file()
    instructions_doc = (child / "CLAUDE.md").read_text()
    assert "csharp.instructions.md" in instructions_doc
    assert "python.instructions.md" in instructions_doc
    descriptor = json.loads((aib / "shared-scope.json").read_text())
    assert descriptor["mode"] == "inherit"
    assert descriptor["localStacks"] == ["python"]
    assert set(json.loads((aib / "config.json").read_text())["stacks"]) == {"python", "dotnet"}
    for private in ("config.json", "manifest.json", "project-id", "state.json",
                    "shared-scope.json", "agent-instructions/model.json",
                    "skills/task/SKILL.md", "skills/task/scripts/task_tracker.py"):
        assert (aib / private).is_file(), private
        assert not (aib / private).is_symlink(), private
    manifest = json.loads((aib / "manifest.json").read_text())
    links = [entry for entry in manifest["sharedScope"]["links"]
             if entry["path"] == ".ai-badger/instructions/csharp.instructions.md"]
    assert len(links) == 1
    assert links[0]["target"] == os.readlink(instruction)
    assert links[0]["source"] == "instructions/csharp.instructions.md", \
        "the ledger records a path relative to the parent, not this machine's"
    assert (source / links[0]["source"]).resolve() == instruction.resolve()
    parent_before, sibling_before = _snapshot(source), _snapshot(sibling)
    nested = child / "src" / "deep"
    nested.mkdir(parents=True)
    transcript = tmp_path / "transcript.jsonl"
    _test_write(transcript, "")
    environment = dict(os.environ)
    for variable in ("CLAUDE_PROJECT_DIR", "AI_BADGER_PROJECT_ID", "AI_BADGER_PROJECT_DIR"):
        environment.pop(variable, None)
    scripts = aib / "skills" / "task" / "scripts"

    started = subprocess.run([
        sys.executable, str(scripts / "task_tracker.py"), "start", "py-shared-runtime",
        "--title", "Shared child runtime", "--session-id", "shared-child-session",
        "--transcript-path", str(transcript), "--no-worktree"],
        cwd=nested, env=environment, capture_output=True, text=True, timeout=60)

    _success(started)
    assert json.loads(started.stdout)["taskId"] == "py-shared-runtime"
    assert (aib / "task-tracking" / "tracking.db").is_file()
    probe = subprocess.run([
        sys.executable, "-c",
        "import json,os,sys; sys.path.insert(0,sys.argv[1]); "
        "import tracker_lib,badger_store; "
        "print(json.dumps({'root':str(tracker_lib.PROJECT_ROOT),"
        "'id':badger_store.resolve_project_id(os.getcwd()),"
        "'sibling':badger_store.resolve_project_id(sys.argv[2])}))",
        str(scripts), str(sibling)], cwd=nested, env=environment,
        capture_output=True, text=True, timeout=30)
    _success(probe)
    assert json.loads(probe.stdout) == {
        "root": str(child), "id": "canonical-python", "sibling": "canonical-dotnet"}
    assert _snapshot(source) == parent_before
    assert _snapshot(sibling) == sibling_before


def test_ordinary_scaffold_and_refresh_refuse_shared_children(tmp_path, root):
    """The sync command is the only scaffold path allowed to rewrite linked children."""
    source, child, sibling = _collected_pair(tmp_path, root)
    aib = child / ".ai-badger"
    child_before = _snapshot(aib)
    parent_before, sibling_before = _snapshot(source), _snapshot(sibling)
    child_id = (aib / "project-id").read_bytes()

    scaffold = subprocess.run([
        sys.executable,
        str(root / "features/common/skills/welcome-ai-badger/scripts/scaffold.py"),
        "--config", str(aib / "config.json"), "--target", str(child),
        "--root", str(root), "--no-install"], capture_output=True, text=True,
        timeout=60)

    assert scaffold.returncode == 2, scaffold.stdout + scaffold.stderr
    assert "shared_scope.py collect" in scaffold.stderr, \
        "an enrolled child carries the union; collect is what restores it"
    assert _snapshot(aib) == child_before
    assert (aib / "project-id").read_bytes() == child_id
    assert _snapshot(source) == parent_before
    assert _snapshot(sibling) == sibling_before

    refresh = subprocess.run([
        sys.executable,
        str(root / "features/common/skills/den-refresh/scripts/refresh.py"),
        "--root", str(root), "--target", str(child)], capture_output=True,
        text=True, timeout=60)

    assert refresh.returncode == 2, refresh.stdout + refresh.stderr
    assert "shared_scope.py collect" in refresh.stdout
    assert _snapshot(aib) == child_before
    assert (aib / "project-id").read_bytes() == child_id
    assert _snapshot(source) == parent_before
    assert _snapshot(sibling) == sibling_before


def test_sync_preflights_every_owned_link_before_detaching(tmp_path, root):
    """A late foreign-link mismatch leaves earlier owned links untouched."""
    source, child, sibling = _collected_pair(tmp_path, root)
    aib = child / ".ai-badger"
    first = aib / "instructions" / "csharp.instructions.md"
    foreign = aib / "instructions" / "python.instructions.md"
    assert first.is_symlink() and foreign.is_symlink()
    foreign.unlink()
    foreign.symlink_to(sibling / ".ai-badger" / "instructions" / "python.instructions.md")
    before = _snapshot(aib)
    parent_before = _snapshot(source)

    result = subprocess.run([
        sys.executable,
        str(root / "features/common/skills/welcome-ai-badger/scripts/shared_scope.py"),
        "sync", "--target", str(child), "--source", str(source), "--root", str(root)],
        capture_output=True, text=True, timeout=60)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "link was replaced" in result.stderr
    assert _snapshot(aib) == before
    assert _snapshot(source) == parent_before
