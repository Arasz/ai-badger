"""An explicitly empty `--skills` means "unchanged", not "none" (issue #129).

`--skills ""` collapses to an empty list indistinguishable from "no skills wanted"; the CLI
recovers the previously scaffolded set from the manifest instead of treating it as an
instruction to unlink every discovery symlink.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config

SCRIPT = "features/common/skills/welcome-ai-badger/scripts/scaffold.py"


def _run(scaffold, config_path, target, root, skills_arg):
    return scaffold.main(["--config", str(config_path), "--target", str(target),
                          "--root", str(root), "--skills", skills_arg, "--no-install"])


def test_an_empty_skills_flag_relinks_the_previously_scaffolded_set(
        tmp_path, load_script, root, capsys):
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, "task,prompt-markers") == 0
    capsys.readouterr()
    assert _run(scaffold, config_path, target, root, "") == 0

    for name in ("task", "prompt-markers"):
        link = target / ".claude" / "skills" / name
        assert link.is_symlink()
        assert link.resolve() == (target / ".ai-badger" / "skills" / name).resolve()


def test_reusing_the_manifest_set_is_stated_on_stdout(tmp_path, load_script, root, capsys):
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, "task,prompt-markers") == 0
    capsys.readouterr()
    assert _run(scaffold, config_path, target, root, "") == 0

    out = capsys.readouterr().out
    assert "--skills" in out
    assert "manifest" in out
    assert "2" in out


def test_an_empty_skills_flag_on_a_fresh_target_still_exits_zero(
        tmp_path, load_script, root):
    """Lock: a fresh target has no manifest to recover from, so the run still exits 0."""
    scaffold = load_script(SCRIPT)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config()), encoding="utf-8")
    target = tmp_path / "proj"
    target.mkdir()

    assert _run(scaffold, config_path, target, root, "") == 0
    assert not (target / ".ai-badger" / "skills").exists()
