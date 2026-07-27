"""Template rendering for the Scaffolder.

Computes document slots for CLAUDE.md/HERMES.md templates, renders template
files, and assembles agent discovery documents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


class TemplateRenderingMixin:
    """Mixin providing template rendering and doc assembly methods."""

    @staticmethod
    def _render_external_mcp_instructions(external_tools: list) -> str:
        """Render externalTools instructions blocks from config."""
        if not external_tools:
            return ""
        blocks = []
        for tool in external_tools:
            instr = tool.get("instructions", "").strip()
            if instr:
                blocks.append(instr)
        return "\n\n".join(blocks) + "\n\n" if blocks else ""

    def _compute_doc_slots(self, invariants: List[str], instr_paths: List[Path],
                            source_of_truth: str = "CLAUDE.md") -> Dict[str, str]:
        """Compute the template slots shared by CLAUDE.md and HERMES.md assembly.

        `source_of_truth` is the .ai-badger/ file this render is the copy of — every agent
        renders the same template, so the self-reference cannot be hardcoded (F-08).
        """
        project = self.config.get("project", {})
        commands = self.config.get("commands", {})
        routing = self.config.get("personaRouting", [])

        inv_md = "\n\n".join(invariants) if invariants else "_None yet._"
        cmd_md = "\n".join(f"- `{k}`: `{v}`" for k, v in commands.items()) or "_None configured._"
        route_md = (
            "\n".join(f"- {r['work']} → `{r['agent']}`" for r in routing) or "_Default routing._"
        )
        instr_md = "\n".join(
            f"- `{p.name}` → `.ai-badger/instructions/{p.name}`" for p in instr_paths
        ) or "_None._"
        ext_mcp_md = self._render_external_mcp_instructions(
            self._merged_external_tools
        )
        return {
            "PROJECT_NAME": project.get("name", ""),
            "PROJECT_SUMMARY": project.get("summary", ""),
            "PROJECT_DOMAIN": project.get("domain", ""),
            "STACKS": ", ".join(self.config.get("stacks", [])),
            "INVARIANTS": inv_md,
            "COMMANDS": cmd_md,
            "PERSONA_ROUTING": route_md,
            "PATH_INSTRUCTIONS": instr_md,
            "EXTERNAL_MCP_INSTRUCTIONS": ext_mcp_md,
            "FRAMEWORK_VERSION": self.index["frameworkVersion"],
            "SOURCE_OF_TRUTH": source_of_truth,
        }

    def _render_template(self, tmpl_name: str, slots: Dict[str, str]) -> str:
        """Render a template file from features/common/templates/ with the given slots."""
        tmpl_path = self.root / "features" / "common" / "templates" / tmpl_name
        if tmpl_path.exists():
            doc = tmpl_path.read_text(encoding="utf-8")
            for k, v in slots.items():
                doc = doc.replace("{{" + k + "}}", str(v))
            return doc
        # fallback minimal doc if template missing
        return (f"# {slots['PROJECT_NAME']}\n\n{slots['PROJECT_SUMMARY']}\n\n"
                f"## Invariants\n\n{slots['INVARIANTS']}\n\n## Commands\n\n{slots['COMMANDS']}\n")

    def assemble_instructions_doc(self, invariants: List[str], instr_paths: List[Path]) -> str:
        """Render the CLAUDE.md.tmpl template with this config's project/commands/invariants."""
        return self._render_template("CLAUDE.md.tmpl",
                                     self._compute_doc_slots(invariants, instr_paths))

    def assemble_hermes_doc(self, invariants: List[str], instr_paths: List[Path]) -> str:
        """Render the HERMES.md.tmpl template with this config's project/commands/invariants."""
        return self._render_template(
            "HERMES.md.tmpl",
            self._compute_doc_slots(invariants, instr_paths, source_of_truth="HERMES.md"))

    # -- agent-discovery copies -----------------------------------------------------

    def _render_template_file(self, source: Path, instr_paths: List[Path],
                               invariants: List[str], source_of_truth: str = "CLAUDE.md") -> str:
        """Render a .tmpl file with the standard scaffold slots."""
        tmpl = source.read_text(encoding="utf-8")
        slots = self._compute_doc_slots(invariants, instr_paths, source_of_truth)
        for k, v in slots.items():
            tmpl = tmpl.replace("{{" + k + "}}", str(v))
        return tmpl

    def _copy_with_header(self, dest: Path, name: str, body: str) -> None:
        """Write body to dest with managed header, preserving hand-authored files."""
        from _shared import _MANAGED_PREFIX, MANAGED_HEADER  # pylint: disable=import-outside-toplevel

        if (not self.overwrite and dest.exists()
                and not dest.read_text(encoding="utf-8",
                                       errors="ignore").lstrip().startswith(_MANAGED_PREFIX)):
            self.notes.append(
                f"preserved hand-authored {dest.relative_to(self.target).as_posix()} "
                "(source written to .ai-badger/; pass --overwrite-agent-files to replace)"
            )
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(MANAGED_HEADER.format(name=name) + body, encoding="utf-8")
