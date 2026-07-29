"""``load_script`` must name modules by dotted repo-relative path, not an ``aib_`` prefix.

mutmut's trampoline dispatches a mutant by matching a function's ``__module__``
against the dotted name it derives from the file's location (path separators become
dots, the ``.py`` suffix drops — see ``mutmut.utils.format_utils.get_mutant_name``).
A prefix like ``aib_bm25`` can never match ``features.common.retrieval.bm25``, so
every mutant silently reports "no tests" and the run measures 0.00 mutations/second
— a symptom that points at mutmut, not at this fixture. See issue #148.
"""
from __future__ import annotations


def test_load_script_names_module_by_dotted_repo_relative_path(load_script):
    module = load_script("features/common/retrieval/tokenizer.py")
    assert module.__name__ == "features.common.retrieval.tokenizer"


def test_load_script_dotted_name_has_no_aib_prefix(load_script):
    module = load_script("features/common/retrieval/bm25.py")
    assert not module.__name__.startswith("aib_")
