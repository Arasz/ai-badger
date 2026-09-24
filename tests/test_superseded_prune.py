"""L3-5: `outputHash` lets prune tell an edited hashes_source output from an untouched one.

`hash` on a `hashes_source` entry (templates, adjustments) is the framework SOURCE's hash
(ADR-0006), which never matches the written, rendered output — so before `outputHash`, every
such output looked "edited here" and could never be pruned, and the note blamed the project
for an edit it never made.
"""
from __future__ import annotations

import json

from scaffold_helpers import _config
from conftest import _test_write

COPILOT_INSTRUCTIONS = ".github/copilot-instructions.md"


def _scaffolded(make_scaffolder, config, skills=("task",)):
    scaf = make_scaffolder(config=config, skills=list(skills))
    return make_scaffolder.target, scaf.run(generated_at="2026-07-30T00:00:00Z")


def test_an_unedited_hashes_source_output_is_pruned_when_its_stack_leaves(make_scaffolder):
    """The gate: an unedited template output must actually be removed, not kept forever."""
    config = _config(stacks=["python"], agents=["claude", "copilot"])
    target, _ = _scaffolded(make_scaffolder, config)
    assert (target / COPILOT_INSTRUCTIONS).is_file()

    _, result = _scaffolded(make_scaffolder, _config(stacks=["python"], agents=["claude"]))

    assert not (target / COPILOT_INSTRUCTIONS).exists(), result["notes"]
    assert any("copilot-instructions" in n and "no longer in config.stacks" in n
               for n in result["notes"]), result["notes"]


def test_an_edited_hashes_source_output_is_kept_and_reported(make_scaffolder):
    config = _config(stacks=["python"], agents=["claude", "copilot"])
    target, _ = _scaffolded(make_scaffolder, config)
    edited = target / COPILOT_INSTRUCTIONS
    _test_write(edited, "# ours now\n", encoding="utf-8")

    _, result = _scaffolded(make_scaffolder, _config(stacks=["python"], agents=["claude"]))

    assert edited.read_text(encoding="utf-8") == "# ours now\n"
    assert any("copilot-instructions" in n and "was edited here" in n for n in result["notes"])


def test_hashes_source_entries_record_an_output_hash(load_script, make_scaffolder):
    """outputHash is version-stamp-normalized (#206): a rendered template's body carries
    "Scaffolded by ai-badger <version>", and a raw byte hash would churn on every version
    bump alone, which `gates/scaffold_freshness_guard.py` is built to treat as a non-change."""
    bl = load_script("engine/badger_lib.py")
    target, result = _scaffolded(
        make_scaffolder, _config(stacks=["python"], agents=["claude", "copilot"]))

    entry = next(e for e in result["manifest"]["entries"] if e["target"] == COPILOT_INSTRUCTIONS)
    assert entry["outputHash"] == bl.content_hash_ignoring_version_stamp(
        target / COPILOT_INSTRUCTIONS)
    assert entry["hash"] != entry["outputHash"], "hash must stay the SOURCE hash (ADR-0006)"


def test_an_older_manifest_without_output_hash_is_never_pruned_and_not_blamed(make_scaffolder):
    """AC3: an entry from before outputHash existed is 'unknown', not 'edited'."""
    target, _ = _scaffolded(
        make_scaffolder, _config(stacks=["python"], agents=["claude", "copilot"]))
    manifest_path = target / ".ai-badger" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        entry.pop("outputHash", None)
    _test_write(manifest_path, json.dumps(manifest), encoding="utf-8")

    _, result = _scaffolded(make_scaffolder, _config(stacks=["python"], agents=["claude"]))

    assert (target / COPILOT_INSTRUCTIONS).is_file()
    assert not any("was edited here" in n and "copilot-instructions" in n
                   for n in result["notes"]), result["notes"]
