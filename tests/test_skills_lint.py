"""Tests for the G4 skills-lint gate in tooling/lint.py (plan 2026-08-07-opt-skills-plan.md).

tmp_path + load_script style, mirroring test_lint.py — no edits to the real tree except the
real-corpus test, which asserts the shipped catalog passes the lint.
"""
from __future__ import annotations

import json
import shutil

import pytest
from conftest import _test_write


def _copy_real_schemas(tmp_path, root):
    (tmp_path / "features").mkdir()
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    _write_hooks_manifest(tmp_path)
    return tmp_path


def _write_hooks_manifest(tmp_path):
    """A complete manifest: since 0.88.4 a tree with no hooks-manifest.json fails --all."""
    d = tmp_path / "features" / "common" / "hooks"
    d.mkdir(parents=True, exist_ok=True)
    _test_write(d / "hooks-manifest.json", json.dumps({"hooks": [
        {"name": "demo-hook", "agents": {
            agent: {"type": "hooks-json", "entry": "hooks.json", "event": "SessionStart",
                    "script": "demo_hook.py"}
            for agent in ("claude", "hermes", "copilot")}},
    ]}), encoding="utf-8")
    return d


def _write_skill(tmp_path, name="my-skill", fm_name=None, description="Use when testing the skills lint.",
                 body="", frontmatter_extra="", stack="common", scope="default"):
    """Write a canonical-frontmatter SKILL.md under a fake features/<stack>/skills/<name>/ tree.

    `scope=None` omits the key, which is rule 12's violation for a common-stack skill.
    """
    d = tmp_path / "features" / stack / "skills" / name
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
        + (f"scope: {scope}\n" if scope is not None else "")
        + f"metadata:\n"
        f"  hermes:\n"
        f"    tags: [lint, tests]\n"
        f"    related_skills: []\n"
    )
    if frontmatter_extra:
        fm += frontmatter_extra
    fm += "---\n"
    _test_write(d / "SKILL.md", fm + body, encoding="utf-8")
    return d


_GOOD_BODY = (
    "# My skill\n\n"
    "Use this skill when linting.\n\n"
    "## Gotchas\n\n"
    "No environment-specific gotchas known.\n"
)


def _lint(module, root):
    return module.skills_lint(root)


def test_name_grammar_rejects_uppercase(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="BadName", body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 1" in v for v in bad)


def test_name_grammar_rejects_uppercase_after_the_first_character(tmp_path, load_script):
    """`BadName` fails at character 0, where `fullmatch` and `match` agree — this one does not."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="name-With-Caps", body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 1" in v for v in bad), bad


def test_name_grammar_rejects_an_underscore_after_the_first_character(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="my_skill", body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 1" in v for v in bad), bad


def test_name_over_the_64_char_cap_is_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="a" * 65, body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 1" in v for v in bad), bad


def test_name_of_exactly_64_chars_is_accepted(tmp_path, load_script):
    """The cap's boundary: 64 passes, so a `>` silently turned `>=` is a failing test."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="a" * 64, body=_GOOD_BODY)

    assert _lint(lint, tmp_path) == []


def test_name_must_match_parent_dir(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="my-skill", fm_name="other-name", body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 2" in v for v in bad)


def test_description_required(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    text = d.joinpath("SKILL.md").read_text(encoding="utf-8")
    text = text.replace("description: >-\n  Use when testing the skills lint.\n", "")
    _test_write(d.joinpath("SKILL.md"), text, encoding="utf-8")

    bad = _lint(lint, tmp_path)

    assert any("rule 3" in v for v in bad)
    # A missing description is one violation, not two: rules 4-5 must not also fire on "".
    assert not any("rule 5" in v for v in bad), bad


def test_description_over_1024_chars_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, description="Use when testing. " + "x" * 1100, body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 4" in v for v in bad)


def test_description_of_exactly_1024_chars_is_accepted(tmp_path, load_script):
    """The cap's boundary: 1024 passes, so a `>` silently turned `>=` is a failing test."""
    lint = load_script("gates/skills_lint.py")
    prefix = "Use when testing the boundary. "
    _write_skill(tmp_path, description=prefix + "x" * (1024 - len(prefix)), body=_GOOD_BODY)

    assert _lint(lint, tmp_path) == []


def test_description_must_start_with_use_when(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, description="Runs the lint when called.", body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 5" in v for v in bad)


def test_description_starting_with_use_but_not_use_when_is_reported(tmp_path, load_script):
    """The word "when" carries the rule; "Use this skill to…" is the shape it exists to reject."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, description="Use this skill to lint the catalog.", body=_GOOD_BODY)

    bad = _lint(lint, tmp_path)

    assert any("rule 5" in v for v in bad), bad


def test_size_over_500_lines_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    body = _GOOD_BODY + "\n".join(f"line {i}" for i in range(510)) + "\n"
    _write_skill(tmp_path, body=body)

    bad = _lint(lint, tmp_path)

    assert any("rule 6" in v for v in bad)


def _body(skill_dir):
    """The body as skills_lint measures it — everything past the closing frontmatter fence."""
    return skill_dir.joinpath("SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]


def test_body_of_exactly_500_lines_is_accepted(tmp_path, load_script):
    """The cap's boundary: 500 passes, so a `>` silently turned `>=` is a failing test."""
    lint = load_script("gates/skills_lint.py")
    body = _GOOD_BODY + "".join(f"line {i}\n" for i in range(400))
    d = _write_skill(tmp_path, body=body + "\n" * (500 - len(("\n" + body).splitlines())))

    assert len(_body(d).splitlines()) == 500
    assert _lint(lint, tmp_path) == []


def test_size_over_5000_proxy_tokens_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    # chars/4 proxy: 20,100 chars / 4 = 5,025 > 5,000
    _write_skill(tmp_path, body=_GOOD_BODY + "# " + "x" * 20_000 + "\n")

    bad = _lint(lint, tmp_path)

    assert any("rule 7" in v for v in bad)


def test_body_at_exactly_5000_proxy_tokens_is_accepted(tmp_path, load_script):
    """The proxy's boundary: 20,000 chars / 4 = 5,000 passes, and only a /4 divisor gets there."""
    lint = load_script("gates/skills_lint.py")
    filler = "x" * (20_000 - 1 - len(_GOOD_BODY))
    d = _write_skill(tmp_path, body=_GOOD_BODY + filler)

    assert len(_body(d)) == 20_000
    assert _lint(lint, tmp_path) == []


def test_references_mention_without_condition_is_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    body = _GOOD_BODY + "\nSee `references/detail.md` for the full story.\n"
    _write_skill(tmp_path, body=body)

    bad = _lint(lint, tmp_path)

    assert any("rule 8" in v for v in bad)


def test_gotchas_section_required(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body="# My skill\n\nSome procedure.\n")

    bad = _lint(lint, tmp_path)

    assert any("rule 9" in v for v in bad)


def test_numbered_gotchas_heading_accepted(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body="# My skill\n\n## 6. Gotchas\n\n- a known trap.\n")

    assert _lint(lint, tmp_path) == []


def test_no_gotchas_note_accepted_case_insensitive(tmp_path, load_script):
    """The note ALONE satisfies rule 9. Before 0.88.4 this fixture also carried a `## Gotchas`
    heading, so it passed on the heading arm and never reached the note arm it is named for."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body="# My skill\n\nNO ENVIRONMENT-SPECIFIC GOTCHAS KNOWN.\n")

    assert _lint(lint, tmp_path) == []


def test_frontmatter_missing_keys_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    text = d.joinpath("SKILL.md").read_text(encoding="utf-8")
    text = text.replace("license: MIT\n", "").replace(
        "    related_skills: []\n", "").replace("platforms: [linux, macos, windows]\n", "")
    _test_write(d.joinpath("SKILL.md"), text, encoding="utf-8")

    bad = _lint(lint, tmp_path)

    rule10 = [v for v in bad if "rule 10" in v]
    assert rule10
    assert any("license" in v for v in rule10)
    assert any("metadata.hermes.related_skills" in v for v in rule10)
    assert any("platforms" in v for v in rule10)


def test_a_metadata_key_carrying_an_inline_value_is_reported_not_passed(tmp_path, load_script):
    """`metadata: <value>` with an indented block under it is ambiguous, so it must not resolve.

    Every other fixture writes the canonical bare `metadata:`, where the block-reader already
    refuses on its own and the inline guard does no work — so removing that guard changed no
    test's verdict while `frontmatter_fields()` started returning a full, "valid" dict here.
    """
    lint = load_script("gates/skills_lint.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    path = d / "SKILL.md"
    _test_write(path, path.read_text(encoding="utf-8").replace(
        "metadata:\n", "metadata: an inline value no reader can reconcile\n"), encoding="utf-8")

    assert lint.frontmatter_fields(path.read_text(encoding="utf-8")) is None
    assert any("rule 10" in v for v in _lint(lint, tmp_path))


def test_unparseable_frontmatter_is_reported_not_passed(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    d = _write_skill(tmp_path, body=_GOOD_BODY)
    _test_write(d.joinpath("SKILL.md"), "---\nname: my-skill\nno closing fence here\n", encoding="utf-8")

    bad = _lint(lint, tmp_path)

    assert any("rule 10" in v and "parse" in v for v in bad)
    # An unreadable name is not a name that disagrees with its directory: rule 2 stays quiet.
    assert not any("rule 2" in v for v in bad), bad


# ------------------------------------------------------------------- rule 12: scope (ADR-0018)
def test_a_common_skill_with_no_scope_is_reported(tmp_path, load_script):
    """The guarantee ADR-0005 wanted: an undeclared skill fails at authorship, never silently."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body=_GOOD_BODY, scope=None)

    bad = _lint(lint, tmp_path)

    assert any("rule 12" in v for v in bad), bad


def test_a_common_skill_with_an_unknown_scope_value_is_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body=_GOOD_BODY, scope="sometimes")

    bad = _lint(lint, tmp_path)

    assert any("rule 12" in v for v in bad), bad


def test_an_empty_scope_value_is_reported(tmp_path, load_script):
    """`scope:` with nothing after it reads as declared to a grep and as nothing to a parser."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body=_GOOD_BODY, scope="")

    bad = _lint(lint, tmp_path)

    assert any("rule 12" in v for v in bad), bad


@pytest.mark.parametrize("scope", ["default", "optIn"])
def test_both_declared_scopes_are_accepted(tmp_path, load_script, scope):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body=_GOOD_BODY, scope=scope)

    assert _lint(lint, tmp_path) == []


def test_a_stack_local_skill_needs_no_scope(tmp_path, load_script):
    """Only the common catalog's scope is consulted; requiring it elsewhere is ceremony."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="dotnet-thing", stack="dotnet", body=_GOOD_BODY, scope=None)

    assert _lint(lint, tmp_path) == []


def test_valid_skill_passes_all_rules(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    body = (
            _GOOD_BODY
            + "\nRead `references/detail.md` when the short version does not settle it.\n"
    )
    _write_skill(tmp_path, body=body)

    assert _lint(lint, tmp_path) == []


def test_g2_condition_on_previous_line_within_window_passes(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    body = _GOOD_BODY + "\nWhen the answer is unclear, see `references/detail.md`.\n"
    _write_skill(tmp_path, body=body)

    assert _lint(lint, tmp_path) == []


def test_g2_condition_two_lines_above_is_outside_window(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    body = _GOOD_BODY + "\nWhen the answer is unclear.\n\nSee `references/detail.md`.\n"
    _write_skill(tmp_path, body=body)

    bad = _lint(lint, tmp_path)

    assert any("rule 8" in v for v in bad)


def test_g2_numbered_step_lines_are_skipped(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    body = _GOOD_BODY + "\n1. run `references/detail.md` through the harness.\n"
    _write_skill(tmp_path, body=body)

    assert _lint(lint, tmp_path) == []


def test_g2_exempt_list_honored(load_script, monkeypatch):
    """Keyed on the mention's text, not its line number: moving the line must not move the key.

    A synthetic entry, because the real one's text carries the word "when" and would be accepted
    by the condition regex whether or not the exemption fired.
    """
    lint = load_script("gates/skills_lint.py")
    mention = "a generic `references/` directory mention"
    monkeypatch.setattr(lint, "REFERENCES_EXEMPT", {("scaffold-documentation", mention)})
    lines = ["line 83", mention, "line 85"]

    exempt = lint.references_without_conditions(lines, "scaffold-documentation")

    assert exempt == []
    assert lint.references_without_conditions(lines, "another-skill") == ["another-skill:2"]


def test_every_references_exemption_still_names_a_line_that_exists(root, load_script):
    """The A12 failure class: the exemption was keyed to `scaffold-documentation:84`, and line 84
    of that file had gone blank. A stale key exempts nothing and nothing said so."""
    lint = load_script("gates/skills_lint.py")

    for skill_name, mention in lint.REFERENCES_EXEMPT:
        matches = list(root.glob(f"features/*/skills/{skill_name}/SKILL.md"))
        assert matches, f"exemption names a skill that no longer exists: {skill_name}"
        lines = [ln.strip() for ln in matches[0].read_text(encoding="utf-8").splitlines()]
        assert mention in lines, (
            f"stale exemption: {skill_name} no longer contains the mention {mention!r}")


def test_g2_condition_regex_covers_all_keywords(load_script):
    lint = load_script("gates/skills_lint.py")
    for keyword in ("when", "if", "before", "after", "only when"):
        lines = [f"read `references/x.md` {keyword} the trigger holds"]
        assert lint.references_without_conditions(lines, "s") == []

    assert lint.references_without_conditions(
        ["read `references/x.md` WHEN the trigger holds"], "s") == []


def test_validate_all_still_reports_skills_lint_after_the_move_to_gates(
        tmp_path, root, load_script, capsys):
    """CI runs `validate.py --all` and nothing else; the extraction must not cost that lane."""
    validate = load_script("tooling/validate.py")
    fake_root = _copy_real_schemas(tmp_path, root)
    _write_skill(fake_root, name="BadName", body=_GOOD_BODY)

    rc = validate.main(["--all", "--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 1
    assert "skills lint" in out
    assert "INVALID" in out


def test_skills_lint_ignores_a_root_without_features(tmp_path, root, load_script, capsys):
    lint = load_script("gates/skills_lint.py")
    fake_root = _copy_real_schemas(tmp_path, root)

    rc = lint.main(["--root", str(fake_root)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ok       skills lint" in out


def test_the_real_corpus_passes_skills_lint(root, load_script):
    lint = load_script("gates/skills_lint.py")

    assert lint.skills_lint(root) == []


def test_a_skill_outside_features_common_is_linted(tmp_path, load_script):
    """Scope. Every other fixture lives under features/common/, so narrowing the glob to that one
    stack left the suite green while 15 of 51 shipped skills went unlinted (the review's A5)."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, name="my-skill", body=_GOOD_BODY)
    _write_skill(tmp_path, name="BadName", body=_GOOD_BODY, stack="dotnet")

    bad = _lint(lint, tmp_path)

    assert [v for v in bad if "features/dotnet/skills/BadName" in v], bad


def test_the_lint_reaches_every_stack_that_ships_skills(root, load_script):
    """Criterion: all 51 shipped SKILL.md stay in scope. The oracle is an independent glob, so
    narrowing the lint's own glob makes the two disagree."""
    lint = load_script("gates/skills_lint.py")
    shipped = sorted(root.glob("features/*/skills/*/SKILL.md"))

    linted = lint.skill_files(root)

    assert linted == shipped
    assert {p.relative_to(root).parts[1] for p in linted} - {"common"}, (
        "every shipped skill is under features/common/ — this test can no longer see a "
        "glob narrowed to that one stack")

def test_duplicate_frontmatter_key_reported(tmp_path, load_script):
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body=_GOOD_BODY, frontmatter_extra="description: a short stub.\n")

    bad = _lint(lint, tmp_path)

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


# ── D4: the gate still fails for every reason it failed inside validate.py ────────────────
#
# One case per rule, each run through the gate's own CLI rather than its functions, so the
# extraction is proved end to end. A rule with no case here is a rule nobody has shown can
# still fail after the move.

_BREAKAGES = [
    ("rule 1", dict(name="Bad-Name", fm_name="Bad-Name")),
    ("rule 2", dict(name="my-skill", fm_name="other-skill")),
    ("rule 3", dict(description="")),
    ("rule 4", dict(description="Use when " + "x" * 1100)),
    ("rule 5", dict(description="Reach for this skill when testing the lint.")),
    ("rule 6", dict(body="\n".join(f"line {i}" for i in range(520)) + "\n## Gotchas\nnone\n")),
    ("rule 7", dict(body="w " * 11000 + "\n## Gotchas\nNo environment-specific gotchas known.\n")),
    ("rule 8", dict(body="Read references/details.md for the rest.\n\n## Gotchas\nnone\n")),
    ("rule 9", dict(body="# Body\n\nProse with no gotchas section at all.\n")),
    ("rule 10", dict(frontmatter_extra="prose no line-oriented reader can resolve\n")),
    ("rule 11", dict(frontmatter_extra="license: MIT\n")),
]


@pytest.mark.parametrize("rule,kwargs", _BREAKAGES, ids=[r for r, _ in _BREAKAGES])
def test_each_rule_still_fails_the_gate_when_broken(rule, kwargs, tmp_path, load_script, capsys):
    """Break one rule, run the gate, and require that rule's number in the report."""
    lint = load_script("gates/skills_lint.py")
    good = dict(body=_GOOD_BODY)
    good.update(kwargs)
    _write_skill(tmp_path, **good)

    rc = lint.main(["--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert rc == 1, out
    assert "SKILLS LINT FAILED" in out
    assert rule in out, out


def test_the_same_fixture_without_a_defect_passes(tmp_path, load_script, capsys):
    """The control every one of the eleven cases above is measured against."""
    lint = load_script("gates/skills_lint.py")
    _write_skill(tmp_path, body=_GOOD_BODY)

    assert lint.main(["--root", str(tmp_path)]) == 0
    assert "ok       skills lint" in capsys.readouterr().out
