"""Tests for engine/badger_lib.py: root discovery, JSON io, hashing, and jsonschema helpers."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


def _make_root(tmp_path, version=None):
    """Build a minimal fake framework root: schemas/ + features/ + engine/badger_lib.py."""
    (tmp_path / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp_path / "features").mkdir(parents=True, exist_ok=True)
    (tmp_path / "engine").mkdir(parents=True, exist_ok=True)
    (tmp_path / "engine" / "badger_lib.py").write_text("", encoding="utf-8")
    if version is not None:
        (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    return tmp_path


def _make_scaffold(project, framework_root):
    """Write the .ai-badger/manifest.json a scaffold run leaves behind, root recorded."""
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    (aib / "manifest.json").write_text(
        json.dumps({"frameworkRoot": str(framework_root)}), encoding="utf-8")
    return aib


def _forbidden_subprocess(*args, **kwargs):
    raise AssertionError(f"offline code path ran a subprocess: {args} {kwargs}")


@pytest.fixture(autouse=True)
def _no_declared_root(monkeypatch):
    """Root lookup must not be steered by whatever $AI_BADGER the developer exported."""
    monkeypatch.delenv("AI_BADGER", raising=False)


def test_find_root_walks_up_to_dir_with_schemas_and_features(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    fake_root = _make_root(tmp_path)
    nested = fake_root / "features" / "dotnet" / "skills" / "foo"
    nested.mkdir(parents=True)

    found = bl.find_root(nested)

    assert found == fake_root.resolve()


def test_find_root_raises_when_no_ancestor_and_no_fallback(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    lonely = tmp_path / "some" / "unrelated" / "dir"
    lonely.mkdir(parents=True)
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    with pytest.raises(bl.FrameworkRootNotFound):
        bl.find_root(lonely)


def test_find_root_never_touches_the_network(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    lonely = tmp_path / "unrelated"
    lonely.mkdir()
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")
    monkeypatch.setattr(bl.subprocess, "run", _forbidden_subprocess)

    with pytest.raises(bl.FrameworkRootNotFound):
        bl.find_root(lonely)


def test_find_root_failure_names_the_explicit_opt_in(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    lonely = tmp_path / "unrelated"
    lonely.mkdir()
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    with pytest.raises(bl.FrameworkRootNotFound) as excinfo:
        bl.find_root(lonely)

    message = str(excinfo.value)
    assert "--root" in message
    assert "ensure_root" in message and "allow_network" in message


def test_find_root_uses_an_existing_cache_without_network(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    lonely = tmp_path / "unrelated"
    lonely.mkdir()
    cache = _make_root(tmp_path / "cache")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
    monkeypatch.setattr(bl.subprocess, "run", _forbidden_subprocess)

    assert bl.find_root(lonely) == cache


# ------------------------------------------------------- resolve_framework_root (ADR-0007)
def test_a_catalog_without_the_engine_is_not_a_framework_root(tmp_path, load_script):
    """schemas/ + features/ alone is a catalog; a root also carries engine/badger_lib.py."""
    bl = load_script("engine/badger_lib.py")
    (tmp_path / "schemas").mkdir()
    (tmp_path / "features").mkdir()

    assert not bl.is_framework_root(tmp_path)
    assert bl.is_framework_root(_make_root(tmp_path))


def test_explicit_root_outranks_every_other_input(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    declared = _make_root(tmp_path / "declared")
    ancestor = _make_root(tmp_path / "ancestor")
    monkeypatch.setenv("AI_BADGER", str(_make_root(tmp_path / "env")))

    assert bl.resolve_framework_root(explicit=declared, start=ancestor) == declared.resolve()


def test_a_declared_root_that_is_not_a_root_refuses_rather_than_falls_through(
        tmp_path, load_script):
    """A wrong --root is a misconfiguration to report, not a reason to resolve something else."""
    bl = load_script("engine/badger_lib.py")
    ancestor = _make_root(tmp_path / "ancestor")
    wrong = tmp_path / "not-a-root"
    wrong.mkdir()

    with pytest.raises(bl.FrameworkRootNotFound) as excinfo:
        bl.resolve_framework_root(explicit=wrong, start=ancestor)

    assert str(wrong) in str(excinfo.value)


def test_the_ancestor_walk_outranks_the_env_var(tmp_path, load_script, monkeypatch):
    """A script inside a checkout uses that checkout's engine, whatever a shell profile says."""
    bl = load_script("engine/badger_lib.py")
    monkeypatch.setenv("AI_BADGER", str(_make_root(tmp_path / "env")))
    ancestor = _make_root(tmp_path / "ancestor")

    assert bl.resolve_framework_root(start=ancestor) == ancestor.resolve()


def test_the_env_var_answers_when_no_framework_stands_above_the_script(
        tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    env_root = _make_root(tmp_path / "env")
    lonely = tmp_path / "unrelated"
    lonely.mkdir()
    monkeypatch.setenv("AI_BADGER", str(env_root))

    assert bl.resolve_framework_root(start=lonely) == env_root.resolve()


def test_a_stale_env_var_refuses_rather_than_falls_through(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    stale = tmp_path / "moved-away"
    lonely = tmp_path / "unrelated"
    lonely.mkdir()
    monkeypatch.setenv("AI_BADGER", str(stale))

    with pytest.raises(bl.FrameworkRootNotFound) as excinfo:
        bl.resolve_framework_root(start=lonely)

    assert "AI_BADGER" in str(excinfo.value)


def test_a_scaffold_resolves_the_root_recorded_in_its_manifest(tmp_path, load_script,
                                                               monkeypatch):
    """The shape with no framework above it: only a recorded root can answer (ADR-0007)."""
    bl = load_script("engine/badger_lib.py")
    framework = _make_root(tmp_path / "framework")
    aib = _make_scaffold(tmp_path / "consumer", framework)
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    script = aib / "skills" / "welcome-ai-badger" / "scripts"
    script.mkdir(parents=True)

    assert bl.resolve_framework_root(start=script) == framework.resolve()


def test_a_hermes_plugin_resolves_the_root_recorded_beside_it(tmp_path, load_script,
                                                              monkeypatch):
    """Two loose files in ~/.hermes/plugins/ are answered by a record their installer wrote."""
    bl = load_script("engine/badger_lib.py")
    framework = _make_root(tmp_path / "framework")
    plugins = tmp_path / "home" / ".hermes" / "plugins"
    _make_scaffold(plugins, framework)
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    assert bl.resolve_framework_root(start=plugins / "learned_skills_sync.py") \
        == framework.resolve()


def test_a_manifest_above_the_working_directory_cannot_steer_resolution(
        tmp_path, load_script, monkeypatch):
    """A cloned repo must not put its own tree on the sys.path of a session-start hook (A1)."""
    bl = load_script("engine/badger_lib.py")
    attacker = _make_root(tmp_path / "hostile" / "vendor")
    _make_scaffold(tmp_path / "hostile", attacker)
    plugins = tmp_path / "home" / ".hermes" / "plugins"
    plugins.mkdir(parents=True)
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")
    monkeypatch.chdir(tmp_path / "hostile")

    with pytest.raises(bl.FrameworkRootNotFound):
        bl.resolve_framework_root(start=plugins / "learned_skills_sync.py")


def test_a_recorded_root_from_another_machine_is_ignored(tmp_path, load_script, monkeypatch):
    """A manifest is a hint, validated before use — a foreign path is not a root here."""
    bl = load_script("engine/badger_lib.py")
    aib = _make_scaffold(tmp_path / "consumer", Path("/nowhere/ai-badger"))
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    with pytest.raises(bl.FrameworkRootNotFound):
        bl.resolve_framework_root(start=aib)


def test_a_recorded_root_may_be_relative_to_the_scaffolded_project(tmp_path, load_script,
                                                                   monkeypatch):
    """A repo scaffolded by itself records `.` — the one value that survives a git clone."""
    bl = load_script("engine/badger_lib.py")
    project = _make_root(tmp_path / "self-hosted")
    aib = project / ".ai-badger"
    aib.mkdir()
    (aib / "manifest.json").write_text(json.dumps({"frameworkRoot": "."}), encoding="utf-8")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    assert bl.recorded_root(aib) == project.resolve()


def test_the_ancestor_walk_outranks_a_recorded_root(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    recorded = _make_root(tmp_path / "recorded")
    ancestor = _make_root(tmp_path / "ancestor")
    _make_scaffold(ancestor, recorded)
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "fake-cache")

    assert bl.resolve_framework_root(start=ancestor / ".ai-badger") == ancestor.resolve()


# ------------------------------------------- the cache reports its own version skew (ADR-0009)
def _scaffold_recording_version(project, version, framework_root=None):
    """A .ai-badger/ scaffold that records the framework version it was written by."""
    aib = project / ".ai-badger"
    aib.mkdir(parents=True, exist_ok=True)
    record = {"frameworkVersion": version}
    if framework_root is not None:
        record["frameworkRoot"] = str(framework_root)
    (aib / "manifest.json").write_text(json.dumps(record), encoding="utf-8")
    return aib


def test_a_stale_cache_names_both_versions_when_it_is_what_answered(
        tmp_path, load_script, monkeypatch, capsys):
    """The cache is never updated in place, so it can be many releases behind the scaffold."""
    bl = load_script("engine/badger_lib.py")
    cache = _make_root(tmp_path / "cache", version="0.13.0")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
    aib = _scaffold_recording_version(tmp_path / "consumer", "0.35.2")

    assert bl.resolve_framework_root(start=aib) == cache

    warning = capsys.readouterr().err
    assert "0.13.0" in warning and "0.35.2" in warning and str(cache) in warning


def test_a_stale_cache_warns_rather_than_refuses(tmp_path, load_script, monkeypatch, capsys):
    """This statement also runs inside session-start hooks, which must never break a session."""
    bl = load_script("engine/badger_lib.py")
    cache = _make_root(tmp_path / "cache", version="0.13.0")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
    aib = _scaffold_recording_version(tmp_path / "consumer", "0.35.2")

    resolved = bl.resolve_framework_root(start=aib)

    assert resolved == cache
    assert capsys.readouterr().err.strip()


def test_a_cache_that_matches_the_scaffold_says_nothing(
        tmp_path, load_script, monkeypatch, capsys):
    bl = load_script("engine/badger_lib.py")
    cache = _make_root(tmp_path / "cache", version="0.35.2")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
    aib = _scaffold_recording_version(tmp_path / "consumer", "0.35.2")

    assert bl.resolve_framework_root(start=aib) == cache
    assert capsys.readouterr().err == ""


def test_a_root_the_cache_did_not_answer_is_never_compared_against_it(
        tmp_path, load_script, monkeypatch, capsys):
    """A stale cache on the machine is irrelevant when something above the script answered."""
    bl = load_script("engine/badger_lib.py")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", _make_root(tmp_path / "cache", version="0.13.0"))
    ancestor = _make_root(tmp_path / "ancestor", version="0.35.2")

    assert bl.resolve_framework_root(start=ancestor) == ancestor.resolve()
    assert capsys.readouterr().err == ""


def test_a_scaffold_that_records_no_version_leaves_the_cache_unjudged(
        tmp_path, load_script, monkeypatch, capsys):
    """With nothing to compare against there is no skew to report, and silence is correct."""
    bl = load_script("engine/badger_lib.py")
    cache = _make_root(tmp_path / "cache", version="0.13.0")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
    plugins = tmp_path / "home" / ".hermes" / "plugins"
    _make_scaffold(plugins, tmp_path / "gone")

    assert bl.resolve_framework_root(start=plugins / "ai_badger_hooks.py") == cache
    assert capsys.readouterr().err == ""


def test_a_cache_without_a_version_file_is_left_unjudged(
        tmp_path, load_script, monkeypatch, capsys):
    bl = load_script("engine/badger_lib.py")
    cache = _make_root(tmp_path / "cache")
    monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
    aib = _scaffold_recording_version(tmp_path / "consumer", "0.35.2")

    assert bl.resolve_framework_root(start=aib) == cache
    assert capsys.readouterr().err == ""


class TestEnsureFrameworkCache:
    """ensure_root() is the only path allowed to reach the network, and only when pinned."""

    @staticmethod
    def _recording_clone(tmp_path, calls, returncode=0):
        """Stand in for git clone: record argv, materialise a usable root on success."""
        def fake_run(cmd, *args, **kwargs):  # pylint: disable=unused-argument
            calls.append(list(cmd))
            if returncode == 0:
                _make_root(tmp_path / "cache")
            return subprocess.CompletedProcess(cmd, returncode, "", "fatal: tag not found\n")
        return fake_run

    def test_returns_the_local_root_without_network_when_one_exists(
        self, tmp_path, load_script, monkeypatch,
    ):
        bl = load_script("engine/badger_lib.py")
        local = _make_root(tmp_path / "checkout")
        monkeypatch.setattr(bl.subprocess, "run", _forbidden_subprocess)

        assert bl.ensure_root(local, allow_network=True) == local

    def test_refuses_to_clone_without_allow_network(self, tmp_path, load_script, monkeypatch):
        bl = load_script("engine/badger_lib.py")
        lonely = tmp_path / "unrelated"
        lonely.mkdir()
        monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "cache")
        monkeypatch.setattr(bl.subprocess, "run", _forbidden_subprocess)

        with pytest.raises(bl.FrameworkRootNotFound):
            bl.ensure_root(lonely)

    def test_clones_pinned_to_the_release_tag(self, tmp_path, load_script, monkeypatch):
        bl = load_script("engine/badger_lib.py")
        calls = []
        monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "cache")
        monkeypatch.setattr(bl.subprocess, "run", self._recording_clone(tmp_path, calls))

        found = bl.ensure_root(tmp_path / "unrelated", allow_network=True, version="0.20.0")

        assert found == tmp_path / "cache"
        assert calls, "no git command ran"
        argv = calls[0]
        assert argv[:2] == ["git", "clone"]
        assert "--branch" in argv and "ai-badger--v0.20.0" in argv
        assert bl.FRAMEWORK_REPO in argv

    def test_refuses_to_clone_when_the_release_version_is_unknown(
        self, tmp_path, load_script, monkeypatch,
    ):
        bl = load_script("engine/badger_lib.py")
        lonely = tmp_path / "unrelated"
        lonely.mkdir()
        monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "cache")
        monkeypatch.setattr(bl.subprocess, "run", _forbidden_subprocess)

        with pytest.raises(bl.FrameworkRootNotFound) as excinfo:
            bl.ensure_root(lonely, allow_network=True, version=None)

        assert "version" in str(excinfo.value).lower()

    def test_takes_the_version_from_the_installed_tree_when_not_given(
        self, tmp_path, load_script, monkeypatch,
    ):
        bl = load_script("engine/badger_lib.py")
        installed = tmp_path / "plugin"
        (installed / "engine").mkdir(parents=True)
        (installed / "VERSION").write_text("0.19.0\n", encoding="utf-8")
        calls = []
        monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "cache")
        monkeypatch.setattr(bl.subprocess, "run", self._recording_clone(tmp_path, calls))

        bl.ensure_root(installed / "engine", allow_network=True)

        assert "ai-badger--v0.19.0" in calls[0]

    def test_an_unusable_cache_is_reported_not_silently_updated(
        self, tmp_path, load_script, monkeypatch,
    ):
        bl = load_script("engine/badger_lib.py")
        cache = tmp_path / "cache"
        (cache / ".git").mkdir(parents=True)  # a clone that is missing schemas/ + features/
        monkeypatch.setattr(bl, "FRAMEWORK_CACHE", cache)
        monkeypatch.setattr(bl.subprocess, "run", _forbidden_subprocess)

        with pytest.raises(bl.FrameworkRootNotFound) as excinfo:
            bl.ensure_root(tmp_path / "unrelated", allow_network=True, version="0.20.0")

        assert str(cache) in str(excinfo.value)

    def test_a_failed_clone_reports_git_stderr(self, tmp_path, load_script, monkeypatch):
        bl = load_script("engine/badger_lib.py")
        monkeypatch.setattr(bl, "FRAMEWORK_CACHE", tmp_path / "cache")
        monkeypatch.setattr(bl.subprocess, "run",
                            self._recording_clone(tmp_path, [], returncode=128))

        with pytest.raises(bl.FrameworkRootNotFound) as excinfo:
            bl.ensure_root(tmp_path / "unrelated", allow_network=True, version="0.14.1")

        assert "fatal: tag not found" in str(excinfo.value)


def test_dump_json_is_atomic_under_write_failure(tmp_path, load_script, monkeypatch):
    bl = load_script("engine/badger_lib.py")
    path = tmp_path / "manifest.json"
    path.write_text('{"entries": ["the user\'s data"]}\n', encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    def exploding_replace(*args, **kwargs):  # pylint: disable=unused-argument
        raise OSError("disk full")

    monkeypatch.setattr(bl.os, "replace", exploding_replace)

    with pytest.raises(OSError):
        bl.dump_json(path, {"entries": []})

    assert path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob("*.tmp"))


def test_dump_json_leaves_the_target_untouched_when_serialisation_fails(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    path = tmp_path / "index.json"
    path.write_text('{"generated": true}\n', encoding="utf-8")

    with pytest.raises(TypeError):
        bl.dump_json(path, {"bad": object()})

    assert path.read_text(encoding="utf-8") == '{"generated": true}\n'
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_text_preserves_the_file_mode(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    path = tmp_path / "hook.sh"
    path.write_text("old\n", encoding="utf-8")
    path.chmod(0o755)

    bl.atomic_write_text(path, "new\n")

    assert path.read_text(encoding="utf-8") == "new\n"
    assert path.stat().st_mode & 0o777 == 0o755


def test_atomic_write_text_creates_missing_parents(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    path = tmp_path / "a" / "b" / "c.json"

    bl.atomic_write_text(path, "{}\n")

    assert path.read_text(encoding="utf-8") == "{}\n"


def test_find_root_default_start_resolves_the_real_framework_root(load_script, root):
    bl = load_script("engine/badger_lib.py")

    found = bl.find_root()

    assert found == root.resolve()


def test_load_json_dump_json_roundtrip(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    path = tmp_path / "data.json"
    data = {"b": 2, "a": [1, 2, 3], "nested": {"x": "y"}}

    bl.dump_json(path, data)
    loaded = bl.load_json(path)

    assert loaded == data


def test_dump_json_is_pretty_printed_and_newline_terminated(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    path = tmp_path / "data.json"

    bl.dump_json(path, {"a": 1})
    text = path.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert "\n  " in text  # indent=2 produces indented lines for multi-key/nested data


def test_sha256_text_matches_hashlib(load_script):
    bl = load_script("engine/badger_lib.py")

    assert bl.sha256_text("hello") == hashlib.sha256(b"hello").hexdigest()


def test_sha256_file_matches_hashlib_for_a_file(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    f = tmp_path / "f.txt"
    f.write_bytes(b"some bytes")

    assert bl.sha256_file(f) == hashlib.sha256(b"some bytes").hexdigest()


def test_sha256_file_is_deterministic_for_a_directory(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("A", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_text("B", encoding="utf-8")

    first = bl.sha256_file(d)
    second = bl.sha256_file(d)

    assert first == second


def test_sha256_file_directory_hash_changes_when_content_changes(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("A", encoding="utf-8")
    before = bl.sha256_file(d)

    (d / "a.txt").write_text("A-changed", encoding="utf-8")
    after = bl.sha256_file(d)

    assert before != after


def test_sha256_file_directory_hash_depends_on_relative_names_not_absolute_path(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    d1 = tmp_path / "one" / "d"
    d1.mkdir(parents=True)
    (d1 / "a.txt").write_text("A", encoding="utf-8")

    d2 = tmp_path / "two" / "somewhere" / "d"
    d2.mkdir(parents=True)
    (d2 / "a.txt").write_text("A", encoding="utf-8")

    assert bl.sha256_file(d1) == bl.sha256_file(d2)


def test_read_index_loads_index_json_from_root(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    (tmp_path / "index.json").write_text(json.dumps({"frameworkVersion": "1.0.0", "stacks": {}}),
                                          encoding="utf-8")

    idx = bl.read_index(tmp_path)

    assert idx["frameworkVersion"] == "1.0.0"


def test_validate_returns_empty_list_when_instance_is_valid(load_script):
    bl = load_script("engine/badger_lib.py")
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}

    errors = bl.validate({"name": "ok"}, schema)

    assert errors == []


def test_validate_returns_readable_sorted_errors_when_instance_is_invalid(load_script):
    bl = load_script("engine/badger_lib.py")
    schema = {
        "type": "object",
        "required": ["name", "age"],
        "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
    }

    errors = bl.validate({"age": "not-a-number"}, schema)

    assert len(errors) >= 1
    assert any("age" in e for e in errors)


def test_validate_file_reads_both_json_files_and_validates(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    schema_path = tmp_path / "s.schema.json"
    schema_path.write_text(json.dumps({"type": "object", "required": ["x"]}), encoding="utf-8")
    instance_path = tmp_path / "i.json"
    instance_path.write_text(json.dumps({"x": 1}), encoding="utf-8")

    assert bl.validate_file(instance_path, schema_path) == []

    instance_path.write_text(json.dumps({}), encoding="utf-8")
    assert bl.validate_file(instance_path, schema_path) != []


def test_check_schemas_selfvalid_accepts_the_real_framework_schemas(root, load_script):
    bl = load_script("engine/badger_lib.py")

    problems = bl.check_schemas_selfvalid(root / "schemas")

    assert problems == []


def test_check_schemas_selfvalid_flags_a_broken_schema(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    (tmp_path / "broken.schema.json").write_text(
        json.dumps({"type": "not-a-real-type"}), encoding="utf-8"
    )

    problems = bl.check_schemas_selfvalid(tmp_path)

    assert len(problems) == 1
    assert "broken.schema.json" in problems[0]


# ---------------------------------------------------------------- feature type registry
def test_features_is_derived_from_the_registry(load_script):
    bl = load_script("engine/badger_lib.py")

    assert bl.FEATURES == [ft.name for ft in bl.FEATURE_TYPES]


def test_every_feature_type_is_looked_up_by_name(load_script):
    bl = load_script("engine/badger_lib.py")

    for ft in bl.FEATURE_TYPES:
        assert bl.feature_type(ft.name) is ft


def test_md_carrying_feature_types_are_the_ones_indexed_as_markdown(load_script):
    bl = load_script("engine/badger_lib.py")

    md = [ft.name for ft in bl.FEATURE_TYPES if ft.md_carrying]

    assert md == ["personas", "invariants", "instructions"]
    assert all(bl.feature_type(name).index_rule == "md" for name in md)


def test_only_feature_types_scaffold_records_by_index_name_are_reported_as_new(load_script):
    """Templates, hooks and adjustments land under names of their own; drift must stay quiet."""
    bl = load_script("engine/badger_lib.py")

    assert bl.DRIFT_NEW_FEATURES == tuple(
        ft.name for ft in bl.FEATURE_TYPES if ft.drift_reports_new
    )
    assert bl.DRIFT_NEW_FEATURES == ("skills", "personas", "invariants", "instructions")


def test_iter_feature_dirs_returns_empty_list_when_no_features_dir(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")

    assert bl.iter_feature_dirs(tmp_path) == []


def test_iter_feature_dirs_yields_stack_feature_dir_tuples_in_sorted_order(tmp_path, load_script):
    bl = load_script("engine/badger_lib.py")
    features = tmp_path / "features"
    (features / "dotnet" / "skills").mkdir(parents=True)
    (features / "dotnet" / "personas").mkdir(parents=True)
    (features / "azure" / "invariants").mkdir(parents=True)
    # a stray, non-FEATURES subdir must be ignored
    (features / "dotnet" / "not-a-feature").mkdir(parents=True)

    found = bl.iter_feature_dirs(tmp_path)

    stacks_features = [(s, f) for s, f, _ in found]
    # stacks sorted alphabetically; within a stack, features in FEATURES order (skills first)
    assert stacks_features == [
        ("azure", "invariants"),
        ("dotnet", "skills"),
        ("dotnet", "personas"),
    ]


# ---------------------------------------------------------------- dir_content_hash
def test_dir_content_hash_excludes_patterns(tmp_path, load_script):
    """Files matching exclude patterns are not included in the hash."""
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    d.mkdir()
    (d / "SKILL.md").write_text("content\n")
    (d / "scripts").mkdir()
    (d / "scripts" / "main.py").write_text("print('hi')\n")
    (d / "tests").mkdir()
    (d / "tests" / "test_main.py").write_text("assert True\n")
    (d / "evals").mkdir()
    (d / "evals" / "evals.json").write_text("{}\n")

    result = bl.dir_content_hash(d, exclude=["tests", "evals"])

    assert result["file_count"] == 2  # SKILL.md + scripts/main.py
    assert result["dir_count"] >= 1   # scripts/
    assert result["content_hash"]  # non-empty


def test_dir_content_hash_deterministic(tmp_path, load_script):
    """Same directory content produces the same hash."""
    bl = load_script("engine/badger_lib.py")
    d1 = tmp_path / "a"
    d1.mkdir()
    (d1 / "file.md").write_text("hello\n")
    d2 = tmp_path / "b"
    d2.mkdir()
    (d2 / "file.md").write_text("hello\n")

    h1 = bl.dir_content_hash(d1)
    h2 = bl.dir_content_hash(d2)

    assert h1["content_hash"] == h2["content_hash"]
    assert h1["file_count"] == h2["file_count"]


def test_dir_content_hash_differs_on_content_change(tmp_path, load_script):
    """Changed file content produces a different hash."""
    bl = load_script("engine/badger_lib.py")
    d1 = tmp_path / "a"
    d1.mkdir()
    (d1 / "file.md").write_text("v1\n")
    d2 = tmp_path / "b"
    d2.mkdir()
    (d2 / "file.md").write_text("v2\n")

    h1 = bl.dir_content_hash(d1)
    h2 = bl.dir_content_hash(d2)

    assert h1["content_hash"] != h2["content_hash"]


def test_dir_content_hash_same_when_excluded_files_differ(tmp_path, load_script):
    """Excluded files (tests, evals) don't affect the hash."""
    bl = load_script("engine/badger_lib.py")
    d1 = tmp_path / "a"
    d1.mkdir()
    (d1 / "SKILL.md").write_text("content\n")
    (d1 / "tests").mkdir()
    (d1 / "tests" / "test_v1.py").write_text("v1\n")
    d2 = tmp_path / "b"
    d2.mkdir()
    (d2 / "SKILL.md").write_text("content\n")
    (d2 / "tests").mkdir()
    (d2 / "tests" / "test_v2.py").write_text("v2\n")

    h1 = bl.dir_content_hash(d1, exclude=["tests"])
    h2 = bl.dir_content_hash(d2, exclude=["tests"])

    assert h1["content_hash"] == h2["content_hash"]


def test_dir_content_hash_exclude_rel_skips_that_path_only(tmp_path, load_script):
    """`exclude_rel` names one path, so a namesake elsewhere in the tree is still hashed."""
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    (d / "scripts").mkdir(parents=True)
    (d / "vendor").mkdir()
    (d / "SKILL.md").write_text("content\n")
    (d / "scripts" / "bm25.py").write_text("placed by an adjustment\n")
    (d / "vendor" / "bm25.py").write_text("the project's own\n")

    result = bl.dir_content_hash(d, exclude_rel=["scripts/bm25.py"])

    assert result["file_count"] == 2  # SKILL.md + vendor/bm25.py
    (d / "scripts" / "bm25.py").write_text("a later framework version\n")
    assert bl.dir_content_hash(d, exclude_rel=["scripts/bm25.py"]) == result


def test_dir_content_hash_exclude_rel_skips_a_whole_subtree(tmp_path, load_script):
    """Naming a directory in `exclude_rel` skips everything under it."""
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    (d / "extras" / "deep").mkdir(parents=True)
    (d / "SKILL.md").write_text("content\n")
    (d / "extras" / "one.py").write_text("1\n")
    (d / "extras" / "deep" / "two.py").write_text("2\n")

    result = bl.dir_content_hash(d, exclude_rel=["extras"])

    assert result["file_count"] == 1
    assert result["content_hash"] == bl.dir_content_hash(d, exclude=["extras"])["content_hash"]


def test_dir_content_hash_still_counts_a_directory_a_nested_entry_created(tmp_path, load_script):
    """dir_count describes the tree on disk; the caller decides when it is comparable (#230).

    Replaces a test that asserted the opposite. Pruning those directories tried to reconstruct
    the recorded count and got it wrong in the other direction whenever the source skill had
    shipped an empty directory, so the reconstruction was dropped and drift stopped comparing
    the number instead.
    """
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    (d / "generated" / "newdir").mkdir(parents=True)
    (d / "SKILL.md").write_text("content\n")
    (d / "generated" / "newdir" / "file.py").write_text("nested\n")

    result = bl.dir_content_hash(d, exclude_rel=["generated/newdir/file.py"])

    assert result["file_count"] == 1, "the owned file is still excluded"
    assert result["dir_count"] == 2, "the directories are still on disk"


def test_dir_content_hash_keeps_a_directory_that_also_holds_an_owned_file(tmp_path, load_script):
    """The prune must not swallow a directory the skill itself put a file in."""
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "mine.py").write_text("owned\n")
    (d / "scripts" / "adjusted.py").write_text("nested\n")

    result = bl.dir_content_hash(d, exclude_rel=["scripts/adjusted.py"])

    assert result["file_count"] == 1
    assert result["dir_count"] == 1, "scripts/ holds an owned file, so it is still structure"


def test_dir_content_hash_ignores_an_exclude_rel_naming_the_directory_itself(
        tmp_path, load_script):
    """"" and "." are every path's ancestor; honouring them would hash nothing at all."""
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text("content\n")
    (d / "scripts" / "helper.py").write_text("helper\n")
    baseline = bl.dir_content_hash(d)

    for degenerate in ("", "."):
        assert bl.dir_content_hash(d, exclude_rel=[degenerate]) == baseline, degenerate


def test_skill_exclude_patterns_ignore_os_droppings(tmp_path, load_script):
    """A .DS_Store dropped beside a skill's files is not a change to the skill."""
    bl = load_script("engine/badger_lib.py")
    d = tmp_path / "skill"
    d.mkdir()
    (d / "SKILL.md").write_text("content\n")
    before = bl.dir_content_hash(d, exclude=bl.SKILL_EXCLUDE_PATTERNS)

    (d / ".DS_Store").write_bytes(b"\x00\x01macos")

    assert bl.dir_content_hash(d, exclude=bl.SKILL_EXCLUDE_PATTERNS) == before


# ---------------------------------------------------------------- nested_entry_targets
def test_nested_entry_targets_finds_what_another_entry_owns(load_script):
    """Paths another manifest entry wrote inside this directory, relative to it."""
    bl = load_script("engine/badger_lib.py")
    entries = [
        {"target": ".ai-badger/skills/mcp-index"},
        {"target": ".ai-badger/skills/mcp-index/scripts/bm25.py"},
        {"target": ".ai-badger/skills/task/SKILL.md"},
    ]

    assert bl.nested_entry_targets(entries, ".ai-badger/skills/mcp-index") == ["scripts/bm25.py"]


def test_nested_entry_targets_is_not_fooled_by_a_shared_prefix(load_script):
    """A sibling whose name merely starts with the directory's name is not inside it."""
    bl = load_script("engine/badger_lib.py")
    entries = [{"target": ".ai-badger/skills/mcp-index-extras/notes.md"}]

    assert bl.nested_entry_targets(entries, ".ai-badger/skills/mcp-index") == []


def test_nested_entry_targets_excludes_the_directory_itself(load_script):
    """The entry that owns the directory must not exclude the directory from its own hash."""
    bl = load_script("engine/badger_lib.py")
    entries = [{"target": ".ai-badger/skills/mcp-index"}]

    assert bl.nested_entry_targets(entries, ".ai-badger/skills/mcp-index") == []

class TestResolveStacks:
    """The always-included catalog stack is config data, not a literal in each script."""

    def test_defaults_to_common_first(self, load_script):
        bl = load_script("engine/badger_lib.py")

        assert bl.resolve_stacks({"stacks": ["python", "github"]}) == \
            ["common", "python", "github"]

    def test_config_names_the_common_stack(self, load_script):
        bl = load_script("engine/badger_lib.py")

        assert bl.resolve_stacks({"commonStacks": "shared", "stacks": ["python"]}) == \
            ["shared", "python"]

    def test_config_may_name_several(self, load_script):
        bl = load_script("engine/badger_lib.py")

        assert bl.resolve_stacks({"commonStacks": ["common", "house"], "stacks": ["python"]}) == \
            ["common", "house", "python"]

    def test_duplicates_collapse_and_order_is_kept(self, load_script):
        bl = load_script("engine/badger_lib.py")

        assert bl.resolve_stacks({"stacks": ["python", "common", "python"]}) == \
            ["common", "python"]

    def test_empty_common_stacks_resolves_to_the_configured_stacks_only(self, load_script):
        bl = load_script("engine/badger_lib.py")

        assert bl.resolve_stacks({"commonStacks": [], "stacks": ["python"]}) == ["python"]


def test_scaffolded_skill_names_ignores_extension_provenance_rows(load_script):
    """A manifest row naming `<skill>/extensions/...` is provenance, not a distinct skill."""
    bl = load_script("engine/badger_lib.py")
    manifest = {"entries": [
        {"feature": "skills", "name": "task"},
        {"feature": "skills", "name": "task/extensions/claude/extension.md"},
        {"feature": "personas", "name": "architect"},
    ]}

    assert bl.scaffolded_skill_names(manifest) == ["task"]


def test_scaffolded_skill_names_refuses_a_manifest_that_is_not_an_object(load_script):
    """A corrupt manifest yields no skills rather than an AttributeError."""
    bl = load_script("engine/badger_lib.py")

    assert bl.scaffolded_skill_names([1, 2, 3]) == []
    assert bl.scaffolded_skill_names({"entries": "not-a-list"}) == []
    assert bl.scaffolded_skill_names({"entries": [{"feature": "skills"}]}) == []


class TestConfigHash:
    """Issue #128: a config-only edit must be detectable, without formatting noise."""

    def _config(self, **overrides):
        base = {
            "$schema": "./schemas/config.schema.json",
            "frameworkVersion": "0.45.0",
            "project": {"name": "p", "summary": "s", "domain": "d"},
            "stacks": ["python"],
            "agents": ["claude"],
        }
        base.update(overrides)
        return base

    def test_config_hash_is_stable_across_key_order_and_whitespace(self, load_script):
        bl = load_script("engine/badger_lib.py")
        config = self._config()
        reordered = dict(reversed(list(config.items())))

        assert bl.config_hash(config) == bl.config_hash(reordered)

    def test_config_hash_ignores_the_framework_version_stamp(self, load_script):
        bl = load_script("engine/badger_lib.py")
        at_0_45 = self._config(frameworkVersion="0.45.0")
        at_0_46 = self._config(frameworkVersion="0.46.0")

        assert bl.config_hash(at_0_45) == bl.config_hash(at_0_46)

    def test_config_hash_changes_when_an_exclusion_is_added(self, load_script):
        bl = load_script("engine/badger_lib.py")
        before = self._config()
        after = self._config(exclude={"invariants": ["tdd-mandatory"]})

        assert bl.config_hash(before) != bl.config_hash(after)
