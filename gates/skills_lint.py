#!/usr/bin/env python3
"""Fail when a catalog SKILL.md breaks one of the thirteen conventions the framework relies on.

Thirteen rules here is distinct from rule 10's eight required frontmatter keys. A repo gate,
not a schema check: it reads prose and frontmatter rather than validating JSON manifests
beyond their own structure, which is why it no longer lives in tooling/validate.py.
`validate.py --all` still reports it,
so CI and the pre-push lane cover it exactly as before; this file is what they both call.

Usage: skills_lint.py [--root <dir>]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# The engine lives in engine/: is_framework_root anchors on engine/badger_lib.py (ADR-0011).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import badger_lib as bl
import frontmatter as fm


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
# Empty since 0.137.0: the scaffold-documentation entry left with its skill into the
# documentation gateway, whose members sit below this lint's reach.
REFERENCES_EXEMPT = set()


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

_HERMES_KEY_RE = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_.-]*):\s*(.*)$")


def _metadata_hermes_fields(lines) -> Optional[Dict[str, str]]:
    """The `metadata:` entry's `hermes:` block flattened to dotted keys, or None.

    The only metadata shape this understands is the canonical G3 block (`metadata:` followed
    directly by a 2-space-indented `hermes:` with 4-space-indented keys); anything else is a
    deterministic parse miss and is reported, never silently passed.
    """
    if len(lines) < 2 or lines[1].strip() != "hermes:" or not lines[1].startswith("  hermes:"):
        return None
    fields: Dict[str, str] = {}
    for line in lines[2:]:
        match = _HERMES_KEY_RE.match(line)
        if match:
            fields[f"metadata.hermes.{match.group(1)}"] = match.group(2).strip()
    return fields


def frontmatter_fields(text: str) -> Optional[Dict[str, str]]:
    """{key: value} with metadata.hermes.* flattened, or None when the block will not resolve.

    A parse miss is rule 10's reported violation, never a pass: the catalog must be readable
    by a line-oriented reader, because ADR-0005 keeps pyyaml optional.
    """
    split = fm.split(text)
    if not split.present or not split.well_formed:
        return None
    fields: Dict[str, str] = {}
    for entry in split.entries:
        if entry.key != "metadata":
            fields[entry.key] = entry.value()
            continue
        if entry.inline:
            return None
        hermes = _metadata_hermes_fields(entry.lines)
        if hermes is None:
            return None
        fields.update(hermes)
    return fields


SKILLS_GLOB = "features/*/skills/*/SKILL.md"

# Rule 12 (ADR-0018) applies to the common catalog alone: `stack_local_skills` ships a stack's
# whole directory whatever its scope, so requiring the key on the other stacks would be a value
# nothing reads. `skill_scope_in` is the predicate production routes on, so the lint's guarantee
# is exactly "what the scaffolder will read is one of the two scopes".
SCOPED_STACKS = tuple(bl.DEFAULT_COMMON_STACKS)


def skill_files(root: Path) -> List[Path]:
    """Every catalog SKILL.md the lint scans — every stack, not just common.

    Its own function so scope is one testable fact: narrowing this glob is what left 15 of 51
    shipped skills unlinted with 22 tests still green (the 2026-08-07 review's A5).
    """
    return sorted(root.glob(SKILLS_GLOB))


# ---------------------------------------------------------------------------
# Rule 13 — gateway manifest validation. A level-1 skill dir carrying manifest.json is a
# gateway; its members live under references/<member>/, one nesting level below registration,
# so the manifest is the only declaration they exist. Everything here derives from disk.
# ---------------------------------------------------------------------------
GATEWAY_KIND = "gateway"
GATEWAY_MANIFEST = "manifest.json"
GATEWAY_REFERENCES_DIR = "references"
MEMBER_OPTIONAL_PATHS = ("scripts", "references")


def _member_problems(skill_dir: Path, rel: str, member: Dict[str, Any],
                     seen: Dict[str, int]) -> List[str]:
    """Rule-13 violations for one member entry."""
    problems: List[str] = []
    name = member.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name or ""):
        return [f"{rel}: rule 13: member name {name!r} must match the skill name grammar"]
    seen[name] = seen.get(name, 0) + 1
    if seen[name] > 1:
        problems.append(
            f"{rel}: rule 13: member name {name!r} appears more than once — "
            f"member names must be unique within the manifest")
    paths = member.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get("skill"), str):
        return problems + [f"{rel}: rule 13: member {name!r} needs paths.skill naming "
                           f"its directory under {GATEWAY_REFERENCES_DIR}/"]
    expected = f"{GATEWAY_REFERENCES_DIR}/{name}"
    if paths["skill"] != expected:
        problems.append(
            f"{rel}: rule 13: member {name!r} paths.skill {paths['skill']!r} does not "
            f"match its directory name (expected {expected!r})")
    skill_md = skill_dir / paths["skill"] / "SKILL.md"
    if not skill_md.is_file():
        problems.append(
            f"{rel}: rule 13: member {name!r} points at {paths['skill']}/SKILL.md, "
            f"which does not exist")
    else:
        purpose = member.get("purpose")
        declared = bl.skill_description(skill_md)
        if not isinstance(purpose, str) or not purpose:
            problems.append(
                f"{rel}: rule 13: member {name!r} has no purpose — it must equal the "
                f"member's frontmatter description verbatim")
        elif purpose != declared:
            problems.append(
                f"{rel}: rule 13: member {name!r} purpose differs from its SKILL.md "
                f"description — copy it verbatim, never paraphrase")
    triggers = member.get("triggers")
    if not isinstance(triggers, list) or not triggers or \
            not all(isinstance(t, str) and t for t in triggers):
        problems.append(
            f"{rel}: rule 13: member {name!r} triggers must be a non-empty list of strings")
    for key in MEMBER_OPTIONAL_PATHS:
        optional = paths.get(key)
        if optional is not None and not (skill_dir / optional).exists():
            problems.append(
                f"{rel}: rule 13: member {name!r} paths.{key} {optional!r} does not exist")
    return problems


def gateway_manifest_violations(root: Path) -> List[str]:
    """Rule 13 across every gateway candidate: features/*/skills/*/manifest.json on disk."""
    violations: List[str] = []
    for manifest_path in sorted(root.glob(f"features/*/skills/*/{GATEWAY_MANIFEST}")):
        skill_dir = manifest_path.parent
        rel = skill_dir.relative_to(root).as_posix()
        try:
            manifest = bl.load_json(manifest_path)
        except (OSError, ValueError) as exc:
            violations.append(f"{rel}: rule 13: {GATEWAY_MANIFEST} is not valid JSON: {exc}")
            continue
        if manifest.get("kind") != GATEWAY_KIND:
            violations.append(
                f"{rel}: rule 13: {GATEWAY_MANIFEST} must declare \"kind\": \"{GATEWAY_KIND}\"")
        members = manifest.get("members")
        if not isinstance(members, list) or not members:
            violations.append(f"{rel}: rule 13: members must be a non-empty list")
            continue
        seen: Dict[str, int] = {}
        for member in members:
            if not isinstance(member, dict):
                violations.append(f"{rel}: rule 13: each member must be an object")
                continue
            violations.extend(_member_problems(skill_dir, rel, member, seen))
        references = skill_dir / GATEWAY_REFERENCES_DIR
        if references.is_dir():
            claimed = set(seen)
            for child in sorted(references.iterdir()):
                if child.is_dir() and child.name not in claimed:
                    violations.append(
                        f"{rel}: rule 13: orphan member dir {child.name!r} under "
                        f"{GATEWAY_REFERENCES_DIR}/ is named by no manifest member")
    return violations


def skills_lint(root: Path) -> List[str]:
    """Convention violations across catalog SKILL.md files (plan G4 rules 1-10, plus 11-12).

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
        body = fm.split(text).body or text
        fields = frontmatter_fields(text)
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
        for key in fm.split(text).duplicate_keys():
            violations.append(
                f"{rel}: rule 11: frontmatter key {key!r} appears more than once "
                f"(a YAML parser resolves duplicates to the last value, not the first)")
        if skill_md.parents[2].name in SCOPED_STACKS and bl.skill_scope_in(skill_md.parent) is None:
            violations.append(
                f"{rel}: rule 12: no readable scope: key — a common-stack skill declares "
                f"{bl.SKILL_SCOPE_DEFAULT!r} (ships unasked) or {bl.SKILL_SCOPE_OPT_IN!r} "
                f"(ships when a project names it) in its own frontmatter")
    violations.extend(gateway_manifest_violations(root))
    return violations


def main(argv=None) -> int:
    """CLI entry point: report every violation in the catalog, or say there are none."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Framework root (default: auto-detect).")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else bl.find_root()

    violations = skills_lint(root)
    if not violations:
        print(f"ok       skills lint — {len(skill_files(root))} SKILL.md checked")
        return 0
    print("SKILLS LINT FAILED")
    for violation in violations:
        print(f"    - {violation}")
    print("Fix each violation above, or change the rule in gates/skills_lint.py.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
