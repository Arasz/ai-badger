"""The banner and YAML frontmatter both want line 1, and only frontmatter may have it (#241).

VS Code and Copilot read an instruction file's frontmatter only when `---` is the literal first
line, so a banner above it makes `applyTo` unresolvable and the whole file inert. The banner
therefore moves below the closing fence — and the managed-file check has to still find it there,
or every managed instruction file reads as hand-authored and stops being refreshed.
"""
# pylint: disable=protected-access  # exercises the writer's internals directly
from __future__ import annotations

import sys

import pytest

from scaffold_helpers import _config
from conftest import _test_write

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"
NAME = "instructions/python.instructions.md"

FRONTMATTER_BODY = (
    "---\n"
    "description: 'Modern Python conventions.'\n"
    "applyTo: '**/*.py'\n"
    "---\n"
    "\n"
    "# Python\n"
)


@pytest.fixture(name="rendering")
def rendering_fixture(load_script, root):
    """The template_rendering module, loaded the way scaffold.py's bootstrap makes it importable."""
    for entry in (str(root / SCRIPTS), str(root / "engine"), str(root / "tooling")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return load_script(f"{SCRIPTS}/template_rendering.py")


@pytest.fixture(name="banner")
def banner_fixture(load_script, root):
    """The rendered managed banner for a given source-of-truth name."""
    for entry in (str(root / SCRIPTS),):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    header = load_script(f"{SCRIPTS}/_shared.py").MANAGED_HEADER
    return lambda name=NAME: header.format(name=name)


def _frontmatter(text: str) -> dict:
    """What a strict line-1 frontmatter parser reads from `text`, or {} when it reads nothing.

    Deliberately as unforgiving as the consumer: `---` on line 1 or there is no frontmatter.
    """
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return {}
    if "---" not in lines[1:]:
        return {}
    fields = {}
    for line in lines[1:lines.index("---", 1)]:
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


# ------------------------------------------------------------------- where the banner goes
def test_a_body_without_frontmatter_keeps_the_banner_on_line_one(rendering, banner):
    body = "# Title\n\nsome guidance\n"

    assert rendering._with_managed_header(body, NAME) == banner() + body


def test_frontmatter_keeps_line_one_and_the_banner_follows_the_closing_fence(rendering, banner):
    out = rendering._with_managed_header(FRONTMATTER_BODY, NAME)

    assert out.splitlines()[0] == "---"
    assert out == (
        "---\n"
        "description: 'Modern Python conventions.'\n"
        "applyTo: '**/*.py'\n"
        "---\n"
        "\n" + banner() + "\n# Python\n"
    )
    assert _frontmatter(out)["applyTo"] == "**/*.py"


def test_only_the_first_fence_pair_is_frontmatter(rendering, banner):
    """A `---` further down is a thematic break; moving the banner there corrupts the file."""
    body = "---\ndescription: 'x'\n---\n\n# Title\n\n---\n\nafter the break\n"

    out = rendering._with_managed_header(body, NAME)

    assert out.startswith("---\ndescription: 'x'\n---\n\n" + banner())
    assert out.endswith("# Title\n\n---\n\nafter the break\n")


def test_a_fenced_yaml_block_is_not_frontmatter(rendering, banner):
    body = "# Doc\n\n```yaml\n---\nkey: value\n---\n```\n"

    assert rendering._with_managed_header(body, NAME) == banner() + body


def test_an_unterminated_opening_fence_is_not_frontmatter(rendering, banner):
    body = "---\ndescription: 'x'\n\n# Title\n"

    assert rendering._with_managed_header(body, NAME) == banner() + body


def test_an_empty_body_is_the_banner_alone(rendering, banner):
    assert rendering._with_managed_header("", NAME) == banner()


def test_crlf_frontmatter_is_found_and_the_separator_matches_the_file(rendering, banner):
    body = "---\r\ndescription: 'x'\r\napplyTo: '**/*.py'\r\n---\r\n\r\n# Title\r\n"

    out = rendering._with_managed_header(body, NAME)

    assert out.splitlines()[0] == "---"
    assert out.startswith("---\r\ndescription: 'x'\r\napplyTo: '**/*.py'\r\n---\r\n\r\n" + banner())
    assert out.endswith("\r\n# Title\r\n")


# ------------------------------------------------------- what counts as a managed copy
def _instruction_file(scaffolder, text=None):
    """The scoped-instruction path copy_with_header writes, optionally seeded with `text`."""
    dest = scaffolder.ctx.target / ".github" / "instructions" / "python.instructions.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        _test_write(dest, text, encoding="utf-8")
    return dest


def _preserved_notes(scaffolder) -> list:
    return [n for n in scaffolder.ctx.notes if "preserved hand-authored" in n]


def test_writing_the_same_body_twice_leaves_the_file_byte_identical(make_scaffolder):
    scaffolder = make_scaffolder()
    dest = _instruction_file(scaffolder)

    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)
    first = dest.read_text(encoding="utf-8")
    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)

    assert dest.read_text(encoding="utf-8") == first


def test_a_banner_on_line_one_is_still_a_managed_copy(make_scaffolder, banner):
    """Files written before the fix carry the banner above the fence; they must keep updating."""
    scaffolder = make_scaffolder()
    dest = _instruction_file(scaffolder, banner() + "---\napplyTo: 'old'\n---\n\n# Old\n")

    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)

    assert "# Python" in dest.read_text(encoding="utf-8")
    assert not _preserved_notes(scaffolder)


def test_a_banner_below_the_frontmatter_is_a_managed_copy(make_scaffolder, rendering):
    scaffolder = make_scaffolder()
    dest = _instruction_file(
        scaffolder, rendering._with_managed_header("---\napplyTo: 'old'\n---\n\n# Old\n", NAME))

    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)

    assert "# Python" in dest.read_text(encoding="utf-8")
    assert not _preserved_notes(scaffolder)


def test_a_hand_authored_file_is_preserved(make_scaffolder):
    scaffolder = make_scaffolder()
    hand_authored = "---\napplyTo: 'mine'\n---\n\n# Mine\n"
    dest = _instruction_file(scaffolder, hand_authored)

    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)

    assert dest.read_text(encoding="utf-8") == hand_authored
    assert _preserved_notes(scaffolder)


def test_a_hand_authored_file_quoting_the_banner_far_down_is_preserved(make_scaffolder, banner):
    """The scan is bounded, so a document that merely quotes the banner is not misread."""
    scaffolder = make_scaffolder()
    hand_authored = "".join(f"line {i}\n" for i in range(39)) + banner()
    dest = _instruction_file(scaffolder, hand_authored)

    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)

    assert dest.read_text(encoding="utf-8") == hand_authored
    assert _preserved_notes(scaffolder)


def test_overwrite_replaces_a_hand_authored_file(make_scaffolder):
    scaffolder = make_scaffolder(overwrite=True)
    dest = _instruction_file(scaffolder, "---\napplyTo: 'mine'\n---\n\n# Mine\n")

    scaffolder.rendering.copy_with_header(dest, NAME, FRONTMATTER_BODY)

    assert "# Python" in dest.read_text(encoding="utf-8")


# ---------------------------------------------------------- the contract with the consumer
def _scaffold_instruction_files(make_scaffolder, **kwargs):
    """Run a scaffold that ships scoped instruction files, and return them."""
    result = make_scaffolder(
        config=_config(stacks=["python", "ts"], agents=["copilot"]), **kwargs
    ).run(generated_at="2026-07-31T00:00:00Z")
    files = sorted((make_scaffolder.target / ".github" / "instructions").glob("*.md"))
    assert files, "expected the copilot scaffold to write scoped instruction files"
    return files, result


def test_every_generated_instruction_file_opens_with_the_fence(make_scaffolder):
    files, _ = _scaffold_instruction_files(make_scaffolder)

    for path in files:
        assert path.read_text(encoding="utf-8").split("\n")[0] == "---", \
            f"{path.name}: line 1 is not the frontmatter fence"


def test_every_generated_instruction_file_resolves_applyto_and_description(make_scaffolder):
    """The permanent guard: what the consumer can read, not what the file looks like."""
    files, _ = _scaffold_instruction_files(make_scaffolder)

    for path in files:
        fields = _frontmatter(path.read_text(encoding="utf-8"))
        assert fields.get("applyTo"), f"{path.name}: applyTo does not resolve"
        assert fields.get("description"), f"{path.name}: description does not resolve"


def test_a_second_scaffold_changes_no_instruction_file(make_scaffolder):
    files, _ = _scaffold_instruction_files(make_scaffolder)
    before = {p: p.read_text(encoding="utf-8") for p in files}

    _scaffold_instruction_files(make_scaffolder)

    assert {p: p.read_text(encoding="utf-8") for p in files} == before


def test_a_hand_edited_managed_instruction_file_is_refreshed(make_scaffolder):
    files, _ = _scaffold_instruction_files(make_scaffolder)
    edited = files[0]
    _test_write(edited, edited.read_text(encoding="utf-8") + "\nstray local edit\n", encoding="utf-8")

    _, result = _scaffold_instruction_files(make_scaffolder)

    content = edited.read_text(encoding="utf-8")
    assert "stray local edit" not in content
    assert content.split("\n")[0] == "---"
    assert not any("preserved hand-authored" in n and edited.name in n for n in result["notes"])
