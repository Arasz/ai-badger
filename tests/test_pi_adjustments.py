"""Tests for pi agent adjustments: MCP, hooks, task, cron."""
# pylint: disable=protected-access,redefined-outer-name  # module internals + fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import os
import types
from pathlib import Path

import pytest

# Self-derived at collection time, before conftest's session fixture redirects $HOME — the
# same idiom as tests/test_suite_isolation.py's REAL_HOME, and for the same reason: a test
# proving USER_EXTENSIONS_DIR was patched away from the real home must not derive "real" from
# the fixture it is checking.
_REAL_HOME = Path.home()


def _real_extension_state(name: str):
    """A fingerprint of a real ~/.pi/agent/extensions/<name>/ dir: filenames and their bytes.

    Asserting the directory does not EXIST would be a different claim, and a false one: once
    ai-badger is installed for pi on a developer's machine — the state this whole feature
    exists to produce — that directory is supposed to be there. What a test may claim is that
    IT did not write to it, so the check is before-and-after, matching
    test_pi_settings_write_does_not_touch_real_home.
    """
    root = _REAL_HOME / ".pi" / "agent" / "extensions" / name
    if not root.is_dir():
        return None
    return {p.name: p.read_bytes() for p in sorted(root.iterdir()) if p.is_file()}


@pytest.fixture
def pi_user_extensions(load_script, tmp_path, monkeypatch):
    """Load adjust_hooks and adjust_cron with USER_EXTENSIONS_DIR redirected under tmp_path.

    ``USER_EXTENSIONS_DIR`` is a module-level ``Path.home()``-based constant in both modules;
    conftest's session ``$HOME`` redirect is the floor, but the constant is only rebuilt once,
    at import time, so a test must patch the attribute on the module object it actually holds
    (``load_script`` builds a fresh module per call) — patched *after* load, *before* any
    ``adjust()`` call. No test using this fixture may write to the real
    ``~/.pi/agent/extensions/``.
    """
    hooks = load_script("features/pi/adjustments/adjust_hooks.py")
    cron = load_script("features/pi/adjustments/adjust_cron.py")

    hooks_dir = tmp_path / "pi" / "agent" / "extensions" / "ai-badger"
    cron_dir = tmp_path / "pi" / "agent" / "extensions" / "pi-cron"
    monkeypatch.setattr(hooks, "USER_EXTENSIONS_DIR", hooks_dir)
    monkeypatch.setattr(cron, "USER_EXTENSIONS_DIR", cron_dir)

    return types.SimpleNamespace(hooks=hooks, cron=cron, hooks_dir=hooks_dir, cron_dir=cron_dir)


@pytest.fixture
def pi_settings_modules(load_script, tmp_path, monkeypatch):
    """Load adjust_skills and adjust_mcp with pi_settings.SETTINGS_PATH redirected to tmp_path.

    Both modules do ``import pi_settings`` after inserting their own directory onto
    ``sys.path``; Python's import cache means that resolves to one shared module object no
    matter which of the two files triggers the first import, so patching the attribute on
    either module's ``pi_settings`` reference redirects both. No test using this fixture may
    write to the real ``~/.pi/agent/settings.json``.
    """
    skills = load_script("features/pi/adjustments/adjust_skills.py")
    mcp = load_script("features/pi/adjustments/adjust_mcp.py")

    settings_path = tmp_path / "pi" / "agent" / "settings.json"
    monkeypatch.setattr(skills.pi_settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(mcp.pi_settings, "SETTINGS_PATH", settings_path)

    return types.SimpleNamespace(skills=skills, mcp=mcp, settings_path=settings_path)


def test_adjust_mcp_no_pi_in_config(load_script):
    """adjust_mcp returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {"config": {"agents": ["claude"]}, "mcp_declarations": {}, "mcp_declined": []}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_mcp_no_declarations(load_script):
    """adjust_mcp returns unapplied when no MCP servers declared."""
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {"config": {"agents": ["pi"]}, "mcp_declarations": {}, "mcp_declined": []}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_mcp_proposes_servers(load_script):
    """adjust_mcp returns applied with notes when pi and servers declared.

    install: False — this test exercises the printed-snippet path specifically; G2's
    settings-merge path (install=True) has its own tests under pi_settings_modules, which
    monkeypatch pi_settings.SETTINGS_PATH so nothing here can reach the real home directory.
    """
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {
            "filesystem": {"command": "npx -y @modelcontextprotocol/server-filesystem /tmp"},
        },
        "mcp_declined": [],
        "install": False,
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert "MCP server" in result["notes"]


def test_adjust_mcp_respects_decline(load_script):
    """adjust_mcp excludes declined servers from proposal.

    install: False for the same reason as test_adjust_mcp_proposes_servers above.
    """
    adjust = load_script("features/pi/adjustments/adjust_mcp.py")
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {
            "filesystem": {"command": "npx server"},
            "github": {"command": "npx server-github"},
        },
        "mcp_declined": ["github"],
        "install": False,
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert "github" in result["notes"]


def test_adjust_hooks_no_pi(load_script):
    """adjust_hooks returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_hooks.py")
    context = {"config": {"agents": ["claude"]}, "install": False}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_hooks_with_pi(load_script, root, tmp_path):
    """adjust_hooks copies hook scripts into a temp target when pi in config."""
    adjust = load_script("features/pi/adjustments/adjust_hooks.py")
    target_dir = tmp_path / ".ai-badger"
    context = {
        "config": {"agents": ["pi"]},
        "framework_root": root,
        "feature_dir": root / "features" / "pi" / "adjustments",
        "target_dir": target_dir,
        "install": False,
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert len(result["files"]) > 0
    # Check at least one known hook was copied
    hook_files = [f for f in result["files"] if "hook" in f]
    assert len(hook_files) > 0


def test_adjust_task_no_pi(load_script):
    """adjust_task returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_task.py")
    context = {"config": {"agents": ["claude"]}, "skills": ["task"]}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_task_with_pi(load_script, root, tmp_path):
    """adjust_task copies pi_session_source.py into a temp target when pi in config."""
    adjust = load_script("features/pi/adjustments/adjust_task.py")
    target_dir = tmp_path / ".ai-badger"
    context = {
        "config": {"agents": ["pi"]},
        "framework_root": root,
        "feature_dir": root / "features" / "pi" / "adjustments",
        "target_dir": target_dir,
        "skills": ["task"],
    }
    result = adjust.adjust(context)
    assert result["applied"]
    assert "pi_session_source" in result["notes"]


def test_adjust_cron_no_pi(load_script):
    """adjust_cron returns unapplied when pi is not in config.agents."""
    adjust = load_script("features/pi/adjustments/adjust_cron.py")
    context = {"config": {"agents": ["claude"]}, "install": False}
    result = adjust.adjust(context)
    assert not result["applied"]


def test_adjust_cron_with_pi_no_cron_dir(load_script, tmp_path):
    """adjust_cron returns unapplied when cron directory missing."""
    adjust = load_script("features/pi/adjustments/adjust_cron.py")
    feature_dir = tmp_path
    context = {
        "config": {"agents": ["pi"]},
        "feature_dir": feature_dir,
        "install": False,
    }
    result = adjust.adjust(context)
    assert not result["applied"]


def test_pi_session_source_register(load_script):
    """pi_session_source.register() wires the pi source into tracker_lib."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    calls = []
    class FakeTrackerLib:
        @staticmethod
        def register_session_source(name, env_var, resolve, checkpoint, resume, delegation_usage):
            calls.append((name, env_var, resolve, checkpoint, resume, delegation_usage))

    session_source.register(FakeTrackerLib)
    assert len(calls) == 1
    assert calls[0][0] == "pi"
    assert calls[0][1] == "PI_SESSION_ID"


def test_pi_session_source_resolve(load_script, monkeypatch):
    """_resolve returns session id from env var."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    monkeypatch.setenv("PI_SESSION_ID", "test-session-123")
    result = session_source._resolve()
    assert result["sessionId"] == "test-session-123"


def test_pi_session_source_resolve_empty(load_script, monkeypatch):
    """_resolve returns empty dict when env var not set."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    monkeypatch.delenv("PI_SESSION_ID", raising=False)
    result = session_source._resolve()
    assert result == {}


def test_pi_session_source_zeroed_checkpoint(load_script):
    """_zeroed_checkpoint returns all-zero checkpoint."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    checkpoint = session_source._zeroed_checkpoint("sess-1")
    assert checkpoint["contextTokens"] == 0
    assert checkpoint["cumulative"]["inputTokens"] == 0
    assert checkpoint["cumulative"]["outputTokens"] == 0


# ---------------------------------------------------------------------------
# T1/T2/T3/T3b — the install path with install: True, the production default
# (scaffold.py:822 `install=not args.no_install`). Every test above this line runs the
# hooks/cron adjusters with install: False, so this branch — where the two shipped blockers
# (F1: missing adapter dir, F2a: missing run-job.ts) live — was never exercised.
# ---------------------------------------------------------------------------

def test_adjust_hooks_with_pi_install_copies_adapter(pi_user_extensions, root, tmp_path):
    """install: True copies the adapter extension (entry `index.ts`) into USER_EXTENSIONS_DIR.

    Reads from the real features/pi/adjustments/ tree (read-only); every write goes to the
    tmp_path USER_EXTENSIONS_DIR the fixture patched in. `index.ts` is pinned, not `adapter.ts`:
    pi discovers `~/.pi/agent/extensions/*/index.ts` and nothing else for a subdirectory
    extension (B-SHOULD-8).
    """
    target_dir = tmp_path / ".ai-badger"
    context = {
        "config": {"agents": ["pi"]},
        "framework_root": root,
        "feature_dir": root / "features" / "pi" / "adjustments",
        "target_dir": target_dir,
        "install": True,
    }

    before = _real_extension_state("ai-badger")

    result = pi_user_extensions.hooks.adjust(context)

    # Secondary observable (behaviour radius), checked first so a functional assertion
    # failing below can never mask a real-home leak: the fixture's redirect actually held.
    assert _real_extension_state("ai-badger") == before

    # Hook scripts still land in target_dir/hooks/ regardless of the adapter's fate.
    hook_files = [f for f in result["files"] if "hook" in f]
    assert len(hook_files) > 0

    adapter_entry = pi_user_extensions.hooks_dir / "index.ts"
    adapter_manifest = pi_user_extensions.hooks_dir / "package.json"
    assert adapter_entry.exists(), (
        f"pi discovers {pi_user_extensions.hooks_dir}/index.ts for a subdirectory extension; "
        f"nothing was installed there (features/pi/adjustments/adapter/ does not exist)"
    )
    assert adapter_manifest.exists()
    json.loads(adapter_manifest.read_text(encoding="utf-8"))  # must parse


def test_adjust_cron_with_pi_install_copies_extension_incl_run_job(
        pi_user_extensions, root):
    """install: True copies the cron extension, including `run-job.ts`, into USER_EXTENSIONS_DIR.

    `cron/index.ts` registers `Bun.cron(join(__dirname, "run-job.ts"), ...)` — a scheduled job
    referencing a script that does not ship is F2a. Reads from the real features/pi/cron/ tree;
    writes go to the tmp_path USER_EXTENSIONS_DIR the fixture patched in.
    """
    context = {
        "config": {"agents": ["pi"]},
        "feature_dir": root / "features" / "pi" / "adjustments",
        "install": True,
    }

    before = _real_extension_state("pi-cron")

    result = pi_user_extensions.cron.adjust(context)

    # Secondary observable, checked first for the same reason as the hooks test above.
    assert _real_extension_state("pi-cron") == before

    assert result["applied"]
    manifest = pi_user_extensions.cron_dir / "package.json"
    assert (pi_user_extensions.cron_dir / "index.ts").exists()
    assert manifest.exists()
    json.loads(manifest.read_text(encoding="utf-8"))  # must parse
    assert (pi_user_extensions.cron_dir / "run-job.ts").exists(), (
        "cron/index.ts registers Bun.cron() against run-job.ts, which does not ship — "
        "a scheduled job referencing a missing script (F2a)"
    )


def test_adjust_hooks_missing_adapter_dir_fails_loud(pi_user_extensions, tmp_path):
    """install: True with no adapter dir (and nothing else to install) fails loud, not silent.

    0.141.0 shipped `applied: True` with an empty install when the adapter dir was missing —
    the untested branch was the mainline. Nothing here touches the real framework tree: the
    fake framework_root/feature_dir have no features/common/hooks/ and no adapter/ either, so
    the hook-script copy also yields nothing and `applied` must go False (D5:
    `applied = bool(files or installed)`).
    """
    framework_root = tmp_path / "fake-framework"
    feature_dir = framework_root / "features" / "pi" / "adjustments"
    adapter_dir = feature_dir / "adapter"
    context = {
        "config": {"agents": ["pi"]},
        "framework_root": framework_root,
        "feature_dir": feature_dir,
        "target_dir": tmp_path / ".ai-badger",
        "install": True,
    }

    result = pi_user_extensions.hooks.adjust(context)

    assert result["files"] == []
    assert result["notes"].startswith("ERROR:"), result["notes"]
    assert str(adapter_dir) in result["notes"], result["notes"]
    assert result["applied"] is False


def test_adjust_cron_missing_cron_dir_fails_loud(pi_user_extensions, tmp_path):
    """install: True with no features/pi/cron/ dir fails loud, not silent (D5, cron's twin of T3).

    `adjust_cron._install_user_extension` carries the identical F6-shaped defect as
    adjust_hooks: `if not install or not cron_dir.is_dir(): return []`, then a generic,
    path-free "not found or empty" note.
    """
    feature_dir = tmp_path / "fake-framework" / "features" / "pi" / "adjustments"
    cron_dir = feature_dir.parent / "cron"
    context = {
        "config": {"agents": ["pi"]},
        "feature_dir": feature_dir,
        "install": True,
    }

    result = pi_user_extensions.cron.adjust(context)

    assert result["notes"].startswith("ERROR:"), result["notes"]
    assert str(cron_dir) in result["notes"], result["notes"]
    assert result["applied"] is False


# ---------------------------------------------------------------------------
# T4/T5 — source-contract (shape) assertions against features/pi/cron/index.ts. This is a
# TypeScript file pytest cannot execute; the TS lane owns behavioural coverage (bun test). These
# two tests pin the launchd/noAgent contract at the string level against the file this task's
# TS lane will rewrite — an honest ceiling, not a substitute for a live cron fire.
# ---------------------------------------------------------------------------

def test_cron_plist_template_has_scheduling_keys(root):
    """The launchd fallback plist must carry a scheduling key or it can never fire (F2b).

    Shape assertion on shipped TS source, not a live launchd probe (out of scope for pytest —
    OS-scheduler behaviour needs a real macOS host). Oracle: the launchd contract itself (a
    plist with neither StartCalendarInterval nor StartInterval never fires), not today's file.
    """
    source = (root / "features" / "pi" / "cron" / "index.ts").read_text(encoding="utf-8")

    assert "StartCalendarInterval" in source or "StartInterval" in source, (
        "the plist template has RunAtLoad=false and KeepAlive=false with no scheduling key at "
        "all — the job it writes can never fire"
    )
    # The scheduling key must be the only fire mechanism.
    assert "<false/>" in source  # RunAtLoad / KeepAlive stay false either way


def test_cron_registers_jobs_without_explicit_no_agent(root):
    """A cron job with no `noAgent` field is registered, not silently dropped (F5).

    `adjust_cron.py`'s docstring documents "no_agent=true by default", but `cron/index.ts`
    checks `if (job.noAgent)` — a bare truthiness check that skips every job that omits the
    field, i.e. the documented default in code that does the opposite of what it claims.
    Correct rule (task spec): schedulable = `jobs.filter(j => j.noAgent !== false)`.
    """
    source = (root / "features" / "pi" / "cron" / "index.ts").read_text(encoding="utf-8")

    assert "noAgent !== false" in source, (
        "no `!== false` comparison found — a job without an explicit `noAgent` field is not "
        "provably schedulable by default"
    )
    assert "if (job.noAgent)" not in source, (
        "the bare truthiness check is still present — it silently skips a field-less job "
        "instead of scheduling it by default"
    )


# ---------------------------------------------------------------------------
# T6 — pi's CLI resume contract. `--resume, -r` takes NO argument (interactive selector, pi
# 0.84.3 --help); resume-by-id is `pi -p --session <id>`.
# ---------------------------------------------------------------------------

def test_pi_session_source_resume_uses_session_flag(load_script):
    """The resume command pi_session_source builds must be one pi actually accepts."""
    session_source = load_script("features/pi/adjustments/pi_session_source.py")
    calls = []

    class FakeTrackerLib:
        @staticmethod
        def register_session_source(name, env_var, resolve, checkpoint, resume,
                                     delegation_usage):
            calls.append((name, env_var, resolve, checkpoint, resume, delegation_usage))

    session_source.register(FakeTrackerLib)
    resume = calls[0][4]
    command = resume("sess-abc-123")

    assert command == "pi -p --session sess-abc-123", command
    assert "--resume" not in command, (
        "--resume takes no argument (interactive selector); an id placed after it is a "
        "separate, silently-ignored argv token"
    )


# ---------------------------------------------------------------------------
# T8 — adjust_mcp's command splitting must follow POSIX/shlex tokenization, not `str.split()`.
# ---------------------------------------------------------------------------

def test_adjust_mcp_command_splits_with_shlex_quoted_argument(load_script):
    """A quoted argument containing a space stays one token (shlex semantics, not str.split())."""
    adjust_mcp = load_script("features/pi/adjustments/adjust_mcp.py")

    entry = adjust_mcp._server_entry(
        "filesystem", {"command": 'npx -y server "--flag value with space"'})

    assert entry["command"] == ["npx", "-y", "server", "--flag value with space"], (
        entry["command"]
    )


def test_adjust_mcp_command_with_unbalanced_quote_raises_value_error(load_script):
    """An unbalanced quote is a malformed declaration, not something to mangle silently."""
    adjust_mcp = load_script("features/pi/adjustments/adjust_mcp.py")

    with pytest.raises(ValueError):
        adjust_mcp._server_entry("filesystem", {"command": 'npx "--flag'})


# ---------------------------------------------------------------------------
# G1/G2 — pi_settings.py's read/merge/write contract, and the two adjustments (adjust_skills,
# adjust_mcp install=True) that write through it. Every test here writes to a tmp_path settings
# file; test_pi_settings_write_does_not_touch_real_home is the one that proves it.
# ---------------------------------------------------------------------------

def test_pi_settings_write_is_atomic_on_failure(load_script, tmp_path, monkeypatch):
    """A failed write leaves the original file intact and no temp file behind."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pi_settings.os, "replace", _boom)

    with pytest.raises(OSError):
        pi_settings.write_settings(path, {"theme": "dark", "skills": ["/x"]})

    # The original content survives untouched — no truncation, no partial write.
    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "dark"}
    # No leftover .tmp file: the finally-block cleanup ran.
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == [], leftovers


def test_pi_settings_merge_skills_path_creates_file_when_absent(load_script, tmp_path):
    """A missing settings.json (and its parent dirs) is created holding just the merged key."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    path = tmp_path / "pi" / "agent" / "settings.json"
    assert not path.exists()

    settings = pi_settings.merge_skills_path(pi_settings.load_settings(path), "/proj/skills")
    pi_settings.write_settings(path, settings)

    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == {"skills": ["/proj/skills"]}


def test_pi_settings_merge_skills_path_is_idempotent(load_script, tmp_path):
    """Merging the same path twice adds it once."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    path = tmp_path / "settings.json"

    for _ in range(2):
        settings = pi_settings.merge_skills_path(pi_settings.load_settings(path), "/proj/skills")
        pi_settings.write_settings(path, settings)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["skills"] == ["/proj/skills"]


def test_pi_settings_merge_preserves_unknown_keys(load_script, tmp_path):
    """lastChangelogVersion and theme — the real file's actual content — survive a merge."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"lastChangelogVersion": "0.140.0", "theme": "dark"}), encoding="utf-8")

    settings = pi_settings.merge_skills_path(pi_settings.load_settings(path), "/proj/skills")
    pi_settings.write_settings(path, settings)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["lastChangelogVersion"] == "0.140.0"
    assert data["theme"] == "dark"
    assert data["skills"] == ["/proj/skills"]


def test_adjust_skills_install_true_merges_skills_path(pi_settings_modules, tmp_path):
    """install: True merges the project's .ai-badger/skills/ path into settings.json."""
    context = {
        "config": {"agents": ["pi"]},
        "target_dir": tmp_path / ".ai-badger",
        "install": True,
    }

    result = pi_settings_modules.skills.adjust(context)

    assert result["applied"]
    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert str(tmp_path / ".ai-badger" / "skills") in data["skills"]


def test_adjust_skills_install_false_is_noop(pi_settings_modules, tmp_path):
    """install: False is a documented no-op, not an error — user-global state is left alone."""
    context = {
        "config": {"agents": ["pi"]},
        "target_dir": tmp_path / ".ai-badger",
        "install": False,
    }

    result = pi_settings_modules.skills.adjust(context)

    assert result["applied"] is False
    assert not pi_settings_modules.settings_path.exists()


def test_adjust_mcp_install_true_merges_into_settings(pi_settings_modules):
    """install: True merges declared servers into settings.json's mcp key."""
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    }

    result = pi_settings_modules.mcp.adjust(context)

    assert result["applied"]
    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert data["mcp"]["filesystem"]["command"] == ["npx", "-y", "server"]
    # The doc-honesty clause: pi core has no consumer for this key.
    assert "no consumer in pi core" in result["notes"]


def test_adjust_mcp_install_true_preserves_existing_settings(pi_settings_modules):
    """The merge is additive: other mcp entries and unknown top-level keys survive."""
    pi_settings_modules.settings_path.parent.mkdir(parents=True, exist_ok=True)
    pi_settings_modules.settings_path.write_text(json.dumps({
        "lastChangelogVersion": "0.100.0",
        "theme": "dark",
        "mcp": {"other-server": {"type": "remote", "url": "https://example.com"}},
    }), encoding="utf-8")

    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    }
    pi_settings_modules.mcp.adjust(context)

    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert data["lastChangelogVersion"] == "0.100.0"
    assert data["theme"] == "dark"
    assert "other-server" in data["mcp"]
    assert "filesystem" in data["mcp"]


def test_adjust_mcp_install_true_is_idempotent(pi_settings_modules):
    """Running the merge twice leaves a single, unduplicated entry for the same server."""
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    }

    pi_settings_modules.mcp.adjust(context)
    pi_settings_modules.mcp.adjust(context)

    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert list(data["mcp"].keys()) == ["filesystem"]


# ---------------------------------------------------------------------------
# G3 — real token checkpoints, read from the pi session JSONL
# (~/.pi/agent/sessions/--<cwd-with-slashes-as-dashes>--/<timestamp>_<uuid>.jsonl). Every test
# below patches SESSIONS_DIR to tmp_path; none may touch the real ~/.pi/agent/sessions/.
# ---------------------------------------------------------------------------

# A field-for-field copy of the real assistant `message` entry measured live this session
# against a logged-in pi 0.84.3 (openrouter) headless run — pi's own field names
# (input/output/cacheRead/cacheWrite/totalTokens), not Anthropic's. A future rename of these
# keys must fail this fixture's test, not silently sum to zero.
_REAL_USAGE_MESSAGE = {
    "type": "message",
    "id": "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba01",
    "parentId": "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba00",
    "timestamp": "2026-08-29T10-05-01-000Z",
    "message": {
        "role": "assistant",
        "usage": {
            "input": 449, "output": 23, "cacheRead": 701, "cacheWrite": 0, "reasoning": 20,
            "totalTokens": 1173,
            "cost": {
                "input": 0.000426, "output": 9.2e-05, "cacheRead": 0.000112,
                "cacheWrite": 0, "total": 0.000630,
            },
        },
    },
}


@pytest.fixture
def pi_sessions_dir(load_script, tmp_path, monkeypatch):
    """Load pi_session_source with SESSIONS_DIR redirected under tmp_path.

    Same idiom as pi_user_extensions above: SESSIONS_DIR is a module-level Path.home()-based
    constant, rebuilt once at import time, so the test patches the attribute on the module
    object load_script hands back — after load, before any call. No test using this fixture
    may read the real ~/.pi/agent/sessions/.
    """
    source = load_script("features/pi/adjustments/pi_session_source.py")
    sessions_dir = tmp_path / "pi" / "agent" / "sessions"
    monkeypatch.setattr(source, "SESSIONS_DIR", sessions_dir)
    return types.SimpleNamespace(source=source, sessions_dir=sessions_dir)


def _write_session_file(project_dir: Path, uuid: str, lines: list[dict],
                         timestamp: str = "2026-08-29T10-04-59-236Z") -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{timestamp}_{uuid}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def _project_dir(sessions_dir: Path, cwd: str) -> Path:
    return sessions_dir / ("--" + cwd.strip("/").replace("/", "-") + "--")


def test_pi_session_source_checkpoint_sums_real_shape_fixture(pi_sessions_dir, monkeypatch):
    """A multi-entry JSONL built from the real measured shape sums correctly across messages."""
    monkeypatch.setenv("PI_SESSION_ID", "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba0b")
    cwd = "/Users/arasz/RiderProjects/ai-badger"
    monkeypatch.chdir("/")  # source must not depend on the real process cwd for this test
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    second = dict(_REAL_USAGE_MESSAGE)
    second["message"] = dict(_REAL_USAGE_MESSAGE["message"])
    second["message"]["usage"] = dict(_REAL_USAGE_MESSAGE["message"]["usage"])
    second["message"]["usage"]["input"] = 100
    second["message"]["usage"]["output"] = 50
    second["message"]["usage"]["cacheRead"] = 200
    second["message"]["usage"]["cacheWrite"] = 10
    lines = [
        {"type": "session", "version": 1, "id": "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba0b",
         "timestamp": "2026-08-29T10-04-59-236Z", "cwd": cwd},
        {"type": "model_change", "id": "x", "parentId": None,
         "timestamp": "2026-08-29T10-04-59-300Z", "provider": "openrouter",
         "modelId": "anthropic/claude-sonnet-4.5"},
        {"type": "thinking_level_change", "id": "y", "parentId": "x",
         "timestamp": "2026-08-29T10-04-59-400Z", "level": "medium"},
        _REAL_USAGE_MESSAGE,
        second,
    ]
    _write_session_file(project_dir, "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba0b", lines)

    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd(
        "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba0b", cwd)

    assert checkpoint["cumulative"]["inputTokens"] == 449 + 100
    assert checkpoint["cumulative"]["outputTokens"] == 23 + 50
    assert checkpoint["cumulative"]["cacheReadTokens"] == 701 + 200
    assert checkpoint["cumulative"]["cacheCreationTokens"] == 0 + 10
    assert checkpoint["assistantMessages"] == 2


def test_pi_session_source_checkpoint_ignores_entries_without_usage(pi_sessions_dir):
    cwd = "/proj"
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    lines = [
        {"type": "session", "id": "sess-1", "timestamp": "t", "cwd": cwd},
        {"type": "message", "id": "m1", "parentId": None, "timestamp": "t",
         "message": {"role": "user", "content": "hi"}},
        _REAL_USAGE_MESSAGE,
    ]
    _write_session_file(project_dir, "sess-1", lines)

    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd("sess-1", cwd)

    assert checkpoint["assistantMessages"] == 1
    assert checkpoint["cumulative"]["inputTokens"] == 449


def test_pi_session_source_checkpoint_skips_malformed_line_and_sums_rest(pi_sessions_dir):
    cwd = "/proj"
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    project_dir.mkdir(parents=True)
    path = project_dir / "t_sess-2.jsonl"
    good = json.dumps(_REAL_USAGE_MESSAGE)
    path.write_text(good + "\n" + "{not valid json\n" + good + "\n", encoding="utf-8")

    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd("sess-2", cwd)

    assert checkpoint["assistantMessages"] == 2
    assert checkpoint["cumulative"]["inputTokens"] == 449 * 2


def test_pi_session_source_checkpoint_missing_dir_yields_zeroes(pi_sessions_dir):
    """SESSIONS_DIR itself does not exist at all."""
    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd("no-such-session", "/nowhere")

    assert checkpoint["assistantMessages"] == 0
    assert checkpoint["cumulative"] == {
        "inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0, "cacheCreationTokens": 0,
    }


def test_pi_session_source_checkpoint_missing_file_yields_zeroes(pi_sessions_dir):
    """The project directory exists but no file's uuid suffix matches the session id."""
    cwd = "/proj"
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    _write_session_file(project_dir, "other-uuid", [_REAL_USAGE_MESSAGE])

    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd("does-not-match", cwd)

    assert checkpoint["assistantMessages"] == 0
    assert checkpoint["cumulative"]["inputTokens"] == 0


def test_pi_session_source_checkpoint_empty_file_yields_zeroes(pi_sessions_dir):
    cwd = "/proj"
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    _write_session_file(project_dir, "sess-empty", [])

    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd("sess-empty", cwd)

    assert checkpoint["assistantMessages"] == 0


def test_pi_session_source_finds_right_file_by_uuid_suffix_among_several(pi_sessions_dir):
    """Several session files sit in one project directory; the id picks the matching one."""
    cwd = "/proj"
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    other = dict(_REAL_USAGE_MESSAGE)
    other["message"] = dict(_REAL_USAGE_MESSAGE["message"])
    other["message"]["usage"] = dict(_REAL_USAGE_MESSAGE["message"]["usage"])
    other["message"]["usage"]["input"] = 999999
    _write_session_file(project_dir, "aaaaaaaa-0000-0000-0000-000000000000", [other],
                         timestamp="2026-08-29T09-00-00-000Z")
    _write_session_file(project_dir, "01a04cfa-c9e4-7fa0-a78c-96f9cb41ba0b",
                         [_REAL_USAGE_MESSAGE], timestamp="2026-08-29T10-04-59-236Z")

    # Partial/prefix match: pi's own --session <path|id> accepts a partial UUID (measured,
    # pi 0.84.3 --help); a prefix of the real file's uuid must resolve to that file, not the
    # other one sitting alongside it.
    checkpoint = pi_sessions_dir.source._checkpoint_for_cwd("01a04cfa-c9e4", cwd)

    assert checkpoint["cumulative"]["inputTokens"] == 449


def test_pi_session_source_zeroed_checkpoint_shape_matches_real_checkpoint_shape(pi_sessions_dir):
    """The zeroes fallback and the real-data path return the exact same key set."""
    zeroed = pi_sessions_dir.source._zeroed_checkpoint("sess-1")
    real = pi_sessions_dir.source._checkpoint_for_cwd("no-such-session", "/nowhere")

    assert set(zeroed) == set(real)
    assert set(zeroed["cumulative"]) == set(real["cumulative"])


def test_pi_session_source_checkpoint_uses_session_env_and_own_cwd(pi_sessions_dir, monkeypatch):
    """The wired `checkpoint` lambda reads PI_SESSION_ID and the process cwd, end to end."""
    cwd = str(Path.cwd())
    project_dir = _project_dir(pi_sessions_dir.sessions_dir, cwd)
    _write_session_file(project_dir, "wired-session-1", [_REAL_USAGE_MESSAGE])

    calls = []

    class FakeTrackerLib:
        @staticmethod
        def register_session_source(name, env_var, resolve, checkpoint, resume,
                                     delegation_usage):
            calls.append((name, env_var, resolve, checkpoint, resume, delegation_usage))

    pi_sessions_dir.source.register(FakeTrackerLib)
    checkpoint_fn = calls[0][3]

    result = checkpoint_fn({"sessionId": "wired-session-1"})

    assert result["cumulative"]["inputTokens"] == 449
    assert result["assistantMessages"] == 1


def test_pi_settings_write_does_not_touch_real_home(pi_settings_modules):
    """The fixture's redirect actually held: the real settings.json is untouched by G1/G2.

    This suite has leaked writes into the real $HOME before (see conftest's REAL_HOME /
    REAL_WRITE_LOG machinery for the general guard); this test asserts the specific case G1/G2
    introduce — a settings.json merge — leaves the developer's real file exactly as it was.
    """
    real_settings = _REAL_HOME / ".pi" / "agent" / "settings.json"
    before = real_settings.read_bytes() if real_settings.exists() else None

    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    }
    pi_settings_modules.mcp.adjust(context)
    pi_settings_modules.skills.adjust({
        "config": {"agents": ["pi"]},
        "target_dir": Path("/tmp/does-not-matter/.ai-badger"),
        "install": True,
    })

    after = real_settings.read_bytes() if real_settings.exists() else None
    assert before == after