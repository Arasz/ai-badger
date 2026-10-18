"""user_hook.py: the user-scope rtk guard hook, self-contained so it outlives the checkout.

Every case runs the script as a subprocess with HOME and CLAUDE_CONFIG_DIR inside tmp_path, so
the real ~/.claude/settings.json is never read or written.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RTK = ROOT / "features/common/tools/rtk"
SCRIPT = RTK / "scripts/user_hook.py"
SCRIPTS = ROOT / "features/common/skills/welcome-ai-badger/scripts"

LEGACY = f"python3 -I {RTK}/scripts/rtk_guard.py claude || true"
AWM = {"matcher": "*", "hooks": [{"type": "command", "command": "python3 /x/awm_gate.py"}]}

RTK_STUB = f"""#!{sys.executable}
import sys
print("rtk " + sys.argv[2])
sys.exit(0)
"""


def project_command() -> str:
    """The command project scope wires for Claude: the guard source inlined."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import tool_hooks  # pylint: disable=import-outside-toplevel
    source = (RTK / "scripts/rtk_guard.py").read_text(encoding="utf-8")
    return tool_hooks.guarded_command("rtk", "claude", source)


class Home:
    """A tmp HOME with its own CLAUDE_CONFIG_DIR."""

    def __init__(self, base: Path):
        self.base = base
        self.config = base / "claude"
        self.config.mkdir()
        self.settings = self.config / "settings.json"
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(base / "home"),
                    "CLAUDE_CONFIG_DIR": str(self.config)}

    def write(self, data) -> None:
        self.settings.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def read(self) -> dict:
        return json.loads(self.settings.read_text(encoding="utf-8"))

    def run(self, *args: str):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                              text=True, env=self.env, cwd=str(self.base), timeout=30,
                              check=False)

    def backups(self) -> list[Path]:
        return sorted(self.settings.resolve().parent.glob("settings.json.bak-*"))

    def rtk_commands(self) -> list[str]:
        return [h["command"] for g in self.read()["hooks"]["PreToolUse"]
                for h in g["hooks"] if "rtk" in h["command"]]


@pytest.fixture(name="home")
def home_fixture(tmp_path) -> Home:
    return Home(tmp_path)


def test_dry_run_prints_the_entry_and_writes_nothing(home):
    proc = home.run()
    assert proc.returncode == 0, proc.stderr
    assert json.dumps(project_command()) in proc.stdout
    assert str(home.settings) in proc.stdout
    assert not home.settings.exists()


def test_apply_replaces_the_checkout_path_entry_and_keeps_other_hooks(home):
    before = {"permissions": {"defaultMode": "auto"},
              "hooks": {"PreToolUse": [AWM, {"matcher": "Bash", "hooks": [
                  {"type": "command", "command": LEGACY}]}]}}
    home.write(before)
    proc = home.run("--apply")
    assert proc.returncode == 0, proc.stderr
    after = home.read()
    assert home.rtk_commands() == [project_command()]
    assert after["hooks"]["PreToolUse"][0] == AWM
    assert after["permissions"] == before["permissions"]
    [backup] = home.backups()
    assert json.loads(backup.read_text(encoding="utf-8")) == before


def test_apply_replaces_a_stale_marked_entry(home):
    stale = project_command().replace("TIMEOUT = 4", "TIMEOUT = 9")
    assert stale != project_command()
    home.write({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": stale}]}]}})
    assert home.run("--apply").returncode == 0
    assert home.rtk_commands() == [project_command()]
    assert len(home.read()["hooks"]["PreToolUse"]) == 1


def test_second_apply_writes_nothing(home):
    home.write({"hooks": {"PreToolUse": [AWM]}})
    assert home.run("--apply").returncode == 0
    for backup in home.backups():
        backup.unlink()
    text = home.settings.read_text(encoding="utf-8")
    proc = home.run("--apply")
    assert proc.returncode == 0, proc.stderr
    assert home.settings.read_text(encoding="utf-8") == text
    assert not home.backups()
    assert "already has the current" in home.run().stdout


def test_apply_creates_a_missing_settings_file(home):
    assert home.run("--apply").returncode == 0
    assert home.rtk_commands() == [project_command()]


def test_a_bare_rtk_hook_is_kept_and_named(home):
    bare = {"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}
    home.write({"hooks": {"PreToolUse": [bare]}})
    proc = home.run("--apply")
    assert proc.returncode == 0, proc.stderr
    assert home.read()["hooks"]["PreToolUse"][0] == bare
    assert "rtk hook claude" in proc.stdout + proc.stderr


def test_invalid_settings_are_refused_untouched(home):
    home.settings.write_text("{not json", encoding="utf-8")
    proc = home.run("--apply")
    assert proc.returncode != 0
    assert home.settings.read_text(encoding="utf-8") == "{not json"


def test_the_applied_hook_runs_without_the_checkout(home, tmp_path):
    home.run("--apply")
    command = home.rtk_commands()[0]
    assert str(ROOT) not in command
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "rtk").write_text(RTK_STUB, encoding="utf-8")
    (bin_dir / "rtk").chmod(0o755)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(elsewhere),
             "tool_input": {"command": "git status"}}
    proc = subprocess.run(["/bin/sh", "-c", command], input=json.dumps(event),
                          capture_output=True, text=True, cwd=str(elsewhere), timeout=30,
                          env={**home.env, "PATH": f"{bin_dir}:/usr/bin:/bin"}, check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["updatedInput"]["command"] == "rtk git status"


@pytest.mark.parametrize("hooks", [[], {"PreToolUse": {}}, {"PreToolUse": [{"hooks": "x"}]}])
def test_a_settings_file_of_the_wrong_shape_is_refused_untouched(home, hooks):
    home.write({"hooks": hooks})
    text = home.settings.read_text(encoding="utf-8")
    proc = home.run("--apply")
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert home.settings.read_text(encoding="utf-8") == text


def test_a_symlinked_settings_file_stays_a_symlink_with_its_mode(home, tmp_path):
    real = tmp_path / "dotfiles/settings.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"hooks": {"PreToolUse": [AWM]}}), encoding="utf-8")
    real.chmod(0o600)
    home.settings.symlink_to(real)
    assert home.run("--apply").returncode == 0
    assert home.settings.is_symlink()
    assert real.stat().st_mode & 0o777 == 0o600
    assert home.rtk_commands() == [project_command()]


def test_without_claude_config_dir_it_writes_under_home(home):
    env = {k: v for k, v in home.env.items() if k != "CLAUDE_CONFIG_DIR"}
    proc = subprocess.run([sys.executable, str(SCRIPT), "--apply"], capture_output=True,
                          text=True, env=env, cwd=str(home.base), timeout=30, check=False)
    assert proc.returncode == 0, proc.stderr
    assert (Path(env["HOME"]) / ".claude/settings.json").is_file()
    assert not home.settings.exists()
