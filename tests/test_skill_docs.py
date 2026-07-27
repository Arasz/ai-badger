"""A script a SKILL.md tells the agent to run must exist where it says it does."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# `python3 <path>.py` / `python3 "<path>.py"` — the form an agent copies and runs.
INVOCATION_RE = re.compile(r'python3\s+"?([^\s"\'`]+\.py)')

# `$AI_BADGER` is documented in welcome-ai-badger/SKILL.md as the framework root — the dir
# holding index.json and schemas/ — so a path under it resolves against the checkout.
FRAMEWORK_VAR = "$AI_BADGER/"

# Paths carrying a placeholder or another shell variable are addressed to a human or resolved
# at run time; only literal paths can be checked from here.
UNRESOLVABLE_PREFIXES = ("$", "<", "/", "~")

SKILL_DIRS = ("features/common/skills", "features/claude/skills")


def _skill_docs(root: Path):
    """Every SKILL.md in the catalog, as (skill_name, path)."""
    for base in SKILL_DIRS:
        for skill_md in sorted((root / base).glob("*/SKILL.md")):
            yield skill_md.parent.name, skill_md


def _invocations(skill_md: Path):
    """Literal script paths a reader is told to run, deduplicated in order."""
    found = [m.group(1) for m in INVOCATION_RE.finditer(skill_md.read_text(encoding="utf-8"))]
    return list(dict.fromkeys(p for p in found if not p.startswith(UNRESOLVABLE_PREFIXES)))


def _framework_invocations(skill_md: Path):
    """Script paths written as `$AI_BADGER/...`, stripped to be root-relative."""
    found = [m.group(1) for m in INVOCATION_RE.finditer(skill_md.read_text(encoding="utf-8"))]
    return list(dict.fromkeys(p[len(FRAMEWORK_VAR):]
                              for p in found if p.startswith(FRAMEWORK_VAR)))


class TestScaffoldedSkillPaths:
    """`.ai-badger/skills/<skill>/scripts/<x>.py` must name a script the catalog ships."""

    def test_every_scaffolded_path_names_a_real_script(self, root):
        missing = []
        for _skill, skill_md in _skill_docs(root):
            for path in _invocations(skill_md):
                if not path.startswith(".ai-badger/skills/"):
                    continue
                rel = path[len(".ai-badger/skills/"):]
                owner = rel.split("/", 1)[0]
                if not any((root / base / rel).exists() for base in SKILL_DIRS):
                    missing.append(f"{skill_md.relative_to(root)} -> {path} (skill {owner!r})")

        assert not missing, "SKILL.md points at scripts that do not exist:\n  " + "\n  ".join(missing)

    def test_no_skill_doc_uses_a_bare_cwd_relative_script_path(self, root):
        """`python3 scripts/x.py` resolves against the agent's cwd, which is the project root."""
        offenders = []
        for _skill, skill_md in _skill_docs(root):
            for path in _invocations(skill_md):
                if path.startswith("scripts/"):
                    offenders.append(f"{skill_md.relative_to(root)} -> {path}")

        assert not offenders, (
            "cwd-relative script paths are ambiguous — an agent runs from the project root, "
            "where these do not resolve. Use .ai-badger/skills/<skill>/scripts/<x>.py:\n  "
            + "\n  ".join(offenders)
        )


class TestFrameworkRelativePaths:
    """`$AI_BADGER/<path>` must resolve inside a framework checkout — it is the onboarding path."""

    def test_every_framework_relative_path_exists_in_the_checkout(self, root):
        missing = []
        for _skill, skill_md in _skill_docs(root):
            for rel in _framework_invocations(skill_md):
                if not (root / rel).exists():
                    missing.append(f"{skill_md.relative_to(root)} -> $AI_BADGER/{rel}")

        assert not missing, (
            "$AI_BADGER is the framework root (the dir holding index.json and schemas/). "
            "These paths do not exist there, so the documented command fails outright:\n  "
            + "\n  ".join(missing)
        )

    def test_the_check_actually_sees_something(self, root):
        """Guard against a vacuous pass if the regex or prefix ever stops matching."""
        total = sum(len(_framework_invocations(md)) for _skill, md in _skill_docs(root))

        assert total >= 5, f"expected several $AI_BADGER invocations, found {total}"


class TestConfigKeysNamedInDocsExist:
    """A SKILL.md that names a config key the schema forbids sends the reader into a hard stop."""

    def test_welcome_names_only_real_config_keys(self, root):
        import json  # pylint: disable=import-outside-toplevel

        schema = json.loads((root / "schemas" / "config.schema.json").read_text(encoding="utf-8"))
        text = (root / "features/common/skills/welcome-ai-badger/SKILL.md").read_text(
            encoding="utf-8")
        known = set(schema["properties"])

        # Only check names the doc presents as config keys in backticks and that look like ours.
        named = {m for m in re.findall(r'`([a-z][A-Za-z]+Scope)`', text)}

        assert named <= known, (
            f"SKILL.md names config key(s) the schema rejects: {sorted(named - known)}. "
            f"config.schema.json sets additionalProperties:false, so a config written from "
            f"this instruction fails validation. Known: {sorted(k for k in known if 'Scope' in k)}"
        )


class TestTaskTrackerIsReachable:
    """The task skill's tracking calls silently no-op if the path is wrong (see #92)."""

    def test_the_task_skill_points_at_the_scaffolded_tracker(self, root):
        text = (root / "features/common/skills/task/SKILL.md").read_text(encoding="utf-8")

        assert "python3 scripts/task_tracker.py" not in text
        assert ".ai-badger/skills/task/scripts/task_tracker.py" in text

    @pytest.mark.parametrize("subcommand", ["status", "start", "finish", "grade", "subagent"])
    def test_each_documented_subcommand_is_reachable(self, root, subcommand):
        text = (root / "features/common/skills/task/SKILL.md").read_text(encoding="utf-8")

        for line in text.splitlines():
            if f"task_tracker.py {subcommand}" in line:
                assert ".ai-badger/skills/task/scripts/task_tracker.py" in line, line.strip()
