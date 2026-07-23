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
    raise RuntimeError("could not locate ai-badger scripts/badger_lib.py")


_bootstrap_lib()
import badger_lib as bl

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
# Test files and eval suites are framework-only quality-regression content and must never be
# scaffolded into a target repo. Applied to every copytree so a skill's tests/, test_*.py, or
# evals/ stay in ai-badger, out of the target's .ai-badger/.
_test_ignore = shutil.ignore_patterns(
    "test_*.py", "*_test.py", "tests", "evals", "__pycache__", "*.pyc"
)
SEED_ONCE_SKILL_FILES: Dict[str, List[str]] = {
    # Path is relative to the scaffolded skill directory. The framework seeds this file on
    # first scaffold; the project owns it thereafter, so scaffold_skills() must stash it before
    # the skill dir's rmtree+copytree refresh and restore it after (see #15). Any other file in
    # the same skill dir (SKILL.md, scripts/) is MANAGED and keeps refreshing on every run.
    "prompt-markers": ["markers-context.json"],
}
MANAGED_HEADER = (
    "<!-- Managed by ai-badger. Source of truth: .ai-badger/{name}. "
    "Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->\n\n"
)
# Stable leading text every managed copy begins with (the part before the {name} slot). Used to
# tell a framework-written discovery file apart from a hand-authored one when deciding whether to
# overwrite, so a mature repo's curated CLAUDE.md/instructions are never clobbered.
_MANAGED_PREFIX = MANAGED_HEADER.split("{name}", 1)[0]


# ---------------------------------------------------------------- config-path helpers
def cfg_get(config: Dict[str, Any], dotted: str) -> Any:
    """Look up a dotted path (e.g. 'project.name') in config, or None if any part is missing."""
    node: Any = config
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def requirement_met(config: Dict[str, Any], req: str) -> bool:
    """Evaluate an extension requirement like 'sourceControl.platform==github' or
    'sourceControl.repoUrl' (presence)."""
    if "==" in req:
        path, expected = (s.strip() for s in req.split("==", 1))
        return str(cfg_get(config, path)) == expected
    val = cfg_get(config, req)
    return val not in (None, "", [], {})


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


class Scaffolder:
    """Materializes a target repo's .ai-badger/ scaffold from a validated config.json."""

    def __init__(self, root: Path, target: Path, config: Dict[str, Any],
                 skills: List[str], install: bool, overwrite: bool = False,
                 reset_seed_files: bool = False):
        self.root = root
        self.target = target
        self.config = config
        self.skills = skills
        self.install = install
        self.overwrite = overwrite
        self.reset_seed_files = reset_seed_files
        self.index = bl.read_index(root)
        self.commit, self.dirty = git_provenance(root)
        self.aib = target / ".ai-badger"
        self.entries: List[Dict[str, Any]] = []
        self.stacks: List[str] = ["common"] + list(config.get("stacks", []))
        self.notes: List[str] = []

    # -- provenance -----------------------------------------------------------------
    def record(self, feature: str, stack: str, name: str, source: Path, target: Path) -> None:
        """Append a manifest entry recording where a scaffolded item came from and went."""
        self.entries.append({
            "feature": feature, "stack": stack, "name": name,
            "source": source.relative_to(self.root).as_posix(),
            "target": target.relative_to(self.target).as_posix(),
            "frameworkVersion": self.index["frameworkVersion"],
            "hash": bl.sha256_file(target),  # as-scaffolded content, so feed detects genuine edits
        })

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
            self._embed_extensions(skill_name, item, dest)
            # hash includes embedded extensions
            self.record("skills", "common", skill_name, src, dest)

    def _embed_extensions(self, skill_name: str, item: Dict[str, Any], dest: Path) -> None:
        for ext in item.get("extensions", []):
            # find the extension descriptor: features/<stack>/skills/<skill>-extensions/<ext>/
            matches = list(self.root.glob(f"features/*/skills/{skill_name}-extensions/{ext}"))
            if not matches:
                continue
            extdir = matches[0]
            descriptor = extdir / "extension.json"
            reqs = []
            if descriptor.exists():
                reqs = bl.load_json(descriptor).get("requires", [])
            if all(requirement_met(self.config, r) for r in reqs):
                ext_dest = dest / "extensions" / ext
                if ext_dest.exists():
                    shutil.rmtree(ext_dest)
                shutil.copytree(extdir, ext_dest, ignore=_test_ignore)
                # not recorded separately — covered by the skill dir's manifest entry/hash
                self.notes.append(
                    f"embedded extension '{ext}' into skill '{skill_name}' (requirements met)"
                )
            else:
                self.notes.append(
                    f"extension '{ext}' for '{skill_name}' skipped (config requirements not met)"
                )

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

    # -- CLAUDE.md assembly ---------------------------------------------------------
    def _compute_doc_slots(self, invariants: List[str], instr_paths: List[Path]) -> Dict[str, str]:
        """Compute the template slots shared by CLAUDE.md and HERMES.md assembly."""
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
        return {
            "PROJECT_NAME": project.get("name", ""),
            "PROJECT_SUMMARY": project.get("summary", ""),
            "PROJECT_DOMAIN": project.get("domain", ""),
            "STACKS": ", ".join(self.config.get("stacks", [])),
            "INVARIANTS": inv_md,
            "COMMANDS": cmd_md,
            "PERSONA_ROUTING": route_md,
            "PATH_INSTRUCTIONS": instr_md,
            "FRAMEWORK_VERSION": self.index["frameworkVersion"],
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
        return self._render_template("HERMES.md.tmpl",
                                     self._compute_doc_slots(invariants, instr_paths))

    # -- agent-discovery copies -----------------------------------------------------
    def _render_template_file(self, source: Path, instr_paths: List[Path],
                               invariants: List[str]) -> str:
        """Render a .tmpl file with the standard scaffold slots."""
        tmpl = source.read_text(encoding="utf-8")
        slots = self._compute_doc_slots(invariants, instr_paths)
        for k, v in slots.items():
            tmpl = tmpl.replace("{{" + k + "}}", str(v))
        return tmpl

    def _copy_with_header(self, dest: Path, name: str, body: str) -> None:
        """Write body to dest with managed header, preserving hand-authored files."""
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

    def _apply_scaffolding(self, agent_name: str, instructions_doc: str,
                            instr_paths: List[Path], invariants: List[str]) -> None:
        """Apply features/<agent>/scaffolding.json to write agent files."""
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
            if is_template:
                body = self._render_template_file(source, instr_paths, invariants)
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

            # Write the primary target
            content = body
            if managed:
                self._copy_with_header(target, file_entry["target"], content)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

            # Write alsoTarget (e.g. .hermes.md alias)
            if also_target:
                also_dest = self.target / also_target
                if managed:
                    self._copy_with_header(also_dest, also_target, content)
                else:
                    also_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, also_dest)

            # Write per-instruction scoped copies (copilot's .github/instructions/)
            if instructions_scoped:
                for p in instr_paths:
                    self._copy_with_header(
                        self.target / ".github" / "instructions" / p.name,
                        f"instructions/{p.name}",
                        p.read_text(encoding="utf-8")
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

    # -- plugins --------------------------------------------------------------------
    def install_plugins(self) -> List[str]:
        """Copy each applicable stack's plugins.json/marketplaces.json for provenance and
        return the `claude plugin ...` commands needed to install them."""
        cmds: List[str] = []
        added_markets: set = set()
        scope_choice = self.config.get("pluginScope", "default")
        for stack in self.stacks:
            pdir = self.root / "features" / stack / "plugins"
            pj = pdir / "plugins.json"
            if not pj.exists():
                continue
            mj = pdir / "marketplaces.json"
            markets = {m["name"]: m["source"]
                       for m in (bl.load_json(mj).get("marketplaces", []) if mj.exists() else [])}
            for plug in bl.load_json(pj).get("plugins", []):
                src = markets.get(plug.get("marketplace"))
                if src and src not in added_markets:  # add each marketplace URL once
                    cmds.append(f"claude plugin marketplace add {src}")
                    added_markets.add(src)
                entry_scope = "local" if scope_choice == "local" else plug.get("scope", "default")
                flag = " --scope user" if entry_scope == "user" else ""
                cmds.append(f"claude plugin install {plug['name']}{flag}")
            # provenance: copy the stack's single plugins.json + marketplaces.json
            dest_dir = self.aib / "plugins" / stack
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_pj = dest_dir / "plugins.json"
            shutil.copyfile(pj, dest_pj)
            self.record("plugins", stack, f"{stack}/plugins", pj, dest_pj)
            if mj.exists():
                dest_mj = dest_dir / "marketplaces.json"
                shutil.copyfile(mj, dest_mj)
                self.record("plugins", stack, f"{stack}/marketplaces", mj, dest_mj)
        if self.install and cmds:
            self.notes.append("plugin auto-install requested but deferred to report "
                              "(run the commands below manually or via the CLI)")
        return cmds

    # -- Hermes skill discovery ---------------------------------------------------
    def symlink_hermes_skills(self) -> None:
        """Symlink .ai-badger/skills/ → .hermes/skills/ for Hermes auto-discovery.

        Hermes discovers project-local skills from .hermes/skills/ in the
        working directory. These symlinks make ai-badger-scaffolded skills
        visible without any config changes — just start hermes in the project
        root.
        """
        if "hermes" not in self.config.get("agents", []):
            return
        hermes_skills = self.target / ".hermes" / "skills"
        hermes_skills.mkdir(parents=True, exist_ok=True)
        for skill_name in self.skills:
            src = self.aib / "skills" / skill_name
            dst = hermes_skills / skill_name
            if not src.is_dir():
                continue
            # Remove stale symlink or directory before recreating
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            dst.symlink_to(os.path.relpath(src, dst.parent))

    # -- orchestrate ----------------------------------------------------------------
    def run(self, generated_at: Optional[str]) -> Dict[str, Any]:
        """Run every scaffold step in order and return the manifest, plugin commands, and notes."""
        self.aib.mkdir(parents=True, exist_ok=True)
        self.scaffold_personas()
        instr_paths = self.scaffold_instructions()
        invariants = self.collect_invariants()
        self.scaffold_skills()
        self.symlink_hermes_skills()
        self.scaffold_agent_instructions()
        self.scaffold_templates()
        doc = self.assemble_instructions_doc(invariants, instr_paths)
        self.write_agent_files(doc, instr_paths, invariants)
        plugin_cmds = self.install_plugins()

        # copy the config into place (source of truth for the skills)
        bl.dump_json(self.aib / "config.json", self.config)

        manifest = {
            "$schema": "../schemas/manifest.schema.json",
            "frameworkVersion": self.index["frameworkVersion"],
            "frameworkCommit": self.commit,
            "frameworkDirty": self.dirty,
            "generatedAt": generated_at,
            "agents": self.config.get("agents", []),
            "pluginScope": self.config.get("pluginScope", "default"),
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
                      reset_seed_files=args.reset_seed_files)
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
