"""The project description must state the dependency contract the code actually implements."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap

OVERCLAIM = "every third-party import is guarded and degrades to a note"

# Every file the summary renders into (config.json is the source of truth). A stale copy
# re-publishes whatever was true when it was generated, so the overclaim guard follows each
# copy wherever it exists — the orchestrator regenerates them all at the wave join.
RENDERED_COPIES = (
    "CLAUDE.md",
    ".ai-badger/CLAUDE.md",
    ".github/copilot-instructions.md",
    ".ai-badger/copilot-instructions.md",
    ".hermes.md",
    ".ai-badger/HERMES.md",
    "HERMES.md",
)

# Refuse `import jsonschema` inside the child, whatever is installed, without touching this
# process. `find_spec` returning None is exactly what a machine missing the wheel produces.
BLOCK_JSONSCHEMA = """
import sys
class _Blocked:
    def find_spec(self, name, path=None, target=None):
        if name == "jsonschema" or name.startswith("jsonschema."):
            raise ImportError("no module named 'jsonschema'")
        return None
sys.meta_path.insert(0, _Blocked())
for name in [n for n in sys.modules if n == "jsonschema" or n.startswith("jsonschema.")]:
    del sys.modules[name]
"""


def _summary(root) -> str:
    config = json.loads((root / ".ai-badger" / "config.json").read_text(encoding="utf-8"))
    return config["project"]["summary"]


def _child(root, *bodies: str) -> subprocess.CompletedProcess:
    """Run the bodies in a fresh interpreter with engine/ importable, from the repo root."""
    program = f"import sys; sys.path.insert(0, {str(root / 'engine')!r})\n"
    program += "".join(textwrap.dedent(body) for body in bodies)
    return subprocess.run([sys.executable, "-c", program],
                          cwd=str(root), capture_output=True, text=True, check=False)


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

    def test_the_summary_names_pydantic_for_the_task_plan(self, root):
        """task_plan_model.py and tooling/task_plan_schema.py import it unguarded (S2)."""
        assert "pydantic" in _summary(root).lower()

    def test_the_summary_names_uv_as_the_plan_server_prerequisite(self, root):
        """The server/CLI are PEP 723 scripts; uv is the consumer-side prerequisite (DR2)."""
        summary = _summary(root).lower()

        assert re.search(r"\buv\b", summary), "uv must be named as the plan-server prerequisite"
        assert "prerequisite" in summary

    def test_the_rendered_copies_match_the_source_of_truth(self, root):
        """CLAUDE.md is generated from the summary; a stale copy re-publishes the old claim.

        Only the overclaim is checked here, not staleness: this lane owns config.json and the
        orchestrator regenerates every rendered copy at the wave join.
        """
        for rel in RENDERED_COPIES:
            path = root / rel
            if path.is_file():
                assert OVERCLAIM not in path.read_text(encoding="utf-8"), (
                    f"{rel} re-publishes the overclaim")


class TestTheContractIsWhatTheDocsSay:
    """Pin the actual behaviour so the docs and the code cannot drift apart again."""

    def test_validation_refuses_when_jsonschema_is_absent(self, root):
        """A hard dependency by decision: validation that silently no-ops is worse.

        Rewrite of test_jsonschema_is_imported_unguarded, which asserted on the source text
        and so could only be satisfied by a top-level import. The contract is the refusal.
        """
        proc = _child(root, BLOCK_JSONSCHEMA, """
            import badger_lib as bl
            try:
                errors = bl.validate({"a": 1}, {"type": "string"})
            except ImportError:
                print("REFUSED")
            else:
                print("PASSED SILENTLY", errors)
            """)

        assert "REFUSED" in proc.stdout, proc.stdout + proc.stderr

    def test_every_validation_entry_point_refuses_together(self, root):
        """One lazy import behind three functions; a guard on only one is the drift to catch."""
        proc = _child(root, BLOCK_JSONSCHEMA, """
            from pathlib import Path
            import badger_lib as bl
            calls = {
                "validate": lambda: bl.validate({}, {}),
                "validate_file": lambda: bl.validate_file(
                    Path("schemas/index.schema.json"), Path("schemas/index.schema.json")),
                "check_schemas_selfvalid": lambda: bl.check_schemas_selfvalid(Path("schemas")),
            }
            for name, call in calls.items():
                try:
                    call()
                except ImportError:
                    print(f"{name}=REFUSED")
                except Exception as exc:  # noqa: BLE001 - any other failure is not a refusal
                    print(f"{name}=OTHER:{type(exc).__name__}")
                else:
                    print(f"{name}=PASSED_SILENTLY")
            """)

        assert proc.stdout.split() == ["validate=REFUSED", "validate_file=REFUSED",
                                       "check_schemas_selfvalid=REFUSED"], (
                proc.stdout + proc.stderr)

    def test_importing_badger_lib_does_not_pay_for_jsonschema(self, root):
        """11 of 13 entry points never validate; they must not import the validator (D1)."""
        proc = _child(root, """
            import sys
            import badger_lib  # noqa: F401
            print("LOADED" if "jsonschema" in sys.modules else "NOT_LOADED")
            """)

        assert proc.stdout.strip() == "NOT_LOADED", proc.stdout + proc.stderr

    def test_the_runtime_dependencies_are_declared_in_requirements(self, root):
        requirements = (root / "engine" / "requirements.txt").read_text(encoding="utf-8").lower()

        assert "jsonschema" in requirements
        assert "pyyaml" in requirements
        assert "pydantic" in requirements

    def test_pyyaml_really_does_degrade_to_a_note(self, load_script):
        """The half of the original claim that is true must stay true."""
        mcp_index = load_script("features/common/skills/mcp-index/scripts/mcp_index.py")

        assert "pyyaml" in mcp_index.YAML_MISSING_HINT.lower()