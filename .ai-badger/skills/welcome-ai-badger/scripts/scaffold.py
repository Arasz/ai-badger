#!/usr/bin/env python3
"""Materialize a target repo's .ai-badger/ scaffold from a validated config.json.

MECHANICAL ONLY — no LLM, no network (except optional plugin installs, which are
skippable). The agent authors config.json; this script does everything else deterministically
and idempotently (safe to re-run; it rewrites managed files and refreshes the manifest).

Usage:
  scaffold.py --config <path/to/config.json> --target <target repo dir> [--root <framework>]
              [--skills task,prompt-markers] [--no-install] [--generated-at <iso>]

Outputs under <target>/.ai-badger/ plus copied agent-discovery files (CLAUDE.md, copilot,
junie) per config.agents, and <target>/.ai-badger/manifest.json.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def _bootstrap_lib() -> None:
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "scripts" / "badger_lib.py"
        if cand.exists() and (anc / "schemas").is_dir():
            sys.path.insert(0, str(anc / "scripts"))
            return
    # Fallback: check cached framework repo at ~/.ai-badger/framework/
    cache = Path.home() / ".ai-badger" / "framework"
    cache_scripts = cache / "scripts" / "badger_lib.py"
    if cache_scripts.exists() and (cache / "schemas").is_dir():
        sys.path.insert(0, str(cache / "scripts"))
        return
    raise RuntimeError(
        "could not locate ai-badger scripts/badger_lib.py locally or at "
        f"{cache} — run with --root <framework> or clone https://github.com/Arasz/ai-badger"
    )


_bootstrap_lib()
import badger_lib as bl

# Ensure the script's directory is on sys.path so domain modules resolve
# when scaffold.py is loaded dynamically (e.g. via tests' load_script).
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _shared import (  # noqa: E402 — re-exported for backward compatibility
    _test_ignore, PROJECT_LOCAL_FILE, MANAGED_HEADER, _MANAGED_PREFIX,
    cfg_get, requirement_met, _condition_met,
)

DEFAULT_SKILLS = [
    "auto-wm",
    "den-refresh",
    "feed-badger",
    "maintain-agent-instructions",
    "mcp-index",
    "prompt-markers",
    "task",
    "welcome-ai-badger",
]
SEED_ONCE_SKILL_FILES: Dict[str, List[str]] = {
    "prompt-markers": ["markers-context.json"],
}


# ---------------------------------------------------------------------- index lookups
def feature_items(index: Dict[str, Any], stack: str, feature: str) -> List[Dict[str, Any]]:
    """Return the index items for one stack's feature bucket (personas, skills, ...)."""
    return index.get("stacks", {}).get(stack, {}).get(feature, [])


def git_provenance(root: Path) -> Tuple[Optional[str], bool]:
    """Return (HEAD sha, working-tree-dirty) for root, or (None, False) when it is not a git repo.

    A plugin cache is a plain copy with no .git, so the commit is unknowable there and the
    version resolves to it instead (ADR-0001 decision 4). A copy cannot be dirty, so False
    is a fact rather than a missing value.
    """
    if not (root / ".git").exists():
        return None, False
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, False
    return (sha or None), bool(status)


# Import mixin classes from domain modules
from hook_wiring import HookWiringMixin, merge_hooks  # noqa: E402
from template_rendering import TemplateRenderingMixin  # noqa: E402
from agent_files import AgentFilesMixin  # noqa: E402
from extensions import ExtensionsMixin  # noqa: E402
from mcp_tools import McpToolsMixin  # noqa: E402


class Scaffolder(
    McpToolsMixin,
    HookWiringMixin,
    TemplateRenderingMixin,
    AgentFilesMixin,
    ExtensionsMixin,
):
    """Materializes a target repo's .ai-badger/ scaffold from a validated config.json."""

    def __init__(self, root: Path, target: Path, config: Dict[str, Any],
                 skills: List[str], install: bool, overwrite: bool = False,
                 reset_seed_files: bool = False, execute: bool = False):
        self.root = root
        self.target = target
        self.config = config
        self.skills = skills
        self.install = install
        self.overwrite = overwrite
        self.reset_seed_files = reset_seed_files
        self.execute = execute
        self.index = bl.read_index(root)
        self.commit, self.dirty = git_provenance(root)
        self.aib = target / ".ai-badger"
        self.entries: List[Dict[str, Any]] = []
        self.stacks: List[str] = ["common"] + list(config.get("stacks", []))
        self.notes: List[str] = []
        self._merged_external_tools: List[Dict[str, Any]] = []
        self._external_tools_merged = False

    # -- provenance -----------------------------------------------------------------
    def record(self, feature: str, stack: str, name: str, source: Path, target: Path) -> None:
        """Append a manifest entry recording where a scaffolded item came from and went."""
        entry = {
            "feature": feature, "stack": stack, "name": name,
            "source": source.relative_to(self.root).as_posix(),
            "target": target.relative_to(self.target).as_posix(),
            "frameworkVersion": self.index["frameworkVersion"],
        }
        if source.is_dir():
            # Directory entry (skills): hash the TARGET dir (after extension
            # embedding/pruning) so drift detection compares the actual scaffolded output
            fingerprint = bl.dir_content_hash(target, exclude=bl.SKILL_EXCLUDE_PATTERNS)
            entry["hash"] = fingerprint["content_hash"]
            entry["dirMeta"] = {
                "file_count": fingerprint["file_count"],
                "dir_count": fingerprint["dir_count"],
            }
        else:
            entry["hash"] = bl.sha256_file(target)
        self.entries.append(entry)

    def copy_file(self, feature: str, stack: str, item: Dict[str, Any], dest_dir: Path) -> Path:
        """Copy one index item's source file into dest_dir and record its provenance."""
        src = self.root / item["path"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copyfile(src, dest)
        self.record(feature, stack, item["name"], src, dest)
        return dest

    # -- seed-once (framework writes once, project owns thereafter; see #15) --------
    def _seed_once_copy(self, src: Path, dest: Path, label: str) -> None:
        """Copy src to dest only on first scaffold. If dest already exists, it is project-owned
        and left untouched (--reset-seed-files overrides this and reseeds from src)."""
        if dest.exists() and not self.reset_seed_files:
            self.notes.append(
                f"preserved seed-once {label} (already exists; not re-seeded; "
                "pass --reset-seed-files to reset)"
            )
            return
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)

    def _stash_seed_once_skill_files(self, skill_name: str, dest: Path) -> Dict[str, bytes]:
        """Read the current content of any seed-once files inside a skill dir before it is
        rmtree'd, so they can be restored after the fresh copytree. Empty on first scaffold
        (dest doesn't exist yet) or when --reset-seed-files is requested."""
        if self.reset_seed_files:
            return {}
        stashed: Dict[str, bytes] = {}
        for relpath in SEED_ONCE_SKILL_FILES.get(skill_name, []):
            p = dest / relpath
            if p.exists():
                stashed[relpath] = p.read_bytes()
        # Also stash project-local.md (generic: any skill may carry one)
        pl = dest / PROJECT_LOCAL_FILE
        if pl.exists():
            stashed[PROJECT_LOCAL_FILE] = pl.read_bytes()
        return stashed

    def _restore_seed_once_skill_files(self, skill_name: str, dest: Path,
                                        stashed: Dict[str, bytes]) -> None:
        """Write back stashed seed-once file content after the skill dir's fresh copytree."""
        for relpath, content in stashed.items():
            p = dest / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            self.notes.append(
                f"preserved seed-once .ai-badger/skills/{skill_name}/{relpath} "
                "(already existed; not re-seeded; pass --reset-seed-files to reset)"
            )

    # -- features -------------------------------------------------------------------
    def scaffold_personas(self) -> None:
        """Copy every applicable stack's persona files into .ai-badger/agents/."""
        for stack in self.stacks:
            for item in feature_items(self.index, stack, "personas"):
                self.copy_file("personas", stack, item, self.aib / "agents")

    def scaffold_instructions(self) -> List[Path]:
        """Copy every applicable stack's instruction files into .ai-badger/instructions/."""
        out: List[Path] = []
        for stack in self.stacks:
            for item in feature_items(self.index, stack, "instructions"):
                out.append(self.copy_file("instructions", stack, item, self.aib / "instructions"))
        return out

    def collect_invariants(self) -> List[str]:
        """Copy invariant snippets and return their rendered markdown for CLAUDE.md."""
        rendered: List[str] = []
        for stack in self.stacks:
            for item in feature_items(self.index, stack, "invariants"):
                dest = self.copy_file("invariants", stack, item, self.aib / "invariants")
                text = dest.read_text(encoding="utf-8").strip()
                rendered.append(text)
        return rendered

    def scaffold_skills(self) -> None:
        """Copy each requested skill directory into .ai-badger/skills/, with its extensions."""
        for skill_name in self.skills:
            item = next((s for s in feature_items(self.index, "common", "skills")
                         if s["name"] == skill_name), None)
            if item is None:
                self.notes.append(f"skill '{skill_name}' not in index common.skills — skipped")
                continue
            src = self.root / item["path"]
            dest = self.aib / "skills" / skill_name
            stashed = self._stash_seed_once_skill_files(skill_name, dest)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, ignore=_test_ignore)
            self._restore_seed_once_skill_files(skill_name, dest, stashed)
            self._prune_inline_extensions(skill_name, dest)
            self._merge_extensions(skill_name, dest)
            self._embed_extensions(skill_name, item, dest)
            self._append_project_local(skill_name, dest)
            # hash includes embedded extensions
            self.record("skills", "common", skill_name, src, dest)

    def scaffold_agent_instructions(self) -> None:
        """Copy the agent-instructions schema/model template into .ai-badger/agent-instructions/."""
        tdir = self.root / "features" / "common" / "templates" / "agent-instructions"
        if not tdir.is_dir():
            self.notes.append("common/templates/agent-instructions missing — skipped")
            return
        out = self.aib / "agent-instructions"
        out.mkdir(parents=True, exist_ok=True)
        schema = tdir / "schema.json"
        if schema.exists():
            shutil.copyfile(schema, out / "schema.json")
        model_tmpl = tdir / "model.template.json"
        self._seed_once_copy(model_tmpl, out / "model.json",
                              ".ai-badger/agent-instructions/model.json")

    def scaffold_templates(self) -> None:
        """Seed the shared state.json template into .ai-badger/ on first scaffold only. It is a
        live task index the project owns after that (see #15): a re-scaffold must not clobber it."""
        tdir = self.root / "features" / "common" / "templates"
        state = tdir / "state.json"
        self._seed_once_copy(state, self.aib / "state.json", ".ai-badger/state.json")

    # -- skill installation --------------------------------------------------------
    def install_plugins(self) -> List[str]:
        """Generate skill installation commands using the install_plugins library.

        Reads skills-source.json + skills.json per stack, resolves per-agent
        installation commands from plugins-instructions.json.
        """
        import install_plugins as ip_lib
        result = ip_lib.install_skills(self.root, self.config, dry_run=not self.install)

        # Provenance: copy skills-source.json + skills.json per stack
        for stack in self.stacks:
            for fname in ("skills-source.json", "skills.json"):
                src = self.root / "features" / stack / fname
                if src.exists():
                    dest_dir = self.aib / "skills-data" / stack
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / fname
                    shutil.copyfile(src, dest)
                    feature = "skills"
                    self.record(feature, stack, f"{stack}/{fname}", src, dest)

        cmds = result["commands"]
        if self.execute and cmds:
            for cmd in cmds:
                try:
                    proc = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        timeout=30, cwd=str(self.target), check=False,
                    )
                    if proc.returncode == 0:
                        self.notes.append(f"executed: {cmd}")
                    else:
                        self.notes.append(
                            f"command failed (exit {proc.returncode}): {cmd}"
                            f"{': ' + proc.stderr.strip() if proc.stderr.strip() else ''}"
                        )
                except subprocess.TimeoutExpired:
                    self.notes.append(f"command timed out (30s): {cmd}")
                except OSError as exc:
                    self.notes.append(f"command error: {cmd} — {exc}")
        elif self.install and cmds:
            self.notes.append("skill auto-install requested but deferred to report "
                              "(run the commands below manually or via --execute)")
        for w in result.get("warnings", []):
            self.notes.append(f"skill install warning: {w}")
        return cmds

    # -- Hermes skill discovery ---------------------------------------------------
    def symlink_hermes_skills(self) -> None:
        """Symlink project skills into ~/.hermes/skills/ with project namespace.

        Each project's skills are namespaced under ~/.hermes/skills/<project-name>/
        to avoid conflicts when multiple projects have skills with the same name
        (e.g., 'task'). Hermes discovers skills from ~/.hermes/skills/ (global).

        Does NOT use external_dirs — that's a shared global list that causes
        skill name conflicts across projects.
        """
        if "hermes" not in self.config.get("agents", []):
            return
        project_name = self.config.get("project", {}).get("name", "unknown")
        global_skills = Path.home() / ".hermes" / "skills"
        global_skills.mkdir(parents=True, exist_ok=True)
        namespace_dir = global_skills / project_name
        if namespace_dir.is_symlink() or namespace_dir.exists():
            if namespace_dir.is_dir() and not namespace_dir.is_symlink():
                shutil.rmtree(namespace_dir)
            else:
                namespace_dir.unlink()
        # Create namespace dir and symlink each skill into it
        namespace_dir.mkdir(parents=True, exist_ok=True)
        for skill_name in self.skills:
            src = self.aib / "skills" / skill_name
            dst = namespace_dir / skill_name
            if not src.is_dir():
                continue
            dst.symlink_to(os.path.relpath(src, dst.parent))

    # -- adjustments ----------------------------------------------------------------
    def run_adjustments(self) -> None:
        """Run agent-specific adjustments declared in features/<agent>/adjustments/.

        Each adjustment is a Python script with an adjust(context) function that
        receives the framework root, config, and target directory, and returns
        {'applied': bool, 'files': list, 'notes': str}.
        """
        for agent_name in self.config.get("agents", []):
            adj_path = self.root / "features" / agent_name / "adjustments" / "adjustment.json"
            if not adj_path.exists():
                continue

            try:
                adj_manifest = bl.load_json(adj_path)
            except (ValueError, OSError):
                continue

            for adj in adj_manifest.get("adjustments", []):
                script_name = adj.get("script")
                if not script_name:
                    continue

                script_path = adj_path.parent / script_name
                if not script_path.exists():
                    self.notes.append(
                        f"adjustment script '{script_name}' for '{agent_name}' not found — skipped"
                    )
                    continue

                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        f"adj_{agent_name}_{script_name}", script_path
                    )
                    if spec is None or spec.loader is None:
                        self.notes.append(
                            f"adjustment '{script_name}' for '{agent_name}' — could not load module"
                        )
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)

                    context = {
                        "framework_root": self.root,
                        "config": self.config,
                        "feature_dir": self.root / "features" / agent_name / "adjustments",
                        "target_dir": self.aib,
                        "target": self.target,
                        "skills": self.skills,
                        "index": self.index,
                    }
                    result = mod.adjust(context)
                    if result.get("applied"):
                        self.notes.append(
                            f"adjustment '{adj.get('feature', script_name)}' for "
                            f"'{agent_name}': {result.get('notes', 'applied')}"
                        )
                        for f in result.get("files", []):
                            self.record("adjustments", agent_name,
                                        f"adjustments/{f}", script_path,
                                        self.target / f)
                    else:
                        self.notes.append(
                            f"adjustment '{adj.get('feature', script_name)}' for "
                            f"'{agent_name}': not applied — {result.get('notes', 'no reason')}"
                        )
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    self.notes.append(
                        f"adjustment '{script_name}' for '{agent_name}' failed: {exc}"
                    )

    # -- orchestrate ----------------------------------------------------------------
    def run(self, generated_at: Optional[str] = None) -> Dict[str, Any]:
        """Run every scaffold step in order and return the manifest, plugin commands, and notes."""
        self.aib.mkdir(parents=True, exist_ok=True)
        self.scaffold_personas()
        instr_paths = self.scaffold_instructions()
        invariants = self.collect_invariants()
        self.scaffold_skills()
        self.symlink_hermes_skills()
        self.scaffold_agent_instructions()
        self.scaffold_templates()
        self._merged_external_tools = self._merge_external_tools(
            self._collect_external_tools(),
            self.config.get("externalTools", []),
        )
        self._external_tools_merged = True
        doc = self.assemble_instructions_doc(invariants, instr_paths)
        self.write_agent_files(doc, instr_paths, invariants)
        self.wire_hooks()
        self.run_adjustments()
        plugin_cmds = self.install_plugins()

        # copy the config into place (source of truth for the skills)
        bl.dump_json(self.aib / "config.json", self.config)

        # generate .mcp.json for external tools that request it
        self._generate_mcp_json()

        # scaffold user-scoped MCP servers into agent-specific config files
        stack_servers = self._collect_stack_mcp_servers()
        merged = self._merge_mcp_servers(stack_servers, self._merged_external_tools)
        project_servers, user_servers = self._split_servers_by_scope(merged)
        self._scaffold_hermes_mcp_user(user_servers)
        self._scaffold_claude_mcp_user(user_servers)
        self._generate_copilot_mcp_config(project_servers)

        manifest = {
            "$schema": "../schemas/manifest.schema.json",
            "frameworkVersion": self.index["frameworkVersion"],
            "frameworkCommit": self.commit,
            "frameworkDirty": self.dirty,
            "generatedAt": generated_at,
            "agents": self.config.get("agents", []),
            "skillScope": self.config.get("skillScope", self.config.get("pluginScope", "default")),
            "pluginScope": self.config.get("skillScope", self.config.get("pluginScope", "default")),  # compat
            "entries": self.entries,
        }
        bl.dump_json(self.aib / "manifest.json", manifest)
        return {"manifest": manifest, "pluginCommands": plugin_cmds, "notes": self.notes}


def main(argv=None) -> int:
    """CLI entry point: validate config.json, then scaffold .ai-badger/ into --target."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--root")
    ap.add_argument("--skills", default=",".join(DEFAULT_SKILLS))
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--overwrite-agent-files", action="store_true",
                    help="Overwrite existing hand-authored discovery files (CLAUDE.md, copilot, "
                         "junie, .github/instructions/*). Default preserves any that lack the "
                         "ai-badger managed header.")
    ap.add_argument("--reset-seed-files", action="store_true",
                    help="Reseed SEED-ONCE files (.ai-badger/state.json, agent-instructions/"
                         "model.json, skills/prompt-markers/markers-context.json) from the "
                         "framework template, discarding any project-owned edits. Default "
                         "preserves them once they exist.")
    ap.add_argument("--execute", action="store_true",
                    help="Execute skill install commands instead of just printing them. "
                         "Commands run with 30s timeout per command. Default is advisory-only.")
    ap.add_argument("--generated-at", default=None,
                    help="ISO timestamp to stamp in manifest (orchestrator supplies; "
                         "scripts avoid clocks).")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()
    config_path = Path(args.config).resolve()
    target = Path(args.target).resolve()

    # validate config BEFORE doing anything
    errors = bl.validate_file(config_path, root / "schemas" / "config.schema.json")
    if errors:
        print("config.json is INVALID — aborting scaffold:")
        for e in errors:
            print(f"    - {e}")
        return 1

    config = bl.load_json(config_path)
    skills = [s for s in args.skills.split(",") if s]
    scaf = Scaffolder(root, target, config, skills, install=not args.no_install,
                      overwrite=args.overwrite_agent_files,
                      reset_seed_files=args.reset_seed_files,
                      execute=args.execute)
    result = scaf.run(generated_at=args.generated_at)

    print(f"scaffolded {len(result['manifest']['entries'])} entries into {scaf.aib}")
    for n in result["notes"]:
        print(f"  note: {n}")
    if result["pluginCommands"]:
        print("  plugin setup commands (run per chosen scope):")
        for c in result["pluginCommands"]:
            print(f"    $ {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
