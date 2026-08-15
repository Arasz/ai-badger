"""The ai-raccoon stack: developing the AiRaccoon server itself.

Detection is by filename only. What identifies the AiRaccoon repo is its own solution and
project file; `stack.schema.json` is explicit that content facts belong in `detect.py`'s
dependency pass rather than in a glob signal.

The checklist template assertions below exist because the two predecessor checklists rotted in
exactly these ways. Each defence is prose in SKILL.md and a check here, so a later "tidy-up"
that drops one goes red instead of going unnoticed.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from conftest import _test_write

ROOT = Path(__file__).resolve().parents[1]
DETECT = "features/common/skills/welcome-ai-badger/scripts/detect.py"
SKILL = ROOT / "features/ai-raccoon/skills/ai-raccoon-manual-checklist"
DERIVE = SKILL / "scripts/derive-facts.sh"


def _real_index():
    return json.loads((ROOT / "index.json").read_text(encoding="utf-8"))


def _template():
    return json.loads((SKILL / "templates/checklist-template.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", ["AiRaccoon.slnx", "AiRaccoon.csproj"])
def test_the_airaccoon_solution_marks_a_repository_as_ai_raccoon(tmp_path, load_script, filename):
    detect = load_script(DETECT)
    _test_write(tmp_path / filename, "x", encoding="utf-8")

    assert "ai-raccoon" in detect.detect_stacks(tmp_path, _real_index())


def test_a_dotnet_repository_is_not_ai_raccoon(tmp_path, load_script):
    """The stack is for building AiRaccoon; firing on every .NET repo would ship a checklist
    full of steps for a product that project does not have."""
    detect = load_script(DETECT)
    _test_write(tmp_path / "MyApp.csproj", "x", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, _real_index())

    assert "dotnet" in stacks
    assert "ai-raccoon" not in stacks


def test_ai_raccoon_implies_dotnet_and_mcp(load_script):
    """AiRaccoon is a .NET MCP server; scaffolding it alone would miss both."""
    detect = load_script(DETECT)

    closure = detect.expand_requires(["ai-raccoon"], _real_index())

    assert "dotnet" in closure
    assert "mcp" in closure


def test_the_catalog_indexes_the_checklist_under_the_ai_raccoon_stack():
    stack = _real_index()["stacks"]["ai-raccoon"]

    assert [s["name"] for s in stack["skills"]] == ["ai-raccoon-manual-checklist"]


class TestTheSkillCarriesWhatRunningItTaught:
    """Each of these was a defect found by executing the checklist against a live 1.19.1 build,
    not by reading it. Losing any of them means re-learning it the same way."""

    def _body(self):
        return (SKILL / "SKILL.md").read_text(encoding="utf-8")

    def test_it_says_a_filter_test_needs_a_negative_control(self):
        assert "negative control" in self._body()

    def test_it_says_a_retrieval_query_must_defeat_keyword_match(self):
        body = self._body()

        assert "BM25" in body
        assert "keyword match cannot carry" in body

    def test_it_says_an_empty_list_proves_nothing(self):
        assert "An empty list is a weak check" in self._body()

    def test_it_forbids_inheriting_a_prior_verdicts_reason(self):
        """A reason right about the outcome and wrong about the cause survived a release."""
        assert "Never inherit a prior verdict's reason" in self._body()

    def test_it_names_every_root_a_stale_copy_can_load_from(self):
        """The deletion that retired the predecessors missed the Hermes skill root, and that
        copy was the first hit for the next person who searched."""
        body = self._body()

        for root in (".ai-badger/skills/learned/", ".claude/skills/",
                     "~/.claude/skills/", "~/.hermes/skills/"):
            assert root in body, root

    def test_it_names_the_data_root_as_the_isolation_axis(self):
        """Lanes parallelise safely; the skill read as if it had to be worked serially."""
        body = self._body()

        assert "parallel" in body
        assert "--data-root" in body


class TestTheDerivationScriptFailsLoudly:
    """Defence against the first rot: facts pinned by hand. A derivation that silently
    reports 0 is worse than one that pins a stale number, because 0 looks derived."""

    def _run(self, tree):
        return subprocess.run([str(DERIVE), str(tree)], capture_output=True, text=True, check=False)

    def _fake_tree(self, tmp_path, tool_source, prompt_source):
        src = tmp_path / "src/AiRaccoon"
        (src / "Tools").mkdir(parents=True, exist_ok=True)
        (src / "Prompts").mkdir(parents=True, exist_ok=True)
        _test_write(src / "AiRaccoon.csproj",
                    "<Project><PropertyGroup><PackageVersion>9.9.9</PackageVersion>"
                    "</PropertyGroup></Project>", encoding="utf-8")
        _test_write(src / "Tools/Tools.cs", tool_source, encoding="utf-8")
        _test_write(src / "Prompts/Prompts.cs", prompt_source, encoding="utf-8")
        return tmp_path

    def test_it_derives_the_version_and_the_counts(self, tmp_path):
        tree = self._fake_tree(tmp_path, "[McpServerTool] a; [McpServerTool] b;",
                               "[McpServerPrompt] c;")

        result = self._run(tree)

        assert result.returncode == 0, result.stderr
        assert "version=9.9.9" in result.stdout
        assert "mcp-tool-count=2" in result.stdout
        assert "mcp-prompt-count=1" in result.stdout

    def test_a_missing_tree_fails_instead_of_reporting_nothing(self, tmp_path):
        result = self._run(tmp_path / "nowhere")

        assert result.returncode != 0
        assert "no csproj" in result.stderr

    def test_a_tree_with_no_tools_fails_instead_of_reporting_zero(self, tmp_path):
        """The trap the old awk pipeline fell into: a moved path summed to a confident 0."""
        tree = self._fake_tree(tmp_path, "public class Nothing { }", "[McpServerPrompt] c;")

        result = self._run(tree)

        assert result.returncode != 0
        assert "zero [McpServerTool]" in result.stderr


class TestTheTemplateKeepsItsAntiRotDefences:

    def test_no_item_pins_a_version_or_a_tool_count(self):
        """Second rot: pinned facts. The template compares against `derived`, never a literal."""
        derived = _template()["derived"]

        assert all(value == "" for key, value in derived.items() if key != "note")

    def test_every_item_has_room_for_the_command_and_the_output(self):
        """Third rot: no evidence field made a filled checklist and an invented one identical."""
        for item in _template()["items"]:
            assert "command" in item, item["item"]
            assert "evidence" in item, item["item"]

    def test_accepted_starts_unanswered_rather_than_false(self):
        """Fourth rot: a boolean default cannot distinguish 'not answered' from 'not accepted',
        so an unfilled run reads as a run with no objections."""
        for item in _template()["items"]:
            assert item["accepted"] is None, item["item"]

    def test_status_is_a_field_that_can_express_a_skip(self):
        """Fifth rot: checked/accepted booleans collapsed pass, fail and skipped into two states."""
        for item in _template()["items"]:
            assert item["status"] == "", item["item"]
            assert "acceptance-reason" in item, item["item"]

    def test_the_template_ships_beside_the_skill_that_points_at_it(self):
        """Sixth rot: a copy that lost its templates/ directory left step 1 pointing at nothing."""
        assert (SKILL / "templates/checklist-template.json").is_file()
        assert "templates/checklist-template.json" in (SKILL / "SKILL.md").read_text(encoding="utf-8")

    def test_a_run_can_report_that_an_earlier_run_was_wrong(self):
        """Found by running it: three of the most valuable outputs of a live run were about prior
        runs being wrong, and the template had nowhere to put them."""
        template = _template()

        assert "findings-against-prior-runs" in template
        for field in ("prior-claim", "what-is-actually-true", "evidence"):
            assert field in template["findings-against-prior-runs"][0], field

    def test_status_can_express_a_substitution(self):
        """Checked-by-another-instrument is neither pass nor skipped; folding it into either
        one misreports the run."""
        note = _template()["_note"]

        assert "substituted" in note
        assert "pass|fail|skipped|substituted" in note

    def test_results_never_land_in_a_bank_directory(self):
        """Seventh rot: reports written into .ai-raccoon/, which is where banks live."""
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")

        assert "docs/work/checklist/" in body
        assert ".ai-raccoon/" in body  # named explicitly as the place results must not go
