"""Tests for pi agent adjustments: MCP, hooks, task."""
# pylint: disable=protected-access,redefined-outer-name  # module internals + fixture reuse; see pyproject.toml
from __future__ import annotations

import json
import os
import types
from pathlib import Path

import pytest

from scaffold_helpers import _config

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
    """Load adjust_hooks with USER_EXTENSIONS_DIR redirected under tmp_path.

    ``USER_EXTENSIONS_DIR`` is a module-level ``Path.home()``-based constant in the module;
    conftest's session ``$HOME`` redirect is the floor, but the constant is only rebuilt once,
    at import time, so a test must patch the attribute on the module object it actually holds
    (``load_script`` builds a fresh module per call) — patched *after* load, *before* any
    ``adjust()`` call. No test using this fixture may write to the real
    ``~/.pi/agent/extensions/``. (The cron extension was removed from this framework in the
    minimal-pi-layer split; its extension now lives canonically in pi-badger-integration.)
    """
    hooks = load_script("features/pi/adjustments/adjust_hooks.py")

    hooks_dir = tmp_path / "pi" / "agent" / "extensions" / "ai-badger"
    monkeypatch.setattr(hooks, "USER_EXTENSIONS_DIR", hooks_dir)

    return types.SimpleNamespace(hooks=hooks, hooks_dir=hooks_dir)


@pytest.fixture
def pi_settings_modules(load_script, tmp_path, monkeypatch):
    """Load adjust_skills and adjust_mcp with pi_settings.SETTINGS_PATH redirected to tmp_path.

    Both modules do ``import pi_settings`` after inserting their own directory onto
    ``sys.path``; Python's import cache means that resolves to one shared module object no
    matter which of the two files triggers the first import, so patching the attribute on
    either module's ``pi_settings`` reference redirects both.

    The removal adjustments are additionally gated on per-extension capability markers under
    ~/.pi/agent/extensions/ (plan M5, R8+R9): adjust_mcp on the pi-mcp-tools fork's
    project-scope marker, adjust_skills on the installed adapter's resources_discover marker.
    The fixture patches those module constants to tmp_path copies and CREATES the files, so
    the default shape is gate-open (the removal path runs); a gate-closed case unlinks one
    explicitly. Raising=True patches: a marker-constant rename must fail here loudly, not
    silently leave these tests gated off (and thus vacuous).

    No test using this fixture may write to the real ``~/.pi/agent/settings.json`` or to the
    real ``~/.pi/agent/extensions/`` tree.
    """
    skills = load_script("features/pi/adjustments/adjust_skills.py")
    mcp = load_script("features/pi/adjustments/adjust_mcp.py")

    settings_path = tmp_path / "pi" / "agent" / "settings.json"
    monkeypatch.setattr(skills.pi_settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(mcp.pi_settings, "SETTINGS_PATH", settings_path)

    fork_marker = (tmp_path / "pi" / "agent" / "extensions" / "pi-mcp-tools" /
                   ".ai-badger-capability-project-scope-mcp")
    adapter_marker = (tmp_path / "pi" / "agent" / "extensions" / "ai-badger" /
                      ".ai-badger-capability-resources-discover")
    monkeypatch.setattr(mcp, "CAPABILITY_MARKER", fork_marker)
    monkeypatch.setattr(skills, "CAPABILITY_MARKER", adapter_marker)
    fork_marker.parent.mkdir(parents=True, exist_ok=True)
    fork_marker.touch()
    adapter_marker.parent.mkdir(parents=True, exist_ok=True)
    adapter_marker.touch()

    return types.SimpleNamespace(skills=skills, mcp=mcp, settings_path=settings_path,
                                 fork_marker=fork_marker, adapter_marker=adapter_marker)


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
    """adjust_mcp (--no-install) prints a REMOVAL proposal, not a merge snippet.

    install: False — this test exercises the printed-proposal path specifically; the removal
    path (install=True) has its own tests under pi_settings_modules, which monkeypatch
    pi_settings.SETTINGS_PATH so nothing here can reach the real home directory.

    The fork reads the project .mcp.json directly (plan M5), so the global 'mcp' key is
    user-owned fallback: the proposal this adjustment prints under --no-install is what a
    subsequent install run would REMOVE from settings.json, never what it would merge in.
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
    assert "remove" in result["notes"], (
        f"--no-install must propose a removal (the fork reads .mcp.json itself); got: "
        f"{result['notes']!r}")


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
# T1/T2/T3 — the install path with install: True, the production default
# (scaffold.py:822 `install=not args.no_install`). Every test above this line runs the
# hooks adjuster with install: False, so this branch — where the shipped blocker
# (F1: missing adapter dir) lives — was never exercised.
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


def test_adjust_skills_install_true_removes_skills_path(pi_settings_modules, tmp_path):
    """install: True removes this project's .ai-badger/skills/ path from settings.json.

    Flipped from merge to removal (plan M5/D3): the adapter's resources_discover now
    contributes the project skills path itself, so the settings.json entry is legacy scaffold
    state — the adjustment migrates it away. It removes exactly this project's path and
    nothing else: other projects' paths, user entries and unknown keys survive.
    """
    skills_dir = str(tmp_path / ".ai-badger" / "skills")
    pi_settings_modules.settings_path.parent.mkdir(parents=True, exist_ok=True)
    pi_settings_modules.settings_path.write_text(json.dumps({
        "theme": "dark",
        "skills": ["/other-project/.ai-badger/skills", skills_dir],
    }), encoding="utf-8")

    context = {
        "config": {"agents": ["pi"]},
        "target_dir": tmp_path / ".ai-badger",
        "install": True,
    }

    result = pi_settings_modules.skills.adjust(context)

    assert result["applied"]
    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert skills_dir not in data["skills"]
    assert data["skills"] == ["/other-project/.ai-badger/skills"], data["skills"]
    assert data["theme"] == "dark"


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


def test_adjust_mcp_install_true_removes_shape_matched_entries(pi_settings_modules, tmp_path):
    """install: True removes exactly this project's declared entries from settings.json's mcp.

    Flipped from merge to removal (plan M5/D3): the fork reads the project .mcp.json itself,
    so a re-scaffold migrates the global entries away. Removal is shape-aware: only entries
    matching what this scaffold would write today are removed; a non-declared user entry and
    unknown top-level keys are preserved, and nothing new is written.
    """
    mcp = pi_settings_modules.mcp
    declarations = {
        "filesystem": {"command": "npx -y server-fs"},
        "hermes": {"command": "npx -y hermes-mcp"},
    }
    generated = {name: mcp._server_entry(name, srv) for name, srv in declarations.items()}
    pi_settings_modules.settings_path.parent.mkdir(parents=True, exist_ok=True)
    pi_settings_modules.settings_path.write_text(json.dumps({
        "lastChangelogVersion": "0.100.0",
        "theme": "dark",
        "mcp": {
            "filesystem": generated["filesystem"],
            "hermes": generated["hermes"],
            "my-own-server": {"type": "remote", "url": "https://example.com"},
        },
    }), encoding="utf-8")

    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": declarations,
        "mcp_declined": [],
        "install": True,
    }

    result = pi_settings_modules.mcp.adjust(context)

    assert result["applied"]
    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert "filesystem" not in data.get("mcp", {})
    assert "hermes" not in data.get("mcp", {})
    # User-owned entries and unknown keys survive; nothing new is written.
    assert data["mcp"] == {"my-own-server": {"type": "remote", "url": "https://example.com"}}
    assert data["lastChangelogVersion"] == "0.100.0"
    assert data["theme"] == "dark"


def test_adjust_mcp_install_true_preserves_existing_settings(pi_settings_modules):
    """Removal is surgical: other mcp entries and unknown top-level keys survive."""
    pi_settings_modules.settings_path.parent.mkdir(parents=True, exist_ok=True)
    pi_settings_modules.settings_path.write_text(json.dumps({
        "lastChangelogVersion": "0.100.0",
        "theme": "dark",
        "mcp": {
            "other-server": {"type": "remote", "url": "https://example.com"},
            "filesystem": {
                "enabled": True, "toolPrefix": "mcp_filesystem", "type": "local",
                "command": ["npx", "-y", "server"],
            },
        },
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
    assert "filesystem" not in data["mcp"]


def test_adjust_mcp_removal_is_idempotent(pi_settings_modules):
    """Running the removal twice leaves the same end state — the second run removes nothing."""
    _seed_settings(
        pi_settings_modules.settings_path,
        mcp={"filesystem": {
            "enabled": True, "toolPrefix": "mcp_filesystem", "type": "local",
            "command": ["npx", "-y", "server"],
        }},
        theme="dark",
    )
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    }

    pi_settings_modules.mcp.adjust(context)
    after_first = pi_settings_modules.settings_path.read_text(encoding="utf-8")
    pi_settings_modules.mcp.adjust(context)

    assert pi_settings_modules.settings_path.read_text(encoding="utf-8") == after_first
    data = json.loads(after_first)
    assert data.get("mcp", {}) == {}
    assert data["theme"] == "dark"


# ---------------------------------------------------------------------------
# M5/R10 — the shape matcher. Removal is keyed to what THIS scaffold would write today
# (regenerate via _server_entry, deep-equal the shape fields, command as shlex-split or
# literal, tolerating the historical str.split→shlex drift c7d0d528). A same-named entry
# that does not match is a user edit: warn-and-leave, never touched.
# ---------------------------------------------------------------------------

def _seed_settings(settings_path, mcp=None, skills=None, **extra):
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(extra)
    if mcp is not None:
        data["mcp"] = mcp
    if skills is not None:
        data["skills"] = skills
    settings_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def test_adjust_mcp_removal_shape_matched_removed_drifted_warned_and_left(
        pi_settings_modules, tmp_path):
    """Matching entries go; the historical drift form goes; a user-edited entry stays."""
    mcp = pi_settings_modules.mcp
    drifted_declaration = {"command": 'npx -y server "--flag value with space"'}
    generated_drifted = mcp._server_entry("graph", drifted_declaration)
    # c7d0d528: the scaffold once tokenized with str.split(), so a quoted arg landed as
    # several tokens. That historical shape is scaffold-owned and must be removed.
    historical_split = dict(generated_drifted)
    historical_split["command"] = 'npx -y server "--flag value with space"'.split()

    _seed_settings(
        pi_settings_modules.settings_path,
        mcp={
            "filesystem": mcp._server_entry("filesystem", {"command": "npx -y server-fs"}),
            "graph": historical_split,
            "string-command": {"enabled": True, "toolPrefix": "mcp_string-command",
                               "type": "local", "command": "npx -y string-srv"},
            "user-edited": {**generated_drifted, "cwd": "/somewhere/else"},
            "my-own-server": {"type": "remote", "url": "https://example.com"},
        },
        lastChangelogVersion="0.100.0",
    )
    context = {
        "config": {"agents": ["pi"]},
        "mcp_declarations": {
            "filesystem": {"command": "npx -y server-fs"},
            "graph": drifted_declaration,
            "string-command": {"command": "npx -y string-srv"},
            "user-edited": drifted_declaration,
        },
        "mcp_declined": [],
        "install": True,
    }

    result = pi_settings_modules.mcp.adjust(context)

    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert "filesystem" not in data["mcp"]
    assert "graph" not in data["mcp"], "historical str.split drift must be removed"
    assert "string-command" not in data["mcp"], "a literal string command must be removed"
    assert "user-edited" in data["mcp"], "a drifted same-named entry is a user edit — left"
    assert data["mcp"]["user-edited"]["cwd"] == "/somewhere/else"
    assert "my-own-server" in data["mcp"], "non-declared entries are never touched"
    assert data["lastChangelogVersion"] == "0.100.0"
    # The report names what was left behind, so the drift is visible in scaffold notes.
    assert "user-edited" in result["notes"]


def test_adjust_mcp_removal_of_drifted_entry_writes_nothing(pi_settings_modules):
    """When every declared entry is drifted, nothing is written — byte-identical file."""
    mcp = pi_settings_modules.mcp
    declaration = {"command": "npx -y server"}
    user_entry = {**mcp._server_entry("filesystem", declaration), "env": {"TOKEN": "x"}}
    _seed_settings(pi_settings_modules.settings_path, mcp={"filesystem": user_entry})
    before = pi_settings_modules.settings_path.read_bytes()

    pi_settings_modules.mcp.adjust({
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    })

    assert pi_settings_modules.settings_path.read_bytes() == before


def test_adjust_mcp_removal_writes_nothing_new_when_settings_absent(pi_settings_modules):
    """No settings.json and nothing matching: the removal creates no file, adds no key."""
    assert not pi_settings_modules.settings_path.exists()

    result = pi_settings_modules.mcp.adjust({
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    })

    assert result["applied"]
    assert not pi_settings_modules.settings_path.exists(), "a removal must never create settings"


def test_adjust_mcp_removal_write_is_atomic_on_failure(pi_settings_modules, monkeypatch):
    """Mirror of test_pi_settings_write_is_atomic_on_failure, through the adjustment: a failed
    replace leaves the original settings.json intact with no temp file behind."""
    pi_settings = pi_settings_modules.mcp.pi_settings
    _seed_settings(
        pi_settings_modules.settings_path,
        mcp={"filesystem": {
            "enabled": True, "toolPrefix": "mcp_filesystem", "type": "local",
            "command": ["npx", "-y", "server"],
        }},
        theme="dark",
    )

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pi_settings.os, "replace", _boom)

    dir_before = {p.name for p in pi_settings_modules.settings_path.parent.iterdir()}

    with pytest.raises(OSError):
        pi_settings_modules.mcp.adjust({
            "config": {"agents": ["pi"]},
            "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
            "mcp_declined": [],
            "install": True,
        })

    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert "filesystem" in data["mcp"] and data["theme"] == "dark"
    # No leftover .tmp file: the finally-block cleanup ran (the fixture's extensions/ dir for
    # the capability markers is pre-existing, so compare against the before-snapshot).
    dir_after = {p.name for p in pi_settings_modules.settings_path.parent.iterdir()}
    assert dir_after == dir_before, dir_after - dir_before


# ---------------------------------------------------------------------------
# M5/R8/R9 — per-extension capability-marker gates. adjust_mcp gates on the pi-mcp-tools
# fork's project-scope marker; adjust_skills gates on the installed adapter's
# resources_discover marker. Marker absent ⇒ skip-with-warning, nothing removed (an old
# fork/adapter still needs the global entries — removing them would strand the machine).
# The gates are per-extension on purpose (R9): one shared gate would strand pre-P2 machines'
# skills even with a project-scope-capable fork installed, and vice versa.
# ---------------------------------------------------------------------------

def test_adjust_mcp_removal_gated_on_fork_capability_marker(pi_settings_modules):
    """Fork marker absent ⇒ warn-and-leave: the global entries stay for the old fork."""
    pi_settings_modules.fork_marker.unlink()
    before = _seed_settings(
        pi_settings_modules.settings_path,
        mcp={"filesystem": {
            "enabled": True, "toolPrefix": "mcp_filesystem", "type": "local",
            "command": ["npx", "-y", "server"],
        }},
    )

    result = pi_settings_modules.mcp.adjust({
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    })

    assert result["applied"] is False
    assert "pi-mcp-tools" in result["notes"]
    assert json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8")) == before


def test_adjust_mcp_removal_gate_is_per_extension_fork_marker_only(pi_settings_modules):
    """The adapter's marker is irrelevant to mcp removal (R9: the gate is per-extension)."""
    pi_settings_modules.adapter_marker.unlink()

    result = pi_settings_modules.mcp.adjust({
        "config": {"agents": ["pi"]},
        "mcp_declarations": {"filesystem": {"command": "npx -y server"}},
        "mcp_declined": [],
        "install": True,
    })

    assert result["applied"]


def test_adjust_skills_removal_gated_on_adapter_capability_marker(pi_settings_modules):
    """Adapter marker absent ⇒ warn-and-leave: an old adapter cannot contribute the project
    skills path, so removing the settings entry would strand the project's skills."""
    pi_settings_modules.adapter_marker.unlink()
    before = _seed_settings(
        pi_settings_modules.settings_path,
        skills=["/proj/.ai-badger/skills"],
    )

    result = pi_settings_modules.skills.adjust({
        "config": {"agents": ["pi"]},
        "target_dir": pi_settings_modules.settings_path.parent / "does-not-matter",
        "install": True,
    })

    assert result["applied"] is False
    assert "ai-badger" in result["notes"]
    assert json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8")) == before


def test_adjust_skills_removal_gate_is_per_extension_adapter_marker_only(pi_settings_modules):
    """The fork's marker is irrelevant to skills removal (R9: the gate is per-extension)."""
    pi_settings_modules.fork_marker.unlink()
    target_dir = pi_settings_modules.settings_path.parent / "proj" / ".ai-badger"
    _seed_settings(pi_settings_modules.settings_path,
                   skills=[str(target_dir / "skills")])

    result = pi_settings_modules.skills.adjust({
        "config": {"agents": ["pi"]},
        "target_dir": target_dir,
        "install": True,
    })

    assert result["applied"]
    data = json.loads(pi_settings_modules.settings_path.read_text(encoding="utf-8"))
    assert data["skills"] == []


# ---------------------------------------------------------------------------
# M5 — pi_settings.py removal helpers: same contract as the merge helpers (atomic write,
# idempotent, unknown keys preserved), plus the shape-matcher report (removed/warned).
# ---------------------------------------------------------------------------

def test_pi_settings_remove_mcp_servers_reports_removed_warned_absent(load_script):
    """Matching entries are removed and reported; drifted ones are warned; absent names ignored."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    settings = {
        "theme": "dark",
        "mcp": {
            "matching": {"enabled": True, "toolPrefix": "mcp_matching", "type": "local",
                         "command": ["npx", "-y", "server"]},
            "drifted": {"enabled": True, "toolPrefix": "mcp_drifted", "type": "local",
                        "command": ["npx", "-y", "server", "--user-flag"]},
        },
    }
    # Both names are declared this run; 'drifted' regenerates to a different shape than the
    # installed entry (the user's --user-flag edit), so it warns instead of being removed.
    generated = {
        "matching": {"enabled": True, "toolPrefix": "mcp_matching", "type": "local",
                     "command": ["npx", "-y", "server"]},
        "drifted": {"enabled": True, "toolPrefix": "mcp_drifted", "type": "local",
                    "command": ["npx", "-y", "server"]},
    }

    merged, removed, warned = pi_settings.remove_mcp_servers(settings, generated)

    assert removed == ["matching"]
    assert warned == ["drifted"]
    assert merged["mcp"] == {"drifted": settings["mcp"]["drifted"]}
    assert merged["theme"] == "dark"
    # The input is never mutated.
    assert "matching" in settings["mcp"]


def test_pi_settings_remove_mcp_servers_tolerates_historical_split_drift(load_script):
    """c7d0d528: an entry written with str.split() (quoted arg as several tokens) still matches
    the shlex-generated shape — re-joined and re-split it is the same command."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    settings = {"mcp": {"graph": {
        "enabled": True, "toolPrefix": "mcp_graph", "type": "local",
        "command": ["npx", "-y", "server", '"--flag', "value", 'with', 'space"'],
    }}}
    generated = {"graph": {
        "enabled": True, "toolPrefix": "mcp_graph", "type": "local",
        "command": ["npx", "-y", "server", "--flag value with space"],
    }}

    merged, removed, _warned = pi_settings.remove_mcp_servers(settings, generated)

    assert removed == ["graph"]
    assert merged.get("mcp") is None, "an emptied mcp key is removed, not left as {}"


def test_pi_settings_remove_mcp_servers_idempotent(load_script):
    """Removing twice: the second run removes and warns nothing."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    generated = {"matching": {"enabled": True, "toolPrefix": "mcp_matching", "type": "local",
                              "command": ["npx", "-y", "server"]}}
    settings = {"mcp": dict(generated)}

    once, removed_1, warned_1 = pi_settings.remove_mcp_servers(settings, generated)
    twice, removed_2, warned_2 = pi_settings.remove_mcp_servers(once, generated)

    assert removed_1 == ["matching"] and warned_1 == []
    assert removed_2 == [] and warned_2 == []
    assert twice == once


def test_pi_settings_remove_skills_path_removes_once_and_preserves_rest(load_script):
    """The project's path goes; other paths and unknown keys stay; a second run is a no-op."""
    pi_settings = load_script("features/pi/adjustments/pi_settings.py")
    settings = {"theme": "dark",
                "skills": ["/other/.ai-badger/skills", "/proj/.ai-badger/skills"]}

    merged, removed = pi_settings.remove_skills_path(settings, "/proj/.ai-badger/skills")
    again, removed_2 = pi_settings.remove_skills_path(merged, "/proj/.ai-badger/skills")

    assert removed is True and removed_2 is False
    assert merged["skills"] == ["/other/.ai-badger/skills"]
    assert merged["theme"] == "dark"
    assert again == merged


# ---------------------------------------------------------------------------
# M2 precondition pin — the fragile-case flip. pi trust-gates exactly
# .pi/{settings.json,extensions,skills,prompts,themes,SYSTEM.md,APPEND_SYSTEM.md} plus
# ancestor .agents/skills (trust-manager.js:8-17,150-166). A scaffolded project that writes
# any of those resolves UNTRUSTED headless (no trust.json, ask→false) and its project MCP
# servers + skills silently vanish. The scaffold must therefore write nothing into a
# project's .pi/ except .pi/agents/ (not on the trust list).
# ---------------------------------------------------------------------------

def test_scaffold_writes_no_trust_requiring_resource_into_project_pi(make_scaffolder):
    """Red the day the fragile case becomes common: a scaffold run must leave a project's
    .pi/ holding only .pi/agents/ — any other resource flips pi's trust resolution and
    silently disarms the project scope headless (plan M2)."""
    target = make_scaffolder.target
    make_scaffolder(config=_config(agents=["pi"]), skills=["task"]).run(
        generated_at="2026-08-30T00:00:00Z")

    pi_dir = target / ".pi"
    offenders = []
    if pi_dir.is_dir():
        for path in sorted(pi_dir.rglob("*")):
            rel = path.relative_to(pi_dir)
            if rel.parts and rel.parts[0] == "agents":
                continue
            offenders.append(rel.as_posix() + ("/" if path.is_dir() else ""))

    assert offenders == [], (
        "scaffold wrote pi-trust-requiring resource(s) into the project's .pi/: "
        f"{offenders} — these flip isProjectTrusted() to false headless and silently "
        "disarm project MCP + skills (plan M2's fragile case). Only .pi/agents/ may be "
        "written."
    )


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
    introduce — a settings.json REMOVAL pass (the flipped M5 behavior) — leaves the
    developer's real file exactly as it was, and leaves the two real extension trees the
    removal reads its capability markers from byte-identical too.
    """
    real_settings = _REAL_HOME / ".pi" / "agent" / "settings.json"
    before = real_settings.read_bytes() if real_settings.exists() else None
    before_ext = {name: _real_extension_state(name)
                  for name in ("ai-badger", "pi-mcp-tools")}

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
    after_ext = {name: _real_extension_state(name)
                 for name in ("ai-badger", "pi-mcp-tools")}
    assert after_ext == before_ext


# ---------------------------------------------------------------------------
# P1 — pi_session_source.delegation_usage: the delegation token record, parsed
# from ~/.pi/agent/subagent-logs/<runId>.jsonl — the R4 frozen cross-repo
# contract written by pi-badger-integration's delegation runner (consumed
# read-only). Every test here patches SUBAGENT_LOGS_DIR to tmp_path; none may
# read or write the real ~/.pi/agent/subagent-logs/. Log shapes are field-for-
# field copies of real delegation logs measured this session (d-1/d-5).
# ---------------------------------------------------------------------------

_DELEGATION_RUN_HEADER = {
    "type": "run",
    "runId": "d-1",
    "agent": "test-engineer",
    "persona": "test-engineer",
    "task": "implement the parser",
    "argv": ["/usr/local/bin/pi", "-p", "--mode", "json"],
    "cwd": "/proj",
    "pid": 30886,
    "startedAt": 1788123428467,
    "sessionId": "01a05458-65a6-75dc-a54b-3da2168521ec",
}


def _assistant_message_end(model="z-ai/glm-5.3-flash", input_=403, output=8485,
                           timestamp=1788122405772):
    """An assistant message_end event, field-for-field the shape pi 0.84.4 emits (d-1/d-5).

    usage.totalTokens is deliberately pi's own cache-INCLUSIVE count (input+output+cacheRead,
    = 80120 for the defaults — the real d-1 values), so any mutant that sums it instead of
    input+output produces a different number and fails.
    """
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "api": "openai-completions",
            "provider": "openrouter",
            "model": model,
            "usage": {
                "input": input_, "output": output, "cacheRead": 71232, "cacheWrite": 0,
                "reasoning": 3616, "totalTokens": input_ + output + 71232,
                "cost": {"input": 3.0225e-05, "output": 0.00212125,
                         "cacheRead": 0.00106848, "cacheWrite": 0, "total": 0.003219955},
            },
            "stopReason": "stop",
            "timestamp": timestamp,
            "responseId": "gen-1788122405-64HOwDFJfbuYgktM0Pm6",
        },
    }


def _write_delegation_log(logs_dir: Path, run_id: str, lines: list) -> Path:
    """Write one subagent log; str entries pass through verbatim (blank/malformed lines)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{run_id}.jsonl"
    text = "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines)
    path.write_text(text + "\n", encoding="utf-8")
    return path


@pytest.fixture
def pi_subagent_logs_dir(load_script, tmp_path, monkeypatch):
    """Load pi_session_source with SUBAGENT_LOGS_DIR redirected under tmp_path.

    Same idiom as pi_sessions_dir above: SUBAGENT_LOGS_DIR is a module-level Path.home()-based
    constant, rebuilt once at import time, so the test patches the attribute on the module
    object load_script hands back — after load, before any call. No test using this fixture
    may read or write the real ~/.pi/agent/subagent-logs/.
    """
    source = load_script("features/pi/adjustments/pi_session_source.py")
    logs_dir = tmp_path / "pi" / "agent" / "subagent-logs"
    monkeypatch.setattr(source, "SUBAGENT_LOGS_DIR", logs_dir)
    return types.SimpleNamespace(source=source, logs_dir=logs_dir)


def test_delegation_usage_happy_path_exit_settled_run(pi_subagent_logs_dir):
    """T1 — a settled run with two assistant turns returns the full record.

    Pins the whole record shape (totalTokens/model/apiCalls/at) in one equality: kills a
    stub that returns None or an empty dict, and any wrong key or value. totalTokens is the
    input+output sum (hermes parity), NOT pi's cache-inclusive usage.totalTokens.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-1", [
        dict(_DELEGATION_RUN_HEADER, runId="d-1"),
        _assistant_message_end(input_=100, output=23, timestamp=1788122400001),
        _assistant_message_end(input_=200, output=50, timestamp=1788122405000),
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-1")

    assert record == {
        "totalTokens": 100 + 23 + 200 + 50,
        "model": "z-ai/glm-5.3-flash",
        "apiCalls": 2,
        "at": 1788123491019,
    }


def test_delegation_usage_run_without_any_settled_marker_returns_none(pi_subagent_logs_dir):
    """T2 — header + usage events but neither exit nor agent_settled → None (run still live).

    Kills a parser that records mid-run: the M1 respec makes a settled marker mandatory.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-2", [
        dict(_DELEGATION_RUN_HEADER, runId="d-2"),
        _assistant_message_end(),
    ])

    assert pi_subagent_logs_dir.source._delegation_usage("d-2") is None


def test_delegation_usage_spawn_error_returns_none(pi_subagent_logs_dir):
    """T3 — spawnError means the child never ran: no record, not even a zeroed one."""
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-3", [
        dict(_DELEGATION_RUN_HEADER, runId="d-3"),
        {"type": "spawnError", "error": "pi: command not found"},
    ])

    assert pi_subagent_logs_dir.source._delegation_usage("d-3") is None


def test_delegation_usage_exit_with_signal_still_records_real_spend(pi_subagent_logs_dir):
    """T4 — a killed run's exit line (signal present) settles it: the tokens are real spend.

    Kills a completed-only filter (exitCode == 0 or signal-absent requirement) that would
    refuse exactly the aborted-spent runs cost recording exists for.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-4", [
        dict(_DELEGATION_RUN_HEADER, runId="d-4"),
        _assistant_message_end(input_=500, output=10),
        {"type": "exit", "exitCode": None, "signal": "SIGKILL", "endedAt": 1788123500000},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-4")

    assert record is not None
    assert record["totalTokens"] == 510
    assert record["at"] == 1788123500000


def test_delegation_usage_zero_total_returns_none(pi_subagent_logs_dir):
    """T5 — exit present but no usage events (the all-elided log) → None, not fabricated zeros."""
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-5", [
        dict(_DELEGATION_RUN_HEADER, runId="d-5"),
        {"type": "tee-elided", "droppedBytes": 5542477},
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])

    assert pi_subagent_logs_dir.source._delegation_usage("d-5") is None


def test_delegation_usage_skips_malformed_line_and_sums_rest(pi_subagent_logs_dir):
    """T6 — a malformed line between good lines is skipped individually, not fatal.

    Same tolerance as _sum_usage: one bad line must not zero out or abort the whole log.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-6", [
        dict(_DELEGATION_RUN_HEADER, runId="d-6"),
        "{not valid json",
        _assistant_message_end(input_=10, output=5, timestamp=1788122400001),
        "} also bad {",
        _assistant_message_end(input_=7, output=3, timestamp=1788122405000),
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-6")

    assert record is not None
    assert record["totalTokens"] == 25
    assert record["apiCalls"] == 2


def test_delegation_usage_tee_elided_marker_parsed_and_ignored(pi_subagent_logs_dir):
    """T7 — the byte-cap marker is a legal unknown type: parse past it, count tail usage.

    The elided middle's usage lines legitimately don't sum; usage around the marker must.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-7", [
        dict(_DELEGATION_RUN_HEADER, runId="d-7"),
        _assistant_message_end(input_=10, output=5, timestamp=1788122400001),
        {"type": "tee-elided", "droppedBytes": 5542477},
        _assistant_message_end(input_=7, output=3, timestamp=1788122405000),
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-7")

    assert record is not None
    assert record["totalTokens"] == 25
    assert record["apiCalls"] == 2


@pytest.mark.parametrize("bad_id", ["../d-1", "..", ""])
def test_delegation_usage_rejects_non_filename_ids_without_opening_target(
        pi_subagent_logs_dir, bad_id):
    """T8 — ids that are not bare filename components are refused, unread.

    A sentinel log holding real usage sits at the exact path a naive
    ``SUBAGENT_LOGS_DIR / f"{bad_id}.jsonl"`` join would open; the parser must return None
    and leave the sentinel byte-identical (path-traversal guard; real ids are d-<n>).
    """
    logs_dir = pi_subagent_logs_dir.logs_dir
    naive_target = logs_dir / f"{bad_id}.jsonl"
    naive_target.parent.mkdir(parents=True, exist_ok=True)
    naive_target.write_text("\n".join([
        json.dumps(dict(_DELEGATION_RUN_HEADER, runId="d-1")),
        json.dumps(_assistant_message_end()),
        json.dumps({"type": "exit", "exitCode": 0, "endedAt": 1788123491019}),
    ]) + "\n", encoding="utf-8")
    before = naive_target.read_bytes()

    assert pi_subagent_logs_dir.source._delegation_usage(bad_id) is None
    assert naive_target.read_bytes() == before


def test_delegation_usage_non_assistant_message_end_not_counted(pi_subagent_logs_dir):
    """T9 — role-blind summing is the bug: a non-assistant message_end never counts.

    The user-role event deliberately carries a usage block — the non-assistant × has-usage
    intersection the role check exists for; usage-presence alone must not admit it.
    """
    user_end_with_usage = {
        "type": "message_end",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input": 999999, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "timestamp": 1788122400000,
        },
    }
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-9", [
        dict(_DELEGATION_RUN_HEADER, runId="d-9"),
        user_end_with_usage,
        _assistant_message_end(input_=10, output=5),
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-9")

    assert record is not None
    assert record["totalTokens"] == 15
    assert record["apiCalls"] == 1


def test_delegation_usage_assistant_end_without_model_records_model_none(
        pi_subagent_logs_dir):
    """T10 — pi's model field is optional in loose streams: the record survives, model None."""
    event = _assistant_message_end(input_=10, output=5)
    del event["message"]["model"]
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-10", [
        dict(_DELEGATION_RUN_HEADER, runId="d-10"),
        event,
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-10")

    assert record is not None
    assert record["model"] is None
    assert record["totalTokens"] == 15


def test_delegation_usage_missing_dir_or_file_returns_none(pi_subagent_logs_dir):
    """T11 — machines without the extension have no logs dir at all: both misses → None.

    A missing dir is the pre-release state of every machine today; a raise there would
    crash the tracker's `subagent --delegation` flow instead of refusing cleanly.
    """
    assert pi_subagent_logs_dir.source._delegation_usage("d-1") is None  # dir absent

    pi_subagent_logs_dir.logs_dir.mkdir(parents=True)  # dir present, file absent
    assert pi_subagent_logs_dir.source._delegation_usage("d-404") is None


def test_delegation_usage_wired_through_register(pi_subagent_logs_dir):
    """T12 — register() hands tracker_lib the real parser, not the None stub.

    Mirrors test_pi_session_source_checkpoint_uses_session_env_and_own_cwd: the callable
    captured from register must resolve a delegation id through the (patched) logs dir
    end-to-end, killing a wiring that leaves `lambda delegation_id: None` in place.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-1", [
        dict(_DELEGATION_RUN_HEADER, runId="d-1"),
        _assistant_message_end(input_=10, output=5),
        {"type": "exit", "exitCode": 0, "endedAt": 1788123491019},
    ])
    calls = []

    class FakeTrackerLib:
        @staticmethod
        def register_session_source(name, env_var, resolve, checkpoint, resume,
                                     delegation_usage):
            calls.append((name, env_var, resolve, checkpoint, resume, delegation_usage))

    pi_subagent_logs_dir.source.register(FakeTrackerLib)

    assert calls[0][0] == "pi"
    assert calls[0][5]("d-1") == {
        "totalTokens": 15,
        "model": "z-ai/glm-5.3-flash",
        "apiCalls": 1,
        "at": 1788123491019,
    }


def test_delegation_usage_agent_settled_without_exit_line_records(pi_subagent_logs_dir):
    """T13 — the M1 witness: a TUI-aborted run (agent_settled, NO exit line) records.

    Field-for-field the real d-1.jsonl shape: run header, one assistant message_end with
    its real usage block, the bare agent_settled line, NO exit line, trailing blank line.
    settleAborted (delegation-runner.ts) writes no exit line, yet the aborted run's tokens
    are real spend — an exit-line-only settled policy refuses exactly this log. `at` falls
    back to the last assistant message_end.timestamp (epoch ms): there is no exit.endedAt.
    """
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-1", [
        dict(_DELEGATION_RUN_HEADER, runId="d-1", agent="architect", persona="architect",
             task="Author an implementation plan (no code changes)", startedAt=1788122400000),
        _assistant_message_end(input_=403, output=8485, timestamp=1788122405772),
        {"type": "agent_settled"},
        "",
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-1")

    assert record == {
        "totalTokens": 403 + 8485,
        "model": "z-ai/glm-5.3-flash",
        "apiCalls": 1,
        "at": 1788122405772,
    }

def test_delegation_usage_at_falls_back_to_header_started_at(pi_subagent_logs_dir):
    """T14 — the third leg of the `at` chain: no exit.endedAt (agent_settled only) and a
    message_end without a timestamp → the run header's startedAt. Defensive but contract-§6."""
    _write_delegation_log(pi_subagent_logs_dir.logs_dir, "d-2", [
        dict(_DELEGATION_RUN_HEADER, runId="d-2", agent="qa", persona="qa",
             task="t", startedAt=1788120000000),
        _assistant_message_end(input_=10, output=5, timestamp=None),
        {"type": "agent_settled"},
    ])

    record = pi_subagent_logs_dir.source._delegation_usage("d-2")

    assert record == {"totalTokens": 15, "model": "z-ai/glm-5.3-flash", "apiCalls": 1,
                      "at": 1788120000000}
