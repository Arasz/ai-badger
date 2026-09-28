"""S4 gates, caps, flags and prompt literals for `jev_choice.py`.

Covered here: the two wire payloads pinned to hand-copied fixture literals (provenance in the
fixture block below), the fail-safe gates in both directions, `PAIR_CAP`/`STATE_CHAR_CAP`
chunking and deterministic truncation, retry economy, and the zero-network proof for flags-off
(a poisoned transport that raises `BaseException`, plus a loopback capture server that must see
no connection, with a positive control proving the capture would have seen one).
"""
# pylint: disable=redefined-outer-name  # the `mod` fixture is named by pytest convention
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Optional

import pytest

from memory_context_openrouter import FakeOpenRouter, reply

MASTER = "AI_BADGER_JEV"
TIER = "AI_BADGER_JEV_TIER"
WAVES = "AI_BADGER_JEV_WAVES"
MODEL = "AI_BADGER_JEV_MODEL"
ENDPOINT = "AI_BADGER_JEV_ENDPOINT"
TIMEOUT = "AI_BADGER_JEV_TIMEOUT_MS"
TEST_BASE = "AI_BADGER_JEV_TEST_OPENROUTER_BASE"
DECISIONS_PATH = "/api/alpha/decisions"


@pytest.fixture
def mod(load_script):
    return load_script("features/common/skills/task-decomposition/scripts/jev_choice.py")


# ------------------------------------------------------------------ prompt fixture literals
#
# Provenance: copied by hand from docs/work/research-lanes/r4-jev-decisions.md §3 (the tier
# prompt) and §4 (the wave-pair prompt), read 2026-09-28. These literals are the oracle; the
# module must never read the research record at runtime (plan R2-F19).
TIER_INSTRUCTION = ("Which model tier is sufficient to implement this step as specified? "
                    "Judge the derivation the step demands, not its size.")
TIER_CRITERIA = {
    "low": "Mechanical, single-file or rename-level change",
    "medium": "Multi-file change needing judgement",
    "high": "Design, debugging, architecture",
}
WAVE_INSTRUCTION = ("Both steps are ready (their dependencies are done). May they run as "
                    "concurrent lanes in this wave, each in its own worktree?")
WAVE_CRITERIA = {
    "share-wave": ("No shared writable external resource: no shared port, service, database, "
                   "lockfile, generated artifact outside the tree, or ordered output contract "
                   "between the two — concurrency cannot invalidate either lane's green run"),
    "serialize": ("Any shared writable external resource, ordered output contract, or race "
                  "between the two — run them in separate waves, dependencies first"),
}

STEP = {
    "id": "S4",
    "goal": "Wrap the fail-closed choice parser and the two decision prompts",
    "instructions": "Port clampProbability/parseAnswer/parseResponseBody from the TS router; "
                    "pin the wire payloads against the R4 fixtures.",
    "acceptance_criteria": ["parser matrix green with two RED witnesses"],
    "effort": "medium",
    "files": ["features/common/skills/task-decomposition/scripts/jev_choice.py"],
    "verifier": "pytest tests/test_jev_choice_parser.py -q",
}
TIER_WIRE = {
    "model": "typesafe/jev-1.13",
    "state": {"step": {
        "id": "S4",
        "goal": "Wrap the fail-closed choice parser and the two decision prompts",
        "instructions": "Port clampProbability/parseAnswer/parseResponseBody from the TS router; "
                        "pin the wire payloads against the R4 fixtures.",
        "acceptance_criteria": ["parser matrix green with two RED witnesses"],
        "declared_effort": "medium",
        "files": ["features/common/skills/task-decomposition/scripts/jev_choice.py"],
        "verifier": "pytest tests/test_jev_choice_parser.py -q",
    }},
    "questions": {"S4_tier": {"type": "choice", "instructions": TIER_INSTRUCTION,
                              "criteria": TIER_CRITERIA}},
}

READY = [
    {"id": "S4", "goal": "Parse decisions", "instructions": "Port the parser.",
     "files": ["a.py"], "resources": ["port 8000"]},
    {"id": "S7", "goal": "Serve tools", "instructions": "Add the stdio server.",
     "files": ["b.py"], "resources": []},
]
DONE = ["S1", "S2"]
EDGES = [["S1", "S4"], ["S1", "S7"], ["S2", "S7"]]
WAVE_WIRE = {
    "model": "typesafe/jev-1.13",
    "state": {
        "steps": [
            {"id": "S4", "goal": "Parse decisions", "instructions": "Port the parser.",
             "files": ["a.py"], "runs": ["port 8000"]},
            {"id": "S7", "goal": "Serve tools", "instructions": "Add the stdio server.",
             "files": ["b.py"], "runs": []},
        ],
        "done": ["S1", "S2"],
        "edges": [["S1", "S4"], ["S1", "S7"], ["S2", "S7"]],
    },
    "questions": {"S4_S7": {"type": "choice", "instructions": WAVE_INSTRUCTION,
                            "criteria": WAVE_CRITERIA}},
}


# ------------------------------------------------------------------ stubs and helpers


class Reply(NamedTuple):
    """The vendored client's `Reply`: failures arrive as status 0 with `error` set."""

    status: int
    headers: dict
    body: bytes
    error: Optional[str] = None


TRANSPORT = Reply(0, {}, b"", "transport")


class Poisoned(BaseException):
    """Raised by the poisoned transport; not an `Exception`, so the module cannot swallow it."""


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Post:
    """Scripted transport: a reply list (the last repeats) or a `respond(body)` function."""

    def __init__(self, *replies, respond=None):
        self.replies = list(replies)
        self.respond = respond
        self.calls = []

    def __call__(self, url, body, key, budget):
        self.calls.append({"url": url, "body": body, "key": key, "remaining": budget.remaining()})
        if self.respond is not None:
            return self.respond(body)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def poison(*_args, **_kwargs):
    raise Poisoned("transport reached while Jev was off")


def env_on(overrides=None):
    env = {MASTER: "1", "OPENROUTER_API_KEY": "sk-or-v1-fixture-key"}
    env.update(overrides or {})
    return env


def make_answer(mod, choice="high", confidence=0.8):
    return mod.ChoiceAnswer("choice", choice, {choice: confidence}, confidence)


def choice_responder(choice, confidence=1.0):
    def respond(body):
        answers = {name: {"type": "choice", "choice": choice,
                          "probabilities": {choice: confidence}, "confidence": confidence}
                   for name in body["questions"]}
        return Reply(200, {}, json.dumps({"answers": answers}).encode())
    return respond


def pair_names(ids):
    """The module's own naming contract, restated independently for the oracle."""
    return [f"{a}_{b}" for index, a in enumerate(ids) for b in ids[index + 1:]]


def compact(state):
    return len(json.dumps(state, ensure_ascii=False, separators=(",", ":")))


def wire_steps(count, instructions="i", goal="g"):
    return [{"id": f"S{i}", "goal": f"{goal}-{i}", "instructions": instructions,
             "files": [f"f{i}.py"], "resources": [f"port {i}"]} for i in range(count)]


# ------------------------------------------------------------------ prompt literals


def test_tier_and_wave_constants_match_the_r4_fixtures(mod):
    assert mod.TIER_INSTRUCTIONS == TIER_INSTRUCTION
    assert mod.TIER_CRITERIA == TIER_CRITERIA
    assert mod.WAVE_INSTRUCTIONS == WAVE_INSTRUCTION
    assert mod.WAVE_CRITERIA == WAVE_CRITERIA


def test_tier_payload_is_the_r4_wire_literal(mod):
    name, body = mod.build_tier_request(STEP)
    assert name == "S4_tier"
    assert body == TIER_WIRE
    assert body["questions"]["S4_tier"]["criteria"] == TIER_CRITERIA


def test_wave_payload_is_the_r4_wire_literal(mod):
    names, body = mod.build_wave_request(READY, done=DONE, edges=EDGES)
    assert names == ["S4_S7"]
    assert body == WAVE_WIRE


def test_effort_and_declared_effort_map_to_the_wire_field(mod):
    declared = {**STEP}
    declared.pop("effort")
    declared["declared_effort"] = "high"
    _, body = mod.build_tier_request(declared)
    assert body["state"]["step"]["declared_effort"] == "high"
    _, body = mod.build_tier_request({**declared, "effort": "low"})
    assert body["state"]["step"]["declared_effort"] == "low"


def test_acceptance_criteria_mappings_reduce_to_statements(mod):
    step = {**STEP, "acceptance_criteria": [{"id": "A1", "statement": "first"},
                                            "second", {"id": "A2"}]}
    _, body = mod.build_tier_request(step)
    assert body["state"]["step"]["acceptance_criteria"] == ["first", "second"]


def test_resources_map_to_runs_on_the_wire(mod):
    _, body = mod.build_wave_request(READY)
    assert [step["runs"] for step in body["state"]["steps"]] == [["port 8000"], []]


def test_model_override_reaches_both_payloads(mod):
    _, tier = mod.build_tier_request(STEP, model_id="other/jev-2")
    _, wave = mod.build_wave_request(READY, model_id="other/jev-2")
    assert tier["model"] == "other/jev-2"
    assert wave["model"] == "other/jev-2"


# ------------------------------------------------------------------ flags and env surface


@pytest.mark.parametrize("env,tier,waves", [
    ({}, False, False),
    ({MASTER: "0"}, False, False),
    ({MASTER: "1"}, False, False),
    ({MASTER: "1", TIER: "1"}, True, False),
    ({MASTER: "1", WAVES: "1"}, False, True),
    ({MASTER: "1", TIER: "1", WAVES: "1"}, True, True),
    ({MASTER: "true", TIER: "1", WAVES: "1"}, False, False),
    ({MASTER: "1", TIER: "yes"}, False, False),
    ({MASTER: " 1", TIER: "1"}, False, False),
    ({TIER: "1", WAVES: "1"}, False, False),
    ({MASTER: "1", TIER: "0", WAVES: "0"}, False, False),
])
def test_flag_matrix_is_literal_and_master_gated(mod, env, tier, waves):
    assert mod.tier_enabled(env) is tier
    assert mod.waves_enabled(env) is waves


def test_wire_defaults_and_overrides(mod):
    assert mod.MODEL_DEFAULT == "typesafe/jev-1.13"
    assert mod.ENDPOINT_DEFAULT == "https://openrouter.ai/api/alpha/decisions"
    assert mod.model({}) == mod.MODEL_DEFAULT
    assert mod.model({MODEL: "other/jev-2"}) == "other/jev-2"
    assert mod.endpoint({}) == mod.ENDPOINT_DEFAULT
    assert (mod.endpoint({ENDPOINT: "http://example.test/decisions"})
            == "http://example.test/decisions")


@pytest.mark.parametrize("raw,expected", [
    (None, 8.0), ("8000", 8.0), ("15000", 15.0), ("2500.7", 2.5), ("8e3", 8.0),
    ("0", 8.0), ("-1", 8.0), ("abc", 8.0), ("", 8.0),
])
def test_timeout_seconds_clamps_to_the_attempt_second_default(mod, raw, expected):
    env = {} if raw is None else {TIMEOUT: raw}
    assert mod.timeout_seconds(env) == expected


def test_endpoint_url_resolution_and_the_loopback_rule(mod):
    key = "sk-test-jev-fixture"
    loop = "http://127.0.0.1:4321"
    assert mod.endpoint_url({TEST_BASE: loop, "OPENROUTER_API_KEY": key}) == loop + DECISIONS_PATH
    assert mod.endpoint_url({"OPENROUTER_API_KEY": key}) == mod.ENDPOINT_DEFAULT
    # A live test base wins over a configured endpoint (never the other way around).
    assert mod.endpoint_url({TEST_BASE: loop, "OPENROUTER_API_KEY": key,
                             ENDPOINT: "http://elsewhere.test/x"}) == loop + DECISIONS_PATH
    # Non-loopback test base or non-test key resolves to None, never to production.
    assert mod.endpoint_url({TEST_BASE: "https://openrouter.ai",
                             "OPENROUTER_API_KEY": key}) is None
    assert mod.endpoint_url({TEST_BASE: loop, "OPENROUTER_API_KEY": "sk-or-v1-real"}) is None
    assert mod.endpoint_url({TEST_BASE: loop}) is None
    assert mod.endpoint_url({}) is None


# ------------------------------------------------------------------ fail-safe directions


def test_tier_high_at_the_gate_proposes_an_upgrade(mod):
    assert mod.propose_tier(STEP, make_answer(mod, "high", 0.6)) == mod.TierProposal("high", 0.6)


@pytest.mark.parametrize("choice,confidence", [
    ("medium", 1.0), ("low", 1.0), ("high", 0.59), ("high", float("nan")),
])
def test_tier_never_demotes_and_never_proposes_below_the_gate(mod, choice, confidence):
    assert mod.propose_tier(STEP, make_answer(mod, choice, confidence)) is None


@pytest.mark.parametrize("declared", [{"level": "low"}, {"model": "typesafe/jev-1.13"}])
def test_tier_never_overrides_a_declared_level_or_model(mod, declared):
    assert mod.propose_tier({**STEP, **declared}, make_answer(mod, "high", 1.0)) is None


def test_tier_failure_proposes_nothing(mod):
    assert mod.propose_tier(STEP, None) is None
    assert mod.propose_tier(None, make_answer(mod, "high", 1.0)) is None


def test_wave_share_wave_at_the_gate_admits_concurrency(mod):
    assert mod.pair_decision(make_answer(mod, "share-wave", 0.7)) == "share-wave"


@pytest.mark.parametrize("choice,confidence", [
    ("serialize", 1.0), ("share-wave", 0.69), ("share-wave", float("nan")), ("medium", 1.0),
])
def test_wave_anything_else_serializes(mod, choice, confidence):
    assert mod.pair_decision(make_answer(mod, choice, confidence)) == "serialize"


def test_wave_failure_serializes(mod):
    assert mod.pair_decision(None) == "serialize"


def test_tier_transport_failure_proposes_nothing_end_to_end(mod):
    post = Post(TRANSPORT)
    assert mod.tier_proposals([STEP], env=env_on({TIER: "1"}), post=post) == {}
    assert len(post.calls) == 2  # ATTEMPTS


def test_wave_transport_failure_serializes_every_pair_end_to_end(mod):
    post = Post(TRANSPORT)
    hints = mod.wave_hints(READY, env=env_on({WAVES: "1"}), post=post)
    assert hints == {"S4_S7": "serialize"}
    assert len(post.calls) == 2


def test_tier_proposals_parse_per_step_and_skip_declared_tiers(mod):
    def respond(body):
        answers = {name: {"type": "choice",
                          "choice": "high" if name == "S4_tier" else "medium",
                          "probabilities": {"high": 0.9, "medium": 0.1}, "confidence": 0.9}
                   for name in body["questions"]}
        return Reply(200, {}, json.dumps({"answers": answers}).encode())

    post = Post(respond=respond)
    steps = [STEP, {**STEP, "id": "S5"}, {**STEP, "id": "S6", "level": "low"}]
    proposals = mod.tier_proposals(steps, env=env_on({TIER: "1"}), post=post)
    assert proposals == {"S4_tier": mod.TierProposal("high", 0.9)}
    assert len(post.calls) == 2  # S6 declares a level: no call, no proposal


# ------------------------------------------------------------------ caps and chunking


def test_caps_are_the_pinned_values(mod):
    assert mod.PAIR_CAP == 10
    assert mod.STATE_CHAR_CAP == 32000
    assert mod.INSTRUCTION_CHAR_CAP == 1000
    assert mod.ATTEMPTS == 2
    assert mod.ATTEMPT_SECONDS == 8.0


def test_ten_members_make_45_questions_and_above_the_cap_the_call_chunks(mod):
    steps = wire_steps(23)
    post = Post(respond=choice_responder("share-wave"))
    hints = mod.wave_hints(steps, env=env_on({WAVES: "1"}), post=post)
    # Calls carry at most PAIR_CAP members and C(10,2)=45 questions: blocks [10, 10, 3].
    assert [len(call["body"]["state"]["steps"]) for call in post.calls] == [10, 10, 3]
    assert [len(call["body"]["questions"]) for call in post.calls] == [45, 45, 3]
    ids = [step["id"] for step in steps]
    blocks = [ids[0:10], ids[10:20], ids[20:]]
    asked = [name for call in post.calls for name in call["body"]["questions"]]
    assert sorted(asked) == sorted(name for block in blocks for name in pair_names(block))
    assert len(asked) == len(set(asked))
    # Pairs spanning chunks are never asked, so they stay at the safe default; asked pairs win.
    assert sorted(hints) == sorted(pair_names(ids))
    for name in pair_names(ids):
        assert hints[name] == ("share-wave" if name in set(asked) else "serialize")


def test_state_cap_truncates_instructions_before_anything_is_dropped(mod):
    _, body = mod.build_wave_request(wire_steps(10, instructions="x" * 5000))
    state = body["state"]
    assert len(state["steps"]) == 10
    assert all(len(step["instructions"]) == mod.INSTRUCTION_CHAR_CAP for step in state["steps"])
    assert compact(state) <= mod.STATE_CHAR_CAP
    assert [step["id"] for step in state["steps"]] == [f"S{i}" for i in range(10)]


def test_state_cap_falls_back_to_goals_only_and_never_drops_steps(mod):
    _, body = mod.build_wave_request(wire_steps(10, instructions="i" * 3000, goal="g" * 3000))
    state = body["state"]
    assert len(state["steps"]) == 10
    assert all(set(step) == {"id", "goal"} for step in state["steps"])
    assert [step["id"] for step in state["steps"]] == [f"S{i}" for i in range(10)]
    assert compact(state) <= mod.STATE_CHAR_CAP


def test_tier_state_truncates_a_giant_instruction(mod):
    _, body = mod.build_tier_request({**STEP, "instructions": "x" * 50000})
    assert len(body["state"]["step"]["instructions"]) == mod.INSTRUCTION_CHAR_CAP


def test_state_fitting_is_deterministic(mod):
    steps = wire_steps(10, instructions="i" * 3000, goal="g" * 3000)
    _, first = mod.build_wave_request(steps)
    _, second = mod.build_wave_request(steps)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ------------------------------------------------------------------ retries and economy


@pytest.mark.parametrize("status,kind", [
    (400, "misrouted-refusal"), (401, "auth"), (402, "billing"), (429, "rate-limited"),
    (301, "server"), (500, "server"),
])
def test_classify_maps_statuses_to_kinds(mod, status, kind):
    assert mod.classify(Reply(status, {}, b"{}"), {}) == mod.Verdict(kind, {})


def test_classify_transport_and_body_kinds(mod):
    assert mod.classify(TRANSPORT, {}).kind == "transport-timeout"
    assert mod.classify(Reply(200, {}, b"not json"), {}).kind == "malformed"
    envelope = b'{"error": {"message": "x"}}'
    assert mod.classify(Reply(200, {}, envelope), {}).kind == "server"


def one_question():
    return {"questions": {"q": {"type": "choice", "criteria": {"a": "A", "b": "B"}}}}


def test_retryable_failures_attempt_twice_then_stop(mod):
    post = Post(Reply(500, {}, b"{}"), Reply(500, {}, b"{}"))
    assert mod.request_choices(one_question(), ["q"], env=env_on(), post=post) == {"q": None}
    assert len(post.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 402])
def test_non_retryable_failures_attempt_once(mod, status):
    post = Post(Reply(status, {}, b"{}"))
    mod.request_choices(one_question(), ["q"], env=env_on(), post=post)
    assert len(post.calls) == 1


def test_malformed_body_is_retryable(mod):
    post = Post(Reply(200, {}, b"not json"))
    mod.request_choices(one_question(), ["q"], env=env_on(), post=post)
    assert len(post.calls) == 2


def test_rate_limit_ignores_retry_after(mod):
    post = Post(Reply(429, {"retry-after": "3600"}, b"{}"))
    mod.request_choices(one_question(), ["q"], env=env_on(), post=post)
    assert len(post.calls) == 2


def test_each_attempt_budget_is_capped_at_attempt_seconds(mod):
    post = Post(Reply(500, {}, b"{}"))
    budget = mod.Budget(100, clock=Clock())
    mod.request_choices(one_question(), ["q"], env=env_on(), post=post, budget=budget)
    assert post.calls
    assert all(call["remaining"] <= mod.ATTEMPT_SECONDS for call in post.calls)


def test_no_sleep_between_attempts(mod, monkeypatch):
    def boom(seconds):
        pytest.fail(f"retry slept for {seconds}s")

    monkeypatch.setattr(mod.time, "sleep", boom)
    post = Post(Reply(500, {}, b"{}"))
    assert mod.request_choices(one_question(), ["q"], env=env_on(), post=post) == {"q": None}
    assert len(post.calls) == 2


# ------------------------------------------------------------------ zero network when off


def test_flags_off_never_touches_the_transport(mod):
    for env in ({}, {MASTER: "0"}, {MASTER: "true"},
                {TIER: "1", WAVES: "1"}, {MASTER: "1"}):
        assert mod.tier_proposals([STEP], env=env, post=poison) == {}
        assert mod.wave_hints(READY, env=env, post=poison) == {}


def test_flags_off_opens_no_connection_even_with_a_loopback_test_endpoint(mod):
    server = FakeOpenRouter()
    try:
        env = {MASTER: "0", TIER: "1", WAVES: "1", TEST_BASE: server.url,
               "OPENROUTER_API_KEY": "sk-test-jev-off"}
        assert mod.tier_proposals([STEP], env=env) == {}
        assert mod.wave_hints(READY, env=env) == {}
        assert server.requests == []
        assert server.connections == 0
    finally:
        server.stop()


def test_loopback_stub_is_a_real_seam_when_enabled(mod):
    server = FakeOpenRouter()
    tier_answer = {"answers": {"S4_tier": {
        "type": "choice", "choice": "high",
        "probabilities": {"low": 0.0, "medium": 0.1, "high": 0.9}, "confidence": 0.9}}}
    server.script(DECISIONS_PATH, reply(body=json.dumps(tier_answer).encode()))
    try:
        env = {MASTER: "1", TIER: "1", TEST_BASE: server.url,
               "OPENROUTER_API_KEY": "sk-test-jev-live"}
        proposals = mod.tier_proposals([STEP], env=env)
        assert proposals == {"S4_tier": mod.TierProposal("high", 0.9)}
        assert len(server.requests) == 1
        request = server.requests[0]
        assert request["method"] == "POST"
        assert request["path"] == DECISIONS_PATH
        assert request["headers"]["authorization"] == "Bearer sk-test-jev-live"
        assert request["body"] == TIER_WIRE
    finally:
        server.stop()


def test_non_loopback_test_base_never_falls_back_to_production(mod):
    env = env_on({TIER: "1", WAVES: "1", TEST_BASE: "https://openrouter.ai"})
    assert mod.endpoint_url(env) is None
    assert mod.tier_proposals([STEP], env=env, post=poison) == {}
    assert mod.wave_hints(READY, env=env, post=poison) == {"S4_S7": "serialize"}


def test_enabled_but_missing_key_proposes_nothing_and_serializes(mod):
    env = {MASTER: "1", TIER: "1", WAVES: "1"}
    assert mod.tier_proposals([STEP], env=env, post=poison) == {}
    assert mod.wave_hints(READY, env=env, post=poison) == {"S4_S7": "serialize"}


# ------------------------------------------------------------------ one budget per advisory run


def test_wave_hints_share_one_budget_across_chunks(mod):
    """A 23-step ready set is three chunk calls; one shared deadline caps transport calls.

    Without the shared budget each chunk gets a fresh `timeout * ATTEMPTS` window, so a slow
    run can spend that window per chunk (6 calls here). With it, the whole advisory is bounded
    by one window and later chunks fail closed without touching the transport.
    """
    steps = wire_steps(23)
    clock = Clock()
    calls = []

    def post(url, body, key, budget):
        calls.append(budget.remaining())
        clock.now += mod.ATTEMPT_SECONDS
        return TRANSPORT

    hints = mod.wave_hints(steps, env=env_on({WAVES: "1"}), post=post, clock=clock)
    assert len(calls) == mod.ATTEMPTS
    assert set(hints.values()) == {"serialize"}


def test_tier_proposals_share_one_budget_across_steps(mod):
    """Three steps are three calls; the shared deadline stops after the first window."""
    steps = [STEP, {**STEP, "id": "S5"}, {**STEP, "id": "S6"}]
    clock = Clock()
    calls = []

    def post(url, body, key, budget):
        calls.append(budget.remaining())
        clock.now += mod.ATTEMPT_SECONDS
        return TRANSPORT

    proposals = mod.tier_proposals(steps, env=env_on({TIER: "1"}), post=post, clock=clock)
    assert proposals == {}
    assert len(calls) == mod.ATTEMPTS


# ------------------------------------------------------------------ the CLI (B1)

ROOT = Path(__file__).resolve().parents[1]
JEV_CLI = ROOT / "features/common/skills/task-decomposition/scripts/jev_choice.py"

CLI_PLAN = {
    "task_id": "aib-jev-cli-probe",
    "workflow": {"steps": {
        "S1": {"id": "S1", "goal": "parse decisions", "instructions": "port the parser",
               "effort": "medium", "depends_on": [], "acceptance_criteria": [],
               "files": ["a.py"], "resources": [], "status": "pending"},
        "S2": {"id": "S2", "goal": "serve the tools", "instructions": "add the stdio server",
               "effort": "low", "depends_on": [], "acceptance_criteria": [],
               "files": ["b.py"], "resources": [], "status": "pending"},
    }},
    "ready": [{"id": "S1", "files": ["a.py"], "resources": []},
              {"id": "S2", "files": ["b.py"], "resources": []}],
}
CLI_ANSWERS = {
    "S1_tier": {"type": "choice", "choice": "high",
                "probabilities": {"low": 0.0, "medium": 0.1, "high": 0.9}, "confidence": 0.9},
    "S2_tier": {"type": "choice", "choice": "medium",
                "probabilities": {"medium": 1.0}, "confidence": 0.95},
    "S1_S2": {"type": "choice", "choice": "share-wave",
              "probabilities": {"share-wave": 0.95}, "confidence": 0.95},
}


def cli_env(**overrides):
    """The subprocess environment with every Jev knob cleared, then the overrides applied."""
    env = {**os.environ}
    for key in (MASTER, TIER, WAVES, MODEL, ENDPOINT, TIMEOUT, TEST_BASE, "OPENROUTER_API_KEY"):
        env.pop(key, None)
    env.update(overrides)
    return env


def run_cli(argv, env, stdin=""):
    """Run the real CLI with the interpreter under test; text in, text out, no shell."""
    return subprocess.run([sys.executable, str(JEV_CLI), *argv], input=stdin,
                          capture_output=True, text=True, encoding="utf-8", env=env,
                          timeout=60)


def test_cli_flags_off_is_off_and_opens_no_connection():
    server = FakeOpenRouter()
    try:
        env = cli_env(**{MASTER: "0", TIER: "1", WAVES: "1", TEST_BASE: server.url,
                         "OPENROUTER_API_KEY": "sk-test-jev-cli-off"})
        proc = run_cli(["-", "--both", "--json"], env, stdin=json.dumps(CLI_PLAN))
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["status"] == "off"
        assert payload["reason"]
        assert payload["tier_proposals"] == {}
        assert payload["wave_hints"] == {}
        assert server.requests == []
        assert server.connections == 0
    finally:
        server.stop()


def test_cli_flags_on_emits_proposals_from_the_loopback_stub():
    server = FakeOpenRouter()
    body = json.dumps({"answers": CLI_ANSWERS}).encode()
    for _ in range(3):  # tier S1, tier S2, wave S1_S2
        server.script(DECISIONS_PATH, reply(body=body))
    try:
        env = cli_env(**{MASTER: "1", TIER: "1", WAVES: "1", TEST_BASE: server.url,
                         "OPENROUTER_API_KEY": "sk-test-jev-cli-live"})
        proc = run_cli(["-", "--both", "--json"], env, stdin=json.dumps(CLI_PLAN))
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["status"] == "ok"
        assert payload["tier_proposals"] == {
            "S1_tier": {"level": "high", "confidence": 0.9}}
        assert payload["wave_hints"] == {"S1_S2": "share-wave"}
        assert len(server.requests) == 3
    finally:
        server.stop()


def test_cli_capability_flags_select_the_phases():
    server = FakeOpenRouter()
    body = json.dumps({"answers": CLI_ANSWERS}).encode()
    for _ in range(6):  # 2 tier-only + 1 waves-only + 3 for the default run
        server.script(DECISIONS_PATH, reply(body=body))
    try:
        env = cli_env(**{MASTER: "1", TIER: "1", WAVES: "1", TEST_BASE: server.url,
                         "OPENROUTER_API_KEY": "sk-test-jev-cli-flags"})
        tier_only = json.loads(run_cli(["-", "--tier", "--json"], env,
                                       stdin=json.dumps(CLI_PLAN)).stdout)
        assert tier_only["tier_proposals"]
        assert tier_only["wave_hints"] == {}
        waves_only = json.loads(run_cli(["-", "--waves", "--json"], env,
                                        stdin=json.dumps(CLI_PLAN)).stdout)
        assert waves_only["tier_proposals"] == {}
        assert waves_only["wave_hints"]
        default = json.loads(run_cli(["-", "--json"], env, stdin=json.dumps(CLI_PLAN)).stdout)
        assert default["tier_proposals"] and default["wave_hints"]
    finally:
        server.stop()


@pytest.mark.parametrize("stdin", ["{not json", '{"task_id": "x"}', ""])
def test_cli_malformed_plan_is_a_clean_error_envelope_never_a_traceback(stdin):
    proc = run_cli(["-", "--both", "--json"], cli_env(), stdin=stdin)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "Traceback" not in proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["status"] == "error"
    assert payload["reason"]
    assert payload["tier_proposals"] == {}
    assert payload["wave_hints"] == {}


def test_cli_unreadable_file_is_a_clean_error_envelope():
    proc = run_cli(["no-such-plan-file.json", "--both", "--json"], cli_env())
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "error"


def test_cli_reads_a_plan_file_not_only_stdin(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(CLI_PLAN), encoding="utf-8")
    proc = run_cli([str(path), "--both", "--json"],
                   cli_env(**{MASTER: "0"}), stdin="")
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "off"
