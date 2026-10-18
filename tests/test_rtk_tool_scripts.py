"""Tests for the rtk tool catalog entry: check.py, install.py, meta.json and tool.md.

Every rtk, brew and winget here is a stub script on a PATH made of tmp_path only, so no test
reaches the network or a real package manager.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path("features/common/tools/rtk")
CHECK = TOOL_DIR / "scripts" / "check.py"
INSTALL = TOOL_DIR / "scripts" / "install.py"


def _stub(bin_dir: Path, name: str, body: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _recording_stub(bin_dir: Path, name: str, log: Path, exit_code: int = 0) -> Path:
    return _stub(bin_dir, name, f'echo "{name} $*" >> "{log}"\nexit {exit_code}')


def _run(root: Path, script: Path, bin_dir: Path, *args: str, env: dict | None = None):
    bin_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(root / script), *args],
        env={"PATH": str(bin_dir), **(env or {})},
        capture_output=True, text=True, timeout=30, check=False,
    )


# ── check.py ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("version", ["rtk 1.0.1", "rtk 1.2.0", "rtk 2.0.0"])
def test_check_passes_at_or_above_the_floor(root, tmp_path, version):
    _stub(tmp_path / "bin", "rtk", f'[ "$1" = "--version" ] && echo "{version}"')

    result = _run(root, CHECK, tmp_path / "bin")

    assert result.returncode == 0, result.stderr
    assert version.split()[1] in result.stdout


@pytest.mark.parametrize("output", ["rtk 0.50.0", "rtk 1.0.0", "rtk 0.99.9"])
def test_check_fails_below_the_floor(root, tmp_path, output):
    _stub(tmp_path / "bin", "rtk", f'echo "{output}"')

    result = _run(root, CHECK, tmp_path / "bin")

    assert result.returncode == 1
    assert "1.0.1" in result.stderr


@pytest.mark.parametrize("output", [
    "Rust Type Kit 1.0.1",
    "rtk-cli 1.2.0",
    "rtk version unknown",
    "",
])
def test_check_fails_when_the_rtk_on_path_is_not_rtk_ai(root, tmp_path, output):
    """crates.io `rtk` is Rust Type Kit; only `^rtk <digit>` is the rtk-ai binary."""
    _stub(tmp_path / "bin", "rtk", f'echo "{output}"')

    result = _run(root, CHECK, tmp_path / "bin")

    assert result.returncode == 1
    assert result.stdout == ""


def test_check_fails_when_rtk_is_not_on_path(root, tmp_path):
    result = _run(root, CHECK, tmp_path / "bin")

    assert result.returncode == 1
    assert "not on PATH" in result.stderr


def test_check_fails_when_rtk_version_exits_non_zero(root, tmp_path):
    _stub(tmp_path / "bin", "rtk", 'echo "rtk 1.2.0"\nexit 3')

    result = _run(root, CHECK, tmp_path / "bin")

    assert result.returncode == 1


# ── install.py ───────────────────────────────────────────────────────────────

def test_install_without_run_executes_nothing(root, tmp_path):
    log = tmp_path / "calls.log"
    _recording_stub(tmp_path / "bin", "brew", log)
    _recording_stub(tmp_path / "bin", "winget", log)

    result = _run(root, INSTALL, tmp_path / "bin")

    assert result.returncode == 0
    assert not log.exists()
    assert "brew install rtk" in result.stdout
    assert "--run" in result.stdout


def test_install_run_prints_the_licence_before_calling_brew(root, tmp_path):
    log = tmp_path / "calls.log"
    _recording_stub(tmp_path / "bin", "brew", log)

    result = _run(root, INSTALL, tmp_path / "bin", "--run")

    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["brew install rtk"]
    out = result.stdout
    assert "BUSL-1.1" in out
    assert "RTK_EDITION=oss" in out
    assert "--no-default-features" in out
    assert out.index("BUSL-1.1") < out.index("Running: brew install rtk")


def test_install_run_with_oss_edition_installs_the_oss_formula(root, tmp_path):
    log = tmp_path / "calls.log"
    _recording_stub(tmp_path / "bin", "brew", log)

    result = _run(root, INSTALL, tmp_path / "bin", "--run", env={"RTK_EDITION": "oss"})

    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["brew install rtk-ai/tap/rtk-oss"]


def test_install_run_propagates_a_brew_failure(root, tmp_path):
    log = tmp_path / "calls.log"
    _recording_stub(tmp_path / "bin", "brew", log, exit_code=7)

    result = _run(root, INSTALL, tmp_path / "bin", "--run")

    assert result.returncode != 0
    assert log.exists()


def test_install_run_without_brew_prints_recipes_and_fails_never_calling_winget(root, tmp_path):
    log = tmp_path / "calls.log"
    _recording_stub(tmp_path / "bin", "winget", log)

    result = _run(root, INSTALL, tmp_path / "bin", "--run")

    assert result.returncode != 0
    assert not log.exists()
    out = result.stdout
    assert "BUSL-1.1" in out
    assert "cargo install --git https://github.com/rtk-ai/rtk rtk" in out
    assert "winget install rtk-ai.rtk" in out
    assert "install.sh" in out


def test_install_source_never_pipes_a_download_into_sh(root):
    source = (root / INSTALL).read_text(encoding="utf-8")

    assert not re.search(r"\|\s*sh\b", source)


# ── meta.json ────────────────────────────────────────────────────────────────

def test_meta_declares_the_hook_mode_for_every_agent(root):
    meta = json.loads((root / TOOL_DIR / "meta.json").read_text(encoding="utf-8"))

    modes = {agent: spec["mode"] for agent, spec in meta["hooks"].items()}

    assert meta["name"] == "rtk"
    # Claude is native through rtk_guard.py, which leaves an ask-matched command unrewritten.
    # Codex stays propose until a live Codex run; its spec already names the same guard.
    assert modes == {"claude": "native", "codex": "propose", "copilot": "native",
                     "pi": "init", "hermes": "propose"}
    assert meta["hooks"]["claude"]["guard"] == meta["hooks"]["codex"]["guard"]
    assert "1.0.1" in meta["prerequisite"]["summary"]
    assert "scripts/check.py" in meta["prerequisite"]["check"]


def test_meta_validates_against_the_tool_schema(root):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((root / "schemas" / "tool.schema.json").read_text(encoding="utf-8"))
    meta = json.loads((root / TOOL_DIR / "meta.json").read_text(encoding="utf-8"))

    jsonschema.validate(meta, schema)


# ── tool.md ──────────────────────────────────────────────────────────────────

def _tool_md(root: Path) -> str:
    return (root / TOOL_DIR / "tool.md").read_text(encoding="utf-8")


def test_tool_md_has_the_section_heading(root):
    assert "## Tools: rtk" in _tool_md(root).splitlines()


def test_tool_md_names_rtk_gain_as_the_verification_not_show_or_verify(root):
    text = _tool_md(root)

    assert "rtk gain" in text
    assert "--show" not in text.replace("`rtk init --show`", "")
    assert "rtk verify" not in text


@pytest.mark.parametrize("phrase", [
    "rtk init",                # running it on a wired agent duplicates the hook
    "duplicate",
    "user-level",
    "Codex",
    "approval",
    "classifier",
    "history.db",
    "90",
    "tracking.enabled=false",
    "RTK_DB_PATH",
    "RTK_RECALL=0",
    "BUSL-1.1",
    "rtk-oss",
    "PATH",
    "POSIX",
])
def test_tool_md_covers_the_reviewed_risks(root, phrase):
    assert phrase in _tool_md(root)


def test_tool_md_stays_within_the_mcp_server_md_line_budget(root):
    """Same 15-line budget as test_every_shipped_server_md_stays_within_the_line_budget in
    tests/test_mcp_catalog_instructions.py: it lands verbatim in every agent file."""
    assert len(_tool_md(root).strip().splitlines()) <= 15
