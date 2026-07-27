"""Tests for features/common/skills/welcome-ai-badger/scripts/scaffold.py: core run behavior.

What a first run creates, which stacks reach the target, and what --execute runs. The
other scaffold behaviors live in the sibling test_scaffold_*.py modules.
"""
from __future__ import annotations

from scaffold_helpers import _config


# ------------------------------------------------------------------------- new-file creation
def test_scaffold_creates_new_skill_dir_on_first_run(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()
    assert not (target / ".ai-badger").exists()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(),
                                skills=["task"], install=False)
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    assert (target / ".ai-badger" / "skills" / "task").is_dir()
    skill_entries = [e for e in result["manifest"]["entries"]
                     if e["feature"] == "skills" and e["name"] == "task"]
    assert len(skill_entries) == 1


# ------------------------------------------------------------------------------- no leakage
def test_scaffold_no_stack_leakage(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target, config=_config(stacks=["dotnet"]),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    aib = target / ".ai-badger"
    assert (aib / "instructions" / "csharp.instructions.md").exists()
    assert (aib / "agents" / "dotnet-engineer.md").exists()  # personas land under agents/

    all_instruction_names = {p.name for p in (aib / "instructions").glob("*")}
    assert "python.instructions.md" not in all_instruction_names
    assert "react.instructions.md" not in all_instruction_names

    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "frontend-engineer.md" not in all_persona_names


def test_scaffold_no_stack_leakage_react_excludes_dotnet(tmp_path, load_script, root):
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(root=root, target=target,
                                config=_config(stacks=["react", "ts", "node"]),
                                skills=[], install=False)
    scaf.run(generated_at="2026-07-19T00:00:00Z")

    aib = target / ".ai-badger"
    assert (aib / "agents" / "frontend-engineer.md").exists()
    all_persona_names = {p.name for p in (aib / "agents").glob("*")}
    assert "dotnet-engineer.md" not in all_persona_names


# ---------------------------------------------------------------------- --execute flag
def test_scaffold_execute_flag_runs_commands(tmp_path, load_script, root):
    """--execute flag should execute install commands and log results."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=True, execute=True,
    )

    # Mock subprocess.run to capture calls without actually running them
    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=0, stderr="")
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Every command is an argv list run without a shell: a skill name is data, not syntax.
    assert mock_run.called
    for call in mock_run.call_args_list:
        cmd = call[0][0] if call[0] else call[1].get("command", [])
        assert isinstance(cmd, list), f"not argv: {cmd!r}"
        assert not call[1].get("shell"), f"ran through a shell: {cmd!r}"


def test_scaffold_execute_flag_handles_failure(tmp_path, load_script, root):
    """--execute flag should log failures without crashing."""
    import unittest.mock
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    target = tmp_path / "proj"
    target.mkdir()

    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(agents=["claude"]),
        skills=["task"], install=True, execute=True,
    )

    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = unittest.mock.MagicMock(returncode=1, stderr="not found")
        scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Should not crash, failures are logged in notes
    if mock_run.called:
        failure_notes = [n for n in scaf.notes if "command failed" in n or "executed:" in n]
        assert len(failure_notes) > 0 or len(mock_run.call_args_list) == 0
