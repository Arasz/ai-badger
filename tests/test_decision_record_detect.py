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


class TestReviewFindings:
    def test_an_adr_dir_outside_the_project_is_refused_with_a_warning(self, tmp_path):
        root = tmp_path / "repo"
        write(tmp_path, "out/0001-a.md")
        write(root, ".adr-dir", "../out\n")
        result = detect(root, which=nothing_installed)
        assert result["adr"] == []
        assert any(".adr-dir" in w for w in result["warnings"])

    def test_an_absolute_adr_dir_inside_the_project_is_made_relative(self, tmp_path):
        write(tmp_path, "arch/0001-a.md")
        write(tmp_path, ".adr-dir", f"{tmp_path.resolve() / 'arch'}\n")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["dir"] == "arch"

    def test_an_unreadable_marker_is_a_warning_not_a_crash(self, tmp_path):
        _test_write(tmp_path / ".adr-dir", b"\xff\xfe\x00bad")
        result = detect(tmp_path, which=nothing_installed)
        assert result["warnings"]

    def test_a_dated_log_reports_no_next_number(self, tmp_path):
        write(tmp_path, ".log4brains.yml", "project:\n  adrFolder: ./docs/arch\n")
        write(tmp_path, "docs/arch/20240101-use-x.md")
        write(tmp_path, "docs/arch/20240315-use-y.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["naming"] == "date"
        assert log["next"] is None

    def test_a_dashed_date_record_is_not_read_as_number_2024(self, tmp_path):
        write(tmp_path, "docs/adr/0001-a.md")
        write(tmp_path, "docs/adr/2024-01-01-b.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["naming"] == "date"
        assert log["next"] is None

    def test_a_sequenced_log_says_so(self, tmp_path):
        write(tmp_path, "docs/adr/0001-a.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["naming"] == "sequence"

    def test_a_symlinked_log_is_found(self, tmp_path):
        root = tmp_path / "repo"
        write(tmp_path, "elsewhere/adr/0001-a.md")
        (root / "docs").mkdir(parents=True)
        (root / "docs/adr").symlink_to(tmp_path / "elsewhere/adr", target_is_directory=True)
        assert [log["dir"] for log in detect(root, which=nothing_installed)["adr"]] == ["docs/adr"]

    def test_a_symlink_loop_terminates(self, tmp_path):
        write(tmp_path, "docs/adr/0001-a.md")
        (tmp_path / "docs/loop").symlink_to(tmp_path / "docs", target_is_directory=True)
        assert len(detect(tmp_path, which=nothing_installed)["adr"]) == 1

    def test_a_declared_path_is_normalised_before_dedup(self, tmp_path):
        write(tmp_path, ".adr-dir", "./doc/../doc/adr\n")
        write(tmp_path, "doc/adr/0001-a.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["dir"] == "doc/adr"

    def test_a_github_folder_log_is_found_but_framework_state_is_not(self, tmp_path):
        write(tmp_path, ".github/decisions/0001-a.md")
        write(tmp_path, ".ai-badger/worktrees/x/docs/adr/0001-copy.md")
        dirs = [log["dir"] for log in detect(tmp_path, which=nothing_installed)["adr"]]
        assert dirs == [".github/decisions"]

    def test_a_log_below_the_depth_limit_is_not_searched(self, tmp_path):
        write(tmp_path, "a/b/c/d/adr/0001-deep.md")
        assert detect(tmp_path, which=nothing_installed)["adr"] == []

    def test_doc_adr_without_a_marker_is_adr_tools(self, tmp_path):
        write(tmp_path, "doc/adr/0001-a.md")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["tool"] == "adr-tools"

    def test_openspec_is_detected_from_its_specs_folder_alone(self, tmp_path):
        (tmp_path / "openspec/specs").mkdir(parents=True)
        assert detect(tmp_path, which=nothing_installed)["specs"] == [
            {"framework": "openspec", "dir": "openspec"}]

    def test_files_that_only_look_numbered_are_not_records(self, tmp_path):
        write(tmp_path, "docs/adr/1-notes.md")
        write(tmp_path, "docs/adr/0001-a.txt")
        assert detect(tmp_path, which=nothing_installed)["adr"] == []

    def test_a_declared_folder_that_does_not_exist_yet_is_still_the_log(self, tmp_path):
        write(tmp_path, ".adr-dir", "architecture/records\n")
        [log] = detect(tmp_path, which=nothing_installed)["adr"]
        assert log["dir"] == "architecture/records"
        assert log["count"] == 0

    def test_text_output_names_the_log_and_its_next_number(self, tmp_path):
        write(tmp_path, "docs/adr/0001-a.md")
        out = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)],
                             capture_output=True, text=True, check=True).stdout
        assert "mode: adr" in out
        assert "adr: docs/adr (unknown, 1 records, next 0002)" in out
