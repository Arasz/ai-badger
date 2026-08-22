# Accessibility enforced by tests

Accessibility is a failing test, not a review checklist item: automated WCAG checks (e.g.
axe-core scans in the end-to-end suite, a Lighthouse accessibility gate on the production
build) run with the test suite and fail the build on any violation. Every view state — lists,
empty states, open dialogs, error pages — is scanned. An accessibility regression is treated
exactly like a functional bug.
