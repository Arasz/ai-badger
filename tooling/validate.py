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
import re
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
    "model.schema.json": ["features/*/templates/agent-instructions/model.template.json"],
    "hooks.schema.json": ["features/*/hooks/hooks.json"],
    "mcp-tags.schema.json": ["features/*/mcp-tags.json"],
    "skill-extension.schema.json": ["features/*/skills/*/extensions/*/extension.json"],
}

# JSON under features/ that no schema validates, and why. A file matching neither a
# SCHEMA_INSTANCES glob nor one of these is a violation: SCHEMA_INSTANCES only proves a
# schema has instances, never that an instance has a schema (the review's A16).
FEATURE_JSON_WITHOUT_SCHEMA: Dict[str, str] = {
    "features/*/skills/*/hooks/settings-snippet.json":
        "a verbatim fragment of the agent's own settings.json, merged in as-is; its shape is "
        "the agent vendor's contract, not ours, so a schema here would only go stale",
    "features/*/skills/*/markers-context.json":
        "free-form prompt context the prompt-markers skill injects; the keys are prose slots "
        "the skill reads by name, with no cross-file contract to hold them to",
    "features/*/skills/*/evals/*.json":
        "retrieval eval fixtures (ADR-0012), consumed only by the eval harness that ships "
        "beside them; wired into no lane today, so a schema would outlive its only reader",
    "features/*/templates/agent-instructions/schema.json":
        "shipped output, not input: this is the JSON Schema a scaffolded project gets for its "
        "own agent-instructions model, and it is self-validating as a schema",
    "features/*/templates/state.json":
        "the seed body of a scaffolded project's .ai-badger/state.json; owned by the tracker "
        "that reads it in the consumer project, and it carries no framework-side contract",
}

# Stacks whose files are not checked for cross-stack references, and why.
CROSS_STACK_REFERENCE_EXEMPT: Dict[str, str] = {
    "common":
        "common ships in every scaffold and has no `requires` closure of its own to violate: "
        "its mentions of stack artifacts are illustrative examples inside prose, not "
        "instructions to go read a file. Checking it would mean hedging a dozen sentences "
        "rather than fixing a dangling pointer. The residual risk is real but bounded — a "
        "common skill naming a dotnet skill still reads oddly in a python-only project.",
}

# Feature directories carrying per-item artifacts a sibling stack's file may point at.
REFERENCEABLE_FEATURES = ("personas", "invariants", "instructions", "skills")

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
                  "design — wiring it on Hermes is possible and simply "
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


HOOKS_MANIFEST_GLOB = "features/*/hooks/hooks-manifest.json"


def hooks_manifest_agent_gaps(root: Path) -> List[str]:
    """Every (hook, agent) pair reaching neither a manifest entry nor a recorded exemption.

    Walks every `hooks-manifest.json` this framework ships (currently exactly one,
    features/common/hooks/hooks-manifest.json) and checks each hook's `agents` map against
    HOOK_CAPABLE_AGENTS. A hook naming an agent is covered; a hook naming neither the agent nor
    an exemption in HOOKS_MANIFEST_AGENT_EXEMPTIONS is a gap — the shape issue #147 was the third
    occurrence of. A glob matching no manifest at all is itself a gap: checking nothing and
    finding nothing are not the same answer.
    """
    manifests = sorted(root.glob(HOOKS_MANIFEST_GLOB))
    if not manifests:
        return [f"{HOOKS_MANIFEST_GLOB} matched no file: this check ran against no input"]
    gaps: List[str] = []
    for manifest_path in manifests:
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


# ---------------------------------------------------------------------------
# G4 skills lint — catalog SKILL.md conventions (docs/work/2026-08-07-opt-skills-plan.md Part C).
# One small pure function per rule; discovery glob mirrors index_build._skill_items
# (features/*/skills/*/SKILL.md, skipping *-extensions dirs).
# ---------------------------------------------------------------------------

NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024
MAX_LINES = 500
# chars/4 token proxy (deterministic stdlib; whitespace-token proxies undercount 1.53-1.75x and
# were rejected). Corpus max measured 2026-08-07: code-review-checklist body = 16,904 chars ->
# 4,226 proxy pre-#320; the post-#320 max was dotnet-mcp-server 52,524 chars -> 13,131 proxy,
# split to references/ in this PR; post-split max is worktree-agent-isolation at 4,922 proxy.
MAX_TOKENS = 5000

# G2/G4 rule 8 shared checker (the plan's G2 acceptance logic, one function): every
# `references/...` mention needs an explicit when/if/before/after/only-when condition on the
# mention line or within its 3-line context window {i-1, i, i+1}. Numbered-step lines and the
# explicit exemption list are skipped.
REFERENCES_CONDITION_RE = re.compile(r"\b(when|if|before|after|only when)\b", re.IGNORECASE)
NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s")
# Explicit exemption: a generic directory mention, not a file pointer (plan review round 1 R1-8).
# Keyed on (skill, the mention line's stripped text), never on a line number — the line-number
# key `scaffold-documentation:84` pointed at a line that had since gone blank, and nothing said
# so. test_every_references_exemption_still_names_a_line_that_exists keeps each anchor honest.
REFERENCES_EXEMPT = {
    ("scaffold-documentation",
     "**when placing a skill's reference material**, put it in a `references/` subdirectory "
     "*inside*"),
}


def references_without_conditions(lines: List[str], skill_name: str) -> List[str]:
    """G2 shared checker: references/ mentions lacking a condition in their 3-line window.

    Returns 1-indexed "{skill_name}:{line}" locators, the shape the plan's G2 acceptance script
    prints, so lint and acceptance share one predicate.
    """
    bad: List[str] = []
    for i, line in enumerate(lines, 1):
        if "references/" not in line or NUMBERED_STEP_RE.match(line):
            continue
        ctx = "\n".join(lines[max(0, i - 2):i + 1])
        if (skill_name, line.strip()) in REFERENCES_EXEMPT or REFERENCES_CONDITION_RE.search(ctx):
            continue
        bad.append(f"{skill_name}:{i}")
    return bad


# G1 gotchas rule: `## Gotchas` heading (the `(?:\d+\.\s+)?` accepts ai-raccoon-memory's
# `## 6. Gotchas`) or the one-line "no environment-specific gotchas known" note.
GOTCHAS_RE = re.compile(r"^##\s+(?:\d+\.\s+)?Gotchas\b", re.MULTILINE)
NO_GOTCHAS_NOTE_RE = re.compile(r"no environment-specific gotchas known", re.IGNORECASE)

# G3 frontmatter completeness gate: presence only, arrays may be empty.
REQUIRED_FRONTMATTER = ("name", "description", "version", "author", "license", "platforms",
                        "metadata.hermes.tags", "metadata.hermes.related_skills")

_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):\s*(.*)$")
_HERMES_KEY_RE = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_.-]*):\s*(.*)$")


def _metadata_hermes_fields(lines: List[str], start: int, end: int):
    """Parse the metadata: -> hermes: -> key: value block; (fields, next_index) or None.

    The only metadata shape the extractor understands is the canonical G3 block (metadata:
    followed directly by a 2-space-indented hermes: with 4-space-indented keys); anything else
    is a deterministic parse miss and is reported, never silently passed (ADR-0005: stdlib only,
    pyyaml stays optional).
    """
    if start >= end:
        return None
    if not lines[start].startswith("  hermes:") or lines[start].strip() != "hermes:":
        return None
    fields: Dict[str, str] = {}
    i = start + 1
    while i < end:
        line = lines[i]
        m = _HERMES_KEY_RE.match(line)
        if not m:
            if line[:1] in (" ", "\t"):
                i += 1
                continue
            break
        fields[f"metadata.hermes.{m.group(1)}"] = m.group(2).strip()
        i += 1
    return fields, i


def _frontmatter_fields(text: str) -> Optional[Dict[str, str]]:
    """Line-oriented frontmatter extractor (ADR-0005: no pyyaml for behavioural parsing).

    Returns {key: raw value}, metadata.hermes.* flattened to dotted keys, or None when the block
    cannot be parsed deterministically — a parse miss is a reported violation, never a pass.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return None
    fields: Dict[str, str] = {}
    i = 1
    while i < end:
        line = lines[i]
        m = _FRONTMATTER_KEY_RE.match(line)
        if not m:
            if line[:1] in (" ", "\t"):
                i += 1
                continue
            return None
        key, value = m.group(1), m.group(2).strip()
        if key == "metadata":
            if value:
                return None
            hermes = _metadata_hermes_fields(lines, i + 1, end)
            if hermes is None:
                return None
            fields.update(hermes[0])
            i = hermes[1]
            continue
        fields[key] = value
        i += 1
    return fields


SKILLS_GLOB = "features/*/skills/*/SKILL.md"


def skill_files(root: Path) -> List[Path]:
    """Every catalog SKILL.md the lint scans — every stack, not just common.

    Its own function so scope is one testable fact: narrowing this glob is what left 15 of 51
    shipped skills unlinted with 22 tests still green (the 2026-08-07 review's A5).
    """
    return sorted(root.glob(SKILLS_GLOB))


def duplicate_frontmatter_keys(text: str) -> List[str]:
    """Top-level frontmatter keys appearing more than once, in first-seen order.

    Counts raw `key:` lines rather than parsing YAML (ADR-0005: pyyaml stays optional) — a real
    parser resolves a duplicate to its *last* value silently, so a validator reading only the
    first would pass a file that every YAML-reading host reads differently. Rule 11 exists to
    make that divergence impossible rather than to guess which value wins.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return []
    seen: Dict[str, int] = {}
    order: List[str] = []
    for line in lines[1:end]:
        m = _FRONTMATTER_KEY_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 1:
            order.append(key)
    return [k for k in order if seen[k] > 1]


def skills_lint(root: Path) -> List[str]:
    """Convention violations across catalog SKILL.md files (plan G4 rules 1-10).

    Missing features/ (fake test roots) yields no violations. Body = text after the closing
    frontmatter fence; rules 3-5 reuse badger_lib.skill_description.
    """
    violations: List[str] = []
    for skill_md in skill_files(root):
        rel = skill_md.relative_to(root)
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, ValueError, UnicodeDecodeError):
            violations.append(f"{rel}: SKILL.md unreadable")
            continue
        parts = text.split("---", 2)
        body = parts[2] if len(parts) > 2 else text
        fields = _frontmatter_fields(text)
        fm_name = (fields or {}).get("name", "")
        desc = bl.skill_description(skill_md)

        if not NAME_RE.fullmatch(fm_name) or len(fm_name) > MAX_NAME_LEN:
            violations.append(
                f"{rel}: rule 1: name {fm_name!r} must match [a-z0-9]+(?:-[a-z0-9]+)* "
                f"and be <= {MAX_NAME_LEN} chars")
        if fm_name and fm_name != skill_md.parent.name:
            violations.append(
                f"{rel}: rule 2: frontmatter name {fm_name!r} != parent dir "
                f"{skill_md.parent.name!r}")
        if not desc:
            violations.append(f"{rel}: rule 3: description: key missing or empty after folding")
        else:
            if len(desc) > MAX_DESC_LEN:
                violations.append(
                    f"{rel}: rule 4: description is {len(desc)} chars > {MAX_DESC_LEN}")
            if not desc.startswith("Use when"):
                violations.append(f"{rel}: rule 5: description must start with 'Use when'")
        nlines = len(body.splitlines())
        if nlines > MAX_LINES:
            violations.append(f"{rel}: rule 6: body is {nlines} lines > {MAX_LINES}")
        proxy = len(body) / 4
        if proxy > MAX_TOKENS:
            violations.append(
                f"{rel}: rule 7: body chars/4 proxy {proxy:.0f} > {MAX_TOKENS}")
        for loc in references_without_conditions(text.splitlines(), skill_md.parent.name):
            violations.append(
                f"{rel}: rule 8: references/ mention at {loc} has no when/if/before/after/"
                f"only-when condition in its 3-line window")
        if not (GOTCHAS_RE.search(body) or NO_GOTCHAS_NOTE_RE.search(body)):
            violations.append(
                f"{rel}: rule 9: no '## Gotchas' section and no "
                f"'no environment-specific gotchas known' note")
        if fields is None:
            violations.append(
                f"{rel}: rule 10: frontmatter cannot be parsed deterministically by the "
                f"line-oriented extractor (no pyyaml; check the --- fence and key shape)")
        else:
            missing = [k for k in REQUIRED_FRONTMATTER if k not in fields]
            if missing:
                violations.append(
                    f"{rel}: rule 10: missing frontmatter keys: {', '.join(missing)}")
        for key in duplicate_frontmatter_keys(text):
            violations.append(
                f"{rel}: rule 11: frontmatter key {key!r} appears more than once "
                f"(a YAML parser resolves duplicates to the last value, not the first)")
    return violations


def catalog_stacks(root: Path) -> List[str]:
    """Stack names the catalog can actually deliver: a stack.json, a feature directory, or both.

    Mirrors index_build.build_index's own membership rule, so this set is exactly
    index.json.stacks without needing a built index to compare against.
    """
    names = {stack for stack, _, _ in bl.iter_feature_dirs(root)}
    features_root = root / "features"
    if features_root.is_dir():
        names |= {d.name for d in features_root.iterdir()
                  if d.is_dir() and (d / "stack.json").is_file()}
    return sorted(names)


def catalog_stack_gaps(root: Path) -> List[str]:
    """features/<dir> that delivers nothing — the shape features/github had (the review's C14)."""
    features_root = root / "features"
    if not features_root.is_dir():
        return []
    known = set(catalog_stacks(root))
    return [f"features/{d.name}: no stack.json and no feature directory, so the index never "
            f"sees it — populate it or delete it"
            for d in sorted(features_root.iterdir())
            if d.is_dir() and not d.name.startswith(".") and d.name not in known]


def config_stack_gaps(root: Path, config: Dict) -> List[str]:
    """Stacks a config selects that the catalog cannot deliver.

    `agents` names catalog directories as much as `stacks` does (badger_lib.delivering_stacks),
    so both are checked. config.schema.json states this rule only in a description string.
    """
    known = set(catalog_stacks(root))
    if not known:
        return []
    common = config.get("commonStacks", "common")
    selected = {
        "stacks": config.get("stacks") or [],
        "agents": config.get("agents") or [],
        "commonStacks": [common] if isinstance(common, str) else list(common or []),
    }
    return [f"config.{key} names {name!r}, which the catalog does not ship "
            f"(known: {', '.join(sorted(known))})"
            for key, names in selected.items() for name in names if name not in known]


def unschemad_feature_json(root: Path) -> List[str]:
    """JSON under features/ that no schema validates and no exemption names (the review's A16)."""
    features_root = root / "features"
    if not features_root.is_dir():
        return []
    covered = {p for patterns in SCHEMA_INSTANCES.values()
               for pattern in patterns for p in root.glob(pattern)}
    covered |= {p for pattern in FEATURE_JSON_WITHOUT_SCHEMA for p in root.glob(pattern)}
    return [f"{p.relative_to(root).as_posix()}: matched by no schema — add a SCHEMA_INSTANCES "
            f"glob or an entry in FEATURE_JSON_WITHOUT_SCHEMA with a reason"
            for p in sorted(features_root.rglob("*.json")) if p not in covered]


def _stack_requires(root: Path, stack: str) -> List[str]:
    sj = root / "features" / stack / "stack.json"
    return list(bl.load_json(sj).get("requires", [])) if sj.is_file() else []


def _requires_closure(root: Path, stack: str) -> set:
    out = {stack, "common"}
    pending = [stack]
    while pending:
        for req in _stack_requires(root, pending.pop()):
            if req not in out:
                out.add(req)
                pending.append(req)
    return out


def _artifact_owners(root: Path) -> Dict[str, set]:
    """Artifact name -> the stacks that ship it, over the referenceable feature types.

    Hyphenated names only: a bare one-word name (`mcp`, `css`, `task`) is ordinary prose
    wherever it appears, so matching it would report noise instead of dangling pointers.
    """
    owners: Dict[str, set] = {}
    for stack, feature, fdir in bl.iter_feature_dirs(root):
        if feature not in REFERENCEABLE_FEATURES:
            continue
        for item in sorted(fdir.iterdir()):
            name = item.name if item.is_dir() else item.stem
            if (item.is_dir() or item.suffix == ".md") and "-" in name:
                owners.setdefault(name, set()).add(stack)
    return owners


def cross_stack_reference_gaps(root: Path) -> List[str]:
    """A stack's file naming an artifact only another, undeclared stack ships (the review's C8).

    `features/dotnet` declares `requires: []`, so a dotnet-only scaffold has no
    `cloud-infra-engineer` — yet its persona sent readers to one.
    """
    owners = _artifact_owners(root)
    gaps: List[str] = []
    for stack_dir in sorted(p for p in (root / "features").glob("*") if p.is_dir()):
        stack = stack_dir.name
        if stack in CROSS_STACK_REFERENCE_EXEMPT:
            continue
        closure = _requires_closure(root, stack)
        candidates = [(n, o) for n, o in owners.items() if not o & closure]
        for path in sorted(stack_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            gaps += [
                f"{path.relative_to(root).as_posix()}: names {name!r}, shipped only by "
                f"{'/'.join(sorted(own))}, which {stack} does not require"
                for name, own in candidates
                if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text)]
    return sorted(gaps)


def validate_all(root: Path) -> int:
    """Validate every catalog file SCHEMA_INSTANCES maps, plus the schemas themselves."""
    ok = True
    ok &= _report("schemas self-check", bl.check_schemas_selfvalid(root / "schemas"))

    ok &= _report("schema coverage",
                  [f"{name} validates nothing: add it to SCHEMA_INSTANCES or to "
                   f"SCHEMAS_WITHOUT_LOCAL_INSTANCES with a reason"
                   for name in undecided_schemas(root)])

    for schema_name, patterns in sorted(SCHEMA_INSTANCES.items()):
        schema_path = root / "schemas" / schema_name
        if not schema_path.is_file():
            ok &= _report(f"schemas/{schema_name}", ["declared in SCHEMA_INSTANCES but missing"])
            continue
        for pattern in patterns:
            for instance in sorted(root.glob(pattern)):
                ok &= _report(str(instance.relative_to(root)),
                              bl.validate_file(instance, schema_path))

    ok &= _report("catalog stack membership", catalog_stack_gaps(root))
    ok &= _report("feature json schema coverage", unschemad_feature_json(root))
    ok &= _report("cross-stack references", cross_stack_reference_gaps(root))
    ok &= _report("hooks-manifest agent coverage", hooks_manifest_agent_gaps(root))
    ok &= _report("skills lint", skills_lint(root))
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
    if ok and schema_path.name == KIND_TO_SCHEMA["config"]:
        # The schema states stack membership only in a description string; a config selecting a
        # stack the catalog cannot deliver is otherwise valid (the review's C14).
        ok &= _report("config stack membership", config_stack_gaps(root, bl.load_json(inst)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())