## @stack-adjustments: python review adjustments

Apply alongside the generic route when the diff touches Python.

- Read `.ai-badger/skills/review-tests/references/stack-python.md` **when** judging changed
  pytest tests and the file exists — it is a stub in some catalogs and says so; when it is a
  stub, fall back to the generic passes rather than inventing stack rules.
- Weight fixture isolation and shared-state teardown as correctness findings: a test suite that
  passes only in file order is a non-determinism finding, not a hygiene note.
- Treat unseeded randomness, wall-clock reads, and ambient environment variables in production
  paths as testability findings when no seam exists to control them.
- Run the project's own lint and typecheck from config `commands` **before** approving Phase 1 —
  Python typing drift is invisible to a review that only reads the diff.
