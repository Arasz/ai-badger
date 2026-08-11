"""An unfinished specification names its own gaps, so the interview knows when to stop.

The elicitation loop's stopping condition is structural, not conversational: a `Rule` with no
example and an example with no steps are the outstanding questions. Counting them is what
separates "the agent decided it had enough" from "the document is complete".
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from conftest import _test_write

SCRIPT = (Path(__file__).resolve().parents[1]
          / "features/common/skills/create-task-spec/scripts/spec_holes.py")

_spec = importlib.util.spec_from_file_location("spec_holes", SCRIPT)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

scan = _module.scan


COMPLETE = """\
Ability: DiscountAppliesAtCheckout
  As a returning customer
  I want the loyalty discount applied before tax
  So that the total I am quoted is the total I pay

  Rule: a loyalty discount applies before tax

    Example: discount precedes tax on a single item
      Given my cart contains "Headphones" at "60.00"
      When I open the checkout summary
      Then the discounted subtotal is "54.00"
"""


class TestACompleteSpecHasNothingOutstanding:
    def test_no_holes_are_reported(self):
        assert scan(COMPLETE) == []


class TestARuleWithoutAnExampleIsAQuestion:
    """A stated invariant nobody illustrated is the commonest half-elicited state."""

    def test_the_rule_is_reported(self):
        text = COMPLETE + "\n  Rule: an expired membership receives no discount\n"

        holes = scan(text)

        assert [h.kind for h in holes] == ["rule-without-example"]
        assert holes[0].title == "an expired membership receives no discount"

    def test_the_hole_carries_its_line_number(self):
        text = COMPLETE + "\n  Rule: an expired membership receives no discount\n"

        assert scan(text)[0].line == len(text.splitlines())


class TestAnExampleWithoutStepsIsAQuestion:
    def test_the_example_is_reported(self):
        text = COMPLETE + "\n    Example: expired membership pays list price\n"

        holes = scan(text)

        assert [h.kind for h in holes] == ["example-without-steps"]
        assert holes[0].title == "expired membership pays list price"

    def test_a_feature_level_example_counts_too(self):
        """Not every scenario sits under a Rule; one that doesn't is still elicitable."""
        text = "Ability: Thing\n\n  Example: something nobody described\n"

        assert [h.kind for h in scan(text)] == ["example-without-steps"]


class TestADeferralIsNotSilence:
    """A hole the owner ruled on is recorded as ruled, not as still-open."""

    def test_a_deferred_example_is_marked_deferred(self):
        text = COMPLETE + "\n    @deferred\n    Example: expired membership pays list price\n"

        holes = scan(text)

        assert len(holes) == 1
        assert holes[0].deferred is True

    def test_an_undeferred_hole_is_not_marked(self):
        text = COMPLETE + "\n    Example: expired membership pays list price\n"

        assert scan(text)[0].deferred is False

    def test_a_deferred_rule_is_marked_deferred(self):
        text = COMPLETE + "\n  @deferred\n  Rule: something postponed\n"

        assert scan(text)[0].deferred is True


class TestBackgroundStepsAreNotAScenariosSteps:
    """Shared setup must not make an unelicited scenario look answered."""

    def test_a_background_does_not_satisfy_a_later_example(self):
        text = (
            "Ability: Thing\n"
            "\n"
            "  Background:\n"
            "    Given I am signed in\n"
            "\n"
            "  Example: nobody wrote this one\n"
        )

        assert [h.kind for h in scan(text)] == ["example-without-steps"]

    def test_a_background_without_steps_is_not_reported_as_an_example(self):
        """A Background is not a question the loop asks; only rules and examples are."""
        text = "Ability: Thing\n\n  Background:\n\n  Example: done\n    Given something\n"

        assert scan(text) == []


class TestTheScannerReadsGherkinNotJustLines:
    def test_a_comment_is_not_a_step(self):
        text = COMPLETE + "\n    Example: commented only\n      # Given something\n"

        assert [h.kind for h in scan(text)] == ["example-without-steps"]

    def test_a_docstring_body_is_not_parsed_as_keywords(self):
        """Prose inside a doc string may contain the word Example without being one."""
        text = (
            "Ability: Thing\n"
            "\n"
            "  Example: has a doc string\n"
            '      Given a payload\n'
            '        """\n'
            "        Example: not a real scenario\n"
            "        Rule: not a real rule\n"
            '        """\n'
            "      Then it is accepted\n"
        )

        assert scan(text) == []

    def test_scenario_is_accepted_as_a_synonym_for_example(self):
        text = "Feature: Thing\n\n  Scenario: nobody wrote this one\n"

        assert [h.kind for h in scan(text)] == ["example-without-steps"]

    def test_every_step_keyword_counts_as_a_step(self):
        for keyword in ("Given", "When", "Then", "And", "But", "*"):
            text = f"Ability: Thing\n\n  Example: filled\n    {keyword} something happens\n"

            assert scan(text) == [], f"{keyword} was not recognised as a step"


class TestHolesAreReportedInDocumentOrder:
    def test_the_queue_follows_the_file(self):
        text = (
            "Ability: Thing\n"
            "\n"
            "  Rule: first rule\n"
            "\n"
            "  Rule: second rule\n"
            "\n"
            "    Example: unelicited\n"
        )

        holes = scan(text)

        assert [h.kind for h in holes] == ["rule-without-example", "example-without-steps"]
        assert [h.line for h in holes] == sorted(h.line for h in holes)


class TestTheExitCodeIsTheGate:
    """Automation reads the exit code; a format flag must not change what it means (#269)."""

    def _spec(self, tmp_path, body):
        path = tmp_path / "Demo.feature"
        _test_write(path, body, encoding="utf-8")
        return str(path)

    def test_an_open_hole_exits_non_zero(self, tmp_path):
        target = self._spec(tmp_path, COMPLETE + "\n  Rule: nobody illustrated this\n")

        assert _module._main([target]) == 1

    def test_an_open_hole_exits_non_zero_with_json_too(self, tmp_path):
        """The regression: --json reported the holes but told the caller everything was fine."""
        target = self._spec(tmp_path, COMPLETE + "\n  Rule: nobody illustrated this\n")

        assert _module._main([target, "--json"]) == 1

    def test_a_complete_spec_exits_zero_in_both_formats(self, tmp_path):
        target = self._spec(tmp_path, COMPLETE)

        assert _module._main([target]) == 0
        assert _module._main([target, "--json"]) == 0

    def test_a_fully_deferred_spec_exits_zero_in_both_formats(self, tmp_path):
        """A ruled deferral is not an open question, whichever format asked."""
        target = self._spec(tmp_path, COMPLETE + "\n  @deferred\n  Rule: postponed\n")

        assert _module._main([target]) == 0
        assert _module._main([target, "--json"]) == 0
