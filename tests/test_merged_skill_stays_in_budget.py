"""`skills_lint` measures a catalog SKILL.md before extensions merge in; this measures the
merged file `scaffold.py` actually ships, which the catalog check never sees (SYNTHESIS.md V7,
risk 5)."""
from __future__ import annotations

from scaffold_helpers import _config

SKILL_NAMES = ("design-tests", "review-tests")


def test_merged_design_tests_and_review_tests_skills_stay_in_budget(make_scaffolder, load_script):
    lint = load_script("gates/skills_lint.py")
    import frontmatter as fm

    config = _config(stacks=["dotnet", "react", "ts", "node"])
    scaf = make_scaffolder(config=config, skills=list(SKILL_NAMES))
    scaf.run(generated_at="2026-08-22T00:00:00Z")

    target = make_scaffolder.target
    for name in SKILL_NAMES:
        skill_dir = target / ".ai-badger" / "skills" / name
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file(), f"{name}: SKILL.md missing from scaffolded output"

        text = skill_md.read_text(encoding="utf-8")
        body = fm.split(text).body or text

        nlines = len(body.splitlines())
        assert nlines <= lint.MAX_LINES, (
            f"{name}: merged body is {nlines} lines > {lint.MAX_LINES}")

        proxy = len(body) / 4
        assert proxy <= lint.MAX_TOKENS, (
            f"{name}: merged body chars/4 proxy {proxy:.0f} > {lint.MAX_TOKENS}")

        assert not (skill_dir / "extensions").exists(), (
            f"{name}: extensions/ should be removed by merge_extensions, but survived")
        assert "<!-- MERGE_EXTENSIONS -->" not in body, (
            f"{name}: MERGE_EXTENSIONS sentinel survived the merge")
        assert "<!-- EXT:" not in body, f"{name}: an EXT marker survived the merge"
