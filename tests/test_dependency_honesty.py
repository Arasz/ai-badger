"""The project description must state the dependency contract the code actually implements."""
from __future__ import annotations

import json

OVERCLAIM = "every third-party import is guarded and degrades to a note"


def _summary(root) -> str:
    config = json.loads((root / ".ai-badger" / "config.json").read_text(encoding="utf-8"))
    return config["project"]["summary"]


class TestTheProjectDescriptionIsTrue:
    """This summary renders into CLAUDE.md for every consumer, so an overclaim travels far."""

    def test_the_summary_does_not_claim_every_import_degrades(self, root):
        assert OVERCLAIM not in _summary(root), (
            "jsonschema is a hard requirement — engine/badger_lib.py imports it unguarded. "
            "Only pyyaml degrades to a note. Describe what the code does."
        )

    def test_the_summary_names_jsonschema_as_required(self, root):
        summary = _summary(root).lower()

        assert "jsonschema" in summary and "required" in summary

    def test_the_rendered_copies_match_the_source_of_truth(self, root):
        """CLAUDE.md is generated from the summary; a stale copy re-publishes the old claim."""
        assert OVERCLAIM not in (root / "CLAUDE.md").read_text(encoding="utf-8")
        assert OVERCLAIM not in (root / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8")


class TestTheContractIsWhatTheDocsSay:
    """Pin the actual behaviour so the docs and the code cannot drift apart again."""

    def test_jsonschema_is_imported_unguarded(self, root):
        """A hard dependency by decision: validation that silently no-ops is worse."""
        source = (root / "engine" / "badger_lib.py").read_text(encoding="utf-8")

        assert "\nimport jsonschema" in source

    def test_both_dependencies_are_declared_in_requirements(self, root):
        requirements = (root / "engine" / "requirements.txt").read_text(encoding="utf-8").lower()

        assert "jsonschema" in requirements and "pyyaml" in requirements

    def test_pyyaml_really_does_degrade_to_a_note(self, load_script):
        """The half of the original claim that is true must stay true."""
        mcp_index = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

        assert "pyyaml" in mcp_index.YAML_MISSING_HINT.lower()
