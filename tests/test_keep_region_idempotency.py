"""Re-scaffolding must not grow a template that ships its own keep region.

`carry_keep_regions` appends the existing file's preserved blocks to the freshly rendered
body. That is correct while no template carries a keep region of its own — and pi's
AGENTS.override.md.tmpl is the first that does, so enabling pi made every re-scaffold append
one more copy: run N produced N blocks, unbounded. The scaffolder's contract is that it is
idempotent and safe to re-run, and the freshness guard fails the moment it is not.
"""
from __future__ import annotations

SCRIPTS = "features/common/skills/welcome-ai-badger/scripts"

BLOCK = (
    "<!-- ai-badger:keep-start -->\n"
    "<!-- Project-specific overrides go here (survives re-scaffold) -->\n"
    "<!-- ai-badger:keep-end -->"
)


def _shared(load_script):
    return load_script(f"{SCRIPTS}/_shared.py")


def test_a_template_with_its_own_keep_region_does_not_grow_on_re_scaffold(load_script):
    carry = _shared(load_script).carry_keep_regions
    template_body = f"# pi\n\nsome managed prose\n\n{BLOCK}\n"

    once = carry(template_body, template_body)
    twice = carry(once, template_body)
    thrice = carry(twice, template_body)

    assert once.count("ai-badger:keep-start") == 1
    assert twice.count("ai-badger:keep-start") == 1
    assert thrice.count("ai-badger:keep-start") == 1


def test_the_edited_content_of_a_kept_region_survives(load_script):
    carry = _shared(load_script).carry_keep_regions
    template_body = f"# pi\n\nmanaged prose\n\n{BLOCK}\n"
    edited = (
        "# pi\n\nold managed prose\n\n"
        "<!-- ai-badger:keep-start -->\n"
        "my project note\n"
        "<!-- ai-badger:keep-end -->\n"
    )

    result = carry(edited, template_body)

    assert "my project note" in result
    assert "managed prose" in result
    assert result.count("ai-badger:keep-start") == 1


def test_a_body_without_keep_regions_still_receives_the_existing_ones(load_script):
    """The original behaviour: templates with no slot of their own must keep appending."""
    carry = _shared(load_script).carry_keep_regions
    edited = f"# thing\n\n{BLOCK}\n"

    result = carry(edited, "# thing\n\nfresh body\n")

    assert result.count("ai-badger:keep-start") == 1
    assert "fresh body" in result


def test_more_edited_regions_than_the_template_offers_are_all_preserved(load_script):
    carry = _shared(load_script).carry_keep_regions
    template_body = f"# pi\n\nmanaged\n\n{BLOCK}\n"
    edited = (
        "# pi\n\nmanaged\n\n"
        "<!-- ai-badger:keep-start -->\nfirst\n<!-- ai-badger:keep-end -->\n\n"
        "<!-- ai-badger:keep-start -->\nsecond\n<!-- ai-badger:keep-end -->\n"
    )

    result = carry(edited, template_body)

    assert "first" in result
    assert "second" in result
    assert result.count("ai-badger:keep-start") == 2
