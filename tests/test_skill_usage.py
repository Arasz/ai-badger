"""den-refresh's prune advice: which delivered skills were observed being used (#172).

The report has to keep three claims apart — observed, observed-absent, and unobservable — and
never recommend pruning a skill it had no way to see.
"""
from __future__ import annotations

import json

SCRIPT = "features/common/skills/den-refresh/scripts/skill_usage.py"

DELIVERED = ["code-review-checklist", "den-refresh", "feed-badger", "task", "welcome-ai-badger"]


def _load(load_script):
    return load_script(SCRIPT)


def _store(home, project, dir_name=None):
    """The Claude Code transcript directory for `project` under a fake `$HOME`."""
    mangled = dir_name or "".join(c if c.isalnum() else "-" for c in str(project))
    path = home / ".claude" / "projects" / mangled
    path.mkdir(parents=True, exist_ok=True)
    return path


def _transcript(directory, records, name="session.jsonl"):
    (directory / name).write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return directory / name


def _skill_call(skill, cwd="/proj", ts="2026-07-20T10:00:00.000Z"):
    return {
        "type": "assistant", "timestamp": ts, "cwd": str(cwd),
        "message": {"content": [{"type": "tool_use", "name": "Skill",
                                 "input": {"skill": skill}}]},
    }


def _slash_call(command, cwd="/proj", ts="2026-07-20T10:00:00.000Z"):
    return {
        "type": "user", "timestamp": ts, "cwd": str(cwd),
        "message": {"role": "user", "content": f"<command-name>{command}</command-name>"},
    }


def _hooks(**skills):
    """A behaviorist hook-activity report: `skill=(records, instrumented)`."""
    return {
        "records": sum(records for records, _ in skills.values()),
        "skills": {name.replace("_", "-"): {"hooks": [f".ai-badger/skills/{name}/scripts/h.py"],
                                            "instrumented": instrumented, "records": records}
                   for name, (records, instrumented) in skills.items()},
    }


NO_HOOKS = {"records": 0, "skills": {}}


def _bucket(report, name):
    return [entry["skill"] for entry in report[name]]


def _entry(report, bucket, skill):
    return next(e for e in report[bucket] if e["skill"] == skill)


# ------------------------------------------------------------------ the invocation channel
def test_a_skill_invoked_through_the_skill_tool_is_reported_used(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("feed-badger", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "feed-badger" in _bucket(report, "used")
    assert _entry(report, "used", "feed-badger")["evidence"] == usage.INVOCATION_EVIDENCE


def test_a_skill_invoked_under_the_frameworks_plugin_prefix_counts_for_the_bare_name(
        tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("ai-badger:task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "task" in _bucket(report, "used")


def test_another_plugins_skill_of_the_same_name_is_not_evidence(tmp_path, load_script):
    """`superpowers:task` is somebody else's skill; counting it would hide an unused one."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project),
                [_skill_call("superpowers:task", cwd=project),
                 _skill_call("feed-badger", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "task" in _bucket(report, "unused")


def test_a_slash_command_is_an_invocation(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project),
                [_slash_call("/code-review-checklist", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "code-review-checklist" in _bucket(report, "used")


def test_a_skill_nobody_invoked_over_an_observed_window_is_a_prune_candidate(
        tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert _bucket(report, "unused") == ["code-review-checklist", "den-refresh", "feed-badger"]


def test_a_transcript_belonging_to_another_project_is_not_evidence(tmp_path, load_script):
    """The directory name is a mangled path, so a neighbouring project can share its prefix."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    mangled = "".join(c if c.isalnum() else "-" for c in str(project))
    neighbour = _store(tmp_path / "home", project, dir_name=mangled + "-two")
    _transcript(neighbour, [_skill_call("feed-badger", cwd=str(project) + "-two")])
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "feed-badger" in _bucket(report, "unused")


def test_a_worktree_session_counts_as_the_project(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    worktree = project / ".claude" / "worktrees" / "wt"
    worktree.mkdir(parents=True)
    mangled = "".join(c if c.isalnum() else "-" for c in str(worktree))
    _transcript(_store(tmp_path / "home", worktree, dir_name=mangled),
                [_skill_call("feed-badger", cwd=worktree)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "feed-badger" in _bucket(report, "used")


def test_an_unparseable_transcript_line_never_breaks_the_scan(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    store = _store(tmp_path / "home", project)
    (store / "broken.jsonl").write_text(
        "{not json at all\n" + json.dumps(_skill_call("task", cwd=project)) + "\n",
        encoding="utf-8")

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "task" in _bucket(report, "used")


# ------------------------------------------------------------------------- the hook channel
def test_a_skill_whose_hook_produced_records_is_used_not_unused(tmp_path, load_script):
    """A hook that fires is doing work here every session; pruning it changes behaviour."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=_hooks(den_refresh=(10, True)))

    assert "den-refresh" in _bucket(report, "used")
    assert _entry(report, "used", "den-refresh")["evidence"] == usage.HOOK_EVIDENCE


def test_a_skill_wiring_a_hook_that_calls_no_debug_logger_cannot_be_told(tmp_path, load_script):
    """Its hook may fire every session and can never say so — silence is not absence."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=_hooks(feed_badger=(0, False)))

    assert "feed-badger" in _bucket(report, "cannotTell")
    assert "feed-badger" not in _bucket(report, "unused")


def test_a_hook_shipping_skill_is_a_candidate_when_the_audit_log_saw_the_others(
        tmp_path, load_script):
    """An instrumented hook that stayed silent while the log was live is real absence."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    hooks = _hooks(task=(20, True), feed_badger=(0, True))
    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=hooks)

    assert "feed-badger" in _bucket(report, "unused")


# ---------------------------------------------------------------------------- the exemptions
def test_welcome_ai_badger_is_never_proposed_for_pruning(tmp_path, load_script):
    """It runs once per project lifetime, by design — and pruning it removes the scaffolder."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert "welcome-ai-badger" not in _bucket(report, "unused")
    assert "welcome-ai-badger" in _bucket(report, "cannotTell")


# ------------------------------------------------------------- no evidence, no recommendation
def test_no_observable_channel_reports_a_reason_and_recommends_nothing(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert report["used"] == [] and report["unused"] == []
    assert report["channels"] == {"invocation": None, "hooks": None}
    assert "behaviorist.py on" in report["hint"]


def test_delivering_no_skills_reports_nothing_at_all(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()

    assert usage.report(project, [], store=tmp_path / "home", hooks=NO_HOOKS) is None


def test_the_hook_channel_alone_never_produces_a_prune_candidate(tmp_path, load_script):
    """With no transcript store, a hookless skill's silence is unobservable, not absence."""
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=_hooks(task=(20, True)))

    assert report["unused"] == []
    assert "task" in _bucket(report, "used")
    assert "feed-badger" in _bucket(report, "cannotTell")


# --------------------------------------------------------------------------------- the window
def test_the_observed_window_travels_with_the_finding(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project),
                [_skill_call("task", cwd=project, ts="2026-07-01T10:00:00.000Z"),
                 _skill_call("task", cwd=project, ts="2026-07-11T10:00:00.000Z")])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert report["window"]["from"].startswith("2026-07-01")
    assert report["window"]["to"].startswith("2026-07-11")
    assert report["window"]["days"] == 10.0
    assert report["window"]["transcripts"] == 1


def test_a_window_too_short_to_support_the_claim_says_so(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project),
                [_skill_call("task", cwd=project, ts="2026-07-01T10:00:00.000Z"),
                 _skill_call("task", cwd=project, ts="2026-07-02T10:00:00.000Z")])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert any("1.0 day" in limit for limit in report["limits"])


def test_the_limits_name_what_neither_channel_can_see(tmp_path, load_script):
    usage = _load(load_script)
    project = tmp_path / "proj"
    project.mkdir()
    _transcript(_store(tmp_path / "home", project), [_skill_call("task", cwd=project)])

    report = usage.report(project, DELIVERED, store=tmp_path / "home" / ".claude" / "projects",
                          hooks=NO_HOOKS)

    assert any("Claude Code" in limit for limit in report["limits"])
    assert any("hook" in limit for limit in report["limits"])
