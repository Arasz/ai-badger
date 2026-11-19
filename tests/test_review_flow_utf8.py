"""Review-flow scripts read child output and write their own as UTF-8 on any locale."""
from __future__ import annotations

import ast
import importlib.util
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "features/common/skills/review-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
UTF8_TEXT = "→ zażółć"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _windows_run(raw: bytes):
    """A subprocess.run double that decodes like Windows: cp1252 unless told otherwise."""
    def run(argv, **kwargs):
        encoding = kwargs.get("encoding") or "cp1252"
        out = raw.decode(encoding, kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")
    return run


def test_gh_runner_decodes_utf8_output_on_a_cp1252_locale(monkeypatch):
    publish = _load("review_publish")
    monkeypatch.setattr(publish.subprocess, "run", _windows_run(UTF8_TEXT.encode("utf-8")))
    assert publish.gh_runner(["api", "x"], None) == UTF8_TEXT


def test_run_git_decodes_utf8_output_on_a_cp1252_locale(monkeypatch):
    cli = _load("review_flow_cli")
    monkeypatch.setattr(cli.subprocess, "run", _windows_run(UTF8_TEXT.encode("utf-8")))
    assert cli.run_git(["git", "log"], ROOT)[1] == UTF8_TEXT


def test_cli_writes_utf8_json_to_a_cp1252_stdout(monkeypatch):
    cli = _load("review_flow_cli")
    sink = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(sink, encoding="cp1252"))
    monkeypatch.setattr(cli, "invoke_verb", lambda verb, arguments: (0, {"note": UTF8_TEXT}))
    assert cli.main(["next", "--json", "{}"]) == 0
    sys.stdout.flush()
    assert UTF8_TEXT in sink.getvalue().decode("utf-8")


def test_every_text_mode_child_process_names_utf8():
    offenders = []
    for path in sorted(SCRIPTS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"run", "Popen", "check_output"}):
                continue
            kwargs = {k.arg: k.value for k in node.keywords}
            text = kwargs.get("text") or kwargs.get("universal_newlines")
            if isinstance(text, ast.Constant) and text.value is True:
                enc = kwargs.get("encoding")
                if not (isinstance(enc, ast.Constant) and enc.value == "utf-8"):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, offenders
