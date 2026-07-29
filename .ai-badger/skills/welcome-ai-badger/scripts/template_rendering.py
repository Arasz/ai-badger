"""Template rendering, one of the scaffold's collaborators.

Computes document slots for CLAUDE.md/HERMES.md templates, renders template
files, and assembles agent discovery documents.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from scaffold_context import ScaffoldContext


class TemplateRendering:
    """Computes the document slots and renders the templates every agent file is made of."""

    def __init__(self, ctx: ScaffoldContext):
        self.ctx = ctx

    @staticmethod
    def _render_instruction_blocks(entries: list) -> str:
        """Join each entry's `instructions` into one slot value, or '' when none has any."""
        blocks = [instr for instr in
                  ((e.get("instructions") or "").strip() for e in entries) if instr]
        return "\n\n".join(blocks) + "\n\n" if blocks else ""

    def _mcp_instruction_slots(self) -> tuple:
        """`(MCP_INSTRUCTIONS, EXTERNAL_MCP_INSTRUCTIONS)` — one server, one block, one source.

        Precedence: the project's own `config.externalTools` entry wins, then the mcp catalog,
        then the legacy `external-tools.json` (ADR-0014). The two slots sit adjacent in the
        templates, so which of them carries a block never moves a byte.
        """
        user_named = {t.get("name") for t in self.ctx.config.get("externalTools") or []}
        catalog = [s for s in self.ctx.mcp_described if s.get("name") not in user_named]
        covered = {s.get("name") for s in catalog}
        legacy = [t for t in self.ctx.merged_external_tools if t.get("name") not in covered]
        return (self._render_instruction_blocks(catalog),
                self._render_instruction_blocks(legacy))

    def compute_doc_slots(self, invariants: List[str], instr_paths: List[Path],
                            source_of_truth: str = "CLAUDE.md") -> Dict[str, str]:
        """Compute the template slots shared by CLAUDE.md and HERMES.md assembly.

        `source_of_truth` is the .ai-badger/ file this render is the copy of — every agent
        renders the same template, so the self-reference cannot be hardcoded (F-08).
        """
        project = self.ctx.config.get("project", {})
        commands = self.ctx.config.get("commands", {})
        routing = self.ctx.config.get("personaRouting", [])

        inv_md = "\n\n".join(invariants) if invariants else "_None yet._"
        cmd_md = "\n".join(f"- `{k}`: `{v}`" for k, v in commands.items()) or "_None configured._"
        route_md = "\n".join(f"- {r['work']} → `{r['agent']}`" for r in routing) or (
            "_None configured — work is not dispatched to a persona. Add entries to "
            "`personaRouting` in `.ai-badger/config.json` to route it._"
        )
        instr_md = "\n".join(
            f"- `{p.name}` → `.ai-badger/instructions/{p.name}`" for p in instr_paths
        ) or "_None._"
        mcp_md, ext_mcp_md = self._mcp_instruction_slots()
        return {
            "PROJECT_NAME": project.get("name", ""),
            "PROJECT_SUMMARY": project.get("summary", ""),
            "PROJECT_DOMAIN": project.get("domain", ""),
            "STACKS": ", ".join(self.ctx.config.get("stacks", [])),
            "INVARIANTS": inv_md,
            "COMMANDS": cmd_md,
            "PERSONA_ROUTING": route_md,
            "PATH_INSTRUCTIONS": instr_md,
            "MCP_INSTRUCTIONS": mcp_md,
            "EXTERNAL_MCP_INSTRUCTIONS": ext_mcp_md,
            "FRAMEWORK_VERSION": self.ctx.index["frameworkVersion"],
            "SOURCE_OF_TRUTH": source_of_truth,
        }

    def _render_template(self, tmpl_name: str, slots: Dict[str, str]) -> str:
        """Render a template file from features/common/templates/ with the given slots."""
        tmpl_path = self.ctx.root / "features" / "common" / "templates" / tmpl_name
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
                                     self.compute_doc_slots(invariants, instr_paths))

    def assemble_hermes_doc(self, invariants: List[str], instr_paths: List[Path]) -> str:
        """Render the HERMES.md.tmpl template with this config's project/commands/invariants."""
        return self._render_template(
            "HERMES.md.tmpl",
            self.compute_doc_slots(invariants, instr_paths, source_of_truth="HERMES.md"))

    # -- agent-discovery copies -----------------------------------------------------

    def render_template_file(self, source: Path, instr_paths: List[Path],
                               invariants: List[str], source_of_truth: str = "CLAUDE.md") -> str:
        """Render a .tmpl file with the standard scaffold slots."""
        tmpl = source.read_text(encoding="utf-8")
        slots = self.compute_doc_slots(invariants, instr_paths, source_of_truth)
        for k, v in slots.items():
            tmpl = tmpl.replace("{{" + k + "}}", str(v))
        return tmpl

    def carried_body(self, dest: Path, body: str) -> Optional[str]:
        """`body` plus dest's preserved regions, or None when dest's markers are malformed."""
        from _shared import carry_keep_regions, MalformedKeepRegion  # pylint: disable=import-outside-toplevel

        if not dest.exists():
            return body
        rel = dest.relative_to(self.ctx.target).as_posix()
        try:
            carried = carry_keep_regions(dest.read_text(encoding="utf-8", errors="ignore"), body)
        except MalformedKeepRegion as exc:
            self.ctx.notes.append(
                f"{rel} left untouched — {exc}; fix the markers and re-run to refresh it"
            )
            return None
        if carried != body:
            self.ctx.notes.append(f"carried preserved regions into {rel}")
        return carried

    def copy_with_header(self, dest: Path, name: str, body: str) -> None:
        """Write body to dest with managed header, preserving hand-authored files."""
        from _shared import _MANAGED_PREFIX, MANAGED_HEADER  # pylint: disable=import-outside-toplevel

        if (not self.ctx.overwrite and dest.exists()
                and not dest.read_text(encoding="utf-8",
                                       errors="ignore").lstrip().startswith(_MANAGED_PREFIX)):
            self.ctx.notes.append(
                f"preserved hand-authored {dest.relative_to(self.ctx.target).as_posix()} "
                "(source written to .ai-badger/; pass --overwrite-agent-files to replace)"
            )
            return
        carried = self.carried_body(dest, body)
        if carried is None:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(MANAGED_HEADER.format(name=name) + carried, encoding="utf-8")
