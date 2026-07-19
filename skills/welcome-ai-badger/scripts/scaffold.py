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
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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

DEFAULT_SKILLS = ["task", "prompt-markers"]
# Test files are framework-only and must never be scaffolded into a target repo. Applied to every
# copytree so a skill's tests/ or test_*.py stay in ai-badger, out of the target's .ai-badger/.
_TEST_IGNORE = shutil.ignore_patterns("test_*.py", "*_test.py", "tests", "__pycache__", "*.pyc")
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


class Scaffolder:
    """Materializes a target repo's .ai-badger/ scaffold from a validated config.json."""

    def __init__(self, root: Path, target: Path, config: Dict[str, Any],
                 skills: List[str], install: bool, overwrite: bool = False):
        self.root = root
        self.target = target
        self.config = config
        self.skills = skills
        self.install = install
        self.overwrite = overwrite
        self.index = bl.read_index(root)
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
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, ignore=_TEST_IGNORE)
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
                shutil.copytree(extdir, ext_dest, ignore=_TEST_IGNORE)
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
        if model_tmpl.exists() and not (out / "model.json").exists():
            shutil.copyfile(model_tmpl, out / "model.json")

    def scaffold_templates(self) -> None:
        """Copy the shared state.json template into .ai-badger/, if present."""
        tdir = self.root / "features" / "common" / "templates"
        state = tdir / "state.json"
        if state.exists():
            shutil.copyfile(state, self.aib / "state.json")

    # -- CLAUDE.md assembly ---------------------------------------------------------
    def assemble_instructions_doc(self, invariants: List[str], instr_paths: List[Path]) -> str:
        """Render the CLAUDE.md.tmpl template with this config's project/commands/invariants."""
        tmpl_path = self.root / "features" / "common" / "templates" / "CLAUDE.md.tmpl"
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
        slots = {
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
        if tmpl_path.exists():
            doc = tmpl_path.read_text(encoding="utf-8")
            for k, v in slots.items():
                doc = doc.replace("{{" + k + "}}", str(v))
            return doc
        # fallback minimal doc if template missing
        return (f"# {slots['PROJECT_NAME']}\n\n{slots['PROJECT_SUMMARY']}\n\n"
                f"## Invariants\n\n{inv_md}\n\n## Commands\n\n{cmd_md}\n")

    # -- agent-discovery copies -----------------------------------------------------
    def write_agent_files(self, instructions_doc: str, instr_paths: List[Path]) -> None:
        """Write the assembled instructions doc into .ai-badger/ and each configured agent's
        discovery location (CLAUDE.md, AGENTS.md, copilot-instructions.md).

        Existing hand-authored discovery files are preserved by default: a target that already
        exists and does not carry the managed header is left untouched (its .ai-badger/ source is
        still written), so a mature repo's curated CLAUDE.md and instructions are never clobbered.
        Framework-written copies (which carry the header) and brand-new files are still written and
        refreshed. Pass overwrite=True (CLI --overwrite-agent-files) to force the old copy-over.
        """
        agents = self.config.get("agents", [])
        # source-of-truth files inside .ai-badger
        (self.aib / "CLAUDE.md").write_text(instructions_doc, encoding="utf-8")

        def copy_with_header(dest: Path, name: str, body: str) -> None:
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

        if "claude" in agents:
            copy_with_header(self.target / "CLAUDE.md", "CLAUDE.md", instructions_doc)
        if "junie" in agents:
            (self.aib / "AGENTS.md").write_text(instructions_doc, encoding="utf-8")
            copy_with_header(self.target / ".junie" / "AGENTS.md", "AGENTS.md", instructions_doc)
        if "copilot" in agents:
            (self.aib / "copilot-instructions.md").write_text(instructions_doc, encoding="utf-8")
            copy_with_header(self.target / ".github" / "copilot-instructions.md",
                             "copilot-instructions.md", instructions_doc)
            # copilot discovers scoped instructions under .github/instructions/
            for p in instr_paths:
                copy_with_header(self.target / ".github" / "instructions" / p.name,
                                 f"instructions/{p.name}", p.read_text(encoding="utf-8"))

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

    # -- orchestrate ----------------------------------------------------------------
    def run(self, generated_at: Optional[str]) -> Dict[str, Any]:
        """Run every scaffold step in order and return the manifest, plugin commands, and notes."""
        self.aib.mkdir(parents=True, exist_ok=True)
        self.scaffold_personas()
        instr_paths = self.scaffold_instructions()
        invariants = self.collect_invariants()
        self.scaffold_skills()
        self.scaffold_agent_instructions()
        self.scaffold_templates()
        doc = self.assemble_instructions_doc(invariants, instr_paths)
        self.write_agent_files(doc, instr_paths)
        plugin_cmds = self.install_plugins()

        # copy the config into place (source of truth for the skills)
        bl.dump_json(self.aib / "config.json", self.config)

        manifest = {
            "$schema": "../schemas/manifest.schema.json",
            "frameworkVersion": self.index["frameworkVersion"],
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
                      overwrite=args.overwrite_agent_files)
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
