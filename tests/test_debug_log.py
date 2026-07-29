"""Debug audit logging: off by default, bounded, private, and never able to break a hook."""
from __future__ import annotations

import io
import json
import os
import stat
from pathlib import Path

import pytest


def _load(load_script, tmp_path, monkeypatch):
    """Load debug_log with its user-level paths redirected under tmp_path."""
    dl = load_script("features/common/hooks/debug_log.py")
    root = tmp_path / "debug"
    monkeypatch.setattr(dl, "DEBUG_DIR", root)
    monkeypatch.setattr(dl, "STATE_FILE", root / "state.json")
    monkeypatch.setattr(dl, "AUDIT_FILE", root / "audit.jsonl")
    monkeypatch.delenv(dl.DEBUG_ENV, raising=False)
    return dl


def _enable(dl, scope="user", project=None, expires_in=3600):
    dl.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "enabled": True,
        "scope": scope,
        "project": project,
        "expires_at": dl.iso(dl.now() + dl.timedelta(seconds=expires_in)),
    }
    dl.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _records(dl):
    if not dl.AUDIT_FILE.exists():
        return []
    return [json.loads(line) for line in dl.AUDIT_FILE.read_text(encoding="utf-8").splitlines()]


class TestWhereTheLogLands:
    """The sink is redirectable, so nothing under test writes into a real developer's log."""

    def test_it_defaults_to_the_users_home_directory(self, load_script, monkeypatch):
        monkeypatch.delenv("AI_BADGER_DEBUG_DIR", raising=False)

        dl = load_script("features/common/hooks/debug_log.py")

        assert dl.DEBUG_DIR == Path.home() / ".ai-badger" / "debug"
        assert dl.STATE_FILE == dl.DEBUG_DIR / "state.json"
        assert dl.AUDIT_FILE == dl.DEBUG_DIR / "audit.jsonl"

    def test_an_env_override_moves_the_whole_sink(self, load_script, tmp_path, monkeypatch):
        monkeypatch.setenv("AI_BADGER_DEBUG_DIR", str(tmp_path / "elsewhere"))

        dl = load_script("features/common/hooks/debug_log.py")
        _enable(dl)
        dl.log_event("some/hook", "start")

        assert dl.DEBUG_DIR == tmp_path / "elsewhere"
        assert len(_records(dl)) == 1

    def test_this_suite_never_resolves_the_real_users_sink(self, load_script):
        """The whole run is redirected; a green suite that writes the real log is not green."""
        dl = load_script("features/common/hooks/debug_log.py")

        assert dl.DEBUG_DIR != Path.home() / ".ai-badger" / "debug"


class TestOffByDefault:
    """Debug logging costs nothing and leaves nothing behind until switched on."""

    def test_no_state_file_means_no_record_and_no_directory(self, load_script, tmp_path,
                                                            monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)

        dl.log_event("some/hook", "start")

        assert not dl.AUDIT_FILE.exists()
        assert not dl.DEBUG_DIR.exists(), "a disabled logger must not create its own directory"

    def test_an_expired_window_stops_logging_without_a_timer(self, load_script, tmp_path,
                                                             monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl, expires_in=-1)

        dl.log_event("some/hook", "start")

        assert _records(dl) == []

    def test_the_env_override_forces_logging_on(self, load_script, tmp_path, monkeypatch):
        """For a one-off run where editing state is inconvenient."""
        dl = _load(load_script, tmp_path, monkeypatch)
        monkeypatch.setenv(dl.DEBUG_ENV, "1")

        dl.log_event("some/hook", "start")

        assert len(_records(dl)) == 1


class TestUserScopeIsTheDefault:
    """Debug is enabled across every project, not one — so scope defaults to user."""

    def test_user_scope_logs_from_any_directory(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl, scope="user")

        dl.log_event("some/hook", "start", project="/somewhere/else")

        assert len(_records(dl)) == 1

    def test_project_scope_ignores_other_projects(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl, scope="project", project="/work/mine")

        dl.log_event("some/hook", "start", project="/work/theirs")
        dl.log_event("some/hook", "start", project="/work/mine")

        assert [r[dl.KEY_PROJECT] for r in _records(dl)] == ["/work/mine"]


class TestRedactMode:
    """The query is the one field carrying user content; redaction drops only that field."""

    def test_the_query_field_is_recorded_by_default(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        monkeypatch.delenv(dl.REDACT_ENV, raising=False)

        dl.log_event("h", "hit", **{dl.KEY_QUERY: "sensitive text", "count": 3})

        record = _records(dl)[0]
        assert record[dl.KEY_QUERY] == "sensitive text"
        assert record["count"] == "3"

    def test_redact_drops_only_the_query_field(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        monkeypatch.setenv(dl.REDACT_ENV, "1")

        dl.log_event("h", "hit", **{dl.KEY_QUERY: "sensitive text", "count": 3})

        record = _records(dl)[0]
        assert dl.KEY_QUERY not in record
        assert record["count"] == "3"

    def test_the_redacted_text_never_touches_disk(self, load_script, tmp_path, monkeypatch):
        """Redaction happens at the point of writing, never as a post-process."""
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        monkeypatch.setenv(dl.REDACT_ENV, "1")

        dl.log_event("h", "hit", **{dl.KEY_QUERY: "super secret query text"})

        raw = dl.AUDIT_FILE.read_text(encoding="utf-8")
        assert "super secret" not in raw


class TestRecordContents:
    """Every record must answer: which code, which copy, where, doing what."""

    def test_the_framework_version_is_always_recorded(self, load_script, tmp_path, monkeypatch):
        """Version is what exposes a stale plugin running against a newer scaffold."""
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)

        dl.log_event("some/hook", "start")

        assert _records(dl)[0][dl.KEY_VERSION], "version must be present on every record"

    def test_component_and_event_are_recorded(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)

        dl.log_event("prompt-markers/user_prompt_hook", "skip")

        record = _records(dl)[0]
        assert record[dl.KEY_COMPONENT] == "prompt-markers/user_prompt_hook"
        assert record[dl.KEY_EVENT] == "skip"
        assert record[dl.KEY_TS]

    def test_optional_context_is_carried_when_known_and_omitted_when_not(self, load_script,
                                                                        tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)

        dl.log_event("h", "start", project="/p", session="abc123")
        dl.log_event("h", "start")

        with_context, without = _records(dl)
        assert with_context[dl.KEY_PROJECT] == "/p" and with_context[dl.KEY_SESSION] == "abc123"
        assert dl.KEY_SESSION not in without


class TestItCannotHurtTheHostHook:
    """A debug facility that can break what it observes is worse than none."""

    def test_an_unwritable_sink_does_not_raise(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        dl.AUDIT_FILE.parent.chmod(0o500)
        try:
            dl.log_event("some/hook", "start")  # must not raise
        finally:
            dl.AUDIT_FILE.parent.chmod(0o700)

    def test_unreadable_state_is_treated_as_disabled(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        dl.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        dl.STATE_FILE.write_text("{not json", encoding="utf-8")

        dl.log_event("some/hook", "start")

        assert _records(dl) == []


class TestBoundedAndPrivate:
    """The log says where someone works and what ran; it is not world-readable or unbounded."""

    def test_the_sink_is_owner_only(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)

        dl.log_event("some/hook", "start")

        assert stat.S_IMODE(os.stat(dl.AUDIT_FILE).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(dl.DEBUG_DIR).st_mode) == 0o700

    def test_the_log_is_trimmed_to_its_cap(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        monkeypatch.setattr(dl, "MAX_AUDIT_LINES", 5)
        _enable(dl)

        for i in range(9):
            dl.log_event("some/hook", "start", session=str(i))

        records = _records(dl)
        assert len(records) == 5
        assert [r[dl.KEY_SESSION] for r in records] == ["4", "5", "6", "7", "8"], "oldest go first"

    def test_every_record_is_exactly_one_parseable_line(self, load_script, tmp_path, monkeypatch):
        """Single-line appends are what keeps concurrent hooks from interleaving."""
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)

        dl.log_event("h", "start", detail="a\nb\nc")

        lines = dl.AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])


class TestHooksAreInstrumented:
    """The point of the feature: you can see that a hook ran, not just guess."""

    def _enable_for(self, dl, tmp_path, monkeypatch):
        for module in (dl,):
            monkeypatch.setattr(module, "DEBUG_DIR", tmp_path / "debug")
            monkeypatch.setattr(module, "STATE_FILE", tmp_path / "debug" / "state.json")
            monkeypatch.setattr(module, "AUDIT_FILE", tmp_path / "debug" / "audit.jsonl")
        _enable(dl)

    def test_session_start_records_that_it_ran(self, load_script, tmp_path, monkeypatch):
        hooks = load_script("features/common/hooks/ai_badger_hooks.py")
        dl = hooks.debug_log
        self._enable_for(dl, tmp_path, monkeypatch)
        monkeypatch.delenv(dl.DEBUG_ENV, raising=False)

        hooks.on_session_start_drift_notice(cwd=str(tmp_path))

        components = [r[dl.KEY_COMPONENT] for r in _records(dl)]
        assert any("session_start" in c for c in components), components

    def test_every_record_from_a_hook_carries_the_version(self, load_script, tmp_path,
                                                          monkeypatch):
        hooks = load_script("features/common/hooks/ai_badger_hooks.py")
        dl = hooks.debug_log
        self._enable_for(dl, tmp_path, monkeypatch)
        monkeypatch.delenv(dl.DEBUG_ENV, raising=False)

        hooks.on_session_start_drift_notice(cwd=str(tmp_path))

        assert all(r.get(dl.KEY_VERSION) for r in _records(dl))


class TestAScaffoldedProjectKnowsItsVersion:
    """A scaffold ships no VERSION file; without a fallback every record reads `unknown`."""

    def _scaffold(self, tmp_path, version="0.35.2"):
        scripts = tmp_path / "proj" / ".ai-badger" / "skills" / "s" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / ".ai-badger" / "manifest.json").write_text(
            json.dumps({"frameworkVersion": version}), encoding="utf-8")
        return scripts / "debug_log.py"

    def test_the_manifest_supplies_the_version_when_no_version_file_exists(
            self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)

        assert dl.framework_version(self._scaffold(tmp_path)) == "0.35.2"

    def test_the_hosts_own_version_file_cannot_masquerade_as_the_frameworks(
            self, load_script, tmp_path, monkeypatch):
        """A scaffolded repo may version itself; that number is not ai-badger's."""
        dl = _load(load_script, tmp_path, monkeypatch)
        start = self._scaffold(tmp_path)
        (tmp_path / "proj" / "VERSION").write_text("9.9.9", encoding="utf-8")

        assert dl.framework_version(start) == "0.35.2"

    def test_a_source_checkout_still_reads_its_version_file(self, load_script, tmp_path,
                                                             monkeypatch):
        """No manifest above it — a checkout of the framework itself."""
        dl = _load(load_script, tmp_path, monkeypatch)
        hooks = tmp_path / "src" / "features" / "common" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "VERSION").write_text("9.9.9", encoding="utf-8")

        assert dl.framework_version(hooks / "debug_log.py") == "9.9.9"

    def test_neither_present_is_still_the_sentinel(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        bare = tmp_path / "bare" / "scripts"
        bare.mkdir(parents=True, exist_ok=True)

        assert dl.framework_version(bare / "debug_log.py") == "unknown"


class TestARecordSaysWhichProjectItCameFrom:
    """An unattributed record pools into every project's analysis and skews all of them."""

    def test_the_environment_names_the_project(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/from/env")

        assert dl.resolve_project_root({"cwd": "/from/payload"}) == "/from/env"

    def test_the_payload_cwd_is_the_fallback(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

        assert dl.resolve_project_root({"cwd": "/from/payload"}) == "/from/payload"

    def test_neither_is_not_a_guess(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

        assert dl.resolve_project_root({}) is None


class TestEveryScaffoldedHookAttributesItsRecords:
    """`analyze` scopes by project; a hook that never says where it ran cannot be scoped."""

    HOOKS = [
        ("features/common/skills/prompt-markers/scripts/user_prompt_hook.py",
         {"prompt": "hint: check the cache"}),
        ("features/common/skills/task/scripts/session_start_hook.py",
         {"session_id": "s1", "source": "startup"}),
    ]

    def _run(self, load_script, tmp_path, monkeypatch, script, payload):
        hook = load_script(script)
        dl = hook.debug_log
        for attr, value in (("DEBUG_DIR", tmp_path / "debug"),
                            ("STATE_FILE", tmp_path / "debug" / "state.json"),
                            ("AUDIT_FILE", tmp_path / "debug" / "audit.jsonl")):
            monkeypatch.setattr(dl, attr, value)
        _enable(dl)
        monkeypatch.delenv(dl.DEBUG_ENV, raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({**payload,
                                                                 "cwd": str(tmp_path / "proj")})))
        try:
            hook.main()
        except SystemExit:
            pass
        return dl

    def test_each_hook_records_the_project_it_ran_in(self, load_script, tmp_path, monkeypatch):
        for script, payload in self.HOOKS:
            dl = self._run(load_script, tmp_path, monkeypatch, script, payload)
            records = _records(dl)
            assert records, f"{script} produced no record"
            assert all(r.get(dl.KEY_PROJECT) == str(tmp_path / "proj") for r in records), (
                f"{script} left records unattributed: {records}")
            dl.AUDIT_FILE.unlink()


class TestTheSuiteCannotWriteToTheRealLog:
    """A test that forgets to redirect the sink must still not touch the user's own log."""

    COPIES = ("features/common/hooks/debug_log.py",
              "features/common/skills/call-behaviorist/scripts/debug_log.py")

    def test_a_freshly_loaded_copy_points_away_from_the_real_home(self, load_script):
        from conftest import REAL_HOME  # pylint: disable=import-outside-toplevel

        for relpath in self.COPIES:
            sink = load_script(relpath).AUDIT_FILE
            assert REAL_HOME not in sink.parents, f"{relpath} would write to {sink}"

    def test_an_unredirected_write_never_reaches_the_real_home(self, load_script, monkeypatch):
        """The escape hatch is closed even with logging forced on and nothing patched.

        Asserts the contract, not the destination: two isolations are in force and either
        one satisfies it — `$AI_BADGER_DEBUG_DIR` wins, `$HOME` is the floor beneath it.
        """
        from conftest import REAL_HOME  # pylint: disable=import-outside-toplevel

        dl = load_script(self.COPIES[0])
        monkeypatch.setenv(dl.DEBUG_ENV, "1")

        dl.log_event("some/hook", "start")

        assert dl.AUDIT_FILE.exists(), "the write should have happened, just somewhere safe"
        assert REAL_HOME not in dl.AUDIT_FILE.parents, f"leaked to {dl.AUDIT_FILE}"


VENDORED_COPIES = (
    "features/common/skills/call-behaviorist/scripts/debug_log.py",
    "features/common/skills/commit-reminder/scripts/debug_log.py",
    "features/common/skills/mcp-index/scripts/debug_log.py",
    "features/common/skills/prompt-markers/scripts/debug_log.py",
    "features/common/skills/task/scripts/debug_log.py",
)


@pytest.mark.parametrize("relpath", VENDORED_COPIES)
def test_the_vendored_copy_matches_the_canonical_one(root, relpath):
    """debug_log is duplicated because hooks import nothing; duplication must be checked."""
    canonical = (root / "features/common/hooks/debug_log.py").read_text(encoding="utf-8")
    vendored = (root / relpath).read_text(encoding="utf-8")

    assert canonical == vendored, (
        f"copy features/common/hooks/debug_log.py over {relpath}"
    )


class TestProjectIdentity:
    """A path is machine-specific; the project's own name travels."""

    def _scaffolded(self, tmp_path, name="probe"):
        aib = tmp_path / "proj" / ".ai-badger"
        aib.mkdir(parents=True, exist_ok=True)
        (aib / "config.json").write_text(
            json.dumps({"project": {"name": name}}), encoding="utf-8")
        return str(tmp_path / "proj")

    def test_the_project_name_is_recorded_when_scaffolded(self, load_script, tmp_path,
                                                          monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        project = self._scaffolded(tmp_path, "my-service")

        dl.log_event("h", "start", project=project)

        assert _records(dl)[0][dl.KEY_NAME] == "my-service"

    def test_an_unscaffolded_project_simply_has_no_name(self, load_script, tmp_path,
                                                        monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)

        dl.log_event("h", "start", project=str(tmp_path))

        assert dl.KEY_NAME not in _records(dl)[0]

    def test_the_name_is_read_once_per_process(self, load_script, tmp_path, monkeypatch):
        """A file read on every hook event would be a real cost for a debug facility."""
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        project = self._scaffolded(tmp_path, "cached")

        dl.log_event("h", "start", project=project)
        (Path(project) / ".ai-badger" / "config.json").unlink()
        dl.log_event("h", "start", project=project)

        assert [r[dl.KEY_NAME] for r in _records(dl)] == ["cached", "cached"]


class TestUserScopeInstalls:
    """A hook installed at user level belongs to no project — naming one would be a guess."""

    def test_a_user_scope_install_records_user_not_a_project_name(self, load_script, tmp_path,
                                                                  monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        monkeypatch.setattr(dl, "is_user_scope", lambda: True)

        dl.log_event("h", "start", project=str(tmp_path))

        assert _records(dl)[0][dl.KEY_NAME] == dl.NAME_USER_SCOPE

    def test_a_project_install_is_unaffected(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)
        _enable(dl)
        monkeypatch.setattr(dl, "is_user_scope", lambda: False)
        aib = tmp_path / "proj" / ".ai-badger"
        aib.mkdir(parents=True, exist_ok=True)
        (aib / "config.json").write_text(json.dumps({"project": {"name": "svc"}}),
                                         encoding="utf-8")

        dl.log_event("h", "start", project=str(tmp_path / "proj"))

        assert _records(dl)[0][dl.KEY_NAME] == "svc"

    def test_the_user_install_roots_are_under_home(self, load_script, tmp_path, monkeypatch):
        dl = _load(load_script, tmp_path, monkeypatch)

        assert all(str(r).startswith(str(Path.home())) for r in dl.USER_INSTALL_ROOTS)
