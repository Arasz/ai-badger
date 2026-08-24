"""`skills_lint` measures a catalog SKILL.md before extensions merge in; this measures the
merged file `scaffold.py` actually ships, which the catalog check never sees (SYNTHESIS.md V7,
risk 5).

task is a sentinel-less skill whose extensions/ stay runtime-loaded (config-gated at
scaffold time, pruned only when requirements are unmet), so its assertions differ from the
merge-at-scaffold skills: budget and line caps still apply to the shipped body, but
extensions/ legitimately survives."""
from __future__ import annotations

from scaffold_helpers import _config

MERGED_SKILLS = ("design-tests", "review-tests")
RUNTIME_EXTENSION_SKILLS = ("task",)


def test_merged_design_tests_review_tests_and_task_skills_stay_in_budget(
        make_scaffolder, load_script):
    lint = load_script("gates/skills_lint.py")
    import frontmatter as fm

    config = _config(stacks=["dotnet", "react", "ts", "node"],
                     source_control={"platform": "none", "repoUrl": None,
                                     "projectUrl": None})
    scaf = make_scaffolder(config=config, skills=list(MERGED_SKILLS) + list(RUNTIME_EXTENSION_SKILLS))
    scaf.run(generated_at="2026-08-22T00:00:00Z")

    target = make_scaffolder.target
    for name in MERGED_SKILLS + RUNTIME_EXTENSION_SKILLS:
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

        if name in RUNTIME_EXTENSION_SKILLS:
            # task keeps extensions/ runtime-loaded; no merge happens in-scaffold.
            assert "<!-- MERGE_EXTENSIONS -->" not in body, (
                f"{name}: unexpected MERGE_EXTENSIONS sentinel")
            continue

        assert not (skill_dir / "extensions").exists(), (
            f"{name}: extensions/ should be removed by merge_extensions, but survived")
        assert "<!-- MERGE_EXTENSIONS -->" not in body, (
            f"{name}: MERGE_EXTENSIONS sentinel survived the merge")
        assert "<!-- EXT:" not in body, f"{name}: an EXT marker survived the merge"


def test_merged_task_body_with_runtime_extension_within_budget(make_scaffolder, load_script):
    """The github extension is runtime-loaded today, but if it ever merges in-scaffold the
    combined file still has to fit — measure it as it would ship with the extension active."""
    lint = load_script("gates/skills_lint.py")
    import frontmatter as fm

    config = _config(stacks=[], source_control={
        "platform": "github", "repoUrl": "https://github.com/foo/bar", "projectUrl": None,
    })
    scaf = make_scaffolder(config=config, skills=["task"])
    scaf.run(generated_at="2026-08-22T00:00:00Z")

    skill_md = make_scaffolder.target / ".ai-badger" / "skills" / "task" / "SKILL.md"
    body = fm.split(skill_md.read_text(encoding="utf-8")).body or ""
    ext_md = (make_scaffolder.target / ".ai-badger" / "skills" / "task"
              / "extensions" / "github" / "extension.md")
    assert ext_md.exists(), (
        "github extension missing from scaffolded task skill — the combined "
        "body+extension measurement below would silently degrade to body-only")
    combined = body + "\n\n" + ext_md.read_text(encoding="utf-8")

    proxy = len(combined) / 4
    assert proxy <= lint.MAX_TOKENS * 2, (
        f"task body + github extension proxy {proxy:.0f} exceeds 2x budget — "
        "in-scaffold merge would not fit a single always-loaded read")
