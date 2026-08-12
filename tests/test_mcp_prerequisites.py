"""A declared MCP server names what must already be installed for it to launch.

ai-badger writes launch config for a server with `declare: true`. When the thing that
serves it is not on the machine, that config fails at runtime with the agent's own error,
which says nothing about ai-badger having written it or about what to install. The Aspire
MCP server ships with the Aspire CLI; code-review-graph is a Python distribution. Neither
fact was recorded anywhere, so neither reached the person who had to act on it.

`prerequisite` in meta.json is a property of the server, which is why it lives there
rather than in one stack's declaration — the same reasoning the schema already gives for
`package`.
"""
from __future__ import annotations

import json
import sys

import pytest

CATALOG_META = "meta.json"
SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"


def _load_mcp_tools(load_script, root):
    """Load mcp_tools with the sibling modules its own bootstrap puts on sys.path."""
    for entry in (str(root / SCRIPTS), str(root / "engine"), str(root / "tooling")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/mcp_tools.py")


def _bare_collaborator(mcp_tools):
    """An McpTools with only the context fields note_declared_prerequisites touches."""
    collaborator = mcp_tools.McpTools.__new__(mcp_tools.McpTools)
    collaborator.ctx = type("Ctx", (), {"mcp_prereqs_noted": False, "notes": []})()
    return collaborator


def _meta(root, stack, server):
    path = root / "features" / stack / "mcp" / server / CATALOG_META
    return json.loads(path.read_text(encoding="utf-8"))


class TestCatalogDeclaresPrerequisites:
    """The two servers that need something installed say so."""

    def test_aspire_names_the_cli_it_ships_with(self, root):
        meta = _meta(root, "aspire", "aspire")

        assert meta["prerequisite"]["summary"]
        assert "aspire.dev" in meta["prerequisite"]["install"]

    def test_code_review_graph_names_its_prerequisite(self, root):
        meta = _meta(root, "common", "code-review-graph")

        assert meta["prerequisite"]["summary"]

    def test_a_prerequisite_carries_a_check_command(self, root):
        """A summary tells you what is missing; a check tells you whether it is."""
        for stack, server in (("aspire", "aspire"), ("common", "code-review-graph")):
            assert _meta(root, stack, server)["prerequisite"]["check"]

    def test_every_declared_server_declares_a_prerequisite_or_none(self, root):
        """Declared means ai-badger writes launch config, so silence here is a runtime failure.

        A server needing nothing installed is fine — it just has to say so, rather than
        leaving a reader unable to tell "nothing needed" from "nobody wrote it down".
        """
        missing = []
        for stack_dir in (root / "features").iterdir():
            decl = stack_dir / "stack-mcp.json"
            if not decl.is_file():
                continue
            for srv in json.loads(decl.read_text(encoding="utf-8")).get("servers", []):
                if not srv.get("declare"):
                    continue
                meta_path = stack_dir / "mcp" / srv["name"] / CATALOG_META
                if not meta_path.is_file():
                    continue
                if "prerequisite" not in json.loads(meta_path.read_text(encoding="utf-8")):
                    missing.append(f"{stack_dir.name}/{srv['name']}")

        assert not missing, f"declared servers with no prerequisite recorded: {missing}"


class TestSchemaAcceptsAndBoundsIt:
    """The schema is additionalProperties:false, so the field has to be declared to exist."""

    def test_the_schema_declares_prerequisite(self, root):
        schema = json.loads(
            (root / "schemas" / "mcp-server.schema.json").read_text(encoding="utf-8")
        )

        assert "prerequisite" in schema["properties"]

    def test_a_prerequisite_must_carry_a_summary(self, root):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(
            (root / "schemas" / "mcp-server.schema.json").read_text(encoding="utf-8")
        )

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"name": "x", "prerequisite": {"check": "x --version"}}, schema
            )

    def test_an_unknown_prerequisite_key_is_refused(self, root):
        """Bounded like every other object here: a typo must fail, not be ignored."""
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(
            (root / "schemas" / "mcp-server.schema.json").read_text(encoding="utf-8")
        )

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"name": "x", "prerequisite": {"summary": "s", "instal": "typo"}}, schema
            )

    def test_the_real_catalog_metas_validate(self, root):
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(
            (root / "schemas" / "mcp-server.schema.json").read_text(encoding="utf-8")
        )

        for stack, server in (("aspire", "aspire"), ("common", "code-review-graph")):
            jsonschema.validate(_meta(root, stack, server), schema)


class TestTheScaffoldReportsIt:
    """Recording a prerequisite is only useful if it reaches the person who has to act."""

    def test_a_declared_servers_prerequisite_is_reported(self, make_scaffolder):
        scaf = make_scaffolder(install=True)
        scaf.run(generated_at="2026-08-01T00:00:00Z")

        notes = "\n".join(scaf.ctx.notes)
        assert "code-review-graph" in notes and "prerequisite" in notes.lower()

    def test_the_report_names_the_check_command(self, make_scaffolder):
        """A note saying something is needed, without saying how to test for it, is a shrug."""
        scaf = make_scaffolder(install=True)
        scaf.run(generated_at="2026-08-01T00:00:00Z")

        assert any("check.py" in n for n in scaf.ctx.notes)

    def test_the_report_names_where_to_get_it(self, make_scaffolder):
        scaf = make_scaffolder(install=True)
        scaf.run(generated_at="2026-08-01T00:00:00Z")

        assert any("install.py" in n for n in scaf.ctx.notes)


class TestABadCatalogEntryDoesNotCrashTheScaffold:
    """meta.json is validated by a schema, but nothing validates it *at scaffold time*.

    A hand-edited catalog entry, a half-written file, or a `prerequisite` block missing its
    required `summary` must not take the whole scaffold down. Reported by review on PR #252.
    """

    def test_a_prerequisite_without_a_summary_is_skipped_not_raised(
        self, load_script, root, monkeypatch
    ):
        collaborator = _bare_collaborator(_load_mcp_tools(load_script, root))
        monkeypatch.setattr(
            collaborator, "_server_prerequisite", lambda _n: {"check": "x --version"}
        )

        collaborator.note_declared_prerequisites(["half-written"])

        assert collaborator.ctx.notes == []

    def test_a_summary_that_is_present_still_reports(self, load_script, root, monkeypatch):
        """The skip must be narrow — a good entry still has to produce its note."""
        collaborator = _bare_collaborator(_load_mcp_tools(load_script, root))
        monkeypatch.setattr(
            collaborator, "_server_prerequisite", lambda _n: {"summary": "the thing"}
        )

        collaborator.note_declared_prerequisites(["good"])

        assert any("the thing" in n for n in collaborator.ctx.notes)


class TestTheCatalogGateHasNoHole:
    """The invariant test skipped a declared server with no meta.json at all — the worst case
    it claims to cover. Reported by review on PR #252."""

    def test_a_declared_server_must_have_a_catalog_entry(self, root):
        missing = []
        for stack_dir in (root / "features").iterdir():
            decl = stack_dir / "stack-mcp.json"
            if not decl.is_file():
                continue
            for srv in json.loads(decl.read_text(encoding="utf-8")).get("servers", []):
                if not srv.get("declare"):
                    continue
                if not (stack_dir / "mcp" / srv["name"] / CATALOG_META).is_file():
                    missing.append(f"{stack_dir.name}/{srv['name']}")

        assert not missing, f"declared servers with no catalog meta.json: {missing}"
