"""Behaviour of review-flow's review_diff.py: diff hunk map and lint ingest."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "features/common/skills/review-flow/scripts/review_diff.py"

_spec = importlib.util.spec_from_file_location("review_diff", SCRIPT)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)


def covered(hunks, path):
    return {n for start, end in hunks[path] for n in range(start, end + 1)}


MODIFIED = """\
diff --git a/pkg/a.py b/pkg/a.py
index 111..222 100644
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -1,3 +1,4 @@
 one
+added
 two
 three
@@ -20,3 +21,4 @@ def f():
 ctx
-gone
+new1
+new2
 tail
"""


def test_right_side_line_for_added_and_context():
    hunks = rd.parse_diff(MODIFIED)
    assert covered(hunks, "pkg/a.py") == {1, 2, 3, 4, 21, 22, 23, 24}
    assert rd.in_diff(hunks, "pkg/a.py", 2)
    assert rd.in_diff(hunks, "pkg/a.py", 23)
    assert not rd.in_diff(hunks, "pkg/a.py", 25)


def test_line_outside_every_hunk_is_out_of_diff():
    hunks = rd.parse_diff(MODIFIED)
    assert not rd.in_diff(hunks, "pkg/a.py", 5)
    assert not rd.in_diff(hunks, "pkg/a.py", 20)
    assert not rd.in_diff(hunks, "pkg/a.py", 0)
    assert not rd.in_diff(hunks, "pkg/other.py", 2)


def test_multiple_hunks_each_get_a_range():
    hunks = rd.parse_diff(MODIFIED)
    assert hunks["pkg/a.py"] == [(1, 4), (21, 24)]


def test_added_file_covers_every_line():
    text = ("diff --git a/n.py b/n.py\nnew file mode 100644\nindex 000..111\n"
            "--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,3 @@\n+a\n+b\n+c\n")
    hunks = rd.parse_diff(text)
    assert hunks == {"n.py": [(1, 3)]}


def test_renamed_file_maps_to_new_path():
    text = ("diff --git a/old.py b/new.py\nsimilarity index 80%\n"
            "rename from old.py\nrename to new.py\nindex 1..2 100644\n"
            "--- a/old.py\n+++ b/new.py\n@@ -1,2 +1,3 @@\n a\n+b\n c\n")
    hunks = rd.parse_diff(text)
    assert "old.py" not in hunks
    assert covered(hunks, "new.py") == {1, 2, 3}


def test_pure_rename_has_no_right_side_lines():
    text = ("diff --git a/old.py b/new.py\nsimilarity index 100%\n"
            "rename from old.py\nrename to new.py\n")
    hunks = rd.parse_diff(text)
    assert not rd.in_diff(hunks, "new.py", 1)
    assert not rd.in_diff(hunks, "old.py", 1)


def test_deleted_and_binary_have_no_right_side():
    text = ("diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n"
            "index 1..000\n--- a/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
            "diff --git a/img.png b/img.png\nindex 1..2 100644\n"
            "Binary files a/img.png and b/img.png differ\n"
            "diff --git a/keep.py b/keep.py\n--- a/keep.py\n+++ b/keep.py\n"
            "@@ -1 +1 @@\n-x\n+y\n")
    hunks = rd.parse_diff(text)
    assert not rd.in_diff(hunks, "gone.py", 1)
    assert not rd.in_diff(hunks, "img.png", 1)
    assert hunks.get("gone.py", []) == []
    assert hunks.get("img.png", []) == []
    assert rd.in_diff(hunks, "keep.py", 1)


def test_mode_only_change_has_no_right_side():
    text = ("diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
            "diff --git a/k.py b/k.py\n--- a/k.py\n+++ b/k.py\n@@ -1 +1 @@\n-x\n+y\n")
    hunks = rd.parse_diff(text)
    assert not rd.in_diff(hunks, "run.sh", 1)
    assert rd.in_diff(hunks, "k.py", 1)


def test_no_newline_marker_does_not_consume_a_line():
    text = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
            "@@ -1,2 +1,2 @@\n x\n-y\n\\ No newline at end of file\n+z\n"
            "\\ No newline at end of file\n"
            "@@ -10 +10 @@\n-p\n+q\n")
    hunks = rd.parse_diff(text)
    assert hunks["a.txt"] == [(1, 2), (10, 10)]


def test_no_newline_marker_keeps_following_body_line_in_hunk():
    text = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n"
            "@@ -1 +1 @@\n-y\n\\ No newline at end of file\n+++ b/evil.py\n"
            "@@ -9 +9 @@\n-p\n+q\n")
    assert rd.parse_diff(text) == {"a.txt": [(1, 1), (9, 9)]}


def test_single_line_hunk_header_without_count():
    text = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -5 +7 @@\n-x\n+y\n"
    assert rd.parse_diff(text) == {"a": [(7, 7)]}


def test_body_line_starting_with_dashes_is_not_a_header():
    text = ("diff --git a/a.md b/a.md\n--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n"
            "--- not a header\n+++ not a header either\n"
            "@@ -10 +10 @@\n-x\n+y\n")
    assert rd.parse_diff(text) == {"a.md": [(1, 1), (10, 10)]}


def test_empty_text_gives_empty_map():
    assert rd.parse_diff("") == {}


def test_lint_line_maps_to_path_line():
    out = rd.parse_lint("pkg/x.py:12:3: E501 line too long\n", "/repo")
    assert out == [{"path": "pkg/x.py", "line": 12, "col": 3,
                    "message": "E501 line too long", "kind": "style"}]


def test_lint_without_column_has_none_col():
    out = rd.parse_lint("pkg/x.py:12: something\n", "/repo")
    assert out[0]["col"] is None
    assert out[0]["line"] == 12
    assert out[0]["message"] == "something"


def test_lint_windows_path_with_drive_colon():
    out = rd.parse_lint("C:\\repo\\pkg\\x.py:12:3: msg\n", "C:\\repo")
    assert out[0]["path"] == "pkg/x.py"
    assert (out[0]["line"], out[0]["col"], out[0]["message"]) == (12, 3, "msg")


def test_lint_windows_relative_backslash_path():
    out = rd.parse_lint("pkg\\x.py:12:\n", "/repo")
    assert out[0]["path"] == "pkg/x.py"
    assert out[0]["line"] == 12
    assert out[0]["message"] == ""


def test_lint_absolute_posix_path_made_repo_relative():
    out = rd.parse_lint("/repo/pkg/x.py:4:1: m\n", "/repo/")
    assert out[0]["path"] == "pkg/x.py"


def test_lint_dot_slash_prefix_stripped():
    assert rd.parse_lint("./pkg/x.py:4: m\n", "/repo")[0]["path"] == "pkg/x.py"


def test_lint_path_line_inside_message_text_not_misparsed():
    out = rd.parse_lint("a.py:3:1: duplicate of b.py:99:2: here\n", "/repo")
    assert len(out) == 1
    assert out[0]["path"] == "a.py"
    assert out[0]["line"] == 3
    assert out[0]["message"] == "duplicate of b.py:99:2: here"


def test_lint_unmatched_lines_are_skipped_and_counted():
    text = "Checking files...\na.py:1:1: m\n\n---- summary ----\nb.py:2: n\n"
    findings, skipped = rd.parse_lint_counted(text, "/repo")
    assert [f["path"] for f in findings] == ["a.py", "b.py"]
    assert skipped == 2
    assert rd.parse_lint(text, "/repo") == findings


def test_lint_kind_mapping_and_default():
    text = ("a.py:1:1: W0611: Unused import os (unused-import)\n"
            "a.py:2:1: C0114: Missing module docstring (missing-module-docstring)\n"
            "a.py:3:1: E501 line too long\n")
    kinds = [f["kind"] for f in rd.parse_lint(text, "/repo")]
    assert kinds == ["dead_code", "docs", "style"]


# ------------------------------------------------------------------ old side (review round 2)


DELETION_ONLY = """\
diff --git a/pkg/a.py b/pkg/a.py
--- a/pkg/a.py
+++ b/pkg/a.py
@@ -10,2 +9,0 @@ def f():
-gone1
-gone2
"""

ADDED_FILE = """\
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1,5 @@
+1
+2
+3
+4
+5
"""

RENAMED_EDIT = """\
diff --git a/pkg/old.py b/pkg/new.py
similarity index 90%
rename from pkg/old.py
rename to pkg/new.py
--- a/pkg/old.py
+++ b/pkg/new.py
@@ -4,3 +4,3 @@
 keep
-before
+after
 keep
"""


def test_old_side_maps_a_deletion_only_hunk_to_the_deleted_lines():
    hunks = rd.parse_diff(DELETION_ONLY, side="old")
    assert hunks == {"pkg/a.py": [(10, 11)]}
    assert rd.parse_diff(DELETION_ONLY) == {}


def test_old_side_of_an_added_file_changes_no_old_line():
    hunks = rd.parse_diff(ADDED_FILE, side="old")
    assert not any(start <= 50 <= end for start, end in hunks.get("pkg/new.py", ()))
    assert rd.parse_diff(ADDED_FILE) == {"pkg/new.py": [(1, 5)]}


def test_old_side_keys_a_renamed_file_by_its_old_path_and_old_lines():
    assert rd.parse_diff(RENAMED_EDIT, side="old") == {"pkg/old.py": [(4, 6)]}
    assert rd.parse_diff(RENAMED_EDIT) == {"pkg/new.py": [(4, 6)]}
    assert rd.parse_diff(MODIFIED, side="old") == {"pkg/a.py": [(1, 3), (20, 22)]}
