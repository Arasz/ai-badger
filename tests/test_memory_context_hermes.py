"""The Hermes memory-context arm of `pre_llm_inject_context` and its install rows.

Every row loads `ai_badger_hooks.py` from a flat plugin-shaped dir (a scratch copy, or the one
`adjust()` installs under a temp HERMES_HOME) with the fake `ai-raccoon` first on PATH and, for
pipeline rows, the fake OpenRouter behind the sentinel-guarded loopback base.
"""
# pylint: disable=redefined-outer-name  # the shared autouse fixture is requested by name
from __future__ import annotations

import importlib.util
import json
import logging
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
from memory_context_support import forget_modules_a_test_imported  # noqa: F401  (autouse)

HOOKS_SOURCE = ROOT / "features" / "common" / "hooks" / "ai_badger_hooks.py"
ADJUSTER = ROOT / "features" / "hermes" / "adjustments" / "adjust_hooks.py"
RESOLVER_SOURCE = ROOT / "features" / "common" / "skills" / "task" / "scripts" / "model_groups.py"
REGISTRY = ROOT / "features" / "common" / "data" / "model-groups.json"
PLUGIN_FILES = ("memory_context.py", "badger_store.py", "openrouter_client.py",
                "query_pipeline.py")
NEW_MODULES = ("memory_context.py", "openrouter_client.py", "query_pipeline.py",
               "model_groups.py")
LOAD_PREFIX = "ai_badger_test_hermes_hooks_"
SIBLING_PREFIX = "ai_badger_memory_context__"
END = "(end of memory context)"
KEY = "sk-test-hermes"
SESSION = "hermes-sess-1"
PROMPT = "why does the hermes memory context arm stay silent on every prompt"
OTHER_PROMPT = "how does the per session memo decide when to search the memory bank again"
PLANNED_QUERY = "hermes arm memo lifetime"
SECOND_QUERY = "session start memo reset"
HITS = {"results": [{"hash": "m1", "ranking": 1, "path": "/repo/docs/hermes.md",
                     "snippet": "hermes memory snippet"}],
        "code": [{"hash": "c1", "ranking": 0.5, "path": "/repo/src/arm.py",
                  "snippet": "def arm(): pass", "lineStart": 3, "lineEnd": 4}]}
PLANNED_HITS = {"results": [{"hash": "p1", "ranking": 1, "path": "/repo/docs/planned.md",
                             "snippet": "planned memory snippet"}], "code": []}


def load_hooks(path):
    """Load the `ai_badger_hooks.py` at *path* under a fresh key."""
    key = LOAD_PREFIX + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(key, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


def plugin_dir(env, *, drop=None, resolver=True):
    """A flat plugin-shaped dir: the hooks module beside the memory-context modules."""
    target = env.root / "plugin"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(HOOKS_SOURCE, target / "ai_badger_hooks.py")
    for name in PLUGIN_FILES:
        if name != drop:
            shutil.copy(SCRIPTS / name, target / name)
    if resolver:
        shutil.copy(RESOLVER_SOURCE, target / "model_groups.py")
    return target


def project(env, monkeypatch, *, skill=True, task=False, name="proj"):
    """A project with an id; the ai-raccoon-memory skill unless declined. Becomes the cwd."""
    path = env.project(name=name)
    if skill:
        (path / ".ai-badger" / "skills" / "ai-raccoon-memory").mkdir(parents=True, exist_ok=True)
    if task:
        (path / ".ai-badger" / "skills" / "task").mkdir(parents=True, exist_ok=True)
        shutil.copy(REGISTRY, path / ".ai-badger" / "model-groups.json")
    monkeypatch.chdir(path)
    return path


def planner_body(queries=(PLANNED_QUERY, SECOND_QUERY)):
    plan = {"concepts": [{"name": "HermesArm", "queries": list(queries)}]}
    return json.dumps({"choices": [{"message": {"role": "assistant",
                                                "content": json.dumps(plan)}}]}).encode()


def pipeline_on(monkeypatch, router, *, model="vendor/override-model"):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT_TEST_OPENROUTER_BASE", router.url)
    if model:
        monkeypatch.setenv("AI_BADGER_MEMORY_CONTEXT_PLANNER_MODEL", model)


def chat_requests(router):
    return [r for r in router.requests if r["path"] == fake_router.CHAT_PATH]


def call(hooks, prompt=PROMPT, session=SESSION, **kwargs):
    kwargs.setdefault("platform", "cli")
    kwargs.setdefault("user_message", prompt)
    return hooks.pre_llm_inject_context(session_id=session, conversation_history=[],
                                        is_first_turn=True, model="m", **kwargs)


def context_of(result):
    return (result or {}).get("context") or ""


def expected_block(hooks, query=PROMPT, hits=None):
    hits = hits or HITS
    return hooks._load_memory_context().format_block(  # pylint: disable=protected-access
        query, hits["results"], hits["code"])


@pytest.fixture(name="reset", autouse=True)
def _reset():
    """Hide every memory-context module and loaded hooks copy; restore them afterwards."""
    def ours(key):
        return (key.startswith(SIBLING_PREFIX) or key.startswith(LOAD_PREFIX)
                or key == "ai_badger_memory_context")
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


@pytest.fixture(name="hooks")
def _hooks(memory_context_env):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits({PROMPT: HITS, OTHER_PROMPT: HITS, PLANNED_QUERY: PLANNED_HITS})
    return load_hooks(plugin_dir(env) / "ai_badger_hooks.py")


def runs(env):
    return env.fake.runs()


# ------------------------------------------------------------------------------ W1, W2


@pytest.mark.parametrize("kwarg", ["user_message", "message"])
def test_w1_real_payload_and_message_variant_carry_the_block(memory_context_env, hooks,
                                                             monkeypatch, kwarg):
    env = memory_context_env
    project(env, monkeypatch)
    kwargs = {"user_message": ""} if kwarg == "message" else {}
    kwargs[kwarg] = PROMPT

    result = call(hooks, **kwargs)

    assert expected_block(hooks) in context_of(result)
    assert len(runs(env)) == 1
    [search] = env.fake.calls()
    assert search["params"]["arguments"]["sessionId"] == SESSION
    assert search["params"]["arguments"]["query"] == PROMPT


def test_w2_block_is_the_last_part_and_the_terminator_follows_it(memory_context_env, hooks,
                                                                 monkeypatch):
    project(memory_context_env, monkeypatch)

    context = context_of(call(hooks))

    block = expected_block(hooks)
    assert context.endswith("\n" + block + "\n" + END)
    assert context.startswith("[Hermes] Use /usage")
    assert context.count(END) == 1


# ------------------------------------------------------------------------------ W3, W4


def test_w3_missing_sibling_keeps_other_parts_and_logs_once(memory_context_env, monkeypatch,
                                                            caplog):
    env = memory_context_env
    hooks = load_hooks(plugin_dir(env, drop="memory_context.py") / "ai_badger_hooks.py")
    project(env, monkeypatch)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    first = context_of(call(hooks))
    call(hooks, prompt=OTHER_PROMPT)

    assert first.startswith("[Hermes] Use /usage")
    assert END not in first
    missing = [r for r in caplog.records if "memory context missing" in r.getMessage()]
    assert len(missing) == 1
    assert runs(env) == []


def test_w4_build_failure_keeps_other_parts_and_logs_the_type_only(memory_context_env, hooks,
                                                                   monkeypatch, caplog):
    env = memory_context_env
    project(env, monkeypatch)
    module = hooks._load_memory_context()  # pylint: disable=protected-access

    def explode(prompt, *_args, **_kwargs):
        raise RuntimeError(f"boom while handling {prompt}")
    monkeypatch.setattr(module, "build", explode)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    context = context_of(call(hooks))

    assert context.startswith("[Hermes] Use /usage")
    assert END not in context
    warnings = [r for r in caplog.records if "memory context" in r.getMessage()]
    assert len(warnings) == 1
    assert "RuntimeError" in caplog.text
    assert PROMPT not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


# ------------------------------------------------------------------------------ W6, W7


def test_w6_declined_skill_leaves_the_arm_inert(memory_context_env, hooks, monkeypatch):
    env = memory_context_env
    project(env, monkeypatch, skill=False, name="declined")
    assert END not in context_of(call(hooks))
    assert runs(env) == []

    project(env, monkeypatch, name="accepted")
    assert END in context_of(call(hooks, session="accepted-sess"))
    assert len(runs(env)) == 1


RUNS = "runs"
INERT = "inert"
PLATFORMS = [("cli", RUNS), (None, RUNS), ("", RUNS), ("<absent>", RUNS),
             ("CLI", INERT), ("telegram", INERT), ("discord", INERT), ("gateway", INERT),
             ("subagent", INERT)]


@pytest.mark.parametrize(("platform", "outcome"), PLATFORMS)
def test_w7_only_a_cli_session_searches(memory_context_env, hooks, router, monkeypatch,
                                        platform, outcome):
    """Hermes's own normalisation `(platform or "cli") == "cli"`: an empty platform is the CLI
    (Hermes passes `""` when the agent has none); every named non-CLI platform stays inert."""
    env = memory_context_env
    project(env, monkeypatch)
    pipeline_on(monkeypatch, router)
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    if platform == "<absent>":
        result = hooks.pre_llm_inject_context(session_id=SESSION, user_message=PROMPT)
    else:
        result = call(hooks, platform=platform)

    if outcome == RUNS:
        assert len(runs(env)) == 1
        assert len(chat_requests(router)) == 1
        assert END in context_of(result)
    else:
        assert runs(env) == []
        assert router.requests == []
        assert END not in context_of(result)


# ------------------------------------------------------------------------------------ W9


def test_w9_a_hanging_proxy_returns_inside_the_budget_and_leaves_nothing(memory_context_env,
                                                                        hooks, monkeypatch):
    env = memory_context_env
    project(env, monkeypatch)
    env.fake.mode("hang")
    module = hooks._load_memory_context()  # pylint: disable=protected-access
    monkeypatch.setattr(module, "SINGLE_BUDGET_SECONDS", 0.5)
    monkeypatch.setattr(module, "PIPELINE_TOTAL_SECONDS", 0.5)

    started = time.monotonic()
    context = context_of(call(hooks))
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert END not in context
    assert len(runs(env)) == 1
    assert all(support.pid_gone(run["pid"]) for run in runs(env))
    assert support.live_openrouter_threads() == []


# ------------------------------------------------------------------------------ W8, W10


def adjust_context(env, target):
    return {
        "framework_root": ROOT,
        "config": {"agents": ["hermes"]},
        "feature_dir": ROOT / "features" / "hermes" / "adjustments",
        "target_dir": target / ".ai-badger",
        "target": target,
        "install": True,
    }


def install_plugin(env, monkeypatch):
    """Run the real Hermes adjuster with HERMES_HOME inside the test's temp HOME."""
    hermes_home = env.home / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    assert env.root in hermes_home.parents
    adjuster = load_hooks(ADJUSTER)
    target = env.root / "target"
    target.mkdir()
    adjuster.adjust(adjust_context(env, target))
    return adjuster, target, hermes_home / "plugins" / "ai-badger"


def test_w8_adjust_ships_the_four_modules_to_both_destinations(memory_context_env,
                                                               monkeypatch):
    adjuster, target, plugin = install_plugin(memory_context_env, monkeypatch)

    for name in NEW_MODULES:
        assert (target / ".ai-badger" / "hooks" / name).is_file(), name
        assert (plugin / name).is_file(), name
        assert name in adjuster.LEGACY_FLAT_FILES


def planted_resolver(path, marker):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"import pathlib\npathlib.Path({str(marker)!r}).write_text('loaded')\n"
                    "def load_groups(path=None):\n    return {}\n"
                    "def resolve(level=None, explicit_model=None, groups=None):\n"
                    "    return 'openrouter/planted/model'\n", encoding="utf-8")


def test_w10_installed_plugin_runs_the_pipeline_from_its_own_dir(memory_context_env, router,
                                                                 monkeypatch):
    env = memory_context_env
    env.fake.mode("perquery")
    env.fake.hits({PROMPT: HITS, PLANNED_QUERY: PLANNED_HITS})
    _, _, plugin = install_plugin(env, monkeypatch)
    cwd = project(env, monkeypatch, task=True)
    pipeline_on(monkeypatch, router, model=None)
    router.script(fake_router.CHAT_PATH, reply(200, planner_body()))
    hooks = load_hooks(plugin / "ai_badger_hooks.py")

    context = context_of(call(hooks, session="w10-a"))

    assert END in context
    assert len(chat_requests(router)) == 1
    assert [c["params"]["arguments"]["query"] for c in env.fake.calls()] == [PLANNED_QUERY,
                                                                        SECOND_QUERY]
    loaded = {key: mod for key, mod in sys.modules.items()
              if key.startswith(SIBLING_PREFIX) or key == "ai_badger_memory_context"}
    for stem in ("openrouter_client", "query_pipeline", "model_groups"):
        assert SIBLING_PREFIX + stem in loaded, stem
    for key, mod in loaded.items():
        assert plugin.resolve() in Path(mod.__file__).resolve().parents, key

    (plugin / "model_groups.py").unlink()
    sys.modules.pop(SIBLING_PREFIX + "model_groups", None)
    marker = env.root / "planted-marker"
    planted_resolver(env.home / ".hermes" / "task" / "scripts" / "model_groups.py", marker)
    planted_resolver(cwd / "task" / "scripts" / "model_groups.py", marker)
    before = len(chat_requests(router))

    context = context_of(call(hooks, session="w10-b"))

    assert not marker.exists()
    assert len(chat_requests(router)) == before
    assert env.fake.calls()[-1]["params"]["arguments"]["query"] == PROMPT
    assert END in context

    shutil.copy(RESOLVER_SOURCE, plugin / "model_groups.py")
    module = hooks._load_memory_context()  # pylint: disable=protected-access
    monkeypatch.setattr(module, "PLANNER_SECONDS", 0.5)
    router.script(fake_router.CHAT_PATH, behaviour("body-drip"))
    started = time.monotonic()
    context = context_of(call(hooks, session="w10-c"))
    assert time.monotonic() - started < 3.0
    assert env.fake.calls()[-1]["params"]["arguments"]["query"] == PROMPT
    assert END in context
    assert support.live_openrouter_threads() == []


# ------------------------------------------------------------------------------ W11


def test_w11_the_arm_hands_build_limits_that_end_before_the_hermes_callback_cap(
        memory_context_env, hooks, monkeypatch):
    """Hermes abandons a pre_llm_call callback after 30 s (plugins_dispatch.py:153), which loses
    the whole turn's injection; the arm must hand build() stage limits that end before that."""
    env = memory_context_env
    project(env, monkeypatch)
    module = hooks._load_memory_context()  # pylint: disable=protected-access
    seen = []

    def spy(prompt, *_args, **kwargs):
        seen.append(kwargs)
    monkeypatch.setattr(module, "build", spy)

    call(hooks)

    assert len(seen) == 1
    assert tuple(seen[0]["limits"]) == tuple(module.stage_limits(hooks.MEMORY_CONTEXT_SECONDS))
    assert seen[0]["limits"][0] == hooks.MEMORY_CONTEXT_SECONDS < 30
    assert callable(seen[0]["on_error"])


# ------------------------------------------------------------------------------ W12, W13


def test_w12_a_programming_error_inside_build_is_warned_once_by_type(memory_context_env, hooks,
                                                                    monkeypatch, caplog):
    env = memory_context_env
    project(env, monkeypatch)
    module = hooks._load_memory_context()  # pylint: disable=protected-access

    def broken(_prompt):
        raise NameError(f"never logged {PROMPT}")
    monkeypatch.setattr(module, "should_enrich", broken)
    monkeypatch.setattr(module, "_REPORTED", set(), raising=False)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    first = context_of(call(hooks))
    call(hooks, prompt=OTHER_PROMPT)

    assert first.startswith("[Hermes] Use /usage")
    assert END not in first
    warnings = [r for r in caplog.records if "memory context" in r.getMessage()]
    assert len(warnings) == 1
    assert "memory_context.build: NameError at " in warnings[0].getMessage()
    assert PROMPT not in caplog.text
    assert runs(env) == []


def test_w13_a_failing_skill_check_keeps_the_other_parts(memory_context_env, hooks, monkeypatch,
                                                        caplog):
    env = memory_context_env
    project(env, monkeypatch)

    def unreadable(*_args):
        raise PermissionError("w13")
    monkeypatch.setattr(hooks, "_memory_context_wanted", unreadable)
    caplog.set_level(logging.WARNING, logger="ai_badger_hooks")

    context = context_of(call(hooks))

    assert context.startswith("[Hermes] Use /usage")
    assert END not in context
    assert "PermissionError" in caplog.text
    assert runs(env) == []


def test_a_hermes_notice_outside_an_exception_names_no_failure(hooks, caplog):
    where = "memory_context.egress-refused /corp/.ai-badger/config.json: dataPolicy"
    with caplog.at_level("WARNING"):
        hooks._memory_context_failed(where)  # pylint: disable=protected-access
    assert [r.getMessage() for r in caplog.records] == [f"memory context: {where}"]
