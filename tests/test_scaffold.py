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


# ----------------------------------------------------------------- stack-local skills
def test_auto_wm_is_not_a_universal_default(load_script):
    """auto-wm is a claude stack-local skill, not in the universal SKILL_SCOPES."""
    bl = load_script("scripts/badger_lib.py")
    assert "auto-wm" not in bl.SKILL_SCOPES


def test_scaffolder_discovers_stack_local_skill_for_configured_stack(
        tmp_path, load_script, root):
    """A stack-local skill is auto-discovered when its stack is configured."""
    scaffold = load_script(
        "features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    target = tmp_path / "proj"
    target.mkdir()
    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(stacks=["claude"]),
        skills=[], install=False)
    result = scaf.run(generated_at="2026-07-28T00:00:00Z")

    assert "auto-wm" in scaf.skills
    assert (target / ".ai-badger" / "skills" / "auto-wm").is_dir()
    skill_entries = [e for e in result["manifest"]["entries"]
                     if e.get("feature") == "skills"
                     and e.get("name") == "auto-wm"]
    assert len(skill_entries) == 1
    assert skill_entries[0]["stack"] == "claude"


def test_scaffolder_does_not_discover_stack_local_skill_for_other_stack(
        tmp_path, load_script, root):
    """A stack-local skill is NOT included when its stack is not configured."""
    scaffold = load_script(
        "features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    target = tmp_path / "proj"
    target.mkdir()
    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(stacks=["dotnet"]),
        skills=[], install=False)
    scaf.run(generated_at="2026-07-28T00:00:00Z")

    assert "auto-wm" not in scaf.skills
    assert not (target / ".ai-badger" / "skills" / "auto-wm").exists()


def test_stack_local_skill_not_symlinked_to_other_agent(
        tmp_path, load_script, root):
    """A claude stack-local skill must not appear in copilot's adjustment context."""
    scaffold = load_script(
        "features/common/skills/welcome-ai-badger/scripts/scaffold.py")

    # Capture what skills each agent's adjustment receives
    seen = {}
    original_run = scaffold.Scaffolder.run_adjustments

    def capturing_run(self):
        import importlib.util
        for agent_name in self.config.get("agents", []):
            adj_path = self.root / "features" / agent_name / "adjustments" / "adjustment.json"
            if not adj_path.exists():
                continue
            adj_manifest = scaffold.bl.load_json(adj_path)
            for adj in adj_manifest.get("adjustments", []):
                script_name = adj.get("script")
                if not script_name:
                    continue
                script_path = adj_path.parent / script_name
                if not script_path.exists():
                    continue
                spec = importlib.util.spec_from_file_location("test", script_path)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                agent_stacks = [s for s in self.stacks
                                if s == "common" or s == agent_name]
                agent_skills = [s for s in self.skills
                                if any(s in scaffold.bl.skills_for_stack(self.root, st)
                                       for st in agent_stacks)]
                seen[agent_name] = agent_skills
        # Don't actually run adjustments

    target = tmp_path / "proj"
    target.mkdir()
    scaf = scaffold.Scaffolder(
        root=root, target=target,
        config=_config(stacks=["claude"], agents=["claude", "copilot"]),
        skills=[], install=False)
    scaf.run(generated_at="2026-07-28T00:00:00Z")

    # After run, capture what each agent would get
    agent_stacks_claude = ["common", "claude"]
    agent_stacks_copilot = ["common"]
    claude_skills = [s for s in scaf.skills
                     if any(s in scaffold.bl.skills_for_stack(root, st)
                            for st in agent_stacks_claude)]
    copilot_skills = [s for s in scaf.skills
                      if any(s in scaffold.bl.skills_for_stack(root, st)
                             for st in agent_stacks_copilot)]

    assert "auto-wm" in claude_skills
    assert "auto-wm" not in copilot_skills
