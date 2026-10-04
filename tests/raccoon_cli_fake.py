"""A scriptable fake `ai-raccoon` for tests/test_raccoon_cli_client.py.

The fixture writes an executable named `ai-raccoon` into a tmp bin directory and puts that
directory first on PATH, with every original PATH entry that holds a real `ai-raccoon`
removed. Behaviour is read from the environment at invocation time, so one fake serves
every exit branch:

- `FAKE_RACCOON_CLI_SCRIPT` — a JSON object keyed `get` / `register` / `default`, each
  mapping to `{"exit": <int>, "stdout": <str>, "stderr": <str>, "sleep": <number>}`.
  A verb key wins when the verb appears in argv; `default` covers the rest.
- `FAKE_RACCOON_CLI_EXIT`, `FAKE_RACCOON_CLI_STDOUT`, `FAKE_RACCOON_CLI_STDERR`,
  `FAKE_RACCOON_CLI_SLEEP` — one-off overrides, present-wins even when empty.

Every invocation appends one `{"argv": [...], "exit": <code>}` JSON line to
`FAKE_RACCOON_CLI_LOG` before it exits. Exit codes in the tests come from project_id's
constants, never literals, so renumbering stays a one-place edit.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

_FAKE_SOURCE = '''#!__PYTHON__
"""Scriptable fake ai-raccoon: behaviour from the environment, one JSON log line per call."""
import json
import os
import sys
import time


def _value(name, fallback):
    if name in os.environ:
        return os.environ[name]
    return fallback


def _rule(argv):
    try:
        rules = json.loads(os.environ.get("FAKE_RACCOON_CLI_SCRIPT") or "{}")
    except ValueError:
        rules = {}
    if not isinstance(rules, dict):
        rules = {}
    for verb in ("get", "register"):
        if verb in argv and isinstance(rules.get(verb), dict):
            return rules[verb]
    return rules.get("default") if isinstance(rules.get("default"), dict) else {}


def main():
    argv = list(sys.argv)
    rule = _rule(argv)
    code = int(_value("FAKE_RACCOON_CLI_EXIT", rule.get("exit", 0)))
    log = os.environ.get("FAKE_RACCOON_CLI_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "exit": code}) + "\\n")
    sys.stdout.write(_value("FAKE_RACCOON_CLI_STDOUT", rule.get("stdout", "")))
    sys.stderr.write(_value("FAKE_RACCOON_CLI_STDERR", rule.get("stderr", "fake-raccoon: warning\\n")))
    sleep = _value("FAKE_RACCOON_CLI_SLEEP", rule.get("sleep"))
    if sleep:
        time.sleep(float(sleep))
    return code


if __name__ == "__main__":
    sys.exit(main())
'''


def _path_without_raccoon() -> list:
    """The current PATH entries that hold no executable named `ai-raccoon`."""
    kept = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry) / "ai-raccoon"
        if candidate.is_file():
            continue
        kept.append(entry)
    return kept


class FakeRaccoon:
    """Handle for scripting and inspecting one installed fake."""

    def __init__(self, exe: Path, log: Path, monkeypatch):
        self.exe = str(exe)
        self.bin_dir = str(exe.parent)
        self.log = log
        self._monkeypatch = monkeypatch

    def script(self, **rules) -> None:
        """Set the per-verb JSON script (`get=...`, `register=...`, `default=...`)."""
        self._monkeypatch.setenv("FAKE_RACCOON_CLI_SCRIPT", json.dumps(rules))

    def env(self, name: str, value) -> None:
        """Set one of the FAKE_RACCOON_CLI_* overrides."""
        self._monkeypatch.setenv(name, str(value))

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in
                self.log.read_text(encoding="utf-8").splitlines()]

    def arcs(self) -> list:
        return [entry["argv"] for entry in self.calls()]


@pytest.fixture
def raccoon_cli_fake(tmp_path, monkeypatch) -> FakeRaccoon:
    """Install the fake on PATH with HOME and the log redirected to tmp."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "ai-raccoon"
    exe.write_text(_FAKE_SOURCE.replace("__PYTHON__", sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    log = tmp_path / "raccoon-cli.log"
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FAKE_RACCOON_CLI_LOG", str(log))
    monkeypatch.delenv("FAKE_RACCOON_CLI_SCRIPT", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), *_path_without_raccoon()]))
    return FakeRaccoon(exe, log, monkeypatch)