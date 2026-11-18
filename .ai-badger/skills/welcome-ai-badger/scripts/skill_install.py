"""Skill installation, one of the scaffold's collaborators.

Resolves the per-agent install commands, copies each stack's skill source files into
.ai-badger/skills-data/, and runs the commands when the scaffold was asked to execute.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import List

from scaffold_context import ScaffoldContext


class SkillInstall:
    """Generates, records and optionally runs the skill installation commands."""

    def __init__(self, ctx: ScaffoldContext, install: bool, execute: bool):
        self.ctx = ctx
        self.install = install
        self.execute = execute

    def run(self) -> List[str]:
        """Return the install commands; copy the stacks' skill sources and run them on --execute."""
        import install_plugins as ip_lib  # pylint: disable=import-outside-toplevel
        ctx = self.ctx
        result = ip_lib.install_skills(ctx.root, ctx.config, dry_run=not self.install)

        for stack in ctx.stacks:
            for fname in ("skills-source.json", "skills.json"):
                src = ctx.root / "features" / stack / fname
                if src.exists():
                    dest_dir = ctx.aib / "skills-data" / stack
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / fname
                    shutil.copyfile(src, dest)
                    ctx.record("skills", stack, f"{stack}/{fname}", src, dest)

        cmds = result["commands"]
        if self.execute and cmds:
            for cmd in cmds:
                ctx.notes.append(self._execute(ip_lib, cmd))
        elif self.install and cmds:
            ctx.notes.append("skill auto-install requested but deferred to report "
                             "(run the commands below manually or via --execute)")
        for warning in result.get("warnings", []):
            ctx.notes.append(f"skill install warning: {warning}")
        return cmds

    def _execute(self, ip_lib, cmd) -> str:
        """Run one command with a 30 s limit and return the note describing its outcome."""
        shown = ip_lib.printable(cmd)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                  cwd=str(self.ctx.target), check=False)
        except subprocess.TimeoutExpired:
            return f"command timed out (30s): {shown}"
        except OSError as exc:
            return f"command error: {shown} — {exc}"
        if proc.returncode == 0:
            return f"executed: {shown}"
        stderr = proc.stderr.strip()
        return (f"command failed (exit {proc.returncode}): {shown}"
                f"{': ' + stderr if stderr else ''}")
