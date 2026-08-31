"""The --skills argv is a contract, not a suggestion: quoting artifacts and unknown names are
refused (task aib-scaffold-freshness-guard-blindspot-proof, D3).

The defect: the printed remediation `--skills ''` is shell-safe, but any non-shell transport
delivers the literal two-character `''` as a skill "name" — truthy, so the #129 recovery is
bypassed, the name is silently skipped, and the run under-delivers (the ea17ae60 shape).
Refusals close that hole; the true-empty recovery mode itself is untouched (pinned by
test_scaffold_empty_skills.py and re-pinned here per transport).
"""
from __future__ import annotations

import json

import pytest
from conftest import _test_write
from scaffold_helpers import _config

SCRIPT = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"
INVALID = "SCAFFOLD ARGV INVALID"


def _write_config(config_path, stacks=None):
    _test_write(config_path, json.dumps(_config(stacks=stacks)), encoding="utf-8")


def _run(scaffold, config_path, target, root, skills_argv):
    return scaffold.main(["--config", str(config_path), "--target", str(target),
                          "--root", str(root), *skills_argv, "--no-install"])


@pytest.mark.parametrize("value", ["''", '""', " task ", "task\\"])
def test_a_quoting_artifact_is_refused_with_a_named_message(
        tmp_path, load_script, root, capsys, value):
    """A quote character or untrimmed whitespace in a name is a transport artifact, never a
    skill: refused with exit 2 before anything is scaffolded."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", value]) == 2

    out = capsys.readouterr().out
    assert INVALID in out
    assert "not scaffolded" not in out  # the refusal precedes any scaffold work


def test_an_alias_absorbed_name_is_refused_naming_the_gateway(
        tmp_path, load_script, root, capsys):
    """`migrate-documentation` is a real config.include name from before the documentation
    gateway absorbed it: today it silently delivers nothing. Refused, with the gateway named."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", "migrate-documentation"]) == 2

    out = capsys.readouterr().out
    assert INVALID in out
    assert "documentation" in out


def test_a_garbage_name_is_refused_without_an_alias_hint(
        tmp_path, load_script, root, capsys):
    """A typo fails loudly instead of printing a skip note and exiting 0."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", "no-such-skill"]) == 2

    assert INVALID in capsys.readouterr().out


def test_a_manifest_recorded_name_is_allowed_even_when_the_catalog_dropped_it(
        tmp_path, load_script, root, capsys):
    """The catalog-drop flow: a name the framework no longer ships but the target manifest
    still records keeps working (the skill is then skipped per find_skill_in_stacks)."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", "task"]) == 0
    manifest_path = target / ".ai-badger" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"].append({"target": ".ai-badger/skills/ghost-skill", "feature": "skills",
                                "name": "ghost-skill", "stack": "common",
                                "source": "features/common/skills/ghost-skill",
                                "hash": "0" * 64})
    _test_write(manifest_path, json.dumps(manifest), encoding="utf-8")
    capsys.readouterr()

    assert _run(scaffold, config_path, target, root, ["--skills", "ghost-skill"]) == 0


@pytest.mark.parametrize("value", ["", ","])
def test_true_empty_values_still_recover_the_manifest_set(
        tmp_path, load_script, root, capsys, value):
    """#129 recovery is untouched: both shell-renderable empty forms recover, not refuse."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", "task,prompt-markers"]) == 0
    capsys.readouterr()
    assert _run(scaffold, config_path, target, root, ["--skills", value]) == 0

    assert "reused 2 skill(s)" in capsys.readouterr().out


def test_the_printed_empty_value_cannot_change_outcome_by_transport(
        tmp_path, load_script, root, capsys):
    """D6b, per transport (QA-F4): a non-shell transport of the printed `--skills ''` advice
    carries the literal two quotes as a name — refused, never silently under-delivering; the
    shell transport strips them, argv receives a true empty value, and recovery runs. The two
    transports do NOT produce the same outcome; neither one under-delivers."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", "task,prompt-markers"]) == 0
    capsys.readouterr()

    # list-form transport: the quote characters arrive in argv as a bogus name → refused.
    assert _run(scaffold, config_path, target, root, ["--skills", "''"]) == 2
    out = capsys.readouterr().out
    assert INVALID in out
    assert "reused" not in out

    # shell transport: quotes are shell syntax → true-empty value → recovery to the full set.
    assert _run(scaffold, config_path, target, root, ["--skills", ""]) == 0
    assert "reused 2 skill(s)" in capsys.readouterr().out


def test_narrow_argv_delivers_no_scope_default_skill(tmp_path, load_script, root):
    """The explicit argv REPLACES the catalog defaults (V10): `--skills task` on a stack with
    no stack-local skills delivers exactly task — no scope-default skill leaks in. This pins
    the Scaffolder refactor shape: the config-derived expected set must never widen a narrow
    argv (API-F2)."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    _write_config(config_path, stacks=["node"])
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, ["--skills", "task"]) == 0

    manifest = json.loads((target / ".ai-badger" / "manifest.json").read_text(encoding="utf-8"))
    names = [e["name"] for e in manifest["entries"]
             if e.get("feature") == "skills" and "/" not in e.get("name", "")]
    assert names == ["task"]
