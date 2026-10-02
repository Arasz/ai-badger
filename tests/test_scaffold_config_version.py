"""The config the scaffolder writes must say which framework version wrote it."""
from __future__ import annotations

import json

import pytest


def _config() -> dict:
    """A config carrying a deliberately stale frameworkVersion."""
    return {
        "$schema": "./schemas/config.schema.json",
        "frameworkVersion": "0.1.0",
        "project": {"name": "probe", "summary": "s", "domain": "d"},
        "stacks": ["dotnet"],
        "agents": ["claude"],
        "sourceControl": {"platform": "none", "repoUrl": None, "projectUrl": None},
        "commands": {},
        "personaRouting": [],
        "skillScope": "default",
        "docs": {},
    }


def _scaffold_into(make_scaffolder, config):
    target = make_scaffolder.target
    make_scaffolder(config=config).run(generated_at="2026-07-27T00:00:00Z")
    return json.loads((target / ".ai-badger" / "config.json").read_text(encoding="utf-8"))


def _framework_version(root) -> str:
    return json.loads((root / "index.json").read_text(encoding="utf-8"))["frameworkVersion"]


class TestScaffoldStampsFrameworkVersion:
    """config.frameworkVersion means 'the version that generated this' — so it must be true."""

    def test_the_written_config_carries_the_current_framework_version(self, root, make_scaffolder):
        written = _scaffold_into(make_scaffolder, _config())

        assert written["frameworkVersion"] == _framework_version(root)

    def test_a_stale_incoming_version_is_replaced_not_preserved(self, make_scaffolder):
        """Copying 0.1.0 through is what let a real project claim 0.18.1 for nine releases."""
        written = _scaffold_into(make_scaffolder, _config())

        assert written["frameworkVersion"] != "0.1.0"

    def test_the_callers_config_dict_is_not_mutated(self, make_scaffolder):
        """The scaffolder owns its output copy, not the dict it was handed."""
        config = _config()

        _scaffold_into(make_scaffolder, config)

        assert config["frameworkVersion"] == "0.1.0"

    def test_every_other_config_key_survives_the_stamp(self, make_scaffolder):
        config = _config()

        written = _scaffold_into(make_scaffolder, config)

        for key, value in config.items():
            if key != "frameworkVersion":
                assert written[key] == value, key


def _prior_config(target, config):
    (target / ".ai-badger").mkdir(parents=True, exist_ok=True)
    (target / ".ai-badger" / "config.json").write_text(json.dumps(config), encoding="utf-8")


class TestRescaffoldKeepsTheDataPolicyLock:
    """A welcome re-run proposes a config without `dataPolicy`; the lock on disk must survive it."""

    def test_a_prior_lock_is_carried_into_a_config_that_lacks_it(self, make_scaffolder):
        _prior_config(make_scaffolder.target, {**_config(), "dataPolicy": "local-only"})

        result = make_scaffolder(config=_config()).run(generated_at="2026-07-27T00:00:00Z")

        written = json.loads((make_scaffolder.target / ".ai-badger" / "config.json")
                             .read_text(encoding="utf-8"))
        assert written["dataPolicy"] == "local-only"
        assert [note for note in result["notes"] if "dataPolicy" in note]

    @pytest.mark.parametrize("raw", ['{"dataPolicy": "local-only",\n<<<<<<< HEAD\n', "[]"])
    def test_an_unparsable_prior_config_keeps_egress_locked(self, make_scaffolder, raw):
        (make_scaffolder.target / ".ai-badger").mkdir(parents=True, exist_ok=True)
        (make_scaffolder.target / ".ai-badger" / "config.json").write_text(raw, encoding="utf-8")

        result = make_scaffolder(config=_config()).run(generated_at="2026-07-27T00:00:00Z")

        written = json.loads((make_scaffolder.target / ".ai-badger" / "config.json")
                             .read_text(encoding="utf-8"))
        assert written["dataPolicy"] == "local-only"
        assert [note for note in result["notes"] if "dataPolicy" in note]

    def test_an_invalid_prior_value_is_carried_as_the_valid_lock(self, make_scaffolder):
        _prior_config(make_scaffolder.target, {**_config(), "dataPolicy": "bogus"})

        written = _scaffold_into(make_scaffolder, _config())

        assert written["dataPolicy"] == "local-only"

    def test_no_prior_lock_adds_none(self, make_scaffolder):
        _prior_config(make_scaffolder.target, _config())

        written = _scaffold_into(make_scaffolder, _config())

        assert "dataPolicy" not in written


class TestRescaffoldKeepsTheAllowlist:
    """The object form carries an `allowHosts` list: a valid one survives a re-run verbatim."""

    POLICY = {"mode": "local-only", "allowHosts": ["decider.corp.example", "Other.Corp.Example."]}

    def test_a_valid_object_form_is_kept_verbatim(self, make_scaffolder):
        _prior_config(make_scaffolder.target, {**_config(), "dataPolicy": self.POLICY})

        written = _scaffold_into(make_scaffolder, _config())

        assert written["dataPolicy"] == self.POLICY

    @pytest.mark.parametrize("policy", [
        {"mode": "local-only", "allowHosts": ["*.corp.example"]},
        {"mode": "open", "allowHosts": ["decider.corp.example"]},
        {"mode": "local-only", "allowHosts": ["decider.corp.example"], "extra": 1},
        {"mode": "local-only", "allowHosts": "decider.corp.example"},
    ], ids=["wildcard", "other-mode", "unknown-key", "not-a-list"])
    def test_an_invalid_object_form_is_written_back_as_the_string_lock(self, make_scaffolder,
                                                                       policy):
        _prior_config(make_scaffolder.target, {**_config(), "dataPolicy": policy})

        result = make_scaffolder(config=_config()).run(generated_at="2026-07-27T00:00:00Z")

        written = json.loads((make_scaffolder.target / ".ai-badger" / "config.json")
                             .read_text(encoding="utf-8"))
        assert written["dataPolicy"] == "local-only"
        notes = [note for note in result["notes"] if "dataPolicy" in note]
        assert notes and "allowHosts" in notes[0] and "dropped" in notes[0]


def _dropped_note(make_scaffolder, policy):
    """Re-scaffold over a prior *policy*; the written `dataPolicy` and its one dataPolicy note."""
    _prior_config(make_scaffolder.target, {**_config(), "dataPolicy": policy})
    result = make_scaffolder(config=_config()).run(generated_at="2026-07-27T00:00:00Z")
    written = json.loads((make_scaffolder.target / ".ai-badger" / "config.json")
                         .read_text(encoding="utf-8"))
    [note] = [note for note in result["notes"] if "dataPolicy" in note]
    return written["dataPolicy"], note


class TestTheDroppedNoteNamesTheErrorWithoutTheEntry:
    """An invalid object form is written back as `local-only`; its note says what was wrong but
    never repeats an entry, so a host name in a config never reaches the scaffold output."""

    def test_a_duplicate_entry_is_dropped_and_located_without_its_text(self, make_scaffolder):
        policy = {"mode": "local-only", "allowHosts": ["secret.corp.example"] * 2}

        written, note = _dropped_note(make_scaffolder, policy)

        assert written == "local-only"
        assert "dropped" in note and "($.allowHosts)" in note
        assert "secret" not in note

    def test_a_bad_entry_is_located_by_its_index(self, make_scaffolder):
        policy = {"mode": "local-only", "allowHosts": ["decider.corp.example", "*.secret.example"]}

        written, note = _dropped_note(make_scaffolder, policy)

        assert written == "local-only"
        assert "($.allowHosts[1])" in note
        assert "secret" not in note

    def test_an_error_holding_no_entry_text_is_quoted(self, make_scaffolder):
        policy = {"mode": "open", "allowHosts": ["secret.corp.example"]}

        written, note = _dropped_note(make_scaffolder, policy)

        assert written == "local-only"
        assert "($.mode: 'local-only' was expected)" in note
        assert "secret" not in note


@pytest.mark.parametrize("schema", [None, "{not json", '{"properties": {}}'],
                         ids=["missing", "invalid-json", "no-data-policy"])
def test_an_unreadable_schema_drops_the_allowlist_and_keeps_the_lock(make_scaffolder, tmp_path,
                                                                    schema):
    root = tmp_path / "framework"
    (root / "schemas").mkdir(parents=True)
    if schema is not None:
        (root / "schemas" / "config.schema.json").write_text(schema, encoding="utf-8")
    aib = tmp_path / "proj" / ".ai-badger"
    policy = {"mode": "local-only", "allowHosts": ["decider.corp.example"]}
    _prior_config(aib.parent, {**_config(), "dataPolicy": policy})
    notes = []

    written = make_scaffolder.module.write_config(aib, _config(), "9.9.9", notes, root)

    assert written["dataPolicy"] == "local-only"
    assert json.loads((aib / "config.json").read_text(encoding="utf-8"))["dataPolicy"] == \
        "local-only"
    assert [note for note in notes if "schema unreadable, allowlist dropped" in note]
