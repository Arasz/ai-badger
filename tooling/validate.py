#!/usr/bin/env python3
"""Validate an ai-badger JSON model against its schema.

Usage:
  validate.py <instance.json> [--schema <schema.json>]
  validate.py --kind {config|manifest|index|skills-source|skills|plugins-instructions|adjustment|hooks-manifest|learned-skills} <instance.json>
  validate.py --all         # validate index.json + all feature data + self-check schemas

Exit code 0 == valid, 1 == invalid, 2 == usage error. Mechanical; no LLM, no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl

KIND_TO_SCHEMA = {
    "config": "config.schema.json",
    "manifest": "manifest.schema.json",
    "index": "index.schema.json",
    "skills-source": "skills-source.schema.json",
    "skills": "skills.schema.json",
    "plugins-instructions": "plugins-instructions.schema.json",
    "adjustment": "adjustment.schema.json",
    "hooks-manifest": "hooks-manifest.schema.json",
    "learned-skills": "learned-skills.schema.json",
}

# Every catalog file --all validates, as root-relative globs per schema. Adding a schema
# without a line here fails test_every_schema_has_a_coverage_decision.
SCHEMA_INSTANCES = {
    "index.schema.json": ["index.json"],
    "skills-source.schema.json": ["features/*/skills-source.json"],
    "skills.schema.json": ["features/*/skills.json"],
    "hooks-manifest.schema.json": ["features/*/hooks/hooks-manifest.json"],
    "adjustment.schema.json": ["features/*/adjustments/adjustment.json"],
    "plugins-instructions.schema.json": ["features/*/plugins-instructions.json"],
    "stack-mcp.schema.json": ["features/*/stack-mcp.json"],
    "mcp-server.schema.json": ["features/*/mcp/*/meta.json"],
    "mcp-server-tools.schema.json": ["features/*/mcp/*/tools.json"],
    "stack.schema.json": ["features/*/stack.json"],
    "dependencies.schema.json": ["features/*/dependencies.json"],
    "scaffolding.schema.json": ["features/*/scaffolding.json"],
    "support.schema.json": ["features/*/support.json"],
    "model.schema.json": ["features/*/agent-instructions/model.json"],
}

# Schemas with no instance in this repo, and why. Listed so the completeness check stays
# honest rather than silently shrinking.
SCHEMAS_WITHOUT_LOCAL_INSTANCES = {
    "config.schema.json": "instances live in consumer projects (.ai-badger/config.json)",
    "manifest.schema.json": "instances live in consumer projects (.ai-badger/manifest.json)",
    "learned-skills.schema.json": "instances live in consumer projects (skills-data/)",
    "agents.schema.json": "vocabulary schema, referenced by others; no standalone instance",
    "mcp-tools.schema.json": "instances live in consumer projects (.ai-badger/mcp-tools.json)",
}

# Agents capable of every hook event family this framework wires: SessionStart/on_session_start/
# sessionStart, UserPromptSubmit/pre_llm_call/userPromptSubmitted, PostToolUse-PreToolUse/
# post_tool_call-pre_tool_call/postToolUse-preToolUse, and Stop-SessionEnd/on_session_end/
# agentStop-sessionEnd (docs/dictionary.md "Hooks"). A hooks-
# manifest.json entry missing one of these must say why (see HOOKS_MANIFEST_AGENT_EXEMPTIONS)
# instead of silently never reaching it — issue #147 was the third occurrence of exactly that.
HOOK_CAPABLE_AGENTS = ("claude", "hermes", "copilot")

# Junie is deliberately absent from HOOK_CAPABLE_AGENTS, not merely unlisted per hook: its own
# config ignores project-local hooks entirely (docs/dictionary.md "Hooks" — every Junie column
# reads N/A), a platform limit rather than a per-hook decision. Recorded here, not just in a
# comment, so a test can assert the reason is not empty (test_hooks_manifest_agent_coverage.py).
JUNIE_HOOK_EXEMPTION = (
    "Junie's own configuration ignores project-local hooks entirely — a platform limit, not a "
    "per-hook decision, so it never appears in HOOK_CAPABLE_AGENTS or in any hook's agents map."
)

# hook name -> {agent: reason} for a hook that deliberately does not reach one of
# HOOK_CAPABLE_AGENTS. Every reason is asserted non-trivial by
# tests/test_hooks_manifest_agent_coverage.py (the #145 review finding: an untested reason
# string is not a reason, only a key that happens to exist).
HOOKS_MANIFEST_AGENT_EXEMPTIONS: Dict[str, Dict[str, str]] = {
    "session-start-tracking": {
        "hermes": "Claude-only by design: recording the session id/transcript path, surfacing "
                  "unfinished tracked tasks, and starting the usage-limit poller are all Claude "
                  "Code concepts (transcript files, Claude's own usage limits) with no Hermes "
                  "analogue to wire onto.",
        "copilot": "Claude-only by design, same reasoning as the hermes exemption above: "
                   "nothing here maps onto a Copilot concept either.",
    },
    "task-checkpoint": {
        "hermes": "Claude-only for the same reason session-start-tracking is: the tracked-task "
                  "record this hook refreshes only ever exists because session-start-tracking "
                  "wrote a Claude session id onto it, and the numbers come from parsing that "
                  "session's Claude transcript JSONL, which Hermes does not produce. Wired onto "
                  "on_session_end it would match no task and measure nothing.",
        "copilot": "Claude-only, same reasoning as the hermes exemption above, plus a second "
                   "wall: Copilot has an agentStop event but keeps its usage in "
                   "~/.copilot/session-store.db rather than a transcript JSONL, and its hook "
                   "protocol has no block-with-reason channel for the enforcement half to use.",
    },
    "task-checkpoint-session-end": {
        "hermes": "Inherits the task-checkpoint exemption verbatim — same script, same "
                  "Claude-only tracked-task ledger and transcript JSONL, only a different "
                  "event. Hermes' on_session_end carries completed/interrupted booleans and "
                  "neither a session id nor a transcript path to checkpoint from.",
        "copilot": "Inherits the task-checkpoint exemption verbatim — same script, same "
                   "Claude-only tracked-task ledger and transcript JSONL. Copilot's sessionEnd "
                   "would fire correctly and find nothing to write.",
    },
    "dispatch-gate": {
        "hermes": "Nothing to gate: Hermes has no custom-agent files (support.json customAgents "
                  "supported=false), so a dispatch names no subagent type whose model lane could "
                  "cover it, and its subagent roles (leaf/orchestrator) carry no per-dispatch "
                  "model parameter for a hook to find missing.",
        "copilot": "Acknowledged gap on the model-lane half, a wall on the enforcement half: "
                   "Copilot does fire preToolUse and does keep a model in .github/agents/"
                   "*.agent.md frontmatter, so reading the lane is possible and simply has not "
                   "been done — but its hook protocol has no block-with-reason channel, and a "
                   "deny with the fix in it is this hook's entire output.",
    },
    "prompt-markers": {
        "hermes": "Acknowledged gap, not a design limit: marker detection (h:/f:/e:) has no "
                  "Hermes-side implementation yet, unlike session-start-tracking's Claude-only "
                  "design or Junie's platform limit — wiring it on Hermes is possible and simply "
                  "has not been done.",
    },
}

PROVENANCE_KEYS = ("frameworkCommit", "frameworkDirty")

PROVENANCE_HINT = (
    "This manifest predates ai-badger 0.2.0, which requires provenance keys "
    "(frameworkCommit, frameworkDirty). There is no migration by design — "
    "re-scaffold with welcome-ai-badger to upgrade it. Seed-once files "
    "(state.json, markers-context.json, agent-instructions/model.json) are preserved "
    "across a re-scaffold; "
    "review the diff before committing. See docs/adr/0001-versioning-and-release-model.md."
)


def provenance_hint(errors: List[str]) -> Optional[str]:
    """Return an actionable upgrade hint when errors are missing-provenance-key errors."""
    if any(key in err and "is a required property" in err
           for err in errors for key in PROVENANCE_KEYS):
        return PROVENANCE_HINT
    return None


def _report(label: str, errors) -> bool:
    if errors:
        print(f"INVALID  {label}")
        for e in errors:
            print(f"    - {e}")
        hint = provenance_hint(errors)
        if hint:
            print(f"    → {hint}")
        return False
    print(f"ok       {label}")
    return True


def undecided_schemas(root: Path) -> List[str]:
    """Schemas in schemas/ that SCHEMA_INSTANCES and the exemption list both ignore."""
    shipped = {p.name for p in (root / "schemas").glob("*.schema.json")}
    decided = set(SCHEMA_INSTANCES) | set(SCHEMAS_WITHOUT_LOCAL_INSTANCES)
    return sorted(shipped - decided)


def hooks_manifest_agent_gaps(root: Path) -> List[str]:
    """Every (hook, agent) pair reaching neither a manifest entry nor a recorded exemption.

    Walks every `hooks-manifest.json` this framework ships (currently exactly one,
    features/common/hooks/hooks-manifest.json) and checks each hook's `agents` map against
    HOOK_CAPABLE_AGENTS. A hook naming an agent is covered; a hook naming neither the agent nor
    an exemption in HOOKS_MANIFEST_AGENT_EXEMPTIONS is a gap — the shape issue #147 was the third
    occurrence of.
    """
    gaps: List[str] = []
    for manifest_path in sorted(root.glob("features/*/hooks/hooks-manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rel = manifest_path.relative_to(root)
        for hook in manifest.get("hooks", []):
            name = hook.get("name", "<unnamed>")
            agents = hook.get("agents", {})
            exemptions = HOOKS_MANIFEST_AGENT_EXEMPTIONS.get(name, {})
            for agent in HOOK_CAPABLE_AGENTS:
                if agent in agents or agent in exemptions:
                    continue
                gaps.append(
                    f"{rel}: hook '{name}' has no '{agent}' entry and no recorded exemption in "
                    f"HOOKS_MANIFEST_AGENT_EXEMPTIONS"
                )
    return gaps


def validate_all(root: Path) -> int:
    """Validate every catalog file SCHEMA_INSTANCES maps, plus the schemas themselves."""
    ok = True
    ok &= _report("schemas self-check", bl.check_schemas_selfvalid(root / "schemas"))

    undecided = undecided_schemas(root)
    if undecided:
        ok &= _report("schema coverage",
                      [f"{name} validates nothing: add it to SCHEMA_INSTANCES or to "
                       f"SCHEMAS_WITHOUT_LOCAL_INSTANCES with a reason" for name in undecided])

    for schema_name, patterns in sorted(SCHEMA_INSTANCES.items()):
        schema_path = root / "schemas" / schema_name
        if not schema_path.is_file():
            ok &= _report(f"schemas/{schema_name}", ["declared in SCHEMA_INSTANCES but missing"])
            continue
        for pattern in patterns:
            for instance in sorted(root.glob(pattern)):
                ok &= _report(str(instance.relative_to(root)),
                              bl.validate_file(instance, schema_path))

    gaps = hooks_manifest_agent_gaps(root)
    if gaps:
        ok &= _report("hooks-manifest agent coverage", gaps)
    return 0 if ok else 1


def main(argv=None) -> int:
    """CLI entry point: validate one instance (--schema/--kind) or the whole tree (--all)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("instance", nargs="?", help="Path to the JSON instance to validate.")
    ap.add_argument("--schema", help="Explicit schema path.")
    ap.add_argument("--kind", choices=sorted(KIND_TO_SCHEMA))
    ap.add_argument("--all", action="store_true", help="Validate the whole framework tree.")
    ap.add_argument("--root", help="Framework root (default: auto-detect).")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else bl.find_root()

    if args.all:
        return validate_all(root)

    if not args.instance:
        ap.error("provide an instance path or --all")
    inst = Path(args.instance).resolve()

    schema_path = None
    if args.schema:
        schema_path = Path(args.schema).resolve()
    elif args.kind:
        schema_path = root / "schemas" / KIND_TO_SCHEMA[args.kind]
    else:
        ap.error("provide --schema or --kind")

    ok = _report(str(inst), bl.validate_file(inst, schema_path))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
