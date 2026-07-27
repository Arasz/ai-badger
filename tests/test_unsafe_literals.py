"""Tests for scripts/unsafe_literals.py: the shared outbound-content guard.

Both paths that move content between a project and the framework use this: the inbound
learned-skill sync (which already did) and feed-badger's outbound PR (which did not — review
F-24/security I4). The rule that makes a finding safe to print is that `pattern` is always a
label from a closed vocabulary and no scanned byte ever reaches the return value.
"""
from __future__ import annotations

# Obviously fake, but shaped like the patterns the scanner recognises.
FAKE_GITHUB_TOKEN = "ghp_FAKEnotarealtoken" + "0" * 19
FAKE_PROVIDER_KEY = "sk-FAKEnotarealkey" + "1" * 20


def _mod(load_script):
    return load_script("scripts/unsafe_literals.py")


def test_a_clean_tree_produces_no_findings(tmp_path, load_script):
    lit = _mod(load_script)
    (tmp_path / "SKILL.md").write_text("# a skill\n\nNothing secret here.\n", encoding="utf-8")

    assert lit.scan_tree(tmp_path) == []


def test_a_token_shaped_literal_is_found_and_labelled(tmp_path, load_script):
    lit = _mod(load_script)
    (tmp_path / "SKILL.md").write_text(f"token: {FAKE_GITHUB_TOKEN}\n", encoding="utf-8")

    findings = lit.scan_tree(tmp_path)

    # One line can match more than one shape; every finding names the file and a known label.
    assert {f["file"] for f in findings} == {"SKILL.md"}
    assert {f["pattern"] for f in findings} <= lit.UNSAFE_LITERAL_LABELS
    assert "github token" in {f["pattern"] for f in findings}


def test_no_scanned_byte_reaches_the_finding(tmp_path, load_script):
    """A finding is printed and logged; the matched text must never travel with it."""
    lit = _mod(load_script)
    (tmp_path / "conf.env").write_text(f"api_key = {FAKE_PROVIDER_KEY}\n", encoding="utf-8")

    findings = lit.scan_tree(tmp_path)

    assert findings
    for finding in findings:
        assert set(finding) == {"file", "pattern"}
        assert FAKE_PROVIDER_KEY not in repr(finding)


def test_scan_paths_accepts_a_mix_of_files_and_directories(tmp_path, load_script):
    lit = _mod(load_script)
    (tmp_path / "loose.md").write_text(f"{FAKE_GITHUB_TOKEN}\n", encoding="utf-8")
    nested = tmp_path / "skills" / "thing"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("clean\n", encoding="utf-8")
    (nested / "notes.md").write_text(f"{FAKE_PROVIDER_KEY}\n", encoding="utf-8")

    findings = lit.scan_paths(tmp_path, ["loose.md", "skills/thing"])

    assert sorted(f["file"] for f in findings) == ["loose.md", "skills/thing/notes.md"]


def test_scan_paths_reports_relative_to_the_root(tmp_path, load_script):
    lit = _mod(load_script)
    nested = tmp_path / "features" / "common"
    nested.mkdir(parents=True)
    (nested / "x.md").write_text(f"{FAKE_GITHUB_TOKEN}\n", encoding="utf-8")

    findings = lit.scan_paths(tmp_path, ["features/common/x.md"])

    assert findings[0]["file"] == "features/common/x.md"


def test_a_path_that_does_not_exist_is_skipped_not_raised(tmp_path, load_script):
    lit = _mod(load_script)

    assert lit.scan_paths(tmp_path, ["nope.md"]) == []


def test_a_file_over_the_size_cap_is_skipped(tmp_path, load_script, monkeypatch):
    lit = _mod(load_script)
    monkeypatch.setattr(lit, "LITERAL_SCAN_MAX_BYTES", 10)
    (tmp_path / "big.md").write_text(f"{FAKE_GITHUB_TOKEN}\n" * 100, encoding="utf-8")

    assert lit.scan_tree(tmp_path) == []


def test_symlinks_are_not_followed(tmp_path, load_script):
    lit = _mod(load_script)
    outside = tmp_path / "outside.md"
    outside.write_text(f"{FAKE_GITHUB_TOKEN}\n", encoding="utf-8")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "link.md").symlink_to(outside)

    assert lit.scan_tree(tree) == []


def test_the_label_vocabulary_is_closed(load_script):
    lit = _mod(load_script)

    assert lit.UNSAFE_LITERAL_LABELS == frozenset(
        label for label, _ in lit.UNSAFE_LITERAL_PATTERNS)


def test_learned_skills_sync_uses_the_shared_scanner(tmp_path, load_script):
    """The inbound path keeps working through the extracted module, not a second copy."""
    sync = load_script("features/common/hooks/learned_skills_sync.py")
    lit = _mod(load_script)
    (tmp_path / "SKILL.md").write_text(f"{FAKE_GITHUB_TOKEN}\n", encoding="utf-8")

    findings = sync.scan_for_unsafe_literals(tmp_path)

    assert [f["pattern"] for f in findings] == [lit.scan_tree(tmp_path)[0]["pattern"]]
    assert sync.UNSAFE_LITERAL_LABELS == lit.UNSAFE_LITERAL_LABELS
