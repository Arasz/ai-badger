<!-- Managed by ai-badger. Source of truth: .ai-badger/instructions/python.instructions.md. Do not edit this copy by hand; edit the source and re-run welcome-ai-badger. -->

---
description: 'Modern Python conventions.'
applyTo: '**/*.py'
---

# Python

- Target a currently supported CPython; declare it in `pyproject.toml` and keep runtime and CI on the same interpreter.
- Add type hints to every public function signature and run a static type checker (e.g. pyright) as part of the gate; treat type errors as build failures, not warnings.
- Use one tool for both lint and format (e.g. ruff) and run it in CI; do not hand-format or argue style in review.
- Prefer explicit data models with validation at boundaries (e.g. pydantic/dataclasses) over passing loosely-typed dicts through the codebase.
- Guard clauses over deep nesting: validate inputs and return/raise early rather than wrapping the body in conditionals.
- Manage dependencies through the project file and a lockfile; pin for applications, use ranges for libraries, and never `pip install` into the ambient environment.
- Write tests with a single framework (e.g. pytest), keep them isolated and hermetic, and prefer a failing test before the fix.
- Never swallow exceptions with a bare `except:`; catch the narrowest type and re-raise or handle deliberately.
- Prefer standard-library `pathlib`, `dataclasses`, `enum`, and `typing` constructs over hand-rolled equivalents.
