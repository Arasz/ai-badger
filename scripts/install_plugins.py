"""Generic skill installation orchestrator for ai-badger.

Reads skills-source.json + skills.json per stack, resolves per-agent installation
commands from plugins-instructions.json, and returns the commands to execute.

Imported by scaffold.py; also usable standalone for testing.

Usage (library):
    from install_plugins import install_skills
    result = install_skills(framework_root, config, dry_run=True)

Usage (CLI):
    install_plugins.py --root <framework> --config <config.json> [--dry-run]

MECHANICAL ONLY — no LLM, no network.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
import badger_lib as bl


def _load_agent_instructions(root: Path, agent: str) -> Dict[str, Any]:
    """Load plugins-instructions.json for an agent, or return empty."""
    pii = root / "features" / agent / "plugins-instructions.json"
    if not pii.exists():
        return {}
    return bl.load_json(pii)


def _load_stack_sources(root: Path, stack: str) -> List[Dict[str, Any]]:
    """Load skills-source.json for a stack."""
    ssj = root / "features" / stack / "skills-source.json"
    if not ssj.exists():
        return []
    return bl.load_json(ssj).get("sources", [])


def _load_stack_skills(root: Path, stack: str) -> List[Dict[str, Any]]:
    """Load skills.json for a stack."""
    skj = root / "features" / stack / "skills.json"
    if not skj.exists():
        return []
    return bl.load_json(skj).get("skills", [])


def _source_supports_agent(source: Dict[str, Any], agent: str) -> bool:
    """Check if a source supports a given agent."""
    support = source.get("support")
    if support == "common":
        return True
    if isinstance(support, list):
        return agent in support
    return False


def _resolve_scope(entry_scope: str, config_scope: str) -> str:
    """Resolve the effective scope for a skill entry."""
    if config_scope == "local":
        return "local"
    return entry_scope if entry_scope != "default" else "default"


def _build_command(template: str, source_url: str, skill_name: str = "",
                   scope: str = "default") -> str:
    """Substitute placeholders in a command template."""
    cmd = template.replace("{source}", source_url)
    cmd = cmd.replace("{name}", skill_name)
    cmd = cmd.replace("{scope}", scope)
    return cmd


def install_skills(root: Path, config: Dict[str, Any],
                   dry_run: bool = True) -> Dict[str, Any]:
    """Generate skill installation commands for all agents and stacks.

    For each agent, for each stack's skills:
    1. Find the source in skills-source.json
    2. Check if the agent supports this source type
    3. Look up the installation instructions for this source type
    4. Generate "add source" command (first template, without {name})
    5. Generate "install skill" command (template with {name}, or second template)

    Args:
        root: Framework root directory.
        config: Project config (from .ai-badger/config.json).
        dry_run: If True, don't execute commands (default: True).

    Returns:
        {
            'commands': list[str],
            'warnings': list[str],
            'dryRun': bool,
        }
    """
    agents = config.get("agents", [])
    stacks = config.get("stacks", [])
    config_scope = config.get("skillScope", config.get("pluginScope", "default"))

    commands: List[str] = []
    warnings: List[str] = []
    added_sources: Dict[str, set] = {}

    for agent in agents:
        instructions = _load_agent_instructions(root, agent)
        agent_instructions = instructions.get("instructions", {})
        added_sources[agent] = set()

        for stack in stacks:
            sources = _load_stack_sources(root, stack)
            skills = _load_stack_skills(root, stack)
            source_map = {s["name"]: s for s in sources}

            for skill in skills:
                source_name = skill.get("source")
                if not source_name or source_name not in source_map:
                    warnings.append(
                        f"Skill '{skill['name']}' references unknown source "
                        f"'{source_name}'")
                    continue

                source = source_map[source_name]
                if not _source_supports_agent(source, agent):
                    continue

                source_type = source.get("type")
                source_url = source.get("source", "")
                instruction = agent_instructions.get(source_type)

                if not instruction:
                    warnings.append(
                        f"Agent '{agent}' has no instruction for source type "
                        f"'{source_type}' (skill '{skill['name']}' from "
                        f"'{source_name}')")
                    continue

                cmd_templates = instruction.get("commands", [])
                if not cmd_templates:
                    continue

                # Add source command once per (agent, source_type, source_url)
                source_key = (source_type, source_url)
                if source_key not in added_sources[agent]:
                    commands.append(_build_command(cmd_templates[0], source_url))
                    added_sources[agent].add(source_key)

                # Install skill command
                scope = _resolve_scope(
                    skill.get("scope", "default"), config_scope)

                install_template = None
                for tpl in cmd_templates:
                    if "{name}" in tpl:
                        install_template = tpl
                        break
                if install_template is None and len(cmd_templates) > 1:
                    install_template = cmd_templates[1]
                elif install_template is None:
                    install_template = cmd_templates[0]

                scope_suffix = ""
                if scope != "default" and "{scope}" not in install_template:
                    scope_suffix = f" --scope {scope}"

                install_cmd = _build_command(
                    install_template, source_url, skill["name"], scope)
                install_cmd += scope_suffix
                commands.append(install_cmd)

    return {"commands": commands, "warnings": warnings, "dryRun": dry_run}


def main(argv: Any = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", help="Framework root (default: auto-detect)")
    ap.add_argument("--config", required=True, help="Path to config.json")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Don't execute, just print commands (default: True)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()
    config = bl.load_json(Path(args.config).resolve())

    result = install_skills(root, config, dry_run=args.dry_run)

    if result["warnings"]:
        for w in result["warnings"]:
            print(f"WARNING: {w}", file=sys.stderr)

    if result["commands"]:
        for cmd in result["commands"]:
            print(cmd)
    else:
        print("No skill installation commands needed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
