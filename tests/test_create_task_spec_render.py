"""A rendered spec shows what is missing, not just what was written.

Plain Gherkin is legible but flat: it reads the same whether every question has been answered or
half of them are still open. The renderer's job is to make an unfinished spec look unfinished.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1]
          / "features/common/skills/create-task-spec/scripts/render_spec.py")

_spec = importlib.util.spec_from_file_location("render_spec", SCRIPT)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

render = _module.render


COMPLETE = """\
Ability: DiscountAppliesAtCheckout
  As a returning customer
  I want the loyalty discount applied before tax
  So that the total I am quoted is the total I pay

  Rule: a loyalty discount applies before tax

    Example: discount precedes tax
      Given my cart contains "Headphones" at "60.00"
      When I open the checkout summary
      Then the discounted subtotal is "54.00"
"""


class TestTheRenderedPageStandsAlone:
    """A file:// page with an external asset is a broken page."""

    def test_it_is_a_whole_document(self):
        html = render(COMPLETE)

        assert html.lstrip().startswith("<!doctype html>")
        assert "</html>" in html

    def test_it_carries_its_own_styles(self):
        assert "<style>" in render(COMPLETE)

    def test_it_references_nothing_external(self):
        html = render(COMPLETE)

        assert "http://" not in html
        assert "https://" not in html


class TestTheSpecsContentSurvives:
    def test_the_ability_title_is_shown(self):
        assert "DiscountAppliesAtCheckout" in render(COMPLETE)

    def test_the_user_story_is_shown(self):
        assert "As a returning customer" in render(COMPLETE)

    def test_a_rule_is_shown(self):
        assert "a loyalty discount applies before tax" in render(COMPLETE)

    def test_a_step_is_shown(self):
        assert "I open the checkout summary" in render(COMPLETE)


class TestHolesAreVisibleNotJustCounted:
    """The whole point of rendering: an unfinished spec must look unfinished."""

    def test_a_rule_without_an_example_is_marked(self):
        html = render(COMPLETE + "\n  Rule: an expired membership gets no discount\n")

        assert "rule-without-example" in html

    def test_an_example_without_steps_is_marked(self):
        html = render(COMPLETE + "\n    Example: nobody elicited this\n")

        assert "example-without-steps" in html

    def test_a_complete_spec_reports_no_open_questions(self):
        html = render(COMPLETE)

        assert "rule-without-example" not in html
        assert "example-without-steps" not in html

    def test_a_deferred_hole_reads_as_ruled_not_open(self):
        html = render(COMPLETE + "\n  @deferred\n  Rule: postponed for now\n")

        assert "deferred" in html.lower()


class TestUntrustedTextCannotBecomeMarkup:
    """Spec text is written by a person and rendered into a page; it is not markup."""

    def test_angle_brackets_in_a_title_are_escaped(self):
        html = render('Ability: Thing\n\n  Example: handles <script>alert(1)</script>\n')

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_an_ampersand_is_escaped(self):
        html = render("Ability: Thing\n\n  Example: terms & conditions\n    Given a thing\n")

        assert "terms &amp; conditions" in html


class TestTheManifestJoinsTheBehaviour:
    """Scope and constraints live in the manifest; the page is where they meet the spec."""

    def test_manifest_scope_is_rendered_when_supplied(self):
        html = render(COMPLETE, manifest={"scope": "Checkout pricing only",
                                          "outOfScope": ["Refunds"]})

        assert "Checkout pricing only" in html
        assert "Refunds" in html

    def test_the_page_renders_without_a_manifest(self):
        assert "DiscountAppliesAtCheckout" in render(COMPLETE, manifest=None)
