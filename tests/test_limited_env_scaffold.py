"""Behavior contract for the opt-in instruction-only stack."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scaffold_helpers import _config

HOOK_SKILLS = ["task", "prompt-markers", "ai-raccoon-memory", "git-work"]


def _commands_in_hooks(path: Path) -> list[str]:
    """Return command strings beneath hook sections in one generated config file."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    commands: list[str] = []

    def visit(value, in_hooks=False):
        if isinstance(value, dict):
            for key, child in value.items():
                if in_hooks and key in {"command", "bash"} and isinstance(child, str):
                    commands.append(child)
                else:
                    visit(child, in_hooks or key == "hooks")
        elif isinstance(value, list):
            for child in value:
                visit(child, in_hooks)

    visit(data)
    return commands


def _is_ai_badger_command(command: str) -> bool:
    return any(marker in command for marker in
               (".ai-badger/", "features/common/", "ai_badger", "AI_BADGER_TOOL="))


@pytest.mark.parametrize(
    ("agent", "registration"),
    [
        ("claude", ".claude/settings.json"),
        ("codex", ".codex/hooks.json"),
        ("copilot", ".github/hooks/ai-badger-hooks.json"),
        ("hermes", "user-plugin"),
        ("pi", "user-extension"),
    ],
)
def test_limited_env_does_not_add_ai_badger_hook_registrations(
        agent, registration, make_scaffolder):
    config = _config(stacks=[agent, "limited-env"], agents=[agent])
    config["tools"] = {"rtk": {"hooks": [agent]}}
    scaffolder = make_scaffolder(config=config, skills=HOOK_SKILLS, install=True)

    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    if registration == "user-plugin":
        plugin = Path.home() / ".hermes" / "plugins" / "ai-badger" / "plugin.yaml"
        assert not plugin.exists()
        assert not (make_scaffolder.target / ".ai-badger" / "hooks" / "hooks.json").exists()
    elif registration == "user-extension":
        extension = Path.home() / ".pi" / "agent" / "extensions" / "ai-badger" / "index.ts"
        assert not extension.exists()
        assert not (make_scaffolder.target / ".ai-badger" / "hooks" / "hooks.json").exists()
    else:
        output = make_scaffolder.target / registration
        assert not any(_is_ai_badger_command(command) for command in _commands_in_hooks(output)), (output.read_text() if output.exists() else "missing")
    generated_hooks = make_scaffolder.target / ".ai-badger" / "hooks" / "hooks.json"
    assert not any(_is_ai_badger_command(command) for command in _commands_in_hooks(generated_hooks))


def test_limited_env_delivers_instruction_boundary(make_scaffolder):
    scaffolder = make_scaffolder(
        config=_config(stacks=["limited-env"], agents=["claude"]),
        skills=HOOK_SKILLS + ["evidence-first-research", "get-raw-text-search",
                             "artifact-verification"])

    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    instruction = make_scaffolder.target / ".ai-badger" / "invariants" / "instruction-only.md"
    text = instruction.read_text(encoding="utf-8")
    assert "memory search" in text
    assert "canonical projectId, scope=all" in text
    assert "when the topic changes" in text
    assert "do not claim memory was checked" in text
    assert "no hook enforces it" in text
    assert "administrator" in text
    assert "does not prohibit repository scripts" in text
    task_extension = make_scaffolder.target / ".ai-badger/skills/task/extensions/limited-env/extension.md"
    task_text = task_extension.read_text(encoding="utf-8")
    assert "Do not run `limited_mode.py checkin`" in task_text
    assert "manual checkpoint" in task_text
    marker_extension = make_scaffolder.target / ".ai-badger/skills/prompt-markers/extensions/limited-env/extension.md"
    assert "no prompt hook injects" in marker_extension.read_text(encoding="utf-8")
    extension_expectations = {
        "evidence-first-research": "If memory search is unavailable",
        "get-raw-text-search": "Use the `rg` or other permitted search command directly",
        "artifact-verification": "Use visible, permitted commands",
    }
    for skill, expected in extension_expectations.items():
        extension = (make_scaffolder.target / ".ai-badger" / "skills" / skill /
                     "extensions/limited-env/extension.md")
        assert expected in extension.read_text(encoding="utf-8")


def test_limited_env_preserves_third_party_claude_hook_when_removing_owned_hook(
        make_scaffolder):
    target = make_scaffolder.target
    settings_path = target / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "python3 /project/.ai-badger/skills/task/scripts/session_start_hook.py"}]},
                {"hooks": [{"type": "command", "command": "third-party startup check"}]},
                    {"hooks": [{"type": "command", "command": None}]},
                    {"hooks": None},
                    {"hooks": [{"type": "command", "command": "env AI_BADGER_TOOL=rtk rtk hook claude"}]},
            ]
        },
        "permissions": {"allow": ["Read"]},
    }
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    scaffolder = make_scaffolder(
        config=_config(stacks=["claude", "limited-env"], agents=["claude"]),
        skills=HOOK_SKILLS)
    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    result = json.loads(settings_path.read_text(encoding="utf-8"))
    commands = [hook["command"]
                for entry in result.get("hooks", {}).get("SessionStart", [])
                for hook in (entry.get("hooks") or [])]
    assert "third-party startup check" in commands
    assert None in [hook.get("command")
                    for entry in result["hooks"]["SessionStart"]
                    for hook in (entry.get("hooks") or [])]
    assert {"hooks": None} in result["hooks"]["SessionStart"]
    assert not any(isinstance(command, str)
                   and "/.ai-badger/skills/task/scripts/session_start_hook.py" in command
                   for command in commands)
    assert not any("AI_BADGER_TOOL=" in command for command in
                   _commands_in_hooks(settings_path))
    assert "Read" in result["permissions"]["allow"]


@pytest.mark.parametrize(
    ("agent", "relative", "owned", "unrelated"),
    [
        ("codex", ".codex/hooks.json",
         "env AI_BADGER_CODEX_HOOK=1 python hooks/ai-raccoon-memory/scripts/memory_first_gate_hook.py",
         "third-party codex hook"),
    ],
)
def test_limited_env_removes_owned_codex_hook_and_preserves_unrelated(
        agent, relative, owned, unrelated, make_scaffolder):
    target = make_scaffolder.target
    config_path = target / relative
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": owned},
                   {"type": "command", "command": "env AI_BADGER_TOOL=rtk rtk hook codex"},
                   {"type": "command", "command": unrelated}]}
    ]}}), encoding="utf-8")

    scaffolder = make_scaffolder(
        config=_config(stacks=[agent, "limited-env"], agents=[agent]),
        skills=HOOK_SKILLS)
    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    commands = _commands_in_hooks(config_path)
    assert unrelated in commands
    assert owned not in commands
    assert not any("AI_BADGER_TOOL=" in command for command in commands)


def test_limited_env_removes_copilot_hook_file_without_touching_sibling(
        make_scaffolder):
    target = make_scaffolder.target
    hooks_dir = target / ".github" / "hooks"
    hooks_dir.mkdir(parents=True)
    owned = hooks_dir / "ai-badger-hooks.json"
    owned.write_text(json.dumps({"version": 1, "hooks": {"sessionStart": [
        {"type": "command", "bash": "python .ai-badger/hooks/ai_badger_hooks.py"}
    ]}}), encoding="utf-8")
    unrelated = hooks_dir / "vendor-hooks.json"
    unrelated.write_text('{"vendor": true}\n', encoding="utf-8")
    tool_hook = hooks_dir / "rtk-rewrite.json"
    tool_hook.write_text(json.dumps({"version": 1, "hooks": {"PreToolUse": [
        {"type": "command", "command": "env AI_BADGER_TOOL=rtk rtk hook copilot"}
    ]}}), encoding="utf-8")

    config = _config(stacks=["copilot", "limited-env"], agents=["copilot"])
    config["tools"] = {"rtk": {"hooks": ["copilot"]}}
    scaffolder = make_scaffolder(
        config=config, skills=HOOK_SKILLS)
    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    assert not owned.exists()
    assert not tool_hook.exists()
    assert unrelated.read_text(encoding="utf-8") == '{"vendor": true}\n'


@pytest.mark.parametrize("agent", ["hermes", "pi"])
def test_limited_env_preserves_existing_user_hook_install(agent, make_scaffolder):
    if agent == "hermes":
        installed = Path.home() / ".hermes" / "plugins" / "ai-badger" / "plugin.yaml"
    else:
        installed = Path.home() / ".pi" / "agent" / "extensions" / "ai-badger" / "index.ts"
    installed.parent.mkdir(parents=True)
    installed.write_text("user-installed version\n", encoding="utf-8")

    scaffolder = make_scaffolder(
        config=_config(stacks=[agent, "limited-env"], agents=[agent]),
        skills=HOOK_SKILLS, install=True)
    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    assert installed.read_text(encoding="utf-8") == "user-installed version\n"


@pytest.mark.parametrize("agent", ["claude", "codex", "copilot", "hermes", "pi"])
def test_omitting_limited_env_keeps_normal_ai_badger_hook_delivery(
        agent, make_scaffolder, tmp_path):
    target = tmp_path / f"normal-{agent}"
    scaffolder = make_scaffolder(
        config=_config(stacks=[agent], agents=[agent]), target=target,
        skills=HOOK_SKILLS, install=True)

    scaffolder.run(generated_at="2026-10-21T00:00:00Z")

    if agent in {"claude", "codex", "copilot"}:
        output = target / {
            "claude": ".claude/settings.json",
            "codex": ".codex/hooks.json",
            "copilot": ".github/hooks/ai-badger-hooks.json",
        }[agent]
        commands = _commands_in_hooks(output)
        assert any(_is_ai_badger_command(command) for command in commands), (output,
            output.read_text() if output.exists() else "missing")
    elif agent == "hermes":
        assert (Path.home() / ".hermes/plugins/ai-badger/plugin.yaml").exists()
    else:
        assert (Path.home() / ".pi/agent/extensions/ai-badger/index.ts").exists()
