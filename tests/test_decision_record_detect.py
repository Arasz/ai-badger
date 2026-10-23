"""The decision-record skill writes into the format a project already uses, found from the tree.

A detector that guesses wrong sends a decision into a log nobody reads: an OpenSpec change in a
repo whose decisions live in `docs/adr/`, or a fresh `docs/decisions/` beside an existing one.
Each test below names the wrong answer it exists to catch.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from conftest import _test_write

SCRIPT = (Path(__file__).resolve().parents[1]
          / "features/common/skills/decision-record/scripts/detect_formats.py")

_spec = importlib.util.spec_from_file_location("detect_formats", SCRIPT)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

detect = _module.detect


def nothing_installed(_name):
    return None


def write(root: Path, rel: str, text: str = "# record\n") -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    _test_write(root / rel, text)


class TestAnEmptyProject:
    def test_reports_no_format_and_falls_back_to_madr(self, tmp_path):
        result = detect(tmp_path, which=nothing_installed)
        assert result["mode"] == "none"
        assert result["adr"] == [] and result["specs"] == []
        assert result["fallback"] == {"dir": "docs/decisions", "next": "0001"}


class TestAnAdrLog:
    def test_finds_the_log_and_the_next_number(self, tmp_path):
        write(tmp_path, "docs/adr/0001-first.md")
        write(tmp_path, "docs/adr/0002-second.md")
        write(tmp_path, "docs/adr/README.md")
        result = detect(tmp_path, which=nothing_installed)
        assert result["mode"] == "adr"
        [log] = result["adr"]
        assert log["dir"] == "docs/adr"
        assert log["count"] == 2
        assert log["next"] == "0003"
        assert log["newest"] == "docs/adr/0002-second.md"
        assert log["index"] == "docs/adr/README.md"

    def test_the_next_number_keeps_the_logs_own_width(self, tmp_path):
        write(tmp_path, "decisions/009-a.md")
        write(tmp_path, "decisions/010-b.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["next"] == "011"
        assert log["index"] is None

    def test_a_decisions_folder_with_no_numbered_record_is_not_a_log(self, tmp_path):
        write(tmp_path, "docs/decisions/notes.md")
        assert detect(tmp_path, which=nothing_installed)["adr"] == []

    def test_vendored_logs_are_not_the_projects(self, tmp_path):
        write(tmp_path, "node_modules/pkg/docs/adr/0001-theirs.md")
        write(tmp_path, ".git/docs/adr/0001-theirs.md")
        assert detect(tmp_path, which=nothing_installed)["adr"] == []

    def test_an_adr_dir_marker_declares_the_log_even_when_empty(self, tmp_path):
        write(tmp_path, ".adr-dir", "architecture/records\n")
        (tmp_path / "architecture/records").mkdir(parents=True)
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["dir"] == "architecture/records"
        assert log["tool"] == "adr-tools"
        assert log["next"] == "0001"

    def test_log4brains_config_declares_its_folder(self, tmp_path):
        write(tmp_path, ".log4brains.yml",
              "project:\n  name: x\n  adrFolder: ./docs/arch\n")
        write(tmp_path, "docs/arch/20240101-use-x.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["dir"] == "docs/arch"
        assert log["tool"] == "log4brains"

    def test_a_declared_log_is_reported_once(self, tmp_path):
        write(tmp_path, ".adr-dir", "doc/adr\n")
        write(tmp_path, "doc/adr/0001-a.md")
        assert len(detect(tmp_path, which=nothing_installed)["adr"]) == 1


class TestSpecFrameworks:
    def test_openspec_spec_kit_and_kiro_are_each_detected(self, tmp_path):
        write(tmp_path, "openspec/config.yaml", "schema: spec-driven\n")
        write(tmp_path, ".specify/memory/constitution.md")
        write(tmp_path, ".kiro/specs/login/requirements.md")
        frameworks = [s["framework"] for s in detect(tmp_path, which=nothing_installed)["specs"]]
        assert frameworks == ["openspec", "spec-kit", "kiro"]

    def test_an_adr_log_beside_a_spec_framework_is_a_combination(self, tmp_path):
        write(tmp_path, "docs/adr/0001-a.md")
        write(tmp_path, "openspec/config.yaml", "schema: spec-driven\n")
        assert detect(tmp_path, which=nothing_installed)["mode"] == "combination"

    def test_a_spec_framework_alone_is_spec_mode(self, tmp_path):
        write(tmp_path, "openspec/config.yaml", "schema: spec-driven\n")
        assert detect(tmp_path, which=nothing_installed)["mode"] == "spec"


class TestInstalledTools:
    def test_a_cli_on_path_without_project_artifacts_is_not_adoption(self, tmp_path):
        result = detect(tmp_path, which=lambda name: f"/bin/{name}")
        assert result["mode"] == "none"
        assert result["clis"]["openspec"] == "/bin/openspec"

    def test_every_known_cli_is_reported(self, tmp_path):
        clis = detect(tmp_path, which=nothing_installed)["clis"]
        assert set(clis) == {"openspec", "specify", "adr", "log4brains"}


class TestTheCommandLine:
    def test_json_output_parses_and_matches_detect(self, tmp_path):
        write(tmp_path, "docs/adr/0001-a.md")
        out = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), "--json"],
                             capture_output=True, text=True, check=True).stdout
        assert json.loads(out)["adr"][0]["dir"] == "docs/adr"
