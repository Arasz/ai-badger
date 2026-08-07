"""Tests for gates/workflow_lint.py: pinned `uses:` refs and declared `permissions:` blocks.

0.97.0 pinned nine action references by hand, honouring
`features/github/invariants/pin-actions-to-sha.md`, and nothing enforced it — which is how the
same invariant shipped violated nine times over within hours of being written. Every test here
asserts a verdict in both directions: a fixture that fails clean would prove nothing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SCRIPT = Path(__file__).resolve().parents[1] / "gates" / "workflow_lint.py"


@pytest.fixture(name="lint")
def _lint(load_script):
    return load_script("gates/workflow_lint.py")


def _workflow(root: Path, text: str, name: str = "ci.yml") -> Path:
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


PINNED_AND_SCOPED = f"""name: ci
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA}
"""


def test_a_pinned_and_scoped_workflow_passes(lint, tmp_path):
    _workflow(tmp_path, PINNED_AND_SCOPED)

    assert lint.workflow_lint(tmp_path) == []


@pytest.mark.parametrize("ref", [
    "actions/checkout@v4",
    "actions/checkout@main",
    "actions/checkout@3d3c42e",
    "actions/checkout@3D3C42E5AAC5BA805825DA76410C181273BA90B1",
    f"actions/checkout@{SHA}0",
])
def test_an_unpinned_uses_is_reported(lint, tmp_path, ref):
    """A tag, a branch, a short sha and an over-long one are all mutable or malformed."""
    _workflow(tmp_path, PINNED_AND_SCOPED.replace(f"actions/checkout@{SHA}", ref))

    violations = lint.workflow_lint(tmp_path)

    assert len(violations) == 1, violations
    assert "not pinned" in violations[0] and ref in violations[0]


def test_a_trailing_version_comment_does_not_unpin_a_ref(lint, tmp_path):
    """Every pinned ref in this repo carries a `# v7.0.1` comment; it is not part of the ref."""
    _workflow(tmp_path, PINNED_AND_SCOPED.replace(SHA, f"{SHA} # v7.0.1"))

    assert lint.workflow_lint(tmp_path) == []


def test_a_local_action_needs_no_pin(lint, tmp_path):
    """`./` names a directory in this very commit — there is no remote code to re-fetch."""
    _workflow(tmp_path, PINNED_AND_SCOPED.replace(f"actions/checkout@{SHA}",
                                                  "./.github/actions/setup"))

    assert lint.workflow_lint(tmp_path) == []


def test_a_commented_out_uses_is_not_a_violation(lint, tmp_path):
    """A ref in a comment runs nothing, so failing on it would be a false alarm."""
    _workflow(tmp_path, PINNED_AND_SCOPED + "      # uses: actions/stale@v9\n")

    assert lint.workflow_lint(tmp_path) == []


NO_PERMISSIONS = f"""name: ci
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA}
"""


def test_a_workflow_with_no_permissions_anywhere_is_reported(lint, tmp_path):
    _workflow(tmp_path, NO_PERMISSIONS)

    violations = lint.workflow_lint(tmp_path)

    assert len(violations) == 1, violations
    assert "'build'" in violations[0] and "default token scope" in violations[0]


def test_a_job_level_permissions_block_satisfies_the_rule(lint, tmp_path):
    """codeql.yml's real shape: no top-level block, one job that declares its own."""
    _workflow(tmp_path, NO_PERMISSIONS.replace(
        "    runs-on: ubuntu-latest\n",
        "    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n"))

    assert lint.workflow_lint(tmp_path) == []


def test_a_second_job_without_permissions_is_still_reported(lint, tmp_path):
    """One scoped job must not vouch for its unscoped sibling."""
    _workflow(tmp_path, NO_PERMISSIONS.replace(
        "    runs-on: ubuntu-latest\n",
        "    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n"
    ) + "  publish:\n    runs-on: ubuntu-latest\n    steps:\n      - run: true\n")

    violations = lint.workflow_lint(tmp_path)

    assert len(violations) == 1, violations
    assert "'publish'" in violations[0]


def test_a_commented_out_permissions_block_does_not_count(lint, tmp_path):
    """The comment `# permissions:` grants nothing; a substring search would read it as a pass."""
    _workflow(tmp_path, NO_PERMISSIONS.replace("on: [push]\n",
                                               "on: [push]\n# permissions: read-all\n"))

    assert len(lint.workflow_lint(tmp_path)) == 1


def test_a_file_with_no_jobs_block_refuses_to_report_a_pass(lint, tmp_path):
    """A shape the line reader cannot see into must fail, not skip — that is the whole defect."""
    _workflow(tmp_path, "name: ci\non: [push]\n")

    violations = lint.workflow_lint(tmp_path)

    assert len(violations) == 1, violations
    assert "refusing to report a pass" in violations[0]


def test_an_empty_workflow_directory_refuses_to_report_a_pass(lint, tmp_path):
    """A gate that finds nothing has a broken glob, not a clean tree."""
    (tmp_path / ".github" / "workflows").mkdir(parents=True)

    violations = lint.workflow_lint(tmp_path)

    assert len(violations) == 1, violations
    assert "refusing to report a pass" in violations[0]


def test_both_extensions_are_scanned(lint, tmp_path):
    """`.yaml` is as valid as `.yml`, and a glob that misses it is a silent exemption."""
    _workflow(tmp_path, PINNED_AND_SCOPED)
    _workflow(tmp_path, NO_PERMISSIONS, name="other.yaml")

    assert [v for v in lint.workflow_lint(tmp_path) if "other.yaml" in v]


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          check=False)


def test_cli_exits_zero_and_says_what_it_checked(tmp_path):
    _workflow(tmp_path, PINNED_AND_SCOPED)

    done = _run("--root", str(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 workflow(s) checked" in done.stdout


def test_cli_exits_one_and_names_the_invariant(tmp_path):
    _workflow(tmp_path, NO_PERMISSIONS)

    done = _run("--root", str(tmp_path))

    assert done.returncode == 1
    assert "WORKFLOW LINT FAILED" in done.stdout
    assert "pin-actions-to-sha.md" in done.stdout


def test_this_repository_satisfies_the_invariant(root):
    """The tree the lint ships with. `.github/workflows/pylint.yml` failed this until 0.102.0."""
    done = _run("--root", str(root))

    assert done.returncode == 0, done.stdout + done.stderr
