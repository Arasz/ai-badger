"""`memory_context.build()` wired to the query pipeline: real proxy session, real `post_json`.

Every row runs a copy of the scripts installed in a scaffold layout, the fake `ai-raccoon`
(`perquery`), and the fake OpenRouter reached through the sentinel-guarded loopback base with an
`sk-test-` key. Timing rows bound at most 4 s against fakes that end by a 20 s ceiling.
"""
from __future__ import annotations

import json
import os
import select
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

import memory_context_openrouter as fake_router
import memory_context_support as support
from memory_context_openrouter import FakeOpenRouter, behaviour, reply
from memory_context_support import ROOT, SCRIPTS, memory_context_env  # noqa: F401

PROMPT = "why does the memory context hook stay silent on every prompt"
ALLOW = "AI_BADGER_ALLOW_THIRD_PARTY"
PRODUCTION_KEY = "sk-or-v1-x"
KEY = "sk-test-wiring"
SIBLING_PREFIX = "ai_badger_memory_context__"
COPY_PREFIX = "ai_badger_test_wiring_"
CATALOG_RESOLVER = ROOT / "features" / "common" / "skills" / "task" / "scripts" / "model_groups.py"
CATALOG_REGISTRY = ROOT / "features" / "common" / "data" / "model-groups.json"
MODULE_FILES = ("memory_context.py", "badger_store.py", "openrouter_client.py", "query_pipeline.py")

PLANNED = [("ConceptAlpha", ["proxy session lifetime"]),
           ("ConceptBeta", ["stage budget arithmetic", "deadline child budgets"])]
QUERIES = [query for _, queries in PLANNED for query in queries]
POOL_SIZE = 15
SCORES = {14: 3.0, 2: 2.5, 9: 2.0, 5: 1.5, 12: 1.0}
MERGED = [14, 2, 9, 5, 12]
PROMPT_HITS = {"results": [{"hash": "p1", "ranking": 1, "path": "/repo/docs/prompt.md",
                            "snippet": "prompt level memory"}], "code": []}


def kind_of(index):
    """Pool index -> kind: the first three hits of each query are memory, the rest code."""
    return "memory" if index // 3 < 3 else "code"


def hit(index):
    """The hit at pool position *index*; its server rank is index + 1, so pool order is index order."""
    if kind_of(index) == "memory":
        return {"hash": f"h{index}", "ranking": index + 1, "path": f"/repo/docs/f{index}.md",
                "snippet": f"memory snippet number {index}"}
    return {"hash": f"h{index}", "ranking": index + 1, "path": f"/repo/src/f{index}.py",
            "snippet": f"code snippet number {index}", "lineStart": index, "lineEnd": index + 1}


def hits_table(size=POOL_SIZE):
    """perquery map: planned query k returns every hit whose index is k modulo 3."""
    table = {PROMPT: PROMPT_HITS}
    for k, query in enumerate(QUERIES):
        mine = [i for i in range(size) if i % 3 == k]
        table[query] = {"results": [hit(i) for i in mine if kind_of(i) == "memory"],
                        "code": [hit(i) for i in mine if kind_of(i) == "code"]}
    return table


def planner_body(planned=None):
    plan = {"concepts": [{"name": name, "queries": queries}
                         for name, queries in (planned or PLANNED)]}
    return json.dumps({"choices": [{"message": {"role": "assistant",
                                                "content": json.dumps(plan)}}]}).encode()


def jev_body(scores, size=POOL_SIZE):
    return json.dumps({"answers": {f"c{i}": {"type": "score", "score": scores.get(i, 0.0)}
                                   for i in range(size)}}).encode()


def block_of(module, mem_indices, code_indices, query=PROMPT):
    return module.format_block(query, [hit(i) for i in mem_indices],
                               [hit(i) for i in code_indices])


def by_path(router, path):
    return [r for r in router.requests if r["path"] == path]


def install(root, layout, *, resolver=True, drop=None, broken=None):
    """Copy the scripts in the *layout* a scaffold uses and load the copied `memory_context`.

    `skill`: `<root>/skills/ai-raccoon-memory/scripts/`, resolver at `<root>/skills/task/scripts/`.
    `flat`: every file in *root* (the Hermes plugin dir), resolver as a flat sibling.
    """
    scripts = root / "skills" / "ai-raccoon-memory" / "scripts" if layout == "skill" else root
    scripts.mkdir(parents=True, exist_ok=True)
    for name in MODULE_FILES:
        if name == drop:
            continue
        target = scripts / name
        if name == broken:
            target.write_text('raise RuntimeError("broken sibling")\n', encoding="utf-8")
        else:
            shutil.copy(SCRIPTS / name, target)
    if resolver:
        where = root / "skills" / "task" / "scripts" if layout == "skill" else scripts
        where.mkdir(parents=True, exist_ok=True)
        shutil.copy(CATALOG_RESOLVER, where / "model_groups.py")
    return load_copy(scripts / "memory_context.py")


def load_copy(path):
    import importlib.util  # pylint: disable=import-outside-toplevel
    key = COPY_PREFIX + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(key, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


def project(env, *, task=True, name="proj"):
    """A project with `.ai-badger/project-id` and the registry; `skills/task/` unless declined."""
    path = env.project(name=name)
    shutil.copy(CATALOG_REGISTRY, path / ".ai-badger" / "model-groups.json")
    if task:
        (path / ".ai-badger" / "skills" / "task").mkdir(parents=True, exist_ok=True)
    return path


def medium_model():
    """The medium tier's preferred id from the catalog registry, `openrouter/` removed."""
    groups = load_copy(CATALOG_RESOLVER)
    ident = groups.resolve(level="medium", groups=groups.load_groups(CATALOG_REGISTRY))
    assert ident.startswith("openrouter/")
    return ident.removeprefix("openrouter/")


def wiring_env(router, **extra):
    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = KEY
    env["AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE"] = router.url
    env.pop(ALLOW, None)
    for name, value in extra.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def run_build(module, env, cwd, run_env, **kwargs):
    return module.build(PROMPT, str(cwd), "sess-1", env=run_env, home=str(env.home), **kwargs)


def scaffold(env):
    """The Claude scaffold: the scripts inside the project's own `.ai-badger/skills/`."""
    path = project(env)
    return path, install(path / ".ai-badger", "skill")


@pytest.fixture(name="sibling_cache", autouse=True)
def _sibling_cache():
    """Each row loads its own copies: hide cached siblings, restore them afterwards."""
    def ours(key):
        return key.startswith(SIBLING_PREFIX) or key.startswith(COPY_PREFIX)
    saved = {key: sys.modules.pop(key) for key in list(sys.modules) if ours(key)}
    yield
    for key in [key for key in sys.modules if ours(key)]:
        del sys.modules[key]
    sys.modules.update(saved)


@pytest.fixture(name="router")
def _router():
    server = FakeOpenRouter()
    yield server
    server.stop()


def assert_clean(env):
    assert support.live_openrouter_threads() == []
    for run in env.fake.runs():
        assert support.pid_gone(run["pid"])


# ------------------------------------------------------------------------------------ B9


def test_b9_end_to_end_one_session_merged_block(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    router.script(fake_router.DECISIONS_PATH, reply(200, jev_body(SCORES)),
                  reply(200, jev_body(SCORES)))
    cwd, module = scaffold(env)

    block = run_build(module, env, cwd, wiring_env(router))

    runs = env.fake.runs()
    assert len(runs) == 1
    assert [m["method"] for m in env.fake.requests() if m.get("id") == 1] == ["initialize"]
    calls = env.fake.calls()
    assert [c["id"] for c in calls] == [2, 3, 4]
    assert [c["params"]["arguments"]["query"] for c in calls] == QUERIES
    for call in calls:
        assert call["params"]["arguments"]["scope"] == "project"
        assert call["params"]["arguments"]["limit"] == 5
    assert len(by_path(router, fake_router.CHAT_PATH)) == 1
    assert len(by_path(router, fake_router.DECISIONS_PATH)) == -(-POOL_SIZE // 12)
    mem = [i for i in MERGED if kind_of(i) == "memory"]
    code = [i for i in MERGED if kind_of(i) == "code"]
    assert block == block_of(module, mem, code)
    planner_text = module._load_sibling("query_pipeline").PLANNER_ADDENDUM  # pylint: disable=protected-access
    for text in [*QUERIES, *(name for name, _ in PLANNED), planner_text[:40]]:
        assert text not in block
    assert_clean(env)


# ------------------------------------------------------------------------------ B10, B11


def single_search_observations(env, router, block, module, spy_calls):
    assert router.requests == []
    assert [c["params"]["arguments"]["query"] for c in env.fake.calls()] == [PROMPT]
    assert spy_calls == []
    assert block == module.format_block(PROMPT, PROMPT_HITS["results"], PROMPT_HITS["code"])


def spy_run(module, monkeypatch):
    calls = []
    stages = module._load_sibling("query_pipeline")  # pylint: disable=protected-access
    real = stages.run

    def spy(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)
    monkeypatch.setattr(stages, "run", spy)
    return calls


def test_b10_missing_key_is_single_search_under_the_single_budget(memory_context_env, router,
                                                                   monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = scaffold(env)
    spy_calls = spy_run(module, monkeypatch)

    block = run_build(module, env, cwd, wiring_env(router, OPENROUTER_API_KEY=None))
    single_search_observations(env, router, block, module, spy_calls)
    switched_off = run_build(module, env, cwd,
                             wiring_env(router, AI_BADGER_MEMORY_CONTEXT_PIPELINE="0"))
    assert block == switched_off

    monkeypatch.setattr(module, "SINGLE_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(module, "PIPELINE_TOTAL_SECONDS", 30.0)
    env.fake.mode("hang")
    started = time.monotonic()
    assert run_build(module, env, cwd, wiring_env(router, OPENROUTER_API_KEY=None)) is None
    assert time.monotonic() - started < 2.0
    assert spy_calls == []
    assert router.requests == []
    assert_clean(env)


@pytest.mark.parametrize("value", ["", "false", "off", "00", " 0"])
def test_b11_only_literal_zero_turns_the_pipeline_off(memory_context_env, router, monkeypatch,
                                                      value):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = scaffold(env)
    spy_calls = spy_run(module, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE", router.url)

    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT_PIPELINE", "0")
    block = module.build(PROMPT, str(cwd), "sess-1", home=str(env.home))
    single_search_observations(env, router, block, module, spy_calls)

    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT_PIPELINE", value)
    module.build(PROMPT, str(cwd), "sess-1", home=str(env.home))
    assert len(by_path(router, fake_router.CHAT_PATH)) == 1
    assert len(spy_calls) == 1


# ----------------------------------------------------------------------------------- B12


def test_b12_planner_failure_falls_back_to_one_prompt_search(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    router.script(fake_router.CHAT_PATH, reply(500, b'{"error": "down"}'))
    cwd, module = scaffold(env)

    block = run_build(module, env, cwd, wiring_env(router))

    assert [c["params"]["arguments"]["query"] for c in env.fake.calls()] == [PROMPT]
    assert len(by_path(router, fake_router.CHAT_PATH)) == 1
    assert by_path(router, fake_router.DECISIONS_PATH) == []
    assert block == module.format_block(PROMPT, PROMPT_HITS["results"], PROMPT_HITS["code"])


def test_b12_jev_failure_merges_planned_hits_by_server_rank(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    router.script(fake_router.DECISIONS_PATH, *[reply(500, b'{"error": "down"}')] * 6)
    cwd, module = scaffold(env)

    block = run_build(module, env, cwd, wiring_env(router))

    assert [c["params"]["arguments"]["query"] for c in env.fake.calls()] == QUERIES
    assert len(by_path(router, fake_router.DECISIONS_PATH)) == 6
    assert block == block_of(module, [0, 1, 2, 3, 4], [])


# ----------------------------------------------------------------------------------- B13


@pytest.mark.parametrize("how", ["missing", "raising"])
@pytest.mark.parametrize("sibling", support.load_module().SIBLINGS)
def test_b13_a_bad_sibling_leaves_single_search(memory_context_env, router, sibling, how):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd = project(env)
    module = install(cwd / ".ai-badger", "skill", drop=sibling if how == "missing" else None,
                     broken=sibling if how == "raising" else None)
    assert sibling in module.SIBLINGS

    block = run_build(module, env, cwd, wiring_env(router))

    assert block == module.format_block(PROMPT, PROMPT_HITS["results"], PROMPT_HITS["code"])
    assert [c["params"]["arguments"]["query"] for c in env.fake.calls()] == [PROMPT]
    assert router.requests == []


# ----------------------------------------------------------------------------------- B14


@pytest.mark.parametrize("stall", ["planner-drip", "jev-hang"])
def test_b14_stage_shares_stay_inside_the_total(memory_context_env, router, stall):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    if stall == "planner-drip":
        router.script(fake_router.CHAT_PATH, behaviour("body-drip"))
    else:
        router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
        router.script(fake_router.DECISIONS_PATH, *[behaviour("hang")] * 6)
    cwd, module = scaffold(env)
    stages = module._load_sibling("query_pipeline")  # pylint: disable=protected-access
    scaled = stages.Limits(3.0, 15.0 / 30, 15.0 / 30, 8.0 / 30)

    started = time.monotonic()
    block = run_build(module, env, cwd, wiring_env(router), limits=scaled)
    assert time.monotonic() - started < 4.0

    assert block is not None
    assert len(env.fake.runs()) == 1
    assert_clean(env)


# ----------------------------------------------------------------------------------- B15


def test_b15_requests_reach_the_server_through_the_real_client(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    router.script(fake_router.DECISIONS_PATH, reply(200, jev_body(SCORES)),
                  reply(200, jev_body(SCORES)))
    cwd, module = scaffold(env)
    stages = module._load_sibling("query_pipeline")  # pylint: disable=protected-access

    run_build(module, env, cwd, wiring_env(router))

    (chat,) = by_path(router, fake_router.CHAT_PATH)
    assert chat["method"] == "POST"
    assert chat["headers"]["authorization"] == f"Bearer {KEY}"
    assert chat["headers"]["content-type"] == "application/json"
    assert chat["body"] == {"model": medium_model(), "messages": [
        {"role": "system", "content": stages.DELEGATOR_PERSONA + "\n\n" + stages.PLANNER_ADDENDUM},
        {"role": "user", "content": stages.build_user_prompt(PROMPT)}]}
    decisions = by_path(router, fake_router.DECISIONS_PATH)
    asked = {}
    for request in decisions:
        assert request["headers"]["authorization"] == f"Bearer {KEY}"
        assert set(request["body"]) == {"model", "state", "questions"}
        assert request["body"]["model"] == stages.MODEL
        assert request["body"]["state"] == PROMPT
        asked.update(request["body"]["questions"])
    assert sorted(asked, key=lambda name: int(name[1:])) == [f"c{i}" for i in range(POOL_SIZE)]
    for i in range(POOL_SIZE):
        assert asked[f"c{i}"] == stages.build_score_question({**hit(i), "kind": kind_of(i)})
    assert [len(r["body"]["questions"]) for r in decisions] == [12, 3]


# ----------------------------------------------------------------------------------- B16


@pytest.mark.parametrize("layout", ["skill", "flat"])
def test_b16_declined_task_has_no_planner_model(memory_context_env, router, layout):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    module = install(env.root / "plugin", layout)
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()), reply(200, planner_body()))

    declined = project(env, task=False, name="declined")
    block = run_build(module, env, declined, wiring_env(router))
    assert block == module.format_block(PROMPT, PROMPT_HITS["results"], PROMPT_HITS["code"])
    assert [c["params"]["arguments"]["query"] for c in env.fake.calls()] == [PROMPT]
    assert router.requests == []

    run_build(module, env, declined,
              wiring_env(router, AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL="vendor/override-model"))
    assert [r["body"]["model"] for r in by_path(router, fake_router.CHAT_PATH)] == [
        "vendor/override-model"]

    accepted = project(env, name="accepted")
    run_build(module, env, accepted, wiring_env(router))
    assert [r["body"]["model"] for r in by_path(router, fake_router.CHAT_PATH)] == [
        "vendor/override-model", medium_model()]


# ----------------------------------------------------------------------------------- B17


def planted_resolver(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"import pathlib\npathlib.Path({str(marker)!r}).write_text('loaded')\n"
                    "def load_groups(path=None):\n    return {}\n"
                    "def resolve(level=None, explicit_model=None, groups=None):\n"
                    "    return 'openrouter/planted/model'\n", encoding="utf-8")


def test_b17_flat_layout_loads_only_a_flat_sibling_resolver(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    flat = env.root / "hermes" / "plugin"
    module = install(flat, "flat", resolver=False)
    marker = env.root / "planted-marker"
    planted_resolver(flat.parent / "task" / "scripts" / "model_groups.py", marker)
    planted_resolver(flat / "task" / "scripts" / "model_groups.py", marker)
    cwd = project(env)

    block = run_build(module, env, cwd, wiring_env(router))

    assert not marker.exists()
    assert router.requests == []
    assert block == module.format_block(PROMPT, PROMPT_HITS["results"], PROMPT_HITS["code"])
    assert SIBLING_PREFIX + "model_groups" not in sys.modules


def test_b17_skill_layout_loads_only_the_task_skill_resolver(memory_context_env, router):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    root = env.root / "scaffold"
    module = install(root, "skill")
    marker = env.root / "planted-marker"
    scripts = root / "skills" / "ai-raccoon-memory" / "scripts"
    planted_resolver(scripts / "model_groups.py", marker)
    planted_resolver(scripts.parent / "task" / "scripts" / "model_groups.py", marker)
    cwd = project(env)

    run_build(module, env, cwd, wiring_env(router))

    assert not marker.exists()
    assert [r["body"]["model"] for r in by_path(router, fake_router.CHAT_PATH)] == [
        medium_model()]
    loaded = sys.modules[SIBLING_PREFIX + "model_groups"]
    assert Path(loaded.__file__).resolve() == (
        root / "skills" / "task" / "scripts" / "model_groups.py").resolve()


# ----------------------------------------------------------------------------------- J6b


def hang_until_eof(handler):
    """Hold the reply until the client closes the connection; record when it did."""
    owner = handler.server.owner
    end = time.monotonic() + owner.ceiling
    while not owner.stopping.is_set() and time.monotonic() < end:
        ready, _, _ = select.select([handler.connection], [], [], 0.02)
        if ready:
            try:
                data = handler.connection.recv(1)
            except OSError:
                data = b""
            if not data:
                owner.eof_at.append(time.monotonic())
                break
    handler.close_connection = True


def test_j6b_real_clock_retry_on_a_fresh_connection(memory_context_env, router, monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table(size=3))
    real_answer = fake_router._Handler._answer  # pylint: disable=protected-access
    real_record = fake_router._Handler._record  # pylint: disable=protected-access

    def answer(handler, step):
        if step.behaviour == "hang-until-eof":
            hang_until_eof(handler)
        else:
            real_answer(handler, step)

    def record(handler):
        real_record(handler)
        handler.server.owner.requests[-1]["at"] = time.monotonic()

    monkeypatch.setattr(fake_router._Handler, "_answer", answer)  # pylint: disable=protected-access
    monkeypatch.setattr(fake_router._Handler, "_record", record)  # pylint: disable=protected-access
    router.eof_at = []
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    router.script(fake_router.DECISIONS_PATH, behaviour("hang-until-eof"),
                  reply(200, jev_body({0: 0.0, 1: 1.0, 2: 2.0}, size=3)))
    cwd, module = scaffold(env)
    stages = module._load_sibling("query_pipeline")  # pylint: disable=protected-access
    monkeypatch.setattr(stages, "ATTEMPT_SECONDS", 0.2)

    block = run_build(module, env, cwd, wiring_env(router),
                      limits=stages.Limits(30.0, 5.0, 5.0, 0.5))

    decisions = by_path(router, fake_router.DECISIONS_PATH)
    assert len(decisions) == 2
    assert len(router.eof_at) == 1
    assert router.eof_at[0] < decisions[1]["at"]
    assert block == block_of(module, [2, 1, 0], [])
    assert_clean(env)


# ------------------------------------------------------------------- third-party egress


def production_env(**extra):
    """A production key and no loopback test base: only the opt-in may route to OpenRouter."""
    env = {name: value for name, value in os.environ.items()
           if name not in (ALLOW, "AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE")}
    env["OPENROUTER_API_KEY"] = PRODUCTION_KEY
    env.update(extra)
    return env


def lock(path):
    (path / ".ai-badger").mkdir(parents=True, exist_ok=True)
    (path / ".ai-badger" / "config.json").write_text('{"dataPolicy": "local-only"}',
                                                     encoding="utf-8")


def test_a_production_key_alone_builds_no_pipeline(memory_context_env):
    cwd, module = scaffold(memory_context_env)
    assert module.pipeline_for(production_env(), str(cwd), None) is None
    assert module.pipeline_for(production_env(**{ALLOW: "true"}), str(cwd), None) is None


def test_the_opt_in_from_an_unlocked_project_routes_to_production(memory_context_env):
    cwd, module = scaffold(memory_context_env)
    env = production_env(**{ALLOW: "1"})
    pipeline = module.pipeline_for(env, str(cwd), None)
    assert pipeline is not None
    for stage in (pipeline.plan, pipeline.score):
        assert stage.keywords["base"] == "https://openrouter.ai"
        assert stage.keywords["key"] == PRODUCTION_KEY
        assert stage.keywords["post"].keywords == {"env": env, "cwd": str(cwd)}


def test_a_locked_project_builds_no_pipeline_even_with_the_opt_in(memory_context_env):
    cwd, module = scaffold(memory_context_env)
    lock(cwd)
    assert module.pipeline_for(production_env(**{ALLOW: "1"}), str(cwd), None) is None


def recorder():
    """An `on_error` that records `where` and the exception being handled, nothing else."""
    seen = []

    def record(where):
        seen.append((where, sys.exc_info()[0]))
    return seen, record


def test_an_opted_in_build_refused_by_a_lock_reports_the_config_once(memory_context_env,
                                                                     monkeypatch):
    cwd, module = scaffold(memory_context_env)
    lock(cwd)
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    for _ in range(2):
        run_build(module, memory_context_env, cwd, production_env(**{ALLOW: "1"}),
                  on_error=record)
    config = os.path.join(os.path.abspath(cwd), ".ai-badger", "config.json")
    assert seen == [(f"memory_context.egress-refused {config}: dataPolicy", None)]
    assert PROMPT not in repr(seen)
    assert memory_context_env.guards.net_attempts == []


def test_an_opted_in_refusal_names_the_lock_that_denies_not_the_nearest(memory_context_env,
                                                                        monkeypatch):
    parent, module = scaffold(memory_context_env)
    lock(parent)
    child = parent / "child"
    (child / ".ai-badger").mkdir(parents=True)
    policy = {"mode": "local-only", "allowHosts": ["openrouter.ai"]}
    (child / ".ai-badger" / "config.json").write_text(json.dumps({"dataPolicy": policy}),
                                                      encoding="utf-8")
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    assert module.pipeline_for(production_env(**{ALLOW: "1"}), str(child), None,
                               on_error=record) is None
    config = os.path.join(os.path.abspath(parent), ".ai-badger", "config.json")
    assert seen == [(f"memory_context.egress-refused {config}: dataPolicy", None)]


def test_an_opted_in_refusal_with_no_lock_reports_a_bad_base_once(memory_context_env,
                                                                  monkeypatch):
    cwd, module = scaffold(memory_context_env)
    client = module._load_sibling("openrouter_client")  # pylint: disable=protected-access
    monkeypatch.setattr(client, "api_base", lambda env, key: "http://decider.corp.example")
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    for _ in range(2):
        assert module.pipeline_for(production_env(**{ALLOW: "1"}), str(cwd), None,
                                   on_error=record) is None
    assert seen == [("memory_context.egress-refused bad-base", None)]
    assert "decider" not in repr(seen)


@pytest.mark.parametrize("value,cause", [
    ("http://127.0.0.1:3128/path", "malformed"),
    ("h;x:3128", "malformed"),
    ("http://user:pass@127.0.0.1:3128", "unsupported"),
    ("https://127.0.0.1:3128", "unsupported"),
])
def test_an_opted_in_refused_proxy_is_reported_once_and_serves_the_local_search(
        memory_context_env, router, monkeypatch, value, cause):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = scaffold(env)
    spy_calls = spy_run(module, monkeypatch)
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    for _ in range(3):
        block = run_build(module, env, cwd, production_env(**{ALLOW: "1", "HTTPS_PROXY": value}),
                          on_error=record)
        single_search_observations(env, router, block, module, spy_calls)
    assert seen == [(f"memory_context.proxy-refused: {cause}", None)]
    assert "3128" not in repr(seen) and "pass" not in repr(seen)
    assert env.guards.net_attempts == []


def test_a_refused_proxy_is_not_reported_without_the_opt_in(memory_context_env, monkeypatch):
    cwd, module = scaffold(memory_context_env)
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    assert module.pipeline_for(production_env(HTTPS_PROXY="h;x:1"), str(cwd), None,
                               on_error=record) is None
    assert seen == []


def test_a_proxy_refusing_connect_is_reported_once_as_its_status(memory_context_env, monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = scaffold(env)
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    refuse = fake_router.CaptureProxy(mode="refuse", refuse_status=407)
    try:
        for _ in range(2):
            run_build(module, env, cwd, production_env(**{ALLOW: "1", "HTTPS_PROXY": refuse.url}),
                      on_error=record)
    finally:
        refuse.stop()
    assert refuse.connects and all(c["line"].startswith("CONNECT openrouter.ai:443 ")
                                   for c in refuse.connects)
    assert seen == [("memory_context.proxy-refused: connect-407", None)]
    assert "Refused" not in repr(seen)
    assert [attempt for attempt in env.guards.net_attempts
            if "openrouter" in repr(attempt)] == []


@pytest.mark.parametrize("extra", [{}, {ALLOW: "true"}, {ALLOW: "1", "OPENROUTER_API_KEY": ""}],
                         ids=["not-opted-in", "not-literal-one", "no-key"])
def test_a_lock_refusal_is_not_reported_without_the_opt_in_and_a_key(memory_context_env,
                                                                     monkeypatch, extra):
    cwd, module = scaffold(memory_context_env)
    lock(cwd)
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    assert module.pipeline_for(production_env(**extra), str(cwd), None, on_error=record) is None
    assert seen == []


def test_a_defect_inside_pipeline_for_is_reported(memory_context_env, monkeypatch):
    cwd, module = scaffold(memory_context_env)
    monkeypatch.setattr(module, "_REPORTED", set())

    def broken(stem):
        raise NameError(stem)
    monkeypatch.setattr(module, "_load_sibling", broken)
    seen, record = recorder()
    assert module.pipeline_for(production_env(**{ALLOW: "1"}), str(cwd), None,
                               on_error=record) is None
    assert seen == [("memory_context.pipeline_for", NameError)]


def test_a_production_key_alone_serves_the_single_local_search(memory_context_env, router,
                                                               monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = scaffold(env)
    spy_calls = spy_run(module, monkeypatch)

    block = run_build(module, env, cwd, production_env())
    single_search_observations(env, router, block, module, spy_calls)
    assert env.guards.net_attempts == []
    assert_clean(env)


# ------------------------------------------------------------------- project-id binding

PROJECT_ID = "AI_BADGER_PROJECT_ID"
MISMATCH = "memory_context.project-id-mismatch"


def bound(env, project_id, name="open"):
    """A scaffolded project whose `.ai-badger/project-id` holds *project_id* (none when None)."""
    path = env.project(project_id, name=name)
    shutil.copy(CATALOG_REGISTRY, path / ".ai-badger" / "model-groups.json")
    return path, install(path / ".ai-badger", "skill")


def opted(router, **extra):
    """The loopback wiring env, opted in: only the project-id binding can refuse the pipeline."""
    return wiring_env(router, **{ALLOW: "1", PROJECT_ID: None, **extra})


def test_b1_an_override_naming_another_project_builds_no_pipeline(memory_context_env, router,
                                                                 monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = bound(env, "open-id")
    assert module.pipeline_for(opted(router), str(cwd), None) is not None
    run_env = opted(router, **{PROJECT_ID: "locked-id"})
    assert module.pipeline_for(run_env, str(cwd), None) is None
    spy_calls = spy_run(module, monkeypatch)
    block = run_build(module, env, cwd, run_env)
    single_search_observations(env, router, block, module, spy_calls)
    assert env.fake.calls()[0]["params"]["arguments"]["projectId"] == "locked-id"


def test_b1b_an_override_in_the_process_env_is_bound_too(memory_context_env, router,
                                                        monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits(hits_table())
    cwd, module = bound(env, "open-id")
    monkeypatch.setenv(PROJECT_ID, "locked-id")
    run_env = opted(router)
    assert PROJECT_ID not in run_env
    assert module.pipeline_for(run_env, str(cwd), None) is None
    spy_calls = spy_run(module, monkeypatch)
    block = run_build(module, env, cwd, run_env)
    single_search_observations(env, router, block, module, spy_calls)
    assert env.fake.calls()[0]["params"]["arguments"]["projectId"] == "locked-id"


def test_b2_a_padded_override_equal_to_the_file_id_builds(memory_context_env, router):
    cwd, module = bound(memory_context_env, "open-id")
    assert module.pipeline_for(opted(router, **{PROJECT_ID: "  open-id \t"}), str(cwd),
                               None) is not None


def test_b3_an_override_with_no_file_id_builds_no_pipeline(memory_context_env, router):
    cwd, module = bound(memory_context_env, None)
    assert module.pipeline_for(opted(router), str(cwd), None) is not None
    assert module.pipeline_for(opted(router, **{PROJECT_ID: "any-id"}), str(cwd), None) is None


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_b4_a_blank_override_is_unset(memory_context_env, router, blank):
    cwd, module = bound(memory_context_env, "open-id")
    assert module.pipeline_for(opted(router, **{PROJECT_ID: blank}), str(cwd), None) is not None


def test_b5_a_mismatch_is_reported_once_when_opted_in(memory_context_env, router, monkeypatch):
    cwd, module = bound(memory_context_env, "open-id")
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    for _ in range(2):
        assert module.pipeline_for(opted(router, **{PROJECT_ID: "locked-id"}), str(cwd), None,
                                   on_error=record) is None
    assert seen == [(MISMATCH + ": differs", None)]
    assert "locked-id" not in repr(seen) and "open-id" not in repr(seen)


def _no_file(module, cwd, monkeypatch):
    del module, monkeypatch
    (cwd / ".ai-badger" / "project-id").unlink()


def _unreadable_id(module, cwd, monkeypatch):
    del module, monkeypatch
    (cwd / ".ai-badger" / "project-id").chmod(0)


def _blank_id(module, cwd, monkeypatch):
    del module, monkeypatch
    (cwd / ".ai-badger" / "project-id").write_text(" \n", encoding="utf-8")


def _store_unavailable(module, cwd, monkeypatch):
    del cwd
    monkeypatch.setattr(module, "load_badger_store", lambda: None)


@pytest.mark.parametrize("break_id,why", [(_no_file, "no-file"), (_unreadable_id, "unreadable"),
                                          (_blank_id, "unreadable"),
                                          (_store_unavailable, "store-unavailable")],
                         ids=["no-file", "unreadable", "blank", "store-unavailable"])
def test_b5_each_mismatch_names_why_and_no_id(memory_context_env, router, monkeypatch,
                                              break_id, why):
    if why == "unreadable" and hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    cwd, module = bound(memory_context_env, "open-id")
    monkeypatch.setattr(module, "_REPORTED", set())
    break_id(module, cwd, monkeypatch)
    seen, record = recorder()
    try:
        for _ in range(2):
            assert module.pipeline_for(opted(router, **{PROJECT_ID: "locked-id"}), str(cwd),
                                       None, on_error=record) is None
    finally:
        if why == "unreadable":
            (cwd / ".ai-badger" / "project-id").chmod(0o600)
    assert seen == [(f"{MISMATCH}: {why}", None)]
    assert "locked-id" not in repr(seen) and "open-id" not in repr(seen)


def test_b5_a_mismatch_is_silent_without_the_opt_in(memory_context_env, router, monkeypatch):
    cwd, module = bound(memory_context_env, "open-id")
    monkeypatch.setattr(module, "_REPORTED", set())
    seen, record = recorder()
    run_env = wiring_env(router, **{PROJECT_ID: "locked-id"})
    assert module.pipeline_for(run_env, str(cwd), None, on_error=record) is None
    assert seen == []


def test_b6_a_nested_override_naming_the_parent_id_builds_no_pipeline(memory_context_env,
                                                                     router):
    parent, module = bound(memory_context_env, "parent-id", name="parent")
    child = parent / "child"
    (child / ".ai-badger").mkdir(parents=True)
    assert module.pipeline_for(opted(router, **{PROJECT_ID: "parent-id"}), str(parent),
                               None) is not None
    assert module.pipeline_for(opted(router, **{PROJECT_ID: "parent-id"}), str(child),
                               None) is None
