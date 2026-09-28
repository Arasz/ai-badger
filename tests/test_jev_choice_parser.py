"""Fail-closed port of pi's `decision-router` choice parser into `jev_choice.py`.

Oracle: the semantics pinned in the S4 brief and R4 §3's validation list — `clampProbability`,
`parseAnswer` and `parseJevResponseBody` (`decision-router-client.ts:115-345`), ported to Python.
The wire body is parsed as strict JSON (pi's `JSON.parse`: `NaN`/`Infinity` are not JSON); a
directly constructed answer object carrying `float("nan")` still clamps to 0, exactly like pi's
`clampProbability` defensive branch. Nothing in this file reads a doc at runtime.
"""
# pylint: disable=redefined-outer-name  # the `mod` fixture is named by pytest convention
from __future__ import annotations

import json

import pytest

OPTIONS = ("low", "medium", "high")


@pytest.fixture
def mod(load_script):
    return load_script("features/common/skills/task-decomposition/scripts/jev_choice.py")


def choices(mod, options=OPTIONS):
    return {"P2_tier": mod.QuestionSpec("choice", tuple(options) if options else None)}


def parsed(mod, entry, name="P2_tier", options=OPTIONS):
    return mod.parse_answer(name, entry,
                            mod.QuestionSpec("choice", tuple(options) if options else None))


def body(mod, payload, options=OPTIONS):
    return mod.parse_response_body(json.dumps(payload), choices(mod, options))


# ------------------------------------------------------------------ clampProbability


@pytest.mark.parametrize("value,expected", [
    (0.5, 0.5), (1, 1.0), (0, 0.0), (-0.0, 0.0), (1.5, 1.0), (-1, 0.0),
    (float("nan"), 0.0), (float("inf"), 1.0), (float("-inf"), 0.0),
    ("2", 0.0), (True, 0.0), (False, 0.0), (None, 0.0), ([], 0.0), ({}, 0.0),
])
def test_clamp_probability_exact_semantics(mod, value, expected):
    assert mod.clamp_probability(value) == expected


# ------------------------------------------------------------------ parseAnswer rows


def test_valid_choice_answer_parses(mod):
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": {"low": 0.1, "medium": 0.2, "high": 0.7},
                          "confidence": 0.9})
    assert result.status == "ok"
    assert result.answer == mod.ChoiceAnswer("choice", "high",
                                             {"low": 0.1, "medium": 0.2, "high": 0.7}, 0.9)


def test_nan_confidence_clamps_to_zero(mod):
    # NaN cannot arrive through strict-JSON wire text (see test_nan_literal_is_malformed_body);
    # it is reachable on a constructed answer object, which is where pi's clamp branch lives.
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": {"high": 0.9}, "confidence": float("nan")})
    assert result.status == "ok"
    assert result.answer.confidence == 0.0


def test_missing_winner_probability_degrades_to_winner_only(mod):
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": {"low": 0.3, "medium": 0.3}, "confidence": 0.9})
    assert result.status == "ok"
    assert result.answer.probabilities == {"high": 1.0}
    assert result.answer.confidence == 0.0


@pytest.mark.parametrize("probabilities", [
    None, "0.9", 7, [0.9], {"high": "0.9"}, {"high": True}, {"high": float("nan")},
    {"high": float("inf")},
])
def test_unusable_probabilities_degrade_to_winner_only(mod, probabilities):
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": probabilities, "confidence": 0.9})
    assert result.status == "ok"
    assert result.answer.probabilities == {"high": 1.0}
    assert result.answer.confidence == 0.0


def test_impossible_winner_rejects_that_question_as_unknown_choice(mod):
    result = parsed(mod, {"type": "choice", "choice": "tiny", "confidence": 1.0})
    assert result.status == "reject"
    assert result.reason == "unknown-choice"
    assert result.answer is None


def test_out_of_range_probabilities_are_clamped(mod):
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": {"low": -0.2, "medium": 1.5, "high": 0.5},
                          "confidence": 0.5})
    assert result.answer.probabilities == {"low": 0.0, "medium": 1.0, "high": 0.5}


def test_string_number_and_boolean_probabilities_become_zero(mod):
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": {"low": "2", "medium": True, "high": 0.9},
                          "confidence": 0.9})
    assert result.answer.probabilities == {"low": 0.0, "medium": 0.0, "high": 0.9}


@pytest.mark.parametrize("confidence,expected", [
    (0.4, 0.4), (1.7, 1.0), (-3, 0.0), ("0.9", 0.0), (True, 0.0), (None, 0.0),
    (float("inf"), 1.0),
])
def test_confidence_is_clamped_or_zero(mod, confidence, expected):
    result = parsed(mod, {"type": "choice", "choice": "high",
                          "probabilities": {"high": 0.9}, "confidence": confidence})
    assert result.answer.confidence == expected


@pytest.mark.parametrize("entry", [None, [], [1], "choice", 7, True, b"x"])
def test_non_object_answer_is_mis_keyed(mod, entry):
    result = parsed(mod, entry)
    assert result.status == "reject"
    assert result.reason == "mis-keyed"


def test_missing_answer_is_mis_keyed(mod):
    result = mod.parse_response_body("{}", choices(mod))
    assert result.status == "ok"
    assert result.answers["P2_tier"].reason == "mis-keyed"


@pytest.mark.parametrize("entry", [
    {"score": 2}, {"type": "score", "score": 2}, {"type": None},
    {"type": "choice", "choice": None}, {"type": "choice", "choice": 7},
    {"type": "choice", "choice": ""},
])
def test_wrong_type_or_non_string_winner_is_type_mismatch(mod, entry):
    result = parsed(mod, entry)
    assert result.status == "reject"
    assert result.reason == "type-mismatch"


def test_empty_options_accepts_any_non_empty_winner(mod):
    result = parsed(mod, {"type": "choice", "choice": "anything"}, options=None)
    assert result.status == "ok"
    assert result.answer.choice == "anything"


def test_unknown_fields_are_ignored_at_answer_level(mod):
    result = parsed(mod, {"type": "choice", "choice": "high", "confidence": 0.7,
                          "probabilities": {"high": 0.7}, "notes": "ignored"})
    assert result.status == "ok"


# ------------------------------------------------------------------ parseJevResponseBody rows


def test_body_identity_and_usage_are_parsed(mod):
    result = body(mod, {"model": "typesafe/jev-1.13", "id": "req_1", "provider": "TypeSafe",
                        "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.00004},
                        "answers": {"P2_tier": {"type": "choice", "choice": "high",
                                                "probabilities": {"high": 0.9},
                                                "confidence": 0.9}}})
    assert result.status == "ok"
    assert result.model == "typesafe/jev-1.13"
    assert result.id == "req_1"
    assert result.provider == "TypeSafe"
    assert result.usage == mod.Usage(10, 2, 0.00004)


@pytest.mark.parametrize("payload", [
    "", "not json", "{", "[]", "[1]", "null", "true", "42", '"text"',
])
def test_malformed_body_rejects_as_malformed(mod, payload):
    result = mod.parse_response_body(payload, choices(mod))
    assert result.status == "reject"
    assert result.reason == "malformed"


def test_nan_literal_is_malformed_body(mod):
    # pi's JSON.parse refuses NaN/Infinity; the wire body is strict JSON.
    text = '{"answers": {"P2_tier": {"type": "choice", "choice": "high", "confidence": NaN}}}'
    result = mod.parse_response_body(text, choices(mod))
    assert result.status == "reject"
    assert result.reason == "malformed"


def test_non_object_answers_map_rejects_each_question_as_mis_keyed(mod):
    # pi's parser degrades a non-object `answers` to `{}`; the body stays ok (decision-router
    # client `parseJevResponseBody`), and each asked question is mis-keyed.
    for payload in ('{"answers": []}', '{"answers": null}', '{"answers": 7}'):
        result = mod.parse_response_body(payload, choices(mod))
        assert result.status == "ok"
        assert result.answers["P2_tier"].reason == "mis-keyed"


def test_error_envelope_is_rejected(mod):
    result = mod.parse_response_body('{"error": {"message": "boom"}}', choices(mod))
    assert result.status == "reject"
    assert result.reason == "error-envelope"


def test_one_rejected_answer_does_not_reject_the_body(mod):
    spec = {"P2_tier": mod.QuestionSpec("choice", OPTIONS),
            "P3_tier": mod.QuestionSpec("choice", OPTIONS)}
    result = mod.parse_response_body(json.dumps({"answers": {
        "P2_tier": {"type": "choice", "choice": "tiny"},
        "P3_tier": {"type": "choice", "choice": "low",
                    "probabilities": {"low": 0.8}, "confidence": 0.8}}}), spec)
    assert result.status == "ok"
    assert result.answers["P2_tier"].reason == "unknown-choice"
    assert result.answers["P3_tier"].status == "ok"


# ------------------------------------------------------------------ leakage / robustness


def test_details_are_capped_and_never_carry_body_or_prompt_text(mod):
    secret = "SECRET-PROMPT-TEXT-" + "s" * 40
    name = "q" * 400
    result = mod.parse_answer(name, {"type": "choice", "choice": "tiny",
                                     "prompt": secret, "body": secret},
                              mod.QuestionSpec("choice", ("low", "high")))
    assert result.reason == "unknown-choice"
    assert len(result.detail) <= 120
    assert secret not in result.detail
    assert name not in result.detail
    assert mod.DETAIL_CAP == 120


GARBAGE_ENTRIES = [
    None, 0, 1.5, True, "choice", b"bytes", [], {}, object(),
    {"type": "choice"}, {"type": "choice", "choice": None},
    {"type": "choice", "choice": "", "probabilities": {}},
    {"type": "choice", "choice": "high", "probabilities": {"high": "x"}},
    {"type": "choice", "choice": "high", "probabilities": {"high": 0.5}, "confidence": "0.9"},
    {"type": "choice", "choice": "high", "probabilities": {"high": 0.5},
     "confidence": float("nan")},
    {"type": "choice", "choice": "high", "probabilities": {"high": float("inf")}},
    {"type": "choice", "choice": "high", "probabilities": {"high": float("-inf")}},
    {"type": "score", "score": 1}, {"nested": {"deep": [1, 2, {"x": None}]}},
]

GARBAGE_BODIES = [
    "", "not json", "{", "[]", "[1]", "null", "true", "42", '"text"', b"\xff\xfe",
    3.14, None, object(), '{"answers": []}', '{"answers": null}', '{"answers": 7}',
    '{"answers": {"P2_tier": []}}', '{"answers": {"P2_tier": null}}',
    '{"answers": {"P2_tier": {"type": "choice", "choice": "high", "probabilities": []}}}',
    '{"error": {"message": "x"}, "answers": {"P2_tier": null}}',
    "[" * 2000 + "]" * 2000,
]


@pytest.mark.parametrize("entry", GARBAGE_ENTRIES)
def test_garbage_answers_never_raise(mod, entry):
    result = parsed(mod, entry)
    assert result.status in ("ok", "reject")
    assert result.reason in (None, "mis-keyed", "type-mismatch", "unknown-choice")


@pytest.mark.parametrize("payload", GARBAGE_BODIES)
def test_garbage_bodies_never_raise(mod, payload):
    result = mod.parse_response_body(payload, choices(mod))
    assert result.status in ("ok", "reject")
    assert result.reason in (None, "malformed", "error-envelope")
    assert isinstance(result.answers, dict)
