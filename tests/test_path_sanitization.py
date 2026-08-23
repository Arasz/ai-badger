"""TDD tests for centralized path and session sanitization."""
from __future__ import annotations

import pytest


@pytest.fixture
def ce(load_script):
    return load_script("features/common/retrieval/context_enrichment.py")


@pytest.fixture
def gate(load_script):
    return load_script("features/common/skills/ai-raccoon-memory/scripts/memory_first_gate.py")


@pytest.fixture
def export_mod(load_script):
    return load_script("features/common/skills/semantica-knowledge-graph/scripts/export_semantica_graph.py")


class TestSanitizePathSegment:
    """Extensive test harness for sanitize_path_segment."""

    @pytest.mark.parametrize(
        "input_val, expected",
        [
            # None and empty
            (None, ""),
            ("", ""),
            # Plain valid strings
            ("abc", "abc"),
            ("ABC123", "ABC123"),
            ("session-1", "session-1"),
            ("session_2", "session_2"),
            ("valid.name", "valid.name"),
            ("abc-123_XYZ.456", "abc-123_XYZ.456"),
            # Dangerous path traversal segments
            (".", "_"),
            ("..", "__"),
            ("...", "..."),
            ("....", "...."),
            # Path separators
            ("a/b", "a_b"),
            ("a\\b", "a_b"),
            ("a/b/c", "a_b_c"),
            ("a\\b\\c", "a_b_c"),
            ("a/../b", "a_.._b"),
            # Windows drive prefixes and colons
            ("C:", "C_"),
            ("C:\\Windows", "C__Windows"),
            ("C:/path/file", "C__path_file"),
            ("sess:123", "sess_123"),
            ("2026-08-23T16:00:00Z", "2026-08-23T16_00_00Z"),
            # Spaces and whitespace
            ("hello world", "hello_world"),
            ("  spaces  ", "__spaces__"),
            ("tab\tnewline\n", "tab_newline_"),
            # Null bytes and control characters
            ("evil\0byte", "evil_byte"),
            ("control\x01\x1fchar", "control__char"),
            # Special shell / filesystem characters
            ("foo*bar?baz", "foo_bar_baz"),
            ("foo\"bar'baz", "foo_bar_baz"),
            ("foo<bar>baz|qux", "foo_bar_baz_qux"),
            ("foo$bar`baz`", "foo_bar_baz_"),
            ("foo;bar&baz", "foo_bar_baz"),
            # Unicode / non-ASCII characters
            ("zażółć gęślą jaźń", "za_____g__l__ja__"),
            ("café-1", "caf_-1"),
            ("日本語", "___"),
            ("emoji🚀test", "emoji_test"),
            # Leading and trailing dots and dashes
            (".hidden", ".hidden"),
            ("..hidden", "..hidden"),
            ("trailing.", "trailing."),
            ("-leading", "-leading"),
            ("_leading", "_leading"),
        ],
    )
    def test_sanitize_path_segment_rules(self, ce, input_val, expected):
        assert ce.sanitize_path_segment(input_val) == expected

    def test_single_function_used_across_modules(self, ce, gate, export_mod, load_script):
        """Verify that ce, gate, export_mod, and blast_radius all use identical sanitization behavior."""
        blast_guard = load_script(
            "features/common/skills/worktree-agent-isolation/scripts/blast_radius_kill_guard.py"
        )
        samples = [
            None,
            "",
            ".",
            "..",
            "...",
            "a/b",
            "C:\\foo:bar",
            "sess:123 a",
            "evil\0name",
            "emoji🌟sess",
            "2026-08-23T16:00:00Z",
            "café-1",
            "日本語",
        ]
        for s in samples:
            expected = ce.sanitize_path_segment(s)
            assert ce._safe_session(s) == expected
            assert gate._safe_session(s) == expected
            assert export_mod._sanitize_segment(s or "") == (expected if s else "")
            assert blast_guard._safe_session(s) == expected
