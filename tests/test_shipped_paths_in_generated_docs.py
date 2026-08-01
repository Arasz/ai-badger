"""A path inside a shipped page is live config, not a quotation (#268 review).

`docs/` is exempt from the shipped-paths guard for a stated reason: a changelog entry or an ADR
legitimately quotes a real leaked path as the record of an incident. That reasoning covers prose.

It does not cover the generated review forms now living in `docs/work/`. Their `CONFIG.expectedDir`
is read by the page's own JavaScript and shown to a reviewer as the directory to save into — a
machine-specific value there is not a record of a past leak, it is a live instruction pointing at
somebody else's home directory. #268 shipped two such files past the guard.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "gates/shipped_paths_guard.py"

_spec = importlib.util.spec_from_file_location("shipped_paths_guard", SCRIPT)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


class TestProseInDocsStaysExempt:
    """The original exemption must survive — it exists for a real reason."""

    @pytest.mark.parametrize("rel", [
        "docs/changelog/0.22.0-portability-and-truth.md",
        "docs/adr/0011-engine-tooling-split.md",
        "docs/work/2026-08-01-some-record.md",
        "README.md",
    ])
    def test_a_document_may_quote_a_leaked_path(self, rel):
        assert guard.is_exempt(rel, ())


class TestAGeneratedPageIsNotProse:
    """A `.html`/`.htm` file under docs/ carries executable config, so the exemption stops
    there — both suffixes name the same live-config hazard (#268)."""

    @pytest.mark.parametrize("rel", [
        "docs/work/2026-08-01-post-backlog-review.html",
        "docs/work/2026-08-01-session-decisions-review.html",
        "docs/anything/else.html",
        "docs/anything/else.htm",
    ])
    def test_a_shipped_page_is_checked(self, rel):
        assert not guard.is_exempt(rel, ())

    @pytest.mark.parametrize("rel", [
        "docs/work/2026-08-01-post-backlog-review.html",
        "docs/work/2026-08-01-post-backlog-review.htm",
    ])
    def test_an_explicit_allowlist_entry_still_wins(self, rel):
        """The escape hatch stays usable for a page that genuinely must quote a path."""
        assert guard.is_exempt(rel, (rel,))


class TestATestFixtureStaysExempt:
    """`tests/` keeps its own exemption (test_gates_layout.py) — the docs/-only generated-page
    suffix rule must not reach a fixture just because it happens to end in .html/.htm."""

    @pytest.mark.parametrize("rel", [
        "tests/fixtures/leaked_path.html",
        "tests/fixtures/leaked_path.htm",
    ])
    def test_a_generated_page_suffix_under_tests_stays_exempt(self, rel):
        assert guard.is_exempt(rel, ())


class TestTheRealTreeIsClean:
    """The regression #268 shipped: no tracked page may name a home directory."""

    def test_no_shipped_page_carries_a_machine_specific_path(self, root):
        offenders = []
        for path in sorted(root.glob("docs/**/*.html")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for marker in ("/Users/", "/home/", "C:\\Users\\"):
                if marker in text:
                    offenders.append(f"{path.relative_to(root)} contains {marker!r}")

        assert not offenders, "\n".join(offenders)
