"""Jev half of query_pipeline.py: constants, wire bodies, classifier, attempts and batching.

Goldens come from pi's `jev-client.ts` run under bun (`pipeline_goldens.json`,
`score_fixtures.json`). Every row drives an injected `post` and a `Budget` on a fake clock.
"""
from __future__ import annotations

import json
import logging
import time
from typing import NamedTuple, Optional

import pytest

from memory_context_support import FIXTURES, load_module, memory_context_env  # noqa: F401

mc = load_module()
qp = mc._load_sibling("query_pipeline")  # pylint: disable=protected-access

GOLDENS = json.loads((FIXTURES / "pipeline_goldens.json").read_text(encoding="utf-8"))
INPUTS = json.loads((FIXTURES / "pipeline_golden_inputs.json").read_text(encoding="utf-8"))
SCORE_FIXTURES = json.loads((FIXTURES / "score_fixtures.json").read_text(encoding="utf-8"))
BASE = "http://127.0.0.1:9"
KEY = "sk-test-jev-SECRETKEY"


class Reply(NamedTuple):
    """openrouter_client's `Reply`: failures arrive as status 0 with `error` timeout/transport."""

    status: int
    headers: dict
    body: bytes
    error: Optional[str] = None


TIMEOUT = Reply(0, {}, b"", "timeout")
TRANSPORT = Reply(0, {}, b"", "transport")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Post:
    """Scripted `post`: a reply list (the last repeats) or a function of the request body."""

    def __init__(self, *replies, respond=None, advance=0.0, clock=None):
        self.replies = list(replies)
        self.respond = respond
        self.advance = advance
        self.clock = clock
        self.calls = []

    def __call__(self, url, body, key, budget):
        self.calls.append({"url": url, "body": body, "key": key, "remaining": budget.remaining()})
        if self.clock is not None:
            self.clock.now += self.advance
        if self.respond is not None:
            return self.respond(body)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def answers_reply(scores: dict) -> Reply:
    body = {"answers": {name: {"type": "score", "score": value} for name, value in scores.items()}}
    return Reply(200, {}, json.dumps(body).encode())


def ok_for(body) -> Reply:
    return answers_reply({name: 2 for name in body["questions"]})


def hits(count: int, prefix: str = "h"):
    return [{"hash": f"{prefix}{i}", "path": f"docs/{prefix}{i}.md",
             "snippet": f"snippet {prefix}{i}", "kind": "memory"} for i in range(count)]


def run_score(pool, post, budget=None, key=KEY, base=BASE, query="the prompt"):
    return qp.score(query, pool, post=post, base=base, key=key,
                    budget=budget if budget is not None else mc.Budget(8, clock=Clock()))


# ------------------------------------------------------------------ J1 constants


def test_j1_constants_equal_pi():
    pi = GOLDENS["jev"]["constants"]
    assert qp.BATCH_MAX == pi["SCORE_BATCH_MAX"] == 12
    assert qp.ATTEMPTS == pi["SCORE_ATTEMPTS"] == 3
    assert qp.POOL_MAX == pi["SCORE_POOL_MAX"] == 48
    assert qp.ATTEMPT_SECONDS * 1000 == pi["SCORE_TIMEOUT_DEFAULT_MS"]
    assert qp.ATTEMPT_SECONDS == mc.ATTEMPT_SECONDS
    assert qp.STATE_CHAR_CAP == pi["SCORE_STATE_CHAR_CAP"] == 32000
    assert qp.EXCERPT_CHAR_CAP == pi["SCORE_EXCERPT_CHAR_CAP"] == 500
    assert qp.MODEL == pi["SCORE_MODEL_DEFAULT"] == "typesafe/jev-1.13"
    assert "https://openrouter.ai" + qp.DECISIONS_PATH == pi["SCORE_ENDPOINT_DEFAULT"]
    assert qp.SCORE_QUESTION == pi["SCORE_QUESTION"] == SCORE_FIXTURES["MEASURED_QUESTION"]
    assert list(qp.SCORE_CRITERIA) == pi["SCORE_CRITERIA"] == SCORE_FIXTURES["MEASURED_CRITERIA"]
    assert list(qp.ERROR_KINDS) == pi["SCORE_ERROR_KINDS"]
    assert list(qp.RETRYABLE_KINDS) == pi["SCORE_RETRYABLE_KINDS"]


# ------------------------------------------------------------------ J2 wire bodies


def resolve_set(entry):
    """The generator's own expansion of one `wire_candidate_sets` entry."""
    if "prompt_repeat" in entry:
        prompt = entry["prompt_repeat"]["char"] * entry["prompt_repeat"]["count"]
    else:
        prompt = entry["prompt"]
    generated = entry.get("candidates_generated")
    if generated:
        out = []
        for i in range(generated["count"]):
            cand = {"hash": f"{generated['hash_prefix']}{i}",
                    "path": f"docs/{generated['hash_prefix']}{i}.md",
                    "snippet": f"snippet {generated['hash_prefix']}{i}", "kind": "memory"}
            if generated.get("ranking_formula") == "50 - index":
                cand["ranking"] = 50 - i
            out.append(cand)
        return prompt, out
    out = []
    for spec in entry["candidates"]:
        cand = dict(spec)
        repeat = cand.pop("snippet_repeat", None)
        if repeat:
            cand["snippet"] = repeat["char"] * repeat["count"]
        out.append(cand)
    return prompt, out


@pytest.mark.parametrize("entry", INPUTS["jev"]["wire_candidate_sets"], ids=lambda e: e["id"])
def test_j2_wire_bodies_equal_pi(entry):
    golden = {g["id"]: g["requests"] for g in GOLDENS["jev"]["wire_bodies"]}[entry["id"]]
    prompt, candidates = resolve_set(entry)
    pool = qp.make_pool(candidates, [], list)
    post = Post(respond=lambda body: answers_reply({}))
    run_score(pool, post, query=prompt, budget=mc.Budget(60, clock=Clock()))
    assert [c["body"] for c in post.calls] == golden
    assert all(c["url"] == BASE + qp.DECISIONS_PATH and c["key"] == KEY for c in post.calls)


def test_j2_measured_request_is_reproduced():
    request = SCORE_FIXTURES["MEASURED_SCORE_REQUEST"]
    wires = [q["instructions"]["candidate"] for q in request["questions"].values()]
    pool = [{"hash": f"m{i}", "path": w["path"], "kind": w["kind"], "snippet": w["excerpt"]}
            for i, w in enumerate(wires)]
    post = Post(answers_reply({}))
    run_score(pool, post, query=SCORE_FIXTURES["MEASURED_PROMPT"])
    assert post.calls[0]["body"] == request


def test_j2_question_fields_follow_js_nullish_and_code_points():
    question = qp.build_score_question({"path": None, "sourceFile": "docs/s.md",
                                        "snippet": "\U0001F600" * 600})
    candidate = question["instructions"]["candidate"]
    assert candidate == {"path": "docs/s.md", "kind": "memory", "excerpt": "\U0001F600" * 500}
    assert qp.build_score_question({"path": "", "sourceFile": "x"})["instructions"]["candidate"] \
        == {"path": "", "kind": "memory", "excerpt": ""}
    assert qp.build_score_question({"kind": "code"})["instructions"]["candidate"]["kind"] == "code"


# ------------------------------------------------------------------ J3 batching


@pytest.mark.parametrize("count,batches", [(25, [12, 12, 1]), (12, [12]), (13, [12, 1])])
def test_j3_batches_of_twelve_with_their_own_names(count, batches):
    post = Post(respond=ok_for)
    run_score(hits(count), post)
    sizes = [len(c["body"]["questions"]) for c in post.calls]
    assert sizes == batches
    names = [name for c in post.calls for name in c["body"]["questions"]]
    assert names == [f"c{i}" for i in range(count)]


# ------------------------------------------------------------------ J4 classifier


@pytest.mark.parametrize("case", INPUTS["jev"]["classify_cases"], ids=lambda c: c["id"])
def test_j4_classify_equals_pi(case):
    golden = {g["id"]: g["outcome"] for g in GOLDENS["jev"]["classify"]}[case["id"]]
    names = case.get("names", ["c0"])
    verdict = qp.classify(Reply(case["status"], {}, case["body"].encode()), names)
    if golden["status"] == "ok":
        assert verdict.kind == "ok"
        assert verdict.answers == {n: a["score"] for n, a in golden["batch"]["answers"].items()}
    else:
        assert verdict.kind == golden["kind"]
        assert verdict.answers == {}


def test_j4_answer_tolerance_equals_pi():
    golden = GOLDENS["jev"]["answer_tolerance"]["batch"]["answers"]
    body = INPUTS["jev"]["answer_tolerance_body"].encode()
    verdict = qp.classify(Reply(200, {}, body), INPUTS["jev"]["answer_tolerance_names"])
    assert verdict.kind == "ok"
    assert verdict.answers == {n: a["score"] for n, a in golden.items()}


@pytest.mark.parametrize("reply,kind", [
    (TIMEOUT, "transport-timeout"),
    (TRANSPORT, "transport-timeout"),
    ("timeout", "transport-timeout"),
    (None, "transport-timeout"),
    (object(), "transport-timeout"),
    (Reply(200, {}, b"[1, 2]"), "malformed"),
    (Reply(200, {}, b'"text"'), "malformed"),
    (Reply(200, {}, b'{"error": null}'), "server"),
    (Reply(200, {}, b'{"answers": {"c0": {"type": "score", "score": NaN}}}'), "malformed"),
    (Reply(200, {}, "not bytes"), "malformed"),
    (Reply(200, {}, b"\xff\xfe"), "malformed"),
])
def test_j4_classify_never_raises(reply, kind):
    assert qp.classify(reply, ["c0"]).kind == kind


# ------------------------------------------------------------------ J5 retries


@pytest.mark.parametrize("replies,posts", [
    ([Reply(500, {}, b""), answers_reply({"c0": 1})], 2),
    ([Reply(500, {}, b"")] * 4, 3),
    ([TIMEOUT, answers_reply({"c0": 1})], 2),
    ([TRANSPORT, answers_reply({"c0": 1})], 2),
    ([Reply(401, {}, b""), answers_reply({"c0": 1})], 1),
    ([Reply(402, {}, b""), answers_reply({"c0": 1})], 1),
    ([Reply(400, {}, b""), answers_reply({"c0": 1})], 1),
], ids=["500-then-ok", "500x4", "timeout-then-ok", "transport-then-ok", "401", "402", "400"])
def test_j5_retry_only_retryable_kinds(replies, posts):
    post = Post(*replies)
    run_score(hits(1), post)
    assert len(post.calls) == posts


def test_j5_rate_limit_retries_without_sleeping(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    limited = Reply(429, {}, b"")
    post = Post(limited, limited, answers_reply({"c0": 2.5}))
    assert run_score(hits(1), post) == [2.5]
    assert len(post.calls) == 3
    assert sleeps == []


# ------------------------------------------------------------------ J6a deadlines


def test_j6a_each_attempt_gets_min_of_attempt_and_stage_share():
    clock = Clock()
    post = Post(Reply(500, {}, b""), advance=7.0, clock=clock)
    assert run_score(hits(1), post, budget=mc.Budget(20, clock=clock)) == [None]
    assert [c["remaining"] for c in post.calls] == [15.0, 13.0, 6.0]


def test_j6a_long_stage_caps_each_attempt_at_fifteen():
    clock = Clock()
    post = Post(Reply(500, {}, b""), advance=1.0, clock=clock)
    run_score(hits(1), post, budget=mc.Budget(40, clock=clock))
    assert [c["remaining"] for c in post.calls] == [15.0, 15.0, 15.0]


def test_j6a_exhausted_stage_skips_remaining_batches():
    clock = Clock()
    post = Post(respond=ok_for, advance=9.0, clock=clock)
    result = run_score(hits(13), post, budget=mc.Budget(8, clock=clock))
    assert len(post.calls) == 1
    assert result == [2.0] * 12 + [None]


@pytest.mark.parametrize("key,base,expired", [
    (None, BASE, False), ("   ", BASE, False), (KEY, None, False), (KEY, BASE, True)])
def test_j6a_no_key_no_base_or_no_time_posts_nothing(key, base, expired):
    clock = Clock()
    budget = mc.Budget(8, clock=clock)
    if expired:
        clock.now = 9.0
    post = Post(answers_reply({"c0": 3}))
    assert run_score(hits(3), post, budget=budget, key=key, base=base) == [None, None, None]
    assert post.calls == []


def test_j6a_empty_pool_posts_nothing():
    post = Post(answers_reply({}))
    assert run_score([], post) == []
    assert post.calls == []


# ------------------------------------------------------------------ J7 partial failure


def test_j7_one_failed_batch_nulls_only_its_own_entries():
    def respond(body):
        return Reply(401, {}, b"") if "c12" in body["questions"] else ok_for(body)

    post = Post(respond=respond)
    result = run_score(hits(25), post)
    assert len(post.calls) == 3
    assert result == [2.0] * 12 + [None] * 12 + [2.0]


# ------------------------------------------------------------------ J8 answer tolerance


def test_j8_answers_are_tolerant_and_aligned():
    answers = {
        "c3": {"type": "score", "score": 1, "extra": "ignored"},
        "c0": {"type": "score", "score": 4.2},
        "c1": {"type": "score", "score": -1},
        "c2": {"type": "choice", "score": 2},
        "c4": {"type": "score", "score": "2"},
        "c5": {"type": "score", "score": 1e999},
        "c6": {"type": "score", "score": True},
    }
    body = json.dumps({"answers": answers}).replace("Infinity", "1e999").encode()
    result = run_score(hits(8), Post(Reply(200, {}, body)))
    assert result == [3.0, 0.0, None, 1.0, None, None, None, None]
    assert all(value is None or isinstance(value, float) for value in result)


# ------------------------------------------------------------------ J9 leak


def test_j9_error_bodies_and_key_never_surface(capsys, caplog):
    caplog.set_level(logging.DEBUG)
    bodies = [(400, "SYNTH_SCORE_BAD_REQUEST_BODY"), (401, "SYNTH_SCORE_UNAUTHORIZED_BODY"),
              (402, "SYNTH_SCORE_PAYMENT_REQUIRED_BODY"), (429, "SYNTH_SCORE_RATE_LIMITED_BODY"),
              (500, "SYNTH_SCORE_SERVER_ERROR_BODY"), (200, "SYNTH_SCORE_ERROR_ENVELOPE"),
              (200, "SYNTH_SCORE_TRUNCATED_JSON")]
    seen = []
    for status, name in bodies:
        reply = Reply(status, {}, SCORE_FIXTURES[name].encode())
        seen.append(repr(qp.classify(reply, ["c0"])))
        seen.append(repr(run_score(hits(2), Post(reply))))
    out, err = capsys.readouterr()
    for text in seen + [out, err, caplog.text]:
        assert "SECRET-BODY-MARKER" not in text
        assert KEY not in text
