"""The review-flow skill doc must agree with the coordinator CLI it describes.

Convention for naming a verb in SKILL.md: every CLI call is written `review_flow_cli.py <verb>`
(in a code span or a code block). The test collects each `review_flow_cli.py <verb>` token and
compares that set with the CLI's verb registry. A verb in prose alone does not count.
"""
from __future__ import annotations

import json
import re
import typing
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "features" / "common" / "skills" / "review-flow"
CLI_RELPATH = "features/common/skills/review-flow/scripts/review_flow_cli.py"
VERB_CALL = re.compile(r"review_flow_cli\.py\s+([a-z][a-z0-9-]*)")
HEADING = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


@pytest.fixture(name="cli")
def _cli(load_script):
    return load_script(CLI_RELPATH)


def _skill_text() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def _brief_sections() -> dict:
    text = (SKILL_DIR / "references" / "worker-briefs.md").read_text(encoding="utf-8")
    matches = list(HEADING.finditer(text))
    return {m.group(1): text[m.end():matches[i + 1].start() if i + 1 < len(matches) else None]
            for i, m in enumerate(matches)}


def test_review_flow_passes_lint(load_script):
    lint = load_script("gates/skills_lint.py")
    mine = [v for v in lint.skills_lint(ROOT) if "skills/review-flow/" in v]
    assert mine == []


def test_verbs_in_doc_equal_verbs_in_cli(cli):
    named = set(VERB_CALL.findall(_skill_text()))
    assert named, "SKILL.md names no `review_flow_cli.py <verb>` call"
    assert named == set(cli.VERBS), (
        f"doc only: {sorted(named - set(cli.VERBS))}; cli only: {sorted(set(cli.VERBS) - named)}")


def test_every_rules_action_is_named_in_the_doc(cli):
    actions = typing.get_args(cli.RulesArgs.model_fields["action"].annotation)
    text = _skill_text()
    missing = [action for action in actions if f'"action": "{action}"' not in text]
    assert missing == []


def test_every_brief_names_persona_and_schema(cli):
    sections = _brief_sections()
    assert set(sections) == set(cli.BRIEF_KINDS) == set(cli.BRIEF_PERSONA)
    for kind, body in sections.items():
        assert f"Persona: `{cli.BRIEF_PERSONA[kind]}`" in body, kind
        assert f"`{cli.BRIEF_SCHEMA[kind]}`" in body, kind
        phase = cli.BRIEF_PHASE[kind].value
        assert f'"phase": "{phase}"' in body, f"{kind}: no submit call for phase {phase}"


def test_limited_env_extension_is_gated_like_the_task_skill():
    ext = SKILL_DIR / "extensions" / "limited-env"
    gate = json.loads((ext / "extension.json").read_text(encoding="utf-8"))
    task_gate = json.loads((ROOT / "features" / "common" / "skills" / "task" / "extensions"
                            / "limited-env" / "extension.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / "skill-extension.schema.json")
                        .read_text(encoding="utf-8"))
    jsonschema.validate(gate, schema)
    assert (gate["skill"], gate["extension"]) == ("review-flow", "limited-env")
    assert gate["requires"] == task_gate["requires"]
    body = (ext / "extension.md").read_text(encoding="utf-8")
    for needle in ("python3", "exit 3", "git diff", '"dry_run": true'):
        assert needle in body, needle
