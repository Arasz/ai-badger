"""Tests for the G4 skills-lint gate in tooling/validate.py (plan 2026-08-07-opt-skills-plan.md).

tmp_path + load_script style, mirroring test_validate.py — no edits to the real tree except the
real-corpus test, which asserts the shipped catalog passes the lint.
"""
from __future__ import annotations

import shutil


def _copy_real_schemas(tmp_path, root):
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    return tmp_path


def _write_skill(tmp_path, name="my-skill", fm_name=None, description="Use when testing the skills lint.",
                 body="", frontmatter_extra=""):
    """Write a canonical-frontmatter SKILL.md under a fake features/common/skills/<name>/ tree."""
    d = tmp_path / "features" / "common" / "skills" / name
    d.mkdir(parents=True)
    if fm_name is None:
        fm_name = name
    fm = (
        f"---\n"
        f"name: {fm_name}\n"
        f"description: >-\n"
        f"  {description}\n"
        f"version: 1.0.0\n"
        f"author: ai-badger\n"
        f"license: MIT\n"
        f"platforms: [linux, macos, windows]\n"
        f"metadata:\n"
        f"  hermes:\n"
        f"    tags: [lint, tests]\n"
        f"    related_skills: []\n"
    )
    if frontmatter_extra:
        fm += frontmatter_extra
    fm += "---\n"
    (d / "SKILL.md").write_text(fm + body, encoding="utf-8")
    return d


_GOOD_BODY = (
    "# My skill\n\n"
    "Use this skill when linting.\n\n"
    "## Gotchas\n\n"
    "No environment-specific gotchas known.\n"
)


def _lint(validate, root):
    return validate.skills_lint(root)


def test_name_grammar_rejects_uppercase(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, name="BadName", body=_GOOD_BODY)

    bad = _lint(validate, tmp_path)

    assert any("rule 1" in v for v in bad)


def test_name_must_match_parent_dir(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, name="my-skill", fm_name="other-name", body=_GOOD_BODY)

    bad = _lint(validate, tmp_path)

    assert any("rule 2" in v for v in bad)


def test_description_required(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    text = d.joinpath("SKILL.md").read_text(encoding="utf-8")
    text = text.replace("description: >-\n  Use when testing the skills lint.\n", "")
    d.joinpath("SKILL.md").write_text(text, encoding="utf-8")

    bad = _lint(validate, tmp_path)

    assert any("rule 3" in v for v in bad)


def test_description_over_1024_chars_reported(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, description="Use when testing. " + "x" * 1100, body=_GOOD_BODY)

    bad = _lint(validate, tmp_path)

    assert any("rule 4" in v for v in bad)


def test_description_must_start_with_use_when(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, description="Runs the lint when called.", body=_GOOD_BODY)

    bad = _lint(validate, tmp_path)

    assert any("rule 5" in v for v in bad)


def test_size_over_500_lines_reported(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    body = _GOOD_BODY + "\n".join(f"line {i}" for i in range(510)) + "\n"
    _write_skill(tmp_path, body=body)

    bad = _lint(validate, tmp_path)

    assert any("rule 6" in v for v in bad)


def test_size_over_5000_proxy_tokens_reported(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    # chars/4 proxy: 20,100 chars / 4 = 5,025 > 5,000
    _write_skill(tmp_path, body=_GOOD_BODY + "# " + "x" * 20_000 + "\n")

    bad = _lint(validate, tmp_path)

    assert any("rule 7" in v for v in bad)


def test_references_mention_without_condition_is_reported(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    body = _GOOD_BODY + "\nSee `references/detail.md` for the full story.\n"
    _write_skill(tmp_path, body=body)

    bad = _lint(validate, tmp_path)

    assert any("rule 8" in v for v in bad)


def test_gotchas_section_required(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, body="# My skill\n\nSome procedure.\n")

    bad = _lint(validate, tmp_path)

    assert any("rule 9" in v for v in bad)


def test_numbered_gotchas_heading_accepted(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, body="# My skill\n\n## 6. Gotchas\n\n- a known trap.\n")

    assert _lint(validate, tmp_path) == []


def test_no_gotchas_note_accepted_case_insensitive(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, body="# My skill\n\n## Gotchas\n\nNO ENVIRONMENT-SPECIFIC GOTCHAS KNOWN.\n")

    assert _lint(validate, tmp_path) == []


def test_frontmatter_missing_keys_reported(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    text = d.joinpath("SKILL.md").read_text(encoding="utf-8")
    text = text.replace("license: MIT\n", "").replace(
        "    related_skills: []\n", "").replace("platforms: [linux, macos, windows]\n", "")
    d.joinpath("SKILL.md").write_text(text, encoding="utf-8")

    bad = _lint(validate, tmp_path)

    rule10 = [v for v in bad if "rule 10" in v]
    assert rule10
    assert any("license" in v for v in rule10)
    assert any("metadata.hermes.related_skills" in v for v in rule10)
    assert any("platforms" in v for v in rule10)


def test_unparseable_frontmatter_is_reported_not_passed(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    d.joinpath("SKILL.md").write_text(
        "---\nname: my-skill\nno closing fence here\n", encoding="utf-8")

    bad = _lint(validate, tmp_path)

    assert any("rule 10" in v and "parse" in v for v in bad)


def test_valid_skill_passes_all_rules(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    body = (
            _GOOD_BODY
            + "\nRead `references/detail.md` when the short version does not settle it.\n"
    )
    _write_skill(tmp_path, body=body)

    assert _lint(validate, tmp_path) == []


def test_g2_condition_on_previous_line_within_window_passes(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    body = _GOOD_BODY + "\nWhen the answer is unclear, see `references/detail.md`.\n"
    _write_skill(tmp_path, body=body)

    assert _lint(validate, tmp_path) == []


def test_g2_condition_two_lines_above_is_outside_window(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    body = _GOOD_BODY + "\nWhen the answer is unclear.\n\nSee `references/detail.md`.\n"
    _write_skill(tmp_path, body=body)

    bad = _lint(validate, tmp_path)

    assert any("rule 8" in v for v in bad)


def test_g2_numbered_step_lines_are_skipped(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    body = _GOOD_BODY + "\n1. run `references/detail.md` through the harness.\n"
    _write_skill(tmp_path, body=body)

    assert _lint(validate, tmp_path) == []


def test_g2_exempt_list_honored(load_script):
    validate = load_script("tooling/validate.py")
    lines = ["line 83", "a generic `references/` directory mention", "line 85"]
    skill_name = "scaffold-documentation"
    line_no = 84

    bad = validate.references_without_conditions(lines, skill_name)

    assert f"{skill_name}:{line_no}" not in bad
    assert validate.REFERENCES_EXEMPT == {"scaffold-documentation:84"}


def test_g2_condition_regex_covers_all_keywords(load_script):
    validate = load_script("tooling/validate.py")
    for keyword in ("when", "if", "before", "after", "only when"):
        lines = [f"read `references/x.md` {keyword} the trigger holds"]
        assert validate.references_without_conditions(lines, "s") == []

    assert validate.references_without_conditions(
        ["read `references/x.md` WHEN the trigger holds"], "s") == []


def test_validate_all_reports_skills_lint(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    _write_skill(fake_root, name="BadName", body=_GOOD_BODY)

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "skills lint" in out
    assert "INVALID" in out


def test_skills_lint_ignores_a_root_without_features(tmp_path, root, load_script, capsys):
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ok       skills lint" in out


def test_the_real_corpus_passes_skills_lint(root, load_script):
    validate = load_script("tooling/validate.py")

    assert validate.skills_lint(root) == []


def test_duplicate_frontmatter_key_reported(tmp_path, load_script):
    validate = load_script("tooling/validate.py")
    _write_skill(tmp_path, body=_GOOD_BODY, frontmatter_extra="description: a short stub.\n")

    bad = _lint(validate, tmp_path)

    assert any("rule 11" in v and "description" in v for v in bad)


def test_real_corpus_has_no_duplicate_description_key(root):
    """Independent of rule 11's implementation: counts raw `description:` lines per SKILL.md.

    PR #320 shipped 20 skills with a duplicate `description:` key — the first (long,
    trigger-oriented) line is what skills_lint validates, but a real YAML parser resolves
    duplicates to the *last* value, so every agent host reads the short stub instead.
    """
    offenders = []
    for skill_md in sorted(root.glob("features/*/skills/*/SKILL.md")):
        lines = skill_md.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            continue
        end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), len(lines))
        count = sum(1 for line in lines[1:end] if line.startswith("description:"))
        if count > 1:
            offenders.append(str(skill_md.relative_to(root)))
    assert offenders == []