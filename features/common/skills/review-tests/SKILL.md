---
name: review-tests
description: >-
  Use when tests that already exist have to be reviewed against the ruleset and turned into an
  improvement plan — "are these tests any good", "review the tests in this PR", a coverage number
  nobody trusts, a gate nobody has watched fail, or a test file a reviewer flagged. Takes a
  directory, a file list, a diff, or "the tests for X". Not for writing new tests (design-tests).
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [testing, test-quality, review, mutation]
    related_skills: [design-tests]
---

# review-tests

Green is the symptom, not the verdict; this skill exists to judge tests that already exist against
one shared ruleset and hand back an improvement plan, not to write new ones.

This skill and `design-tests` are declared as one group, `SKILL_GROUPS["testing"]`, in
`engine/badger_lib.py` — the same ruleset backs both walks, so asking for either name installs
both.

## Status

This file is a skeleton (work package W0a of the qa-testing plan). The scope/refusal rules, the
pass-by-pass walk, the improvement-plan output shape, and the ruleset itself all land in later
work packages. Today this file exists only to declare the skill's name, its trigger surface, and
its place in the `testing` group, so `design-tests` has a real sibling to travel with from the
first commit.

<!-- MERGE_EXTENSIONS -->

## Gotchas

- Naming only `design-tests` or only `review-tests` still installs both — `expand_skill_groups`
  resolves either name to the full `testing` group, and neither skill can do its job with the
  other absent from disk.
- This file intentionally cites no sibling path yet. The eventual ruleset lands here and
  `design-tests` will read across into it, but adding that citation ahead of the work package that
  writes the ruleset would ship a dangling reference that
  `tests/test_skill_groups.py::test_each_referenced_sibling_exists` is built to catch.
