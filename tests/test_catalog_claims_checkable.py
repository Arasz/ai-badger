"""The catalog's own claims, checked: stack membership, schema coverage, cross-stack refs.

Three claims the catalog made in prose and nothing verified (review C14, A16, C8):
a config may only select stacks the catalog ships, every JSON under features/ is either
schema'd or exempt by name, and a stack's files may only point at artifacts its declared
`requires` closure delivers.
"""
from __future__ import annotations

import json
import subprocess

import pytest


def _config(**over):
    cfg = {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "p", "summary": "s", "domain": "d"},
        "stacks": ["python"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }
    cfg.update(over)
    return cfg


# ── C14: a config may only select stacks the catalog ships ────────────────────────────

def test_a_config_selecting_a_stack_outside_the_catalog_fails_validation(
        tmp_path, root, load_script, capsys):
    """The rule lived only in config.schema.json's description string, so nothing enforced it."""
    validate = load_script("tooling/validate.py")
    instance = tmp_path / "config.json"
    instance.write_text(json.dumps(_config(stacks=["python", "not-a-real-stack"])),
                        encoding="utf-8")

    rc = validate.main(["--kind", "config", "--root", str(root), str(instance)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "not-a-real-stack" in out


def test_a_config_selecting_only_catalog_stacks_still_passes(tmp_path, root, load_script):
    validate = load_script("tooling/validate.py")
    instance = tmp_path / "config.json"
    instance.write_text(json.dumps(_config(stacks=["python", "github", "dotnet"])),
                        encoding="utf-8")

    assert validate.main(["--kind", "config", "--root", str(root), str(instance)]) == 0


def test_an_agent_name_is_a_catalog_stack_too_and_must_exist(tmp_path, root, load_script,
                                                             capsys):
    """`agents` names catalog directories as much as `stacks` does (badger_lib.delivering_stacks),
    so an agent the catalog cannot deliver is the same defect."""
    validate = load_script("tooling/validate.py")
    instance = tmp_path / "config.json"
    cfg = _config()
    cfg["agents"] = ["copilot"]
    instance.write_text(json.dumps(cfg), encoding="utf-8")
    assert validate.main(["--kind", "config", "--root", str(root), str(instance)]) == 0

    assert validate.config_stack_gaps(root, _config(stacks=["python"], agents=["ghost"]))


def test_this_repos_own_config_selects_only_stacks_the_catalog_ships(root, load_script):
    """github was advertised in CLAUDE.md and selected here while absent from the catalog index."""
    validate = load_script("tooling/validate.py")
    config = json.loads((root / ".ai-badger" / "config.json").read_text(encoding="utf-8"))

    assert validate.config_stack_gaps(root, config) == []


def test_every_directory_under_features_is_a_stack_the_index_can_see(root, load_script):
    """features/github held one skills.json and nothing indexable, so index.json never saw it."""
    validate = load_script("tooling/validate.py")

    assert validate.catalog_stack_gaps(root) == []


def test_a_features_directory_with_nothing_indexable_is_reported(tmp_path, root, load_script):
    """The exact shape features/github had: a directory, a stub json, no stack.json, no feature."""
    validate = load_script("tooling/validate.py")
    shell = tmp_path / "features" / "ghost"
    shell.mkdir(parents=True)
    (shell / "skills.json").write_text('{"skills": []}', encoding="utf-8")

    gaps = validate.catalog_stack_gaps(tmp_path)

    assert any("ghost" in g for g in gaps), gaps


def test_a_dot_directory_under_features_is_not_a_candidate_stack(tmp_path, root, load_script):
    """The non-git fallback's own rule: local state lands in features/.ai-badger/, never a stack."""
    validate = load_script("tooling/validate.py")
    stray = tmp_path / "features" / ".ai-badger" / "task-tracking"
    stray.mkdir(parents=True)
    (stray / "poll_limit.pid").write_text("1234", encoding="utf-8")

    assert validate.catalog_stack_gaps(tmp_path) == []


def _committed_catalog(tmp_path):
    """A git checkout whose features/ holds one committed stack directory."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.email", "t@example.com"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    stack = tmp_path / "features" / "python" / "skills" / "demo"
    stack.mkdir(parents=True)
    (stack / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "catalog"], check=True)
    return tmp_path


def test_an_untracked_directory_under_features_cannot_fail_validation(
        tmp_path, root, load_script):
    """A validator that read the working tree failed on whatever the session left behind."""
    validate = load_script("tooling/validate.py")
    checkout = _committed_catalog(tmp_path)
    scratch = checkout / "features" / "scratchdir"
    scratch.mkdir()
    (scratch / "skills.json").write_text('{"skills": []}', encoding="utf-8")

    assert validate.catalog_stack_gaps(checkout) == []


def test_a_committed_directory_the_index_cannot_deliver_is_still_reported(
        tmp_path, root, load_script):
    """features/github's exact shape, committed: reading HEAD must not cost the real check."""
    validate = load_script("tooling/validate.py")
    checkout = _committed_catalog(tmp_path)
    ghost = checkout / "features" / "ghoststack"
    ghost.mkdir()
    (ghost / "skills.json").write_text('{"skills": []}', encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(checkout), "commit", "-qm", "ghoststack"], check=True)

    gaps = validate.catalog_stack_gaps(checkout)

    assert any("ghoststack" in g for g in gaps), gaps


def test_a_committed_dot_directory_is_not_a_candidate_stack_either(
        tmp_path, root, load_script):
    """The same rule on the branch that actually runs: every real checkout has an index, so
    `git ls-tree` answers and the working-tree fallback never executes here."""
    validate = load_script("tooling/validate.py")
    checkout = _committed_catalog(tmp_path)
    stray = checkout / "features" / ".ai-badger"
    stray.mkdir()
    (stray / "config.json").write_text("{}", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "-Af"], check=True)
    subprocess.run(["git", "-C", str(checkout), "commit", "-qm", "local state"], check=True)

    assert ".ai-badger" not in validate.candidate_stack_dirs(checkout)
    assert validate.catalog_stack_gaps(checkout) == []


# ── A16: every JSON under features/ is schema'd or exempt by name ─────────────────────

def test_every_json_under_features_is_schemad_or_exempt_by_name(root, load_script):
    validate = load_script("tooling/validate.py")

    assert validate.unschemad_feature_json(root) == []


@pytest.mark.parametrize("rel", [
    "features/common/hooks/hooks.json",
    "features/common/mcp-tags.json",
    "features/common/skills/task/extensions/github/extension.json",
])
def test_the_three_named_unschemad_families_now_have_a_schema(rel, root, load_script):
    """A16 named these specifically; an exemption for them would be the wrong answer."""
    validate = load_script("tooling/validate.py")
    path = root / rel
    assert path.is_file()

    matched = [name for name, patterns in validate.SCHEMA_INSTANCES.items()
               for pattern in patterns if path in set(root.glob(pattern))]

    assert matched, f"{rel} is still matched by no SCHEMA_INSTANCES glob"


def test_a_new_unschemad_json_under_features_is_a_violation(tmp_path, load_script):
    """The check has to fail for a file nobody thought about — that is its whole job."""
    validate = load_script("tooling/validate.py")
    stray = tmp_path / "features" / "python" / "surprise.json"
    stray.parent.mkdir(parents=True)
    stray.write_text("{}", encoding="utf-8")

    gaps = validate.unschemad_feature_json(tmp_path)

    assert any("surprise.json" in g for g in gaps), gaps


def test_every_feature_json_exemption_matches_a_file_that_exists(root, load_script):
    """A mis-keyed exemption is an exemption for nothing — and it hides the file it named."""
    validate = load_script("tooling/validate.py")

    inert = [pattern for pattern in validate.FEATURE_JSON_WITHOUT_SCHEMA
             if not list(root.glob(pattern))]

    assert inert == [], f"these exemptions cover no file: {inert}"


def test_every_feature_json_exemption_states_a_reason(root, load_script):
    validate = load_script("tooling/validate.py")

    thin = {p: r for p, r in validate.FEATURE_JSON_WITHOUT_SCHEMA.items() if len(r) < 30}

    assert thin == {}


# ── C8: a stack may only point at artifacts its `requires` closure delivers ───────────

def test_no_dotnet_file_points_at_an_artifact_from_an_undeclared_stack(root, load_script):
    """features/dotnet declares requires: [] but its persona sent readers to
    cloud-infra-engineer, which ships only with features/azure."""
    validate = load_script("tooling/validate.py")

    dotnet = [g for g in validate.cross_stack_reference_gaps(root) if "features/dotnet" in g]

    assert dotnet == []


def test_no_stack_points_at_an_artifact_from_an_undeclared_stack(root, load_script):
    validate = load_script("tooling/validate.py")

    assert validate.cross_stack_reference_gaps(root) == []


def test_a_reference_to_another_stacks_persona_is_reported(tmp_path, root, load_script):
    validate = load_script("tooling/validate.py")
    (tmp_path / "features" / "azure" / "personas").mkdir(parents=True)
    (tmp_path / "features" / "azure" / "personas" / "cloud-infra-engineer.md").write_text(
        "# persona", encoding="utf-8")
    (tmp_path / "features" / "dotnet" / "personas").mkdir(parents=True)
    (tmp_path / "features" / "dotnet" / "stack.json").write_text(
        json.dumps({"name": "dotnet", "requires": []}), encoding="utf-8")
    (tmp_path / "features" / "dotnet" / "personas" / "dotnet-engineer.md").write_text(
        "ask the cloud-infra-engineer instead", encoding="utf-8")

    gaps = validate.cross_stack_reference_gaps(tmp_path)

    assert any("cloud-infra-engineer" in g for g in gaps), gaps


def test_declaring_the_requires_clears_the_cross_stack_reference(tmp_path, load_script):
    """The rule is about the declared closure, not about the word being forbidden."""
    validate = load_script("tooling/validate.py")
    (tmp_path / "features" / "azure" / "personas").mkdir(parents=True)
    (tmp_path / "features" / "azure" / "personas" / "cloud-infra-engineer.md").write_text(
        "# persona", encoding="utf-8")
    (tmp_path / "features" / "dotnet" / "personas").mkdir(parents=True)
    (tmp_path / "features" / "dotnet" / "stack.json").write_text(
        json.dumps({"name": "dotnet", "requires": ["azure"]}), encoding="utf-8")
    (tmp_path / "features" / "dotnet" / "personas" / "dotnet-engineer.md").write_text(
        "ask the cloud-infra-engineer instead", encoding="utf-8")

    assert validate.cross_stack_reference_gaps(tmp_path) == []


def test_the_cross_stack_exemption_list_is_named_and_reasoned(load_script):
    validate = load_script("tooling/validate.py")

    assert set(validate.CROSS_STACK_REFERENCE_EXEMPT) == {"common"}
    assert len(validate.CROSS_STACK_REFERENCE_EXEMPT["common"]) >= 40


# ── the three checks reach --all, and say so even when clean ──────────────────────────

def test_all_reports_every_new_catalog_check_even_when_there_is_nothing_to_say(
        root, load_script, capsys):
    validate = load_script("tooling/validate.py")

    rc = validate.main(["--all", "--root", str(root)])

    out = capsys.readouterr().out
    assert rc == 0, out
    for label in ("catalog stack membership", "feature json schema coverage",
                  "cross-stack references"):
        assert f"ok       {label}" in out, out
