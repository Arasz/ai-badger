---
name: design-tests
description: >-
  Use when tests have to be designed or written for a target — "write tests for X", "add coverage
  here", "what should I test", a new behaviour with no test yet, a bug that needs a reproduction
  test, or a bare "write some tests" with nothing named. Works with a target given or none given.
  Not for judging tests that already exist (review-tests).
version: 1.0.0
author: ai-badger
license: MIT
platforms: [linux, macos, windows]
scope: default
metadata:
  hermes:
    tags: [testing, tdd, test-design, coverage]
    related_skills: [review-tests]
---

# design-tests

A test earns its place by failing under a plausible bug; this skill exists to get a test suite
designed and written to that standard, whether or not the caller can already name what needs
testing.

This skill and `review-tests` are declared as one group, `SKILL_GROUPS["testing"]`, in
`engine/badger_lib.py` — the same ruleset backs both walks, so asking for either name installs
both.

## Status

This file is a skeleton (work package W0a of the qa-testing plan). The Stage 0 target-less
decision tree, the contract/behaviour/oracle stages, the runner-and-isolation guidance, and the
scripts this skill will call all land in later work packages. Today this file exists only to
declare the skill's name, its trigger surface, and its place in the `testing` group, so
`review-tests` has a real sibling to travel with from the first commit.

<!-- MERGE_EXTENSIONS -->

## Gotchas

- Naming only `design-tests` or only `review-tests` still installs both — `expand_skill_groups`
  resolves either name to the full `testing` group, and neither skill can do its job with the
  other absent from disk.
- This file intentionally cites no sibling path. Adding a citation to the other skill ahead of the
  work package that gives it a real target would ship a dangling reference that the catalog guard
  in `tests/test_skill_groups.py` is built to catch — let that guard go red before adding one.
