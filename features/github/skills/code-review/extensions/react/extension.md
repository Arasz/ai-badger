## @stack-adjustments: react review adjustments

Apply alongside the generic route when the diff touches React components or hooks.

- The checklist's react phases (component quality, accessibility) merge into
  `.ai-badger/skills/code-review-checklist/SKILL.md` at scaffold time — run Phase 7 accessibility
  checks for every new interactive element, not just the ones a reviewer notices.
- Read `.ai-badger/skills/review-tests/references/stack-ts-react-browser.md` **when** judging
  tests for browser-rendered code — it carries the jsdom/browser-specific rule bodies the generic
  passes point at.
- Weight client-server contract drift (Phase 5) above style when the diff touches both a hook and
  the endpoint it calls: wrong query-key names and mismatched response shapes fail silently.
- Check hydration and server/client component boundaries **when** a component moves between
  rendering contexts — state and browser APIs that worked client-side break at the boundary.
