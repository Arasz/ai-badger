## @stack-adjustments: ts review adjustments

Apply alongside the generic route when the diff touches TypeScript.

- The checklist's ts sections (browser security, TypeScript quality) merge into
  `.ai-badger/skills/code-review-checklist/SKILL.md` at scaffold time — zero tolerance for `any`
  in application code and unsafe `as` casts is the floor, not a preference.
- Read `.ai-badger/skills/review-tests/references/stack-ts-react-browser.md` **when** judging
  tests for browser or Node TypeScript — it carries the ecosystem-specific rule bodies the
  generic passes point at.
- Treat unawaited promises and floating `void`-discarded async calls as error-handling findings:
  an unobserved rejection in a PR is a silent failure path the type system approved.
- Verify route params and external input pass a schema parse **before** reaching business logic
  — a string that merely compiles is unvalidated input.
