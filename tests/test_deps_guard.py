"""Tests for gates/deps_guard.py: no third-party import that requirements.txt does not declare.

CONTRIBUTING says "do not add a third runtime dependency without a very good reason" and nothing
enforced it — which is how the docs came to claim every third-party import was guarded while
`jsonschema` was imported unguarded. The guard classifies every import in scripts/ and features/
as stdlib, first-party or third-party, and fails on a third-party one that is not declared.
"""
from __future__ import annotations

import pytest

DECLARED = "jsonschema>=4.26.0\npyyaml>=6.0.3\n"
ABSENT = "no_such_distribution_anywhere_xyz"
# Installed in CI and in .venv, but never a runtime dependency of this framework.
INSTALLED_BUT_UNDECLARED = "pylint"


def _repo(tmp_path, requirements=DECLARED):
    """A tree the guard can scan: declared dependencies plus the two roots it walks."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "requirements.txt").write_text(requirements, encoding="utf-8")
    (tmp_path / "features").mkdir()
    return tmp_path


def _module(repo, relpath, source):
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture(name="guard")
def _guard(load_script):
    return load_script("gates/deps_guard.py")


class TestClassification:
    """Every import lands in exactly one of stdlib, first-party, third-party."""

    def test_a_declared_third_party_import_passes(self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "scripts/validate.py", "import jsonschema\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_an_undeclared_third_party_import_is_reported_with_file_and_line(
            self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "scripts/thing.py", f"import os\n\nimport {INSTALLED_BUT_UNDECLARED}\n")

        rc = guard.main(["--root", str(repo)])

        out = capsys.readouterr().out
        assert rc == 1
        assert "scripts/thing.py:3" in out
        assert INSTALLED_BUT_UNDECLARED in out

    def test_a_module_that_resolves_nowhere_counts_as_undeclared(self, tmp_path, guard, capsys):
        """An unresolvable name is not proof of innocence — a missing dependency looks like this."""
        repo = _repo(tmp_path)
        _module(repo, "scripts/thing.py", f"from {ABSENT} import helper\n")

        rc = guard.main(["--root", str(repo)])

        out = capsys.readouterr().out
        assert rc == 1
        assert "scripts/thing.py:1" in out
        assert ABSENT in out

    def test_stdlib_imports_are_never_flagged(self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "scripts/thing.py",
                "from __future__ import annotations\n"
                "import os\nimport sys\nimport json\nimport importlib.util\n"
                "from pathlib import Path\nfrom typing import List\n"
                "import xml.etree.ElementTree as ET\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_a_first_party_sibling_import_is_never_flagged(self, tmp_path, guard, capsys):
        """Hooks and skill scripts import siblings and scripts/ modules by bare name."""
        repo = _repo(tmp_path)
        _module(repo, "scripts/badger_lib.py", "VALUE = 1\n")
        _module(repo, "features/common/hooks/debug_log.py", "VALUE = 1\n")
        _module(repo, "features/common/hooks/hook.py",
                "import badger_lib as bl\nimport debug_log\nfrom debug_log import VALUE\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_a_first_party_package_import_is_never_flagged(self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "features/common/hooks/shared/__init__.py", "VALUE = 1\n")
        _module(repo, "features/common/hooks/hook.py", "from shared import VALUE\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out


class TestWhatTheWalkSees:
    """The repo hides imports inside functions and try: blocks deliberately; both count."""

    def test_a_function_level_import_is_seen(self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "scripts/thing.py",
                f"def run():\n    import {INSTALLED_BUT_UNDECLARED}\n    return "
                f"{INSTALLED_BUT_UNDECLARED}\n")

        rc = guard.main(["--root", str(repo)])

        out = capsys.readouterr().out
        assert rc == 1
        assert "scripts/thing.py:2" in out

    def test_a_try_block_import_is_seen(self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "scripts/thing.py",
                f"try:\n    import {ABSENT}\nexcept ImportError:\n    {ABSENT} = None\n")

        rc = guard.main(["--root", str(repo)])

        out = capsys.readouterr().out
        assert rc == 1
        assert "scripts/thing.py:2" in out

    def test_a_file_is_parsed_and_never_executed(self, tmp_path, guard, capsys):
        """A module with a top-level side effect must not run — the guard reads the AST."""
        repo = _repo(tmp_path)
        _module(repo, "scripts/thing.py",
                "import sys\n\nraise RuntimeError('deps_guard imported this module')\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_a_syntactically_invalid_file_is_reported_not_crashed_on(
            self, tmp_path, guard, capsys):
        repo = _repo(tmp_path)
        _module(repo, "scripts/broken.py", "def (:\n")

        rc = guard.main(["--root", str(repo)])

        out = capsys.readouterr().out
        assert rc == 1
        assert "scripts/broken.py" in out
        assert "parse" in out.lower() or "syntax" in out.lower()


class TestDeclarations:
    """requirements.txt names distributions; source imports modules. They are not the same word."""

    def test_a_distribution_whose_import_name_differs_is_recognised(self, tmp_path, guard, capsys):
        """`pyyaml` is declared; `import yaml` is what the code writes."""
        repo = _repo(tmp_path)
        _module(repo, "features/common/hooks/hook.py", "import yaml\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_version_specifiers_extras_and_comments_are_stripped(self, tmp_path, guard, capsys):
        repo = _repo(tmp_path, requirements=(
            "# Runtime dependencies.\n\n"
            "jsonschema[format-nongpl]>=4.26.0,<5  # validation\n"
            "PyYAML >= 6.0.3 ; python_version >= '3.8'\n"))
        _module(repo, "scripts/thing.py", "import jsonschema\nimport yaml\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_the_import_name_of_an_uninstalled_distribution_is_still_known(
            self, tmp_path, guard, monkeypatch, capsys):
        """pyyaml is optional: the guard must give the same verdict where it is not installed."""
        monkeypatch.setattr(guard, "_metadata_modules", lambda distribution: set())
        repo = _repo(tmp_path)
        _module(repo, "features/common/hooks/hook.py", "import yaml\n")

        assert guard.main(["--root", str(repo)]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_an_import_declared_nowhere_fails_even_when_a_sibling_is_declared(
            self, tmp_path, guard):
        repo = _repo(tmp_path, requirements="jsonschema>=4.26.0\n")
        _module(repo, "scripts/thing.py", "import jsonschema\nimport yaml\n")

        assert guard.main(["--root", str(repo)]) == 1

    def test_a_missing_requirements_file_fails_loudly(self, tmp_path, guard, capsys):
        """No declarations file means nothing is declared — that is a finding, not a free pass."""
        repo = _repo(tmp_path)
        (repo / "scripts" / "requirements.txt").unlink()
        _module(repo, "scripts/thing.py", "import jsonschema\n")

        rc = guard.main(["--root", str(repo)])

        assert rc == 1
        assert "requirements.txt" in capsys.readouterr().out


def test_the_real_repository_passes(root, guard, capsys):
    """If this fails, the repo grew an undeclared dependency — declare it, don't relax the gate."""
    rc = guard.main(["--root", str(root)])

    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASS" in out
