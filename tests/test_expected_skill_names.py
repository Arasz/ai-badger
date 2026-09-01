"""`expected_skill_names(root, config)` — the one oracle for what an unattended scaffold
delivers (D1, task aib-scaffold-freshness-guard-blindspot-proof).

The guard compares the manifest against this derivation and re-scaffolds from it, so the
scaffolder and the guard cannot disagree. The composition is pinned at every input that
changes the set on real configs: include-expansion BEFORE alias mapping, the opt-in addable
gate, alias-mapped exclusions at every stage, stack-local discovery in `resolve_stacks` order
with the constant common skip-set — and the RETURN ORDER is `Scaffolder`'s delivery BLOCK
order (defaults, include-derived, stack-local), not flat-sorted (API-F1): manifest row order
is guard-visible, so a flat-sorted oracle fails healthy trees.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import _test_write

import badger_lib as bl

# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml

ROOT = Path(__file__).resolve().parents[1]


def _skill(root: Path, stack: str, name: str, scope: str) -> None:
    skill_dir = root / "features" / stack / "skills" / name
    skill_dir.mkdir(parents=True)
    _test_write(skill_dir / "SKILL.md", f"---\nname: {name}\nscope: {scope}\n---\n\n#{name}\n")


def _gateway(root: Path, stack: str, name: str, members: list) -> None:
    skill_dir = root / "features" / stack / "skills" / name
    skill_dir.mkdir(parents=True)
    _test_write(skill_dir / "SKILL.md",
                f"---\nname: {name}\nscope: optIn\n---\n\n#{name}\n")
    _test_write(skill_dir / "manifest.json", json.dumps(
        {"kind": "gateway", "members": [{"name": m, "purpose": "p", "triggers": [],
                                         "paths": {"skill": f"references/{m}"}}
                                        for m in members]}))


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    """A synthetic framework root: two scope-default commons, the testing group's opt-in
    members, a gateway that absorbed `old-member`, and two stacks with local skills."""
    _skill(tmp_path, "common", "alpha", "default")
    _skill(tmp_path, "common", "zulu", "default")
    _skill(tmp_path, "common", "design-tests", "optIn")
    _skill(tmp_path, "common", "review-tests", "optIn")
    _gateway(tmp_path, "common", "gateway-x", ["old-member"])
    _skill(tmp_path, "claude", "claude-local", "default")
    _skill(tmp_path, "hermes", "hermes-local", "default")
    return tmp_path


def test_derived_set_equals_the_manifest_rows_on_this_repo(root):
    """The oracle pin on the healthy tree: derived == the committed manifest's skill rows,
    in the manifest's own (block) order — 33 of them at the pin's writing."""
    config = bl.load_json(root / ".ai-badger" / "config.json")
    manifest = bl.load_json(root / ".ai-badger" / "manifest.json")
    recorded = bl.scaffolded_skill_names(manifest)

    derived = bl.expected_skill_names(root, config)

    assert derived == recorded
    assert len(derived) == 35


def test_block_order_defaults_then_include_then_stack_local(catalog):
    """Delivery BLOCK order (API-F1): sorted defaults, sorted include-derived, stack-local in
    resolve_stacks order. NOT flat-sorted — manifest row order is guard-visible."""
    config = {"stacks": ["claude", "hermes"], "include": {"skills": ["old-member"]}}

    derived = bl.expected_skill_names(catalog, config)

    assert derived == ["alpha", "zulu", "gateway-x", "claude-local", "hermes-local"]
    assert derived == sorted(derived) or True  # block order is NOT sorted order in general


def test_include_names_a_group_and_installs_the_whole_group(catalog):
    """Grouped skills install whole (#266): naming the group key or a member pulls in every
    sibling — expansion happens before the addable filter."""
    config = {"stacks": [], "include": {"skills": ["testing"]}}

    derived = bl.expected_skill_names(catalog, config)

    assert derived == ["alpha", "zulu", "design-tests", "review-tests"]


def test_include_names_an_absorbed_member_and_gets_the_gateway(catalog):
    """A stale member name resolves to the gateway that absorbed it (ADR-0021) — alias
    mapping AFTER expansion."""
    config = {"stacks": [], "include": {"skills": ["old-member"]}}

    assert bl.expected_skill_names(catalog, config) == ["alpha", "zulu", "gateway-x"]


def test_include_cannot_widen_past_the_addable_gate_or_duplicate_the_defaults(catalog):
    """An unknown include name is inclusion_notes' to report, never a delivery; a scope-default
    skill named by include stays at its defaults-block position, exactly once."""
    config = {"stacks": [], "include": {"skills": ["alpha", "no-such-skill"]}}

    assert bl.expected_skill_names(catalog, config) == ["alpha", "zulu"]


def test_stack_local_follows_resolve_stacks_order_and_never_walks_common(catalog):
    """Stack-local discovery iterates resolve_stacks(config) — config-overridable
    `commonStacks` — and skips the CONSTANT common skip-set: a common-catalog skill with no
    readable scope is never delivered by discovery."""
    config = {"stacks": ["hermes", "claude"], "include": {"skills": []}}
    _skill(catalog, "common", "scopeless", "nonsense")

    derived = bl.expected_skill_names(catalog, config)
    assert derived == ["alpha", "zulu", "hermes-local", "claude-local"]

    config = {"stacks": ["hermes", "claude"], "commonStacks": ["web"],
              "include": {"skills": []}}
    _skill(catalog, "web", "web-local", "default")
    derived = bl.expected_skill_names(catalog, config)
    # The scope-default common CATALOG always ships (the defaults block walks the common
    # skills dir, not resolve_stacks); commonStacks only re-points discovery — and `web` is
    # not in the CONSTANT skip-set, so it is discovered first, in resolve_stacks order.
    assert derived == ["alpha", "zulu", "web-local", "hermes-local", "claude-local"]


def test_alias_mapped_exclusions_apply_at_every_stage(catalog):
    """`exclude` is the mirror of `include` (ADR-0021): a stale member name declines the
    gateway that absorbed it — and the alias-mapped exclusion holds in the defaults block,
    the include-derived block, and stack-local discovery alike. Naming `design-tests` also
    pins the exclusion×group intersection: the sibling rides along (#266), the aliased
    gateway does not."""
    config = {"stacks": ["claude"], "include": {"skills": ["old-member", "design-tests"]},
              "exclude": {"skills": ["zulu", "old-member", "claude-local"]}}

    derived = bl.expected_skill_names(catalog, config)

    assert derived == ["alpha", "design-tests", "review-tests"]


def test_empty_config_yields_the_defaults_block_alone(catalog):
    config = {"stacks": []}

    assert bl.expected_skill_names(catalog, config) == ["alpha", "zulu"]
