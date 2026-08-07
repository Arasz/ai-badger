"""The 0.86.0 dotnet harvest shipped one private project's docs to every .NET consumer.

Two contracts hold the purge in place. First, none of the strings that harvest left behind may
reappear anywhere in ``features/``: the source project's namespace root, the mangled identifiers
a careless find/replace produced, and the misspelled product name. Second, every ``references/``
file must be named by its own ``SKILL.md`` — a reference nothing links to is shipped weight the
reader can never reach, which is exactly how the four harvest orphans went unnoticed.

Each rule is paired with a could-fail test that seeds a scratch tree with the literal text the
harvest actually shipped, so the scanner is known to catch what it was written for.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ROOT

# Substrings that may never appear anywhere under features/.
#
# - JobSearchAiAssistant: the harvested project's namespace root.
# - the the / class the / interface the: the find/replace that redacted the project name
#   swallowed identifiers and articles, leaving prose where a C# declaration belonged.
# - ai-raccon: a misspelling of the product ai-raccoon. "ai-raccoon" does not contain it
#   (…racc-o-o-n vs …racc-o-n), so every hit is the typo.
BANNED_EVERYWHERE = (
    "JobSearchAiAssistant",
    "ai-raccon",
    "the the ",
    "class the ",
    "interface the ",
)

# "this project" is legitimate framework voice — features/common speaks to the consumer's repo
# constantly. Under features/dotnet/skills it is not: that catalog ships .NET guidance that must
# never presume what the reader's codebase already contains, and every occurrence there came from
# the harvest asserting facts about the source repo.
BANNED_IN_DOTNET_SKILLS = ("this project",)

SCANNED_SUFFIXES = {".md", ".json", ".py", ".cs", ".yml", ".yaml", ".sh", ".tmpl", ".mjs",
                    ".csproj", ".jsonl"}


def _text_files(root: Path):
    """Every scannable file under root/features, sorted."""
    return sorted(p for p in (root / "features").rglob("*")
                  if p.is_file() and p.suffix in SCANNED_SUFFIXES)


def banned_string_hits(root: Path):
    """(relative path, line number, banned substring) for every leftover harvest artifact."""
    hits = []
    for path in _text_files(root):
        rel = path.relative_to(root)
        in_dotnet_skills = rel.as_posix().startswith("features/dotnet/skills/")
        banned = BANNED_EVERYWHERE + (BANNED_IN_DOTNET_SKILLS if in_dotnet_skills else ())
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            lowered = line.lower()
            hits.extend((rel.as_posix(), number, needle)
                        for needle in banned if needle.lower() in lowered)
    return hits


def unreferenced_reference_files(root: Path):
    """Relative paths of references/ files their own SKILL.md never names."""
    orphans = []
    for skill_md in sorted((root / "features").glob("*/skills/*/SKILL.md")):
        body = skill_md.read_text(encoding="utf-8")
        references = skill_md.parent / "references"
        if not references.is_dir():
            continue
        orphans.extend(ref.relative_to(root).as_posix()
                       for ref in sorted(references.rglob("*"))
                       if ref.is_file() and ref.name not in body)
    return orphans


def test_catalog_carries_no_harvest_artifact_strings():
    hits = banned_string_hits(ROOT)
    assert not hits, "harvest artifacts still in the catalog: " + "; ".join(
        f"{path}:{number} ({needle!r})" for path, number, needle in hits)


def test_every_reference_file_is_named_by_its_skill():
    orphans = unreferenced_reference_files(ROOT)
    assert not orphans, (
            "references/ files no SKILL.md names — wire them in or delete them: "
            + ", ".join(orphans))


# --- could-fail: the scanners must reject the text the harvest actually shipped -------------

# Verbatim from the 0.86.0 harvest, one per rule the scanner enforces.
HARVEST_SAMPLES = pytest.mark.parametrize("relative, line", [
    ("features/dotnet/skills/dotnet-domain-modeling/references/injectable-components-pattern.md",
     "internal static partial class the config dispatcher"),
    ("features/dotnet/skills/dotnet-domain-modeling/references/injectable-components-pattern.md",
     "public interface the encryption command interface"),
    ("features/dotnet/skills/dotnet-mcp-server/references/mcp-csharp-sdk-2.0-apis.md",
     "Repo: `~/RiderProjects/ai-raccon/the project`, worktree `.ai-badger/worktrees/x`"),
    ("features/dotnet/skills/dotnet-system-commandline/references/ga-api.md",
     "args for the the MCP server. The GA release differs sharply from the beta."),
    ("features/dotnet/skills/dotnet-domain-modeling/references/cosmos-persistence.md",
     "namespace JobSearchAiAssistant.Infrastructure.LinkedIn;"),
    ("features/dotnet/skills/dotnet-domain-modeling/references/cosmos-persistence.md",
     "When adding a new Cosmos-backed entity to this project, follow this exact sequence."),
])


def _seed(root: Path, relative: str, line: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# reference\n\n{line}\n", encoding="utf-8")


@HARVEST_SAMPLES
def test_banned_string_scanner_catches_the_shipped_harvest_text(tmp_path, relative, line):
    _seed(tmp_path, relative, line)
    assert banned_string_hits(tmp_path), f"scanner missed shipped harvest text: {line!r}"


def test_banned_string_scanner_allows_legitimate_framework_voice(tmp_path):
    """"this project" is the framework addressing the consumer's repo outside features/dotnet."""
    _seed(tmp_path, "features/common/skills/den-refresh/SKILL.md",
          "skills this project edited in place are not framework drift")
    _seed(tmp_path, "features/dotnet/personas/dotnet-engineer.md",
          "Read this project's C# scoped instructions first.")
    assert banned_string_hits(tmp_path) == []


def test_orphan_scanner_catches_a_reference_no_skill_names(tmp_path):
    skill = tmp_path / "features/dotnet/skills/dotnet-domain-modeling"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "# s\n\nWhen classifying, read `references/deterministic-classification-pipeline.md`.\n",
        encoding="utf-8")
    (skill / "references/deterministic-classification-pipeline.md").write_text("x", "utf-8")
    (skill / "references/llm-classifier-integration.md").write_text("x", "utf-8")

    orphans = unreferenced_reference_files(tmp_path)

    assert orphans == [
        "features/dotnet/skills/dotnet-domain-modeling/references/llm-classifier-integration.md"]