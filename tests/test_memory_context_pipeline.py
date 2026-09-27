"""Merge and runner of query_pipeline.py against pi's `mergeSelect` and `runPipeline` goldens.

Every runner row drives `run(...)` with fake `plan`/`search`/`score`, the real `prune_hits`, and a
`Budget` on a fake clock that the fakes advance.
"""
from __future__ import annotations

import json
import math

import pytest

from memory_context_support import FIXTURES, load_module, memory_context_env  # noqa: F401

mc = load_module()
qp = mc._load_sibling("query_pipeline")  # pylint: disable=protected-access

GOLDENS = json.loads((FIXTURES / "pipeline_goldens.json").read_text(encoding="utf-8"))
INPUTS = json.loads((FIXTURES / "pipeline_golden_inputs.json").read_text(encoding="utf-8"))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Fakes:
    """Fake `plan`/`search`/`score` that record what they were given and advance the clock."""

    def __init__(self, clock, plan, table, scores=None, *, plan_cost=0.0, search_cost=0.0,
                 score_cost=0.0):
        self.clock = clock
        self.plan_result = plan
        self.table = table
        self.scores = scores
        self.costs = (plan_cost, search_cost, score_cost)
        self.plans, self.searches, self.scored = [], [], []

    def plan(self, query, *, budget):
        self.plans.append((query, budget.remaining()))
        self.clock.now += self.costs[0]
        if isinstance(self.plan_result, BaseException):
            raise self.plan_result
        return self.plan_result

    def search(self, query, budget):
        self.searches.append((query, budget.remaining()))
        self.clock.now += self.costs[1]
        found = self.table.get(query)
        if isinstance(found, BaseException):
            raise found
        return found

    def score(self, query, pool, *, budget):
        self.scored.append((query, [dict(h) for h in pool], budget.remaining()))
        self.clock.now += self.costs[2]
        if isinstance(self.scores, BaseException):
            raise self.scores
        if callable(self.scores):
            return self.scores(pool)
        return self.scores

    def run(self, query="raw", seconds=90.0, limits=None):
        budget = mc.Budget(seconds, clock=self.clock)
        return qp.run(query, plan=self.plan, search=self.search, score=self.score,
                      prune=mc.prune_hits, budget=budget, limits=limits)


def ok_plan(*queries, name="c1"):
    return qp.PlanResult("ok", "ok", {"concepts": [{"name": name, "queries": list(queries)}]})


def mem_hit(hash_, rank, **kw):
    hit = {"hash": hash_, "path": f"docs/{hash_}.md", "snippet": f"snippet {hash_}",
           "ranking": rank}
    hit.update(kw)
    return hit


def hashes(hits):
    return [h["hash"] for h in hits]


# ------------------------------------------------------------------ MG1, MG2 merge


@pytest.mark.parametrize("case", INPUTS["merge"]["merge_select_cases"], ids=lambda c: c["id"])
def test_mg1_merge_select_equals_pi(case):
    golden = {g["id"]: g for g in GOLDENS["merge"]["merge_select"]}[case["id"]]
    mem, code = qp.merge_select(case["candidates"], case["slots"])
    assert (hashes(mem), hashes(code)) == (golden["mem"], golden["code"])


@pytest.mark.parametrize("case", INPUTS["merge"]["doc_key_cases"], ids=lambda c: c["id"])
def test_mg1_doc_key_equals_pi(case):
    golden = {g["id"]: g["output"] for g in GOLDENS["merge"]["doc_key"]}[case["id"]]
    assert qp.doc_key(case["hit"]) == golden


@pytest.mark.parametrize("case", INPUTS["merge"]["server_rank_cases"], ids=lambda c: c["id"])
def test_mg2_server_rank_order_equals_pi(case):
    golden = {g["id"]: g["order"] for g in GOLDENS["merge"]["server_rank_order"]}[case["id"]]
    mem, _ = qp.merge_select(case["candidates"], 5)
    assert hashes(mem) == golden


@pytest.mark.parametrize("raw,rank", [
    (3, 3), (2.5, 2.5), ("2.5", 2.5), (" 7 ", 7), ("1e3", 1000), ("-4", -4), (".5", 0.5),
    ("x", math.inf), (None, math.inf), (math.nan, math.inf), (math.inf, math.inf),
    (-math.inf, math.inf), ("", math.inf), ("Infinity", math.inf), (True, math.inf),
    ("0x10", math.inf), ("1_000", math.inf), ([1], math.inf),
])
def test_mg2_server_rank_table(raw, rank):
    assert qp.server_rank({"hash": "h", "ranking": raw}) == rank


def test_mg2_missing_ranking_is_last():
    assert qp.server_rank({"hash": "h"}) == math.inf


# ------------------------------------------------------------------ R1, R2 plan and queries


def test_r1_plans_once_then_searches_each_planned_query_in_order():
    clock = Clock()
    table = {"q2": ([mem_hit("b", 2)], []), "q1": ([mem_hit("a", 1)], []), "q3": None}
    fakes = Fakes(clock, qp.PlanResult("ok", "ok", {"concepts": [
        {"name": "c1", "queries": ["q2", "q1"]}, {"name": "c2", "queries": ["q3"]}]}),
        table, lambda pool: [None] * len(pool))
    result = fakes.run(query="  the raw prompt ")
    assert [q for q, _ in fakes.plans] == ["  the raw prompt "]
    assert [q for q, _ in fakes.searches] == ["q2", "q1", "q3"]
    assert len(fakes.scored) == 1 and fakes.scored[0][0] == "  the raw prompt "
    assert result.queries == ["q2", "q1", "q3"]
    assert (result.status, result.reason) == ("pipeline", "ok")


def test_r2_dedupe_queries_trims_and_drops_blanks_duplicates_and_the_input():
    concepts = [{"name": "a", "queries": [" q1 ", "q1", "   ", "raw", "q2", "﻿q2　"]},
                {"name": "b", "queries": ["q2", "q3"]}]
    assert qp.dedupe_queries(concepts, " raw ") == [("q1", "a"), ("q2", "a"), ("q3", "b")]


def test_r2_all_queries_dropped_falls_back_with_invalid_shape():
    clock = Clock()
    fakes = Fakes(clock, ok_plan("  ", "raw"), {"raw": ([mem_hit("r", 1)], [])})
    result = fakes.run(query="raw")
    assert (result.status, result.reason) == ("fallback", "invalid-shape")
    assert [q for q, _ in fakes.searches] == ["raw"]
    assert hashes(result.mem) == ["r"]


# ------------------------------------------------------------------ R3 runner goldens


def scenario_fakes(spec, clock):
    if spec["plan"]["status"] == "throw":
        plan = RuntimeError("planner exploded")
    elif spec["plan"]["status"] == "ok":
        plan = qp.PlanResult("ok", "ok", {"concepts": spec["plan"]["concepts"]})
    else:
        plan = qp.PlanResult("fallback", spec["plan"]["reason"], None)
    table = {}
    for query, entry in spec["search"].items():
        table[query] = RuntimeError("search failed") if entry == "throw" else (entry, [])
    mode = spec["score"]["mode"]
    if mode == "throw":
        scores = RuntimeError("jev down")
    elif mode == "null":
        scores = lambda pool: [None] * len(pool)  # noqa: E731
    else:
        fixed = spec["score"]["scores"]
        scores = lambda pool: [fixed.get(h["hash"]) for h in pool]  # noqa: E731
    return Fakes(clock, plan, table, scores)


@pytest.mark.parametrize("spec", INPUTS["runner"]["scenarios"], ids=lambda s: s["id"])
def test_r3_runner_equals_pi(spec):
    golden = {g["id"]: g for g in GOLDENS["runner"]["scenarios"]}[spec["id"]]
    fakes = scenario_fakes(spec, Clock())
    fakes.table.setdefault(spec["query"], RuntimeError("no fixture hits"))
    result = fakes.run(query=spec["query"])
    got = {"id": spec["id"], "status": result.status, "reason": result.reason,
           "mem": hashes(result.mem), "code": hashes(result.code), "queries": result.queries,
           "candidates": result.candidates, "scored": result.scored}
    assert got == golden


def test_r3_fallback_keeps_the_planner_reason():
    fakes = Fakes(Clock(), qp.PlanResult("fallback", "timeout", None),
                  {"raw": ([mem_hit("r", 1)], [mem_hit("c", 1)])})
    result = fakes.run()
    assert (result.status, result.reason) == ("fallback", "timeout")
    assert hashes(result.mem) == ["r"] and hashes(result.code) == ["c"]
    assert [q for q, _ in fakes.searches] == ["raw"]


# ------------------------------------------------------------------ R5 budget arithmetic


def test_r5_limits_equal_memory_context_constants():
    assert qp.LIMITS == (mc.PIPELINE_TOTAL_SECONDS, mc.PLANNER_SECONDS, mc.SEARCH_SECONDS,
                         mc.SCORE_SECONDS)


def test_r5_planner_share_keeps_the_search_and_score_reserve():
    fakes = Fakes(Clock(), qp.PlanResult("fallback", "no-model", None), {"raw": None})
    fakes.run()
    assert fakes.plans[0][1] == 15.0
    fakes = Fakes(Clock(), qp.PlanResult("fallback", "no-model", None), {"raw": None})
    fakes.run(seconds=30.0, limits=qp.Limits(30.0, 15.0, 15.0, 8.0))
    assert fakes.plans[0][1] == 7.0


def test_r5_search_shares_leave_the_score_reserve_and_stop_at_eight_and_a_half():
    clock = Clock()
    queries = [f"q{i}" for i in range(6)]
    table = {q: ([mem_hit(q, i)], []) for i, q in enumerate(queries)}
    fakes = Fakes(clock, ok_plan(*queries[:4], name="a"), table, lambda pool: [None] * len(pool),
                  search_cost=5.0)
    fakes.plan_result = qp.PlanResult("ok", "ok", {"concepts": [
        {"name": "a", "queries": queries[:4]}, {"name": "b", "queries": queries[4:]}]})
    result = fakes.run(seconds=30.0)
    assert [share for _, share in fakes.searches] == [15.0, 15.0, 12.0, 7.0, 2.0]
    assert fakes.scored[0][2] == 5.0
    assert (result.status, result.reason) == ("pipeline", "ok")


def test_r5_boundary_of_the_search_loop():
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": ([mem_hit("a", 1)], []),
                                                 "raw": ([mem_hit("r", 1)], [])})
    result = fakes.run(seconds=8.5)
    assert [q for q, _ in fakes.searches] == ["raw"]
    assert fakes.searches[0][1] == pytest.approx(0.5)
    assert result.reason == "no-candidates"
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": ([mem_hit("a", 1)], [])},
                  lambda pool: [None] * len(pool))
    fakes.run(seconds=8.6)
    assert fakes.searches[0][0] == "q1"
    assert fakes.searches[0][1] == pytest.approx(0.6)


def test_r5_score_share_is_eight_seconds_capped_by_the_run():
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": ([mem_hit("a", 1)], [])},
                  lambda pool: [None] * len(pool))
    fakes.run()
    assert fakes.scored[0][2] == 8.0


@pytest.mark.parametrize("left,searched,reason", [
    (0.9, [], "no-model"), (5.0, [], "search-error"), (20.0, [("raw", 12.0)], "no-model")])
def test_r5_fallback_share(left, searched, reason):
    fakes = Fakes(Clock(), qp.PlanResult("fallback", "no-model", None),
                  {"raw": ([mem_hit("r", 1)], [])}, plan_cost=90.0 - left)
    result = fakes.run()
    assert fakes.searches == searched
    assert (result.status, result.reason) == ("fallback", reason)
    assert bool(result.mem) is bool(searched)


def test_r5_deadline_passed_during_scoring_is_budget_exhausted():
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": ([mem_hit("a", 1)], [])},
                  lambda pool: [3.0] * len(pool), score_cost=91.0)
    result = fakes.run()
    assert (result.status, result.reason) == ("fallback", "budget-exhausted")
    assert (result.mem, result.code) == ([], [])


# ------------------------------------------------------------------ R6 search failures


def test_r6_a_failed_search_is_skipped_and_the_next_runs():
    table = {"q1": None, "q2": RuntimeError("boom"), "q3": 5, "q4": ([mem_hit("d", 1)], [])}
    fakes = Fakes(Clock(), ok_plan("q1", "q2", "q3", "q4"), table,
                  lambda pool: [None] * len(pool))
    result = fakes.run()
    assert [q for q, _ in fakes.searches] == ["q1", "q2", "q3", "q4"]
    assert (result.status, result.reason, hashes(result.mem)) == ("pipeline", "ok", ["d"])


def test_r6_all_searches_fail_then_one_fallback_then_search_error():
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": None, "q2": None, "raw": None})
    result = fakes.run()
    assert [q for q, _ in fakes.searches] == ["q1", "q2", "raw"]
    assert (result.status, result.reason, result.mem, result.code) == (
        "fallback", "search-error", [], [])


@pytest.mark.parametrize("which", ["plan", "search", "score", "all"])
def test_r6_run_never_raises(which):
    boom = RuntimeError("boom")
    fakes = Fakes(Clock(), boom if which in ("plan", "all") else ok_plan("q1", "q2"),
                  {"q1": boom if which in ("search", "all") else ([mem_hit("a", 1)], []),
                   "q2": boom, "raw": boom if which == "all" else ([mem_hit("r", 1)], [])},
                  boom if which in ("score", "all") else (lambda pool: [None] * len(pool)))
    result = fakes.run()
    assert result.reason in qp.PLANNER_REASONS + qp.RUN_REASONS


# ------------------------------------------------------------------ R7 Jev failure (O-6)


@pytest.mark.parametrize("scores", [
    RuntimeError("jev down"), lambda pool: [None] * len(pool), lambda pool: None,
    lambda pool: [3.0], lambda pool: "timeout"],
    ids=["raises", "all-null", "none", "wrong-length", "junk"])
def test_r7_jev_failure_merges_planned_hits_by_server_rank(scores):
    table = {"q1": ([mem_hit("late", 3)], []), "q2": ([mem_hit("early", 1)], [])}
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), table, scores)
    result = fakes.run()
    assert (result.status, result.reason) == ("pipeline", "ok")
    assert hashes(result.mem) == ["early", "late"]
    assert [q for q, _ in fakes.searches] == ["q1", "q2"]
    assert result.scored == 0


def test_r7_jev_timeout_does_not_fall_back():
    table = {"q1": ([mem_hit("late", 3)], []), "q2": ([mem_hit("early", 1)], [])}
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), table, lambda pool: [None] * len(pool),
                  score_cost=8.0)
    result = fakes.run()
    assert (result.status, result.reason) == ("pipeline", "ok")
    assert [q for q, _ in fakes.searches] == ["q1", "q2"]


# ------------------------------------------------------------------ R8 pool


def test_r8_pool_prunes_per_kind_and_drops_droppables():
    mem = [mem_hit("x", 1), {"hash": "drop", "ranking": 0}, mem_hit("x", 4)]
    code = [mem_hit("x", 2, path="src/x.py")]
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": (mem, code)},
                  lambda pool: [None] * len(pool))
    fakes.run()
    pool = fakes.scored[0][1]
    assert [(h["hash"], h["kind"]) for h in pool] == [("x", "memory"), ("x", "code")]


def test_r8_pool_sorts_by_server_rank_then_caps_at_48():
    hits = [mem_hit(f"h{i}", 60 - i) for i in range(60)]
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": (hits, [])},
                  lambda pool: [None] * len(pool))
    fakes.run()
    pool = fakes.scored[0][1]
    assert len(pool) == qp.POOL_MAX == 48
    assert hashes(pool) == [f"h{i}" for i in range(59, 11, -1)]


def test_r8_pool_ties_keep_insertion_order():
    mem = [mem_hit("m1", "x"), mem_hit("m2", 1)]
    code = [mem_hit("c1", None, path="src/c.py"), mem_hit("c2", 1, path="src/d.py")]
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": (mem, code)},
                  lambda pool: [None] * len(pool))
    fakes.run()
    assert hashes(fakes.scored[0][1]) == ["m2", "c2", "m1", "c1"]


def test_r8_scores_join_by_hash():
    mem = [mem_hit("a", 1), mem_hit("b", 2), mem_hit("c", 3)]
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": (mem, [])},
                  lambda pool: [{"a": 0.0, "b": 1.0, "c": 3.0}[h["hash"]] for h in pool])
    result = fakes.run()
    assert hashes(result.mem) == ["c", "b", "a"]
    assert result.scored == 3


def test_r8_a_hash_shared_across_kinds_takes_the_last_score_like_pi():
    mem = [mem_hit("x", 1), mem_hit("y", 3)]
    code = [mem_hit("x", 2, path="src/x.py")]
    fakes = Fakes(Clock(), ok_plan("q1", "q2"), {"q1": (mem, code)},
                  lambda pool: [3.0, None, 2.0][:len(pool)])
    result = fakes.run()
    assert [h["hash"] for h in fakes.scored[0][1]] == ["x", "x", "y"]
    assert result.scored == 1
    assert hashes(result.mem) == ["y", "x"] and hashes(result.code) == ["x"]
