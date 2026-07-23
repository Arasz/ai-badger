"""Tests for skills/welcome-ai-badger/scripts/detect.py.

Covers data-driven stack detection from detectionSignals, ignore-dir exclusion,
dependency-based detection, expand_requires, and agent/source-control/command detection.
"""
from __future__ import annotations

import json
import subprocess


def _index(stacks: dict) -> dict:
    """A minimal synthetic index.json body: just enough for detect_stacks/expand_requires."""
    return {"frameworkVersion": "0.0.0", "stacks": stacks}


def _stack(detection_signals=None, requires=None) -> dict:
    meta = {}
    if detection_signals is not None:
        meta["detectionSignals"] = detection_signals
    if requires is not None:
        meta["requires"] = requires
    return {"meta": meta}


# --------------------------------------------------------------------- detect_stacks (glob)
def test_detect_stacks_matches_data_driven_glob_signal(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = _index({"widget": _stack(detection_signals=["*.widget"])})
    (tmp_path / "thing.widget").write_text("x", encoding="utf-8")

    assert detect.detect_stacks(tmp_path, index) == ["widget"]


def test_detect_stacks_no_match_when_signal_absent(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = _index({"widget": _stack(detection_signals=["*.widget"])})
    (tmp_path / "unrelated.txt").write_text("x", encoding="utf-8")

    assert detect.detect_stacks(tmp_path, index) == []


def test_detect_stacks_skips_common_stack(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = _index({"common": _stack(detection_signals=["*.md"])})
    (tmp_path / "README.md").write_text("x", encoding="utf-8")

    # "common" is always scaffolded separately by scaffold.py; detect_stacks must not report it
    assert detect.detect_stacks(tmp_path, index) == []


def test_detect_stacks_prose_signals_with_spaces_are_not_used_as_globs(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    # a prose-only signal (contains spaces) can never match a file glob; must not error or match
    index = _index({"widget": _stack(detection_signals=["widget usage present"])})
    (tmp_path / "widget usage present").write_text("x", encoding="utf-8")

    assert detect.detect_stacks(tmp_path, index) == []


# ------------------------------------------------------------- ignore-dir exclusion (real index)
def test_detect_stacks_ignores_claude_dir_python_scripts(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    scripts_dir = tmp_path / ".claude" / "skills" / "task" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "tracker.py").write_text("# agent tooling\n", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "python" not in stacks


def test_detect_stacks_ignores_ai_badger_dir_python_scripts(tmp_path, load_script, root):
    """The framework's own scaffolded output (.ai-badger/skills/.../scripts/*.py) must never be
    re-detected as the target project's stack -- that's a self-inflicted false positive that
    would get worse on every re-scaffold."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    scripts_dir = tmp_path / ".ai-badger" / "skills" / "task" / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "tracker_lib.py").write_text("# agent tooling\n", encoding="utf-8")
    markers_dir = tmp_path / ".ai-badger" / "skills" / "prompt-markers" / "scripts"
    markers_dir.mkdir(parents=True)
    (markers_dir / "markers.py").write_text("# agent tooling\n", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "python" not in stacks


def test_detect_stacks_ignores_node_modules_and_venv_contents(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    nm = tmp_path / "node_modules" / "some-pkg"
    nm.mkdir(parents=True)
    (nm / "setup.cfg").write_text("[metadata]\n", encoding="utf-8")

    venv = tmp_path / ".venv" / "lib" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "requirements.txt").write_text("foo==1.0\n", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "python" not in stacks


def test_detect_stacks_bare_node_modules_dir_is_excluded_from_its_own_signal(tmp_path, load_script, root):
    """node_modules is both a node detectionSignal AND an ignored dir: an empty node_modules/
    alone (no package.json) does not trigger node, since the ignore-dir check excludes the
    match itself. Documents current behavior; node is still detected normally via package.json."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    (tmp_path / "node_modules").mkdir()

    stacks = detect.detect_stacks(tmp_path, index)

    assert "node" not in stacks


# -------------------------------------------------------------- real python-project detection
def test_detect_stacks_python_via_pyproject_toml(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "python" in stacks


def test_detect_stacks_dotnet_via_csproj(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    (tmp_path / "App.csproj").write_text("<Project />", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "dotnet" in stacks
    assert "python" not in stacks


# --------------------------------------------------------------------- dependency-based stacks
def test_detect_stacks_react_via_package_json_dependency(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "react" in stacks


def test_detect_stacks_ts_via_package_json_dev_dependency(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"typescript": "^5.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "ts" in stacks


def test_detect_stacks_angular_via_scoped_dependency(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@angular/core": "^17.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "angular" in stacks


def test_detect_stacks_angular_via_angular_json_presence(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "angular.json").write_text("{}", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "angular" in stacks


def test_detect_stacks_cosmos_via_package_json_dependency(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@azure/cosmos": "^4.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "cosmos" in stacks


def test_detect_stacks_cosmos_via_csproj_content(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "App.csproj").write_text(
        '<Project><ItemGroup><PackageReference Include="Microsoft.Azure.Cosmos" /></ItemGroup>'
        "</Project>", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "cosmos" in stacks


def test_detect_stacks_azure_via_dependency_name_substring(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@azure/functions": "^4.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "azure" in stacks


def test_detect_stacks_angular_via_package_json_in_subdirectory(tmp_path, load_script, root):
    """Monorepo case (GitHub issue Arasz/ai-badger#15 follow-up): Angular living in a
    subdirectory (e.g. frontend/) must still be detected -- dependency checks must not be
    root-only. Verified against a real monorepo (arasz-home-page) where this was missed."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"dependencies": {"@angular/core": "^17.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "angular" in stacks


def test_detect_stacks_angular_via_angular_json_in_subdirectory(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "angular.json").write_text("{}", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "angular" in stacks


def test_detect_stacks_react_via_package_json_in_subdirectory(tmp_path, load_script, root):
    """The monorepo-aware package.json scan is stack-agnostic: any dependency-detected stack
    (not just angular) must be found from a nested package.json."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "react" in stacks


def test_detect_stacks_package_json_under_node_modules_is_ignored(tmp_path, load_script, root):
    """A dependency's own package.json (vendored under node_modules/) must never contribute a
    stack -- only the target project's own package.json files matter."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    vendored = tmp_path / "node_modules" / "@angular" / "core"
    vendored.mkdir(parents=True)
    (vendored / "package.json").write_text(
        json.dumps({"dependencies": {"@angular/core": "^17.0.0"}}), encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert "angular" not in stacks


def test_detect_stacks_dedupes_when_glob_and_dependency_both_match(tmp_path, load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}}), encoding="utf-8")
    (tmp_path / "App.tsx").write_text("export default {};\n", encoding="utf-8")

    stacks = detect.detect_stacks(tmp_path, index)

    assert stacks.count("react") == 1


# --------------------------------------------------- catalog-wide detectionSignals glob guard
def test_all_catalog_detection_signals_are_glob_shaped(load_script, root):
    """Prose detectionSignals (e.g. "@angular/core in package.json dependencies") silently drop
    out of _signal_globs() -- containing a space makes them un-matchable as a file glob -- so a
    stack.json written with prose-only signals never gets data-driven detection at all (this is
    exactly how angular went undetected everywhere, GitHub issue Arasz/ai-badger#15 follow-up).
    Every features/*/stack.json must list only real, space-free glob signals; facts that can't
    be expressed as a glob (a dependency, file content) belong in _dependency_stacks() instead,
    not in detectionSignals."""
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    offenders = []
    for stack, data in index.get("stacks", {}).items():
        for signal in data.get("meta", {}).get("detectionSignals", []):
            if " " in signal:
                offenders.append(f"{stack}: {signal!r}")

    assert not offenders, (
        "prose (space-containing) detectionSignals found -- these never match as globs:\n"
        + "\n".join(offenders)
    )


# ------------------------------------------------------------------------- expand_requires
def test_expand_requires_transitive_closure(load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = _index({
        "a": _stack(requires=["b"]),
        "b": _stack(requires=["c"]),
        "c": _stack(requires=[]),
    })

    assert detect.expand_requires(["a"], index) == ["a", "b", "c"]


def test_expand_requires_does_not_duplicate_already_present_stack(load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = _index({
        "a": _stack(requires=["b"]),
        "b": _stack(requires=[]),
    })

    assert detect.expand_requires(["a", "b"], index) == ["a", "b"]


def test_expand_requires_unknown_stack_is_left_as_is(load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = _index({})

    assert detect.expand_requires(["mystery"], index) == ["mystery"]


def test_expand_requires_react_pulls_in_ts_and_node_from_real_index(load_script, root):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    index = detect.bl.read_index(root)

    expanded = detect.expand_requires(["react"], index)

    assert set(expanded) == {"react", "ts", "node"}


# ---------------------------------------------------------------------------- detect_agents
def test_detect_agents_claude_via_claude_md(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    (tmp_path / "CLAUDE.md").write_text("# guidance\n", encoding="utf-8")

    assert detect.detect_agents(tmp_path) == ["claude"]


def test_detect_agents_copilot_via_instructions_dir(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    (tmp_path / ".github" / "instructions").mkdir(parents=True)

    assert "copilot" in detect.detect_agents(tmp_path)


def test_detect_agents_junie_via_agents_md(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    (tmp_path / "AGENTS.md").write_text("# guidance\n", encoding="utf-8")

    assert "junie" in detect.detect_agents(tmp_path)


def test_detect_agents_junie_via_dot_junie_dir(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    (tmp_path / ".junie").mkdir()

    assert "junie" in detect.detect_agents(tmp_path)


def test_detect_agents_defaults_to_claude_when_nothing_found(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))

    assert detect.detect_agents(tmp_path) == ["claude"]


def test_detect_agents_claude_via_user_home_dot_claude(tmp_path, load_script, monkeypatch):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    fake_home = tmp_path / "fake-home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: fake_home))
    empty_target = tmp_path / "target"
    empty_target.mkdir()

    assert detect.detect_agents(empty_target) == ["claude"]


# ------------------------------------------------------------------- detect_source_control
def test_detect_source_control_no_git_dir(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")

    sc = detect.detect_source_control(tmp_path)

    assert sc == {"platform": "none", "repoUrl": None, "projectUrl": None}


def test_detect_source_control_git_dir_without_remote(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    (tmp_path / ".git").mkdir()

    sc = detect.detect_source_control(tmp_path)

    assert sc["platform"] == "none"
    assert sc["repoUrl"] is None


def test_detect_source_control_github_ssh_remote_normalized(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:someuser/somerepo.git"],
                    cwd=tmp_path, check=True)

    sc = detect.detect_source_control(tmp_path)

    assert sc["platform"] == "github"
    assert sc["repoUrl"] == "https://github.com/someuser/somerepo"


def test_detect_source_control_gitlab_https_remote(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://gitlab.com/someuser/somerepo.git"],
                    cwd=tmp_path, check=True)

    sc = detect.detect_source_control(tmp_path)

    assert sc["platform"] == "gitlab"
    assert sc["repoUrl"] == "https://gitlab.com/someuser/somerepo"


def test_detect_source_control_azure_devops_remote(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://dev.azure.com/org/proj/_git/repo"],
        cwd=tmp_path, check=True)

    sc = detect.detect_source_control(tmp_path)

    assert sc["platform"] == "azure-devops"
    assert sc["repoUrl"] == "https://dev.azure.com/org/proj/_git/repo"


# ------------------------------------------------------------------------ detect_commands
def test_detect_commands_dotnet_defaults_without_package_json(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")

    cmds = detect.detect_commands(tmp_path, ["dotnet"])

    assert cmds == {"build": "dotnet build", "test": "dotnet test"}


def test_detect_commands_npm_scripts_without_bun_lock(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"build": "vite build", "test": "vitest", "lint": "eslint .", "dev": "vite"}
    }), encoding="utf-8")

    cmds = detect.detect_commands(tmp_path, [])

    assert cmds == {
        "build": "npm run build", "test": "npm run test",
        "lint": "npm run lint", "run": "npm run dev",
    }


def test_detect_commands_bun_scripts_with_bun_lock(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"build": "vite build", "test": "vitest"}
    }), encoding="utf-8")
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")

    cmds = detect.detect_commands(tmp_path, [])

    assert cmds["build"] == "bun run build"
    assert cmds["test"] == "bun run test"


def test_detect_commands_run_prefers_dev_over_start(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"dev": "vite", "start": "node server.js"}
    }), encoding="utf-8")

    cmds = detect.detect_commands(tmp_path, [])

    assert cmds["run"] == "npm run dev"


def test_detect_commands_run_falls_back_to_start(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"start": "node server.js"}
    }), encoding="utf-8")

    cmds = detect.detect_commands(tmp_path, [])

    assert cmds["run"] == "npm run start"


def test_detect_commands_dotnet_setdefault_does_not_override_package_json(tmp_path, load_script):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"build": "vite build"}
    }), encoding="utf-8")
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")

    cmds = detect.detect_commands(tmp_path, ["dotnet"])

    assert cmds["build"] == "bun run build"  # package.json script wins
    assert cmds["test"] == "dotnet test"     # dotnet default fills the gap


# ------------------------------------------------------------------------------- main()
def test_main_emits_valid_proposed_config_json(tmp_path, load_script, root, monkeypatch, capsys):
    detect = load_script("features/common/skills/welcome-ai-badger/scripts/detect.py")
    monkeypatch.setattr(detect.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    target = tmp_path / "target-repo"
    target.mkdir()
    (target / "App.csproj").write_text("<Project />", encoding="utf-8")

    rc = detect.main(["--target", str(target), "--root", str(root)])

    assert rc == 0
    proposed = json.loads(capsys.readouterr().out)
    assert proposed["project"]["name"] == "target-repo"
    assert "dotnet" in proposed["stacks"]
    assert proposed["agents"] == ["claude"]
    assert proposed["sourceControl"]["platform"] == "none"
    assert proposed["commands"] == {"build": "dotnet build", "test": "dotnet test"}
