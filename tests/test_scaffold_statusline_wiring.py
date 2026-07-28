"""Statusline capture wiring: opt-in, portable, and never a renderer the user did not ask for."""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scaffold_helpers import _config

SCAFFOLD = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
CAPTURE = "task/scripts/statusline_capture.py"
DELEGATE_RECORD = Path(".ai-badger") / "task-tracking" / "statusline-delegate.json"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` and the HOME env vars into tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home
    return home


def _capture_config(enabled=True, agents=None):
    config = _config(stacks=["python"], agents=agents)
    config["statusLineCapture"] = {"enabled": enabled}
    return config


def _run(make_scaffolder, config, skills=("task",)):
    scaf = make_scaffolder(config=config, skills=list(skills))
    result = scaf.run(generated_at="2026-07-27T00:00:00Z")
    return result["notes"]


def _settings(target):
    path = target / ".claude" / "settings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _delegate(target):
    path = target / DELEGATE_RECORD
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_settings(target, data):
    path = target / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def target(make_scaffolder):
    """The factory's shared target; the scaffolder writes here."""
    return make_scaffolder.target


@pytest.mark.usefixtures("fake_home")
def test_statusline_is_not_wired_when_the_config_key_is_absent(target, make_scaffolder):
    """statusLine is a personal setting: an unasked-for project override is a clobber."""
    _run(make_scaffolder, _config(stacks=["python"]))

    assert "statusLine" not in _settings(target)
    assert _delegate(target) is None


@pytest.mark.usefixtures("fake_home")
def test_statusline_is_not_wired_when_capture_is_disabled(target, make_scaffolder):
    _run(make_scaffolder, _capture_config(enabled=False))

    assert "statusLine" not in _settings(target)


@pytest.mark.usefixtures("fake_home")
def test_enabling_wires_the_capture_script_through_the_project_dir_placeholder(
        target, make_scaffolder):
    """The wired command must survive a second checkout, so no absolute path (F-hooks)."""
    _run(make_scaffolder, _capture_config())

    entry = _settings(target)["statusLine"]
    assert entry["type"] == "command"
    assert "${CLAUDE_PROJECT_DIR}" in entry["command"]
    assert entry["command"].endswith(f'/.ai-badger/skills/{CAPTURE}"')
    assert str(target) not in entry["command"]


@pytest.mark.usefixtures("fake_home")
def test_an_existing_project_statusline_becomes_the_delegate(target, make_scaffolder):
    _write_settings(target, {"statusLine": {"type": "command", "command": "my-renderer.sh"}})

    _run(make_scaffolder, _capture_config())

    assert _delegate(target)["command"] == "my-renderer.sh"
    assert CAPTURE in _settings(target)["statusLine"]["command"]


def test_the_user_level_statusline_becomes_the_delegate_when_the_project_has_none(
        target, fake_home, make_scaffolder):
    user_settings = fake_home / ".claude" / "settings.json"
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_settings.write_text(
        json.dumps({"statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}}),
        encoding="utf-8")

    _run(make_scaffolder, _capture_config())

    assert _delegate(target)["command"] == "~/.claude/statusline.sh"


def test_an_unreadable_user_settings_file_is_reported_not_silently_ignored(
        fake_home, make_scaffolder):
    """Reading no delegate out of a broken file would drop the user's renderer without a word."""
    user_settings = fake_home / ".claude" / "settings.json"
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_settings.write_text("{ not json", encoding="utf-8")

    notes = _run(make_scaffolder, _capture_config())

    assert any("refused" in n and ".claude/settings.json" in n for n in notes), notes


@pytest.mark.usefixtures("fake_home")
def test_no_delegate_is_recorded_when_nothing_rendered_a_statusline(target, make_scaffolder):
    _run(make_scaffolder, _capture_config())

    assert _delegate(target)["command"] is None


@pytest.mark.usefixtures("fake_home")
def test_enabling_twice_never_chains_the_capture_to_itself(target, make_scaffolder):
    """Recording ai-badger's own wrapper as its delegate is an infinite statusline loop."""
    _write_settings(target, {"statusLine": {"type": "command", "command": "my-renderer.sh"}})
    config = _capture_config()

    _run(make_scaffolder, config)
    _run(make_scaffolder, config)

    assert _delegate(target)["command"] == "my-renderer.sh"
    assert _settings(target)["statusLine"]["command"].count(CAPTURE) == 1


@pytest.mark.usefixtures("fake_home")
def test_a_capture_command_from_another_checkout_is_replaced_not_chained(target, make_scaffolder):
    _write_settings(target, {"statusLine": {
        "type": "command",
        "command": 'python3 "/elsewhere/.ai-badger/skills/task/scripts/statusline_capture.py"',
    }})

    _run(make_scaffolder, _capture_config())

    entry = _settings(target)["statusLine"]
    assert entry["command"].count(CAPTURE) == 1
    assert "/elsewhere/" not in entry["command"]
    assert _delegate(target) is None, "the wrapper was recorded as its own delegate"


@pytest.mark.usefixtures("fake_home")
def test_display_options_of_the_replaced_statusline_are_preserved(target, make_scaffolder):
    _write_settings(target, {"statusLine": {
        "type": "command", "command": "my-renderer.sh", "padding": 1, "refreshInterval": 5,
    }})

    _run(make_scaffolder, _capture_config())

    entry = _settings(target)["statusLine"]
    assert entry["padding"] == 1
    assert entry["refreshInterval"] == 5


@pytest.mark.usefixtures("fake_home")
def test_an_unreadable_settings_file_is_refused_with_a_note(target, make_scaffolder):
    path = _write_settings(target, {})
    path.write_text("{ not json", encoding="utf-8")

    notes = _run(make_scaffolder, _capture_config())

    assert path.read_text(encoding="utf-8") == "{ not json"
    assert any("refused" in n and "statusline" in n.lower() for n in notes), notes


@pytest.mark.usefixtures("fake_home")
def test_a_statusline_of_the_wrong_shape_is_refused_with_a_note(target, make_scaffolder):
    _write_settings(target, {"statusLine": "not-a-mapping"})

    notes = _run(make_scaffolder, _capture_config())

    assert _settings(target)["statusLine"] == "not-a-mapping"
    assert any("refused" in n and "statusline" in n.lower() for n in notes), notes


@pytest.mark.usefixtures("fake_home")
def test_statusline_is_not_wired_when_claude_is_not_a_configured_agent(target, make_scaffolder):
    _run(make_scaffolder, _capture_config(agents=["copilot"]))

    assert "statusLine" not in _settings(target)


@pytest.mark.usefixtures("fake_home")
def test_statusline_is_not_wired_when_the_capture_script_was_not_scaffolded(
        target, make_scaffolder):
    """Pointing statusLine at a script that is not there replaces the renderer with nothing."""
    _write_settings(target, {"statusLine": {"type": "command", "command": "my-renderer.sh"}})

    notes = _run(make_scaffolder, _capture_config(), skills=["prompt-markers"])

    assert _settings(target)["statusLine"]["command"] == "my-renderer.sh"
    assert _delegate(target) is None
    assert any("statusline capture" in n and "task" in n for n in notes), notes


@pytest.mark.usefixtures("fake_home")
def test_disabling_capture_restores_the_renderer_it_displaced(target, make_scaffolder):
    """Turning the flag off must give the user their own status line back."""
    _write_settings(target, {"statusLine": {"type": "command", "command": "my-renderer.sh"}})
    _run(make_scaffolder, _capture_config())

    _run(make_scaffolder, _capture_config(enabled=False))

    assert _settings(target)["statusLine"]["command"] == "my-renderer.sh"


@pytest.mark.usefixtures("fake_home")
def test_disabling_capture_preserves_the_display_options_of_the_restored_renderer(
        target, make_scaffolder):
    _write_settings(target, {"statusLine": {
        "type": "command", "command": "my-renderer.sh", "padding": 1,
    }})
    _run(make_scaffolder, _capture_config())

    _run(make_scaffolder, _capture_config(enabled=False))

    entry = _settings(target)["statusLine"]
    assert entry["command"] == "my-renderer.sh"
    assert entry["padding"] == 1


@pytest.mark.usefixtures("fake_home")
def test_disabling_capture_removes_the_statusline_when_it_displaced_nothing(
        target, make_scaffolder):
    _run(make_scaffolder, _capture_config())

    _run(make_scaffolder, _capture_config(enabled=False))

    assert "statusLine" not in _settings(target)


@pytest.mark.usefixtures("fake_home")
def test_disabling_capture_never_removes_a_statusline_ai_badger_did_not_place(
        target, make_scaffolder):
    """Refuse-to-clobber: a renderer we never displaced is not ours to remove."""
    _write_settings(target, {"statusLine": {"type": "command", "command": "my-renderer.sh"}})

    _run(make_scaffolder, _capture_config(enabled=False))

    assert _settings(target)["statusLine"]["command"] == "my-renderer.sh"


@pytest.mark.usefixtures("fake_home")
def test_dropping_claude_from_the_agents_unwires_the_capture(target, make_scaffolder):
    _write_settings(target, {"statusLine": {"type": "command", "command": "my-renderer.sh"}})
    _run(make_scaffolder, _capture_config())

    _run(make_scaffolder, _capture_config(agents=["copilot"]))

    assert _settings(target)["statusLine"]["command"] == "my-renderer.sh"


@pytest.mark.usefixtures("fake_home")
def test_unwiring_refuses_an_unreadable_settings_file_with_a_note(target, make_scaffolder):
    _run(make_scaffolder, _capture_config())
    path = target / ".claude" / "settings.json"
    path.write_text("{ not json", encoding="utf-8")

    notes = _run(make_scaffolder, _capture_config(enabled=False))

    assert path.read_text(encoding="utf-8") == "{ not json"
    assert any("refused" in n and "statusline" in n.lower() for n in notes), notes


@pytest.mark.usefixtures("fake_home")
def test_unwiring_leaves_a_statusline_of_the_wrong_shape_alone(target, make_scaffolder):
    _write_settings(target, {"statusLine": "not-a-mapping"})

    _run(make_scaffolder, _capture_config(enabled=False))

    assert _settings(target)["statusLine"] == "not-a-mapping"


def test_config_schema_accepts_the_statusline_capture_key(tmp_path, root, load_script, capsys):
    import shutil  # pylint: disable=import-outside-toplevel

    validate = load_script("tooling/validate.py")
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    instance = tmp_path / "config.json"
    config = _config(stacks=["python"])
    config["statusLineCapture"] = {"enabled": True}
    instance.write_text(json.dumps(config), encoding="utf-8")

    rc = validate.main(["--kind", "config", "--root", str(tmp_path), str(instance)])

    assert rc == 0, capsys.readouterr().out
