"""Tests for features/common/hooks/learned_skills_sync.py (Hermes learned-skill sync).

Stages 1-3 of docs/design/hermes-learned-skills-sync-impl-plan.md.
"""
# pylint: disable=redefined-outer-name  # module-local fixture reuse; see pyproject.toml
import importlib.util
import json
import pathlib
import shutil
import sys

import pytest

NOW = "2026-07-26T20:00:00Z"
# Obviously fake, but shaped like the github-token pattern the scanner recognises.
FAKE_GITHUB_TOKEN = "ghp_FAKEnotarealtoken" + "0" * 19


@pytest.fixture
def sync(load_script):
    """Load the learned-skills sync module."""
    return load_script("features/common/hooks/learned_skills_sync.py")


def _make_project(tmp_path, framework_skills=("task",)):
    project = tmp_path / "proj"
    aib = project / ".ai-badger"
    aib.mkdir(parents=True)
    entries = [
        {
            "feature": "skills",
            "stack": "common",
            "name": name,
            "source": f"features/common/skills/{name}",
            "target": f".ai-badger/skills/{name}",
            "frameworkVersion": "0.17.0",
            "hash": "0" * 64,
        }
        for name in framework_skills
    ]
    (aib / "manifest.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    for name in framework_skills:
        skill_dir = aib / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# framework {name}\n", encoding="utf-8")
    return project


def _make_source_skill(skills_root, category, name, body="---\nname: demo\n---\n"):
    skill_dir = skills_root / category / name if category else skills_root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return skill_dir


def _make_secret_file(tmp_path, name="credentials"):
    """A credential-shaped file outside the skills root, i.e. a symlink's payload."""
    secret = tmp_path / "outside" / name
    secret.parent.mkdir(exist_ok=True)
    secret.write_text(f"token={FAKE_GITHUB_TOKEN}\n", encoding="utf-8")
    return secret


def _learned_tree_text(project):
    learned = project / ".ai-badger" / "skills" / "learned"
    return "".join(path.read_text(encoding="utf-8", errors="ignore")
                   for path in sorted(learned.rglob("*")) if path.is_file())


# --------------------------------------------------------------------------------------
# Stage 1 — gates
# --------------------------------------------------------------------------------------

def test_target_project_returns_none_when_cwd_has_no_manifest(tmp_path, sync):
    assert sync.target_project(str(tmp_path)) is None


def test_target_project_returns_project_root_when_manifest_present(tmp_path, sync):
    project = _make_project(tmp_path)
    assert sync.target_project(str(project)) == project.resolve()


def test_target_project_returns_none_for_empty_or_missing_cwd(tmp_path, sync):
    assert sync.target_project("") is None
    assert sync.target_project(str(tmp_path / "nope")) is None


def test_resolve_source_dir_uses_category_segment(tmp_path, sync):
    skills_root = tmp_path / "skills"
    expected = _make_source_skill(skills_root, "apple", "apple-notes")
    assert sync.resolve_source_dir("apple-notes", "apple", skills_root) == expected


def test_resolve_source_dir_without_category_searches_one_level(tmp_path, sync):
    skills_root = tmp_path / "skills"
    expected = _make_source_skill(skills_root, "misc", "foo")
    assert sync.resolve_source_dir("foo", None, skills_root) == expected


def test_resolve_source_dir_rejects_traversal_name(tmp_path, sync):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    assert sync.resolve_source_dir("../../etc", None, skills_root) is None
    assert sync.resolve_source_dir("ok", "../..", skills_root) is None


def test_is_syncable_rejects_symlinked_skill_dir(tmp_path, sync):
    skills_root = tmp_path / "skills"
    namespace = skills_root / "ai-badger"
    namespace.mkdir(parents=True)
    framework = _make_project(tmp_path) / ".ai-badger" / "skills" / "task"
    (namespace / "task").symlink_to(framework, target_is_directory=True)

    assert sync.is_syncable(namespace / "task", skills_root) == (False, "symlink")


def test_is_syncable_rejects_symlink_pointing_outside_skills_root(tmp_path, sync):
    """A link inside the skill is as unsyncable as a linked skill dir: the copy follows it."""
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")
    (source / "creds.txt").symlink_to(_make_secret_file(tmp_path))

    assert sync.is_syncable(source, skills_root) == (False, "symlink")


def test_is_syncable_rejects_path_escaping_skills_root(tmp_path, sync):
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    outside = _make_source_skill(tmp_path / "elsewhere", "apple", "apple-notes")

    ok, reason = sync.is_syncable(outside, skills_root)
    assert ok is False
    assert reason


def test_is_syncable_rejects_dir_without_skill_md(tmp_path, sync):
    skills_root = tmp_path / "skills"
    bare = skills_root / "apple" / "apple-notes"
    bare.mkdir(parents=True)

    assert sync.is_syncable(bare, skills_root) == (False, "no SKILL.md")


def test_is_syncable_accepts_plain_skill_dir(tmp_path, sync):
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")

    assert sync.is_syncable(source, skills_root) == (True, "")


def test_is_framework_owned_true_for_manifest_target_name(tmp_path, sync):
    project = _make_project(tmp_path, framework_skills=("task", "feed-badger"))
    assert sync.is_framework_owned(project, "task") is True
    assert sync.is_framework_owned(project, "feed-badger") is True


def test_is_framework_owned_false_for_unknown_name(tmp_path, sync):
    project = _make_project(tmp_path)
    assert sync.is_framework_owned(project, "apple-notes") is False


# --------------------------------------------------------------------------------------
# Stage 2 — the write path
# --------------------------------------------------------------------------------------

def _learned_json_path(project):
    return project / ".ai-badger" / "skills-data" / "hermes" / "learned.json"


def _learned(project):
    return json.loads(_learned_json_path(project).read_text(encoding="utf-8"))


def test_sync_skill_copies_into_learned_category_path(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")

    result = sync.sync_skill(project, source, "apple-notes", "apple", now=NOW,
                             source_path="apple/apple-notes")

    assert result["action"] == "created"
    target = project / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes" / "SKILL.md"
    assert target.read_text(encoding="utf-8") == (source / "SKILL.md").read_text(encoding="utf-8")


def test_sync_skill_uses_uncategorized_when_category_missing(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", None, "loose")

    result = sync.sync_skill(project, source, "loose", None, now=NOW, source_path="loose")

    assert result["action"] == "created"
    assert (project / ".ai-badger" / "skills" / "learned" / "uncategorized" / "loose"
            / "SKILL.md").is_file()


def test_sync_skill_copies_subdirectories(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")
    (source / "scripts").mkdir()
    (source / "scripts" / "helper.py").write_text("print('hi')\n", encoding="utf-8")
    (source / "references").mkdir()
    (source / "references" / "api.md").write_text("# api\n", encoding="utf-8")

    sync.sync_skill(project, source, "apple-notes", "apple", now=NOW,
                    source_path="apple/apple-notes")

    dest = project / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes"
    assert (dest / "scripts" / "helper.py").is_file()
    assert (dest / "references" / "api.md").is_file()


def test_sync_skill_writes_learned_manifest_entry(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")

    sync.sync_skill(project, source, "apple-notes", "apple", now=NOW,
                    source_path="apple/apple-notes")

    data = _learned(project)
    assert data["version"] == 1
    assert len(data["skills"]) == 1
    record = data["skills"][0]
    assert record["name"] == "apple-notes"
    assert record["category"] == "apple"
    assert record["target"] == ".ai-badger/skills/learned/apple/apple-notes"
    assert record["sourcePath"] == "apple/apple-notes"
    assert record["syncedAt"] == NOW
    assert record["status"] == "synced"
    assert len(record["sourceHash"]) == 64


def test_sync_skill_manifest_source_path_is_relative(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")

    sync.sync_skill(project, source, "apple-notes", "apple", now=NOW)

    raw = _learned_json_path(project).read_text(encoding="utf-8")
    assert str(tmp_path) not in raw
    assert str(pathlib.Path.home()) not in raw
    assert "/Users/" not in raw
    assert _learned(project)["skills"][0]["sourcePath"] == "apple/apple-notes"


def test_sync_skill_is_idempotent_when_source_unchanged(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")

    sync.sync_skill(project, source, "apple-notes", "apple", now=NOW,
                    source_path="apple/apple-notes")
    first = _learned_json_path(project).read_text(encoding="utf-8")
    result = sync.sync_skill(project, source, "apple-notes", "apple",
                             now="2027-01-01T00:00:00Z", source_path="apple/apple-notes")

    assert result["action"] == "skipped"
    assert _learned_json_path(project).read_text(encoding="utf-8") == first
    assert len(_learned(project)["skills"]) == 1


def test_sync_skill_updates_in_place_when_source_changed(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")
    sync.sync_skill(project, source, "apple-notes", "apple", now=NOW,
                    source_path="apple/apple-notes")

    (source / "SKILL.md").write_text("---\nname: demo\n---\nchanged\n", encoding="utf-8")
    later = "2026-08-01T10:00:00Z"
    result = sync.sync_skill(project, source, "apple-notes", "apple", now=later,
                             source_path="apple/apple-notes")

    assert result["action"] == "updated"
    dest = project / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes" / "SKILL.md"
    assert "changed" in dest.read_text(encoding="utf-8")
    records = _learned(project)["skills"]
    assert len(records) == 1
    assert records[0]["syncedAt"] == later


def test_sync_skill_reports_conflict_for_untracked_existing_path(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")
    dest = project / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("hand written\n", encoding="utf-8")

    result = sync.sync_skill(project, source, "apple-notes", "apple", now=NOW,
                             source_path="apple/apple-notes")

    assert result["action"] == "conflict"
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "hand written\n"
    assert not _learned_json_path(project).exists()


def test_sync_skill_never_writes_outside_learned_root(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "apple-notes")

    result = sync.sync_skill(project, source, "apple-notes", "../../..", now=NOW)

    assert result["action"] == "refused"
    framework_skill = project / ".ai-badger" / "skills" / "task" / "SKILL.md"
    assert framework_skill.read_text(encoding="utf-8") == "# framework task\n"
    assert not _learned_json_path(project).exists()


def test_sync_skill_refuses_framework_owned_name(tmp_path, sync):
    project = _make_project(tmp_path)
    source = _make_source_skill(tmp_path / "skills", "apple", "task")

    result = sync.sync_skill(project, source, "task", "apple", now=NOW,
                             source_path="apple/task")

    assert result["action"] == "refused"
    assert not (project / ".ai-badger" / "skills" / "learned").exists()


# --------------------------------------------------------------------------------------
# Stage 3 — orchestration, deletes, secrets, reconcile
# --------------------------------------------------------------------------------------

def test_on_skill_manage_ignores_other_tools(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(project), tool_name="terminal", skills_root=skills_root, now=NOW)

    assert result is None
    assert not (project / ".ai-badger" / "skills" / "learned").exists()


def test_on_skill_manage_ignores_failed_calls(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "error", str(project), skills_root=skills_root, now=NOW)

    assert result is None
    assert not (project / ".ai-badger" / "skills" / "learned").exists()


def test_on_skill_manage_ignores_non_project_cwd(tmp_path, sync):
    gateway_cwd = tmp_path / "gateway"
    gateway_cwd.mkdir()
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(gateway_cwd), skills_root=skills_root, now=NOW)

    assert result is None
    assert list(gateway_cwd.iterdir()) == []


def test_on_skill_manage_syncs_on_create(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result["action"] == "created"
    assert (project / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes"
            / "SKILL.md").is_file()
    assert _learned(project)["skills"][0]["sourcePath"] == "apple/apple-notes"


@pytest.mark.parametrize("action", ["patch", "edit"])
def test_on_skill_manage_syncs_on_patch_and_edit(tmp_path, sync, action):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = sync.on_skill_manage(
        {"action": action, "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result["action"] == "created"


def test_on_skill_manage_marks_orphaned_on_delete(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")
    sync.on_skill_manage({"action": "create", "name": "apple-notes", "category": "apple"},
                         "ok", str(project), skills_root=skills_root, now=NOW)

    result = sync.on_skill_manage(
        {"action": "delete", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now="2026-08-02T00:00:00Z")

    assert result["action"] == "orphaned"
    assert _learned(project)["skills"][0]["status"] == "orphaned"
    assert (project / ".ai-badger" / "skills" / "learned" / "apple" / "apple-notes"
            / "SKILL.md").is_file()


def test_on_skill_manage_restores_synced_status_after_orphan(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")
    args = {"name": "apple-notes", "category": "apple"}
    sync.on_skill_manage(dict(args, action="create"), "ok", str(project),
                         skills_root=skills_root, now=NOW)
    sync.on_skill_manage(dict(args, action="delete"), "ok", str(project),
                         skills_root=skills_root, now=NOW)

    later = "2026-09-09T00:00:00Z"
    result = sync.on_skill_manage(dict(args, action="create"), "ok", str(project),
                                  skills_root=skills_root, now=later)

    assert result["action"] == "updated"
    record = _learned(project)["skills"][0]
    assert record["status"] == "synced"
    assert record["syncedAt"] == later


def test_on_skill_manage_ignores_unknown_action(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = sync.on_skill_manage(
        {"action": "view", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result is None
    assert not (project / ".ai-badger" / "skills" / "learned").exists()


def test_secret_scan_refuses_skill_with_api_key_literal(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(
        skills_root, "apple", "apple-notes",
        body="---\nname: demo\n---\nRun with sk-FAKE-not-a-real-key-000 to authenticate.\n")

    assert sync.scan_for_unsafe_literals(source)
    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result["action"] == "refused"
    assert not (project / ".ai-badger" / "skills" / "learned").exists()
    assert not _learned_json_path(project).exists()


def test_secret_findings_are_structured_and_carry_no_scanned_text(tmp_path, sync):
    """Findings name the file and the pattern; the matched literal never leaves the scanner."""
    literal = "sk-FAKE-not-a-real-key-000"
    skills_root = tmp_path / "skills"
    source = _make_source_skill(
        skills_root, "apple", "apple-notes",
        body=f"---\nname: demo\n---\nRun with {literal} to authenticate.\n")

    findings = sync.scan_for_unsafe_literals(source)
    assert findings == [{"file": "SKILL.md", "pattern": "provider api key"}]
    assert all(f["pattern"] in sync.UNSAFE_LITERAL_LABELS for f in findings)
    assert literal not in json.dumps(findings)


def test_refusal_result_never_contains_the_matched_literal(tmp_path, sync):
    """A refusal is safe to print: no scanned content reaches the result (CodeQL alert 13)."""
    literal = "sk-FAKE-not-a-real-key-000"
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(
        skills_root, "apple", "apple-notes",
        body=f"---\nname: demo\n---\nRun with {literal} to authenticate.\n")

    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result["action"] == "refused"
    assert literal not in json.dumps(result)
    assert result["unsafeLiterals"] == [{"file": "SKILL.md", "pattern": "provider api key"}]


def test_reconcile_detail_reports_which_file_tripped_the_scan(tmp_path, sync):
    """A refusal must stay actionable: the offending file survives into the summary."""
    literal = "sk-FAKE-not-a-real-key-000"
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(
        skills_root, "apple", "apple-notes",
        body=f"---\nname: demo\n---\nRun with {literal} to authenticate.\n")

    summary = sync.reconcile(project, skills_root, now=NOW, dry_run=True)

    refused = [d for d in summary["details"] if d["action"] == "refused"]
    assert refused[0]["unsafeLiterals"] == [{"file": "SKILL.md", "pattern": "provider api key"}]
    assert literal not in json.dumps(summary)


def test_cli_output_names_the_file_that_tripped_the_scan(tmp_path, sync, capsys, monkeypatch):
    """Guards the CLI path: reconcile() keeping the detail is not enough if main() drops it."""
    literal = "sk-FAKE-not-a-real-key-000"
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(
        skills_root, "apple", "apple-notes",
        body=f"---\nname: demo\n---\nRun with {literal} to authenticate.\n")
    monkeypatch.chdir(project)

    assert sync.main(["--reconcile", "--target", str(project),
                      "--skills-root", str(skills_root), "--dry-run"]) == 0

    printed = capsys.readouterr().out
    assert literal not in printed
    refused = [d for d in json.loads(printed)["details"] if d["action"] == "refused"]
    assert refused[0]["unsafeLiterals"] == [{"file": "SKILL.md", "pattern": "provider api key"}]


def test_secret_scan_allows_placeholder_env_reference(tmp_path, sync):
    skills_root = tmp_path / "skills"
    source = _make_source_skill(
        skills_root, "apple", "apple-notes",
        body="---\nname: demo\n---\napi_key=${OPENAI_API_KEY}\ntoken: $env:FOO\n")

    assert sync.scan_for_unsafe_literals(source) == []


# --------------------------------------------------------------------------------------
# No framework root — the ~/.hermes/plugins/ copy whose recorded root went away
# --------------------------------------------------------------------------------------

@pytest.fixture
def rootless_sync(root, tmp_path, monkeypatch):
    """The module as the Hermes host loads it when nothing resolves a framework root."""
    home = tmp_path / "home"
    home.mkdir()
    stranded = tmp_path / "plugins" / "learned_skills_sync.py"
    stranded.parent.mkdir(parents=True)
    shutil.copy2(root / "features" / "common" / "hooks" / "learned_skills_sync.py", stranded)
    monkeypatch.delenv("AI_BADGER", raising=False)
    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: home))
    monkeypatch.chdir(tmp_path)

    spec = importlib.util.spec_from_file_location("aib_stranded_sync", stranded)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module.FRAMEWORK_ROOT is None, "the fixture is not rootless; it proves nothing"
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def test_the_plugin_still_imports_when_no_framework_root_resolves(rootless_sync):
    """Hermes imports this file at startup; raising there takes the whole plugin down."""
    assert rootless_sync.FRAMEWORK_ROOT is None


def test_the_sync_is_silent_when_no_framework_root_resolves(tmp_path, rootless_sync):
    """The host's entry point reports nothing and writes nothing without the engine."""
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")

    result = rootless_sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result is None
    assert not (project / ".ai-badger" / "skills" / "learned").exists()


def test_sync_skill_refuses_rather_than_copying_unscanned_without_the_engine(
        tmp_path, rootless_sync):
    """No scanner means no proof a skill is safe to copy: refuse, never write."""
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")

    result = rootless_sync.sync_skill(project, source, "apple-notes", "apple", now=NOW)

    assert result["action"] == "refused"
    assert "framework" in result["reason"]
    assert not (project / ".ai-badger" / "skills" / "learned").exists()


def test_the_cli_reports_the_missing_framework_rather_than_a_clean_run(
        tmp_path, rootless_sync, capsys):
    """A CLI is not a hook: --reconcile must say why it did nothing, not print an empty summary."""
    project = _make_project(tmp_path)

    rc = rootless_sync.main(["--reconcile", "--target", str(project),
                             "--skills-root", str(tmp_path / "skills")])

    assert rc == 1
    assert "framework" in json.loads(capsys.readouterr().out)["error"]


def test_skill_containing_symlink_is_refused(tmp_path, sync):
    """The scanner cannot read through a symlink, so the copy must never dereference one."""
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")
    (source / "creds.txt").symlink_to(_make_secret_file(tmp_path))

    result = sync.sync_skill(project, source, "apple-notes", "apple", now=NOW)

    assert result["action"] == "refused"
    assert result["reason"] == "symlink"
    assert FAKE_GITHUB_TOKEN not in _learned_tree_text(project)
    assert not _learned_json_path(project).exists()


def test_symlink_refusal_carries_no_bytes_from_the_symlink_target(tmp_path, sync):
    """The refusal vocabulary is fixed: neither the target's content nor its path is echoed."""
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")
    secret = _make_secret_file(tmp_path)
    (source / "creds.txt").symlink_to(secret)

    result = sync.sync_skill(project, source, "apple-notes", "apple", now=NOW)
    serialized = json.dumps(result)

    assert result["action"] == "refused"
    assert FAKE_GITHUB_TOKEN not in serialized
    assert str(secret) not in serialized
    assert secret.name not in serialized


def test_nested_symlink_inside_a_skill_subdirectory_is_refused(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")
    (source / "reference").mkdir()
    (source / "reference" / "creds.txt").symlink_to(_make_secret_file(tmp_path))

    result = sync.sync_skill(project, source, "apple-notes", "apple", now=NOW)

    assert (result["action"], result["reason"]) == ("refused", "symlink")
    assert FAKE_GITHUB_TOKEN not in _learned_tree_text(project)


def test_symlinked_directory_inside_a_skill_is_refused(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")
    secret = _make_secret_file(tmp_path)
    (source / "vendor").symlink_to(secret.parent, target_is_directory=True)

    result = sync.sync_skill(project, source, "apple-notes", "apple", now=NOW)

    assert (result["action"], result["reason"]) == ("refused", "symlink")
    assert FAKE_GITHUB_TOKEN not in _learned_tree_text(project)


def test_on_skill_manage_never_dereferences_a_symlinked_secret(tmp_path, sync):
    """The hook path stops at gate 4, so the refusal reads as 'skipped' with the same reason."""
    project = _make_project(tmp_path)
    skills_root = tmp_path / "skills"
    source = _make_source_skill(skills_root, "apple", "apple-notes")
    (source / "creds.txt").symlink_to(_make_secret_file(tmp_path))

    result = sync.on_skill_manage(
        {"action": "create", "name": "apple-notes", "category": "apple"},
        "ok", str(project), skills_root=skills_root, now=NOW)

    assert result == {"action": "skipped", "target": "", "reason": "symlink"}
    assert FAKE_GITHUB_TOKEN not in _learned_tree_text(project)


def _seed_reconcile_root(tmp_path, project):
    skills_root = tmp_path / "skills"
    _make_source_skill(skills_root, "apple", "apple-notes")
    _make_source_skill(skills_root, "misc", "foo")
    _make_source_skill(skills_root, "devtools", "bar")
    namespace = skills_root / "ai-badger"
    namespace.mkdir(parents=True)
    (namespace / "task").symlink_to(project / ".ai-badger" / "skills" / "task",
                                    target_is_directory=True)
    return skills_root


def test_reconcile_syncs_all_eligible_and_skips_symlinks(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = _seed_reconcile_root(tmp_path, project)

    summary = sync.reconcile(project, skills_root, now=NOW)

    assert summary["created"] == 3
    assert summary["skipped"] == 1
    skipped = [d for d in summary["details"] if d["action"] == "skipped"]
    assert [d["reason"] for d in skipped] == ["symlink"]
    assert len(_learned(project)["skills"]) == 3
    assert not (project / ".ai-badger" / "skills" / "learned" / "ai-badger").exists()


def test_reconcile_is_idempotent(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = _seed_reconcile_root(tmp_path, project)
    sync.reconcile(project, skills_root, now=NOW)
    first = _learned_json_path(project).read_text(encoding="utf-8")

    summary = sync.reconcile(project, skills_root, now="2027-03-03T00:00:00Z")

    assert summary["created"] == 0
    assert summary["updated"] == 0
    assert _learned_json_path(project).read_text(encoding="utf-8") == first


def test_reconcile_dry_run_writes_nothing(tmp_path, sync):
    project = _make_project(tmp_path)
    skills_root = _seed_reconcile_root(tmp_path, project)

    summary = sync.reconcile(project, skills_root, now=NOW, dry_run=True)

    assert summary["created"] == 3
    assert not (project / ".ai-badger" / "skills" / "learned").exists()
    assert not _learned_json_path(project).exists()


def test_reconcile_cli_prints_json_summary(tmp_path, sync, capsys):
    project = _make_project(tmp_path)
    skills_root = _seed_reconcile_root(tmp_path, project)

    rc = sync.main(["--reconcile", "--target", str(project),
                    "--skills-root", str(skills_root), "--dry-run"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["created"] == 3
    assert not _learned_json_path(project).exists()


def test_learned_manifest_validates_against_schema(tmp_path, sync, root):
    project = _make_project(tmp_path)
    skills_root = _seed_reconcile_root(tmp_path, project)
    sync.reconcile(project, skills_root, now=NOW)

    errors = sync.bl.validate_file(_learned_json_path(project),
                                   root / "schemas" / "learned-skills.schema.json")
    assert errors == []


def test_load_manifest_refuses_to_discard_an_unreadable_manifest(tmp_path, sync):
    project = _make_project(tmp_path)
    manifest = project / ".ai-badger" / "skills-data" / "hermes" / "learned.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"skills": [{"name": "a"}', encoding="utf-8")  # truncated by a crash

    with pytest.raises(sync.ManifestUnreadable):
        sync.load_manifest(project)


def test_sync_refuses_rather_than_overwriting_an_unreadable_manifest(tmp_path, sync):
    project = _make_project(tmp_path)
    manifest = project / ".ai-badger" / "skills-data" / "hermes" / "learned.json"
    manifest.parent.mkdir(parents=True)
    truncated = '{"skills": [{"name": "kept", "category": "general"}'
    manifest.write_text(truncated, encoding="utf-8")
    source = tmp_path / "hermes-skills" / "general" / "note-taking"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# note taking\n", encoding="utf-8")

    result = sync.sync_skill(project, source, "note-taking", "general", now=NOW)

    assert result["action"] == "refused"
    assert manifest.read_text(encoding="utf-8") == truncated
