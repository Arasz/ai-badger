"""Planner half of query_pipeline.py: pi's prose, `parse_plan`, the model table and the call.

Goldens come from pi's `planner.ts` run under bun (`pipeline_goldens.json`). Every row drives an
injected `post` and a `Budget` on a fake clock; nothing touches a socket.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional

import pytest

from memory_context_support import FIXTURES, ROOT, load_module, memory_context_env  # noqa: F401

mc = load_module()
qp = mc._load_sibling("query_pipeline")  # pylint: disable=protected-access

GOLDENS = json.loads((FIXTURES / "pipeline_goldens.json").read_text(encoding="utf-8"))
INPUTS = json.loads((FIXTURES / "pipeline_golden_inputs.json").read_text(encoding="utf-8"))
BASE = "http://127.0.0.1:9"
KEY = "sk-test-planner"
PLAN_TEXT = '{"concepts":[{"name":"n","queries":["alpha query","beta query"]}]}'
PLAN = {"concepts": [{"name": "n", "queries": ["alpha query", "beta query"]}]}


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
    """Scripted `post`: returns the replies in order (the last repeats) and records each call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, body, key, budget):
        self.calls.append({"url": url, "body": body, "key": key, "remaining": budget.remaining()})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def chat(content: Any, status: int = 200) -> Reply:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return Reply(status, {"content-type": "application/json"}, json.dumps(body).encode())


def call(post, model="vendor/m", base=BASE, key=KEY, query="how does the gate work"):
    return qp.plan(query, post=post, base=base, key=key, model=model,
                   budget=mc.Budget(15, clock=Clock()))


def as_pi(result):
    if result.status == "ok":
        return {"status": "ok", "plan": result.plan}
    return {"status": "fallback", "reason": result.reason}


def test_module_loads():
    assert qp is not None


# ------------------------------------------------------------------ PL1, PL2 prose


def test_pl1_prose_equals_pi_goldens():
    golden = GOLDENS["planner"]
    assert qp.PLANNER_ADDENDUM == golden["planner_addendum"]
    assert qp.PLANNER_USER_PREFIX == golden["planner_user_prefix"]
    assert qp.DELEGATOR_PERSONA == golden["delegator_persona"]
    queries = {e["id"]: e["query"] for e in INPUTS["planner"]["build_user_prompt_queries"]}
    for entry in golden["build_user_prompt"]:
        assert qp.build_user_prompt(queries[entry["id"]]) == entry["output"], entry["id"]


def test_pl1_system_prompt_joins_persona_and_addendum():
    post = Post(chat(PLAN_TEXT))
    call(post)
    system = post.calls[0]["body"]["messages"][0]["content"]
    assert system == qp.DELEGATOR_PERSONA + "\n\n" + qp.PLANNER_ADDENDUM


def test_pl2_persona_equals_the_catalog_delegator():
    text = (ROOT / "features" / "common" / "personas" / "delegator.md").read_text(encoding="utf-8")
    assert qp.DELEGATOR_PERSONA == text[text.index("# Delegator"):]
    assert "name: delegator" not in qp.DELEGATOR_PERSONA
    assert "Managed by" not in qp.DELEGATOR_PERSONA


# ------------------------------------------------------------------ PL3 parse_plan


def test_pl3_parse_plan_matches_pi_on_the_corpus():
    texts = {e["id"]: e["text"] for e in INPUTS["planner"]["parse_plan_corpus"]}
    mismatches = [entry["id"] for entry in GOLDENS["planner"]["parse_plan"]
                  if as_pi(qp.parse_plan(texts[entry["id"]])) != entry["output"]]
    assert mismatches == []


def test_pl3_js_trim_twin_matches_memory_context():
    assert qp.JS_SPACE == mc.JS_SPACE


@pytest.mark.parametrize("text", [None, 42, ["{}"], "﻿ 　"])
def test_pl3_non_text_and_js_blank_are_empty_text(text):
    assert as_pi(qp.parse_plan(text)) == {"status": "fallback", "reason": "empty-text"}


def test_pl3_a_closing_brace_inside_a_string_is_inert():
    text = '{"concepts":[{"name":"n}","queries":["alpha","beta"]}]}'
    assert as_pi(qp.parse_plan(text)) == {
        "status": "ok", "plan": {"concepts": [{"name": "n}", "queries": ["alpha", "beta"]}]}}


def test_pl3_nan_literal_is_not_json():
    text = '{"concepts":[{"name":"n","queries":["a","b"]}],"x":NaN}'
    assert as_pi(qp.parse_plan(text)) == {"status": "fallback", "reason": "invalid-shape"}


def test_pl3_one_mib_of_braces_is_refused_fast():
    start = time.monotonic()
    result = qp.parse_plan("{" * (1024 * 1024))
    assert time.monotonic() - start < 0.5
    assert as_pi(result) == {"status": "fallback", "reason": "no-json-object"}


def test_pl3_over_the_cap_is_refused_without_scanning():
    text = PLAN_TEXT + " " * (qp.PLAN_TEXT_MAX - len(PLAN_TEXT) + 1)
    assert as_pi(qp.parse_plan(text)) == {"status": "fallback", "reason": "no-json-object"}
    assert qp.parse_plan(text[:qp.PLAN_TEXT_MAX]).status == "ok"


class CountingDecoder:
    """Wraps the planner's decoder and counts `raw_decode` calls."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def raw_decode(self, text, start):
        self.calls += 1
        return self.inner.raw_decode(text, start)


def test_pl3_deep_nesting_at_the_cap_decodes_at_most_the_depth_limit(monkeypatch):
    depth = (qp.PLAN_TEXT_MAX - 1) // 6
    text = '{"a":' * depth + "1" + "}" * depth
    assert len(text) <= qp.PLAN_TEXT_MAX
    counter = CountingDecoder(qp._DECODER)  # pylint: disable=protected-access
    monkeypatch.setattr(qp, "_DECODER", counter)

    result = qp.parse_plan(text)

    assert counter.calls <= qp.PLAN_DEPTH_MAX
    assert as_pi(result) == {"status": "fallback", "reason": "no-json-object"}


def test_pl3_a_plan_nested_at_the_depth_limit_still_parses():
    plan = '{"concepts":[{"name":"n","queries":["alpha","beta"]}]}'
    wrap = qp.PLAN_DEPTH_MAX - 1
    assert qp.parse_plan('{"a":' * wrap + plan + "}" * wrap).status == "ok"
    assert qp.parse_plan('{"a":' * (wrap + 1) + plan + "}" * (wrap + 1)).status == "fallback"


# ------------------------------------------------------------------ PL4 request shape


def test_pl4_request_body_is_model_and_two_messages():
    post = Post(chat(PLAN_TEXT))
    call(post, query="  keep  the query verbatim ")
    assert len(post.calls) == 1
    sent = post.calls[0]
    assert sent["url"] == BASE + "/api/v1/chat/completions"
    assert sent["key"] == KEY
    assert set(sent["body"]) == {"model", "messages"}
    assert sent["body"]["model"] == "vendor/m"
    assert [m["role"] for m in sent["body"]["messages"]] == ["system", "user"]
    assert sent["body"]["messages"][1] == {
        "role": "user", "content": qp.build_user_prompt("  keep  the query verbatim ")}
    assert all(set(m) == {"role", "content"} for m in sent["body"]["messages"])


# ------------------------------------------------------------------ PL5 model table


def load_resolver(tmp_path: Path):
    source = ROOT / "features" / "common" / "skills" / "task" / "scripts" / "model_groups.py"
    target = tmp_path / "resolver" / "model_groups.py"
    target.parent.mkdir()
    shutil.copy(source, target)
    spec = importlib.util.spec_from_file_location("ai_badger_test_pl5_model_groups", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry(tmp_path: Path, medium_id=None) -> Path:
    doc = json.loads((ROOT / "features" / "common" / "data" / "model-groups.json")
                     .read_text(encoding="utf-8"))
    if medium_id is not None:
        doc["groups"]["medium"][0]["id"] = medium_id
    path = tmp_path / f"registry-{medium_id is not None}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_pl5_model_table(tmp_path):
    resolver = load_resolver(tmp_path)
    good = registry(tmp_path)
    medium = json.loads(good.read_text(encoding="utf-8"))["groups"]["medium"][0]["id"]
    assert medium.startswith("openrouter/")
    table = [
        ("vendor/m", None, None, "vendor/m"),
        ("openrouter/vendor/m", None, None, "vendor/m"),
        ("no-slash", resolver, good, None),
        (None, resolver, good, medium[len("openrouter/"):]),
        ("   ", resolver, good, medium[len("openrouter/"):]),
        (None, resolver, registry(tmp_path, "openrouter/bad id/x"), None),
        (None, None, good, None),
        (None, resolver, tmp_path / "missing.json", None),
    ]
    for override, module, path, expected in table:
        assert qp.planner_model(override, module, path) == expected, (override, path)


def test_pl5_no_model_posts_nothing():
    post = Post(chat(PLAN_TEXT))
    result = call(post, model=None)
    assert as_pi(result) == {"status": "fallback", "reason": "no-model"}
    assert post.calls == []


def test_pl5_refused_base_posts_nothing():
    post = Post(chat(PLAN_TEXT))
    assert as_pi(call(post, base=None)) == {"status": "fallback", "reason": "transport"}
    assert post.calls == []


# ------------------------------------------------------------------ PL6 reply table


PARTS = [{"type": "text", "text": '{"concepts":[{"name":"n",'},
         {"type": "reasoning", "text": "ignore me"},
         {"type": "text", "text": '"queries":["alpha query","beta query"]}]}'}]


@pytest.mark.parametrize("reply,expected", [
    (chat(PLAN_TEXT), {"status": "ok", "plan": PLAN}),
    (chat(PARTS), {"status": "ok", "plan": PLAN}),
    (Reply(200, {}, json.dumps({"choices": [{"message": {"content": None,
                                                          "reasoning": PLAN_TEXT}}]}).encode()),
     {"status": "fallback", "reason": "empty-text"}),
    (Reply(200, {}, b"{}"), {"status": "fallback", "reason": "empty-text"}),
    (chat(5), {"status": "fallback", "reason": "empty-text"}),
    (Reply(200, {}, b"not json"), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 500), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 401), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 301), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 302), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 303), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 307), {"status": "fallback", "reason": "transport"}),
    (chat(PLAN_TEXT, 308), {"status": "fallback", "reason": "transport"}),
    (TIMEOUT, {"status": "fallback", "reason": "timeout"}),
    (TRANSPORT, {"status": "fallback", "reason": "transport"}),
], ids=["string", "parts", "reasoning-only", "no-choices", "non-string", "non-json",
        "500", "401", "301", "302", "303", "307", "308", "timeout", "transport"])
def test_pl6_reply_table(reply, expected):
    assert as_pi(call(Post(reply))) == expected


# ------------------------------------------------------------------ PL7 vocabulary


def test_pl7_reason_vocabularies_equal_pi():
    assert qp.PLANNER_REASONS == tuple(GOLDENS["planner"]["fallback_reasons"]["value"])
    assert qp.RUN_REASONS == ("ok", "no-candidates", "search-error", "budget-exhausted")
    assert set(GOLDENS["runner"]["reasons_observed"]) <= set(qp.PLANNER_REASONS + qp.RUN_REASONS)


@pytest.mark.parametrize("post,model,base", [
    (Post(RuntimeError("boom")), "vendor/m", BASE),
    (Post(object()), "vendor/m", BASE),
    (Post(Reply("200", {}, b"{}")), "vendor/m", BASE),
    (Post(Reply(200, {}, "not bytes")), "vendor/m", BASE),
    (Post(chat({"weird": 1})), "vendor/m", BASE),
    (Post(chat(PLAN_TEXT)), None, BASE),
    (Post(chat(PLAN_TEXT)), "vendor/m", None),
    (Post(TIMEOUT), "vendor/m", BASE),
], ids=["raises", "object", "string-status", "str-body", "dict-content", "no-model", "no-base",
        "timeout"])
def test_pl7_plan_never_raises_and_reasons_stay_in_vocabulary(post, model, base):
    result = call(post, model=model, base=base)
    assert result.status == "fallback"
    assert result.reason in qp.PLANNER_REASONS


def test_pl7_expired_budget_is_timeout_without_a_post():
    clock = Clock()
    budget = mc.Budget(1, clock=clock)
    clock.now = 5.0
    post = Post(chat(PLAN_TEXT))
    result = qp.plan("q", post=post, base=BASE, key=KEY, model="vendor/m", budget=budget)
    assert as_pi(result) == {"status": "fallback", "reason": "timeout"}
    assert post.calls == []
