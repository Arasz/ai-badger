"""Tests for the code-review router skill (github stack, 0.158.0).

The skill is pure content: a review entry point GitHub Copilot code review loads from
.github/skills/ (read from the head branch), routing to the catalog's review skills and
adjusted per project stack through the one extension mechanism (ADR-0006). Three contracts
are pinned here:

  1. The router names only skills the catalog actually ships — a rename upstream must
     break this test rather than silently strand the route.
  2. Scaffold delivery: the github stack delivers the skill (stack-local discovery,
     ADR-0010) and the copilot agent's adjustment symlinks it into .github/skills/ —
     the path Copilot code review discovers. Stack extensions merge into the body
     per their requires (dotnet/react/ts/python/azure in when configured, out when not)
     and extensions/ is removed by the merge.
  3. The shipped (merged) body stays inside the skills_lint budgets — lines and chars/4
     token proxy — measured at worst case with every extension's stack configured.

Failure modes pinned: a routed skill name with no catalog backing (route strands), a
stack extension that never ships because its requires names a typo'd stack, a stack
section that leaks into a project without that stack, a missing Copilot discovery
symlink (the skill ships but the reviewing agent never finds it), and a merged body
that outgrew the always-loaded budget.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys

import pytest

from conftest import ROOT

SKILL_REL = "features/github/skills/code-review/SKILL.md"
ROUTED_SIBLING_RE = re.compile(r"`\.ai-badger/skills/([a-z0-9-]+)/SKILL\.md`")
STACK_SECTION_RE = re.compile(r"^## (.+?) review adjustments", re.MULTILINE)

STACK_EXTENSIONS = {
    "dotnet": "stacks=dotnet",
    "react": "stacks=react",
    "ts": "stacks=ts",
    "python": "stacks=python",
    "azure": "stacks=azure",
}


def _load_lint():
    """Load gates/skills_lint.py standalone (it inserts engine/ into sys.path itself)."""
    spec = importlib.util.spec_from_file_location(
        "skills_lint_under_test", ROOT / "gates" / "skills_lint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _github_config(stacks, agents=("claude", "copilot")):
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": list(stacks),
        "agents": list(agents),
        "sourceControl": {"platform": "github",
                          "repoUrl": "https://github.com/foo/bar", "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


# ---------------------------------------------------------------------------
# 1. the router routes to skills that exist
# ---------------------------------------------------------------------------

def test_the_router_names_only_catalog_skills():
    text = (ROOT / SKILL_REL).read_text(encoding="utf-8")
    routed = set(ROUTED_SIBLING_RE.findall(text))
    assert routed, "router names no sibling skills — nothing to route to"
    catalog = {d.parent.name for d in ROOT.glob("features/*/skills/*/SKILL.md")}
    stranded = sorted(routed - catalog)
    assert not stranded, (
        f"router points at skills the catalog does not ship: {stranded} — "
        "fix the route or the test is lying about where review work lives")


def test_every_routed_sibling_names_its_scope_so_the_router_can_degrade():
    """The router promises a baseline fallback for undelivered siblings; each routed
    sibling's frontmatter must carry a readable scope so the promise stays decidable."""
    sys.path.insert(0, str(ROOT / "engine"))
    import badger_lib as bl  # pylint: disable=import-outside-toplevel

    text = (ROOT / SKILL_REL).read_text(encoding="utf-8")
    routed = sorted(set(ROUTED_SIBLING_RE.findall(text)))
    scopeless = []
    for name in routed:
        hits = sorted(ROOT.glob(f"features/*/skills/{name}/SKILL.md"))
        assert len(hits) == 1, f"{name}: expected exactly one catalog home, found {hits}"
        if bl.skill_scope_in(hits[0].parent) is None:
            scopeless.append(name)
    assert not scopeless, f"routed skills without a readable scope: {scopeless}"


# ---------------------------------------------------------------------------
# 2. extension descriptors are honest
# ---------------------------------------------------------------------------

def test_every_stack_extension_requires_a_stack_the_catalog_knows():
    """A typo'd `stacks=<name>` never fails — requirement_met just reads it as unmet and
    the extension silently never ships. Pin each declared stack to the catalog index."""
    sys.path.insert(0, str(ROOT / "engine"))
    import badger_lib as bl  # pylint: disable=import-outside-toplevel

    known = set(bl.read_index(ROOT).get("stacks", {}))
    ext_base = ROOT / "features/github/skills/code-review/extensions"
    seen = {d.name for d in ext_base.iterdir() if d.is_dir()}
    assert seen == set(STACK_EXTENSIONS), (
        f"extensions on disk {sorted(seen)} != declared {sorted(STACK_EXTENSIONS)}")
    for ext, requires in STACK_EXTENSIONS.items():
        descriptor = json.loads((ext_base / ext / "extension.json").read_text("utf-8"))
        assert descriptor.get("skill") == "code-review", f"{ext}: wrong skill binding"
        assert descriptor.get("requires") == [requires], (
            f"{ext}: requires {descriptor.get('requires')} != [{requires!r}]")
        stack_name = requires.split("=", 1)[1]
        assert stack_name in known, (
            f"{ext}: requires stack {stack_name!r} which the catalog does not know — "
            "typo'd requires ship nothing and say nothing")


# ---------------------------------------------------------------------------
# 3. scaffold delivery — stack-local discovery + copilot discovery symlink
# ---------------------------------------------------------------------------

@pytest.fixture(name="scaffolded")
def scaffolded_fixture(make_scaffolder):
    """Scaffold a github + copilot + all-five-stacks project; return the delivered skill dir.

    install=False (suite default): hermes symlinks are the only install-gated step and
    this project configures no hermes agent.
    """
    scaf = make_scaffolder(
        config=_github_config(["github", "dotnet", "react", "ts", "python", "azure"]),
        skills=[])
    scaf.run(generated_at="2026-08-25T00:00:00Z")
    return scaf.target / ".ai-badger" / "skills" / "code-review"


def test_github_stack_delivers_the_router_without_being_asked(scaffolded):
    """Stack-local skills ship whole when the stack is configured (ADR-0010): skills=[] —
    discovery, not an explicit include, is what delivers this."""
    assert (scaffolded / "SKILL.md").is_file(), (
        "github stack configured but the code-review router was not delivered — "
        "stack-local discovery did not pick it up")


def test_copilot_agent_symlinks_the_router_into_github_skills(scaffolded):
    link = scaffolded.parent.parent.parent / ".github" / "skills" / "code-review"
    assert link.is_symlink(), (
        "copilot agent configured but .github/skills/code-review was not created — "
        "Copilot code review would never discover the entry point")
    resolved = link.resolve()
    assert resolved == scaffolded.resolve(), (
        f"symlink points at {resolved}, not the scaffolded skill {scaffolded.resolve()}")


def test_sentinel_and_markers_are_gone_from_the_shipped_body(scaffolded):
    text = (scaffolded / "SKILL.md").read_text(encoding="utf-8")
    assert "<!-- MERGE_EXTENSIONS -->" not in text
    assert "<!-- EXT:" not in text
    assert not (scaffolded / "extensions").exists(), (
        "extensions/ survived a merge-at-scaffold skill — the shipped tree carries dead dirs")


def test_stack_sections_arrive_only_with_their_stack(scaffolded):
    text = (scaffolded / "SKILL.md").read_text(encoding="utf-8")
    found = set(STACK_SECTION_RE.findall(text))
    missing = set(STACK_EXTENSIONS) - found
    assert not missing, f"configured stacks missing their review adjustments: {missing}"


def test_unconfigured_stack_sections_do_not_leak(make_scaffolder):
    scaf = make_scaffolder(config=_github_config(["github"], agents=("claude",)), skills=[])
    scaf.run(generated_at="2026-08-25T00:00:00Z")
    skill_dir = scaf.target / ".ai-badger" / "skills" / "code-review"
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    leaked = set(STACK_SECTION_RE.findall(text))
    assert not leaked, f"stack adjustments shipped without their stacks: {leaked}"
    assert not (skill_dir / "extensions").exists()
    assert "## Gotchas" in text or "no environment-specific gotchas known" in text


# ---------------------------------------------------------------------------
# 4. the shipped body stays inside the always-loaded budget
# ---------------------------------------------------------------------------

def test_merged_router_body_stays_in_budget(make_scaffolder):
    """Worst case: every extension's stack configured at once. Mirrors
    test_merged_skill_stays_in_budget, which the catalog lint never sees."""
    lint = _load_lint()
    scaf = make_scaffolder(
        config=_github_config(["github", "dotnet", "react", "ts", "python", "azure"],
                              agents=("claude",)),
        skills=[])
    scaf.run(generated_at="2026-08-25T00:00:00Z")
    skill_md = scaf.target / ".ai-badger" / "skills" / "code-review" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    body = lint.fm.split(text).body or text
    nlines = len(body.splitlines())
    assert nlines <= lint.MAX_LINES, f"merged body is {nlines} lines > {lint.MAX_LINES}"
    proxy = len(body) / 4
    assert proxy <= lint.MAX_TOKENS, (
        f"merged body chars/4 proxy {proxy:.0f} > {lint.MAX_TOKENS}")
