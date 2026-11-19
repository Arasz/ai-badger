"""The recorded review-flow dry run keeps its rendered summary comment and the reviewed commit."""
import re
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "docs" / "work" / "2026-11-18-review-flow-demo.md"
SUMMARY_MARKER = re.compile(r"<!-- ai-badger-review:summary v1[^>]*-->")
COMMIT_SHA = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")


def _text() -> str:
    assert DEMO.is_file(), f"demo record missing: {DEMO}"
    return DEMO.read_text(encoding="utf-8")


def test_demo_holds_the_rendered_summary_marker():
    assert SUMMARY_MARKER.search(_text())


def test_demo_names_a_full_commit_sha():
    assert COMMIT_SHA.search(_text())


def test_summary_marker_sits_beside_the_reviewed_commit():
    text = _text()
    marker = SUMMARY_MARKER.search(text)
    assert marker is not None
    reviewed = re.search(r"Reviewed commit: `([0-9a-f]{40})`", text[marker.end():])
    assert reviewed is not None, "summary body must state the reviewed commit after its marker"
