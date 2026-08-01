"""Agent-discovery files scaffold.py writes: preserve-vs-managed, managed headers, warnings."""
# pylint: disable=protected-access  # exercises Scaffolder internals directly; see pyproject.toml
from __future__ import annotations

import re

from scaffold_helpers import _config


KEEP_A = "keep-region-alpha-3f9c"
KEEP_B = "keep-region-beta-7d21"
KEEP_NOISE = "keep-region-noise-b40e"


# --------------------------------------------------------- preserve-by-default / overwrite
def test_scaffold_preserves_hand_authored_claude_md_by_default(make_scaffolder):
    target = make_scaffolder.target
    hand_authored = "# My Curated Guidance\n\nDo not touch this.\n"
    (target / "CLAUDE.md").write_text(hand_authored, encoding="utf-8")

    result = make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == hand_authored
    assert (target / ".ai-badger" / "CLAUDE.md").exists()  # source of truth still written
    assert any("preserved hand-authored" in n for n in result["notes"])


def test_scaffold_overwrite_replaces_hand_authored_claude_md(make_scaffolder):
    target = make_scaffolder.target
    (target / "CLAUDE.md").write_text("# My Curated Guidance\n", encoding="utf-8")

    make_scaffolder(overwrite=True).run(generated_at="2026-07-19T00:00:00Z")

    content = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert content.startswith(make_scaffolder.module._MANAGED_PREFIX)


def test_scaffold_managed_file_refreshes_on_second_run_without_overwrite(make_scaffolder):
    target = make_scaffolder.target
    make_scaffolder(config=_config(commands={"build": "dotnet build"})).run(
        generated_at="2026-07-19T00:00:00Z")
    first = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "dotnet build" in first
    assert first.startswith(make_scaffolder.module.MANAGED_HEADER.split("{name}", 1)[0])

    make_scaffolder(config=_config(commands={"build": "dotnet build -c Release"})).run(
        generated_at="2026-07-19T00:05:00Z")
    second = (target / "CLAUDE.md").read_text(encoding="utf-8")

    assert "dotnet build -c Release" in second


# ------------------------------------------------ non-standard agent file detection
def test_scaffold_warns_about_nonstandard_copilot_instructions(make_scaffolder):
    """When a repo has COPILOT_INSTRUCTIONS.md at root, the scaffolder should warn."""
    # Create a non-standard Copilot instruction file at root
    (make_scaffolder.target / "COPILOT_INSTRUCTIONS.md").write_text(
        "# My Copilot Rules\n", encoding="utf-8")

    result = make_scaffolder(config=_config(agents=["copilot"])).run(
        generated_at="2026-07-24T00:00:00Z")

    assert any("COPILOT_INSTRUCTIONS.md" in n and "non-standard" in n.lower()
               for n in result["notes"]), (
        f"Expected non-standard agent file warning, got: {result['notes']}"
    )


def test_scaffold_no_warning_when_no_nonstandard_files(make_scaffolder):
    """No warning when only standard agent files exist."""
    result = make_scaffolder(config=_config(agents=["copilot"])).run(
        generated_at="2026-07-24T00:00:00Z")

    assert not any("non-standard" in n.lower() for n in result["notes"]), (
        f"Unexpected non-standard warning: {result['notes']}"
    )


# ------------------------------------------------------------------- managed headers (F-08)
_HEADER_RE = re.compile(r"Source of truth(?: for this file)?: `?([^\s`]+)")


def _referenced_path(text: str):
    """The .ai-badger/ path a managed banner or self-reference names, or None."""
    match = _HEADER_RE.search(text)
    return match.group(1).rstrip(".") if match else None


def _managed_files(target) -> list:
    """Every scaffolded file carrying the managed-by-ai-badger banner."""
    found = []
    for path in sorted(target.rglob("*.md")):
        if path.is_file() and path.read_text(encoding="utf-8").startswith("<!-- Managed by"):
            found.append(path)
    return found


def _scaffold_all_agents(make_scaffolder):
    make_scaffolder(
        config=_config(agents=["claude", "copilot", "hermes", "junie"]),
        skills=["task"],
    ).run(generated_at="2026-07-24T00:00:00Z")


def test_every_managed_header_points_at_an_existing_file(make_scaffolder):
    """The banner is the first line an agent reads about where durable edits go (F-08)."""
    target = make_scaffolder.target
    _scaffold_all_agents(make_scaffolder)

    managed = _managed_files(target)
    assert managed, "expected at least one managed file"
    for path in managed:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        referenced = _referenced_path(first_line)
        assert referenced, f"{path.relative_to(target)}: unparseable header {first_line!r}"
        assert (target / referenced).exists(), \
            f"{path.relative_to(target)} points at {referenced}, which does not exist"


def test_managed_body_self_reference_matches_the_banner(make_scaffolder):
    """A rendered file's own 'Source of truth for this file' must name its own source."""
    _scaffold_all_agents(make_scaffolder)

    body = (make_scaffolder.target / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8")
    self_ref = next(line for line in body.splitlines() if "Source of truth for this file" in line)
    assert _referenced_path(self_ref) == ".ai-badger/copilot-instructions.md"


# ------------------------------------------------------------ preserved regions (keep markers)
KEEP_START = "<!-- ai-badger:keep-start -->"
KEEP_END = "<!-- ai-badger:keep-end -->"


def _scaffold(make_scaffolder, **kwargs):
    return make_scaffolder(**kwargs).run(generated_at="2026-07-27T00:00:00Z")


def _append(path, text):
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def test_keep_region_in_source_of_truth_survives_rescaffold(make_scaffolder):
    """The declared source of truth is the file that used to lose project content silently."""
    _scaffold(make_scaffolder)

    block = f"\n{KEEP_START}\n\n- `api-routes.instructions.md` — REST path taxonomy\n\n{KEEP_END}\n"
    aib_claude = make_scaffolder.target / ".ai-badger" / "CLAUDE.md"
    _append(aib_claude, block)

    _scaffold(make_scaffolder)

    assert block.strip() in aib_claude.read_text(encoding="utf-8")


def test_keep_region_in_managed_discovery_copy_survives_rescaffold(make_scaffolder):
    _scaffold(make_scaffolder)

    block = f"\n{KEEP_START}\nproject-authored line\n{KEEP_END}\n"
    root_claude = make_scaffolder.target / "CLAUDE.md"
    _append(root_claude, block)

    _scaffold(make_scaffolder)

    content = root_claude.read_text(encoding="utf-8")
    assert block.strip() in content
    assert content.startswith(make_scaffolder.module._MANAGED_PREFIX)


def test_unmarked_content_is_still_replaced(make_scaffolder):
    _scaffold(make_scaffolder)

    aib_claude = make_scaffolder.target / ".ai-badger" / "CLAUDE.md"
    _append(aib_claude, f"\nunmarked stray line\n{KEEP_START}\nkept line\n{KEEP_END}\n")

    _scaffold(make_scaffolder)

    content = aib_claude.read_text(encoding="utf-8")
    assert "unmarked stray line" not in content
    assert "kept line" in content


def test_multiple_keep_regions_are_all_preserved_in_order(make_scaffolder):
    _scaffold(make_scaffolder)

    aib_claude = make_scaffolder.target / ".ai-badger" / "CLAUDE.md"
    _append(aib_claude, f"\n{KEEP_START}\n{KEEP_A}\n{KEEP_END}\n\n{KEEP_NOISE}\n\n"
                        f"{KEEP_START}\n{KEEP_B}\n{KEEP_END}\n")

    _scaffold(make_scaffolder)

    content = aib_claude.read_text(encoding="utf-8")
    assert content.index(KEEP_A) < content.index(KEEP_B)
    assert KEEP_NOISE not in content


def test_keep_regions_do_not_accumulate_across_rescaffolds(make_scaffolder):
    _scaffold(make_scaffolder)

    aib_claude = make_scaffolder.target / ".ai-badger" / "CLAUDE.md"
    _append(aib_claude, f"\n{KEEP_START}\ncarried-exactly-one-copy\n{KEEP_END}\n")

    _scaffold(make_scaffolder)
    after_first = aib_claude.read_text(encoding="utf-8")
    _scaffold(make_scaffolder)

    assert aib_claude.read_text(encoding="utf-8") == after_first
    assert after_first.count("carried-exactly-one-copy") == 1


def test_fresh_scaffold_with_no_prior_file_writes_no_keep_markers(make_scaffolder):
    target = make_scaffolder.target
    result = _scaffold(make_scaffolder)

    assert KEEP_START not in (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert KEEP_START not in (target / ".ai-badger" / "CLAUDE.md").read_text(encoding="utf-8")
    assert not any("keep" in n for n in result["notes"])


def test_unterminated_keep_start_leaves_the_file_untouched(make_scaffolder):
    """Losing marked content to a typo must be impossible: refuse the rewrite instead."""
    _scaffold(make_scaffolder)

    aib_claude = make_scaffolder.target / ".ai-badger" / "CLAUDE.md"
    _append(aib_claude, f"\n{KEEP_START}\nunterminated content\n")
    before = aib_claude.read_text(encoding="utf-8")

    result = _scaffold(make_scaffolder)

    assert aib_claude.read_text(encoding="utf-8") == before
    assert any("keep-start" in n and "CLAUDE.md" in n for n in result["notes"])


def test_stray_keep_end_leaves_the_file_untouched(make_scaffolder):
    _scaffold(make_scaffolder)

    root_claude = make_scaffolder.target / "CLAUDE.md"
    _append(root_claude, f"\nvaluable content\n{KEEP_END}\n")
    before = root_claude.read_text(encoding="utf-8")

    result = _scaffold(make_scaffolder)

    assert root_claude.read_text(encoding="utf-8") == before
    assert any("keep-end" in n and "CLAUDE.md" in n for n in result["notes"])


def test_agent_docs_point_at_the_delegation_map_and_the_declare_model_rule(make_scaffolder):
    """One line, budgeted against HERMES.md's maxLines headroom (ADR-0015)."""
    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    content = (make_scaffolder.target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "- Every dispatch names its `model` — the delegation map is " \
           "`.ai-badger/delegation.md`." in content


def test_empty_persona_routing_renders_as_absent_not_as_a_policy(make_scaffolder):
    """`_Default routing._` read like a configured policy; there is no such policy (F-38)."""
    make_scaffolder().run(generated_at="2026-07-19T00:00:00Z")

    content = (make_scaffolder.target / "CLAUDE.md").read_text(encoding="utf-8")
    assert "_Default routing._" not in content
    assert "personaRouting" in content
