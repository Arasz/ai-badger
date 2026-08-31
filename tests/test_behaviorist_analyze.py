"""`behaviorist analyze` turns the audit log into findings an agent can report on."""
from __future__ import annotations

import json
from conftest import _test_write


def _load(load_script, tmp_path, monkeypatch):
    beh = load_script("features/common/skills/call-behaviorist/scripts/behaviorist.py")
    root = tmp_path / "debug"
    root.mkdir(parents=True, exist_ok=True)
    for module in (beh.dl,):
        monkeypatch.setattr(module, "DEBUG_DIR", root)
        monkeypatch.setattr(module, "STATE_FILE", root / "state.json")
        monkeypatch.setattr(module, "AUDIT_FILE", root / "audit.jsonl")
    return beh


def _write(beh, records):
    """Seed records where the read path reads them: the store's audit DB when the store
    is available (the same sink `read_records` queries), the legacy jsonl otherwise."""
    store = beh.dl._store()  # noqa: SLF001  # pylint: disable=protected-access
    if store is None:
        lines = [json.dumps(r) for r in records]
        _test_write(beh.dl.AUDIT_FILE, "\n".join(lines) + "\n", encoding="utf-8")
        return
    try:
        for rec in records:
            store.log_append("hook_audit", rec.get(beh.dl.KEY_TS, ""), rec)
    finally:
        store.close()


DEFAULT_TS = "2026-07-27T09:00:00+00:00"


def _record(component, event="start", version="0.30.0", project="/repo", ts=DEFAULT_TS, **extra):
    rec = {
        beh_keys["t"]: ts,
        beh_keys["c"]: component,
        beh_keys["e"]: event,
        beh_keys["v"]: version,
        beh_keys["p"]: project,
    }
    rec.update(extra)
    return rec


beh_keys = {"t": "t", "c": "c", "e": "e", "v": "v", "p": "p"}


def _unattributed(component, **extra):
    """A record from a hook that could not name a project — the key is absent, not null."""
    rec = _record(component, **extra)
    del rec[beh_keys["p"]]
    return rec


def _kinds(report):
    return [f["kind"] for f in report["findings"]]


def _by_component(report):
    return {f["component"]: f["kind"] for f in report["findings"]}


QUIET = "print('no logging here')\n"
LOUD = "import debug_log\ndebug_log.log_event\n"


def _named(component):
    """An instrumented hook that logs under a name of its own choosing."""
    return f'import debug_log\nCOMPONENT = "{component}"\ndebug_log.log_event(COMPONENT, "x")\n'


SETTINGS = ".claude/settings.json"
HOOKS_JSON = ".ai-badger/hooks/hooks.json"


def _register(tmp_path, scripts, config=SETTINGS, event="SessionStart"):
    """Write `scripts` ({project-relative path: body}) and register them in `config`."""
    root = tmp_path / "proj"
    for relpath, body in scripts.items():
        script = root / relpath
        script.parent.mkdir(parents=True, exist_ok=True)
        _test_write(script, body, encoding="utf-8")
    path = root / config
    path.parent.mkdir(parents=True, exist_ok=True)
    _test_write(path, json.dumps({"hooks": {event: [{"hooks": [
        {"type": "command", "command": f'python3 "${{CLAUDE_PROJECT_DIR}}/{relpath}"'}
        for relpath in scripts
    ]}]}}), encoding="utf-8")
    return str(root)


class TestAbsenceOfDataIsNotHealth:
    """An empty log means nobody looked, not that everything is fine."""

    def test_no_records_reports_unknown_not_ok(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)

        report = beh.analyze(project="/repo", expected=["a/hook"])

        assert report["health"] == "unknown"
        assert report["window"]["records"] == 0

    def test_it_says_how_to_collect_data(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)

        report = beh.analyze(project="/repo", expected=[])

        assert "behaviorist.py on" in report["hint"]


class TestSilentComponents:
    """The failure this feature exists for: something wired that never runs."""

    def test_an_expected_component_that_never_logged_is_a_finding(self, load_script, tmp_path,
                                                                  monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha", "hooks/never"])

        silent = [f for f in report["findings"] if f["kind"] == "never_observed"]
        assert [f["component"] for f in silent] == ["hooks/never"]
        assert report["health"] == "degraded"

    def test_a_component_that_only_ever_skips_is_a_finding(self, load_script, tmp_path,
                                                          monkeypatch):
        """It fires but always exits early — live, but doing nothing."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", event="start"),
                     _record("hooks/alpha", event="skip"),
                     _record("hooks/alpha", event="start"),
                     _record("hooks/alpha", event="skip")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert "always_skipped" in _kinds(report)

    def test_a_healthy_component_produces_no_finding(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", event="start"),
                     _record("hooks/alpha", event="done")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert report["findings"] == []
        assert report["health"] == "ok"


class TestVersionSkew:
    """Several copies of ai-badger coexist; when they disagree the symptoms are baffling."""

    def test_one_component_logging_two_versions_is_a_finding(self, load_script, tmp_path,
                                                             monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="0.13.0"),
                     _record("hooks/alpha", version="0.30.0")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        skew = [f for f in report["findings"] if f["kind"] == "version_skew"]
        assert skew and sorted(skew[0]["versions"]) == ["0.13.0", "0.30.0"]

    def test_a_single_version_is_not_skew(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha"), _record("hooks/alpha")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert "version_skew" not in _kinds(report)


class TestScoping:
    """A user-wide log holds every project; analysis is about one of them."""

    def test_records_from_other_projects_are_excluded(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", project="/elsewhere"),
                     _record("hooks/beta", project="/repo")])

        report = beh.analyze(project="/repo", expected=["hooks/beta"])

        assert set(report["observed"]) == {"hooks/beta"}

    def test_unexpected_components_are_reported_not_hidden(self, load_script, tmp_path,
                                                           monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/surprise")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert "unexpected_component" in _kinds(report)


class TestARecordNamingNoProjectBelongsToNoProject:
    """A user-wide log holds every project; a record naming none belongs to none of them."""

    def test_it_is_not_counted_among_this_project_s_components(self, load_script, tmp_path,
                                                               monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_unattributed("hooks/elsewhere"), _record("hooks/beta")])

        report = beh.analyze(project="/repo", expected=["hooks/beta"])

        assert set(report["observed"]) == {"hooks/beta"}

    def test_it_does_not_become_an_unexpected_component(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_unattributed("hooks/elsewhere"), _record("hooks/beta")])

        report = beh.analyze(project="/repo", expected=["hooks/beta"])

        assert "unexpected_component" not in _kinds(report)

    def test_its_version_does_not_pollute_this_project_s_versions(self, load_script, tmp_path,
                                                                  monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/beta", version="0.40.0"),
                     _unattributed("hooks/beta", version="0.37.0")])

        report = beh.analyze(project="/repo", expected=["hooks/beta"])

        assert report["observed"]["hooks/beta"]["versions"] == ["0.40.0"]

    def test_what_was_set_aside_is_counted_not_silently_dropped(self, load_script, tmp_path,
                                                               monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_unattributed("hooks/elsewhere"), _unattributed("hooks/elsewhere"),
                     _record("hooks/beta")])

        report = beh.analyze(project="/repo", expected=["hooks/beta"])

        assert report["window"]["unattributed"] == 2
        assert report["window"]["unattributed_components"] == ["hooks/elsewhere"]

    def test_bookkeeping_is_not_reported_as_set_aside(self, load_script, tmp_path, monkeypatch):
        """`enabled`/`cleared` name no project by design; they were never evidence."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_unattributed("call-behaviorist", event="cleared"), _record("hooks/beta")])

        report = beh.analyze(project="/repo", expected=["hooks/beta"])

        assert report["window"]["unattributed"] == 0
        assert report["window"]["unattributed_components"] == []

    def test_a_project_spelled_through_a_symlink_still_matches(self, load_script, tmp_path,
                                                              monkeypatch):
        """/var and /private/var name one directory; comparing the text alone loses records."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/beta", project=str(link))])

        report = beh.analyze(project=str(real), expected=["hooks/beta"])

        assert set(report["observed"]) == {"hooks/beta"}


class TestOutputIsMachineReadable:
    """The report is handed to an agent, which turns it into a GitHub issue."""

    def test_the_cli_emits_valid_json(self, load_script, tmp_path, monkeypatch, capsys):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha")])

        rc = beh.main(["analyze", "--project", "/repo", "--json"])

        report = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert report["observed"]["hooks/alpha"]["count"] == 1

    def test_findings_carry_a_severity_and_an_explanation(self, load_script, tmp_path,
                                                          monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha", "hooks/never"])

        finding = report["findings"][0]
        assert finding["severity"] in ("high", "medium", "low")
        assert finding["detail"]


class TestNotYetInstrumentedIsNotAFailure:
    """A wired hook with no logging call cannot produce records — that is not a defect."""

    def _wire(self, tmp_path, script_name, body):
        aib = tmp_path / "proj" / ".ai-badger"
        (aib / "hooks").mkdir(parents=True, exist_ok=True)
        _test_write(aib / "hooks" / "hooks.json", json.dumps({
            "hooks": {"SessionStart": [{"hooks": [
                {"type": "command", "command": f'python3 "{tmp_path}/proj/{script_name}"'}]}]}
        }), encoding="utf-8")
        _test_write(tmp_path / "proj" / script_name, body, encoding="utf-8")
        return str(tmp_path / "proj")

    def test_an_uninstrumented_hook_is_reported_as_such_not_as_broken(self, load_script,
                                                                      tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = self._wire(tmp_path, "quiet_hook.py", "print('no logging here')\n")
        _write(beh, [_record("other", project=project)])

        report = beh.analyze(project=project)

        kinds = {f["kind"]: f for f in report["findings"]}
        assert "not_instrumented" in kinds
        assert kinds["not_instrumented"]["severity"] == "low"
        assert "never_observed" not in kinds

    def test_an_instrumented_hook_that_stays_silent_is_a_real_finding(self, load_script,
                                                                      tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = self._wire(tmp_path, "loud_hook.py", "import debug_log\ndebug_log.log_event\n")
        _write(beh, [_record("other", project=project)])

        report = beh.analyze(project=project)

        kinds = {f["kind"]: f for f in report["findings"]}
        assert kinds["never_observed"]["severity"] == "high"


class TestComponentNamesMatchAcrossNamespaces:
    """Observed names are `<script>/<phase>`; expected names come from hooks.json filenames."""

    def test_a_phase_qualified_component_matches_its_script(self, load_script, tmp_path,
                                                            monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("alpha_hook/session_start")])

        report = beh.analyze(project="/repo", expected=["alpha_hook"])

        assert report["findings"] == [], report["findings"]


class TestTwoHooksCanShareAFilename:
    """`user_prompt_hook.py` exists in more than one skill; they are not one component."""

    SCRIPTS = {
        "task/scripts/user_prompt_hook.py": QUIET,
        "markers/scripts/user_prompt_hook.py": LOUD,
    }

    def test_both_paths_are_expected_components(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, self.SCRIPTS, config=HOOKS_JSON)

        report = beh.analyze(project=project)

        assert report["expected"] == sorted(self.SCRIPTS)

    def test_the_instrumented_twin_is_still_reported_silent(self, load_script, tmp_path,
                                                            monkeypatch):
        """The uninstrumented sibling must not explain away the other's silence."""
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, self.SCRIPTS, config=HOOKS_JSON)
        _write(beh, [_record("other", project=project)])

        report = beh.analyze(project=project)

        by_component = _by_component(report)
        assert by_component["task/scripts/user_prompt_hook.py"] == "not_instrumented"
        assert by_component["markers/scripts/user_prompt_hook.py"] == "never_observed"
        assert report["health"] == "degraded"


class TestItAuditsWhatIsRegistered:
    """Hooks run from what is registered with the agent, not from what ai-badger declared."""

    def test_a_hook_only_in_claude_settings_is_audited(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {"task/scripts/stop_hook.py": LOUD}, config=SETTINGS)

        report = beh.analyze(project=project)

        assert report["expected"] == ["task/scripts/stop_hook.py"]

    def test_hooks_json_still_counts_where_there_is_no_claude_settings(self, load_script,
                                                                       tmp_path, monkeypatch):
        """A Hermes- or Copilot-only project registers nothing under .claude/."""
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {"task/scripts/stop_hook.py": LOUD}, config=HOOKS_JSON)

        report = beh.analyze(project=project)

        assert report["expected"] == ["task/scripts/stop_hook.py"]

    def test_a_hook_in_both_files_is_one_component(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        scripts = {"task/scripts/stop_hook.py": LOUD}
        _register(tmp_path, scripts, config=HOOKS_JSON)
        project = _register(tmp_path, scripts, config=SETTINGS)

        report = beh.analyze(project=project)

        assert report["expected"] == ["task/scripts/stop_hook.py"]

    def test_a_third_party_hook_is_classified_not_hidden(self, load_script, tmp_path,
                                                          monkeypatch):
        """Someone else's hook is information; it just cannot report on itself."""
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {"vendor/other_hook.py": QUIET}, config=SETTINGS)
        _write(beh, [_record("other", project=project)])

        report = beh.analyze(project=project)

        assert _by_component(report)["vendor/other_hook.py"] == "not_instrumented"


class TestAProjectThatWasNeverObserved:
    """The end-to-end shape: everything wired, nothing looked at."""

    def test_five_registered_hooks_and_an_empty_log_report_unknown(self, load_script, tmp_path,
                                                                    monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        scripts = {
            "task/scripts/session_start_hook.py": LOUD,
            "task/scripts/stop_hook.py": LOUD,
            "task/scripts/drift_notice_hook.py": QUIET,
            "task/scripts/user_prompt_hook.py": QUIET,
            "markers/scripts/user_prompt_hook.py": QUIET,
        }
        project = _register(tmp_path, scripts, config=SETTINGS)

        report = beh.analyze(project=project)

        assert report["health"] == "unknown"
        assert report["expected"] == sorted(scripts)
        assert [f for f in report["findings"] if f["severity"] == "high"] == []


class TestTheToolsOwnEventsAreNotEvidence:
    """`enabled`/`disabled`/`cleared` are bookkeeping; they say nothing about any hook."""

    def test_only_bookkeeping_records_still_reports_unknown(self, load_script, tmp_path,
                                                            monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("call-behaviorist", event="cleared", project=None)])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert report["health"] == "unknown"

    def test_no_high_severity_finding_is_raised_without_evidence(self, load_script, tmp_path,
                                                                 monkeypatch):
        """`never_observed` is vacuous when nothing was observed at all."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("call-behaviorist", event="cleared", project=None)])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert [f for f in report["findings"] if f["severity"] == "high"] == []

    def test_the_tool_is_not_reported_as_an_unexpected_component(self, load_script, tmp_path,
                                                                 monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("call-behaviorist", event="cleared", project=None),
                     _record("hooks/alpha", project="/repo")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert "unexpected_component" not in _kinds(report)

    def test_the_window_counts_evidence_not_bookkeeping(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("call-behaviorist", event="cleared", project=None),
                     _record("hooks/alpha", project="/repo")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert report["window"]["records"] == 1

    def test_real_evidence_still_produces_a_real_finding(self, load_script, tmp_path, monkeypatch):
        """The fix must not mute genuine silence — alpha fired, never did not."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("call-behaviorist", event="cleared", project=None),
                     _record("hooks/alpha", project="/repo")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha", "hooks/never"])

        silent = [f for f in report["findings"] if f["kind"] == "never_observed"]
        assert [f["component"] for f in silent] == ["hooks/never"]
        assert report["health"] == "degraded"


class TestAHookIsNamedByWhatItLogs:
    """`user_prompt_hook.py` logs as `prompt_markers_hook`; the filename is not the identity."""

    SCRIPTS = {"markers/scripts/user_prompt_hook.py": _named("prompt_markers_hook")}

    def test_a_hook_logging_under_its_declared_name_is_not_reported_silent(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, self.SCRIPTS, config=HOOKS_JSON)
        _write(beh, [_record("prompt_markers_hook", project=project)])

        report = beh.analyze(project=project)

        assert report["findings"] == [], report["findings"]

    def test_it_is_not_reported_as_an_unexpected_component_either(self, load_script, tmp_path,
                                                                  monkeypatch):
        """The stem mismatch used to indict the same run twice, in contradictory ways."""
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, self.SCRIPTS, config=HOOKS_JSON)
        _write(beh, [_record("prompt_markers_hook", project=project)])

        report = beh.analyze(project=project)

        assert "unexpected_component" not in _kinds(report)

    def test_a_declared_name_that_really_is_silent_is_still_a_finding(self, load_script, tmp_path,
                                                                      monkeypatch):
        """Matching on the declared name must not become a way to never be silent."""
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, self.SCRIPTS, config=HOOKS_JSON)
        _write(beh, [_record("something_else", project=project)])

        report = beh.analyze(project=project)

        assert _by_component(report)["markers/scripts/user_prompt_hook.py"] == "never_observed"

    def test_a_hook_declaring_no_name_still_matches_on_its_filename(self, load_script, tmp_path,
                                                                     monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {"skill/scripts/alpha_hook.py": LOUD}, config=HOOKS_JSON)
        _write(beh, [_record("alpha_hook", project=project)])

        report = beh.analyze(project=project)

        assert report["findings"] == [], report["findings"]


class TestAnUnknownVersionIsNotADisagreement:
    """`unknown` is the logger's sentinel for "no VERSION found" — not a version."""

    def test_the_sentinel_alongside_a_real_version_is_not_skew(self, load_script, tmp_path,
                                                                monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="0.35.2"),
                     _record("hooks/alpha", version="unknown")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert "version_skew" not in _kinds(report)

    def test_two_real_versions_are_still_skew_when_the_sentinel_is_present(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="0.13.0"),
                     _record("hooks/alpha", version="unknown"),
                     _record("hooks/alpha", version="0.30.0")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        skew = [f for f in report["findings"] if f["kind"] == "version_skew"]
        assert skew and sorted(skew[0]["versions"]) == ["0.13.0", "0.30.0"]

    def test_the_sentinel_is_still_visible_in_what_was_observed(self, load_script, tmp_path,
                                                                monkeypatch):
        """Suppressing the finding must not amount to hiding the evidence."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="0.35.2"),
                     _record("hooks/alpha", version="unknown")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert "unknown" in report["observed"]["hooks/alpha"]["versions"]


# Issue #108's window: seven releases, and every wired hook upgraded through them in turn.
RELEASE_TRAIN = ("0.35.1", "0.35.2", "0.35.3", "0.35.4", "0.35.5", "0.35.6", "0.36.0")
TRAINED_HOOKS = ("drift_notice_hook", "session_start_hook", "stop_hook", "task_user_prompt_hook",
                 "commit_reminder_hook", "prompt_markers_hook", "learned_skills_hook")

# The real instance from the same window: 0.35.2 still emitting while 0.36.0 was already live.
CONCURRENT = (("0.35.2", "2026-07-27T22:55:42+00:00"),
              ("0.35.2", "2026-07-28T06:41:21+00:00"),
              ("0.36.0", "2026-07-28T06:25:49+00:00"),
              ("0.36.0", "2026-07-28T06:48:09+00:00"))


def _train(component, versions=RELEASE_TRAIN):
    """One record per version, an hour apart: an upgrade sequence, never two copies at once."""
    return [_record(component, version=version, ts=f"2026-07-27T{9 + i:02d}:00:00+00:00")
            for i, version in enumerate(versions)]


def _concurrent(component):
    """Two versions whose observed ranges overlap — the real concurrent-copy instance."""
    return [_record(component, version=version, ts=ts) for version, ts in CONCURRENT]


def _high(report):
    return [f for f in report["findings"] if f["severity"] == "high"]


class TestAReleaseTrainIsNotSkew:
    """Versions that ran one after another are an upgrade, not two copies disagreeing."""

    def test_seven_releases_across_seven_hooks_raise_no_high_finding(self, load_script, tmp_path,
                                                                     monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [rec for hook in TRAINED_HOOKS for rec in _train(hook)])

        report = beh.analyze(project="/repo", expected=list(TRAINED_HOOKS))

        assert _high(report) == []
        assert report["health"] != "degraded"

    def test_an_upgrade_sequence_leaves_health_ok(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, _train("drift_notice_hook"))

        report = beh.analyze(project="/repo", expected=["drift_notice_hook"])

        assert report["health"] == "ok"

    def test_the_sequence_is_still_reported_as_progression(self, load_script, tmp_path,
                                                            monkeypatch):
        """Suppressing the finding must not amount to hiding the upgrade."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, _train("drift_notice_hook"))

        report = beh.analyze(project="/repo", expected=["drift_notice_hook"])

        progression = [f for f in report["findings"] if f["kind"] == "version_progression"]
        assert progression and progression[0]["severity"] == "info"
        assert progression[0]["versions"] == list(RELEASE_TRAIN)

    def test_a_single_version_reports_no_progression_either(self, load_script, tmp_path,
                                                             monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha"), _record("hooks/alpha")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert report["findings"] == []


class TestConcurrentCopiesAreStillHigh:
    """Overlapping ranges are the problem the finding exists for; it must survive the fix."""

    def test_overlapping_ranges_are_a_high_finding(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, _concurrent("drift_notice_hook"))

        report = beh.analyze(project="/repo", expected=["drift_notice_hook"])

        skew = [f for f in report["findings"] if f["kind"] == "version_skew"]
        assert len(skew) == 1 and skew[0]["severity"] == "high"
        assert sorted(skew[0]["versions"]) == ["0.35.2", "0.36.0"]
        assert report["health"] == "degraded"

    def test_it_names_the_competing_versions_with_their_observed_ranges(self, load_script,
                                                                        tmp_path, monkeypatch):
        """Reconstructing this timeline by hand is what the issue's author had to do."""
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, _concurrent("drift_notice_hook"))

        report = beh.analyze(project="/repo", expected=["drift_notice_hook"])

        skew = [f for f in report["findings"] if f["kind"] == "version_skew"][0]
        assert skew["ranges"]["0.35.2"]["from"] == "2026-07-27T22:55:42+00:00"
        assert skew["ranges"]["0.35.2"]["to"] == "2026-07-28T06:41:21+00:00"
        assert skew["ranges"]["0.36.0"]["from"] == "2026-07-28T06:25:49+00:00"
        assert skew["ranges"]["0.36.0"]["to"] == "2026-07-28T06:48:09+00:00"
        assert "0.35.2" in skew["detail"] and "2026-07-28T06:25:49+00:00" in skew["detail"]

    def test_the_one_real_instance_is_not_buried_among_upgrades(self, load_script, tmp_path,
                                                                 monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [rec for hook in TRAINED_HOOKS[1:] for rec in _train(hook)]
               + _concurrent("drift_notice_hook"))

        report = beh.analyze(project="/repo", expected=list(TRAINED_HOOKS))

        assert [(f["kind"], f["component"]) for f in _high(report)] == [
            ("version_skew", "drift_notice_hook")]


class TestAnUnresolvableVersionNamesTheStaleScaffold:
    """`unknown` is the sentinel for "no VERSION found" — evidence of a copy left behind."""

    def test_the_sentinel_is_its_own_low_finding(self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="0.36.0"),
                     _record("hooks/alpha", version="unknown")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        unresolvable = [f for f in report["findings"] if f["kind"] == "version_unresolvable"]
        assert unresolvable and unresolvable[0]["severity"] == "low"
        assert _high(report) == []

    def test_it_counts_the_records_that_could_not_name_a_version(self, load_script, tmp_path,
                                                                  monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="unknown", ts=f"2026-07-27T0{i}:00:00+00:00")
                     for i in range(3)])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        unresolvable = [f for f in report["findings"] if f["kind"] == "version_unresolvable"][0]
        assert unresolvable["records"] == 3

    def test_the_sentinel_alone_is_neither_skew_nor_progression(self, load_script, tmp_path,
                                                                 monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        _write(beh, [_record("hooks/alpha", version="unknown"),
                     _record("hooks/alpha", version="unknown")])

        report = beh.analyze(project="/repo", expected=["hooks/alpha"])

        assert _kinds(report) == ["version_unresolvable"]


class TestHookActivityPerSkill:
    """What the log can say about a *skill*: its hooks ran, or it ships none that could speak."""

    def test_records_are_attributed_to_the_skill_that_ships_the_hook(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {
            ".ai-badger/skills/commit-reminder/scripts/commit_reminder_hook.py":
                _named("commit_reminder_hook")})
        _write(beh, [_record("commit_reminder_hook", project=project),
                     _record("commit_reminder_hook", project=project)])

        activity = beh.hook_activity(project)

        assert activity["skills"]["commit-reminder"]["records"] == 2
        assert activity["skills"]["commit-reminder"]["instrumented"] is True

    def test_a_phase_qualified_component_still_counts_for_its_skill(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {
            ".ai-badger/skills/task/scripts/session_start_hook.py":
                _named("session_start_hook")})
        _write(beh, [_record("session_start_hook/drift", project=project)])

        assert beh.hook_activity(project)["skills"]["task"]["records"] == 1

    def test_a_hook_that_calls_no_debug_logger_is_reported_uninstrumented(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {
            ".ai-badger/skills/feed-badger/scripts/quiet_hook.py": QUIET})
        _write(beh, [_record("something_else", project=project)])

        entry = beh.hook_activity(project)["skills"]["feed-badger"]

        assert entry["instrumented"] is False
        assert entry["records"] == 0

    def test_another_projects_records_are_not_this_projects_evidence(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {
            ".ai-badger/skills/commit-reminder/scripts/commit_reminder_hook.py":
                _named("commit_reminder_hook")})
        _write(beh, [_record("commit_reminder_hook", project="/somewhere/else")])

        activity = beh.hook_activity(project)

        assert activity["records"] == 0
        assert activity["skills"]["commit-reminder"]["records"] == 0

    def test_a_project_wiring_no_skill_hooks_names_no_skills(
            self, load_script, tmp_path, monkeypatch):
        beh = _load(load_script, tmp_path, monkeypatch)
        project = _register(tmp_path, {"tools/loose_hook.py": LOUD})
        _write(beh, [_record("loose_hook", project=project)])

        activity = beh.hook_activity(project)

        assert activity["skills"] == {}
        assert activity["records"] == 1
