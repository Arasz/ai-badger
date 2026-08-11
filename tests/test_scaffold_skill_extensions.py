"""Skill extensions: the requirement gate that selects them and the markers that place them."""
from __future__ import annotations

import re

import pytest

from scaffold_helpers import _config
from conftest import _test_write


def _sole_index(content, anchor):
    """Offset of *anchor*, refusing one that does not occur exactly once (#283).

    `str.index` silently returns the earliest match, so an anchor that also appears in
    unrelated catalog prose measures a position the assertion never meant.
    """
    first = content.find(anchor)
    assert first != -1, f"ordering anchor {anchor!r} is not in the rendered document"
    assert content.find(anchor, first + 1) == -1, (
        f"ordering anchor {anchor!r} occurs more than once, so its position is ambiguous — "
        f"choose a token unique to the item under test"
    )
    return first


def test_an_ambiguous_ordering_anchor_is_refused():
    """Without this the helper is decoration: it must fail on a repeat, not measure the first."""
    assert _sole_index("alpha beta", "beta") == 6

    with pytest.raises(AssertionError, match="occurs more than once"):
        _sole_index("alpha beta alpha", "alpha")

    with pytest.raises(AssertionError, match="is not in the rendered document"):
        _sole_index("alpha beta", "gamma")


# ------------------------------------------------------------------- github extension gate
def test_scaffold_github_extension_embedded_when_platform_github(make_scaffolder):
    target = make_scaffolder.target
    config = _config(source_control={
        "platform": "github", "repoUrl": "https://github.com/foo/bar", "projectUrl": None,
    })

    scaf = make_scaffolder(config=config, skills=["task"])
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    ext_dir = target / ".ai-badger" / "skills" / "task" / "extensions" / "github"
    assert ext_dir.is_dir()
    assert any("embedded extension 'github'" in n for n in result["notes"])


def test_scaffold_github_extension_not_embedded_when_platform_none(make_scaffolder):
    target = make_scaffolder.target
    config = _config(source_control={"platform": "none", "repoUrl": None, "projectUrl": None})

    scaf = make_scaffolder(config=config, skills=["task"])
    result = scaf.run(generated_at="2026-07-19T00:00:00Z")

    ext_dir = target / ".ai-badger" / "skills" / "task" / "extensions" / "github"
    assert not ext_dir.exists()
    assert any("skipped (config requirements not met)" in n for n in result["notes"])


# --------------------------------------------------------- requirement_met OR syntax + list membership
def test_requirement_met_list_membership(load_script, root):
    """When config value is a list, equality check tests membership."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"stacks": ["dotnet", "react"]}
    assert scaffold.requirement_met(config, "stacks=dotnet") is True
    assert scaffold.requirement_met(config, "stacks=react") is True
    assert scaffold.requirement_met(config, "stacks=cosmos") is False


def test_requirement_met_or_syntax(load_script, root):
    """|| splits a requirement into alternatives; true if any matches."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"stacks": ["dotnet", "react"]}
    assert scaffold.requirement_met(config, "stacks=dotnet||stacks=node") is True
    assert scaffold.requirement_met(config, "stacks=cosmos||stacks=node") is False


def test_requirement_met_or_with_scalar(load_script, root):
    """|| works with scalar config values too."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"sourceControl": {"platform": "github"}}
    assert scaffold.requirement_met(config, "sourceControl.platform==github||sourceControl.platform==gitlab") is True
    assert scaffold.requirement_met(config, "sourceControl.platform==bitbucket||sourceControl.platform==gitlab") is False


def test_requirement_met_and_array(load_script, root):
    """Multiple entries in requires array are AND-ed."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"stacks": ["dotnet", "react"], "sourceControl": {"platform": "github"}}
    # Both conditions must be true
    assert scaffold.requirement_met(config, "stacks=react") is True
    assert scaffold.requirement_met(config, "sourceControl.platform==github") is True
    # Simulate AND by calling requirement_met for each
    assert all(scaffold.requirement_met(config, r) for r in ["stacks=react", "sourceControl.platform==github"]) is True
    assert all(scaffold.requirement_met(config, r) for r in ["stacks=cosmos", "sourceControl.platform==github"]) is False


def test_requirement_met_presence(load_script, root):
    """Presence check still works for non-empty values."""
    scaffold = load_script("features/common/skills/welcome-ai-badger/scripts/scaffold.py")
    config = {"sourceControl": {"repoUrl": "https://github.com/foo/bar"}}
    assert scaffold.requirement_met(config, "sourceControl.repoUrl") is True
    assert scaffold.requirement_met(config, "sourceControl.missing") is False


# --------------------------------------------------------- round-trip: generic + extensions + project-local → original
def test_code_review_checklist_roundtrip_reconstructs_original(make_scaffolder):
    """Given a project with all stacks + project-local.md, the scaffolded SKILL.md
    should contain every checklist item from the original project-specific skill.

    This is the round-trip guarantee: the original skill was decomposed into
    GENERIC base + stack extensions + project-local additions. After scaffold,
    reassembling them must produce equivalent coverage.
    """
    target = make_scaffolder.target

    # Config with every stack that has an extension
    config = _config(stacks=["dotnet", "react", "ts", "cosmos", "azure", "mcp"])
    skill_name = "code-review-checklist"

    # First scaffold — creates the skill with all extensions
    scaf = make_scaffolder(config=config, skills=[skill_name])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    # Write project-local.md with the incident lessons from the original skill
    project_local = target / ".ai-badger" / "skills" / skill_name / "project-local.md"
    _test_write(project_local, """
## Phase 10: Incident Lessons (Project-Specific)

### 10.1 DI Registration Crash (2026-07-24)

`ChannelMonitoringOptions` was injected but never registered via
`AddOptions<ChannelMonitoringOptions>().Bind(...)` in `Program.cs`.
The API compiled fine but crashed at runtime.

### 10.2 API Route Path Mismatch (2026-07-24)

Frontend used `/signals`, API defined `/channel-monitoring/signals`.
Every request hit a 404.

### 10.3 Problem Type URI Drift (2026-07-24)

Backend used `signal-stale`, frontend checked `stale-signal-proposal`.
409 detection never matched.

### 10.4 Optimistic Concurrency Gap (2026-07-24)

`signalRepository.UpsertAsync` had no ETag parameter — last-write-wins.

### 10.5 Domain Type in Wrong Project (2026-07-24)

`ProfileUpdateProposal` was placed in Api project — circular dependency.

### 10.6 C# String Escape in Spec (2026-07-24)

Spec contained a C# record with two properties both named `Errors`.
""")

    # Re-scaffold — project-local.md should be preserved and appended
    scaf2 = make_scaffolder(config=config, skills=[skill_name])
    result = scaf2.run(generated_at="2026-07-24T00:00:00Z")

    skill_md = target / ".ai-badger" / "skills" / skill_name / "SKILL.md"
    content = skill_md.read_text()

    # Verify every stack's content is present (from extensions)
    # GENERIC items
    generic_checks = [
        "Build passes",
        "Tests pass",
        "No hardcoded secrets",
        "One PR = one task",
        "Domain has zero infrastructure dependencies",
        "Infrastructure implements domain interfaces",
        "Screaming architecture",
        "State transitions enforced by domain model",
        "Tests exist for all new production code",
        "Test-first order",
        "Optimistic concurrency via ETag",
        "Idempotent operations return 200",
        "Client route paths match API route paths EXACTLY",
        "Response shapes match field-for-field",
        "Mock/test fixtures match actual API responses",
        "Retry loops are bounded",
        "Merge conflicts resolved with intent",
    ]
    # DOTNET items
    dotnet_checks = [
        "Every injected type is registered in DI",
        "AddOptions<T>().Bind()",
        "AddHttpClient<T>()",
        "sealed record",
        "CommunityToolkit.Diagnostics.Guard",
        "LoggerMessage",
        "DomainExceptionProblemMapper",
        "ResourceNotFoundException",
    ]
    # REACT items
    react_checks = [
        "ContentSection",
        "QueryLoading",
        "AlertDialog",
        "react-query",
        "apiFetch",
        "useMutation",
        "onMutate",
        "toast",
        "renderWithProviders",
        "userEvent",
        "MSW handlers follow",
        "Promise.allSettled",
    ]
    # TS items
    ts_checks = [
        "No `any` types",
        "No `as` type assertions",
        "Route params are type-safe",
    ]
    # COSMOS items
    cosmos_checks = [
        "partition key",
        "Single writer invariant",
        "ISecretCipher",
    ]
    # AZURE items
    azure_checks = [
        "Managed identity preferred",
        "202 Accepted",
    ]
    # MCP items
    mcp_checks = [
        "WithTools<T>",
        "MCP tools are thin HTTP clients",
    ]
    # PROJECT-LOCAL items
    project_checks = [
        "ChannelMonitoringOptions",
        "ChannelMonitoring",
        "signal-stale",
        "stale-signal-proposal",
        "signalRepository.UpsertAsync",
        "ProfileUpdateProposal",
        "two properties both named",
    ]

    all_checks = (
        ("GENERIC", generic_checks),
        ("DOTNET", dotnet_checks),
        ("REACT", react_checks),
        ("TS", ts_checks),
        ("COSMOS", cosmos_checks),
        ("AZURE", azure_checks),
        ("MCP", mcp_checks),
        ("PROJECT", project_checks),
    )

    missing = []
    for group, checks in all_checks:
        for check in checks:
            if check not in content:
                missing.append(f"[{group}] {check}")

    assert not missing, (
        f"Round-trip failed — {len(missing)} items missing from scaffolded SKILL.md:\n"
        + "\n".join(f"  - {m}" for m in missing)
    )

    # Verify project-local.md was stashed and survived
    assert project_local.exists(), "project-local.md was lost"
    assert any("appended project-local.md" in n for n in result["notes"])


# --------------------------------------------------------- extension marker routing
def test_extension_marker_routing_positions_items_correctly(make_scaffolder):
    """Extension sections with @marker headers are inserted at the matching
    <!-- EXT:name --> position, not appended at the end."""
    target = make_scaffolder.target

    config = _config(stacks=["dotnet", "react", "ts", "cosmos", "azure", "mcp"])
    scaf = make_scaffolder(config=config, skills=["code-review-checklist"])
    scaf.run(generated_at="2026-07-24T00:00:00Z")

    content = (target / ".ai-badger" / "skills" / "code-review-checklist" / "SKILL.md").read_text()

    # Verify EXT markers are consumed (not left in output)
    # Verify actual EXT marker lines are consumed (not left in output)
    # Note: Usage Tips may reference EXT markers in prose — that is fine
    ext_marker_lines = [l for l in content.split(chr(10)) if re.match(r"^\s*<!-- EXT:[a-z]", l)]
    assert not ext_marker_lines, f"EXT marker lines should be removed: {ext_marker_lines}"
    assert "<!-- MERGE_EXTENSIONS -->" not in content, "MERGE_EXTENSIONS sentinel should be removed"

    # Verify marker routing: dotnet items land BETWEEN the right generic items
    # Pre-takeoff phase: generic item -> dotnet item -> next phase
    assert _sole_index(content, "no API keys, tokens, connection strings") < _sole_index(
        content, "No `#pragma warning disable`")
    assert _sole_index(content, "No `#pragma warning disable`") < _sole_index(
        content, "Architecture & Layering")

    # Architecture phase: generic item -> dotnet item -> next phase
    assert _sole_index(content, "Domain has zero infrastructure") < _sole_index(
        content, "sealed record")
    assert _sole_index(content, "sealed record") < _sole_index(content, "Cross-Cutting Concerns")

    # Backend runtime phase: generic item -> dotnet/cosmos items -> next phase
    assert _sole_index(content, "Optimistic concurrency via ETag") < _sole_index(
        content, "[LoggerMessage]` source generators")
    assert _sole_index(content, "partition key") < _sole_index(
        content, "Client-Server Contract")

    # Contract alignment phase: react/ts items -> next phase
    assert _sole_index(content, "react-query") < _sole_index(content, "Cross-Feature Patterns")
    assert _sole_index(content, "No `any` types") < _sole_index(content, "Cross-Feature Patterns")

    # Post-merge: dotnet/react items present. `clean on main` alone would not discriminate —
    # the generic checklist carries "Build clean on main" whether or not dotnet merged.
    assert "`dotnet build` clean on main" in content
    assert "Frontend lint + test all pass" in content
