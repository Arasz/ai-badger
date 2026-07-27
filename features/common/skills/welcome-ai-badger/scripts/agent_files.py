"""Agent file scaffolding for the Scaffolder.

Applies scaffolding.json to write agent discovery files (CLAUDE.md, copilot,
junie, .github/instructions/*) based on each agent's feature directory.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List


# Known non-standard agent file locations that may coexist with the standard ones.
_NONSTANDARD_AGENT_FILES: Dict[str, List[str]] = {
    ".github/copilot-instructions.md": ["COPILOT_INSTRUCTIONS.md"],
}


class AgentFilesMixin:
    """Mixin providing agent file scaffolding methods."""

    def _apply_scaffolding(self, agent_name: str, instructions_doc: str,  # pylint: disable=too-many-statements
                            instr_paths: List[Path], invariants: List[str]) -> None:
        """Apply features/<agent>/scaffolding.json to write agent files."""
        import badger_lib as bl

        scaffolding_path = self.root / "features" / agent_name / "scaffolding.json"
        if not scaffolding_path.is_file():
            self.notes.append(f"no scaffolding.json for agent '{agent_name}' — skipped")
            return

        scaffolding = bl.load_json(scaffolding_path)
        schema = bl.load_json(self.root / "schemas" / "scaffolding.schema.json")
        errors = bl.validate(scaffolding, schema)
        if errors:
            self.notes.append(
                f"scaffolding.json for '{agent_name}' is invalid — skipping: {errors}"
            )
            return

        feature_dir = self.root / "features" / agent_name
        for file_entry in scaffolding["files"]:
            source = feature_dir / file_entry["source"]
            target = self.target / file_entry["target"]
            managed = file_entry.get("managed", True)
            seed_once = file_entry.get("seedOnce", False)
            is_template = file_entry.get("template", False)
            also_target = file_entry.get("alsoTarget")
            aib_copy = file_entry.get("aibCopy")
            instructions_scoped = file_entry.get("instructionsScoped", False)

            if not source.exists():
                self.notes.append(
                    f"scaffolding source '{file_entry['source']}' for '{agent_name}' "
                    f"not found at {source} — skipping"
                )
                continue

            # Determine the body content
            source_of_truth = aib_copy or file_entry["target"]
            if is_template:
                body = self._render_template_file(source, instr_paths, invariants,
                                                  source_of_truth)
            else:
                body = source.read_text(encoding="utf-8")

            # Write source-of-truth copy under .ai-badger/
            if aib_copy:
                (self.aib / aib_copy).write_text(body, encoding="utf-8")

            # Seed-once: skip if target already exists
            if seed_once and target.exists():
                self.notes.append(
                    f"preserved seed-once {file_entry['target']} for '{agent_name}'"
                )
                continue

            # Write the primary target. The header must name the .ai-badger/ copy it is
            # generated from — its own target path is where edits get discarded (F-08).
            content = body
            if managed:
                self._copy_with_header(target, source_of_truth, content)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if is_template:
                    target.write_text(content, encoding="utf-8")
                else:
                    shutil.copyfile(source, target)

            # Write alsoTarget (e.g. .hermes.md alias)
            if also_target:
                also_dest = self.target / also_target
                if managed:
                    self._copy_with_header(also_dest, source_of_truth, content)
                else:
                    also_dest.parent.mkdir(parents=True, exist_ok=True)
                    if is_template:
                        also_dest.write_text(content, encoding="utf-8")
                    else:
                        shutil.copyfile(source, also_dest)

            # Write per-instruction scoped copies (copilot's .github/instructions/)
            if instructions_scoped:
                for p in instr_paths:
                    self._copy_with_header(
                        self.target / ".github" / "instructions" / p.name,
                        f"instructions/{p.name}",
                        p.read_text(encoding="utf-8")
                    )

            self._detect_nonstandard_agent_files(file_entry["target"])

    def _detect_nonstandard_agent_files(self, target_rel: str) -> None:
        """Warn if non-standard equivalents of an agent file exist in the project."""
        for alt in _NONSTANDARD_AGENT_FILES.get(target_rel, []):
            alt_path = self.target / alt
            if alt_path.exists():
                self.notes.append(
                    f"non-standard agent file '{alt}' found — '{target_rel}' was also "
                    "written; consider removing the non-standard file to avoid confusion"
                )

    def write_agent_files(self, instructions_doc: str, instr_paths: List[Path],
                           invariants: List[str]) -> None:
        """Write agent discovery files using scaffolding.json from each agent's feature dir.

        Each agent in config.agents must have a features/<agent>/scaffolding.json that
        declares what files to write. No hardcoded fallback — all agents are data-driven.
        """
        agents = self.config.get("agents", [])
        for agent_name in agents:
            self._apply_scaffolding(agent_name, instructions_doc, instr_paths, invariants)
